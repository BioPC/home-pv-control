"""Crashes at every durable lifecycle boundary: reload never replays ambiguity."""

from dataclasses import replace
import unittest
from dispatch_support import Harness
from custom_components.hpvc.execution.dispatcher import Dispatcher
from custom_components.hpvc.execution.executor import FakeExecutor
from custom_components.hpvc.execution.models import OperationState as S, Lane

BOUNDARIES = (
    "before_prepared_commit",
    "after_prepared_commit",
    "after_armed_commit",
    "before_executor_call",
    "after_executor_call_before_inflight",
    "after_inflight_commit",
    "after_service_completed",
    "before_verification",
    "after_verification",
)


class RestartTests(unittest.IsolatedAsyncioTestCase):
    pass


def case(boundary):
    async def test(self):
        h = await Harness().start()

        class Crash(Exception):
            pass

        async def checkpoint(name, op):
            if name == boundary:
                raise Crash(name)

        h.dispatch.checkpoint = checkpoint
        try:
            try:
                await h.submit()
                req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
                await h.dispatch.receive_completion(h.completion(req))
                await h.verify(req)
            except Crash:
                pass
            else:
                self.fail("Boundary not reached " + boundary)
            called = len(h.fake.requests)
            await h.dispatch.close()
            new = Dispatcher(
                h.prefix, h.ledger, h.runtime, FakeExecutor(), owner_epoch="new"
            )
            await new.load(h.clock(3, "new"))
            new.update_identities(getattr(h, "views", ()))
            self.assertIsNone(await new.pump_lane(Lane.INVERTER, h.clock(3, "new")))
            self.assertFalse(new.executor.requests)
            if boundary in (
                "before_prepared_commit",
                "after_prepared_commit",
                "after_armed_commit",
                "before_executor_call",
            ):
                self.assertEqual(called, 0)
            if boundary == "after_verification":
                self.assertEqual(h.ledger.current.operations[0].state, S.VERIFIED)
                self.assertIsNotNone(new.settling_restriction())
            elif boundary not in ("before_prepared_commit", "after_prepared_commit"):
                self.assertEqual(h.ledger.current.operations[0].state, S.UNKNOWN)
                self.assertTrue(h.ledger.current.restore_obligations)
            await new.close()
        finally:
            await h.stop()

    return test


for boundary in BOUNDARIES:
    setattr(RestartTests, "test_restart_" + boundary, case(boundary))


async def test_completed_settling_survives_reload_without_inventing_new_window(self):
    h = await Harness().start()
    try:
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        await h.verify(req)
        await h.settle(req)
        await h.dispatch.close()
        new = Dispatcher(
            h.prefix, h.ledger, h.runtime, FakeExecutor(), owner_epoch="new"
        )
        await new.load(h.clock(10, "new"))
        self.assertIsNone(new.settling_restriction())
        await new.close()
    finally:
        await h.stop()


RestartTests.test_completed_settling_survives_reload_without_inventing_new_window = (
    test_completed_settling_survives_reload_without_inventing_new_window
)


class PersistedRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_maintenance_reload_retains_obligations_and_blocks_authority(self):
        from custom_components.hpvc.execution.models import MaintenanceState

        h = await Harness().start()
        try:
            await h.proposal()
            await h.maintenance.request("disable", True, h.views, h.clock())
            before = h.ledger.current.restore_obligations
            await h.dispatch.close()
            new = Dispatcher(
                h.prefix, h.ledger, h.runtime, FakeExecutor(), owner_epoch="new"
            )
            await new.load(h.clock(2, "new"))
            self.assertEqual(h.ledger.current.restore_obligations, before)
            self.assertEqual(
                h.ledger.current.maintenance.state, MaintenanceState.BLOCKED
            )
            self.assertIsNone(h.ledger.current.maintenance.authorization_revision)
            await new.close()
        finally:
            await h.stop()

    async def test_override_reload_preserves_originals_and_never_replays_action(self):
        import gzip, json
        from pathlib import Path
        from custom_components.hpvc.hbc.state import RawEntity
        from custom_components.hpvc.policy_runtime import PolicyRuntimeAdapter

        f = json.loads(
            gzip.decompress(
                Path("tests/fixtures/hbc-v1.6-sequences.json.gz").read_bytes()
            )
        )
        row = next(
            s for s in f["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        raw = tuple(RawEntity.from_dict(e) for e in row["entities"])
        h = await Harness().start()
        try:
            await h.proposal(entities=raw, permission=True, all_in=-0.1)
            q = await h.proposal(1, entities=raw, permission=True, all_in=-0.1)
            await h.dispatch.submit_hbc(q, h.clock(1))
            request = await h.dispatch.pump_lane(Lane.HBC, h.clock(1))
            saved = h.runtime.accepted.hbc.override
            await h.dispatch.close()
            h.runtime.close()
            runtime = PolicyRuntimeAdapter(h.prefix, "plant", h.ledger)
            await runtime.load(h.clock(2, "new"))
            self.assertEqual(
                runtime.accepted.hbc.override.previous_strategy, saved.previous_strategy
            )
            self.assertEqual(
                runtime.accepted.hbc.override.previous_goal, saved.previous_goal
            )
            new = Dispatcher(
                h.prefix, h.ledger, runtime, FakeExecutor(), owner_epoch="new"
            )
            await new.load(h.clock(2, "new"))
            self.assertIsNone(await new.pump_lane(Lane.HBC, h.clock(2, "new")))
            self.assertFalse(await new.receive_completion(h.completion(request, 3)))
            await new.close()
            runtime.close()
        finally:
            await h.stop()

    async def test_exact_dev4_execution_payload_upgrades_without_relaxing_codec(self):
        import json, hashlib
        from custom_components.hpvc.storage import VersionedStore, canonical
        from custom_components.hpvc.execution.models import ExecutionLedger

        h = await Harness().start()
        try:
            await h.submit()
            p = h.ledger.store.path
            envelope = json.loads(p.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            for op in payload["operations"]:
                op.pop("expected_native_value")
            for evidence in payload["evidence"]:
                evidence.pop("observed_native_value")
            for obligation in payload["restore_obligations"]:
                obligation.pop("established_at_utc")
                obligation.pop("owner_epoch")
            for key in (
                "requested_at_utc",
                "post_disable_evaluation_id",
                "owner_epoch",
                "requested_monotonic",
                "boot_id",
            ):
                payload["maintenance"].pop(key)
            envelope["sha256"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
            p.write_text(json.dumps(envelope), encoding="utf-8")
            upgraded = await VersionedStore(p, "execution", ExecutionLedger).load()
            self.assertEqual(upgraded.operations[0].state, S.PREPARED)
            self.assertIsNone(upgraded.operations[0].expected_native_value)
        finally:
            await h.stop()
