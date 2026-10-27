"""Importer and bounded scheduler behavior against production code."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from custom_components.hpvc.control.models import *
from custom_components.hpvc.legacy import *
from custom_components.hpvc.storage import *
from custom_components.hpvc.coordinator import LifecycleOwner, EvaluationScheduler


# Explicit fixture values, never importer defaults for missing required settings.
def legacy_values(count="0"):
    values = {
        "input_number.hpvc_inverter_count": count,
        "input_boolean.hpvc_enabled": "on",
    }
    values.update(
        {
            "input_number.hpvc_" + key: str(getattr(ControlSettings(), key))
            for key in ControlSettings.__dataclass_fields__
        }
    )
    return values


class ImportTests(unittest.IsolatedAsyncioTestCase):
    def test_zero_and_missing_are_different(self):
        self.assertIsNotNone(build_preview(legacy_values(), "p").candidate)
        values = legacy_values()
        del values["input_number.hpvc_inverter_count"]
        self.assertIsNone(build_preview(values, "p").candidate)

    def test_malformed_counts(self):
        for value in ("1.5", "11", "-1", "NaN", "unavailable", ""):
            with self.subTest(value=value):
                self.assertTrue(build_preview(legacy_values(value), "p").issues)

    def test_malformed_threshold_not_defaulted(self):
        values = legacy_values()
        values["input_number.hpvc_pv_adjust_deadband"] = "garbage"
        self.assertTrue(build_preview(values, "p").issues)

    def test_enable_intent_is_not_imported_as_authority(self):
        preview = build_preview(legacy_values(), "p")
        self.assertTrue(preview.saved_enabled_intent)
        self.assertFalse(preview.candidate.enabled_intent)

    def test_all_232_mappings_unique(self):
        self.assertEqual(len(MAPPINGS), 232)
        self.assertEqual(len({row.source for row in MAPPINGS}), 232)
        self.assertEqual(
            next(
                row.destination
                for row in MAPPINGS
                if row.source == "input_boolean.hpvc_pv1_control_disabled"
            ),
            "switch.hpvc_pv1_control",
        )

    def test_helper_absence_is_not_fencing(self):
        self.assertEqual(detect_legacy({}), "unassessed")

    def test_partial_legacy_is_unknown(self):
        self.assertEqual(
            detect_legacy({"input_text.hpvc_status": "Idle"}), "legacy_presence_unknown"
        )

    def test_fingerprint_ignores_runtime_diagnostics(self):
        values = legacy_values()
        a = build_preview(values, "p")
        values["input_text.hpvc_status"] = "changed"
        self.assertEqual(a.transaction_id, build_preview(values, "p").transaction_id)

    def test_configuration_changes_fingerprint(self):
        values = legacy_values()
        a = build_preview(values, "p")
        values["input_number.hpvc_pv_adjust_deadband"] = "30"
        self.assertNotEqual(a.transaction_id, build_preview(values, "p").transaction_id)

    def controller_values(self):
        values = legacy_values("1")
        values.update(
            {
                "input_text.hpvc_pv1_limit_number": "number.inverter",
                "input_number.hpvc_pv1_full_limit": "2000",
                "input_number.hpvc_pv1_low_limit": "0",
            }
        )
        return values

    def test_controller_opt_out_and_auto_provenance(self):
        values = self.controller_values()
        values.update(
            {
                "input_boolean.hpvc_pv1_control_disabled": "on",
                "input_boolean.hpvc_pv1_auto_managed": "on",
                "input_text.hpvc_pv1_auto_identity": "enphase|number.inverter",
            }
        )
        preview = build_preview(values, "p")
        self.assertFalse(preview.issues)
        c = preview.candidate.controllers[0]
        self.assertFalse(c.control_enabled)
        self.assertTrue(c.auto_managed)
        self.assertEqual(len(preview.candidate.controllers), 1)

    def test_invalid_json_and_sequence_shape(self):
        for value in ("{", "[]", '{"x":NaN}'):
            values = self.controller_values()
            values["input_text.hpvc_pv1_fixed_data_json"] = value
            self.assertTrue(build_preview(values, "p").issues)
        values = self.controller_values()
        values["input_text.hpvc_pv1_pre_actions_json"] = "[42]"
        self.assertTrue(build_preview(values, "p").issues)

    async def test_idempotent_import_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = VersionedStore(
                Path(tmp) / "config.json", "configuration", ConfigurationState
            )
            await store.load()
            state = ConfigurationState(PlantConfiguration("p"))
            await store.commit(state, 0)
            preview = build_preview(legacy_values(), "p")
            state, _ = await persist_preview(store, state, preview, commit=True)
            revision = store.revision
            state, _ = await persist_preview(store, state, preview, commit=True)
            self.assertEqual(store.revision, revision)
            changed = legacy_values()
            changed["input_number.hpvc_pv_adjust_deadband"] = "30"
            with self.assertRaises(SchemaError):
                await persist_preview(
                    store, state, build_preview(changed, "p"), commit=True
                )
            loaded = await VersionedStore(
                Path(tmp) / "config.json", "configuration", ConfigurationState
            ).load()
            self.assertEqual(loaded.imports[0].stage, ImportStage.COMMITTED)

    async def test_invalid_preview_persisted_without_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = VersionedStore(
                Path(tmp) / "config.json", "configuration", ConfigurationState
            )
            await store.load()
            state = ConfigurationState(PlantConfiguration("p"))
            state, transaction = await persist_preview(
                store, state, build_preview({}, "p")
            )
            self.assertEqual(transaction.stage, ImportStage.INVALID)
            with self.assertRaises(SchemaError):
                await persist_preview(store, state, transaction, commit=True)

    def test_inactive_slot_configuration_is_preserved(self):
        values = legacy_values("0")
        values.update(
            {
                "input_text.hpvc_pv7_limit_number": "number.saved",
                "input_number.hpvc_pv7_full_limit": "1700",
                "input_number.hpvc_pv7_low_limit": "10",
            }
        )
        preview = build_preview(values, "p")
        self.assertFalse(preview.issues)
        self.assertEqual(preview.candidate.inverter_count, 0)
        self.assertEqual(preview.candidate.controllers[0].identity.slot, 7)
        self.assertEqual(preview.candidate.controllers[0].full_limit_w, 1700)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = LifecycleOwner()
        self.time = 0.0
        self.calls = []
        self.refreshes = 0
        self.active = 0
        self.max_active = 0

        async def refresh():
            self.refreshes += 1
            return self.refreshes

        async def evaluate(snapshot):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0)
            self.calls.append(snapshot)
            self.active -= 1

        self.scheduler = EvaluationScheduler(
            self.owner,
            refresh,
            evaluate,
            lambda a, b: False,
            lambda: False,
            clock=lambda: self.time,
            main_interval=1000,
            startup_delay=1000,
        )
        self.scheduler.start()

    async def asyncTearDown(self):
        await self.owner.close()

    async def drain(self):
        for _ in range(8):
            await asyncio.sleep(0)

    async def test_startup_barrier(self):
        self.scheduler.request_settings()
        await self.drain()
        self.assertEqual(self.calls, [])
        self.scheduler.startup_wake()
        await self.drain()
        self.assertEqual(len(self.calls), 1)

    async def test_telemetry_does_not_evaluate(self):
        for _ in range(1000):
            self.scheduler.mark_telemetry_dirty()
        await self.drain()
        self.assertEqual(self.refreshes, 0)

    async def test_stable_skip_and_forced_30_seconds(self):
        self.scheduler.startup_wake()
        await self.drain()
        for when in (10, 20, 30):
            self.time = when
            self.scheduler.timer_wake()
            await self.drain()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.scheduler.skipped_evaluations, 2)

    async def test_bounded_settings_coalescing_and_serialization(self):
        self.scheduler.startup_wake()
        for _ in range(1000):
            self.scheduler.request_settings()
        await self.drain()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.max_active, 1)

    async def test_lifecycle_cancels_arbitrary_workers_and_listeners(self):
        cleanup = []
        finished = asyncio.Event()

        async def worker():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        self.owner.add_cleanup(lambda: cleanup.append(True))
        self.owner.create_task(worker(), "hpvc-test-http-worker")
        await asyncio.sleep(0)
        await self.owner.close()
        self.assertTrue(finished.is_set())
        self.assertEqual(cleanup, [True])
        self.assertFalse(self.owner.tasks)
        self.assertTrue(all(handle.cancelled() for handle in self.scheduler._handles))

    async def test_no_work_after_unload(self):
        await self.owner.close()
        self.scheduler.startup_wake()
        self.scheduler.timer_wake()
        self.scheduler.request_settings()
        await self.drain()
        self.assertFalse(self.calls)

    def test_source_cadences(self):
        from custom_components.hpvc.const import (
            MAIN_INTERVAL,
            STARTUP_DELAY,
            FORCED_FULL_INTERVAL,
        )

        self.assertEqual(
            (MAIN_INTERVAL, STARTUP_DELAY, FORCED_FULL_INTERVAL), (10, 5, 30)
        )
