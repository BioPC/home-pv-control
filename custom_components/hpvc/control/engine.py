"""Pure v1.6 policy, allocation and adapter representation. No dispatcher."""

from dataclasses import replace
from .decisions import (
    PolicyController,
    PolicySnapshot,
    PolicyIntent,
    PolicyResult,
    AllocationOutcome,
    Action,
)
from .models import RepresentedPlan, AllocationResult
from .night_restore import transition, fresh
from .priorities import PolicyFacts, arbitrate
from .allocation import allocate
from ..execution.models import ExecutionSnapshot, CommandBatch
from ..inverter.base import AdapterView
from ..inverter.manager import FleetSnapshot
from ..inverter.generic_number import GenericNumberAdapter, js_round
from ..inverter.generic_action import GenericActionAdapter
from ..inverter.enphase import EnphaseAdapter
from ..inverter.hoymiles import HoymilesAdapter


def controllers_from_fleet(fleet: FleetSnapshot) -> tuple[PolicyController, ...]:
    rows = []
    for row in fleet.effective:
        v = row.view
        if v.operating_range.full_w <= 0:
            continue
        current = v.observation.limit.value if v.available else None
        if current is None and v.available:
            current = v.assumed_limit_w
        step = v.capabilities.step or 0
        if v.configuration.unit.value == "Percent":
            step = step / 100 * v.operating_range.full_w
        rows.append(
            PolicyController(
                row.uid,
                current,
                v.operating_range.full_w,
                v.operating_range.minimum_w,
                v.available,
                row.participating,
                v.valid,
                v.independently_verifiable,
                step,
                v.configuration_signature,
                not v.supports_verification,
            )
        )
    return tuple(rows)


