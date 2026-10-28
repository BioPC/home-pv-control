"""Local read-only acceptance probes; intentionally expose unmet requirements."""

import argparse
import ast
import copy
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument("--source-root", required=True, type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.source_root.resolve()))

from custom_components.hpvc.site_audit.ownership import classify_ownership, KNOWN
from custom_components.hpvc.inverter.base import EntityRecord
from custom_components.hpvc.inverter.manager import InverterManager
from custom_components.hpvc.control.models import PlantConfiguration, ControllerConfiguration, ControllerIdentity
from custom_components.hpvc.execution.ha_executor import production_transport_admitted
from custom_components.hpvc.site_audit.engine import authorization_design

known = dict(entity_id="binary_sensor.hpvc_required_inputs_ready", unique_id="hpvc_required_inputs_ready", platform="template", config_entry_id=None)
cases = []


def add(name, row, expected, *, explicit=False, duplicate=False, legacy=None):
    bundle = dict(entity_registry=[row], config_entries=[], legacy=copy.deepcopy(legacy or {}))
    if explicit:
        bundle["legacy"]["registry_ownership"] = [copy.deepcopy(row)]
    if duplicate:
        bundle["entity_registry"].append({**row, "entity_id": row["entity_id"] + "_duplicate"})
    before = copy.deepcopy(bundle)
    actual = classify_ownership(row, bundle)
    cases.append(dict(name=name, expected=expected, actual=actual["classification"],
                      approved_catalogue_match=(row["entity_id"].split(".")[0], row["platform"], row["unique_id"]) in KNOWN,
                      input_unchanged=bundle == before, passed=actual["classification"] == expected and bundle == before))


add("exact_catalogue_identity", known, "proven_legacy_hpvc_owned")
add("renamed_exact_identity", {**known, "entity_id": "binary_sensor.renamed_ready"}, "proven_legacy_hpvc_owned")
add("same_name_other_uid", {**known, "unique_id": "unrelated"}, "unproven_collision")
add("wrong_domain", {**known, "entity_id": "sensor.hpvc_required_inputs_ready"}, "unproven_collision")
add("wrong_platform", {**known, "platform": "mqtt"}, "unproven_collision")
add("config_entry_owned", {**known, "config_entry_id": "unknown-entry"}, "unproven_collision")
add("duplicate_identity", known, "unproven_collision", duplicate=True)
add("contradictory_package", known, "unproven_collision", legacy={"source_sha256": "0" * 64})
add("unrelated_template", dict(entity_id="sensor.unrelated", unique_id="unrelated", platform="template", config_entry_id=None), "unrelated")
add("manifest_cannot_bypass_catalogue", {**known, "unique_id": "not_in_approved_catalogue"}, "unproven_collision", explicit=True)
add("manifest_cannot_bypass_domain", {**known, "entity_id": "sensor.hpvc_required_inputs_ready"}, "unproven_collision", explicit=True)
add("manifest_cannot_prove_unknown_config_entry", {**known, "config_entry_id": "unknown-entry"}, "unproven_collision", explicit=True)
add("manifest_cannot_bypass_duplicates", known, "unproven_collision", explicit=True, duplicate=True)
add("manifest_cannot_bypass_package_mismatch", known, "unproven_collision", explicit=True, legacy={"approved_v16_package_match": False})

manual_cases = []
for attrs in ({}, {"hpvc_test_fixture": True}, {"hpvc_test_transport": True}):
    entity_id = "number.hpvc_fake_manual_limit_nonpersistent_absolute"
    cfg = ControllerConfiguration(ControllerIdentity("manual", 1), "manual", full_limit_w=2000, limit_number=entity_id)
    plant = PlantConfiguration("manual-probe", inverter_count=1, controllers=(cfg,), enabled_intent=True)
    before = plant.to_dict()
    state = EntityRecord(entity_id, "1000", 1800000000.0, json.dumps(dict(min=0, max=5000, step=1, unit_of_measurement="W", **attrs)))
    manager = InverterManager()
    fleet = manager.refresh(plant, (state,), (), (), now=1800000000.0)
    passed = (len(fleet.effective) == 1 and fleet.effective[0].origin == "manual"
              and fleet.effective[0].view.configuration.limit_number == entity_id
              and not fleet.physical_writes_authorized and not manager.candidates
              and plant.to_dict() == before)
    manual_cases.append(dict(markers=attrs, passed=passed, physical_writes_authorized=fleet.physical_writes_authorized))

src = (a.source_root / "custom_components/hpvc/execution/ha_executor.py").read_text(encoding="utf-8")
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "production_transport_admitted")
safety = dict(production_transport_authorized=production_transport_admitted(),
              permanent_veto=authorization_design()["dev8_permanent_veto"],
              admission_returns_literal_false=isinstance(fn.body[-1], ast.Return) and isinstance(fn.body[-1].value, ast.Constant) and fn.body[-1].value.value is False,
              service_or_registry_write_calls=0, hardware_actions=0)
result = dict(ownership_cases=cases, ownership_passed=sum(x["passed"] for x in cases), ownership_failed=sum(not x["passed"] for x in cases),
              manual_binding_cases=manual_cases, safety=safety)
out = Path(__file__).with_name("strict-requirements-results.json")
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(dict(ownership_passed=result["ownership_passed"], ownership_failed=result["ownership_failed"], manual_binding_passed=sum(x["passed"] for x in manual_cases), safety=safety), indent=2))
sys.exit(0 if all(x["passed"] for x in cases + manual_cases) and not safety["production_transport_authorized"] else 1)
