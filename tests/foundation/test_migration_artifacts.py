"""Registry CAS, import/history and native dashboard migration contracts."""

import json
import tempfile
from pathlib import Path
from dataclasses import replace
import unittest
from unittest.mock import patch
from migration_fixture import LegacyFixture
from custom_components.hpvc.migration.model import Stage
from custom_components.hpvc.migration.registry import (
    RegistryIdentity,
    plan_registry_migration,
    RegistryMigrator,
)
from custom_components.hpvc.migration.dashboard import native_dashboard
from custom_components.hpvc.migration.imports import migration_manifest
from custom_components.hpvc.migration.bridge import decode_context_export, REQUIRED
from custom_components.hpvc.storage import HistoryState
from custom_components.hpvc.codec import SchemaError


class FakeRegistry:
    def __init__(self, rows):
        self.rows = {r.entity_id: r for r in rows}

    def async_get(self, key):
        return self.rows.get(key)

    def async_update_entity(self, key, new_entity_id):
        assert new_entity_id not in self.rows
        r = self.rows.pop(key)
        self.rows[new_entity_id] = replace(r, entity_id=new_entity_id)


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.f = await LegacyFixture(self.root).initialize()
        self.old = RegistryIdentity(
            "sensor.hpvc_status", "hpvc-v16-status", "template", "legacy-entry"
        )
        self.native = RegistryIdentity(
            "sensor.hpvc_status_2", "migration-test:status", "hpvc", "native-entry"
        )
        self.rows = (self.old, self.native)

    async def asyncTearDown(self):
        self.temp.cleanup()

    def plan(self):
        return plan_registry_migration(
            self.rows,
            self.old,
            self.native,
            "sensor.hpvc_status",
            ownership_manifest=(self.old,),
        )

    async def migrator(self):
        await self.f.until(Stage.READY)
        self.registry = FakeRegistry(self.rows)
        m = RegistryMigrator(
            self.root / "registry.json",
            self.f.engine.current.transaction_id,
            registry=self.registry,
            permit=self.f.permit,
        )
        await m.load()
        return m

    async def test_normal_owned_entity_migration_and_repeat_are_idempotent(self):
        m = await self.migrator()
        plan = self.plan()
        await m.apply(plan, self.f.engine.current)
        self.assertEqual(
            self.registry.async_get("sensor.hpvc_status").unique_id,
            self.native.unique_id,
        )
        await m.apply(plan, self.f.engine.current)
        self.assertEqual(len(self.registry.rows), 2)

    async def test_renamed_legacy_is_preserved_when_desired_free(self):
        old = replace(self.old, entity_id="sensor.user_renamed_hpvc")
        moves = plan_registry_migration(
            (old, self.native),
            old,
            self.native,
            "sensor.hpvc_status",
            ownership_manifest=(old,),
        )
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].identity, self.native)

    async def test_unrelated_collision_is_never_seized(self):
        with self.assertRaises(SchemaError):
            plan_registry_migration(
                self.rows,
                self.old,
                self.native,
                "sensor.hpvc_status",
                ownership_manifest=(),
            )
        unrelated = replace(self.old, unique_id="another-user")
        with self.assertRaises(SchemaError):
            plan_registry_migration(
                (unrelated, self.native),
                self.old,
                self.native,
                "sensor.hpvc_status",
                ownership_manifest=(self.old,),
            )

    async def test_cross_domain_registry_move_rejected(self):
        with self.assertRaises(SchemaError):
            plan_registry_migration(
                self.rows,
                self.old,
                self.native,
                "switch.hpvc_status",
                ownership_manifest=(self.old,),
            )

    async def test_interrupted_apply_reconciles_exact_completed_move(self):
        m = await self.migrator()
        plan = self.plan()
        original = m.store.commit

        async def fail(value, revision):
            if value.applied == 1:
                raise OSError("after registry update")
            await original(value, revision)

        with patch.object(m.store, "commit", side_effect=fail):
            with self.assertRaises(OSError):
                await m.apply(plan, self.f.engine.current)
        await m.load()
        await m.apply(plan, self.f.engine.current)
        self.assertEqual(
            self.registry.async_get("sensor.hpvc_status").unique_id,
            self.native.unique_id,
        )

    async def test_rollback_restores_original_mapping(self):
        m = await self.migrator()
        await m.apply(self.plan(), self.f.engine.current)
        await m.rollback()
        self.assertEqual(
            tuple(sorted(self.registry.rows)),
            tuple(sorted(r.entity_id for r in self.rows)),
        )
        with self.assertRaises(SchemaError):
            await m.apply(self.plan(), self.f.engine.current)

    async def test_rollback_collision_leaves_unrelated_entity(self):
        m = await self.migrator()
        await m.apply(self.plan(), self.f.engine.current)
        self.registry.rows[self.native.entity_id] = replace(
            self.native, unique_id="unrelated"
        )
        with self.assertRaises(SchemaError):
            await m.rollback()
        self.assertEqual(
            self.registry.rows[self.native.entity_id].unique_id, "unrelated"
        )

    async def test_registry_requires_owner_ready_even_with_fixture_permit(self):
        m = await self.migrator()
        with self.assertRaises(SchemaError):
            await m.apply(
                self.plan(),
                replace(
                    self.f.engine.current, stage=Stage.POST, native_owner_ready=False
                ),
            )

    async def test_current_day_history_and_configuration_finalize(self):
        f = self.f
        history = replace(
            f.history,
            local_date="2026-10-27",
            insights_json='[{"price":0.1}]',
            report_history_json='{"summary":"retained"}',
        )
        f.config, item, got = await f.finalizer.commit(
            f.cs,
            f.config,
            f.tx,
            f.hs,
            f.history,
            today="2026-10-27",
            export={"source_version": "1.6.0", "history": history.to_dict()},
        )
        self.assertEqual(got, history)
        revision = f.hs.revision
        f.config, item, got = await f.finalizer.commit(
            f.cs,
            f.config,
            f.tx,
            f.hs,
            got,
            today="2026-10-27",
            export={"source_version": "1.6.0", "history": history.to_dict()},
        )
        self.assertEqual(f.hs.revision, revision)
        self.assertTrue(f.finalizer.current.completed)

    async def test_prior_day_history_not_imported(self):
        f = self.f
        history = replace(f.history, local_date="2026-10-26")
        with self.assertRaises(SchemaError):
            await f.finalizer.commit(
                f.cs,
                f.config,
                f.tx,
                f.hs,
                f.history,
                today="2026-10-27",
                export={"source_version": "1.6.0", "history": history.to_dict()},
            )
        self.assertIsNone((await f.hs.load()).local_date)

    async def test_different_plant_history_rejected(self):
        f = self.f
        history = HistoryState("other", local_date="2026-10-27")
        with self.assertRaises(SchemaError):
            await f.finalizer.commit(
                f.cs,
                f.config,
                f.tx,
                f.hs,
                f.history,
                today="2026-10-27",
                export={"source_version": "1.6.0", "history": history.to_dict()},
            )

    async def test_repeated_import_preserves_later_native_edit(self):
        f = self.f
        await f.until(Stage.IMPORT)
        native = replace(
            f.config, configuration=replace(f.config.configuration, notifications=False)
        )
        await f.cs.commit(native, f.cs.revision)
        state, _, _ = await f.finalizer.commit(
            f.cs, native, f.tx, f.hs, f.history, today="2026-10-27"
        )
        self.assertFalse(state.configuration.notifications)

    async def test_manifest_contains_actual_renamed_native_mapping(self):
        f = self.f
        rows = migration_manifest(
            f.tx, {"switch.hpvc_enabled": "switch.user_native_hpvc"}
        )
        row = next(r for r in rows if r.old_entity_id == "input_boolean.hpvc_enabled")
        self.assertEqual(row.new_entity_id, "switch.user_native_hpvc")

    async def test_native_dashboard_uses_actual_mapping_and_preserves_sections(self):
        d = native_dashboard(
            {"sensor.hpvc_status": "sensor.my_native_status"}, self.f.tx.candidate
        )
        text = json.dumps(d)
        self.assertIn("sensor.my_native_status", text)
        self.assertNotIn('sensor.hpvc_status"', text)
        self.assertEqual(len([v for v in d["views"] if v["path"].startswith("pv")]), 10)
        self.assertTrue(
            {"Insights", "Reports", "Power Control", "Price Interval"}
            <= {v["title"] for v in d["views"]}
        )
        self.assertIn("No inverters", text)
        self.assertIn("controller_ui_json", text)
        self.assertIn("Limit entity", text)
        self.assertIn("```text", text)
        self.assertIn("numeric_state", text)
        self.assertIn("Manual controller settings", text)

    async def test_dashboard_rejects_untrusted_entity_string(self):
        with self.assertRaises(SchemaError):
            native_dashboard({"sensor.hpvc_status": "sensor.x')}}bad"})

    async def test_bridge_missing_context_never_means_quiescent(self):
        with self.assertRaises(SchemaError):
            decode_context_export(
                {"schema": "hpvc-migration/1.6.0/1", "complete": False},
                observed=self.f.clock(),
                controller_bindings=(),
                hbc_original=("a", "b"),
                hbc_current=("a", "b"),
                hbc_observed=self.f.clock(),
                hbc_available=True,
                master_off=True,
            )

    async def test_disabled_tabs_alone_do_not_prove_fencing(self):
        f = self.f
        now = f.clock()
        raw = {k: None for k in REQUIRED}
        raw.update(
            homePvControlAdapterRuntimeOwner="b",
            homePvControlAdapterRequests={},
            homePvControlAdapterScheduler={"busy": None, "queue": []},
            homePvControlDisableRestoreState={"active": False},
            homePvControlAdapterSafetyBlocked=False,
            homePvControlAdapterResync=False,
            homePvControlUninstallShutdownStartedAt=now.utc * 1000 - 2000,
            homePvControlUninstallShutdownLastEvaluationAt=now.utc * 1000,
        )
        export = dict(
            schema="hpvc-migration/1.6.0/1",
            complete=True,
            raw=raw,
            runtimeBoot="b",
            transactionId="t",
            challenge="c",
            fingerprint="f",
            commandTabsDisabled=True,
        )
        b = decode_context_export(
            export,
            observed=now,
            controller_bindings=(),
            hbc_original=("a", "b"),
            hbc_current=("a", "b"),
            hbc_observed=now,
            hbc_available=True,
            master_off=True,
        )
        self.assertTrue(b.quiescent)
        self.assertTrue(b.command_capability)
        self.assertFalse(b.auto_resume_blocked)

    async def test_registry_restore_of_old_backup_invalidates_completed_journal(self):
        m = await self.migrator()
        await m.apply(self.plan(), self.f.engine.current)
        self.registry.rows = {r.entity_id: r for r in self.rows}
        with self.assertRaises(SchemaError):
            await m.apply(self.plan(), self.f.engine.current)

    async def test_interrupted_history_result_commit_reconciles_written_payload(self):
        f = self.f
        history = replace(
            f.history, local_date="2026-10-27", insights_json='[{"retained":true}]'
        )
        export = {"source_version": "1.6.0", "history": history.to_dict()}
        original = f.finalizer.store.commit

        async def fail(value, revision):
            if value.completed:
                raise OSError("after history write")
            await original(value, revision)

        with patch.object(f.finalizer.store, "commit", side_effect=fail):
            with self.assertRaises(OSError):
                await f.finalizer.commit(
                    f.cs,
                    f.config,
                    f.tx,
                    f.hs,
                    f.history,
                    today="2026-10-27",
                    export=export,
                )
        f.config = await f.cs.load()
        f.history = await f.hs.load()
        await f.finalizer.load()
        revision = f.hs.revision
        _, _, got = await f.finalizer.commit(
            f.cs, f.config, f.tx, f.hs, f.history, today="2026-10-27", export=export
        )
        self.assertEqual(got, history)
        self.assertEqual(f.hs.revision, revision)
