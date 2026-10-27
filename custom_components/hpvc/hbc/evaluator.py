"""Raw HBC observations to immutable Charge Priority/learning/override proposals."""

from dataclasses import replace
from .state import HbcResult, HbcMemory
from .models import HbcPolicyInput
from .observations import health
from .learning import prepare, headroom
from .override import evaluate_override
from ..control.night_restore import fresh
from ..inverter.generic_number import js_round


def after_restart(memory, clock):
    batteries = []
    for battery in memory.batteries:
        bands = []
        for band in battery.bands:
            interrupted = bool(
                memory.pending_probe
                and any(
                    p.index == battery.index and p.band == band.key
                    for p in memory.pending_probe.batteries
                )
            )
            bands.append(
                replace(
                    band,
                    stable_since=None,
                    last_power_w=None,
                    result="interrupted" if interrupted else band.result,
                    requires_recovery=True if interrupted else band.requires_recovery,
                    failure_until=clock.shift(30)
                    if interrupted
                    else band.failure_until,
                )
            )
        batteries.append(replace(battery, bands=tuple(bands)))
    override = memory.override
    if override.phase != "inactive":
        override = replace(
            override, phase_since=clock, last_retry=None, fault_published=None
        )
    return replace(
        memory,
        boot_id=clock.boot_id,
        batteries=tuple(batteries),
        priority_state="off",
        last_confirmed=None,
        transition_until=None,
        persistent_export_since=None,
        healthy_since=None,
        pending_probe=None,
        override=override,
        interrupted_probe=memory.pending_probe is not None or memory.interrupted_probe,
    )


