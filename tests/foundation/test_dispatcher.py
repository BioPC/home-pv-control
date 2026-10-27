"""Durable fake dispatcher, matched callbacks, independent finalization and safety."""

import asyncio, ast, json
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from dispatch_support import Harness, NOW
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.storage import StorageError
from custom_components.hpvc.execution.models import (
    OperationState as S,
    TransportStatus as T,
    Lane,
    ObligationState,
    MaintenanceState,
)
from custom_components.hpvc.execution.executor import FakeExecutor, Completion
from custom_components.hpvc.execution.dispatcher import Dispatcher
from custom_components.hpvc.execution.verification import (
    VerificationOutcome,
    EvidenceKind,
)
from custom_components.hpvc.execution.settling import SettlingOutcome
from custom_components.hpvc.execution.snapshot import build_execution_snapshot


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await Harness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def test_complete_raw_policy_dispatch_accept_verify_settle_next_cycle(self):
        h = self.h
        q = await h.submit()
        self.assertFalse(h.runtime.event_recorder.current.events)
        requests = await h.dispatch.pump(h.clock())
        req = next(r for r in requests if r)
        self.assertEqual(len(h.fake.requests), 1)
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.IN_FLIGHT)
        self.assertEqual(
            h.runtime.event_recorder.current.last_inverter.accepted, h.clock()
        )
        await h.dispatch.receive_completion(h.completion(req))
        self.assertEqual(
            h.dispatch._op(req.operation_id).state, S.AWAITING_VERIFICATION
        )
        self.assertEqual((await h.verify(req)).outcome, VerificationOutcome.CONFIRMED)
        self.assertEqual((await h.settle(req)).outcome, SettlingOutcome.APPLIED)
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.RETIRED)
        next_q = await h.proposal(31, controllers=[h.controller(current=2285)], pv=2000)
        self.assertFalse(next_q.policy.intent.cooldown_active)
        self.assertTrue(h.dispatch.current.history)
        self.assertFalse(next_q.policy.intent.physical_writes_authorized)

    async def test_cooldown_owned_only_by_issued_main(self):
        h = self.h
        await h.submit()
        q = await h.proposal(1)
        self.assertEqual(q.policy.intent.cooldown_until_utc, 0)
        await h.dispatch.pump(h.clock(1))
        q = await h.proposal(2)
        self.assertEqual(q.policy.intent.cooldown_until_utc, NOW + 31)

    async def test_inverter_lane_serializes_two_controllers(self):
        h = self.h
        await h.submit(controllers=[h.controller(), h.controller()])
        first = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1)))
        await h.dispatch.receive_completion(h.completion(first))
        second = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(2))
        self.assertNotEqual(first.controller_uid, second.controller_uid)
        self.assertEqual(len(h.fake.requests), 2)

    async def test_delayed_receipt_does_not_allow_second_lane_operation(self):
        h = self.h
        await h.submit()
        h.fake.acceptance_gate = asyncio.Event()
        task = asyncio.create_task(h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        for _ in range(30):
            await asyncio.sleep(0.01)
            if h.fake.requests:
                break
        self.assertEqual(len(h.fake.requests), 1)
        self.assertEqual(h.ledger.current.operations[0].state, S.ARMED)
        self.assertFalse(h.runtime.event_recorder.current.events)
        h.fake.acceptance_gate.set()
        await task

    async def test_duplicate_and_stale_callback_do_not_advance_new_work(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        stale = replace(req, dispatch_id="wrong")
        self.assertFalse(await h.dispatch.receive_completion(h.completion(stale)))
        self.assertFalse(
            await h.dispatch.receive_completion(
                h.completion(replace(req, owner_epoch="prior"))
            )
        )
        self.assertTrue(await h.dispatch.receive_completion(h.completion(req)))
        self.assertFalse(await h.dispatch.receive_completion(h.completion(req)))
        self.assertEqual(
            h.dispatch._op(req.operation_id).state, S.AWAITING_VERIFICATION
        )

    async def test_never_completing_not_cleared_by_age(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(100000)))
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.IN_FLIGHT)

    async def test_prepared_generation_superseded_before_issue(self):
        h = self.h
        await h.submit()
        await h.submit(1, grid=-1200)
        self.assertEqual(h.ledger.current.operations[0].state, S.SUPERSEDED)
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1))
        self.assertEqual(req.operation_id, h.ledger.current.operations[-1].operation_id)

    async def test_identical_generation_coalesces_without_resetting_identity(self):
        h = self.h
        await h.submit()
        old = h.ledger.current.operations
        await h.submit(1)
        self.assertEqual(h.ledger.current.operations, old)

    async def test_replaced_configuration_cannot_issue_old_prepared_work(self):
        h = self.h
        await h.submit()
        h.dispatch.identities = {"number.inv1": "replacement"}
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.fake.requests)

    async def test_arming_commit_failure_never_invokes_fake_executor(self):
        h = self.h
        await h.submit()
        with patch.object(
            h.ledger.store, "commit", side_effect=StorageError("injected")
        ):
            with self.assertRaises(StorageError):
                await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertFalse(h.fake.requests)

    async def test_prepared_commit_failure_never_invokes_executor(self):
        h = self.h
        q = await h.proposal()
        with patch.object(
            h.ledger.store, "commit", side_effect=StorageError("injected")
        ):
            with self.assertRaises(StorageError):
                await h.dispatch.submit(q, h.views, h.clock())
        self.assertFalse(h.fake.requests)
        self.assertTrue(h.dispatch.fault)

    async def test_transport_failure_isolated_from_other_controller(self):
        h = self.h
        await h.submit(controllers=[h.controller(), h.controller()])
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(
            h.completion(req, result="transport_failure")
        )
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.SERVICE_FAILED)
        self.assertTrue(h.ledger.current.restore_obligations)
        other = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(2))
        self.assertNotEqual(other.controller_uid, req.controller_uid)

    async def test_unknown_transport_blocks_lane_and_survives_close(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req, result="outcome_unknown"))
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.UNKNOWN)
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1000)))

    async def test_completion_does_not_verify_without_readback(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        self.assertFalse(h.dispatch._op(req.operation_id).evidence_ids)

    async def test_wrong_target_explicit_failure_keeps_obligation(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        candidate = h.candidate(req, native_value=0)
        verdict = await h.dispatch.finalize_evidence(
            req.operation_id, candidate, h.clock(2), final_failure=True
        )
        self.assertEqual(verdict.outcome, VerificationOutcome.VALUE_MISMATCH)
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.VERIFICATION_FAILED)
        self.assertTrue(h.ledger.current.restore_obligations)

    async def test_stale_and_unavailable_evidence_cannot_finalize(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        for changes in (
            {"reported_at_utc": NOW - 1},
            {"native_value": None},
            {"kind": EvidenceKind.COMMAND_CACHE},
            {"configuration_signature": "replacement"},
        ):
            v = await h.dispatch.finalize_evidence(
                req.operation_id, h.candidate(req, **changes), h.clock(2)
            )
            self.assertNotEqual(v.outcome, VerificationOutcome.CONFIRMED)
            self.assertEqual(
                h.dispatch._op(req.operation_id).state, S.AWAITING_VERIFICATION
            )

    async def test_reload_callback_is_ignored_and_ambiguous_work_not_replayed(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.close()
        self.assertFalse(await h.dispatch.receive_completion(h.completion(req)))
        new = Dispatcher(
            h.prefix, h.ledger, h.runtime, FakeExecutor(), owner_epoch="new"
        )
        await new.load(h.clock(3, "new"))
        new.update_identities(h.views)
        self.assertIsNone(await new.pump_lane(Lane.INVERTER, h.clock(3, "new")))
        self.assertTrue(h.ledger.current.restore_obligations)
        await new.close()

    async def test_only_concrete_fake_executor_can_be_bound(self):
        h = self.h

        class Other:
            async def issue(self, request):
                raise AssertionError("Never called")

        with self.assertRaises(SchemaError):
            Dispatcher(h.prefix, h.ledger, h.runtime, Other())

    async def test_corrupt_dispatch_journal_fails_closed(self):
        h = self.h
        await h.dispatch.close()
        h.dispatch.store.path.write_text("{broken", encoding="utf-8")
        new = Dispatcher(
            h.prefix, h.ledger, h.runtime, FakeExecutor(), owner_epoch="new"
        )
        with self.assertRaises(StorageError):
            await new.load(h.clock(1, "new"))
        await new.close()

    async def test_quiescence_does_not_clear_physical_obligation(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req, result="outcome_unknown"))
        receipt = h.fake.confirm_quiescent(req, h.clock(2))
        self.assertTrue(await h.dispatch.reconcile_quiescence(receipt))
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.RECOVERY_REQUIRED)
        self.assertTrue(h.ledger.current.restore_obligations)
        await h.dispatch.resume_verification(req.operation_id)
        self.assertEqual(
            (await h.verify(req, 3)).outcome, VerificationOutcome.CONFIRMED
        )
        self.assertTrue(
            any(
                o.state != ObligationState.VERIFIED
                for o in h.ledger.current.restore_obligations
            )
        )


class SafetyTests(unittest.TestCase):
    def test_fake_executor_has_no_actuator_or_network_dependency(self):
        base = Path("custom_components/hpvc")
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(
                        n.attr,
                        (
                            "services",
                            "async_call",
                            "post",
                            "put",
                            "delete",
                            "send_command",
                        ),
                        str(path),
                    )
        tree = ast.parse((base / "execution/executor.py").read_text(encoding="utf-8"))
        self.assertEqual(
            [
                n.name
                for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef)
                and any(
                    isinstance(c, ast.AsyncFunctionDef) and c.name == "issue"
                    for c in n.body
                )
            ],
            ["Executor", "FakeExecutor"],
        )
