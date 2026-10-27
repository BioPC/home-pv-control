"""HA transport receipt/admission/identity/error semantics with isolated test registry."""

import asyncio, ast, pickle
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from transport_support import TransportHarness, test_admission
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.execution.models import (
    Lane,
    OperationState as S,
    MaintenanceRecord,
    MaintenanceState,
)
from custom_components.hpvc.execution.ha_executor import (
    TransportRefused,
    production_transport_admitted,
    TEST_DOMAIN,
    _TransportTestAdmission,
)


class HaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await TransportHarness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def issue(self):
        await self.h.submit()
        return await self.h.dispatch.pump_lane(Lane.INVERTER, self.h.clock())

    async def test_success_preserves_native_value_and_is_not_verification(self):
        h = self.h
        request = await self.issue()
        self.assertIsNotNone(request)
        await h.finish_transport()
        domain, service, kwargs = h.registry.calls[0]
        self.assertEqual((domain, service), (TEST_DOMAIN, "number_set_value"))
        self.assertEqual(kwargs["service_data"], {"value": 2285})
        self.assertEqual(kwargs["target"], {"entity_id": "number.inv1"})
        self.assertTrue(kwargs["blocking"])
        self.assertEqual(
            h.dispatch._op(request.operation_id).state, S.AWAITING_VERIFICATION
        )
        self.assertFalse(h.dispatch._op(request.operation_id).evidence_ids)
        self.assertEqual(h.states["number.inv1"].state, "3000")
        self.assertFalse(h.executor.physical_writes_authorized)
        self.assertEqual(h.executor.current.attempts[0].result, "success")

    async def test_default_executor_production_admission_is_permanently_closed(self):
        h = self.h
        await h.submit()
        h.executor._test_admission = None
        self.assertFalse(production_transport_admitted())
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)
        self.assertEqual(h.ledger.current.operations[-1].state, S.SUPERSEDED)

    async def test_direct_runtime_issuer_cannot_bypass_dispatcher(self):
        h = self.h
        await h.submit()
        with self.assertRaises(TransportRefused):
            await h.executor.issue(None)
        self.assertFalse(h.registry.calls)

    async def refused_change(self, mutate):
        h = self.h
        await h.submit()

        async def checkpoint(name, op):
            if name == "before_executor_call":
                mutate(h)

        h.dispatch.checkpoint = checkpoint
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)
        self.assertEqual(h.ledger.current.operations[-1].state, S.SUPERSEDED)

    async def test_epoch_change_before_issue_refuses(self):
        await self.refused_change(lambda h: setattr(h, "binding_epoch", "stale"))

    async def test_opt_out_before_issue_refuses(self):
        await self.refused_change(
            lambda h: setattr(
                h,
                "live_views",
                (
                    replace(
                        h.views[0],
                        configuration=replace(
                            h.views[0].configuration, control_enabled=False
                        ),
                    ),
                ),
            )
        )

    async def test_configuration_change_before_issue_refuses(self):
        await self.refused_change(
            lambda h: setattr(
                h,
                "live_views",
                (replace(h.views[0], configuration_signature="replacement"),),
            )
        )

    async def test_missing_entity_before_issue_refuses(self):
        await self.refused_change(lambda h: h.states.clear())

    async def test_unavailable_entity_before_issue_refuses(self):
        await self.refused_change(
            lambda h: setattr(h.states["number.inv1"], "state", "unavailable")
        )

    async def test_missing_service_before_issue_refuses(self):
        await self.refused_change(lambda h: setattr(h.registry, "found", False))

    async def test_revoked_admission_before_issue_refuses(self):
        await self.refused_change(lambda h: setattr(h.permit, "active", False))

    async def test_recheck_after_transport_log_await_detects_identity_change(self):
        h = self.h
        await h.submit()
        original = h.executor._audit

        async def audit(row):
            await original(row)
            if row.result == "armed":
                h.live_views = (
                    replace(h.views[0], configuration_signature="changed-during-io"),
                )

        with patch.object(h.executor, "_audit", side_effect=audit):
            self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)

    async def test_handler_exception_is_transport_failure_with_durable_details(self):
        h = self.h

        async def handler(*args):
            raise ValueError("controlled service exception")

        h.registry.handler = handler
        request = await self.issue()
        await h.finish_transport()
        self.assertEqual(h.dispatch._op(request.operation_id).state, S.SERVICE_FAILED)
        row = h.executor.current.attempts[0]
        self.assertEqual(row.exception_type, "ValueError")
        self.assertIn("controlled service exception", row.exception_message)
        self.assertTrue(h.ledger.current.restore_obligations)

    async def test_completion_can_precede_receipt_commit_without_finalizing_armed_work(
        self,
    ):
        h = self.h
        seen = []

        async def handler(*args):
            seen.append(
                (
                    h.ledger.current.operations[0].state,
                    len(h.runtime.event_recorder.current.events),
                )
            )

        h.registry.handler = handler
        request = await self.issue()
        self.assertEqual(seen, [(S.ARMED, 0)])
        self.assertTrue(h.runtime.event_recorder.current.last_inverter)
        await h.finish_transport()
        self.assertEqual(
            h.dispatch._op(request.operation_id).state, S.AWAITING_VERIFICATION
        )

    async def test_timeout_does_not_cancel_a_possibly_issued_service(self):
        h = self.h
        release = asyncio.Event()
        completed = []
        h.executor.timeout_seconds = 0.02

        async def handler(*args):
            await release.wait()
            completed.append(True)

        h.registry.handler = handler
        request = await self.issue()
        try:
            await asyncio.wait_for(h.executor.results_ready.wait(), 2)
            await h.dispatch.drain_completions()
            self.assertEqual(h.dispatch._op(request.operation_id).state, S.UNKNOWN)
            self.assertFalse(h.executor._attempts[request.dispatch_id]["task"].done())
        finally:
            release.set()
            await h.finish_transport()
        self.assertTrue(completed)
        self.assertEqual(h.dispatch._op(request.operation_id).state, S.UNKNOWN)
        receipt = h.executor.confirm_quiescent(request, h.clock(1))
        self.assertEqual(receipt.transport_result, "completed")

    async def test_unload_does_not_cancel_issued_registry_work(self):
        h = self.h
        release = asyncio.Event()
        completed = []

        async def handler(*args):
            await release.wait()
            completed.append(True)

        h.registry.handler = handler
        request = await self.issue()
        await h.dispatch.close()
        await h.executor.close()
        self.assertFalse(h.executor._attempts[request.dispatch_id]["task"].done())
        self.assertEqual(h.dispatch._op(request.operation_id).state, S.UNKNOWN)
        release.set()
        await h.finish_transport()
        self.assertTrue(completed)
        self.assertEqual(h.dispatch._op(request.operation_id).state, S.UNKNOWN)

    async def test_cancellation_before_registry_issue_is_never_success(self):
        h = self.h
        await h.submit()
        entered = asyncio.Event()
        release = asyncio.Event()
        original = h.executor._audit

        async def audit(row):
            entered.set()
            await release.wait()
            await original(row)

        with patch.object(h.executor, "_audit", side_effect=audit):
            task = asyncio.create_task(h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
            await entered.wait()
            await h.dispatch.close()
            release.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)
        self.assertNotEqual(h.ledger.current.operations[-1].state, S.VERIFIED)