def evaluate(snapshot):
    clock = snapshot.clock
    p = snapshot.policy
    s = p.settings
    memory = snapshot.memory
    if memory.boot_id and memory.boot_id != clock.boot_id:
        memory = after_restart(memory, clock)
        snapshot = replace(snapshot, memory=memory)
    h = health(snapshot)
    override = evaluate_override(snapshot, h["entities"])
    memories, pending, interrupted = prepare(snapshot, h["memories"], h["telemetry"])
    rows, memories, totals = headroom(snapshot, h, memories, pending)
    available_headroom = totals["normal"] + totals["taper"]
    eligible = [r for r in rows if r.eligible]
    below = [r for r in eligible if r.telemetry.soc < 90]
    taper = [r for r in eligible if r.telemetry.soc >= 90]
    available_controllers = [
        c
        for c in p.controllers
        if c.participating and c.available and c.eligible and c.current_w is not None
    ]
    current = sum(c.current_w for c in available_controllers)
    full = sum(c.full_w for c in available_controllers)
    minimum = sum(c.minimum_w for c in available_controllers)
    deadband = max(1, s.pv_adjust_deadband)
    grid = p.grid.value or 0.0
    market_ok = fresh(p.market, clock.utc, max_age=7200)
    remembered = p.memory.price_limiting
    if remembered is None:
        remembered = market_ok and (
            p.market.value <= s.pv_limiting_price
            or p.market.value <= s.pv_limiting_price + s.battery_price_hysteresis
            and full - current >= max(deadband, 1e-7)
        )
    if market_ok:
        if p.market.value <= s.pv_limiting_price:
            remembered = True
        elif p.market.value > s.pv_limiting_price + s.battery_price_hysteresis:
            remembered = False
    context = market_ok and remembered and not override.minimum_lock
    executing = h["execution_available"] and h["execution"].strip().lower() in (
        "charge",
        "charge pv",
    )
    intent = (
        snapshot.permission
        and executing
        and context
        and not totals["full"]
        and h["valid"]
    )
    requested = intent and h["control"]
    meaningful = bool(eligible) and available_headroom > deadband
    charging_power = max(0, -totals["total"])
    enter = totals["charging"] and charging_power >= 50
    remain = totals["charging"] and charging_power >= 25
    state = memory.priority_state
    previous = state
    confirmed = memory.last_confirmed
    if not requested or totals["usable"] <= 0:
        state = "off"
        confirmed = None
    elif state in ("active", "exit_hold"):
        age = clock.age(confirmed)
        if remain:
            state = "active"
            confirmed = clock
        elif age is not None and age < 20:
            state = "exit_hold"
        elif meaningful:
            state = "waiting"
        else:
            state = "off"
            confirmed = None
    elif enter:
        state = "active"
        confirmed = clock
    elif meaningful:
        state = "waiting"
    else:
        state = "off"
        confirmed = None
    transition = memory.transition_until
    if previous == "active" and not remain and requested:
        transition = clock.shift(15)
    if not requested or remain or state == "off" or clock.remaining(transition) <= 0:
        transition = None
    transition_remaining = clock.remaining(transition)
    engaged = requested and state in ("waiting", "active", "exit_hold")
    release_age = clock.age(snapshot.last_release)
    response = bool(engaged and release_age is not None and release_age < 15)
    response_remaining = max(0, 15 - release_age) if response else 0.0
    excessive = grid < s.export_start_threshold
    export_since = memory.persistent_export_since
    if engaged and excessive:
        if export_since is None or clock.age(export_since) is None:
            export_since = clock
    else:
        export_since = None
    export_age = clock.age(export_since) or 0.0
    fallback = engaged and excessive and export_age >= 30
    suppressed = bool(
        engaged
        and not fallback
        and (
            transition_remaining > 0
            or response
            or remain
            and available_headroom > deadband
        )
    )
    span = max(1, full - minimum)
    threshold = max(deadband * 8, span * 0.15)
    large_cap = max(deadband * 4, span * 0.35)
    reverse_cap = max(deadband * 4, span * 0.2)
    increase = 0.0
    unshaped = 0.0
    cap = 0.0
    large = False
    reversal = False
    target = current
    if engaged and not response and transition_remaining <= 0 and not excessive:
        highest = max((r.telemetry.soc for r in taper), default=0)
        cap = (
            available_headroom
            if below
            else max(
                deadband,
                js_round(
                    full * (0.03 if highest >= 98 else 0.06 if highest >= 95 else 0.10)
                ),
            )
        )
        unshaped = min(available_headroom, max(0, full - current), cap)
        shaped = unshaped
        if unshaped >= threshold:
            shaped = min(unshaped * 0.65, large_cap)
            large = shaped < unshaped - 1e-9
        age = clock.age(snapshot.last_command)
        if (
            snapshot.last_command_delta_w is not None
            and snapshot.last_command_delta_w < 0
            and abs(snapshot.last_command_delta_w) >= threshold
            and age is not None
            and age <= max(60, s.cooldown_seconds * 6)
            and not snapshot.last_command_failed
            and shaped > reverse_cap
        ):
            shaped = reverse_cap
            reversal = True
        increase = max(0, js_round(shaped))
        target = min(full, js_round(current + increase))
    required = bool(
        engaged and not response and not excessive and target >= current + deadband
    )
    solar = (p.pv.value or 0) >= max(deadband, s.pv_min_power_for_control)
    operational = state == "active" and solar
    display = (
        "requested"
        if intent and totals["usable"] <= 0
        else "active"
        if operational
        else "waiting"
        if state in ("waiting", "exit_hold") or state == "active" and not solar
        else "off"
    )
    exit_remaining = (
        max(0, 20 - (clock.age(confirmed) or 0)) if state == "exit_hold" else 0.0
    )
    next_memory = HbcMemory(
        clock.boot_id,
        tuple(memories[k] for k in sorted(memories)),
        state,
        confirmed,
        transition,
        export_since,
        h["paused"],
        h["healthy_since"],
        pending,
        override.memory,
        memory.interrupted_probe or interrupted,
    )
    resolved = HbcPolicyInput(
        available=h["has_hbc"],
        control_enabled=h["control"],
        execution_strategy="Charge PV"
        if executing and h["execution"].lower() == "charge pv"
        else "Charge"
        if executing
        else h["execution"] or None,
        usable_batteries=totals["usable"],
        eligible_headroom_w=available_headroom,
        response_window_active=response,
        transition_settle_active=transition_remaining > 0,
        persistent_export_fallback=bool(fallback),
        suppress_export_limiting=suppressed,
        priority_operational=operational,
        increase_required=required,
        increase_target_w=target,
        taper_release_requested=bool(taper and required),
        override_restore_pending=override.memory.phase != "inactive",
        override_entities_present="input_select.house_battery_strategy" in h["entities"]
        and "input_select.house_battery_strategy_charge_goal" in h["entities"],
        minimum_lock_reason=override.reason if override.minimum_lock else None,
    )
    faults = h["faults"] + (
        () if h["valid"] else ("invalid HBC count/priority configuration",)
    )
    return HbcResult(
        next_memory,
        resolved,
        rows,
        h["order"],
        h["valid"],
        bool(h["control"]),
        bool(h["recovering"]),
        state,
        display,
        totals["normal"],
        totals["taper"],
        totals["total"],
        bool(enter),
        bool(remain),
        bool(engaged),
        increase,
        unshaped,
        cap,
        large,
        reversal,
        response_remaining,
        transition_remaining,
        exit_remaining,
        export_age,
        override,
        faults,
    )
