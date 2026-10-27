"""Durable migration acceptance and restart/failure matrix; no actuator calls."""

import ast
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from migration_fixture import LegacyFixture
from custom_components.hpvc.migration.model import (
    Stage,
    Inventory,
    NightEvidence,
    Handoff,
)
from custom_components.hpvc.migration.detector import detect, APPROVED_FINGERPRINT
from custom_components.hpvc.migration.handoff import HandoffEngine
from custom_components.hpvc.migration.imports import migration_manifest
from custom_components.hpvc.codec import SchemaError


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.f = await LegacyFixture(self.root).initialize()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_complete_handoff_is_durable_and_transport_closed(self):
        f = self.f
        h = await f.until(Stage.READY)
        self.assertTrue(h.native_owner_ready)
        self.assertFalse(h.production_transport_authorized)
        self.assertEqual(len(f.disable_calls), 1)
        self.assertEqual(len(f.fence_calls), 1)
        self.assertEqual(Handoff.from_dict(h.to_dict()), h)
        await f.restart()
        self.assertFalse(f.engine.current.native_owner_ready)
        self.assertEqual(f.engine.current.stage, Stage.POST)
        await f.until(Stage.READY)

    async def test_installed_engine_has_no_mutating_driver(self):
        e = HandoffEngine(self.root / "closed.json", "p", APPROVED_FINGERPRINT)
        await e.load()
        value = await e.advance(self.f.inventory(), self.f.clock())
        self.assertEqual(value.stage, Stage.BLOCKED)
        self.assertFalse(value.native_owner_ready)

    async def test_absent_helpers_disabled_master_and_zero_count_do_not_prove_absence(
        self,
    ):
        f = self.f
        for inv in (
            Inventory(f.clock()),
            replace(
                f.inventory(),
                known_nodes=(),
                helpers=(),
                heartbeat_boot="",
                runtime_status="unknown",
                managed_present=False,
                fingerprint="",
            ),
            replace(f.inventory(), reachable=False),
        ):
            self.assertEqual(
                detect(inv, f.clock(), APPROVED_FINGERPRINT)[0], Stage.UNKNOWN
            )

    async def test_post_disable_evaluation_is_required(self):
        f = self.f
        await f.until(Stage.QUIESCING)
        inv = f.inventory()
        b = replace(
            inv.bridge,
            master_off=True,
            disabled_at=f.clock().utc,
            evaluated_at=f.clock().utc,
        )
        value = await f.engine.advance(replace(inv, bridge=b), f.clock())
        self.assertEqual(value.stage, Stage.QUIESCING)

    async def test_replayed_bridge_challenge_blocks(self):
        f = self.f
        await f.until(Stage.IMPORT)
        old = f.inventory()
        await f.restart()
        value = await f.engine.advance(old, f.clock())
        self.assertEqual(value.stage, Stage.BLOCKED)

    async def test_transient_unavailability_requires_evidence_backed_recovery(self):
        f = self.f
        await f.until(Stage.IMPORT)
        f.reachable = False
        await f.step()
        self.assertEqual(f.engine.current.stage, Stage.BLOCKED)
        with self.assertRaises(SchemaError):
            await f.engine.recover(f.inventory(), f.clock())
        f.reachable = True
        await f.engine.recover(f.inventory(), f.clock())
        await f.until(Stage.READY)

    async def test_legacy_runtime_reappearance_revokes_ready(self):
        f = self.f
        await f.until(Stage.READY)
        f.fenced = False
        value = await f.step()
        self.assertEqual(value.stage, Stage.BLOCKED)
        self.assertFalse(value.native_owner_ready)

    async def test_old_Node_RED_backup_fence_generation_rejected(self):
        f = self.f
        await f.until(Stage.READY)
        f.fence_token = "old-backup-token"
        self.assertEqual((await f.step()).stage, Stage.BLOCKED)

    async def test_old_HA_backup_needs_fresh_challenge_and_checks(self):
        f = self.f
        await f.until(Stage.READY)
        old = f.inventory()
        await f.restart()
        self.assertFalse(f.engine.current.native_owner_ready)
        self.assertEqual((await f.engine.advance(old, f.clock())).stage, Stage.BLOCKED)

    async def test_configuration_changes_after_fence_block(self):
        f = self.f
        await f.until(Stage.POST)
        f.config_hash = "different"
        self.assertEqual((await f.step()).stage, Stage.BLOCKED)

    async def test_import_manifest_contains_values_disposition_and_warnings(self):
        f = self.f
        await f.until(Stage.IMPORT)
        rows = migration_manifest(f.tx)
        self.assertGreater(len(rows), 100)
        self.assertTrue(
            all(r.validation_result and r.external_reference_warning for r in rows)
        )
        row = next(
            r for r in rows if r.old_entity_id == "input_number.hpvc_inverter_count"
        )
        self.assertEqual(json.loads(row.imported_value_json), 1)

    async def test_night_reference_without_current_night_state_is_rejected(self):
        f = self.f
        await f.until(Stage.RECONCILING)
        f.unavailable = True
        now = f.clock()
        f.nights = (
            NightEvidence("night", f.binding, now, now.utc - 1, 3000, now, False, True),
        )
        self.assertEqual((await f.step()).stage, Stage.BLOCKED)

    async def test_approved_night_exception_still_requires_no_work_and_exact_binding(
        self,
    ):
        f = self.f
        await f.until(Stage.RECONCILING)
        f.unavailable = True
        now = f.clock()
        f.nights = (
            NightEvidence("night", f.binding, now, now.utc - 1, 3000, now, True, True),
        )
        self.assertEqual((await f.step()).stage, Stage.RESTORED)

    async def test_production_authorization_cannot_be_deserialized_true(self):
        with self.assertRaises(SchemaError):
            replace(self.f.engine.current, production_transport_authorized=True)

    async def test_native_active_label_cannot_assert_ready_or_transport(self):
        value = replace(self.f.engine.current, stage=Stage.ACTIVE)
        self.assertFalse(value.production_transport_authorized)
        with self.assertRaises(SchemaError):
            replace(value, native_owner_ready=True)

    async def test_failed_ready_commit_does_not_publish_ownership(self):
        f = self.f
        await f.until(Stage.POST)
        await f.step()
        original = f.engine.store.commit

        async def fail(value, revision):
            if value.native_owner_ready:
                raise OSError("controlled fsync failure")
            await original(value, revision)

        with patch.object(f.engine.store, "commit", side_effect=fail):
            with self.assertRaises(OSError):
                await f.step()
        self.assertFalse(f.engine.current.native_owner_ready)
        await f.restart()
        await f.until(Stage.READY)

    async def test_crash_after_fixture_fence_does_not_repeat_effect(self):
        f = self.f
        await f.until(Stage.FENCING)
        original = f.engine.store.commit

        async def fail(value, revision):
            if value.stage == Stage.POST:
                raise OSError("after fixture fence")
            await original(value, revision)

        with patch.object(f.engine.store, "commit", side_effect=fail):
            with self.assertRaises(OSError):
                await f.step()
        self.assertTrue(f.fenced)
        await f.restart()
        await f.until(Stage.READY)
        self.assertEqual(len(f.fence_calls), 1)

    async def test_no_runtime_fixture_capability_construction(self):
        for p in Path("custom_components/hpvc").rglob("*.py"):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    self.assertNotEqual(n.func.id, "_FixturePermit")


