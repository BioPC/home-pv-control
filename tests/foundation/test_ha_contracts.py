"""Native wrapper contracts under explicit doubles. See tests/ha for real HA."""

import ast
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from ha_contract_harness import install, Hass, Entry

install()
from custom_components.hpvc import async_setup_entry, async_unload_entry
from custom_components.hpvc.config_flow import HpvcConfigFlow
from custom_components.hpvc.control.models import PlantConfiguration
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.const import DOMAIN
from custom_components.hpvc.entity import SWITCHES, NUMBERS, SELECTS, TEXTS
from custom_components.hpvc.legacy import build_preview
from test_import_scheduler import legacy_values


class HaContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hass = Hass(self.tmp.name)
        self.entry = Entry(
            {
                "plant_uid": "p",
                "initial_configuration": PlantConfiguration("p").to_dict(),
            }
        )

    async def asyncTearDown(self):
        if self.entry.runtime_data:
            await async_unload_entry(self.hass, self.entry)
        self.tmp.cleanup()

    async def test_setup_zero_controller_and_entities(self):
        self.assertTrue(await async_setup_entry(self.hass, self.entry))
        self.assertEqual(self.entry.runtime_data.configuration.inverter_count, 0)
        for key in (
            "switch.hpvc_enabled",
            "number.hpvc_inverter_count",
            "number.hpvc_export_start_threshold",
            "select.hpvc_selected_inverter",
            "text.hpvc_grid_power_sensor",
            "sensor.hpvc_migration_state",
            "sensor.hpvc_installed_version",
            "binary_sensor.hpvc_physical_writes_authorized",
            "binary_sensor.hpvc_recovery_required",
        ):
            self.assertIn(key, self.hass.entities)
        self.assertFalse(
            self.hass.entities["binary_sensor.hpvc_physical_writes_authorized"].is_on
        )

    async def test_enable_all_configuration_never_calls_services(self):
        await async_setup_entry(self.hass, self.entry)
        await self.hass.entities["switch.hpvc_enabled"].async_turn_on()
        await self.hass.entities["number.hpvc_inverter_count"].async_set_native_value(
            10
        )
        await self.hass.entities["text.hpvc_grid_power_sensor"].async_set_value(
            "sensor.grid"
        )
        await self.hass.entities["select.hpvc_selected_inverter"].async_select_option(
            "PV10"
        )
        await self.hass.entities["text.hpvc_pv1_action"].async_set_value(
            "number.set_value"
        )
        await self.hass.entities["text.hpvc_pv1_fixed_data_json"].async_set_value(
            '{"value": 0}'
        )
        runtime = self.entry.runtime_data
        runtime.scheduler.startup_wake()
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertTrue(runtime.configuration.enabled_intent)
        self.assertFalse(runtime.physical_writes_authorized)
        self.assertFalse(
            self.hass.entities["binary_sensor.hpvc_physical_writes_authorized"].is_on
        )
        self.hass.services.async_call.assert_not_called()

    async def test_reload_preserves_config_and_no_orphans(self):
        await async_setup_entry(self.hass, self.entry)
        await self.hass.entities["switch.hpvc_enabled"].async_turn_on()
        previous = self.entry.runtime_data
        await async_unload_entry(self.hass, self.entry)
        self.assertTrue(previous.owner.closed)
        self.assertFalse(previous.owner.tasks)
        self.assertFalse(self.hass.subscriptions)
        self.assertTrue(all(task.done() for task in self.entry.created_tasks))
        await async_setup_entry(self.hass, self.entry)
        self.assertTrue(self.entry.runtime_data.configuration.enabled_intent)
        self.assertFalse(self.entry.runtime_data.physical_writes_authorized)

    async def test_setup_failure_cleans_tasks_and_listeners(self):
        config = PlantConfiguration("p", grid_power_sensor="sensor.grid")
        self.entry.data["initial_configuration"] = config.to_dict()
        self.hass.fail_forward = True
        with self.assertRaises(RuntimeError):
            await async_setup_entry(self.hass, self.entry)
        self.assertFalse(self.hass.subscriptions)
        self.assertFalse(self.hass.entities)
        self.assertIsNone(self.entry.runtime_data)
        self.assertFalse(self.hass.data[DOMAIN])

    async def test_missing_existing_ledger_blocks_bootstrap(self):
        await async_setup_entry(self.hass, self.entry)
        await async_unload_entry(self.hass, self.entry)
        Path(self.tmp.name, ".storage", "hpvc_entry_execution.json").unlink()
        with self.assertRaises(Exception):
            await async_setup_entry(self.hass, self.entry)
        self.assertIsNone(self.entry.runtime_data)
        self.hass.services.async_call.assert_not_called()

    async def test_legacy_untouched_and_import_handoff_pending(self):
        values = legacy_values()
        for key, value in values.items():
            self.hass.states.set(key, value)
        preview = build_preview(values, "p")
        self.entry.data["legacy_import"] = preview.to_dict()
        self.entry.data["initial_configuration"] = preview.candidate.to_dict()
        before = {key: value.state for key, value in self.hass.states.values.items()}
        await async_setup_entry(self.hass, self.entry)
        self.assertEqual(self.entry.runtime_data.migration_state, "handoff_pending")
        self.assertFalse(self.entry.runtime_data.configuration.enabled_intent)
        self.assertEqual(
            before, {key: value.state for key, value in self.hass.states.values.items()}
        )
        self.hass.services.async_call.assert_not_called()

    async def test_text_and_numeric_validation(self):
        await async_setup_entry(self.hass, self.entry)
        for entity, value in (
            ("number.hpvc_inverter_count", 1.5),
            ("number.hpvc_pv_adjust_deadband", 0),
        ):
            with self.assertRaises(SchemaError):
                await self.hass.entities[entity].async_set_native_value(value)
        for entity, value in (
            ("text.hpvc_pv1_fixed_data_json", "[]"),
            ("text.hpvc_pv1_action", "not_an_action"),
        ):
            with self.assertRaises(SchemaError):
                await self.hass.entities[entity].async_set_value(value)

    async def test_listener_rebound_after_sensor_change(self):
        await async_setup_entry(self.hass, self.entry)
        entity = self.hass.entities["text.hpvc_grid_power_sensor"]
        await entity.async_set_value("sensor.first")
        self.assertEqual(len(self.hass.subscriptions), 1)
        await entity.async_set_value("sensor.second")
        self.assertEqual(len(self.hass.subscriptions), 1)
        self.assertEqual(
            next(iter(self.hass.subscriptions.values()))[0], ["sensor.second"]
        )

    async def test_native_ids_unique_and_complete(self):
        await async_setup_entry(self.hass, self.entry)
        settings = (*SWITCHES, *NUMBERS, *SELECTS, *TEXTS)
        self.assertEqual(
            len({(item.domain, item.key) for item in settings}), len(settings)
        )
        for setting in settings:
            self.assertIn(f"{setting.domain}.hpvc_{setting.key}", self.hass.entities)

    async def test_config_flow_zero_and_malformed(self):
        flow = HpvcConfigFlow()
        flow.hass = self.hass
        self.assertEqual((await flow.async_step_user())["type"], "form")
        result = await flow.async_step_user({"inverter_count": 0})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["initial_configuration"]["inverter_count"], 0)
        self.assertIn(
            "base", (await flow.async_step_user({"inverter_count": 1.5}))["errors"]
        )

    async def test_config_flow_import_preview_and_source_change(self):
        for key, value in legacy_values().items():
            self.hass.states.set(key, value)
        flow = HpvcConfigFlow()
        flow.hass = self.hass
        result = await flow.async_step_user({"import_legacy": True})
        self.assertEqual(result["step_id"], "legacy_preview")
        self.hass.states.set("input_number.hpvc_pv_adjust_deadband", "30")
        result = await flow.async_step_legacy_preview({"confirm": True})
        self.assertEqual(result["errors"]["base"], "legacy_changed")

    async def test_corrupt_store_never_becomes_empty(self):
        await async_setup_entry(self.hass, self.entry)
        await async_unload_entry(self.hass, self.entry)
        Path(self.tmp.name, ".storage", "hpvc_entry_execution.json").write_text(
            "{broken"
        )
        with self.assertRaises(Exception):
            await async_setup_entry(self.hass, self.entry)
        self.assertIsNone(self.entry.runtime_data)
        self.hass.services.async_call.assert_not_called()

    async def test_all_ownership_states_still_cannot_authorize_writes(self):
        from custom_components.hpvc.execution.models import OwnershipState

        await async_setup_entry(self.hass, self.entry)
        runtime = self.entry.runtime_data
        for state in OwnershipState:
            await runtime.ledger.update(
                lambda ledger: replace(
                    ledger, ownership=replace(ledger.ownership, state=state)
                )
            )
            self.assertFalse(runtime.physical_writes_authorized)
            self.assertFalse(
                self.hass.entities[
                    "binary_sensor.hpvc_physical_writes_authorized"
                ].is_on
            )
        self.hass.services.async_call.assert_not_called()


