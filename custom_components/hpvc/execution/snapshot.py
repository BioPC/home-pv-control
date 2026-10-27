"""Authoritative immutable policy restrictions from durable execution records."""

from .models import (
    ExecutionSnapshot,
    Lane,
    OperationState,
    ObligationState,
    MaintenanceState,
    OwnershipState,
)
from .settling import SettlingOutcome


def build_execution_snapshot(
    ledger,
    controllers,
    clock,
    facts,
    *,
    settling=None,
    boot_clock=None,
    hbc_restore_pending=False,
    override_recovery=False,
):
    terminal = (
        OperationState.VERIFIED,
        OperationState.RETIRED,
        OperationState.SUPERSEDED,
        OperationState.PREPARED,
    )
    operations = tuple(op for op in ledger.operations if op.state not in terminal)
    obligations = tuple(
        o for o in ledger.restore_obligations if o.state != ObligationState.VERIFIED
    )
    ownership_known = ledger.ownership.state in (
        OwnershipState.READY_DISABLED,
        OwnershipState.NATIVE_OWNER_COMMITTED,
        OwnershipState.NATIVE_ACTIVE,
    )
    maintenance = ledger.maintenance.state not in (
        MaintenanceState.IDLE,
        MaintenanceState.COMPLETE,
        MaintenanceState.CANCELLED,
    )
    unknown = any(
        op.state
        in (
            OperationState.UNKNOWN,
            OperationState.RECOVERY_REQUIRED,
            OperationState.SERVICE_FAILED,
            OperationState.VERIFICATION_FAILED,
            OperationState.OPEN_LOOP,
        )
        for op in operations
    )
    # Awaiting verification is pending work, not automatically a global unknown failure.
    recovery = (
        facts.plant_uid != ledger.plant_uid
        or not ownership_known
        or bool(obligations)
        or maintenance
        or unknown
        or override_recovery
        or ledger.hbc_override.phase.value == "recovery_unknown_previous"
        or ledger.hbc_override.phase.value != "inactive"
        and ledger.hbc_override.forced_write_issued is None
    )
    settling_active = bool(
        settling
        and settling.outcome in (SettlingOutcome.WAITING, SettlingOutcome.UNKNOWN)
    )
    timed_out = bool(settling and settling.outcome == SettlingOutcome.TIMED_OUT)
    frozen = {op.controller_uid for op in operations if op.lane == Lane.INVERTER} | {
        o.controller_uid for o in obligations
    }
    if settling_active:
        matched = next(
            (
                op
                for op in ledger.operations
                if op.operation_id == settling.state.operation_id
            ),
            None,
        )
        if matched and matched.state not in (
            OperationState.VERIFIED,
            OperationState.RETIRED,
        ):
            frozen.add(matched.controller_uid)
        elif matched is None:
            recovery = True
    by_uid = {c.uid: c for c in controllers}
    replaced_or_removed = any(
        op.controller_uid not in by_uid
        or (
            by_uid[op.controller_uid].configuration_signature
            and by_uid[op.controller_uid].configuration_signature
            != op.configuration_signature
        )
        for op in operations
        if op.lane == Lane.INVERTER
    )
    if replaced_or_removed:
        recovery = True
    eligible = tuple(
        c.uid
        for c in controllers
        if c.participating
        and c.eligible
        and c.available
        and c.uid not in frozen
        and not recovery
        and not maintenance
    )
    last = facts.last_inverter
    cooldown = 0.0
    delta = None
    last_at = None
    failed = False
    if last:
        age = clock.age(last.accepted)
        if age is None:
            # Persisted acceptance owns an absolute deadline after restart; loading
            # memory never starts a new cooldown. Unresolved execution stays blocked.
            durable_age = clock.utc - last.accepted.utc
            if durable_age < 0:
                recovery = True
                eligible = ()
                age = 0.0
            else:
                age = durable_age
        age = age or 0.0
        cooldown = (
            clock.utc + max(0, last.cooldown_seconds - age)
            if age < last.cooldown_seconds
            else 0.0
        )
        delta = sum(
            c.target_w - (c.before_w if c.before_w is not None else c.target_w)
            for c in last.controllers
        )
        last_at = clock.utc - age
        failed = any(
            o.event_id == last.event_id
            and o.kind in ("service_failed", "verification_failed", "outcome_unknown")
            for o in facts.outcomes
        )
    pending = any(op.lane == Lane.INVERTER for op in operations)
    hbc_pending = any(op.lane == Lane.HBC for op in operations)
    reasons = ["physical_writes_hard_off"]
    if not ownership_known:
        reasons.append("ownership_unresolved")
    if unknown:
        reasons.append("unknown_physical_outcome")
    if obligations:
        reasons.append("restore_obligations")
    if maintenance:
        reasons.append("maintenance")
    if override_recovery:
        reasons.append("override_recovery")
    if pending:
        reasons.append("pending_verification")
    return ExecutionSnapshot(
        unresolved_operation_ids=tuple(
            op.operation_id for op in operations if op.lane == Lane.INVERTER
        ),
        unresolved_hbc_operation_ids=tuple(
            op.operation_id for op in operations if op.lane == Lane.HBC
        ),
        unresolved_obligation_ids=tuple(o.obligation_id for o in obligations),
        recovery_required=bool(recovery),
        blocked_reason=";".join(reasons),
        pending_verification=pending,
        settling=settling_active,
        settling_timed_out=timed_out,
        frozen_controller_uids=tuple(sorted(frozen)),
        write_eligible_uids=eligible,
        maintenance_active=maintenance,
        hbc_restore_pending=hbc_restore_pending
        or hbc_pending
        or ledger.hbc_override.phase.value != "inactive",
        cooldown_until_utc=cooldown,
        last_command_delta_w=delta,
        last_command_at_utc=last_at,
        last_command_verification_failed=failed,
        pending_action=last.action if last and pending else None,
        pending_since_utc=last_at if pending else None,
        write_lock_reason="waiting for previous inverter write confirmation"
        if pending
        else "waiting for post-write PV settling"
        if settling_active
        else "",
        ownership_state=ledger.ownership.state.value,
        accepted_event_id=last.event_id if last else None,
        accepted_controller_uids=tuple(c.controller_uid for c in last.controllers)
        if last
        else (),
        authorization_block_reasons=tuple(reasons),
    )
