"""Owned maintenance, restoration evidence, restart and timeout refusal."""

from dataclasses import replace
import unittest
from dispatch_support import Harness, NOW
from custom_components.hpvc.execution.models import (
    MaintenanceState as M,
    OperationState as S,
    ObligationState as O,
    NightRestoreState,
)
from custom_components.hpvc.execution.maintenance import FullOutputObservation
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.execution.models import Lane


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await Harness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def request(self, at=0, views=None):
        h = self.h
        if not hasattr(h, "views"):
            await h.proposal()
        await h.maintenance.request(
            "disable", True, h.views if views is None else views, h.clock(at)
        )
        return h.ledger.current.maintenance.owner_token

    async def disabled(self, token, at=1, **kw):
        h = self.h
        q = await h.proposal(at, enabled=False, **kw)
        await h.maintenance.observe_disabled(q, h.clock(at), token)
        return q

    async def test_request_captures_saved_intent_and_owner_but_never_authorizes(self):
        h = self.h
        token = await self.request()
        m = h.ledger.current.maintenance
        self.assertTrue(m.saved_enable_intent)
        self.assertEqual(m.owner_token, token)
        self.assertTrue(h.ledger.current.restore_obligations)
        self.assertFalse((await h.maintenance.evaluate(h.clock(1), token)).authorized)

    async def test_post_disable_evaluation_cannot_be_replaced_by_helper(self):
        h = self.h
        token = await self.request()
        with self.assertRaises(SchemaError):
            await h.maintenance.observe_disabled(
                h.runtime.last_proposal, h.clock(1), token
            )

    async def test_zero_controller_still_requires_post_disable_evaluation(self):
        h = self.h
        await h.proposal(controllers=[])
        token = await self.request(views=[])
        self.assertFalse((await h.maintenance.evaluate(h.clock(), token)).authorized)
        await self.disabled(token, controllers=[])
        self.assertTrue((await h.maintenance.evaluate(h.clock(2), token)).authorized)
        self.assertTrue(h.maintenance.authorization_valid(token, h.clock(2)))
        await h.ledger.update(lambda l: l)
        self.assertFalse(h.maintenance.authorization_valid(token, h.clock(2)))

    async def test_full_restoration_path_requires_verification_and_settling(self):
        h = self.h
        await h.proposal(controllers=[h.controller(current=1000)])
        token = await self.request()
        await self.disabled(token, controllers=[h.controller(current=1000)])
        await h.dispatch.submit_restoration(h.views, h.clock(1), token)
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1))
        self.assertIsNotNone(req)
        await h.dispatch.receive_completion(h.completion(req, 2))
        self.assertFalse((await h.maintenance.evaluate(h.clock(2), token)).authorized)
        await h.verify(req, 3)
        await h.maintenance.resolve_verified_restores(h.clock(3), token)
        self.assertTrue(
            all(o.state == O.VERIFIED for o in h.ledger.current.restore_obligations)
        )
        self.assertFalse((await h.maintenance.evaluate(h.clock(3), token)).authorized)
        await h.settle(req, 4)
        decision = await h.maintenance.evaluate(h.clock(6), token)
        self.assertTrue(decision.authorized)
        self.assertFalse(decision.physical_writes_authorized)

    async def test_180_second_timeout_refuses_even_if_zero_controller(self):
        h = self.h
        await h.proposal(controllers=[])
        token = await self.request(views=[])
        await self.disabled(token, controllers=[])
        decision = await h.maintenance.evaluate(h.clock(180), token)
        self.assertFalse(decision.authorized)
        self.assertEqual(decision.state, M.BLOCKED)
        self.assertFalse((await h.maintenance.evaluate(h.clock(181), token)).authorized)

    async def test_wall_jump_does_not_advance_monotonic_timeout(self):
        h = self.h
        await h.proposal(controllers=[])
        token = await self.request(views=[])
        await self.disabled(token, controllers=[])
        clock = replace(h.clock(2), utc=NOW + 10000)
        self.assertTrue((await h.maintenance.evaluate(clock, token)).authorized)

    async def test_wrong_owner_cannot_authorize_or_steal_transaction(self):
        h = self.h
        token = await self.request()
        with self.assertRaises(SchemaError):
            await h.maintenance.evaluate(h.clock(), "other")
        with self.assertRaises(SchemaError):
            await h.maintenance.request("remove", False, h.views, h.clock())

    async def test_zero_rediscovery_and_configuration_replacement_preserve_obligation(
        self,
    ):
        h = self.h
        token = await self.request()
        before = h.ledger.current.restore_obligations
        h.dispatch.update_identities(())
        await self.disabled(token, controllers=[])
        self.assertEqual(h.ledger.current.restore_obligations, before)
        self.assertFalse((await h.maintenance.evaluate(h.clock(2), token)).authorized)

    async def test_already_full_needs_bound_fresh_independent_view(self):
        h = self.h
        token = await self.request()
        await self.disabled(token)
        view = h.views[0]
        view = replace(
            view,
            observation=replace(
                view.observation,
                limit=replace(
                    view.observation.limit,
                    reported_at_utc=NOW + 1,
                    received_at_utc=NOW + 1,
                ),
            ),
        )
        observation = FullOutputObservation(
            "number.inv1",
            view.configuration_signature,
            "config:" + view.configuration_signature,
            "epoch",
            3000,
            "ha_readback",
            NOW + 1,
            NOW + 1,
        )
        self.assertFalse(
            await h.maintenance.already_full(observation, h.clock(1), token)
        )
        for changed in [
            replace(observation, source="command-cache"),
            replace(observation, configuration_signature="replacement"),
            replace(observation, reported_at_utc=NOW - 1),
            replace(observation, owner_epoch="other"),
        ]:
            self.assertFalse(
                await h.maintenance.already_full(changed, h.clock(1), token, view=view)
            )
        self.assertTrue(
            await h.maintenance.already_full(observation, h.clock(1), token, view=view)
        )
        self.assertTrue((await h.maintenance.evaluate(h.clock(2), token)).authorized)

    async def test_conflicting_inflight_work_blocks_stale_full_shortcut(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        token = await self.request(1)
        await self.disabled(token, 2)
        view = h.views[0]
        view = replace(
            view,
            observation=replace(
                view.observation,
                limit=replace(
                    view.observation.limit,
                    reported_at_utc=NOW + 2,
                    received_at_utc=NOW + 2,
                ),
            ),
        )
        obs = FullOutputObservation(
            req.controller_uid,
            req.configuration_signature,
            "config:" + req.configuration_signature,
            "epoch",
            3000,
            "ha_readback",
            NOW + 2,
            NOW + 2,
        )
        self.assertFalse(
            await h.maintenance.already_full(obs, h.clock(2), token, view=view)
        )

    async def test_completed_failure_and_verified_full_restore_can_reconcile(self):
        h = self.h
        await h.submit()
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(
            h.completion(req, result="transport_failure")
        )
        token = await self.request(2)
        await self.disabled(token, 3, controllers=[h.controller(current=1000)])
        await h.dispatch.submit_restoration(h.views, h.clock(3), token)
        restored = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3))
        self.assertIsNotNone(restored)
        await h.dispatch.receive_completion(h.completion(restored, 4))
        await h.verify(restored, 5)
        await h.settle(restored, 6)
        await h.maintenance.resolve_verified_restores(h.clock(8), token)
        self.assertTrue((await h.maintenance.evaluate(h.clock(8), token)).authorized)

    async def test_night_exception_uses_durable_identity_bound_full_proof(self):
        h = self.h
        await h.submit(external_release=True, controllers=[h.controller(current=1000)])
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        await h.verify(req)
        await h.settle(req)
        proof = h.dispatch._op(req.operation_id).evidence_ids[0]
        await h.ledger.update(
            lambda l: replace(
                l,
                night_restore=NightRestoreState(
                    active=True, full_output_proof_reference=proof
                ),
            )
        )
        token = await self.request(10, views=[])
        await self.disabled(token, 11, controllers=[])
        self.assertTrue(await h.maintenance.night_exception(token))
        self.assertTrue((await h.maintenance.evaluate(h.clock(12), token)).authorized)

    async def test_timeout_can_only_start_a_new_explicit_recovery_transaction(self):
        h = self.h
        await h.proposal(controllers=[])
        token = await self.request(views=[])
        await self.disabled(token, controllers=[])
        decision = await h.maintenance.evaluate(h.clock(180), token)
        self.assertEqual(decision.state, M.BLOCKED)
        q = await h.proposal(181, enabled=False, controllers=[])
        with self.assertRaises(SchemaError):
            await h.maintenance.recover_request("wrong", q, h.clock(181))
        new_token = await h.maintenance.recover_request(token, q, h.clock(181))
        self.assertNotEqual(new_token, token)
        self.assertTrue(h.ledger.current.maintenance.saved_enable_intent)
        with self.assertRaises(SchemaError):
            await h.maintenance.evaluate(h.clock(182), token)
        self.assertTrue(
            (await h.maintenance.evaluate(h.clock(182), new_token)).authorized
        )
