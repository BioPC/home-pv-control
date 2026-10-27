"""Pure v1.6 capacity memory, SOC-band learning and bounded taper allowances."""

from dataclasses import replace
from .state import BatteryResult, BatteryMemory, TaperBand, PendingProbe, ProbeBattery
from .observations import available, numeric
from ..inverter.generic_number import js_round

FAILURE = (0, 30, 60, 300)
CONTAMINATION = (0, 0, 30, 60, 120, 300)
BANDS = (
    (92, "90-92", 0.80),
    (94, "92-94", 0.65),
    (96, "94-96", 0.50),
    (98, "96-98", 0.35),
    (100, "98-100", 0.18),
)


def band_for(soc):
    return next(
        ((key, fraction) for upper, key, fraction in BANDS if 90 <= soc < upper), None
    )


def charge(power):
    return max(0, -power) if power is not None else 0.0


def put_band(memory, band):
    bands = {b.key: b for b in memory.bands}
    bands[band.key] = band
    return replace(memory, bands=tuple(bands[k] for k in sorted(bands)))


def get_band(memory, key):
    return next((b for b in memory.bands if b.key == key), TaperBand(key))


def prepare(snapshot, memories, telemetry):
    clock = snapshot.clock
    deadband = max(1, snapshot.policy.settings.pv_adjust_deadband)
    memories = dict(memories)
    for index, memory in tuple(memories.items()):
        age = clock.age(memory.max_updated, durable=True)
        if age is None or age > 1800:
            memory = replace(memory, max_charge_w=None, max_updated=None)
        valid = []
        for band in memory.bands:
            ages = [
                a
                for a in (
                    clock.age(band.last_seen, durable=True),
                    clock.age(band.last_probe, durable=True),
                )
                if a is not None
            ]
            if ages and min(ages) <= 172800:
                valid.append(band)
        memories[index] = replace(memory, bands=tuple(valid))
    pending = snapshot.memory.pending_probe
    if pending is None:
        return memories, None, False
    age = clock.age(pending.accepted)
    interrupted = age is None
    if interrupted or age > 180:
        for before in pending.batteries:
            memory = memories.get(before.index, BatteryMemory(before.index))
            band = get_band(memory, before.band)
            band = replace(
                band,
                result="interrupted" if interrupted else "timeout",
                last_probe=clock,
                requires_recovery=True if interrupted else band.requires_recovery,
                failure_baseline_w=before.charging_w
                if interrupted
                else band.failure_baseline_w,
                failure_until=clock.shift(30) if interrupted else band.failure_until,
            )
            memories[before.index] = put_band(memory, band)
        return memories, None, interrupted
    if age < 10:
        return memories, pending, False
    by_index = {t.index: t for t in telemetry}
    step = max(1, pending.step_w)
    export_increase = max(
        0, max(0, -(snapshot.policy.grid.value or 0)) - max(0, pending.export_before_w)
    )
    unsafe = export_increase >= max(deadband, step * 0.5)
    matches = export_increase <= step * 1.75 + deadband
    still = []
    for before in pending.batteries:
        memory = memories.get(before.index, BatteryMemory(before.index))
        band = get_band(memory, before.band)
        t = by_index.get(before.index)
        fresh = bool(
            t
            and t.usable
            and before.power_updated_at_utc is not None
            and t.power_updated_at_utc is not None
            and t.power_updated_at_utc > before.power_updated_at_utc
            and t.power_updated_at_utc >= pending.accepted.utc
        )
        if not unsafe and not fresh:
            still.append(before)
            continue
        current = charge(t.power_w) if t else 0
        full = (
            fresh
            and t.charging_cutoff is not None
            and t.soc is not None
            and t.soc >= t.charging_cutoff
        )
        expected = max(1, before.expected_share_w)
        delta = max(0, current - before.charging_w)
        ratio = max(0, min(1.5, delta / expected))
        plausible = expected * 2 + deadband
        old = max(
            current,
            band.ceiling_w
            if band.ceiling_w is not None
            else before.effective_ceiling_w or current,
        )
        if full:
            band = replace(
                band,
                result="full",
                last_probe=clock,
                last_seen=clock if unsafe else band.last_seen,
                failure_count=0,
                failure_until=None,
                requires_recovery=False,
                failure_baseline_w=0,
                contamination_count=0,
                contamination_until=None,
            )
        elif (
            unsafe
            and not (fresh and matches and delta <= plausible and ratio <= 0.35)
            or not unsafe
            and delta > plausible
        ):
            count = band.contamination_count + 1
            duration = CONTAMINATION[min(len(CONTAMINATION) - 1, count)]
            band = replace(
                band,
                result="export-contaminated" if unsafe else "contaminated",
                last_probe=clock,
                last_seen=clock,
                contamination_count=count,
                contamination_until=clock.shift(
                    max(duration, clock.remaining(band.contamination_until))
                )
                if duration > 0
                else band.contamination_until,
                expected_share_w=js_round(expected),
                export_increase_w=js_round(export_increase),
                absorbed_ratio=band.absorbed_ratio if unsafe else js_round(ratio, 2),
                contaminated_delta_w=band.contaminated_delta_w
                if unsafe
                else js_round(delta),
                contaminated_limit_w=band.contaminated_limit_w
                if unsafe
                else js_round(plausible),
            )
        else:
            good = ratio >= 0.65
            poor = ratio <= 0.35
            ceiling = (
                max(old, current + max(deadband, js_round(delta * 0.35)))
                if good
                else current
                if poor
                else max(current, js_round(old * 0.75 + current * 0.25))
            )
            failures = (
                band.failure_count + 1 if poor else 0 if good else band.failure_count
            )
            band = replace(
                band,
                ceiling_w=max(0, ceiling),
                samples=band.samples + 1,
                last_probe=clock,
                last_seen=clock,
                result="limited-export-confirmed"
                if unsafe
                else "absorbed"
                if good
                else "limited"
                if poor
                else "partial",
                absorbed_ratio=js_round(ratio, 2),
                expected_share_w=js_round(expected),
                export_increase_w=js_round(export_increase),
                contamination_count=0,
                contamination_until=None,
                failure_count=failures,
                failure_until=clock.shift(FAILURE[min(3, failures)])
                if poor
                else None
                if good
                else band.failure_until,
                failure_baseline_w=current if poor or good else band.failure_baseline_w,
                requires_recovery=failures >= 3
                if poor
                else False
                if good
                else band.requires_recovery,
                idle_until=clock.shift(max(1800, clock.remaining(band.idle_until)))
                if poor and before.idle_startup
                else None
                if good
                else band.idle_until,
            )
        memories[before.index] = put_band(memory, band)
    return memories, replace(pending, batteries=tuple(still)) if still else None, False


