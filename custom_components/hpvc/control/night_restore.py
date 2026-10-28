"""Source 120s entry / 30s continuous recovery, expressed as state transitions."""

from dataclasses import dataclass, replace
from ..codec import Record
from .models import NightRestoreState, Quality
from ..inverter.base import fingerprint


def fresh(observation, now, *, max_age=180):
    return (
        observation.quality == Quality.VALID
        and observation.value is not None
        and observation.reported_at_utc is not None
        and observation.reported_at_utc > 0
        and -60 <= now - observation.reported_at_utc <= max_age
    )


@dataclass(frozen=True)
class NightTransition(Record):
    state: NightRestoreState
    fleet_signature: str
    pending: bool
    suspended: bool
    full_observed: bool
    proof_invalidated: bool
    maintenance_candidate: bool


def transition(
    state,
    pv,
    *,
    now,
    threshold,
    controllers=(),
    sun_below_horizon=False,
    execution=None,
    previous_fleet_signature=None,
    tolerance_w=25,
):
    signature = fingerprint(
        [(c.uid, c.configuration_signature, c.full_w, c.minimum_w) for c in controllers]
    )
    usable = fresh(pv, now)
    low = usable and pv.value <= threshold
    recovering = usable and pv.value > max(25, threshold + 15)
    active = state.active
    entry = state.entry_candidate_since_utc
    recovery = state.recovery_candidate_since_utc
    since = state.active_since_utc
    if active:
        if recovering:
            recovery = now if recovery is None else recovery
            if now - recovery >= 30:
                active = False
                entry = None
                recovery = None
                since = None
        else:
            recovery = None
    else:
        recovery = None
        if low:
            entry = now if entry is None else entry
            if now - entry >= 120:
                active = True
                since = now
        elif not usable and entry is not None:
            if now - entry >= 120:
                if sun_below_horizon:
                    active = True
                    since = now
                else:
                    entry = None
        else:
            entry = None
    tolerance = max(1, tolerance_w)
    full = bool(controllers) and all(
        c.available
        and c.independently_verifiable
        and not c.open_loop
        and c.current_w is not None
        and c.current_w >= c.full_w - tolerance
        for c in controllers
    )
    partial = any(
        c.available
        and c.independently_verifiable
        and not c.open_loop
        and c.current_w is not None
        and c.current_w < c.full_w - tolerance
        for c in controllers
    )
    pending_work = execution is not None and (
        execution.pending_verification
        or execution.settling
        or execution.unresolved_operation_ids
        or execution.unresolved_obligation_ids
        or execution.recovery_required
        or execution.maintenance_active
    )
    invalid = (
        not active
        or partial
        or bool(pending_work)
        or (
            state.full_output_proof_reference is not None
            and signature != previous_fleet_signature
        )
    )
    proof = None if invalid else state.full_output_proof_reference
    state = replace(
        state,
        active=active,
        active_since_utc=since,
        entry_candidate_since_utc=entry,
        recovery_candidate_since_utc=recovery,
        full_output_proof_reference=proof,
    )
    pending = not active and entry is not None
    unavailable = any(not c.available for c in controllers) or not controllers
    suspended = (active and (full or unavailable)) or (
        pending and (not usable or unavailable)
    )
    maintenance = (
        active
        and (full or proof is not None)
        and not pending_work
        and not (execution and execution.hbc_restore_pending)
    )
    return NightTransition(
        state, signature, pending, suspended, full, invalid, maintenance
    )


def after_restart(memory):
    return replace(
        memory,
        night=replace(
            memory.night,
            entry_candidate_since_utc=None,
            recovery_candidate_since_utc=None,
        ),
    )
