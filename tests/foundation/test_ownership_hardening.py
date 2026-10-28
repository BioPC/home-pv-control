"""Manifest evidence cannot override approved YAML catalogue or registry facts."""

import ast
import copy
import hashlib
import json
import textwrap
from pathlib import Path
import unittest
from unittest.mock import patch

from custom_components.hpvc.site_audit.ownership import classify_ownership, REFERENCE
from custom_components.hpvc.site_audit.engine import audit_site
from site_audit_fixture import sample

ROOT = Path(__file__).resolve().parents[2]


class OwnershipHardeningTests(unittest.TestCase):
    def row(self, **changes):
        return dict(
            {
                "entity_id": "binary_sensor.hpvc_required_inputs_ready",
                "unique_id": "hpvc_required_inputs_ready",
                "platform": "template",
                "config_entry_id": None,
            },
            **changes,
        )

    def check(
        self,
        row,
        expected="unproven_collision",
        *,
        evidence=None,
        entries=None,
        registry=None,
        legacy=None,
    ):
        bundle = dict(
            entity_registry=registry or [row],
            config_entries=entries or [],
            legacy={
                **(legacy or {}),
                "registry_ownership": [copy.deepcopy(row)]
                if evidence is None
                else evidence,
            },
        )
        before = copy.deepcopy(bundle)
        actual = classify_ownership(row, bundle)
        self.assertEqual(actual["classification"], expected, actual)
        self.assertEqual(bundle, before)
        return actual

    def test_manifest_cannot_bypass_catalogue(self):
        self.check(self.row(unique_id="operator_asserted_but_uncatalogued"))

    def test_manifest_cannot_bypass_domain(self):
        self.check(self.row(entity_id="sensor.hpvc_required_inputs_ready"))

    def test_manifest_cannot_prove_unknown_config_entry(self):
        result = self.check(self.row(config_entry_id="unknown-entry"))
        self.assertEqual(result["proof"], "config_entry_ownership_unresolved")

    def test_manifest_cannot_bypass_platform(self):
        self.check(self.row(platform="mqtt"))

    def test_resolved_config_entry_owner_is_not_yaml_owned(self):
        for domain in ("template", "hpvc", "mqtt"):
            with self.subTest(domain=domain):
                result = self.check(
                    self.row(config_entry_id="entry"),
                    entries=[dict(entry_id="entry", domain=domain)],
                )
                self.assertEqual(result["proof"], "config_entry_ownership_conflict")

    def test_valid_exact_manifest_supplements_catalogue(self):
        result = self.check(
            self.row(),
            "proven_legacy_hpvc_owned",
            legacy={
                "source_sha256": REFERENCE["sha256"],
                "approved_v16_package_match": True,
            },
        )
        self.assertEqual(result["proof"], "exact_supplied_registry_manifest")

    def test_renamed_exact_identity_with_valid_manifest_remains_proven(self):
        self.check(
            self.row(entity_id="binary_sensor.renamed_readiness"),
            "proven_legacy_hpvc_owned",
        )

    def test_manifest_contradicting_actual_unique_id_blocks_proof(self):
        row = self.row()
        self.check(row, evidence=[{**row, "unique_id": "different"}])

    def test_manifest_contradicting_config_entry_facts_blocks_proof(self):
        row = self.row()
        self.check(
            row,
            evidence=[{**row, "config_entry_id": "claimed-entry"}],
            entries=[dict(entry_id="claimed-entry", domain="template")],
        )
        owned = self.row(config_entry_id="actual-entry")
        self.check(
            owned,
            evidence=[row],
            entries=[dict(entry_id="actual-entry", domain="mqtt")],
        )

    def test_one_matching_manifest_row_cannot_cancel_a_contradiction(self):
        row = self.row()
        self.check(row, evidence=[row, {**row, "platform": "mqtt"}])

    def test_duplicate_registry_identity_is_unproven_even_with_manifest(self):
        row = self.row()
        self.check(
            row, registry=[row, {**row, "entity_id": "binary_sensor.duplicate_name"}]
        )

    def test_contradictory_package_evidence_vetoes_exact_manifest(self):
        for evidence in (
            {"source_sha256": "0" * 64},
            {"approved_v16_package_match": False},
            {"package_reference": "other.yaml"},
        ):
            with self.subTest(evidence=evidence):
                self.check(self.row(), legacy=evidence)

    def test_unrelated_template_is_distinct_from_unproven_hpvc_collision(self):
        row = dict(
            entity_id="sensor.unrelated",
            unique_id="unrelated",
            platform="template",
            config_entry_id=None,
        )
        self.check(row, "unrelated", evidence=[])
        self.check(row, "unproven_collision")

    def test_old_fabricated_compatibility_fixture_cannot_reach_proposal_builder(self):
        bundle = sample()
        old = dict(
            entity_id="sensor.hpvc_status",
            registry_id="old",
            platform="template",
            config_entry_id="legacy-entry",
            unique_id="legacy-status",
            device_id=None,
        )
        native = dict(
            entity_id="sensor.hpvc_status_2",
            registry_id="native",
            platform="hpvc",
            config_entry_id="native-entry",
            unique_id="site-audit-preview:status",
            device_id=None,
        )
        bundle["entity_registry"] += [old, native]
        bundle["config_entries"].append(
            dict(entry_id="native-entry", domain="hpvc", state="loaded")
        )
        bundle["legacy"]["registry_ownership"] = [old]
        before = copy.deepcopy(bundle)
        with patch(
            "custom_components.hpvc.site_audit.engine.plan_registry_migration",
            side_effect=AssertionError("Unproven identity reached proposal builder"),
        ):
            result = audit_site(bundle, now=1800000000.0)
        collision = next(
            r
            for r in result["registry_migration"]
            if r["intended_entity_id"] == old["entity_id"]
        )
        self.assertEqual(collision["ownership_classification"], "unproven_collision")
        self.assertEqual(collision["proposal"], [])
        self.assertEqual(result["overall_verdict"], "BLOCKED")
        self.assertFalse(result["production_transport_authorized"])
        self.assertFalse(result["import_preview"]["committed"])
        self.assertFalse(result["handoff_projection"]["production_state_advanced"])
        self.assertEqual(bundle, before)

    def test_expanded_production_fixture_keeps_twelve_proven_collisions(self):
        bundle = json.loads(
            (
                ROOT
                / "tests/fixtures/site-audit-production-12-collisions-redacted.json"
            ).read_text(encoding="utf-8")
        )
        before = copy.deepcopy(bundle)
        with patch(
            "custom_components.hpvc.site_audit.engine.plan_registry_migration",
            side_effect=AssertionError("No native replacement exists"),
        ):
            result = audit_site(bundle, now=bundle["collected_at_utc"])
        expected = {
            "binary_sensor.hpvc_required_inputs_ready",
            "sensor.hpvc_installed_version",
        } | {f"switch.hpvc_pv{i}_control" for i in range(1, 11)}
        collisions = [r for r in result["registry_migration"] if r["collision"]]
        self.assertEqual({r["intended_entity_id"] for r in collisions}, expected)
        self.assertTrue(
            all(
                r["ownership_classification"] == "proven_legacy_hpvc_owned"
                for r in collisions
            )
        )
        self.assertTrue(all(not r["proposal"] for r in collisions))
        self.assertEqual(result["import_preview"]["issues"], [])
        self.assertEqual(
            {r["writable_entity"] for r in result["controllers"]},
            {
                "number.hms_1000_2t_limit_nonpersistent_absolute",
                "number.hms_2000_4t_limit_nonpersistent_absolute",
            },
        )
        self.assertFalse(result["production_transport_authorized"])
        self.assertFalse(result["import_preview"]["committed"])
        self.assertFalse(result["handoff_projection"]["production_state_advanced"])
        self.assertEqual(result["overall_verdict"], "UNKNOWN")
        self.assertEqual(bundle, before)

    def test_original_compatibility_assertions_preserved_and_only_fixture_corrected(
        self,
    ):
        change = json.loads(
            (ROOT / "tests/fixtures/ownership-compatibility-change.json").read_text(
                encoding="utf-8"
            )
        )
        text = (ROOT / change["test_file"]).read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(text.encode()).hexdigest(), change["hardened_file_sha256_lf"]
        )
        lines = text.splitlines(keepends=True)
        method = next(
            n
            for n in ast.walk(ast.parse(text))
            if isinstance(n, ast.FunctionDef) and n.name == change["test_name"]
        )
        start, end = method.lineno - 1, method.end_lineno
        self.assertEqual("".join(lines[start:end]), change["hardened_test_source"])
        outside = (
            "".join(lines[:start])
            + "    # OWNERSHIP_FIXTURE_HARDENING\n"
            + "".join(lines[end:])
        )
        self.assertEqual(
            hashlib.sha256(outside.encode()).hexdigest(),
            change["unchanged_module_sha256_lf"],
        )
        old = ast.parse(textwrap.dedent(change["baseline_test_source"]))
        new = ast.parse(textwrap.dedent(change["hardened_test_source"]))

        def assertions(tree):
            return sum(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr.startswith("assert")
                for n in ast.walk(tree)
            )

        self.assertEqual(assertions(old), 3)
        self.assertEqual(assertions(old), assertions(new))
        substitutions = change["literal_substitutions"]

        class CorrectFixture(ast.NodeTransformer):
            def visit_Constant(self, node):
                if isinstance(node.value, str) and node.value in substitutions:
                    return ast.copy_location(
                        ast.Constant(substitutions[node.value]), node
                    )
                return node

        self.assertEqual(
            ast.dump(CorrectFixture().visit(old), include_attributes=False),
            ast.dump(new, include_attributes=False),
        )
