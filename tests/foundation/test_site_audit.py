"""Audit immutability, provenance, redaction, strict selection and no actuator capability."""

import ast, copy, json, unittest
from pathlib import Path
from site_audit_fixture import sample
from custom_components.hpvc.site_audit.engine import audit_site, authorization_design
from custom_components.hpvc.site_audit.schema import (
    empty_export,
    EXPECTED,
    redact,
    validate_export,
)
from custom_components.hpvc.site_audit.capture import project_observations
from custom_components.hpvc.site_audit.render import render_report
from custom_components.hpvc.codec import SchemaError
from audit_tools.protocol import ReadOnlyHAClient, READ_COMMANDS
from unittest.mock import AsyncMock

NOW = 1800000000.0


class AuditTests(unittest.TestCase):
    def test_complete_export_is_only_ready_for_later_handoff_and_never_authorized(self):
        raw = sample()
        before = copy.deepcopy(raw)
        r = audit_site(raw, now=NOW)
        self.assertEqual(
            r["overall_verdict"], "READY_FOR_CONTROLLED_HANDOFF", r["blockers_unknowns"]
        )
        self.assertEqual(raw, before)
        self.assertFalse(r["production_transport_authorized"])
        self.assertFalse(r["handoff_projection"]["production_state_advanced"])
        self.assertEqual(r["first_hardware_test"]["controller"], EXPECTED[1])
        self.assertEqual(r["first_hardware_test"]["initial_observed_limit_w"], 1000)
        self.assertEqual(r["first_hardware_test"]["proposed_test_limit_w"], 980)
        self.assertEqual(r["first_hardware_test"]["restoration_target_w"], 1000)
        self.assertFalse(r["first_hardware_test"]["executable"])
        self.assertTrue(all(row["verified"] for row in r["expected_controllers"]))

    def test_missing_site_is_unknown_and_no_numeric_hardware_plan_is_invented(self):
        r = audit_site(empty_export(), now=NOW)
        self.assertEqual(r["overall_verdict"], "UNKNOWN")
        self.assertIsNone(r["first_hardware_test"]["controller"])
        self.assertNotIn("proposed_test_limit_w", r["first_hardware_test"])
        text = render_report(r)
        self.assertTrue(all("\n" + str(i) + ". " in text for i in range(1, 15)))

    def test_names_alone_cannot_prove_two_physical_controllers(self):
        b = sample()
        b["entity_registry"] = []
        b["device_registry"] = []
        r = audit_site(b, now=NOW)
        self.assertNotEqual(r["overall_verdict"], "READY_FOR_CONTROLLED_HANDOFF")
        self.assertFalse(any(x["verified"] for x in r["expected_controllers"]))

    def test_number_maximum_is_never_used_as_rated_power(self):
        b = sample()
        r = audit_site(b, now=NOW)
        self.assertEqual(sorted(x["full_w"] for x in r["controllers"]), [1000, 2000])
        b["opendtu"] = []
        r = audit_site(b, now=NOW)
        self.assertFalse(any(x["full_w"] == 9999 for x in r["controllers"]))
        self.assertIsNone(r["first_hardware_test"]["controller"])

    def test_input_and_output_do_not_share_nested_references(self):
        b = sample()
        r = audit_site(b, now=NOW)
        r["legacy"]["runtime"]["runtime_owner"] = "changed"
        self.assertEqual(b["legacy"]["runtime"]["runtime_owner"], "legacy-runtime")

    def test_configuration_import_is_preview_only(self):
        r = audit_site(sample(), now=NOW)
        self.assertFalse(r["import_preview"]["committed"])
        self.assertEqual(r["import_preview"]["stage"], "preview_ready")
        setting = next(
            x
            for x in r["import_preview"]["settings"]
            if x["old_entity_id"] == "input_boolean.hpvc_enabled"
        )
        self.assertEqual(json.loads(setting["imported_value_json"]), False)

    def test_unrelated_collision_is_not_reclaimable(self):
        b = sample()
        b["entity_registry"].append(
            dict(
                entity_id="sensor.hpvc_status",
                registry_id="other",
                platform="template",
                config_entry_id="other-entry",
                unique_id="unrelated",
                device_id=None,
            )
        )
        r = audit_site(b, now=NOW)
        c = next(
            x
            for x in r["registry_migration"]
            if x["intended_entity_id"] == "sensor.hpvc_status"
        )
        self.assertTrue(c["suffix_risk"])
        self.assertEqual(c["proposal"], [])
        self.assertEqual(c["ownership"], "unrelated_or_unproven_do_not_touch")
        self.assertEqual(r["overall_verdict"], "BLOCKED")

    def test_safe_owned_collision_proposal_is_data_only(self):
        b = sample()
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
            registry_id="new",
            platform="hpvc",
            config_entry_id="native-entry",
            unique_id="site-audit-preview:status",
            device_id=None,
        )
        b["entity_registry"] += [old, native]
        b["config_entries"].append(
            dict(entry_id="native-entry", domain="hpvc", state="loaded")
        )
        b["legacy"]["registry_ownership"] = [old]
        r = audit_site(b, now=NOW)
        c = next(
            x
            for x in r["registry_migration"]
            if x["intended_entity_id"] == "sensor.hpvc_status"
        )
        self.assertEqual(len(c["proposal"]), 2)
        self.assertEqual(c["proposal"][-1]["destination"], "sensor.hpvc_status")
        self.assertEqual(b["entity_registry"][-1]["entity_id"], "sensor.hpvc_status_2")

    def test_redaction_preserves_identity_but_removes_credentials_in_nested_JSON_and_URLs(
        self,
    ):
        paths = []
        secret = {
            "token": "token-value",
            "fixed_data_json": '{"payload":{"password":"password-value"},"value":1}',
            "url": "http://user:pass@host.example/path?api_key=key",
            "note": "Bearer abc.def.secret",
        }
        result = redact(secret, changes=paths)
        text = json.dumps(result)
        for value in (
            "token-value",
            "password-value",
            "user:pass",
            "api_key=key",
            "abc.def.secret",
        ):
            self.assertNotIn(value, text)
        self.assertIn("[REDACTED]", text)
        self.assertTrue(paths)
        self.assertIsInstance(
            redact({"authorization_design": authorization_design()})[
                "authorization_design"
            ],
            dict,
        )

    def test_new_production_gate_is_design_only_and_permanently_false(self):
        d = authorization_design()
        self.assertFalse(d["production_transport_authorized"])
        self.assertTrue(d["dev8_permanent_veto"])
        self.assertEqual(len(d["required_conditions"]), 8)

    def test_no_audit_module_has_service_or_mutation_or_command_execution_paths(self):
        banned = {
            "services",
            "async_call",
            "async_set",
            "async_remove",
            "async_update_entity",
            "async_update_device",
            "async_update_entry",
            "commit",
            "write_text",
            "write_bytes",
            "fence",
            "request_safe_disable",
            "apply",
        }
        for p in Path("custom_components/hpvc/site_audit").glob("*.py"):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(n.attr, banned, str(p))

    def test_projection_discards_config_entry_credentials_and_unrelated_sensor_values(
        self,
    ):
        b = sample()
        b["states"].append(
            dict(
                entity_id="sensor.private_location",
                state="secret location",
                attributes={},
            )
        )
        b["config_entries"][0]["data"] = {"password": "private-password"}
        result = project_observations(
            states=b["states"],
            entities=b["entity_registry"],
            devices=b["device_registry"],
            entries=b["config_entries"],
            ha_version="2026.10.4",
            now=NOW,
        )
        text = json.dumps(result)
        self.assertNotIn("private-password", text)
        self.assertNotIn("secret location", text)

    def test_invalid_duplicate_or_nonfinite_input_is_rejected(self):
        b = sample()
        b["states"].append(b["states"][0])
        with self.assertRaises(SchemaError):
            validate_export(b)
        b = sample()
        b["collected_at_utc"] = float("nan")
        with self.assertRaises(SchemaError):
            validate_export(b)


