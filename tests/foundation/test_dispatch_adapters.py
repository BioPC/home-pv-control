"""Real adapters through the fake dispatcher, separate HBC lane and taper memory."""

from dataclasses import replace
from pathlib import Path
import gzip, json, unittest
from dispatch_support import Harness, NOW
from custom_components.hpvc.execution.models import Lane, OperationState as S
from custom_components.hpvc.execution.verification import (
    EvidenceKind,
    VerificationOutcome,
)
from custom_components.hpvc.control.models import (
    ControllerConfiguration,
    ControllerIdentity,
    AdapterKind,
    ControlMethod,
)
from custom_components.hpvc.inverter.base import EntityRecord, DiscoveryCandidate
from custom_components.hpvc.inverter.generic_action import GenericActionAdapter
from custom_components.hpvc.inverter.enphase import EnphaseAdapter
from custom_components.hpvc.inverter.hoymiles import HoymilesAdapter, OpenDtuCache
from custom_components.hpvc.hbc.state import RawEntity

HBC = json.loads(
    gzip.decompress(
        (
            Path(__file__).parents[2] / "tests/fixtures/hbc-v1.6-sequences.json.gz"
        ).read_bytes()
    )
)


def action_view(open_loop=False):
    cfg = ControllerConfiguration(
        ControllerIdentity("action", 1, AdapterKind.ACTION),
        "cfg",
        method=ControlMethod.ACTION,
        full_limit_w=3000,
        action="script.apply_limit",
        readback_entity="" if open_loop else "sensor.limit",
        pre_actions_json='[{"action":"switch.turn_on","target":{"entity_id":"switch.prepare"}}]',
        post_actions_json='[{"action":"switch.turn_off","target":{"entity_id":"switch.finish"}}]',
    )
    return GenericActionAdapter().normalize(
        cfg, None if open_loop else EntityRecord("sensor.limit", "3000", NOW), NOW
    )


def enphase_view(ready=False, at=0):
    c = DiscoveryCandidate(
        "enphase:device",
        "enphase",
        "number.limit",
        "device",
        "switch.enable",
        "select.mode",
    )
    cfg = ControllerConfiguration(
        ControllerIdentity("e", 1, AdapterKind.ENPHASE),
        "cfg",
        full_limit_w=3000,
        limit_number="number.limit",
    )
    state = lambda e, v, **a: EntityRecord(e, v, NOW + at, json.dumps(a))
    return EnphaseAdapter().normalize(
        cfg,
        state("number.limit", "3000", min=0, max=3000, step=1),
        NOW + at,
        candidate=c,
        states=(
            state("switch.enable", "on" if ready else "off"),
            state(
                "select.mode",
                "Production" if ready else "Export",
                options=["Production", "Export"],
            ),
        ),
    )


class AdapterDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h = await Harness().start()

    async def asyncTearDown(self):
        await self.h.stop()

    async def prepare_action(self, open_loop=False):
        h = self.h
        view = action_view(open_loop)
        q = await h.proposal_views((view,))
        await h.dispatch.submit(q, (view,), h.clock())
        return q

    async def test_generic_action_pre_main_post_order_independent_preconditions(self):
        h = self.h
        await self.prepare_action()
        pre = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertEqual(pre.step.phase, "pre")
        await h.dispatch.receive_completion(h.completion(pre))
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1)))
        self.assertFalse(h.runtime.event_recorder.current.events)
        await h.native(pre, 2)
        main = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3))
        self.assertEqual(main.step.phase, "main")
        await h.dispatch.receive_completion(h.completion(main, 4))
        await h.verify(main, 5)
        post = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(6))
        self.assertEqual(post.step.phase, "post")
        await h.dispatch.receive_completion(h.completion(post, 7))
        await h.native(post, 8)
        await h.settle(main, 9)
        self.assertEqual(
            [r.step.action for r in h.fake.requests],
            ["switch.turn_on", "script.apply_limit", "switch.turn_off"],
        )

    async def test_open_loop_never_fabricates_physical_verification(self):
        h = self.h
        await self.prepare_action(True)
        pre = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(pre))
        await h.native(pre, 2)
        main = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3))
        await h.dispatch.receive_completion(h.completion(main, 4))
        self.assertEqual(h.dispatch._op(main.operation_id).state, S.OPEN_LOOP)
        self.assertIsNone(await h.verify(main, 5))
        self.assertFalse(h.dispatch._op(main.operation_id).evidence_ids)

    async def fail_phase(self, phase):
        h = self.h
        await self.prepare_action()
        pre = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        at = 1
        if phase == "pre":
            req = pre
        else:
            await h.dispatch.receive_completion(h.completion(pre))
            await h.native(pre, 2)
            req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3))
            at = 4
            if phase == "post":
                await h.dispatch.receive_completion(h.completion(req, 4))
                req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(5))
                at = 6
        await h.dispatch.receive_completion(
            h.completion(req, at, result="transport_failure")
        )
        self.assertEqual(h.dispatch._op(req.operation_id).state, S.SERVICE_FAILED)
        self.assertTrue(h.ledger.current.restore_obligations)
        self.assertFalse(
            any(
                o.state == S.PREPARED
                for o in h.ledger.current.operations
                if o.batch_id == h.dispatch._op(req.operation_id).batch_id
            )
        )

    async def test_partial_pre_failure(self):
        await self.fail_phase("pre")

    async def test_partial_main_failure(self):
        await self.fail_phase("main")

    async def test_partial_post_failure(self):
        await self.fail_phase("post")

    async def test_enphase_preflight_requires_observed_enable_and_production(self):
        h = self.h
        view = enphase_view()
        q = await h.proposal_views((view,))
        await h.dispatch.submit(q, (view,), h.clock())
        enable = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertEqual(enable.step.action, "switch.turn_on")
        await h.dispatch.receive_completion(h.completion(enable))
        self.assertIsNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(1)))
        self.assertFalse(await h.native(enable, 2, state="off"))
        await h.native(enable, 2)
        production = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3))
        await h.dispatch.receive_completion(h.completion(production, 4))
        await h.native(production, 5)
        self.assertFalse(h.runtime.event_recorder.current.events)
        ready = enphase_view(True, 6)
        q = await h.proposal_views((ready,), 6)
        await h.dispatch.submit(q, (ready,), h.clock(6))
        main = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(6))
        self.assertEqual(main.step.action, "number.set_value")
        await h.dispatch.receive_completion(h.completion(main, 7))
        result = await h.verify(
            main, 8, kind=EvidenceKind.ENPHASE, enabled=False, production_mode=True
        )
        self.assertEqual(result.outcome, VerificationOutcome.NOT_READY)
        result = await h.verify(
            main, 9, kind=EvidenceKind.ENPHASE, enabled=True, production_mode=True
        )
        self.assertEqual(result.outcome, VerificationOutcome.CONFIRMED)

    async def test_opendtu_requires_post_dispatch_poll_identity_and_status(self):
        h = self.h
        c = DiscoveryCandidate(
            "dtu:serial", "hoymiles", "number.limit", "dtu", serial="serial"
        )
        cfg = ControllerConfiguration(
            ControllerIdentity("d", 1),
            "cfg",
            full_limit_w=3000,
            limit_number="number.limit",
        )
        view = HoymilesAdapter().normalize(
            cfg,
            EntityRecord(
                "number.limit", "3000", NOW, json.dumps(dict(min=0, max=3000, step=1))
            ),
            NOW,
            candidate=c,
            cache=OpenDtuCache(),
        )
        q = await h.proposal_views((view,))
        await h.dispatch.submit(q, (view,), h.clock())
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.dispatch.receive_completion(h.completion(req))
        target = h.dispatch._op(req.operation_id).representable_controller_target_w
        fields = dict(
            kind=EvidenceKind.OPENDTU,
            poll_started_at_utc=NOW - 1,
            max_power_w=3000,
            relative_limit=target / 30,
            command_status="ok",
            device_id="dtu",
            serial="serial",
        )
        self.assertEqual(
            (await h.verify(req, 2, **fields)).outcome, VerificationOutcome.STALE
        )
        fields["poll_started_at_utc"] = NOW + 1
        self.assertEqual(
            (await h.verify(req, 2, **fields)).outcome, VerificationOutcome.CONFIRMED
        )

    async def test_hbc_lane_can_issue_while_inverter_lane_is_inflight(self):
        h = self.h
        row = next(
            s for s in HBC["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        entities = tuple(RawEntity.from_dict(e) for e in row["entities"])
        q = await h.proposal(entities=entities, permission=True, all_in=-0.1)
        q = await h.proposal(1, entities=entities, permission=True, all_in=-0.1)
        await h.dispatch.submit(q, h.views, h.clock(1))
        await h.dispatch.submit_hbc(q, h.clock(1))
        inverter, hbc = await h.dispatch.pump(h.clock(1))
        self.assertIsNotNone(inverter)
        self.assertIsNotNone(hbc)
        self.assertEqual({r.lane for r in h.fake.requests}, {Lane.INVERTER, Lane.HBC})
        await h.dispatch.receive_completion(h.completion(hbc, 2))
        self.assertEqual(
            h.dispatch._op(hbc.operation_id).state, S.AWAITING_VERIFICATION
        )
        await h.native(hbc, 3)
        self.assertTrue(h.runtime.event_recorder.current.events)

    async def test_hbc_entry_exit_order_and_independent_confirmation(self):
        h = self.h
        row = next(
            s for s in HBC["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        entities = tuple(RawEntity.from_dict(e) for e in row["entities"])
        await h.proposal(entities=entities, permission=True, all_in=-0.1)
        q = await h.proposal(1, entities=entities, permission=True, all_in=-0.1)
        steps = []
        for at, allin in [(1, -0.1), (7, -0.1), (13, 0.1), (19, 0.1)]:
            if at != 1:
                q = await h.proposal(
                    at, entities=entities, permission=True, all_in=allin
                )
            await h.dispatch.submit_hbc(q, h.clock(at))
            req = await h.dispatch.pump_lane(Lane.HBC, h.clock(at))
            self.assertIsNotNone(req)
            reg = h.dispatch._reg(h.dispatch._op(req.operation_id).batch_id)
            steps.append(reg.hbc_step)
            await h.dispatch.receive_completion(h.completion(req, at + 1))
            await h.native(req, at + 2)
            entity = json.loads(req.step.target_json)["entity_id"]
            state = h.dispatch._op(req.operation_id).expected_native_value
            entities = tuple(
                replace(e, state=state, updated_at_utc=NOW + at + 2)
                if e.entity_id == entity
                else e
                for e in entities
            )
        q = await h.proposal(25, entities=entities, permission=True, all_in=0.1)
        self.assertEqual(
            steps, ["enter_strategy", "enter_goal", "restore_goal", "restore_strategy"]
        )
        self.assertEqual(q.hbc.override.memory.phase, "inactive")
        self.assertTrue(await h.dispatch.confirm_hbc_restored(q, entities, h.clock(25)))
        self.assertEqual(h.ledger.current.hbc_override.phase.value, "inactive")

    async def test_raw_hbc_priority_acceptance_updates_probe_and_memory_next_cycle(
        self,
    ):
        h = self.h
        sequence = next(
            s for s in HBC["sequences"] if s["name"] == "taper-fresh-learning"
        )
        initial = sequence["cycles"][0]["input"]
        await h.proposal(
            entities=tuple(RawEntity.from_dict(e) for e in initial["entities"]),
            permission=True,
            grid=initial["grid"],
            pv=initial["pv"],
            controllers=[h.controller(current=initial["current"])],
        )
        row = sequence["cycles"][2]["input"]
        entities = tuple(RawEntity.from_dict(e) for e in row["entities"])
        q = await h.submit(
            60,
            entities=entities,
            permission=True,
            grid=row["grid"],
            pv=row["pv"],
            controllers=[h.controller(current=row["current"])],
        )
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock(60))
        self.assertIsNotNone(req)
        self.assertEqual(
            h.runtime.event_recorder.current.last_release.event_id,
            "accepted:" + req.operation_id,
        )
        await h.dispatch.receive_completion(h.completion(req, 61))
        await h.verify(req, 62)
        q = await h.proposal(
            62,
            entities=entities,
            permission=True,
            grid=0,
            pv=row["pv"],
            controllers=[
                h.controller(
                    current=h.dispatch._op(
                        req.operation_id
                    ).representable_controller_target_w
                )
            ],
        )
        self.assertIsNotNone(q.hbc.memory.pending_probe)
        probe = q.hbc.memory.pending_probe
        fresh = tuple(
            replace(
                e,
                state=str(
                    -(
                        probe.batteries[0].charging_w
                        + probe.batteries[0].expected_share_w
                    )
                ),
                updated_at_utc=NOW + 72,
            )
            if e.entity_id.endswith("_ac_power")
            else e
            for e in entities
        )
        q = await h.proposal(
            72,
            entities=fresh,
            permission=True,
            grid=0,
            pv=row["pv"],
            controllers=[
                h.controller(
                    current=h.dispatch._op(
                        req.operation_id
                    ).representable_controller_target_w
                )
            ],
        )
        self.assertIsNone(q.hbc.memory.pending_probe)
        self.assertTrue(
            any(b.samples > 0 for m in q.hbc.memory.batteries for b in m.bands)
        )

    async def test_negative_override_retry_after_transport_failure(self):
        h = self.h
        row = next(
            s for s in HBC["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        entities = tuple(RawEntity.from_dict(e) for e in row["entities"])
        await h.proposal(entities=entities, permission=True, all_in=-0.1)
        q = await h.proposal(1, entities=entities, permission=True, all_in=-0.1)
        await h.dispatch.submit_hbc(q, h.clock(1))
        req = await h.dispatch.pump_lane(Lane.HBC, h.clock(1))
        await h.dispatch.receive_completion(
            h.completion(req, 2, result="transport_failure")
        )
        q = await h.proposal(7, entities=entities, permission=True, all_in=-0.1)
        await h.dispatch.submit_hbc(q, h.clock(7))
        retry = await h.dispatch.pump_lane(Lane.HBC, h.clock(7))
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry.dispatch_id, req.dispatch_id)
        self.assertEqual(retry.step.action, "input_select.select_option")

    async def test_below90_initial_release_before_charging_is_dispatched_only_in_fake(
        self,
    ):
        h = self.h
        row = HBC["sequences"][0]["cycles"][0]["input"]
        entities = tuple(RawEntity.from_dict(e) for e in row["entities"])
        q = await h.submit(
            entities=entities,
            permission=True,
            grid=row["grid"],
            pv=row["pv"],
            controllers=[h.controller(current=row["current"])],
        )
        self.assertEqual(q.policy.intent.action.value, "charge_priority_increase")
        req = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        self.assertIsNotNone(req)
        await h.dispatch.receive_completion(h.completion(req))
        await h.verify(req)
        await h.settle(req)
        self.assertFalse(h.dispatch.physical_writes_authorized)

    async def test_pending_hbc_verification_does_not_freeze_inverter_policy_lane(self):
        h = self.h
        row = next(
            s for s in HBC["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        raw = tuple(RawEntity.from_dict(e) for e in row["entities"])
        await h.proposal(entities=raw, permission=True, all_in=-0.1)
        q = await h.proposal(1, entities=raw, permission=True, all_in=-0.1)
        await h.dispatch.submit_hbc(q, h.clock(1))
        hb = await h.dispatch.pump_lane(Lane.HBC, h.clock(1))
        await h.dispatch.receive_completion(h.completion(hb, 2))
        q = await h.proposal(3, entities=raw, permission=True, all_in=-0.1)
        snapshot = h.dispatch.execution_snapshot(q.controller_provenance, h.clock(3))
        self.assertFalse(snapshot.pending_verification)
        self.assertFalse(snapshot.recovery_required)
        self.assertTrue(snapshot.unresolved_hbc_operation_ids)
        await h.dispatch.submit(q, h.views, h.clock(3))
        self.assertIsNotNone(await h.dispatch.pump_lane(Lane.INVERTER, h.clock(3)))

    async def test_hbc_crash_before_acceptance_keeps_original_capture_without_issued_fact(
        self,
    ):
        h = self.h
        row = next(
            s for s in HBC["sequences"] if s["name"] == "negative-override-entry-exit"
        )["cycles"][0]["input"]
        raw = tuple(RawEntity.from_dict(e) for e in row["entities"])
        await h.proposal(entities=raw, permission=True, all_in=-0.1)
        q = await h.proposal(1, entities=raw, permission=True, all_in=-0.1)
        await h.dispatch.submit_hbc(q, h.clock(1))

        class Crash(Exception):
            pass

        async def checkpoint(name, op):
            if name == "after_executor_call_before_inflight":
                raise Crash()

        h.dispatch.checkpoint = checkpoint
        with self.assertRaises(Crash):
            await h.dispatch.pump_lane(Lane.HBC, h.clock(1))
        self.assertFalse(h.runtime.event_recorder.current.events)
        owned = h.ledger.current.hbc_override
        self.assertIsNotNone(owned.saved_strategy)
        self.assertIsNone(owned.forced_write_issued)
        q = await h.proposal(2, entities=raw, permission=True, all_in=0.1)
        self.assertTrue(q.hbc.override.recovery_required)
        self.assertFalse(q.hbc.override.actions)
        self.assertEqual(q.hbc.memory.override.previous_strategy, owned.saved_strategy)
        self.assertFalse(q.hbc.memory.override.forced_write_issued)

    async def test_safe_disable_drains_remaining_steps_of_an_issued_batch(self):
        h = self.h
        await self.prepare_action()
        pre = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        await h.maintenance.request("disable", True, h.views, h.clock(1))
        same_batch = [
            o
            for o in h.ledger.current.operations
            if o.batch_id == h.dispatch._op(pre.operation_id).batch_id
        ]
        self.assertTrue(
            any(o.step_phase == "post" and o.state == S.PREPARED for o in same_batch)
        )
        self.assertTrue(
            any(o.step_phase == "main" and o.state == S.PREPARED for o in same_batch)
        )