def evaluate(
    snapshot: PolicySnapshot, *, views: tuple[AdapterView, ...] = ()
) -> PolicyResult:
    s = snapshot.settings
    ex = snapshot.execution
    memory = snapshot.memory
    now = snapshot.now
    configured = tuple(c for c in snapshot.controllers if c.participating)
    rows = tuple(
        c for c in configured if c.available and c.eligible and c.current_w is not None
    )
    full = sum(c.full_w for c in rows)
    minimum = sum(c.minimum_w for c in rows)
    current = sum(c.current_w for c in rows)
    night = transition(
        memory.night,
        snapshot.pv,
        now=now,
        threshold=s.pv_night_restore_power,
        controllers=configured,
        sun_below_horizon=snapshot.sun_below_horizon,
        execution=ex,
        previous_fleet_signature=memory.night_fleet_signature,
        tolerance_w=max(1, s.pv_adjust_deadband),
    )
    pv_ok = fresh(snapshot.pv, now)
    grid_ok = fresh(snapshot.grid, now)
    market_ok = fresh(snapshot.market, now, max_age=7200)
    allin_ok = fresh(snapshot.all_in, now, max_age=7200)
    grid = snapshot.grid.value if grid_ok else 0.0
    pv = snapshot.pv.value if pv_ok else 0.0
    market = snapshot.market.value if market_ok else 0.0
    any_below = full - current >= max(s.pv_adjust_deadband, 1e-7)
    remembered = memory.price_limiting
    if remembered is None:
        remembered = market_ok and (
            market <= s.pv_limiting_price
            or (
                market <= s.pv_limiting_price + s.battery_price_hysteresis and any_below
            )
        )
    if market_ok:
        if market <= s.pv_limiting_price:
            remembered = True
        elif market > s.pv_limiting_price + s.battery_price_hysteresis:
            remembered = False
    wants_min = bool(
        (allin_ok and snapshot.all_in.value <= 0)
        or ex.hbc_restore_pending
        or snapshot.hbc.override_restore_pending
    )
    price_active = bool(market_ok and remembered and not wants_min)
    cooldown = ex.cooldown_until_utc > now
    at_min = bool(rows) and all(abs(c.current_w - c.minimum_w) < 1 for c in rows)
    disable_restore = bool(
        not snapshot.enabled
        and not snapshot.automatic_safety_pause
        and (
            full - current > max(1, s.pv_adjust_deadband)
            or any(not c.available for c in configured)
            or ex.hbc_restore_pending
            or ex.pending_verification
            or ex.unresolved_obligation_ids
            or any(not c.independently_verifiable for c in configured)
        )
    )
    can_change = bool(disable_restore or wants_min or not cooldown)
    lock = bool(
        ex.pending_verification
        or ex.settling
        or ex.unresolved_operation_ids
        or (
            ex.write_eligible_uids is not None
            and any(c.uid not in ex.write_eligible_uids for c in rows)
        )
    )
    import_active = any_below and grid > s.import_restore_threshold
    degraded = 0 < len(rows) < len(configured)
    if lock:
        raw = (
            current + max(0, grid - s.export_stop_threshold)
            if import_active
            else current
        )
    else:
        baseline = (
            max(current, pv)
            if import_active
            else current
            if degraded or ex.settling_timed_out
            else pv
        )
        raw = (
            full
            if not any_below and grid > s.import_restore_threshold
            else baseline + grid - s.export_stop_threshold
        )
    undamped = js_round(max(minimum, min(full, raw)))
    calculated = undamped
    large = False
    reversal = False
    delta = undamped - current
    span = max(1, full - minimum)
    large_threshold = max(s.pv_adjust_deadband * 8, span * 0.15)
    if not lock and price_active and abs(delta) >= large_threshold:
        direction = 1 if delta > 0 else -1 if delta < 0 else 0
        magnitude = min(abs(delta) * 0.65, max(s.pv_adjust_deadband * 4, span * 0.35))
        large = magnitude < abs(delta) - 1e-9
        last = ex.last_command_delta_w
        stamp = ex.last_command_at_utc
        recent = (
            last is not None
            and abs(last) >= large_threshold
            and last * direction < 0
            and stamp is not None
            and 0 <= now - stamp <= max(60, s.cooldown_seconds * 6)
            and not ex.last_command_verification_failed
        )
        if recent and magnitude > max(s.pv_adjust_deadband * 4, span * 0.2):
            magnitude = max(s.pv_adjust_deadband * 4, span * 0.2)
            reversal = True
        calculated = js_round(max(minimum, min(full, current + direction * magnitude)))
    if night.suspended:
        calculated = js_round(current)
        import_active = False
    since = memory.release_requested_since_utc
    since = (now if since is None else since) if snapshot.external_release else None
    age = 0 if since is None else max(0, now - since)
    facts = PolicyFacts(
        current,
        full,
        minimum,
        calculated,
        any_below,
        price_active,
        wants_min,
        at_min,
        can_change,
        import_active,
        lock,
        disable_restore,
        market_ok,
        market,
        grid,
        pv,
        night.pending,
        night.state.active,
        night.suspended,
        age,
    )
    arbitration = arbitrate(snapshot, facts)
    action = arbitration.action
    status = arbitration.status
    reason = arbitration.reason
    target = js_round(arbitration.target_w)
    blocked = False
    restrictions = []
    if snapshot.automatic_safety_pause:
        blocked = True
        status = "Safety paused"
        reason = "Automatic safety pause; holding existing PV limits"
    elif not snapshot.enabled and not disable_restore:
        blocked = True
        status = "Disabled"
        reason = "Home PV Control is disabled"
    elif (
        not disable_restore
        and not night.suspended
        and not (
            grid_ok
            and market_ok
            and allin_ok
            and (pv_ok or night.state.active or night.pending)
        )
    ):
        blocked = True
        status = "Waiting for inputs"
        reason = "Waiting for live inputs: " + ", ".join(
            label
            for valid, label in [
                (grid_ok, "Grid power sensor"),
                (market_ok, "Market/export price sensor"),
                (allin_ok, "All-in price sensor"),
                (pv_ok, "PV power sensor"),
            ]
            if not valid
        )
    elif not rows and not night.state.active and not night.pending:
        blocked = True
        status = (
            "No PV inverters available" if not configured else "Inverters unavailable"
        )
        reason = (
            "HPVC requires at least one usable PV inverter for control"
            if not configured
            else "Control paused; all configured inverter limit/readback paths are currently unavailable"
        )
    if ex.maintenance_active or (ex.recovery_required and not disable_restore):
        blocked = True
        restrictions.append(
            "maintenance" if ex.maintenance_active else "recovery_required"
        )
        status = "Recovery required"
        reason = "Execution owns unresolved recovery/maintenance state"
    if blocked:
        action = Action.NONE
        target = 0.0
        calculated = None
        price_active = False
        remembered = memory.price_limiting
    if lock:
        restrictions.append("pending_verification_or_settling")
    if ex.unresolved_obligation_ids:
        restrictions.append("restore_obligations")
    if ex.hbc_restore_pending:
        restrictions.append("hbc_restore_pending")
    if action == Action.ADJUST and large:
        reason += (
            f"; large correction staged to {int(js_round(abs(calculated - current)))} W of {int(js_round(abs(delta)))} W requested"
            + (" with first-reversal damping" if reversal else "")
        )
    rebalance = (
        snapshot.rebalance_pending
        and can_change
        and not lock
        and not disable_restore
        and not blocked
    )
    intent = PolicyIntent(
        evaluation_id=snapshot.evaluation_id,
        action=action,
        status=status,
        reason=reason,
        requested_plant_target_w=target,
        calculated_plant_target_w=calculated,
        raw_grid_target_w=raw,
        undamped_target_w=undamped,
        price_limiting=price_active,
        remembered_price_limiting=remembered,
        cooldown_active=False if wants_min else cooldown,
        cooldown_until_utc=ex.cooldown_until_utc,
        import_protection=import_active,
        large_step_damped=large,
        reversal_damped=reversal,
        night_suspended=night.suspended,
        rebalance_requested=rebalance,
        external_release_full_observed=arbitration.release_full_observed,
        external_release_degraded_candidate=arbitration.release_degraded_candidate,
        hbc_negative_override_requested=bool(
            snapshot.enabled
            and allin_ok
            and snapshot.all_in.value <= 0
            and snapshot.hbc.override_entities_present
            and snapshot.hbc.control_enabled
            and snapshot.negative_price_hbc_charge
        ),
        restriction_reasons=tuple(restrictions),
        blocked=blocked,
    )
    new_memory = replace(
        memory,
        price_limiting=remembered,
        negative_minimum=wants_min,
        night=night.state,
        night_fleet_signature=night.fleet_signature,
        release_requested_since_utc=since,
    )
    frozen = set(ex.frozen_controller_uids)
    if ex.write_eligible_uids is not None:
        frozen.update(c.uid for c in rows if c.uid not in ex.write_eligible_uids)
    bypass = lock and import_active and target > current
    allocation = allocate(
        snapshot.evaluation_id,
        target,
        snapshot.controllers,
        frozen_uids=tuple(frozen)
        if bypass or ex.write_eligible_uids is not None
        else (),
        rebalance=rebalance,
        deadband_w=s.pv_adjust_deadband,
    )
    if blocked:
        allocation = AllocationOutcome(
            AllocationResult(snapshot.evaluation_id, target, None),
            tuple(restrictions),
            blocked=True,
        )
    result = PolicyResult(intent, new_memory, allocation)
    return (
        represent(result, views, import_floor=import_active and action == Action.ADJUST)
        if views
        else result
    )


