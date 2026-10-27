"""One final arbitration before allocation/representation. No competing commands."""

from dataclasses import dataclass
from ..codec import Record
from .decisions import Action


@dataclass(frozen=True)
class PolicyFacts(Record):
    current: float
    full: float
    minimum: float
    calculated: float
    any_below_full: bool
    price_active: bool
    wants_minimum: bool
    at_minimum: bool
    can_change: bool
    import_active: bool
    write_lock: bool
    disable_restore: bool
    market_valid: bool
    market: float
    grid: float
    pv: float
    night_pending: bool
    night_active: bool
    night_suspended: bool
    release_age: float


@dataclass(frozen=True)
class Arbitration(Record):
    action: Action
    status: str
    reason: str
    target_w: float
    release_full_observed: bool = False
    release_degraded_candidate: bool = False


def arbitrate(snapshot, f):
    s = snapshot.settings
    ex = snapshot.execution
    hbc = snapshot.hbc
    changed = abs(f.calculated - f.current) >= max(s.pv_adjust_deadband, 1)
    at_full = f.calculated >= f.full - s.pv_adjust_deadband
    at_min = f.calculated <= f.minimum + s.pv_adjust_deadband
    hbc_ready = hbc.ready
    suppressed = (
        hbc_ready
        and hbc.suppress_export_limiting
        and not hbc.persistent_export_fallback
    )
    import_bypass = f.write_lock and f.import_active and f.calculated > f.current
    normal_min = (
        f.can_change
        and not f.write_lock
        and at_min
        and f.market_valid
        and f.price_active
        and f.pv > s.pv_min_power_for_control
        and f.grid < s.export_start_threshold
        and not suppressed
    )
    force_min = (
        not f.night_active and not f.at_minimum and (f.wants_minimum or normal_min)
    )
    export_correction = (
        not f.wants_minimum
        and f.price_active
        and changed
        and f.calculated < f.current
        and f.grid < s.export_start_threshold
        and not suppressed
    )
    charge_increase = (
        f.can_change
        and not f.write_lock
        and not f.wants_minimum
        and not export_correction
        and hbc_ready
        and hbc.increase_required
        and hbc.increase_target_w is not None
    )
    restore = (
        f.any_below_full
        and f.can_change
        and (not f.write_lock or import_bypass)
        and (
            f.night_active
            or (
                not f.wants_minimum
                and (
                    f.market > s.pv_limiting_price + s.battery_price_hysteresis
                    or at_full
                )
            )
        )
    )
    adjust = (
        not at_full
        and not at_min
        and not f.wants_minimum
        and f.market_valid
        and changed
        and f.price_active
        and (f.pv > s.pv_min_power_for_control or f.import_active)
        and f.can_change
        and (not f.write_lock or import_bypass)
        and (f.grid < s.export_start_threshold or f.import_active)
        and not (f.grid < s.export_start_threshold and suppressed)
    )
    negative_reason = hbc.minimum_lock_reason or (
        "Negative all-in protection active: PV is locked at configured inverter minimums; native HBC override entities are not installed, so no HBC strategy is changed."
        if not hbc.override_entities_present
        else "Negative all-in protection active: PV is locked at configured inverter minimums; Enable HBC is off, so no HBC strategy is changed."
        if not hbc.control_enabled
        else "Negative all-in protection active: PV is locked at configured inverter minimums; negative-price HBC charging is disabled, so no HBC strategy is changed."
        if not snapshot.negative_price_hbc_charge
        else "Negative all-in protection active."
    )
    negative_reason += " Inverter limits remain locked at configured minimums."
    action = Action.NONE
    target = f.current
    status = "Idle"
    reason = "No action"
    release_full = False
    degraded = False
    if f.disable_restore:
        status = "Disabling - restoring"
        if f.current < f.full - max(1, s.pv_adjust_deadband):
            action = Action.RESTORE
            target = f.full
            reason = (
                "Master control was switched off; bypassing the in-flight command and restoring all configured inverter limits to full."
                if f.write_lock
                else "Master control was switched off; restoring configured inverter limits to full before HPVC stops."
            )
        else:
            reason = (
                "PV is full; waiting for the HPVC-owned HBC override to restore before HPVC stops."
                if ex.hbc_restore_pending
                else "Waiting for independent full-output verification of every obligated inverter and for in-flight inverter actions to finish."
            )
    elif f.night_suspended:
        status = "Night Restore pending" if f.night_pending else "Night Restore"
        unavailable = any(
            not c.available for c in snapshot.controllers if c.participating
        )
        recovery = int(max(25, s.pv_night_restore_power + 15))
        reason = (
            (
                "Night Restore confirmation is pending; low PV was already observed and nighttime PV/limit telemetry may be temporarily unavailable during the 120-second confirmation window."
                if snapshot.sun_below_horizon
                else "Night Restore confirmation is pending; low PV was already observed, but unavailable PV telemetry will not be promoted to Night Restore without sun.sun nighttime corroboration."
            )
            if f.night_pending
            else (
                f"Night Restore active; nighttime PV/limit telemetry is unavailable as expected, so PV calculations remain suspended until PV telemetry returns and stays above {recovery} W for 30 s."
                if unavailable
                else f"Night Restore active; inverter limits are full and PV calculations are suspended until PV remains above {recovery} W for 30 s."
            )
        )
    elif force_min:
        action = Action.MINIMUM
        target = f.minimum
        status = (
            "PV minimum - negative price" if f.wants_minimum else "PV minimum limit"
        )
        reason = (
            negative_reason if f.wants_minimum else "Calculated target is minimum power"
        )
    elif snapshot.external_release:
        controllers = tuple(c for c in snapshot.controllers if c.participating)
        full = [
            c
            for c in controllers
            if c.available
            and c.independently_verifiable
            and not c.open_loop
            and c.current_w is not None
            and abs(c.current_w - c.full_w) <= max(1, s.pv_adjust_deadband)
        ]
        unavailable = [c for c in controllers if not c.available and not c.open_loop]
        openloop = any(c.open_loop for c in controllers)
        clear = (
            not f.write_lock
            and not ex.unresolved_operation_ids
            and not ex.unresolved_obligation_ids
            and not ex.recovery_required
        )
        release_full = bool(controllers) and len(full) == len(controllers) and clear
        degraded = (
            f.release_age >= 90
            and bool(unavailable)
            and bool(full)
            and len(full) + len(unavailable) == len(controllers)
            and not openloop
            and clear
        )
        status = "External PV release waiting"
        if f.wants_minimum or ex.hbc_restore_pending:
            reason = "External release is queued until the active negative-price/HBC restore state has completed."
        elif hbc.transition_settle_active or hbc.response_window_active:
            reason = "External release is queued until the current HBC Charge Priority response/transition window has completed."
        elif release_full:
            status = "External PV release active"
            reason = "PV is released to full output for an external controller; normal HPVC curtailment is suspended until the request is removed."
        elif degraded:
            status = "External PV release active"
            names = ", ".join(
                "PV" + str(index + 1)
                for index, c in enumerate(snapshot.controllers)
                if c in unavailable
            )
            capacity = int(sum(c.full_w for c in unavailable))
            reason = f"Degraded external PV release active after 90 s: every independently reachable inverter is confirmed full and has no pending write/settling work; unavailable: {names} ({capacity} W capacity not confirmed)."
        elif openloop and f.release_age >= 90:
            reason = "External release cannot use degraded acknowledgement without independent live readback"
        elif f.write_lock:
            reason = "External release is waiting for reachable inverter write verification/physical settling to complete."
        elif not f.any_below_full:
            reason = "Every configured inverter must have available, independently verified full-limit readback before release can be acknowledged."
        elif f.can_change:
            action = Action.RESTORE
            target = f.full
            status = "External PV release requested"
            reason = "External controller requested PV release; restoring all configured inverter limits to full."
        else:
            reason = "External PV release requested; waiting for the current HPVC cooldown/write-confirmation window before restoring full output."
    elif charge_increase:
        action = Action.HBC_INCREASE
        target = hbc.increase_target_w
        status = "HBC Charge Priority"
        reason = f"HBC Charge Priority: normal battery headroom available; releasing {round(target - f.current)} W of PV headroom for HBC"
    elif restore:
        action = Action.RESTORE
        target = f.full
        status = "Night Restore" if f.night_active else "Restoring PV"
        reason = (
            (
                "Night Restore confirmed after 120s of valid low PV with sun.sun below horizon; restoring inverter limits to full before suspending PV calculations"
                if snapshot.sun_below_horizon
                else f"Valid PV {round(f.pv)}W <= Night {round(s.pv_night_restore_power)}W for 120s; restoring inverter limits to full before suspending PV calculations (low-PV fallback)"
            )
            if f.night_active
            else f"Market/export price {f.market:.4f} €/kWh exceeded the PV restore threshold {s.pv_limiting_price + s.battery_price_hysteresis:.4f} €/kWh (limit + hysteresis)"
            if f.market > s.pv_limiting_price + s.battery_price_hysteresis
            else "Calculated target is full power"
        )
    elif adjust:
        action = Action.ADJUST
        target = f.calculated
        status = "PV dynamically adjusted"
        reason = (
            f"Export {round(f.grid)}W < Start {round(s.export_start_threshold)}W"
            if f.grid < s.export_start_threshold
            else f"Import {round(f.grid)}W > Restore {round(s.import_restore_threshold)}W"
        )
    else:
        status = (
            "Restoring PV"
            if f.write_lock and f.any_below_full and ex.pending_action == "restore"
            else "HBC Charge Priority"
            if hbc_ready and hbc.priority_operational
            else "PV minimum locked - negative price"
            if f.wants_minimum
            else "Monitoring low price"
            if f.price_active
            else "PV full / price OK"
        )
        reason = (
            "Charge Priority is preserving available PV for battery charging"
            if hbc_ready and hbc.priority_operational
            else negative_reason
            if f.wants_minimum
            else f"Previous inverter command still in flight: {ex.write_lock_reason or 'waiting for previous inverter write confirmation'} ({round(max(0, snapshot.now - (ex.pending_since_utc or snapshot.now)))} s; timeout {round(max(120, s.cooldown_seconds * 4))} s)"
            if f.write_lock
            else "PV already at minimum; waiting until a higher target is needed"
            if at_min and f.at_minimum
            else "No target change needed"
            if f.can_change
            else "PV cooldown active"
        )
    if f.night_pending and not f.night_suspended and not f.disable_restore:
        status = "Night Restore pending"
        reason = f"PV is at/below {round(s.pv_night_restore_power)} W; waiting for the 120-second Night Restore confirmation window."
    return Arbitration(action, status, reason, target, release_full, degraded)
