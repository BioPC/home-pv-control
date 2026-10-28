"""Synthetic UI states only: never physical readiness or production evidence."""

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.hpvc.control.models import PlantConfiguration
from custom_components.hpvc.dashboard.presentation import (
    CATALOG,
    CONDITION_KEYS,
    dashboard_attributes,
)

NOW = 1800000000.0
LONG_IDS = (
    "number.hms_2000_4t_limit_nonpersistent_absolute",
    "number.hms_1000_2t_limit_nonpersistent_absolute",
)
SCENARIOS = (
    "zero",
    "one",
    "multiple",
    "hoymiles",
    "enphase",
    "mixed",
    "hbc_unavailable",
    "stale",
    "unavailable",
    "monitoring_only",
    "partial",
)


def fixture(name, *, native_data=False):
    if name not in SCENARIOS:
        raise ValueError(name)
    sources = {}
    states = {
        e: {"state": "unknown", "attributes": {}} for e in CATALOG["native_entities"]
    }
    reads = []

    def put(entity, state, attrs=None, stale=False):
        sources[entity] = SimpleNamespace(
            state=str(state),
            attributes=attrs or {},
            last_reported=datetime.fromtimestamp(NOW - (10000 if stale else 0), UTC),
        )
        states[entity] = {"state": str(state), "attributes": attrs or {}}

    for role, value in (("grid", 0), ("pv", 1234), ("market", 0.12), ("all", 0.22)):
        put(
            "sensor.fixture_" + role,
            "unavailable" if name == "unavailable" else value,
            stale=name == "stale",
        )
    count = (
        0
        if name in ("zero", "monitoring_only")
        else 1
        if name in ("one", "enphase", "hbc_unavailable", "stale", "unavailable")
        else 2
    )
    rows = []
    for i in range(1, count + 1):
        kind = (
            "enphase"
            if name == "enphase" or (name == "mixed" and i == count)
            else "generic"
            if name == "one" or (name == "multiple" and i == count)
            else "opendtu"
        )
        auto = kind != "generic"
        row = {
            "status": "Unavailable"
            if name == "partial" and i == 2
            else "Detected"
            if auto
            else "Configured",
            "source": "auto" if auto else "manual",
            "kind": kind,
            "control_method": "Number entity",
            "limit_entity": LONG_IDS[i - 1]
            if kind == "opendtu"
            else "number.fixture_envoy_dpel_limit"
            if kind == "enphase"
            else "number.fixture_manual_limit",
            "limit_unit": "Watts",
            "max_power": 2000 if i == 1 else 1000,
            "min_power": 100,
            "max_power_locked": auto,
            "valid": True,
        }
        rows.append(row)
    cfg = PlantConfiguration(
        "ui-fixture",
        inverter_count=count,
        enabled_intent=name != "monitoring_only",
        grid_power_sensor="sensor.fixture_grid",
        pv_power_sensor="sensor.fixture_pv",
        market_price_sensor="sensor.fixture_market",
        all_in_price_sensor="sensor.fixture_all",
    )
    if name != "hbc_unavailable":
        put("input_select.house_battery_strategy", "Self Consumption")
        put("input_text.house_battery_strategy_active_sub_strategy", "Balanced")
        put("input_number.house_battery_count", 2)
        for i in (1, 2):
            put(f"sensor.marstek_m{i}_ac_power", 150 * i, stale=name == "stale")
            put(f"sensor.marstek_m{i}_battery_state_of_charge", 40 + i)
        put(
            "sensor.hbc_energy_prices_data",
            "available",
            {
                "marks": [
                    {
                        "start": "2027-01-15T08:00:00+00:00",
                        "price": 12.0,
                        "mark": "normal",
                        "is_now": True,
                    }
                ]
            },
            stale=name == "stale",
        )
    fleet = SimpleNamespace(
        effective=tuple(SimpleNamespace(origin=r["source"]) for r in rows), faults=()
    )

    def read(entity):
        reads.append(entity)
        return sources.get(entity)

    runtime = SimpleNamespace(
        configuration=cfg, manager=SimpleNamespace(current=fleet), state_reader=read
    )
    attrs = dashboard_attributes(runtime, rows, now=NOW)
    states["sensor.hpvc_status"] = {
        "state": "Read-only architecture - physical writes disabled",
        "attributes": attrs,
    }
    states["sensor.hpvc_effective_inverter_runtime"] = {
        "state": str(count),
        "attributes": {
            "effective_count": count,
            "controller_ui_json": rows,
            "runtime_json": [
                "|".join(
                    (
                        r["limit_entity"],
                        r["limit_unit"],
                        str(r["max_power"]),
                        str(r["min_power"]),
                        r["kind"],
                        r["control_method"],
                        r["source"],
                    )
                )
                for r in rows
            ],
        },
    }
    states["sensor.hpvc_inverter_limit_entity_display"] = {
        "state": "\u200b",
        "attributes": {
            f"pv{i}_limit_entity": r["limit_entity"] for i, r in enumerate(rows, 1)
        },
    }
    states["select.hpvc_selected_inverter"]["state"] = "PV1"
    states["number.hpvc_inverter_count"]["state"] = str(count)
    for key in (
        "enabled",
        "notifications",
        "insights_enabled",
        "control_hbc_strategy",
        "negative_price_hbc_charge",
        "external_release_request",
    ):
        states["switch.hpvc_" + key]["state"] = (
            "off" if key == "enabled" and name == "monitoring_only" else "on"
        )
    for k in cfg.settings.__dataclass_fields__:
        states["number.hpvc_" + k]["state"] = str(getattr(cfg.settings, k))
    for k in (
        "grid_power_sensor",
        "pv_power_sensor",
        "market_price_sensor",
        "all_in_price_sensor",
    ):
        states["text.hpvc_" + k]["state"] = getattr(cfg, k)
    for i, r in enumerate(rows, 1):
        for key, value in (
            ("auto_detected", r["source"] == "auto"),
            ("limit_range_invalid", False),
            ("max_power_locked", r["max_power_locked"]),
        ):
            states[f"binary_sensor.hpvc_pv{i}_{key}"] = {
                "state": "on" if value else "off",
                "attributes": r,
            }
        states[f"switch.hpvc_pv{i}_control"]["state"] = "on"
        states[f"select.hpvc_pv{i}_control_method"]["state"] = "Number entity"
        states[f"select.hpvc_pv{i}_limit_unit"]["state"] = "Watts"
    if native_data:
        from pathlib import Path

        from custom_components.hpvc.dashboard.data import (
            DashboardObserver,
            DashboardState,
            HistoryPoint,
        )
        from custom_components.hpvc.execution.models import ExecutionLedger

        runtime.ledger = SimpleNamespace(current=ExecutionLedger(cfg.plant_uid))
        runtime.recovery_required = False
        runtime.migration_state = "unassessed"
        runtime.policy_runtime = None
        runtime.policy_proposal = None
        observer = DashboardObserver(
            runtime, Path("synthetic-not-written-dashboard.json"), clock=lambda: NOW
        )
        point = HistoryPoint(
            NOW, reason="Synthetic read-only fixture; no native execution proof"
        )
        observer.state = DashboardState(
            cfg.plant_uid,
            datetime.fromtimestamp(NOW, UTC).date().isoformat(),
            (point,),
            unavailable=1,
        )
        observer.latest = point
        runtime.dashboard_observer = observer
        states["sensor.hpvc_status"]["attributes"] = dashboard_attributes(
            runtime, rows, now=NOW
        )
    for key in CONDITION_KEYS:
        value = states["sensor.hpvc_status"]["attributes"].get(key)
        states["sensor.hpvc_dashboard_" + key] = {
            "state": "unknown" if value is None else str(value),
            "attributes": {},
        }
    return {
        "states": states,
        "rows": rows,
        "configuration": cfg,
        "runtime": runtime,
        "reads": reads,
        "scenario": name,
    }


