"""Read-only dashboard projection. No decision evaluation, persistence or writes."""

import json
import math
import time
from datetime import datetime
from pathlib import Path

CATALOG = json.loads(
    Path(__file__).with_name("bindings.json").read_text(encoding="utf-8")
)
PROJECTIONS = tuple(r for r in CATALOG["bindings"] if r["kind"] == "projection")
CONDITION_KEYS = tuple(
    json.loads(Path(__file__).with_name("condition-keys.json").read_text())
)


def ui_key(entity):
    return "ui_" + entity.replace(".", "_")


def dashboard_attributes(runtime, controller_rows, *, now=None):
    """Observe configuration, authoritative fleet and optional external HBC states.

    These attributes are presentation data on the existing status sensor. They
    never replace the authorization/readiness binary sensors. Legacy HPVC helper
    states are never read. Missing native execution/history facts stay unknown.
    """
    now = time.time() if now is None else now
    cfg = runtime.configuration
    values = {r["attribute"]: "unknown" for r in PROJECTIONS}
    attributes = {}

    def put(entity, value):
        values[ui_key(entity)] = value

    def read(entity):
        return runtime.state_reader(entity) if entity else None

    def fresh(state, ttl):
        try:
            return 0 <= now - state.last_reported.timestamp() <= ttl
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def number(entity, ttl=180):
        state = read(entity)
        try:
            value = float(state.state)
            if not math.isfinite(value) or not fresh(state, ttl):
                return None
            return value
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    for r in PROJECTIONS:
        entity = r["source"]
        # Optional external HBC data is observed; no legacy HPVC helper fallback.
        if entity.startswith(
            (
                "input_select.house_battery_",
                "input_text.house_battery_",
                "input_number.house_battery_",
                "sensor.marstek_m",
                "sensor.hbc_",
                "sun.",
            )
        ):
            state = read(entity)
            put(entity, state.state if state is not None else "unknown")
            if entity.startswith("sensor.marstek_m"):
                put(entity, number(entity))
            if entity == "sensor.hbc_energy_prices_data":
                marks = (getattr(state, "attributes", {}) or {}).get("marks", [])
                safe = []
                if isinstance(marks, list) and fresh(state, 7200):
                    for m in marks[:512]:
                        if not isinstance(m, dict):
                            continue
                        if type(m.get("price")) not in (
                            int,
                            float,
                        ) or not math.isfinite(m["price"]):
                            continue
                        try:
                            datetime.fromisoformat(m["start"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        safe.append(
                            {
                                k: m[k]
                                for k in ("start", "price", "mark", "is_now")
                                if k in m
                                and type(m[k]) in (str, int, float, bool)
                                and not (
                                    type(m[k]) is float and not math.isfinite(m[k])
                                )
                            }
                        )
                attributes[entity] = {"marks": safe}

    observed = {}
    for key, source in (
        ("grid_power_sensor", "sensor.hpvc_diag_grid_power"),
        ("pv_power_sensor", "sensor.hpvc_diag_pv_power"),
        ("market_price_sensor", "sensor.hpvc_diag_market_export_price"),
        ("all_in_price_sensor", "sensor.hpvc_diag_all_in_price"),
    ):
        observed[key] = number(getattr(cfg, key), 7200 if "price" in key else 180)
        put(source, observed[key])

    strategy = read("input_select.house_battery_strategy")
    hbc = strategy is not None and strategy.state not in ("unknown", "unavailable", "")
    put("binary_sensor.hpvc_hbc_available", "on" if hbc else "off")
    put("sensor.hpvc_diag_hbc_strategy", strategy.state if hbc else "unavailable")
    powers = [number(f"sensor.marstek_m{i}_ac_power") for i in range(1, 7)]
    try:
        count = int(values.get(ui_key("input_number.house_battery_count"), "0"))
    except (ValueError, TypeError):
        count = 0
    valid_powers = powers[:count] if 1 <= count <= 6 else []
    put(
        "sensor.hpvc_total_hbc_charging_power",
        sum(max(0, p) for p in valid_powers)
        if valid_powers and all(p is not None for p in valid_powers)
        else None,
    )
    core = all(x is not None for x in observed.values())
    put("binary_sensor.hpvc_core_inputs_ready", "on" if core else "off")
    put(
        "binary_sensor.hpvc_configuration_valid",
        "off" if runtime.manager.current.faults else "on",
    )
    put("binary_sensor.hpvc_export_threshold_range_invalid", "off")
    put("input_boolean.hpvc_onboarding_complete", "on")
    put("input_boolean.hpvc_defaults_applied", "on")
    put(
        "input_text.hpvc_status",
        "Monitoring only" if cfg.enabled_intent else "Disabled — monitoring only",
    )
    put("input_text.hpvc_node_red_flows_status", "Native HPVC — no Node-RED dependency")
    put(
        "input_text.hpvc_update_status",
        "Maintenance actions disabled in this development build",
    )
    for key in (
        "auto_resume_pending",
        "report_generating",
        "report_ready",
        "update_available",
        "update_dashboard_manual",
        "update_in_progress",
        "update_reload_required",
    ):
        put("input_boolean.hpvc_" + key, "off")
    for r in PROJECTIONS:
        if r["source"].startswith(("input_button.", "script.")):
            put(r["source"], "Unavailable in this build")
    fleet = runtime.manager.current
    values.update(
        ui_effective_count=len(fleet.effective),
        ui_telemetry_ready="on" if core else "off",
        ui_public_status="Monitoring only",
        ui_source_attributes=attributes,
        ui_report_generation_available=False,
        ui_control_history_available=False,
        ui_charge_priority_state="Unavailable — native execution is disabled",
    )
    observer = getattr(runtime, "dashboard_observer", None)
    if observer:
        data = observer.presentation(now)
        from .report import report_sections

        sections, maintenance = report_sections(
            runtime, values, data, controller_rows, now
        )
        current = data["current"]
        values.update(
            ui_dashboard_data=data,
            ui_report_sections=sections,
            ui_maintenance=maintenance,
            ui_control_history_available=True,
            ui_report_data_available=True,
            ui_charge_priority_state=current["priority"],
            ui_binary_sensor_hpvc_charge_priority_active="on"
            if current["priority"] == "Active"
            else "off"
            if current["priority"] in ("Off", "Waiting")
            else "unknown",
            ui_binary_sensor_hpvc_pv_limited="on"
            if current["limited"] is True
            else "off"
            if current["limited"] is False
            else "unknown",
            ui_binary_sensor_hpvc_cooldown_active="on"
            if current["cooldown"] is True
            else "off"
            if current["cooldown"] is False
            else "unknown",
        )
        for binding in PROJECTIONS:
            source = binding["source"]
            if source.startswith("sensor.hpvc_daily_"):
                metric = data["accuracy"]
                suffix = source.removeprefix("sensor.hpvc_daily_")
                supported = {
                    "target_accuracy": metric["accuracy_percent"],
                    "target_accuracy_samples": metric["measured"],
                    "target_samples": metric["measured"],
                    "sample_count": metric["measured"],
                }
                if suffix in supported:
                    values[binding["attribute"]] = supported[suffix]
        values[ui_key("binary_sensor.hpvc_maintenance_inverter_warning")] = (
            "on" if getattr(runtime, "recovery_required", False) else "off"
        )
    return values