def _adapter(view: AdapterView):
    kind = view.configuration.identity.adapter.value
    return (
        GenericActionAdapter()
        if kind == "generic_action"
        else EnphaseAdapter()
        if kind == "enphase"
        else HoymilesAdapter()
        if kind == "hoymiles"
        else GenericNumberAdapter()
    )


def represent(
    result: PolicyResult, views: tuple[AdapterView, ...], *, import_floor: bool = False
) -> PolicyResult:
    by_uid = {v.configuration.identity.uid: v for v in views}
    targets = []
    reasons = []
    for target in result.allocation.result.controller_targets:
        view = by_uid.get(target.controller_uid)
        if view is None or not view.valid:
            reasons.append("representation_unavailable:" + target.controller_uid)
            continue
        floor = view.observation.limit.value if import_floor else None
        represented = _adapter(view).represent(
            view, target.target_w, import_floor_w=floor
        )
        targets.append(represented)
        if abs(represented.representable_target_w - target.target_w) > 0.001:
            reasons.append("quantization:" + target.controller_uid)
    represented_total = (
        sum(t.representable_target_w for t in targets)
        if len(targets) == len(result.allocation.result.controller_targets)
        else None
    )
    plan = RepresentedPlan(
        result.intent.evaluation_id,
        result.intent.requested_plant_target_w,
        result.allocation.result.allocated_plant_target_w,
        represented_total,
        tuple(targets),
    )
    return replace(result, represented=plan, representation_reasons=tuple(reasons))


def command_batches(
    result: PolicyResult, views: tuple[AdapterView, ...], execution: ExecutionSnapshot
) -> tuple[CommandBatch, ...]:
    """Simulation-only immutable plan composition. Never calls an execution API."""
    if (
        result.intent.blocked
        or result.allocation.blocked
        or result.represented is None
        or execution.recovery_required
        or execution.maintenance_active
        or execution.unresolved_obligation_ids
    ):
        return ()
    if result.intent.action == Action.NONE and not result.allocation.rebalance_applied:
        return ()
    by_uid = {v.configuration.identity.uid: v for v in views}
    plans = []
    for target in result.represented.targets:
        uid = target.controller_uid
        view = by_uid[uid]
        if uid in execution.frozen_controller_uids or (
            execution.write_eligible_uids is not None
            and uid not in execution.write_eligible_uids
        ):
            continue
        if (
            view.observation.limit.value is not None
            and abs(target.representable_target_w - view.observation.limit.value)
            <= 1e-7
        ):
            continue
        if not view.available or not view.configuration.control_enabled:
            continue
        plans.append(
            _adapter(view).build_plan(
                view,
                target,
                batch_id=result.intent.evaluation_id + ":" + uid,
                evaluation_id=result.intent.evaluation_id,
                requested_plant_target_w=result.intent.requested_plant_target_w,
            )
        )
    return tuple(plans)