def headroom(snapshot, health, memories, pending):
    clock = snapshot.clock
    settings = snapshot.policy.settings
    deadband = max(1, settings.pv_adjust_deadband)
    combined = sum(
        c.full_w
        for c in snapshot.policy.controllers
        if c.participating and c.eligible and c.available
    )
    rows = []
    by_index = {t.index: t for t in health["telemetry"]}
    pending_indexes = {b.index for b in pending.batteries} if pending else set()
    remembered = snapshot.policy.memory.price_limiting
    if remembered is None:
        remembered = (
            snapshot.policy.market.value is not None
            and snapshot.policy.market.value <= settings.pv_limiting_price
        )
    if snapshot.policy.market.value is not None:
        if snapshot.policy.market.value <= settings.pv_limiting_price:
            remembered = True
        elif (
            snapshot.policy.market.value
            > settings.pv_limiting_price + settings.battery_price_hysteresis
        ):
            remembered = False
    price_context = (
        remembered
        or snapshot.policy.all_in.value is not None
        and snapshot.policy.all_in.value <= 0
    )
    charge_context = (
        health["control"]
        and health["execution"].lower() in ("charge", "charge pv")
        and price_context
    )
    total = 0.0
    full_count = 0
    usable = 0
    normal = 0.0
    taper = 0.0
    charging_any = False
    for i in health["order"] or tuple(range(1, health["count"] + 1)):
        t = by_index[i]
        memory = memories.get(i, BatteryMemory(i))
        max_entity = health["entities"].get(f"number.marstek_m{i}_max_charge_power")
        live = numeric(max_entity)
        present = available(max_entity)
        live_positive = present and live is not None and live > 0
        if live_positive:
            memory = replace(memory, max_charge_w=live, max_updated=clock)
        age = clock.age(memory.max_updated, durable=True)
        cached = (
            not present
            and memory.max_charge_w is not None
            and memory.max_charge_w > 0
            and age is not None
            and age <= 1800
        )
        maximum = live if live_positive else memory.max_charge_w if cached else 0.0
        max_source = (
            "live"
            if live_positive
            else "live-zero"
            if present and live == 0
            else "invalid"
            if present
            else "remembered"
            if cached
            else "unknown"
        )
        memories[i] = memory
        row = BatteryResult(
            t,
            "uncertain"
            if (t.power_w is not None and not t.power_fresh)
            or (t.soc is not None and not t.soc_fresh)
            else "unavailable",
            maximum,
            max_source,
        )
        if not t.telemetry_usable:
            rows.append(replace(row, exclusion="telemetry unavailable or stale"))
            continue
        if not t.control_enabled:
            rows.append(
                replace(
                    row,
                    status="control-disabled",
                    exclusion="RS485 control must be enable",
                )
            )
            continue
        usable += 1
        total += t.power_w
        if t.soc >= t.charging_cutoff:
            full_count += 1
            rows.append(
                replace(row, status="full", exclusion="charging cutoff reached")
            )
            continue
        current = charge(t.power_w)
        if t.soc < 90 and maximum > 0:
            raw = max(0, maximum - current)
            near = current >= maximum * 0.95 or raw < deadband
            status = (
                "charging"
                if t.power_w < 0
                else "discharging"
                if t.power_w >= 25
                else "empty"
                if t.soc <= t.discharging_cutoff
                else "idle"
            )
            charging_any |= t.power_w < 0
            row = replace(
                row,
                status=status,
                charging=t.power_w < 0,
                effective_ceiling_w=js_round(maximum),
                raw_headroom_w=raw,
                eligible=not near,
                normal_headroom_w=raw if not near else 0,
                exclusion="at maximum charge power"
                if near
                else "below 90% charge headroom available",
            )
            if not near:
                normal += raw
        elif t.power_w < 0:
            charging_any = True
            row = replace(row, status="charging", charging=True)
            selected = band_for(t.soc) if maximum > 0 else None
            if maximum <= 0:
                rows.append(
                    replace(row, exclusion="max charge power unknown, zero or invalid")
                )
                continue
            if selected:
                key, fraction = selected
                band = get_band(memory, key)
                tolerance = max(15, js_round(maximum * 0.02))
                stable = (
                    band.stable_since
                    if band.last_power_w is not None
                    and abs(current - band.last_power_w) <= tolerance
                    and band.stable_since is not None
                    else clock
                )
                stable_age = clock.age(stable) or 0.0
                recovery_threshold = max(deadband, js_round(maximum * 0.03))
                if (
                    band.requires_recovery
                    and current >= band.failure_baseline_w + recovery_threshold
                ):
                    band = replace(
                        band,
                        requires_recovery=False,
                        failure_count=0,
                        failure_until=None,
                    )
                fail_locked = (
                    clock.remaining(band.failure_until) > 0 or band.requires_recovery
                )
                contaminated = clock.remaining(band.contamination_until) > 0
                learned = (
                    max(current, band.ceiling_w)
                    if band.ceiling_w is not None
                    else max(current, js_round(maximum * fraction))
                )
                cap = max(
                    deadband,
                    js_round(
                        maximum
                        * (0.05 if t.soc >= 98 else 0.10 if t.soc >= 94 else 0.15)
                    ),
                )
                generic = max(
                    deadband,
                    min(
                        js_round(maximum * 0.08),
                        js_round(
                            (combined or maximum) * 0.04 / max(1, health["count"])
                        ),
                    ),
                )
                awaiting = i in pending_indexes
                probe = (
                    stable_age >= 60
                    and current < maximum - deadband
                    and not awaiting
                    and not fail_locked
                    and not contaminated
                )
                confirmed = (
                    max(0, min(maximum, learned) - current)
                    if band.ceiling_w is not None and not fail_locked
                    else 0.0
                )
                allowance = (
                    0.0
                    if awaiting or fail_locked
                    else min(
                        max(0, maximum - current),
                        max(
                            confirmed,
                            min(maximum - current, min(cap, generic)) if probe else 0,
                        ),
                        cap,
                    )
                )
                effective = min(maximum, current + allowance)
                near = current >= effective * 0.95 or allowance < deadband
                band = replace(
                    band,
                    stable_since=stable,
                    last_power_w=current,
                    last_seen=clock,
                    ceiling_w=max(current, min(maximum, band.ceiling_w))
                    if band.ceiling_w is not None
                    else None,
                )
                memories[i] = put_band(memory, band)
                row = replace(
                    row,
                    status="tapering",
                    band=key,
                    effective_ceiling_w=js_round(effective),
                    raw_headroom_w=js_round(allowance),
                    eligible=not near,
                    taper_allowance_w=js_round(allowance),
                    learned_ceiling_w=js_round(learned)
                    if band.ceiling_w is not None
                    else None,
                    probe_eligible=probe,
                    awaiting_confirmation=awaiting,
                    step_cap_w=js_round(cap),
                    stable_seconds=js_round(stable_age),
                    exclusion="per-battery taper allowance available"
                    if not near
                    else "learned taper ceiling reached or probe blocked",
                )
                if not near:
                    taper += row.raw_headroom_w
            else:
                raw = max(0, maximum - current)
                near = current >= maximum * 0.95 or raw < deadband
                row = replace(
                    row,
                    effective_ceiling_w=js_round(maximum),
                    raw_headroom_w=raw,
                    normal_headroom_w=raw if not near else 0,
                    eligible=not near,
                )
                if not near:
                    normal += raw
        elif t.power_w >= 25:
            row = replace(row, status="discharging", exclusion="battery discharging")
        elif t.soc >= 90 and maximum > 0 and charge_context:
            selected = band_for(t.soc)
            row = replace(row, status="idle")
            if selected:
                key, fraction = selected
                band = get_band(memory, key)
                awaiting = i in pending_indexes
                if not awaiting:
                    band = replace(band, last_seen=clock)
                locked = (
                    band.requires_recovery
                    or clock.remaining(band.idle_until) > 0
                    or clock.remaining(band.failure_until) > 0
                    or clock.remaining(band.contamination_until) > 0
                )
                if not awaiting and not locked:
                    base = max(
                        deadband,
                        min(
                            js_round(maximum * 0.08),
                            js_round(
                                (combined or maximum) * 0.04 / max(1, health["count"])
                            ),
                        ),
                    )
                    scaled = max(deadband, js_round(base * fraction))
                    learned = (
                        min(band.ceiling_w, scaled)
                        if band.ceiling_w is not None and band.ceiling_w > 0
                        else scaled
                    )
                    allowance = min(maximum, max(deadband, js_round(learned)))
                    cap = max(
                        deadband,
                        js_round(
                            maximum
                            * (0.05 if t.soc >= 98 else 0.10 if t.soc >= 94 else 0.15)
                        ),
                    )
                    allowance = min(allowance, cap)
                    eligible = allowance >= deadband
                    row = replace(
                        row,
                        band=key,
                        effective_ceiling_w=allowance,
                        raw_headroom_w=allowance,
                        taper_allowance_w=allowance,
                        step_cap_w=cap,
                        probe_eligible=eligible,
                        idle_startup=eligible,
                        eligible=eligible,
                        exclusion="idle high-SOC startup probe available",
                    )
                    if eligible:
                        taper += allowance
                else:
                    row = replace(
                        row,
                        band=key,
                        awaiting_confirmation=False,
                        exclusion="idle taper probe blocked",
                    )
                memories[i] = put_band(memory, band)
        else:
            row = replace(
                row,
                status="empty" if t.soc <= t.discharging_cutoff else "idle",
                exclusion="max charge power unknown, zero or invalid"
                if maximum <= 0
                else "battery not charging",
            )
        rows.append(row)
    return (
        tuple(rows),
        memories,
        dict(
            total=total,
            charging=charging_any,
            normal=normal,
            taper=taper,
            usable=usable,
            full=usable > 0 and full_count == usable,
        ),
    )


def probe_from_accepted(event_id, clock, step_w, grid_w, rows):
    eligible = [r for r in rows if r.eligible and r.raw_headroom_w > 0]
    taper = [r for r in eligible if r.telemetry.soc >= 90 and r.taper_allowance_w > 0]
    all_headroom = sum(r.raw_headroom_w for r in eligible)
    allowance = sum(r.taper_allowance_w for r in taper)
    if not taper or all_headroom <= 0 or allowance <= 0 or step_w <= 0:
        return None
    step = min(step_w, step_w * allowance / all_headroom)
    return PendingProbe(
        event_id,
        clock,
        step,
        max(0, -grid_w),
        tuple(
            ProbeBattery(
                r.telemetry.index,
                r.band,
                charge(r.telemetry.power_w),
                r.effective_ceiling_w or r.max_charge_w,
                step * r.taper_allowance_w / allowance,
                r.telemetry.power_updated_at_utc,
                r.idle_startup,
            )
            for r in taper
        ),
    )
