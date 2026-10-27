"""Human-readable audit rendering; no I/O or execution capability."""

import json


def render_report(r):
    lines = [
        "HPVC DEV.8 — SITE-SPECIFIC READINESS AUDIT",
        "Observation only. No import, safe-disable, fence, ownership transition or actuator command is executed.",
        "",
    ]

    def section(n, title, value):
        lines.extend(
            [
                str(n) + ". " + title,
                "",
                value
                if isinstance(value, str)
                else json.dumps(value, indent=2, ensure_ascii=False),
                "",
            ]
        )

    section(
        1,
        "OVERALL READINESS VERDICT",
        r["overall_verdict"]
        + "\nProduction observations supplied: "
        + str(r["production_observations_supplied"])
        + "\nProduction transport authorized: False",
    )
    section(
        2,
        "HOME ASSISTANT ENVIRONMENT",
        dict(environment=r["ha"], coverage=r["coverage"]),
    )
    section(3, "LEGACY HPVC STATUS", r["legacy"])
    section(4, "NATIVE HPVC STATUS", r["native"])
    section(
        5,
        "CONTROLLER INVENTORY",
        dict(
            expected=r["expected_controllers"],
            effective=r["controllers"],
            site_telemetry=r["telemetry"],
        ),
    )
    section(6, "HBC STATUS", r["hbc"])
    section(7, "IMPORT PREVIEW", r["import_preview"])
    section(8, "ENTITY-REGISTRY MIGRATION", r["registry_migration"])
    section(
        9,
        "EXTERNAL REFERENCES",
        dict(references=r["references"], scope=r["external_reference_scope"]),
    )
    section(
        10,
        "HANDOFF BLOCKERS / UNKNOWNS",
        dict(projection=r["handoff_projection"], items=r["blockers_unknowns"]),
    )
    section(
        11,
        "RECOMMENDED FIRST HARDWARE CONTROLLER",
        r["first_hardware_test"].get("controller")
        or "UNDETERMINED. No controller can be chosen from entity names alone; production metadata and fresh independent observations are required.",
    )
    section(12, "EXACT PROPOSED FIRST HARDWARE TEST", r["first_hardware_test"])
    section(
        13,
        "ROLLBACK / RECOVERY PROCEDURE",
        "Stop new commands/tests after any stale telemetry, API/identity mismatch, unavailability, wrong readback, grid deviation, timeout, HA reload or Node-RED activity. Retain any possibly issued obligation. A separately approved recovery owner must revalidate identity and exclusivity before restoring the captured original full limit. Never blindly replay, restore a replaced controller, or treat a callback as physical proof. Verify independent restoration; otherwise remain in recovery and stop.",
    )
    section(
        14,
        "GO / NO-GO CHECKLIST",
        dict(
            site_readiness_verdict=r["overall_verdict"],
            site_readiness_approval="NOT GRANTED BY AUDIT",
            ownership_and_fence="Must be separately performed and verified under later approval",
            no_unresolved_work="Must be freshly proven",
            fresh_controller_API_PV_grid="Required at execution, not inferred from this archived snapshot",
            grid_abort_bound="Site-specific bound still requires approval",
            production_authorization=r["authorization_design"],
            one_inverter_only=True,
            execution_allowed=False,
        ),
    )
    lines.append(
        "Credentials are redacted. Hardware entity/device/serial identifiers are retained for identity review. Unprovided user content has not been exhaustively audited."
    )
    return "\n".join(lines) + "\n"