class SafetySourceTests(unittest.TestCase):
    def test_no_actuator_service_http_or_mqtt_calls_anywhere(self):
        base = Path("custom_components/hpvc")
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(
                        node.attr,
                        {"services", "async_call", "call_service", "mqtt_publish"},
                        str(path),
                    )
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [item.name for item in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""]
                    )
                    for name in names:
                        self.assertFalse(
                            name.startswith(
                                (
                                    "aiohttp",
                                    "requests",
                                    "homeassistant.components.mqtt",
                                    "homeassistant.helpers.service",
                                )
                            ),
                            str(path),
                        )
        # dev.5 permits a fake-only dispatcher, while the actuator/transport AST
        # bans above remain unchanged and apply to every new execution module.
        dispatchers = list(base.rglob("dispatcher.py"))
        self.assertEqual(dispatchers, [base / "execution/dispatcher.py"])
        self.assertIn("type(executor) is not FakeExecutor", dispatchers[0].read_text(encoding="utf-8"))
        # Concrete adapters may construct immutable plans, but have no execution methods.
        forbidden_methods = {
            "execute",
            "async_execute",
            "dispatch",
            "async_dispatch",
            "write_limit",
            "async_write_limit",
        }
        for path in (base / "inverter").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotIn(node.name, forbidden_methods, str(path))
        http = ast.parse((base / "inverter/hoymiles.py").read_text(encoding="utf-8"))
        gets = [
            node
            for node in ast.walk(http)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "session"
        ]
        self.assertEqual(len(gets), 1)
        self.assertEqual(gets[0].func.attr, "get")
        self.assertTrue(
            any(
                keyword.arg == "allow_redirects"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in gets[0].keywords
            )
        )

    def test_manifest_has_no_runtime_dependencies(self):
        data = json.loads(Path("custom_components/hpvc/manifest.json").read_text())
        self.assertEqual(data["requirements"], [])
        self.assertTrue(data["config_flow"])