def conditions(items, states):
    for item in items:
        kind = item.get("condition", "state")
        if kind in ("and", "or"):
            result = [conditions([x], states) for x in item["conditions"]]
            ok = all(result) if kind == "and" else any(result)
        else:
            row = states.get(item.get("entity"), {})
            value = (
                row.get("attributes", {}).get(item["attribute"])
                if "attribute" in item
                else row.get("state", "unknown")
            )
            if kind == "numeric_state":
                try:
                    ok = (
                        "above" not in item or float(value) > float(item["above"])
                    ) and ("below" not in item or float(value) < float(item["below"]))
                except (ValueError, TypeError):
                    ok = False
            else:
                ok = True
                for key in ("state", "state_not"):
                    if key in item:
                        expected = (
                            item[key] if isinstance(item[key], list) else [item[key]]
                        )
                        match = str(value) in [str(x) for x in expected]
                        ok = ok and (match if key == "state" else not match)
        if not ok:
            return False
    return True


def visible_nodes(node, states, path=""):
    if isinstance(node, list):
        for i, value in enumerate(node):
            yield from visible_nodes(value, states, path + "/" + str(i))
    elif isinstance(node, dict):
        if not conditions(node.get("visibility", []), states):
            return
        if node.get("type") == "conditional" and not conditions(
            node.get("conditions", []), states
        ):
            return
        yield path, node
        for key in ("cards", "card", "entities", "row", "sections"):
            if key in node:
                yield from visible_nodes(node[key], states, path + "/" + key)
