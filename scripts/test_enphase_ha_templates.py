import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "home assistant" / "hpvc_config.yaml"
FLOW = ROOT / "node-red" / "hpvc_flow.json"


@dataclass
class Entity:
    entity_id: str
    state: str = "unknown"
    attributes: dict = field(default_factory=dict)


class States:
    def __init__(self, entities=None):
        self.entities = {}
        for entity in entities or []:
            self.entities[entity.entity_id] = entity

    def __call__(self, entity_id):
        entity = self.entities.get(str(entity_id))
        return entity.state if entity else "unknown"

    def __iter__(self):
        return iter(self.entities.values())

    def __getattr__(self, domain):
        prefix = f"{domain}."
        return [e for e in self.entities.values() if e.entity_id.startswith(prefix)]

    def add(self, entity_id, state="unknown", attributes=None):
        self.entities[entity_id] = Entity(entity_id, str(state), attributes or {})


def regex_match(value, pattern):
    return re.match(pattern, str(value or "")) is not None


def from_json(value, default=None):
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def is_number(value):
    try:
        float(value)
        return str(value).strip().lower() not in {"nan", "inf", "+inf", "-inf"}
    except Exception:
        return False


def build_env(states):
    env = Environment(autoescape=False)
    env.filters["regex_match"] = regex_match
    env.filters["from_json"] = from_json
    env.filters["to_json"] = json.dumps
    env.globals.update(
        states=states,
        state_attr=lambda entity_id, attr: states.entities.get(str(entity_id), Entity("")).attributes.get(attr),
        is_number=is_number,
        is_state=lambda entity_id, expected: states(str(entity_id)) == expected,
    )
    return env


def render(template, states):
    return build_env(states).from_string(template).render().strip()


def template_entity(config, unique_id):
    for block in config.get("template", []):
        if not isinstance(block, dict):
            continue
        for values in block.values():
            if not isinstance(values, list):
                continue
            for entity in values:
                if isinstance(entity, dict) and entity.get("unique_id") == unique_id:
                    return entity
    raise AssertionError(f"Template entity not found: {unique_id}")


def base_states():
    s = States()
    # Core configured entity helpers.
    s.add("input_text.hpvc_grid_power_sensor", "sensor.grid_power")
    s.add("input_text.hpvc_market_price_sensor", "sensor.market_price")
    s.add("input_text.hpvc_all_in_price_sensor", "sensor.all_in_price")
    s.add("input_text.hpvc_pv_power_sensor", "sensor.pv_power")
    s.add("sensor.grid_power", "-250")
    s.add("sensor.market_price", "0.10")
    s.add("sensor.all_in_price", "0.20")
    s.add("sensor.pv_power", "3000")
    s.add("input_text.hpvc_status", "Running")

    # Valid shipped control helpers used by Configuration Valid.
    numeric = {
        "input_number.hpvc_pv_limiting_price": "0.02",
        "input_number.hpvc_battery_price_hysteresis": "0.02",
        "input_number.hpvc_export_start_threshold": "-125",
        "input_number.hpvc_export_stop_threshold": "-25",
        "input_number.hpvc_import_restore_threshold": "125",
        "input_number.hpvc_pv_min_power_for_control": "100",
        "input_number.hpvc_pv_night_restore_power": "10",
        "input_number.hpvc_cooldown_seconds": "30",
        "input_number.hpvc_pv_adjust_deadband": "25",
        "input_number.hpvc_inverter_count": "1",
    }
    for entity_id, value in numeric.items():
        s.add(entity_id, value)

    # Slot 1 defaults: intentionally empty Number slot, valid for Enphase reuse.
    s.add("input_select.hpvc_pv1_control_method", "Number entity")
    s.add("input_select.hpvc_pv1_limit_unit", "Watts")
    s.add("input_number.hpvc_pv1_full_limit", "2000")
    s.add("input_number.hpvc_pv1_low_limit", "100")
    s.add("input_text.hpvc_pv1_limit_number", "")
    s.add("input_text.hpvc_pv1_readback_entity", "")
    s.add("input_text.hpvc_pv1_action", "")
    s.add("input_text.hpvc_pv1_value_field", "value")
    s.add("input_boolean.hpvc_pv1_auto_managed", "off")
    s.add("input_text.hpvc_pv1_auto_identity", "")
    return s


