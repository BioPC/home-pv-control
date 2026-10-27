"""Dependency-free behavioral tests of real production model/storage code."""

import asyncio
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.control.models import *
from custom_components.hpvc.execution.models import *
from custom_components.hpvc.hbc.models import *
from custom_components.hpvc.reports import ReportSnapshot
from custom_components.hpvc.storage import *


class ModelTests(unittest.TestCase):
    def test_all_approved_boundaries_round_trip(self):
        config = PlantConfiguration("plant")
        identity = ControllerIdentity("device", 1)
        snapshot = PlantSnapshot(
            "snapshot", 1.0, 1, (Observation("grid", 0.0, Quality.VALID),)
        )
        op = PhysicalOperation(
            "op",
            "batch",
            "step",
            "epoch",
            "device",
            "generic_number",
            "signature",
            "config:1",
        )
        records = [
            config,
            Observation("missing"),
            Observation("zero", 0.0, Quality.VALID),
            snapshot,
            identity,
            ControllerConfiguration(identity, "signature"),
            ControllerObservation(identity, Observation("limit")),
            ExecutionSnapshot(),
            PolicyDecision("evaluation"),
            AllocationResult("evaluation", 1500.0, 1200.0),
            RepresentedPlan("evaluation", 1500.0, 1200.0, 1190.0),
            CommandBatch("batch", "evaluation", "device", "signature", "sequence"),
            op,
            VerificationEvidence(
                "proof", "device", "signature", "op", "ha", VerificationStatus.PENDING
            ),
            RestoreObligation(
                "restore", "device", "signature", "config:1", "disable", 2000.0
            ),
            NightRestoreState(),
            HbcState(),
            ReportSnapshot(
                "report", config, snapshot, ExecutionSnapshot(), HbcState(), 0
            ),
            ImportTransaction("import", "fingerprint", ImportStage.DETECTED, None),
            HandoffRecord(),
            ExecutionLedger("plant"),
        ]
        for record in records:
            with self.subTest(model=type(record).__name__):
                self.assertEqual(type(record).from_dict(record.to_dict()), record)

    def test_models_are_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            PlantConfiguration("plant").inverter_count = 2

    def test_zero_is_not_unknown(self):
        self.assertNotEqual(
            Observation("grid", 0.0, Quality.VALID), Observation("grid")
        )

    def test_invalid_count(self):
        for count in (-1, 11, 1.5, True):
            with self.subTest(count=count), self.assertRaises(SchemaError):
                PlantConfiguration("plant", inverter_count=count)

    def test_threshold_order(self):
        with self.assertRaises(SchemaError):
            ControlSettings(export_start_threshold=0.0, export_stop_threshold=0.0)

    def test_unknown_fields_enum_and_nonfinite_rejected(self):
        data = Observation("grid").to_dict()
        for change in (
            {"quality": "invented"},
            {"value": float("nan")},
            {"value": True},
            {"extra": 1},
        ):
            with self.subTest(change=change), self.assertRaises(SchemaError):
                Observation.from_dict(data | change)

    def test_unknown_missing_fields(self):
        with self.assertRaises(SchemaError):
            PlantConfiguration.from_dict({"plant_uid": "p"})

    def test_separate_target_stages(self):
        plan = RepresentedPlan("e", 1700.0, 1500.0, 1480.0)
        self.assertEqual(
            (
                plan.requested_plant_target_w,
                plan.allocated_plant_target_w,
                plan.representable_plant_target_w,
            ),
            (1700, 1500, 1480),
        )

    def test_authorization_not_deserializable(self):
        with self.assertRaises(SchemaError):
            ExecutionSnapshot.from_dict(
                ExecutionSnapshot().to_dict() | {"physical_writes_authorized": True}
            )
        self.assertIs(
            ExecutionSnapshot(recovery_required=False).physical_writes_authorized, False
        )

    def test_wrong_controller_evidence_rejected(self):
        proof = VerificationEvidence(
            "proof",
            "wrong",
            "sig",
            "op",
            "ha",
            VerificationStatus.VERIFIED,
            100.0,
            1.0,
            None,
            2.0,
        )
        op = PhysicalOperation(
            "op",
            "b",
            "s",
            "epoch",
            "device",
            "generic_number",
            "sig",
            "config",
            representable_controller_target_w=100.0,
            state=OperationState.VERIFIED,
            verification=VerificationStatus.VERIFIED,
            evidence_ids=("proof",),
        )
        with self.assertRaises(SchemaError):
            ExecutionLedger("p", operations=(op,), evidence=(proof,))

    def test_command_cache_never_proof(self):
        with self.assertRaises(SchemaError):
            RestoreObligation(
                "r",
                "device",
                "sig",
                "cfg",
                "disable",
                100.0,
                state=ObligationState.VERIFIED,
            )

    def test_strict_json_duplicate_and_nan(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(SchemaError):
                strict_json(raw)


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.json"
        self.store = VersionedStore(self.path, "execution", ExecutionLedger)
        self.repo = LedgerRepository(self.store, "plant")
        await self.repo.load()

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def op(self, key="op"):
        return PhysicalOperation(
            key, "batch", "step", "epoch", "device", "generic_number", "sig", "config:1"
        )

    async def test_atomic_commit_and_restart(self):
        await self.repo.register_operation(self.op())
        new = LedgerRepository(
            VersionedStore(self.path, "execution", ExecutionLedger), "plant"
        )
        await new.load()
        self.assertEqual(new.current, self.repo.current)

    async def test_serialized_concurrent_commits(self):
        await asyncio.gather(
            *(self.repo.register_operation(self.op(str(i))) for i in range(20))
        )
        self.assertEqual(len(self.repo.current.operations), 20)
        self.assertEqual(self.store.revision, 20)

    async def test_compare_and_swap(self):
        await self.repo.register_operation(self.op())
        with self.assertRaises(RevisionConflict):
            await self.store.commit(self.repo.current, 0)

    async def test_replace_failure_preserves_old_file_and_poisoned_store(self):
        await self.repo.register_operation(self.op())
        original = self.path.read_bytes()
        with patch(
            "custom_components.hpvc.storage.os.replace",
            side_effect=OSError("crash before replace"),
        ):
            with self.assertRaises(OSError):
                await self.repo.register_operation(self.op("next"))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.store.healthy)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        with self.assertRaises(StorageError):
            await self.repo.register_operation(self.op("third"))

    async def test_fsync_failure_never_publishes(self):
        with patch(
            "custom_components.hpvc.storage.os.fsync",
            side_effect=OSError("sync failed"),
        ):
            with self.assertRaises(OSError):
                await self.repo.register_operation(self.op())
        self.assertFalse(self.path.exists())

    async def test_corrupt_and_future_schema_fail_closed(self):
        await self.repo.register_operation(self.op())
        raw = json.loads(self.path.read_text())
        for changed in (
            b"{",
            json.dumps(raw | {"schema_version": 99}).encode(),
            json.dumps(raw | {"sha256": "wrong"}).encode(),
        ):
            self.path.write_bytes(changed)
            with self.assertRaises(StorageError):
                await VersionedStore(self.path, "execution", ExecutionLedger).load()

    async def test_wrong_plant_rejected(self):
        await self.repo.register_operation(self.op())
        with self.assertRaises(StorageError):
            await LedgerRepository(
                VersionedStore(self.path, "execution", ExecutionLedger), "other"
            ).load()

    async def test_armed_restart_stays_unknown(self):
        await self.repo.register_operation(self.op())
        await self.repo.transition_operation(
            "op", OperationState.ARMED, armed_at_utc=1.0
        )
        await self.repo.reconcile_restart()
        self.assertEqual(self.repo.current.operations[0].state, OperationState.UNKNOWN)
        self.assertTrue(self.repo.recovery_required)

    async def test_illegal_supersession(self):
        await self.repo.register_operation(self.op())
        await self.repo.transition_operation(
            "op", OperationState.ARMED, armed_at_utc=1.0
        )
        with self.assertRaises(SchemaError):
            await self.repo.transition_operation("op", OperationState.SUPERSEDED)

    async def test_identity_cannot_mutate(self):
        await self.repo.register_operation(self.op())
        with self.assertRaises(SchemaError):
            await self.repo.transition_operation(
                "op", OperationState.ARMED, controller_uid="different"
            )

    async def test_removed_controller_obligation_survives(self):
        obligation = RestoreObligation(
            "restore", "removed", "sig", "config:old", "disable", 1500.0
        )
        await self.repo.update(
            lambda ledger: replace(ledger, restore_obligations=(obligation,))
        )
        await self.repo.reconcile_restart()
        self.assertEqual(self.repo.current.restore_obligations, (obligation,))
        self.assertTrue(self.repo.recovery_required)

    async def test_night_active_persists_but_partial_windows_reset(self):
        await self.repo.update(
            lambda ledger: replace(
                ledger, night_restore=NightRestoreState(True, 1.0, 2.0, 3.0)
            )
        )
        await self.repo.reconcile_restart()
        night = self.repo.current.night_restore
        self.assertTrue(night.active)
        self.assertIsNone(night.recovery_candidate_since_utc)
        self.assertIsNone(night.entry_candidate_since_utc)

    async def test_hbc_and_maintenance_persist(self):
        hbc = HbcOverrideRecovery(
            phase=OverridePhase.UNKNOWN_PREVIOUS, fault="unknown previous"
        )
        await self.repo.update(
            lambda ledger: replace(
                ledger,
                hbc_override=hbc,
                maintenance=MaintenanceRecord(state=MaintenanceState.RESTORING),
            )
        )
        await self.repo.reconcile_restart()
        self.assertEqual(self.repo.current.hbc_override, hbc)
        self.assertEqual(self.repo.current.maintenance.state, MaintenanceState.BLOCKED)

    async def test_evidence_is_bounded(self):
        for i in range(130):
            await self.repo.add_evidence(
                VerificationEvidence(
                    str(i), "device", "sig", None, "ha", VerificationStatus.PENDING
                )
            )
        self.assertEqual(len(self.repo.current.evidence), 128)

    async def test_history_schema_separate(self):
        path = self.path.with_name("history.json")
        store = VersionedStore(path, "history", HistoryState)
        await store.load()
        await store.commit(HistoryState("plant"), 0)
        with self.assertRaises(StorageError):
            await VersionedStore(path, "execution", ExecutionLedger).load()

    async def test_cancellation_waits_for_io_worker(self):
        started = threading.Event()
        release = threading.Event()
        from custom_components.hpvc.storage import atomic_replace as real

        def slow(path, data):
            started.set()
            release.wait(2)
            real(path, data)

        with patch("custom_components.hpvc.storage.atomic_replace", side_effect=slow):
            task = asyncio.create_task(self.repo.register_operation(self.op()))
            await asyncio.to_thread(started.wait, 1)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        loaded = await VersionedStore(self.path, "execution", ExecutionLedger).load()
        self.assertEqual(loaded.operations[0].operation_id, "op")
        self.assertFalse(
            any(
                t.get_name() == "hpvc-storage-io" and not t.done()
                for t in asyncio.all_tasks()
            )
        )

    async def test_cannot_discard_unresolved_work(self):
        await self.repo.register_operation(self.op())
        with self.assertRaises(SchemaError):
            await self.repo.update(lambda ledger: replace(ledger, operations=()))
        obligation = RestoreObligation(
            "restore", "device", "sig", "config:1", "disable", 100.0
        )
        await self.repo.update(
            lambda ledger: replace(ledger, restore_obligations=(obligation,))
        )
        with self.assertRaises(SchemaError):
            await self.repo.update(
                lambda ledger: replace(ledger, restore_obligations=())
            )

    async def test_direct_update_cannot_skip_operation_lifecycle(self):
        await self.repo.register_operation(self.op())
        with self.assertRaises(SchemaError):
            await self.repo.update(
                lambda ledger: replace(
                    ledger,
                    operations=(
                        replace(
                            ledger.operations[0], state=OperationState.RECOVERY_REQUIRED
                        ),
                    ),
                )
            )

    async def test_unknown_execution_blocks_another_armed_operation(self):
        await self.repo.register_operation(self.op())
        await self.repo.transition_operation(
            "op", OperationState.ARMED, armed_at_utc=1.0
        )
        await self.repo.reconcile_restart()
        await self.repo.register_operation(self.op("next"))
        with self.assertRaises(SchemaError):
            await self.repo.transition_operation(
                "next", OperationState.ARMED, armed_at_utc=2.0
            )

    async def test_crash_after_replace_reloads_durable_candidate(self):
        from custom_components.hpvc.storage import atomic_replace as real

        def replaced_then_crashed(path, content):
            real(path, content)
            raise OSError("crash after replacement")

        with patch(
            "custom_components.hpvc.storage.atomic_replace",
            side_effect=replaced_then_crashed,
        ):
            with self.assertRaises(OSError):
                await self.repo.register_operation(self.op())
        repo = LedgerRepository(
            VersionedStore(self.path, "execution", ExecutionLedger), "plant"
        )
        await repo.load()
        self.assertEqual(repo.current.operations[0].operation_id, "op")
        self.assertTrue(repo.recovery_required)

    async def test_command_cache_cannot_be_verified_evidence(self):
        with self.assertRaises(SchemaError):
            VerificationEvidence(
                "e",
                "device",
                "sig",
                "op",
                "command-cache",
                VerificationStatus.VERIFIED,
                100.0,
            )

    async def test_invalid_accuracy_schema_is_not_history_success(self):
        with self.assertRaises(SchemaError):
            HistoryState("plant", accuracy_json='{"eligibilitySchema": 10}')