FAULTS = {
    "missing_registry": lambda b: b["entity_registry"][0].update(unique_id=""),
    "missing_device_owner": lambda b: b["device_registry"][0].update(config_entries=[]),
    "disabled_entry": lambda b: b["config_entries"][0].update(disabled_by="user"),
    "entry_unloaded": lambda b: b["config_entries"][0].update(state="not_loaded"),
    "API_serial_mismatch": lambda b: b["opendtu"][0].update(
        payload={
            "999999999999": dict(
                max_power=2000, limit_relative=100, limit_set_status="success"
            )
        }
    ),
    "API_endpoint_mismatch": lambda b: b["opendtu"][0].update(
        endpoint="http://wrong/api/limit/status"
    ),
    "API_stale": lambda b: b["opendtu"][0].update(
        received_at_utc=NOW - 60, poll_started_at_utc=NOW - 61
    ),
    "API_partial": lambda b: b["opendtu"][0]["payload"]["112233445566"].update(
        limit_relative=50
    ),
    "API_unsuccessful": lambda b: b["opendtu"][0]["payload"]["112233445566"].update(
        limit_set_status="pending"
    ),
    "unknown_flow": lambda b: b["legacy"].update(fingerprint="changed"),
    "runtime_unreachable": lambda b: b["legacy"]["runtime"].update(reachable=False),
    "bridge_incomplete": lambda b: b["legacy"]["bridge"].update(complete=False),
    "bridge_fields_missing": lambda b: b["legacy"]["bridge"].pop("queued"),
    "owner_mismatch": lambda b: b["legacy"]["bridge"].update(runtime_owner="old-owner"),
    "queued_work": lambda b: b["legacy"]["bridge"].update(queued=["queued"]),
    "possible_issue": lambda b: b["legacy"]["bridge"].update(
        potentially_issued=["unknown"]
    ),
    "pending_restore": lambda b: b["legacy"]["bridge"].update(
        restore_obligations=["restore"]
    ),
    "update_pending": lambda b: b["legacy"]["runtime"].update(pending_update=True),
    "HBC_owned": lambda b: b["legacy"]["bridge"].update(hbc_override_owned=True),
    "HBC_original_unknown": lambda b: b["legacy"]["bridge"].update(hbc_originals=None),
    "capture_stale": lambda b: b.update(collected_at_utc=NOW - 3600),
}
for name, change in FAULTS.items():

    def check(self, change=change):
        b = sample()
        change(b)
        r = audit_site(b, now=NOW)
        self.assertNotEqual(
            r["overall_verdict"], "READY_FOR_CONTROLLED_HANDOFF", r["blockers_unknowns"]
        )
        self.assertFalse(r["production_transport_authorized"])

    setattr(AuditTests, "test_fault_" + name, check)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_nonread_HA_command_is_denied_without_sending(self):
        ws = AsyncMock()
        client = ReadOnlyHAClient(ws)
        for cmd in (
            "call_service",
            "fire_event",
            "config/entity_registry/update",
            "config/device_registry/update",
            "config_entries/update",
            "config_entries/reload",
            "config_entries/disable",
            "lovelace/config/save",
            "nodered/deploy",
            "unknown",
        ):
            with self.assertRaises(SchemaError):
                await client.read(cmd)
        ws.send_json.assert_not_called()

    async def test_read_commands_have_no_extra_mutation_parameters(self):
        for kind in READ_COMMANDS:
            ws = AsyncMock()
            ws.receive_json.return_value = {
                "id": 1,
                "type": "result",
                "success": True,
                "result": [],
            }
            await ReadOnlyHAClient(ws).read(
                kind,
                entity_ids=["number.test"] if kind.endswith("get_entries") else None,
            )
            msg = ws.send_json.call_args.args[0]
            self.assertEqual(msg["type"], kind)
            self.assertLessEqual(set(msg), {"id", "type", "entity_ids"})

    async def test_failed_or_unmatched_read_cannot_be_treated_as_complete(self):
        ws = AsyncMock()
        ws.receive_json.return_value = {
            "id": 2,
            "type": "result",
            "success": True,
            "result": [],
        }
        with self.assertRaises(SchemaError):
            await ReadOnlyHAClient(ws).read("get_states")