class TransportSafetyTests(unittest.TestCase):
    def test_only_one_production_registry_call_site(self):
        base = Path("custom_components/hpvc")
        sites = []
        for p in base.rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr in (
                    "services",
                    "async_call",
                ):
                    self.assertEqual(p, base / "execution/ha_executor.py")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "async_call"
                ):
                    sites.append(p)
        self.assertEqual(sites, [base / "execution/ha_executor.py"])

    def test_test_admission_is_nonserializable_and_cannot_target_actuator_domains(self):
        permit = test_admission("epoch")
        with self.assertRaises(TypeError):
            pickle.dumps(permit)
        with self.assertRaises(SchemaError):
            test_admission("epoch", {"number.set_value": ("number", "set_value")})
        with self.assertRaises(SchemaError):
            _TransportTestAdmission(_key=object(), owner_epoch="epoch", aliases={})

    def test_runtime_never_constructs_test_admission(self):
        base = Path("custom_components/hpvc")
        for p in base.rglob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            self.assertFalse(
                any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "_TransportTestAdmission"
                    for n in ast.walk(tree)
                ),
                str(p),
            )
        self.assertFalse(production_transport_admitted())


class AdditionalTransportIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await TransportHarness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def test_maintenance_changed_after_registration_refuses_without_call(self):
        h = self.h
        await h.submit()

        async def checkpoint(name, op):
            if name == "before_executor_call":
                await h.ledger.update(
                    lambda l: replace(
                        l,
                        maintenance=MaintenanceRecord(state=MaintenanceState.REQUESTED),
                    )
                )

        h.dispatch.checkpoint = checkpoint
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)

    async def test_compiled_sequence_identity_cannot_be_changed(self):
        h = self.h
        await h.submit()
        op = h.ledger.current.operations[0]
        plan = h.executor._plans[op.operation_id]
        h.executor._plans[op.operation_id] = replace(
            plan, sequence_fingerprint="tampered"
        )
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)

    async def test_old_refusal_cannot_supersede_newer_dispatch_identity(self):
        h = self.h
        await h.submit()

        async def checkpoint(name, op):
            if name == "before_executor_call":
                await h.ledger.update(
                    lambda l: replace(
                        l,
                        operations=tuple(
                            replace(o, dispatch_id="newer-dispatch")
                            for o in l.operations
                        ),
                    )
                )

        h.dispatch.checkpoint = checkpoint
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock()))
        self.assertEqual(h.ledger.current.operations[0].dispatch_id, "newer-dispatch")
        self.assertEqual(h.ledger.current.operations[0].state, S.ARMED)
        self.assertFalse(h.registry.calls)
        self.assertFalse(h.runtime.event_recorder.current.events)

    async def test_issued_receipt_cannot_be_rebound_after_dispatch_identity_change(
        self,
    ):
        h = self.h
        await h.submit()

        async def checkpoint(name, op):
            if name == "after_executor_call_before_inflight":
                await h.ledger.update(
                    lambda l: replace(
                        l,
                        operations=tuple(
                            replace(o, dispatch_id="newer-dispatch")
                            for o in l.operations
                        ),
                    )
                )

        h.dispatch.checkpoint = checkpoint
        with self.assertRaises(SchemaError):
            await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.finish_transport()
        self.assertEqual(len(h.registry.calls), 1)
        self.assertFalse(h.runtime.event_recorder.current.events)
        self.assertEqual(h.ledger.current.operations[0].state, S.UNKNOWN)


class IssuedRefusalExceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_refusal_exception_does_not_prove_nonissue(self):
        h = await TransportHarness().start()
        try:

            async def handler(*args):
                raise TransportRefused("handler_has_already_been_invoked")

            h.registry.handler = handler
            await h.submit()
            request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
            await h.finish_transport()
            self.assertFalse(h.executor.knows_not_issued(request.dispatch_id))
            self.assertEqual(
                h.dispatch._op(request.operation_id).state, S.SERVICE_FAILED
            )
            self.assertEqual(
                h.executor.current.attempts[-1].result, "transport_failure"
            )
        finally:
            await h.stop()
