"""Read-only report snapshot. Proposals are explicitly distinct from execution."""

from ..const import VERSION
from .data import fresh

HEADINGS = (
    "Executive Summary",
    "Live Status",
    "Decision Evaluation",
    "Today’s Insights",
    "Power Control",
    "Today’s Accuracy",
    "HBC & Battery Status",
    "Inverters",
    "Sensor Health",
    "Control Settings",
)


def report_sections(runtime, values, data, rows, now):
    ledger = runtime.ledger.current
    proposal = getattr(runtime, "policy_proposal", None)
    proposal = proposal if proposal and fresh(proposal.clock.utc, now) else None
    current = data["current"]
    metric = data["accuracy"]
    maintenance = {
        "installed_version": VERSION,
        "runtime_health": "recovery required"
        if runtime.recovery_required
        else "read-only runtime",
        "dashboard_storage": "unavailable" if data["fault"] else "healthy",
        "migration_state": runtime.migration_state,
        "unresolved_obligations": sum(
            o.state.value != "verified" for o in ledger.restore_obligations
        ),
        "production_transport_authorized": False,
        "permanent_production_veto": True,
        "restart_reload_required": "unavailable: no authoritative pending-update source",
        "legacy_operations": "Unavailable in native development mode",
    }
    unavailable = "Unavailable: no fresh native evidence"
    sections = (
        {
            "mode": current["mode"],
            "provenance": current["reason"],
            "local_date": data["local_date"],
            "production_transport_authorized": False,
        },
        dict(
            enabled_intent=runtime.configuration.enabled_intent,
            executed_mode=current["mode"],
            sampled_at=data["sampled_at"],
            telemetry_ready=values["ui_telemetry_ready"],
            **maintenance,
        ),
        {
            "kind": "Read-only proposal, not execution",
            "status": proposal.policy.intent.status if proposal else unavailable,
            "reason": proposal.policy.intent.reason if proposal else unavailable,
            "action": proposal.policy.intent.action.value if proposal else unavailable,
        },
        {
            "entries": data["insights"],
            "capacity": 20,
            "order": "newest first",
            "reset": "local midnight",
        },
        {
            "grid_w": values["ui_sensor_hpvc_diag_grid_power"],
            "pv_w": values["ui_sensor_hpvc_diag_pv_power"],
            "executed_mode": current["mode"],
            "cooldown": current["cooldown"],
            "limited": current["limited"],
            "settling": current["settling"],
            "verification_pending": current["verification_pending"],
            "evidence_ids": current["evidence_ids"],
        },
        metric,
        {
            "available": values["ui_binary_sensor_hpvc_hbc_available"],
            "strategy": values.get("ui_input_select_house_battery_strategy"),
            "sub_strategy": values.get(
                "ui_input_text_house_battery_strategy_active_sub_strategy"
            ),
            "charge_priority": current["priority"],
            "priority_provenance": "Accepted native HBC memory; does not imply a physical HPVC write",
            "charging_power_w": values.get("ui_sensor_hpvc_total_hbc_charging_power"),
            "batteries": [
                {
                    "index": i,
                    "soc": values.get(
                        f"ui_sensor_marstek_m{i}_battery_state_of_charge"
                    ),
                    "power_w": values.get(f"ui_sensor_marstek_m{i}_ac_power"),
                }
                for i in range(1, 7)
                if values.get(f"ui_sensor_marstek_m{i}_battery_state_of_charge")
                is not None
            ],
        },
        {
            "effective_count": len(runtime.manager.current.effective),
            "controllers": rows,
        },
        {
            "telemetry_ready": values["ui_telemetry_ready"],
            "stale_dashboard": data["stale"],
            "dashboard_fault": data["fault"],
            "grid_available": values["ui_sensor_hpvc_diag_grid_power"] is not None,
            "pv_available": values["ui_sensor_hpvc_diag_pv_power"] is not None,
        },
        runtime.configuration.settings.to_dict(),
    )
    return dict(zip(HEADINGS, sections)), maintenance