class OriginTests(unittest.TestCase):
    def test_redirect_denied_before_authentication_and_HTTP_WS_schemes_normalize(self):
        from types import SimpleNamespace
        from audit_tools.protocol import validate_ws_origin

        validate_ws_origin(
            "ws://ha.example/api/websocket",
            SimpleNamespace(url="http://ha.example/api/websocket", history=()),
        )
        for url, history in [
            ("http://other.example/api/websocket", ()),
            ("http://ha.example/api/websocket", ("redirect",)),
            ("http://ha.example/wrong", ()),
        ]:
            with self.assertRaises(SchemaError):
                validate_ws_origin(
                    "ws://ha.example/api/websocket",
                    SimpleNamespace(url=url, history=history),
                )

    def test_unofficial_success_status_is_not_native_Ok(self):
        b = sample()
        b["opendtu"][0]["payload"]["112233445566"]["limit_set_status"] = "success"
        r = audit_site(b, now=NOW)
        self.assertFalse(r["expected_controllers"][0]["verified"])


class HelperCredentialTests(unittest.TestCase):
    def test_token_named_helper_and_embedded_authenticated_URL_are_redacted(self):
        data = {
            "entity_id": "input_text.hpvc_access_token",
            "state": "private-helper-value",
            "note": "failure at http://user:password@host/path?secret=private-query",
        }
        text = json.dumps(redact(data))
        for value in ("private-helper-value", "user:password", "private-query"):
            self.assertNotIn(value, text)


