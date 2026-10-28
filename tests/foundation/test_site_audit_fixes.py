"""Production-derived redacted regression and strict synthetic boundary cases."""

import copy
import hashlib
import json
import re
from pathlib import Path
import unittest

from custom_components.hpvc.legacy import build_preview
from custom_components.hpvc.site_audit.engine import audit_site
from custom_components.hpvc.site_audit.schema import EXPECTED
from custom_components.hpvc.site_audit.ownership import classify_ownership, REFERENCE
from custom_components.hpvc.inverter.base import (
    EntityRecord,
    RegistryEntity,
    RegistryDevice,
)
from custom_components.hpvc.inverter.detection import (
    discover_controllers,
    is_hpvc_test_entity,
)
from test_import_scheduler import legacy_values

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/site-audit-production-redacted.json"
OPTIONAL = {
    "fixed_data_json": "{}",
    "target_json": "{}",
    "pre_actions_json": "[]",
    "post_actions_json": "[]",
}


def site_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def enphase(stem):
    return [
        EntityRecord(
            "number." + stem + "_dpel_limit",
            "1000",
            attributes_json='{"unit_of_measurement":"W"}',
        ),
        EntityRecord(
            "select." + stem + "_dpel_mode",
            "Export",
            attributes_json='{"options":["Production","Export"]}',
        ),
        EntityRecord("switch." + stem + "_dpel_enabled", "on"),
    ]


class EmptyJsonTests(unittest.TestCase):
    def values(self, method="Number entity"):
        values = legacy_values("1")
        values.update(
            {
                "input_select.hpvc_pv1_control_method": method,
                "input_text.hpvc_pv1_limit_number": EXPECTED[0],
                "input_number.hpvc_pv1_full_limit": "2000",
                "input_number.hpvc_pv1_low_limit": "100",
                "input_text.hpvc_pv1_action": "number.set_value",
            }
        )
        return values

    def test_blank_and_missing_optional_payloads_have_defined_defaults(self):
        for method in ("Number entity", "Action/service"):
            for value in (None, "", " \t\n "):
                values = self.values(method)
                for key in OPTIONAL:
                    if value is not None:
                        values["input_text.hpvc_pv1_" + key] = value
                before = copy.deepcopy(values)
                p = build_preview(values, "test")
                self.assertFalse(p.issues, p.issues)
                self.assertEqual(values, before)
                for key, default in OPTIONAL.items():
                    self.assertEqual(getattr(p.candidate.controllers[0], key), default)
                self.assertFalse(p.candidate.enabled_intent)

    def test_explicit_empty_shapes_and_populated_JSON_preserve_exact_semantics(self):
        payloads = dict(
            fixed_data_json=' {"value":7,"enabled":false} ',
            target_json=' {"entity_id":"number.external_limit"} ',
            pre_actions_json=' [{"action":"switch.turn_on","data":{},"target":{}}] ',
            post_actions_json=' [{"action":"switch.turn_off"}] ',
        )
        for method in ("Number entity", "Action/service"):
            for case in (OPTIONAL, payloads):
                values = self.values(method)
                values.update({"input_text.hpvc_pv1_" + k: v for k, v in case.items()})
                p = build_preview(values, "test")
                self.assertFalse(p.issues, p.issues)
                for key, value in case.items():
                    self.assertEqual(getattr(p.candidate.controllers[0], key), value)

    def test_nonempty_invalid_JSON_wrong_shape_and_unavailable_remain_errors(self):
        for key, default in OPTIONAL.items():
            wrong = "[]" if default == "{}" else "{}"
            for value in (
                "{",
                "not json",
                "null",
                "NaN",
                '{"x":1,"x":2}',
                wrong,
                "unavailable",
                "unknown",
            ):
                values = self.values()
                values["input_text.hpvc_pv1_" + key] = value
                p = build_preview(values, "test")
                self.assertIsNone(p.candidate, (key, value))
                self.assertTrue(
                    any(x.entity_id == "input_text.hpvc_pv1_" + key for x in p.issues),
                    (key, value),
                )


