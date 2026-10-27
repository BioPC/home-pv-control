from pathlib import Path
import json
import yaml

root = Path(__file__).resolve().parents[1]
dash = root / "home assistant" / "hpvc_dashboard.yaml"
text = dash.read_text(encoding="utf-8")
yaml.safe_load(text)

assert "### Active controller configuration" not in text
assert "Optional manual override" not in text
assert text.count("title: Controller configuration") == 0
assert "show_header_toggle: false\n                  entities:\n                - type: entities" not in text
assert text.count("name: HPVC Control") == 10
for i in range(1, 11):
    assert f"secondary_info: pv{i}_limit_entity" in text
    assert f"input_number.hpvc_pv{i}_full_limit" in text
    assert f"input_number.hpvc_pv{i}_low_limit" in text

config = (root / "home assistant" / "hpvc_config.yaml").read_text(encoding="utf-8")
flow_nodes = json.loads((root / "node-red" / "hpvc_flow.json").read_text(encoding="utf-8"))
flow_funcs = "\n".join(str(n.get("func", "")) for n in flow_nodes)
# Cross-layer zero-state contract: fresh install uses 0, runtime accepts 0, and the safety gate reports the dedicated non-operational state.
fresh_defaults = next(n for n in flow_nodes if n.get("name") == "Prepare full fresh-install defaults").get("func", "")
assert '\"input_number.hpvc_inverter_count\":0' in fresh_defaults, "fresh-install defaults must use zero inverters"
assert 'inverterCountRaw>=0&&inverterCountRaw<=10' in flow_funcs, "Node-RED must accept 0..10 as the configured inverter count"
assert "status = 'No PV inverters available'" in flow_funcs, "zero-inverter runtime must expose the dedicated safety state"
assert "hpvc_sync_auto_detected_controller_helpers" in config
assert "Mirror auto-detected controller values into slot fields" in config
assert config.count("|Number entity|auto") >= 4, "Detected Enphase/OpenDTU helpers must remain auto-classified after mirroring"

for i in range(1, 11):
    assert f"binary_sensor.hpvc_pv{i}_auto_detected" in text
    assert "entity: sensor.hpvc_inverter_limit_entity_display" in text
    assert f"secondary_info: pv{i}_limit_entity" in text
    assert f"entity: binary_sensor.hpvc_pv{i}_auto_detected" in text


# Locked auto-detected rows must stay visually muted instead of using the active binary-sensor color.
assert text.count("state_color: false") >= 30, "all auto-detected read-only rows must use muted icon coloring"

# Auto-detected controller identity fields are read-only; Min power remains tunable.
for i in range(1, 11):
    assert f"attribute: control_method" in text
    assert f"secondary_info: pv{i}_limit_entity" in text
    assert f"attribute: limit_unit" in text
    assert f"attribute: max_power" in text
    assert f"binary_sensor.hpvc_pv{i}_max_power_locked" in text
    assert f"entity: input_number.hpvc_pv{i}_low_limit" in text
    # Manual Number/controller fields remain available behind the auto-detected conditionals.
    assert f"entity: input_select.hpvc_pv{i}_control_method" in text
    assert f"entity: input_select.hpvc_pv{i}_limit_unit" in text
    assert f"entity: input_number.hpvc_pv{i}_full_limit" in text

for i in range(1, 11):
    assert f"unique_id: hpvc_pv{i}_auto_detected" in config
    assert f"unique_id: hpvc_pv{i}_max_power_locked" in config
    assert f"limit_entity: >-" in config

# Zero-controller dashboard state: the normal Inverters numeric-input row remains; PV1 is hidden.
assert 'title="No PV inverters available"' in text
assert 'HPVC is monitoring only. Add an inverter or wait for them to be' in text
assert 'entity: binary_sensor.hpvc_core_inputs_ready' in text
assert 'features_position: inline' in text and 'type: numeric-input' in text and 'style: buttons' in text
assert 'entity: number.hpvc_inverters\n                below: 1' not in text
# PV1 now has an explicit effective-runtime visibility guard; PV2..PV10 retain their show-slot guards.
pv1_marker = "entity: sensor.hpvc_effective_inverter_runtime\n                above: 0\n              - condition: state\n                entity: input_select.hpvc_selected_inverter\n                state: PV1"
assert pv1_marker in text
assert 'default_entity_id: binary_sensor.hpvc_core_inputs_ready' in config


# The Total inverters summary is hidden at zero so Settings shows only the normal Inverters counter row.
dash_obj = yaml.safe_load(text)
def _walk(v):
    if isinstance(v, dict):
        yield v
        for child in v.values():
            yield from _walk(child)
    elif isinstance(v, list):
        for child in v:
            yield from _walk(child)
summary_cards = [o for o in _walk(dash_obj) if o.get("type") == "markdown" and "**Total inverters:**" in o.get("content", "")]
assert len(summary_cards) == 1
assert summary_cards[0].get("visibility") == [{"condition":"numeric_state","entity":"sensor.hpvc_effective_inverter_runtime","above":0}]

print("Dashboard auto-fill/read-only and zero-state behavior: PASS")

# Auto-managed provenance must be explicit so disappearing auto controllers are
# cleared instead of being reinterpreted as manual/incomplete controllers.
for i in range(1, 11):
    assert f"hpvc_pv{i}_auto_managed:" in config
    assert f"input_boolean.hpvc_pv{{{{ slot }}}}_auto_managed" in config
assert "and not currently_auto" in config
assert "cleaned_auto" in config
assert 'value: ""' in config