class NativeRepresentationTests(unittest.TestCase):
    def test_first_target_uses_native_step_origin_instead_of_manual_low_origin(self):
        b = sample()
        b["states"].extend(
            [
                dict(
                    entity_id="input_number.hpvc_pv2_full_limit",
                    state="1000",
                    last_reported=NOW,
                    last_updated=NOW,
                    attributes={},
                ),
                dict(
                    entity_id="input_number.hpvc_pv2_low_limit",
                    state="10",
                    last_reported=NOW,
                    last_updated=NOW,
                    attributes={},
                ),
            ]
        )
        next(r for r in b["states"] if r["entity_id"] == EXPECTED[1])["attributes"][
            "step"
        ] = 6
        result = audit_site(b, now=NOW)
        self.assertEqual(result["first_hardware_test"]["controller"], EXPECTED[1])
        self.assertEqual(result["first_hardware_test"]["proposed_test_limit_w"], 984)


class UniquePhysicalIdentityTests(unittest.TestCase):
    def test_two_entity_devices_with_same_serial_cannot_prove_two_inverters(self):
        b = sample()
        serial = "112233445566"
        b["entity_registry"][1]["unique_id"] = serial + "_limit_nonpersistent_absolute"
        b["device_registry"][1]["identifiers"] = [["mqtt", serial]]
        row = b["opendtu"][1]["payload"].pop("223344556677")
        b["opendtu"][1]["payload"][serial] = row
        r = audit_site(b, now=NOW)
        self.assertEqual(r["overall_verdict"], "BLOCKED")
        self.assertIsNone(r["first_hardware_test"]["controller"])


class PackageOwnershipTests(unittest.TestCase):
    def test_renamed_template_uses_exact_source_unique_ID_not_object_name(self):
        from audit_tools.site_audit import package_ownership

        b = sample()
        b["entity_registry"].append(
            {
                "entity_id": "sensor.user_renamed_status",
                "unique_id": "hpvc_installed_version",
                "platform": "template",
                "config_entry_id": None,
            }
        )
        proof = package_ownership(Path("home assistant/hpvc_config.yaml"), b)
        self.assertTrue(proof["approved_v16_package_match"])
        self.assertTrue(
            any(
                r["entity_id"] == "sensor.user_renamed_status"
                for r in proof["registry_ownership"]
            )
        )
        b["entity_registry"][-1]["config_entry_id"] = "unrelated-template-entry"
        self.assertFalse(
            package_ownership(Path("home assistant/hpvc_config.yaml"), b)[
                "registry_ownership"
            ]
        )

    def test_projection_keeps_renamed_HPVC_template_provenance(self):
        b = sample()
        b["entity_registry"].append(
            dict(
                entity_id="sensor.user_renamed_status",
                unique_id="hpvc_installed_version",
                platform="template",
                config_entry_id=None,
            )
        )
        r = project_observations(
            states=b["states"],
            entities=b["entity_registry"],
            devices=b["device_registry"],
            entries=b["config_entries"],
            ha_version="2026.10.4",
            now=NOW,
        )
        self.assertTrue(
            any(
                e["entity_id"] == "sensor.user_renamed_status"
                for e in r["entity_registry"]
            )
        )


class IndependentHelperHoldTests(unittest.TestCase):
    def test_quiet_runtime_cannot_override_observed_legacy_hold_or_HBC_fault(self):
        for name in (
            "input_boolean.hpvc_update_in_progress",
            "input_boolean.hpvc_update_reload_required",
            "input_boolean.hpvc_auto_resume_pending",
            "input_boolean.hpvc_negative_override_fault",
        ):
            b = sample()
            b["states"].append(
                dict(
                    entity_id=name,
                    state="on",
                    last_reported=NOW,
                    last_updated=NOW,
                    attributes={},
                )
            )
            r = audit_site(b, now=NOW)
            self.assertEqual(r["overall_verdict"], "BLOCKED")
            self.assertEqual(r["legacy"]["helper_indicators"][name], "on")