def add_enphase(states, stem="envoy_122113020461", limit="2500", maximum=4000, minimum=0, step=1,
                enabled="on", mode="Production", options=None):
    options = ["Production", "Export"] if options is None else options
    states.add(
        f"number.{stem}_dpel_limit",
        limit,
        {"min": minimum, "max": maximum, "step": step},
    )
    states.add(f"switch.{stem}_dpel_enabled", enabled)
    states.add(f"select.{stem}_dpel_mode", mode, {"options": options})



def add_opendtu(states, entity_id="number.hms_2000_limit_nonpersistent_absolute", limit="1500", maximum=2000, minimum=10, step=10):
    states.add(entity_id, limit, {"min": minimum, "max": maximum, "step": step, "unit_of_measurement": "W"})


def parse_runtime_json(text):
    value = json.loads(text)
    assert isinstance(value, list), f"runtime_json must render a list JSON value, got {type(value).__name__}"
    return value


def main():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    flow = FLOW.read_text(encoding="utf-8")

    runtime = template_entity(config, "hpvc_effective_inverter_runtime")
    configuration_valid = template_entity(config, "hpvc_configuration_valid")
    required_ready = template_entity(config, "hpvc_required_inputs_ready")
    pv1 = template_entity(config, "hpvc_pv1_actual_limit")

    checks = []

    def check(name, condition):
        checks.append(name)
        if not condition:
            raise AssertionError(name)

    # Structural contract checks still catch accidental renames/refactors.
    yaml_text = CONFIG.read_text(encoding="utf-8")
    check("effective runtime sensor exists", "unique_id: hpvc_effective_inverter_runtime" in yaml_text)
    check("native DPEL discovery pattern", "^number[.].+_dpel_limit$" in yaml_text)
    check("policy captured after discovery", flow.find("homePvControlEnphaseDpelEntities") < flow.find("Capture adapter policy only after native Enphase discovery"))
    check("Enphase auto mirror preserves manual Max/Min", "runtime_parts[4] | trim != 'enphase'" in yaml_text)
    check("Enphase auto identity helpers exist", all(f"hpvc_pv{i}_auto_identity:" in yaml_text for i in range(1, 11)))
    check("Enphase auto cleanup preserves same-controller range", "preserve_enphase_range" in yaml_text and "not preserve_enphase_range" in yaml_text)

    # 0. Zero inverter setup is allowed by the helper/runtime map but is deliberately not operational.
    s_zero = base_states()
    s_zero.add("input_number.hpvc_inverter_count", "0")
    check("Zero-inverter configuration values remain structurally valid", render(configuration_valid["state"], s_zero) == "True")
    s_zero.add("binary_sensor.hpvc_configuration_valid", "on")
    check("Zero-inverter required inputs are not ready", render(required_ready["state"], s_zero) == "False")
    check("Zero-inverter effective count", render(runtime["state"], s_zero) == "0")
    check("Zero-inverter runtime map empty", parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_zero)) == [])

    # 1. Enphase-only: no manual limit helper is required.
    s = base_states()
    add_enphase(s)
    check("Enphase-only configuration valid", render(configuration_valid["state"], s) == "True")
    s.add("binary_sensor.hpvc_configuration_valid", "on")
    check("Enphase-only required inputs ready", render(required_ready["state"], s) == "True")
    check("Enphase-only effective count", render(runtime["state"], s) == "1")
    runtime_list = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s))
    check("Enphase-only runtime slot uses manual Max/Min", len(runtime_list) == 1 and runtime_list[0].startswith("number.envoy_122113020461_dpel_limit|Watts|2000.0|100.0|enphase|Number entity"))
    enphase_ui = parse_runtime_json(render(runtime["attributes"]["controller_ui_json"], s))
    check("Enphase Max power stays manual/editable", len(enphase_ui) == 1 and enphase_ui[0].get("max_power_locked") is False and float(enphase_ui[0].get("max_power", 0)) == 2000)
    s_sentinel = base_states()
    add_enphase(s_sentinel, maximum=10000000000)
    sentinel_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_sentinel))
    check("Enphase sentinel native max is ignored", sentinel_runtime[0].split("|")[2] == "2000.0")
    s_tuned = base_states()
    s_tuned.add("input_number.hpvc_pv1_low_limit", "500")
    add_enphase(s_tuned)
    tuned_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_tuned))
    tuned_ui = parse_runtime_json(render(runtime["attributes"]["controller_ui_json"], s_tuned))
    check("auto Enphase preserves configured slot minimum", tuned_runtime[0].split("|")[3] == "500.0" and float(tuned_ui[0].get("min_power", -1)) == 500)

    # 1a. User-owned Enphase Max/Min are bound to the auto-detected controller identity.
    s_same = base_states()
    s_same.add("input_boolean.hpvc_pv1_auto_managed", "on")
    s_same.add("input_text.hpvc_pv1_auto_identity", "enphase|number.envoy_122113020461_dpel_limit")
    add_enphase(s_same)
    same_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_same))
    check("same Enphase identity retains manual Max/Min", same_runtime[0].split("|")[2:4] == ["2000.0", "100.0"])

    s_other = base_states()
    s_other.add("input_boolean.hpvc_pv1_auto_managed", "on")
    s_other.add("input_text.hpvc_pv1_auto_identity", "enphase|number.previous_envoy_dpel_limit")
    add_enphase(s_other)
    other_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_other))
    other_ui = parse_runtime_json(render(runtime["attributes"]["controller_ui_json"], s_other))
    check("different Enphase identity cannot inherit prior Max/Min", other_runtime[0].split("|")[2:4] == ["0", "0"] or other_runtime[0].split("|")[2:4] == ["0.0", "0.0"])
    check("different Enphase identity remains incomplete until user config", other_ui[0].get("status") == "Incomplete" and other_ui[0].get("valid") is False)

    # 1b. OpenDTU-only: shared registry metadata can expose a fully renamed number without manual helpers.
    s_od = base_states()
    renamed_od = "number.garage_hoymiles_limit"
    add_opendtu(s_od, renamed_od, maximum=2250)
    s_od.add("sensor.hpvc_enphase_registry", "1", {
        "controllers": [],
        "opendtu_controllers": [dict(device_id="od_a", limit_entity=renamed_od, manufacturer="Hoymiles", model="HMS-2000-4T", max_power=2000, max_power_source="OpenDTU API")],
        "registry_entities": [renamed_od],
    })
    check("OpenDTU-only configuration valid", render(configuration_valid["state"], s_od) == "True")
    s_od.add("binary_sensor.hpvc_configuration_valid", "on")
    check("OpenDTU-only required inputs ready", render(required_ready["state"], s_od) == "True")
    check("OpenDTU-only effective count", render(runtime["state"], s_od) == "1")
    od_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_od))
    check("OpenDTU-only runtime slot", len(od_runtime) == 1 and od_runtime[0].startswith(renamed_od + "|Watts|2000.0|100.0|opendtu|Number entity"))
    check("OpenDTU discovered count", render(runtime["attributes"]["discovered_opendtu_count"], s_od) == "1")
    od_ui = parse_runtime_json(render(runtime["attributes"]["controller_ui_json"], s_od))
    check("OpenDTU API max locks Max power UI", len(od_ui) == 1 and od_ui[0].get("max_power_locked") is True and float(od_ui[0].get("max_power", 0)) == 2000)

    # 1c. Official suffix fallback remains available when registry metadata is unavailable.
    s_od_fallback = base_states()
    add_opendtu(s_od_fallback)
    check("OpenDTU suffix fallback configuration valid", render(configuration_valid["state"], s_od_fallback) == "True")
    od_fallback_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_od_fallback))
    check("OpenDTU suffix fallback runtime", "|opendtu|Number entity" in od_fallback_runtime[0])
    # Native number.max is not rated power: with no API/cache and no manual Full Limit, keep the slot detected but incomplete.
    s_od_needs_full = base_states()
    s_od_needs_full.add("input_number.hpvc_pv1_full_limit", "0")
    add_opendtu(s_od_needs_full, maximum=2250)
    od_needs_full_runtime = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_od_needs_full))
    check("OpenDTU native number max not used as rated power", len(od_needs_full_runtime) == 1 and "|Watts|0.0|" in od_needs_full_runtime[0])
    ui_needs_full = parse_runtime_json(render(runtime["attributes"]["controller_ui_json"], s_od_needs_full))
    check("OpenDTU missing Full Limit is not control-valid", len(ui_needs_full) == 1 and ui_needs_full[0].get('status') == 'Incomplete' and ui_needs_full[0].get('valid') is False)
    check("OpenDTU unknown trusted max leaves Max power editable", len(ui_needs_full) == 1 and ui_needs_full[0].get('max_power_locked') is False)
    s_od_wrong = base_states()
    s_od_wrong.add("number.hms_2000_limit_nonpersistent_absolute", "50", {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"})
    check("OpenDTU suffix fallback rejects non-Watt entity", render(configuration_valid["state"], s_od_wrong) == "False")

    # 2. Incomplete/changed DPEL contract is not accepted.
    s_bad = base_states()
    add_enphase(s_bad, options=["Production"])
    check("DPEL without Export option rejected", render(configuration_valid["state"], s_bad) == "False")

    # 3. Native-list and JSON-string HA attribute representations both drive Live Inputs.
    for label, runtime_attr in (
        ("native list", runtime_list),
        ("JSON string", json.dumps(runtime_list)),
    ):
        s_live = base_states()
        add_enphase(s_live)
        s_live.add("sensor.hpvc_effective_inverter_runtime", "1", {"runtime_json": runtime_attr})
        check(f"PV1 availability from {label}", render(pv1["availability"], s_live) == "True")
        check(f"PV1 value from {label}", float(render(pv1["state"], s_live)) == 2500)

    # 4. Manual Number Watts remains supported.
    s_num = base_states()
    s_num.add("number.hms_2000_limit", "1500", {"min": 100, "max": 2000, "step": 1})
    s_num.add("input_text.hpvc_pv1_limit_number", "number.hms_2000_limit")
    s_num.add("input_number.hpvc_pv1_full_limit", "2000")
    r_num = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_num))
    check("manual Number Watts runtime", r_num[0].startswith("number.hms_2000_limit|Watts|2000.0|100.0|manual-number|Number entity"))

    # 5. Manual Number Percent remains supported and Live Inputs converts to W.
    s_pct = base_states()
    s_pct.add("number.percent_limit", "50", {"min": 0, "max": 100, "step": 1})
    s_pct.add("input_text.hpvc_pv1_limit_number", "number.percent_limit")
    s_pct.add("input_select.hpvc_pv1_limit_unit", "Percent")
    s_pct.add("input_number.hpvc_pv1_full_limit", "4000")
    r_pct = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_pct))
    s_pct.add("sensor.hpvc_effective_inverter_runtime", "1", {"runtime_json": r_pct})
    check("manual Number Percent Live Inputs", float(render(pv1["state"], s_pct)) == 2000)

    # 6. Action/service uses its readback entity in the shared runtime map.
    s_action = base_states()
    s_action.add("input_select.hpvc_pv1_control_method", "Action/service")
    s_action.add("input_select.hpvc_pv1_limit_unit", "Watts")
    s_action.add("input_text.hpvc_pv1_action", "modbus.write_register")
    s_action.add("input_text.hpvc_pv1_readback_entity", "sensor.inverter_limit_readback")
    s_action.add("sensor.inverter_limit_readback", "1800")
    r_action = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_action))
    check("Action/service runtime readback", r_action[0].startswith("sensor.inverter_limit_readback|Watts|2000.0|100.0|manual-action|Action/service"))

    # 7. A manually configured DPEL entity is deduplicated and normalized to Watts even if helper says Percent.
    s_manual_dpel = base_states()
    add_enphase(s_manual_dpel, limit="3000", maximum=5000, step=1)
    s_manual_dpel.add("input_text.hpvc_pv1_limit_number", "number.envoy_122113020461_dpel_limit")
    s_manual_dpel.add("input_select.hpvc_pv1_limit_unit", "Percent")
    s_manual_dpel.add("input_number.hpvc_pv1_full_limit", "5000")
    r_manual_dpel = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_manual_dpel))
    check("manual DPEL deduplicated", len(r_manual_dpel) == 1)
    check("manual DPEL normalized to Watts", r_manual_dpel[0].startswith("number.envoy_122113020461_dpel_limit|Watts|5000.0|"))

    # 8. Mixed manual + multiple Envoys keeps deterministic one-controller-per-Envoy slot accounting.
    s_mixed = base_states()
    s_mixed.add("input_number.hpvc_inverter_count", "2")
    s_mixed.add("number.hms_2000_limit", "1800", {"min": 100, "max": 2000, "step": 1})
    s_mixed.add("input_text.hpvc_pv1_limit_number", "number.hms_2000_limit")
    # Define slot 2 as reusable.
    for suffix, value in {
        "control_method": "Number entity",
        "limit_unit": "Watts",
    }.items():
        s_mixed.add(f"input_select.hpvc_pv2_{suffix}", value)
    s_mixed.add("input_number.hpvc_pv2_full_limit", "2000")
    s_mixed.add("input_number.hpvc_pv2_low_limit", "100")
    for suffix in ("limit_number", "readback_entity", "action"):
        s_mixed.add(f"input_text.hpvc_pv2_{suffix}", "")
    add_enphase(s_mixed, stem="envoy_a", maximum=4000)
    add_enphase(s_mixed, stem="envoy_b", maximum=3000)
    r_mixed = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_mixed))
    check("mixed controller count", len(r_mixed) == 3)
    check("mixed manual slot preserved", r_mixed[0].startswith("number.hms_2000_limit|"))
    check("multiple Envoys each consume one slot", sum("|enphase|" in entry for entry in r_mixed) == 2)

    # Registry mappings use the same fully renamed triplets as the flow, without
    # needing template access to HA's internal entity registry.
    s_registry = base_states()
    controller = dict(device_id="device_a", limit_entity="number.custom_ceiling",
                      enable_entity="switch.custom_enable", mode_entity="select.custom_mode")
    s_registry.add(controller["limit_entity"], "3000", {"min": 0, "max": 5000, "step": 1})
    s_registry.add(controller["enable_entity"], "on")
    s_registry.add(controller["mode_entity"], "Production", {"options": ["Production", "Export"]})
    s_registry.add("sensor.hpvc_enphase_registry", "1", {"controllers": [controller],
                   "registry_entities": list(controller.values())[1:]})
    check("renamed registry configuration valid", render(configuration_valid["state"], s_registry) == "True")
    s_registry.add("binary_sensor.hpvc_configuration_valid", "on")
    check("renamed registry required inputs ready", render(required_ready["state"], s_registry) == "True")
    entries = parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_registry))
    check("renamed registry runtime slot uses manual Max power", entries[0].startswith("number.custom_ceiling|Watts|2000.0|"))
    check("renamed registry discovered count", render(runtime["attributes"]["discovered_enphase_count"], s_registry) == "1")
    s_registry.add("input_text.hpvc_pv1_limit_number", "number.custom_ceiling")
    check("renamed manual registry deduplicated", len(parse_runtime_json(render(runtime["attributes"]["runtime_json"], s_registry))) == 1)
    # Authoritative registry rejection must not be bypassed by official suffixes.
    s_blocked = base_states()
    add_enphase(s_blocked)
    s_blocked.add("sensor.hpvc_enphase_registry", "1", {"controllers": [], "registry_entities": ["number.envoy_122113020461_dpel_limit"]})
    check("registry rejection suppresses suffix fallback", render(configuration_valid["state"], s_blocked) == "False")
    # The visible toggle defaults on; its inverse helper restores an opt-out
    # across HA restarts without initial:true overriding the user's choice.
    control = template_entity(config, "hpvc_pv1_control")
    check("controller toggle defaults on", render(control["state"], base_states()) == "True")
    s_registry.add("input_boolean.hpvc_pv1_control_disabled", "on")
    check("controller toggle reflects saved opt-out", render(control["state"], s_registry) == "False")
    dashboard = (ROOT / "home assistant" / "hpvc_dashboard.yaml").read_text(encoding="utf-8")
    for slot in range(1, 11):
        check(f"PV{slot} dashboard control toggle", f"entity: switch.hpvc_pv{slot}_control" in dashboard)
        helper = config["input_boolean"][f"hpvc_pv{slot}_control_disabled"]
        check(f"PV{slot} opt-out survives restart", "initial" not in helper)

    print(f"Enphase/Home Assistant rendered-template regression passed ({len(checks)}/{len(checks)} checks).")


if __name__ == "__main__":
    main()
