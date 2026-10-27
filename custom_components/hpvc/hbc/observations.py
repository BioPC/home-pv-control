"""Raw immutable HBC input normalization and v1.6 tiered battery freshness."""

from dataclasses import replace
from .state import BatteryMemory, BatteryTelemetry
from ..inverter.base import finite


def text(entity):
    return str(entity.state or "").strip() if entity else ""


def available(entity):
    return bool(
        entity and text(entity).lower() not in ("", "unknown", "unavailable", "none")
    )


def numeric(entity):
    return finite(text(entity)) if available(entity) else None


def health(snapshot):
    entities = {e.entity_id: e for e in snapshot.entities}
    clock = snapshot.clock
    now = clock.utc
    strategy = entities.get("input_select.house_battery_strategy")
    execution = entities.get("input_text.house_battery_strategy_active_sub_strategy")
    has_hbc = available(strategy)
    strategy_available = has_hbc and bool(strategy.options)
    count_entity = entities.get("input_number.house_battery_count")
    raw = numeric(count_entity)
    count_valid = (
        not available(count_entity)
        or raw is not None
        and raw.is_integer()
        and 0 <= raw <= 6
    )
    count = (
        (1 if not available(count_entity) else int(raw) if count_valid else 0)
        if snapshot.permission
        else 0
    )
    priority = entities.get("input_number.house_battery_control_prioritize_battery")
    raw_priority = numeric(priority) if available(priority) else 1.0
    priority_valid = (
        not available(priority)
        or raw_priority is not None
        and float(raw_priority).is_integer()
        and raw_priority >= 1
        and (count <= 0 or raw_priority <= count + 1)
    )
    valid = count_valid and priority_valid
    order = list(range(1, count + 1))
    if valid and order:
        rotation = int(raw_priority) - 1
        order = order[rotation:] + order[:rotation]
    elif not valid:
        order = []
    memories = {b.index: b for b in snapshot.memory.batteries}
    telemetry = []
    faults = []
    for i in range(1, count + 1):
        prior = memories.get(i, BatteryMemory(i))
        prefix = f"marstek_m{i}"
        power = entities.get("sensor." + prefix + "_ac_power")
        soc = entities.get("sensor." + prefix + "_battery_state_of_charge")
        charge = entities.get("input_number." + prefix + "_charging_cutoff_capacity")
        discharge = entities.get(
            "input_number." + prefix + "_discharging_cutoff_capacity"
        )
        mode = entities.get("select." + prefix + "_rs485_control_mode")
        p = numeric(power)
        v = numeric(soc)
        v = v if v is not None and 0 <= v <= 100 else None
        ch = numeric(charge)
        di = numeric(discharge)
        live_complete = available(charge) and available(discharge)
        ch_valid = ch is not None and 0 <= ch <= 100
        di_valid = di is not None and 0 <= di <= 100
        live_valid = live_complete and ch_valid and di_valid and di < ch
        # Present malformed values may not be hidden even during a companion helper outage.
        malformed = (
            (available(charge) and not ch_valid)
            or (available(discharge) and not di_valid)
            or (live_complete and not live_valid)
        )
        remembered = (
            not live_complete
            and not malformed
            and prior.charging_cutoff is not None
            and prior.discharging_cutoff is not None
            and 0 <= prior.discharging_cutoff < prior.charging_cutoff <= 100
        )
        if live_valid:
            prior = replace(
                prior, charging_cutoff=ch, discharging_cutoff=di, cutoff_updated=clock
            )
        ch = ch if live_valid else prior.charging_cutoff if remembered else None
        di = di if live_valid else prior.discharging_cutoff if remembered else None
        cutoff = live_valid or remembered

        def age(e, heartbeat=False):
            stamp = (
                (e.heartbeat_at_utc if heartbeat else e.updated_at_utc) if e else None
            )
            return (
                max(0, now - stamp) if stamp is not None and stamp <= now + 60 else None
            )

        pa = age(power)
        sa = age(soc)
        beats = [x for x in (age(power, True), age(soc, True)) if x is not None]
        heartbeat = min(beats) if beats else None
        heartbeat_fresh = heartbeat is not None and heartbeat <= 120
        active = p is not None and abs(p) >= max(
            1, snapshot.policy.settings.pv_adjust_deadband
        )
        power_limit = 120 if active else 300
        power_state = p is not None and pa is not None and pa <= power_limit
        normal_power = p is not None and pa is not None and pa <= 120
        soc_state = v is not None and sa is not None and sa <= 7200
        full_idle = (
            p is not None and v is not None and not active and cutoff and v >= ch
        )
        steady = (
            p is not None
            and v is not None
            and active
            and (heartbeat_fresh or soc_state or pa is not None and pa <= 7200)
        )
        idle = (
            p is not None
            and v is not None
            and not active
            and not full_idle
            and (power_state or heartbeat_fresh or soc_state)
        )
        cross_soc = v is not None and p is not None and (power_state or heartbeat_fresh)
        pf = p is not None and (
            power_state or heartbeat_fresh or steady or idle or full_idle
        )
        sf = v is not None and (
            soc_state or heartbeat_fresh or steady or cross_soc or full_idle
        )
        usable = pf and sf and cutoff
        mode_enabled = text(mode).lower() == "enable"
        freshness = (
            "unavailable"
            if p is None or v is None
            else "heartbeat-confirmed"
            if heartbeat_fresh
            else "cutoff-boundary-idle"
            if full_idle and (not normal_power or not soc_state)
            else "cross-sensor-confirmed"
            if cross_soc and not soc_state
            else "steady-active"
            if steady and not power_state
            else "state-updated"
            if power_state and soc_state
            else "cross-sensor-confirmed"
            if idle
            else "uncertain"
        )
        issues = []
        if not pf:
            issues.append("AC power unavailable" if p is None else "AC power stale")
        if not sf:
            issues.append("SOC unavailable" if v is None else "SOC stale")
        if not cutoff:
            issues.append("cutoff configuration invalid")
        faults.extend(f"M{i} " + issue for issue in issues)
        telemetry.append(
            BatteryTelemetry(
                i,
                v,
                p,
                power.updated_at_utc if power else None,
                ch,
                di,
                cutoff,
                pf,
                sf,
                usable,
                mode_enabled,
                usable and mode_enabled,
                freshness,
                "live" if live_valid else "remembered" if remembered else "unknown",
                tuple(issues),
            )
        )
        memories[i] = prior
    usable_count = sum(t.usable for t in telemetry)
    paused = False
    recovering = False
    healthy_since = snapshot.memory.healthy_since
    if snapshot.permission and strategy_available:
        if count <= 0 or usable_count <= 0:
            paused = True
            healthy_since = None
        elif snapshot.memory.safety_paused:
            healthy_since = healthy_since or clock
            age = clock.age(healthy_since)
            if age is None or age < 60:
                paused = True
                recovering = True
        else:
            healthy_since = None
    else:
        healthy_since = None
    control = (
        snapshot.permission
        and strategy_available
        and available(execution)
        and not paused
        and usable_count > 0
    )
    return dict(
        entities=entities,
        has_hbc=has_hbc,
        strategy_available=strategy_available,
        execution_available=available(execution),
        execution=text(execution),
        count=count,
        valid=valid,
        order=tuple(order),
        telemetry=tuple(telemetry),
        memories=memories,
        paused=paused,
        recovering=recovering,
        healthy_since=healthy_since,
        control=control,
        faults=tuple(faults),
    )