class DiscoveryExclusionTests(unittest.TestCase):
    def test_fake_fallback_removed_real_enphase_and_two_hoymiles_retained(self):
        b = site_fixture()
        states = [
            EntityRecord(
                r["entity_id"], r["state"], attributes_json=json.dumps(r["attributes"])
            )
            for r in b["states"]
        ]
        states.extend(enphase("user_hpvc_envoy"))
        c = discover_controllers((), (), states)
        self.assertEqual(
            {r.limit_entity for r in c},
            {*EXPECTED, "number.user_hpvc_envoy_dpel_limit"},
        )

    def test_fake_metadata_original_identity_and_explicit_markers_are_excluded(self):
        for marker in ("hpvc_test_fixture", "hpvc_test_transport"):
            for member in range(3):
                states = enphase("legitimate_envoy")
                r = states[member]
                states[member] = EntityRecord(
                    r.entity_id,
                    r.state,
                    attributes_json=json.dumps({**r.attributes, marker: True}),
                )
                self.assertFalse(discover_controllers((), (), states))
        for metadata_field in ("original_entity_id", "unique_id"):
            states = enphase("renamed_envoy")
            entries = [
                RegistryEntity(
                    s.entity_id,
                    device_id="device",
                    platform="envoy",
                    config_entry_id="entry",
                    **{
                        metadata_field: "number.hpvc_fake_envoy_dpel_limit"
                        if i == 0
                        else "ordinary"
                    },
                )
                for i, s in enumerate(states)
            ]
            self.assertFalse(
                discover_controllers(entries, (RegistryDevice("device"),), states)
            )

    def test_real_metadata_and_nonboolean_marker_not_overfiltered(self):
        states = enphase("user_hpvc_envoy")
        entries = [
            RegistryEntity(
                s.entity_id,
                device_id="device",
                platform="envoy",
                config_entry_id="entry",
                unique_id=s.entity_id,
            )
            for s in states
        ]
        self.assertEqual(
            len(discover_controllers(entries, (RegistryDevice("device"),), states)), 1
        )
        self.assertFalse(is_hpvc_test_entity("number.user_hpvc_envoy_dpel_limit"))
        self.assertFalse(is_hpvc_test_entity("number.hpvc_house_envoy_dpel_limit"))
        self.assertFalse(
            is_hpvc_test_entity(
                "number.envoy_dpel_limit",
                state=EntityRecord(
                    "number.envoy_dpel_limit",
                    attributes_json='{"hpvc_test_fixture":"true"}',
                ),
            )
        )

    def test_reserved_executor_targets_and_fake_hoymiles_are_never_discovered(self):
        from custom_components.hpvc.inverter.detection import TEST_TRANSPORT_TARGETS

        self.assertTrue(all(is_hpvc_test_entity(e) for e in TEST_TRANSPORT_TARGETS))
        state = EntityRecord(
            "number.hpvc_fake_hm_limit_nonpersistent_absolute",
            "2000",
            attributes_json='{"unit_of_measurement":"W","max":2000}',
        )
        self.assertFalse(discover_controllers((), (), (state,)))


