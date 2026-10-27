"""Additional continuous limiting/import, outage/recovery, release and Night loops."""

import unittest
from dispatch_support import Harness
from custom_components.hpvc.execution.models import Lane


class RuntimeLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await Harness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def execute(self, at):
        h = self.h
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(at))
        self.assertIsNotNone(req)
        await h.dispatch.receive_completion(h.completion(req, at + 1))
        await h.verify(req, at + 2)
        await h.settle(req, at + 3)
        return h.dispatch._op(req.operation_id).representable_controller_target_w

    async def test_limiting_cooldown_then_import_recovery(self):
        h = self.h
        await h.submit()
        target = await self.execute(0)
        q = await h.proposal(
            10, controllers=[h.controller(current=target)], grid=-600, pv=target
        )
        self.assertTrue(q.policy.intent.cooldown_active)
        q = await h.proposal(
            31, controllers=[h.controller(current=target)], grid=600, pv=target
        )
        self.assertGreater(q.policy.intent.requested_plant_target_w, target)
        await h.dispatch.submit(q, h.views, h.clock(31))
        await self.execute(31)

    async def test_partial_outage_then_recovery_rebalance(self):
        h = self.h
        await h.submit(controllers=[h.controller(), h.controller(available=False)])
        target = await self.execute(0)
        self.assertEqual(h.fake.requests[0].controller_uid, "number.inv1")
        q = await h.proposal(
            31,
            controllers=[h.controller(current=target), h.controller(current=1000)],
            rebalance=True,
            grid=0,
            pv=target + 1000,
        )
        self.assertTrue(q.policy.allocation.rebalance_applied)
        await h.dispatch.submit(q, h.views, h.clock(31))
        self.assertIsNotNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(31)))

    async def test_external_release_full_output_independently_verified(self):
        h = self.h
        await h.submit(external_release=True, controllers=[h.controller(current=1000)])
        self.assertEqual(await self.execute(0), 3000)
        q = await h.proposal(31, external_release=True)
        self.assertTrue(q.policy.intent.external_release_full_observed)

    async def test_night_restore_entry_full_command_then_suspended_policy(self):
        h = self.h
        await h.proposal(pv=10, controllers=[h.controller(current=1000)])
        q = await h.submit(120, pv=10, controllers=[h.controller(current=1000)])
        self.assertTrue(q.policy.memory.night.active)
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(120))
        self.assertIsNotNone(req)
        await h.dispatch.receive_completion(h.completion(req, 121))
        await h.verify(req, 122)
        q = await h.proposal(151, pv=10)
        self.assertTrue(q.policy.memory.night.active)
        self.assertFalse(q.policy.intent.physical_writes_authorized)