FAULTS = {
    "active": ("active", ("issued",)),
    "queued": ("queued", ("queued",)),
    "possibly_issued": ("possible", ("uncertain",)),
    "pending_verification": ("pending", ("pending",)),
    "restore_obligation": ("obligations", ("restore",)),
    "HBC_owned": ("hbc_owned", True),
    "HBC_unavailable": ("hbc_available", False),
    "HBC_unrestored": ("hbc_restored", False),
    "HBC_changed": ("hbc_current", ("Charge", "batteries are full")),
    "HBC_stale": ("hbc_stale", True),
    "stale_full": ("proof_stale", True),
    "partial_limit": ("native_value", 2000),
    "invalid_number": ("native_value", float("nan")),
    "cold_context": ("complete", False),
    "runtime_unavailable": ("reachable", False),
    "changed_flow": ("fingerprint", "changed"),
    "runtime_restarted": ("runtime_boot", "newboot"),
    "pending_update": ("pending_update", True),
    "recovery": ("recovery_pending", True),
    "lost_safety": ("safety_unknown", True),
    "controller_missing": ("current_bindings", ()),
}
for name, (field, value) in FAULTS.items():

    async def check(self, field=field, value=value):
        f = self.f
        await f.until(Stage.RECONCILING)
        setattr(f, field, value)
        result = await f.step()
        self.assertEqual(result.stage, Stage.BLOCKED)
        self.assertFalse(result.native_owner_ready)
        self.assertFalse(f.fenced)

    setattr(MigrationTests, "test_fault_" + name, check)

for stage in (
    Stage.UNASSESSED,
    Stage.DETECTED,
    Stage.IMPORT,
    Stage.QUIESCING,
    Stage.RECONCILING,
    Stage.RESTORED,
    Stage.FENCING,
    Stage.POST,
    Stage.READY,
):

    async def restart(self, stage=stage):
        f = self.f
        await f.until(stage)
        await f.restart()
        await f.until(Stage.READY)
        self.assertFalse(f.engine.current.production_transport_authorized)

    setattr(MigrationTests, "test_restart_" + stage.value, restart)


for name, (field, value) in FAULTS.items():

    async def blocked_restart(self, field=field, value=value):
        f = self.f
        await f.until(Stage.RECONCILING)
        setattr(f, field, value)
        await f.step()
        await f.restart()
        self.assertFalse(f.engine.current.native_owner_ready)
        self.assertEqual((await f.step()).stage, Stage.BLOCKED)

    setattr(MigrationTests, "test_restart_with_" + name, blocked_restart)


async def ready_disabled(self):
    f = self.f
    await f.until(Stage.READY)
    f.at += 2
    value = await f.engine.advance(
        f.inventory(),
        f.clock(),
        bindings=f.current_bindings,
        configuration_fingerprint=f.config_hash,
        proofs=f.proofs(),
        finish_disabled=True,
    )
    self.assertEqual(value.stage, Stage.DISABLED)
    self.assertTrue(value.native_owner_ready)
    self.assertFalse(value.production_transport_authorized)
    await f.restart()
    self.assertFalse(f.engine.current.native_owner_ready)


MigrationTests.test_ready_disabled_still_requires_post_restart_proof = ready_disabled