class OwnershipProofTests(unittest.TestCase):
    def row(self, **kw):
        return dict(
            entity_id="binary_sensor.hpvc_required_inputs_ready",
            unique_id="hpvc_required_inputs_ready",
            platform="template",
            config_entry_id=None,
            **kw,
        )

    def classify(self, row, legacy=None, entries=None, registry=None):
        return classify_ownership(
            row,
            dict(
                entity_registry=registry or [row],
                legacy=legacy or {},
                config_entries=entries or [],
            ),
        )["classification"]

    def test_exact_known_identity_and_renamed_identity(self):
        r = self.row()
        self.assertEqual(self.classify(r), "proven_legacy_hpvc_owned")
        r["entity_id"] = "binary_sensor.renamed_readiness"
        self.assertEqual(self.classify(r), "proven_legacy_hpvc_owned")

    def test_names_and_wrong_platform_domain_do_not_prove_ownership(self):
        for changes in (
            {"unique_id": "some_other_unique_id"},
            {"platform": "mqtt"},
            {"entity_id": "sensor.hpvc_required_inputs_ready"},
        ):
            r = {**self.row(), **changes}
            self.assertEqual(self.classify(r), "unproven_collision")
        r = dict(
            entity_id="sensor.unrelated_template",
            unique_id="unrelated",
            platform="template",
            config_entry_id=None,
        )
        self.assertEqual(self.classify(r), "unrelated")

    def test_config_entry_owned_matching_identity_is_not_inferred_legacy(self):
        r = {**self.row(), "config_entry_id": "other-entry"}
        self.assertEqual(self.classify(r), "unproven_collision")
        self.assertEqual(
            self.classify(
                r,
                legacy={"registry_ownership": [r]},
                entries=[dict(entry_id="other-entry", domain="template")],
            ),
            "unproven_collision",
        )

    def test_supplied_package_mismatch_and_duplicates_fail_closed(self):
        r = self.row()
        for proof in (
            {"source_sha256": "0" * 64},
            {"approved_v16_package_match": False},
            {"package_reference": "other-package.yaml"},
        ):
            self.assertEqual(self.classify(r, legacy=proof), "unproven_collision")
        duplicate = {**r, "entity_id": "binary_sensor.duplicate"}
        self.assertEqual(
            self.classify(r, registry=[r, duplicate]), "unproven_collision"
        )
        self.assertEqual(
            self.classify(
                r,
                legacy={
                    "source_sha256": REFERENCE["sha256"],
                    "approved_v16_package_match": True,
                },
            ),
            "proven_legacy_hpvc_owned",
        )

    def test_catalogue_pinned_to_unchanged_approved_source(self):
        self.assertEqual(
            hashlib.sha256(
                (ROOT / REFERENCE["reference"]).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest(),
            REFERENCE["sha256"],
        )
        text = (ROOT / REFERENCE["reference"]).read_text(encoding="utf-8")
        pairs = set(
            re.findall(
                r"default_entity_id:\s*([a-z0-9_]+)\.[a-z0-9_]+\s*\n\s+unique_id:\s*(hpvc_[a-z0-9_]+)\s*$",
                text,
                re.M,
            )
        )
        self.assertEqual(
            {(r["domain"], r["unique_id"]) for r in REFERENCE["entities"]}, pairs
        )


class ProductionRegressionTests(unittest.TestCase):
    def test_actual_redacted_export_has_40_blanks_no_false_import_errors_and_two_real_controllers(
        self,
    ):
        b = site_fixture()
        before = copy.deepcopy(b)
        blanks = [
            r
            for r in b["states"]
            if any(r["entity_id"].endswith("_" + k) for k in OPTIONAL)
        ]
        self.assertEqual(len(blanks), 40)
        self.assertTrue(all(not r["state"].strip() for r in blanks))
        r = audit_site(b, now=b["collected_at_utc"])
        self.assertFalse(r["import_preview"]["issues"], r["import_preview"]["issues"])
        self.assertEqual(
            {c["writable_entity"] for c in r["controllers"]}, set(EXPECTED)
        )
        self.assertTrue(all(c["adapter_kind"] == "hoymiles" for c in r["controllers"]))
        collisions = [x for x in r["registry_migration"] if x["collision"]]
        self.assertEqual(len(collisions), 3)
        self.assertTrue(
            all(
                x["ownership_classification"] == "proven_legacy_hpvc_owned"
                for x in collisions
            )
        )
        self.assertTrue(all(not x["proposal"] for x in collisions))
        self.assertFalse(r["production_transport_authorized"])
        self.assertFalse(r["import_preview"]["committed"])
        self.assertFalse(r["handoff_projection"]["production_state_advanced"])
        self.assertEqual(b, before)

    def test_unproven_collision_still_blocks_after_other_fixes(self):
        b = site_fixture()
        b["entity_registry"].append(
            dict(
                entity_id="sensor.hpvc_status",
                unique_id="different",
                platform="template",
                config_entry_id=None,
            )
        )
        r = audit_site(b, now=b["collected_at_utc"])
        c = next(
            x
            for x in r["registry_migration"]
            if x["intended_entity_id"] == "sensor.hpvc_status"
        )
        self.assertEqual(c["ownership_classification"], "unproven_collision")
        self.assertEqual(c["proposal"], [])
        self.assertEqual(r["overall_verdict"], "BLOCKED")
        self.assertFalse(r["production_transport_authorized"])
