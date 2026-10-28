"""Dashboard-only regression coverage; original control tests stay unchanged."""

import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.dashboard.builder import (
    REFERENCE,
    REPORT_SECTIONS,
    parity_dashboard,
)
from custom_components.hpvc.dashboard.presentation import CATALOG, dashboard_attributes

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/dashboard"))
from dashboard_fixture import LONG_IDS, NOW, SCENARIOS, fixture, visible_nodes


def nodes(value, path=""):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from nodes(v, path + "/" + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from nodes(v, path + "/" + str(i))


class DashboardStructureTests(unittest.TestCase):
    def setUp(self):
        self.d = parity_dashboard()

    def test_original_visual_reference_is_unchanged_and_pinned(self):
        self.assertEqual(
            hashlib.sha256((ROOT / CATALOG["reference"]).read_bytes()).hexdigest(),
            CATALOG["reference_sha256"],
        )

    def test_main_settings_view_order_and_section_order(self):
        self.assertEqual(
            [(v["title"], v["path"]) for v in self.d["views"]],
            [(v["title"], v["path"]) for v in REFERENCE["views"]],
        )
        self.assertEqual([len(v["sections"]) for v in self.d["views"]], [10, 8])

    def test_source_top_level_card_order_preserved_except_explicit_report_preview(self):
        for vi, view in enumerate(REFERENCE["views"]):
            for si, section in enumerate(view["sections"]):
                before = section.get("cards", [])
                after = self.d["views"][vi]["sections"][si].get("cards", [])
                self.assertEqual(
                    len(after), len(before) + (1 if (vi, si) == (0, 8) else 0)
                )
                for old, new in zip(before, after):
                    self.assertEqual(old["type"], new["type"])

    def test_all_entity_bindings_are_real_native_descriptors(self):
        native = set(CATALOG["native_entities"])
        for path, node in nodes(self.d):
            for key in ("entity", "runtime_entity"):
                if key in node:
                    self.assertIn(node[key], native, (path, node[key]))

    def test_no_legacy_hpvc_helper_reads_remain_in_templates(self):
        for path, node in nodes(self.d):
            text = node.get("content", "")
            self.assertNotIn("text.hpvc_insight_", text, path)
            self.assertFalse(
                re.search(
                    r"(?:states|state_attr|is_state)\(['\"]input_(?:boolean|number|select|text)\.hpvc_",
                    text,
                ),
                path,
            )

    def test_no_physical_legacy_or_external_service_actions(self):
        for path, node in nodes(self.d):
            self.assertNotIn(
                node.get("action"), ("perform-action", "call-service", "toggle"), path
            )

    def test_graph_presence_spans_and_reference_legend_colors(self):
        old = [
            (p, n)
            for p, n in nodes(REFERENCE)
            if n.get("type") == "custom:apexcharts-card"
        ]
        lookup = dict(nodes(self.d))
        self.assertEqual(len(old), 3)
        for p, ref in old:
            new = lookup[p]
            self.assertEqual(
                new["graph_span"],
                "12h"
                if ref.get("header", {}).get("title", "").endswith("Power Flow")
                else "48h",
            )
            self.assertEqual(
                [(s.get("name"), s.get("color")) for s in new["series"]],
                [(s.get("name"), s.get("color")) for s in ref["series"]],
            )
            self.assertFalse(any(s.get("type") == "attribute" for s in new["series"]))

    def test_history_remains_explicitly_unknown_until_native_collection_exists(self):
        graphs = [
            n
            for _, n in nodes(self.d)
            if n.get("header", {}).get("title") == "HPVC control/state history"
        ]
        self.assertEqual(len(graphs), 2)
        self.assertTrue(
            all(
                "else" not in s["transform"] and "null" in s["transform"]
                for n in graphs
                for s in n["series"]
            )
        )

    def test_limit_row_count_label_icon_read_only_and_position(self):
        rows = [
            (p, n)
            for p, n in nodes(self.d)
            if n.get("type") == "custom:hpvc-limit-entity-row"
        ]
        self.assertEqual(len(rows), 10)
        for i, (p, n) in enumerate(rows, 1):
            self.assertTrue(p.endswith("/card/cards/2/entities/3/row"), p)
            self.assertEqual(n["name"], "Limit entity:")
            self.assertEqual(n["attribute"], f"pv{i}_limit_entity")
            self.assertEqual(n["icon"], "mdi:lock-outline")
            self.assertNotIn("tap_action", n)

    def test_requested_status_wording_is_present_for_all_ten_slots(self):
        status = [
            n["content"]
            for _, n in nodes(self.d)
            if "Inverter status:" in n.get("content", "")
        ]
        self.assertEqual(len(status), 10)
        self.assertTrue(
            all("Hoymiles Detected" in s and "Enphase Detected" in s for s in status)
        )

    def test_report_preview_preserves_requested_sections_and_discloses_missing_data(
        self,
    ):
        report = self.d["views"][0]["sections"][8]["cards"][-1]
        self.assertEqual(report["title"], "Reports")
        text = report["content"]
        self.assertEqual(
            re.findall(r"<summary>(.*?)</summary>", text), list(REPORT_SECTIONS)
        )
        self.assertIn("<details open>", text)
        self.assertIn("unavailable", text.lower())

    def test_actual_registry_ids_are_substituted_without_double_suffixes(self):
        d = parity_dashboard(
            {
                "sensor.hpvc_status": "sensor.hpvc_status_2",
                "sensor.hpvc_inverter_limit_entity_display": "sensor.hpvc_inverter_limit_entity_display_2",
            }
        )
        text = json.dumps(d)
        self.assertNotIn("hpvc_status_2_2", text)
        self.assertTrue(
            all(
                n["entity"] == "sensor.hpvc_inverter_limit_entity_display_2"
                for _, n in nodes(d)
                if n.get("type") == "custom:hpvc-limit-entity-row"
            )
        )
        for _, n in nodes(d):
            self.assertFalse(
                re.search(r"state_attr\('sensor.hpvc_status'", n.get("content", ""))
            )

    def test_mapping_rejects_invalid_entities_and_cross_domain_targets(self):
        for mapping in (
            {"sensor.hpvc_status": "bad"},
            {"sensor.hpvc_status": "switch.any"},
            {"sensor.not_native": "sensor.x"},
        ):
            with self.assertRaises(SchemaError):
                parity_dashboard(mapping)

    def test_generated_artifact_and_locked_structure_match(self):
        actual = json.loads(
            (ROOT / "home assistant/hpvc_native_dashboard.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(actual, self.d)
        lock = json.loads(
            (ROOT / "custom_components/hpvc/dashboard/parity-lock.json").read_text(
                encoding="utf-8"
            )
        )
        digest = hashlib.sha256(
            json.dumps(
                self.d, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.assertEqual(digest, lock["native_structure_sha256"])


class DashboardDegradedTests(unittest.TestCase):
    def test_all_required_synthetic_scenarios_render_visibility_without_mutation(self):
        for name in SCENARIOS:
            with self.subTest(name=name):
                f = fixture(name)
                before = copy.deepcopy(f["states"])
                result = list(
                    visible_nodes(parity_dashboard()["views"][0], f["states"])
                )
                self.assertTrue(result)
                self.assertEqual(f["states"], before)

    def test_zero_and_monitoring_only_hide_inverter_configuration(self):
        for name in ("zero", "monitoring_only"):
            f = fixture(name)
            visible = list(
                visible_nodes(
                    parity_dashboard()["views"][1]["sections"][1], f["states"]
                )
            )
            self.assertFalse(
                any(n.get("type") == "custom:hpvc-limit-entity-row" for _, n in visible)
            )
            main = list(visible_nodes(parity_dashboard()["views"][0], f["states"]))
            self.assertTrue(
                any(
                    "No PV inverters available. HPVC is monitoring only."
                    in n.get("content", "")
                    for _, n in main
                )
            )

    def test_stale_and_unavailable_values_are_gaps_and_real_zero_is_preserved(self):
        self.assertEqual(
            fixture("one")["states"]["sensor.hpvc_status"]["attributes"][
                "ui_sensor_hpvc_diag_grid_power"
            ],
            0,
        )
        for name in ("stale", "unavailable"):
            attrs = fixture(name)["states"]["sensor.hpvc_status"]["attributes"]
            self.assertIsNone(attrs["ui_sensor_hpvc_diag_grid_power"])
            self.assertIsNone(attrs["ui_sensor_hpvc_diag_pv_power"])
            self.assertEqual(attrs["ui_telemetry_ready"], "off")

    def test_hbc_is_optional_and_missing_prices_not_invented(self):
        f = fixture("hbc_unavailable")
        a = f["states"]["sensor.hpvc_status"]["attributes"]
        self.assertEqual(a["ui_binary_sensor_hpvc_hbc_available"], "off")
        self.assertEqual(
            a["ui_source_attributes"]["sensor.hbc_energy_prices_data"]["marks"], []
        )
        visible = list(visible_nodes(parity_dashboard()["views"][0], f["states"]))
        self.assertFalse(any(n.get("graph_span") == "48h" for _, n in visible))

    def test_projection_never_reads_legacy_hpvc_helpers_or_mutates_configuration(self):
        f = fixture("mixed")
        before = f["configuration"].to_dict()
        fleet = f["runtime"].manager.current
        dashboard_attributes(f["runtime"], f["rows"], now=NOW)
        self.assertEqual(before, f["configuration"].to_dict())
        self.assertIs(fleet, f["runtime"].manager.current)
        self.assertFalse(
            any(
                re.match(r"input_(?:boolean|number|select|text)\.hpvc_", s)
                for s in f["reads"]
            )
        )

    def test_auto_before_manual_total_and_two_real_ids_are_fixture_backed(self):
        f = fixture("hoymiles")
        self.assertEqual([r["limit_entity"] for r in f["rows"]], list(LONG_IDS))
        text = parity_dashboard()["views"][1]["sections"][1]["cards"][2]["content"]
        self.assertLess(text.index("auto-detected"), text.index("manual_"))

    def test_projection_does_not_fabricate_control_or_report_history(self):
        a = fixture("one")["states"]["sensor.hpvc_status"]["attributes"]
        self.assertFalse(a["ui_report_generation_available"])
        self.assertFalse(a["ui_control_history_available"])
        self.assertEqual(a["ui_binary_sensor_hpvc_pv_limited"], "unknown")
        self.assertEqual(a["ui_binary_sensor_hpvc_cooldown_active"], "unknown")

    def test_hbc_price_attributes_never_forward_credentials_or_nonfinite_values(self):
        f = fixture("one")
        state = f["runtime"].state_reader("sensor.hbc_energy_prices_data")
        state.attributes["marks"] = [
            {
                "price": float("nan"),
                "token": "secret",
                "start": "2027-01-01",
                "mark": "high",
            }
        ]
        a = dashboard_attributes(f["runtime"], f["rows"], now=NOW)
        json.dumps(a, allow_nan=False)
        self.assertNotIn("secret", str(a))
