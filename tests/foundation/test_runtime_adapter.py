"""Durable policy adapter and test-only executor lifecycle; no actuator APIs."""

import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.storage import (
    VersionedStore,
    LedgerRepository,
    StorageError,
)
from custom_components.hpvc.policy_runtime import PolicyRuntimeAdapter, align_policy
from custom_components.hpvc.hbc.state import Clock, RawEntity
from custom_components.hpvc.execution.models import (
    ExecutionLedger,
    HandoffRecord,
    OwnershipState,
    PhysicalOperation,
    OperationState,
    TransportStatus,
    VerificationStatus,
    RestoreObligation,
    MaintenanceRecord,
    MaintenanceState,
    Lane,
)
from custom_components.hpvc.execution.facts import (
    AcceptedCommand,
    AcceptedController,
    CommandOutcome,
    ExecutionFacts,
)
from custom_components.hpvc.execution.snapshot import build_execution_snapshot
from custom_components.hpvc.execution.verification import (
    EvidenceCandidate,
    EvidenceKind,
    verify_operation,
    VerificationOutcome,
)
from custom_components.hpvc.execution.settling import (
    SettlingState,
    observe_settling,
    SettlingOutcome,
)
from custom_components.hpvc.control.models import (
    Observation,
    Quality,
    NightRestoreState,
)
from custom_components.hpvc.control.decisions import PolicyMemory
from custom_components.hpvc.inverter.base import fingerprint
from policy_support import make_snapshot, make_views, NOW
from hbc_support import HbcDriver
import json, gzip

ROOT = Path(__file__).parents[2]
HBC = json.loads(
    gzip.decompress(
        (ROOT / "tests/fixtures/hbc-v1.6-sequences.json.gz").read_bytes()
    ).decode("utf-8")
)


def scenario():
    return dict(
        name="runtime-policy",
        grid=-600,
        pv=2500,
        market=-0.01,
        all_in=0.1,
        controllers=[
            dict(
                full=3000,
                minimum=0,
                current=3000,
                unit="Watts",
                step=1,
                available=True,
                participating=True,
            )
        ],
    )


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temp.name) / "plant"
        self.ledger = LedgerRepository(
            VersionedStore(
                self.prefix.with_suffix(".json"), "execution_ledger", ExecutionLedger
            ),
            "plant",
        )
        await self.ledger.load()
        await self.ledger.update(
            lambda l: replace(
                l, ownership=HandoffRecord(state=OwnershipState.READY_DISABLED)
            )
        )
        self.adapter = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        await self.adapter.load(Clock(NOW, 100, "boot"))
        self.s = scenario()
        self.p = make_snapshot(self.s)
        self.views = make_views(self.s)

    async def asyncTearDown(self):
        self.adapter.close()
        self.temp.cleanup()

    def proposal(self, at=0, **kw):
        return self.adapter.propose(
            replace(self.p, now=NOW + at, evaluation_id="evaluation:" + str(at)),
            (),
            Clock(NOW + at, 100 + at, "boot"),
            views=self.views,
            **kw,
        )

    async def issue(self, proposal=None):
        proposal = proposal or self.proposal()
        await self.adapter.accept_proposal(proposal)
        target = proposal.policy.represented.targets[0]
        uid = target.controller_uid
        op = PhysicalOperation(
            "op",
            "batch",
            "main",
            "simulation",
            uid,
            "generic_number",
            "signature:0",
            "config:1",
            representable_controller_target_w=target.representable_target_w,
            prepared_at_utc=NOW,
        )
        await self.ledger.register_operation(op)
        await self.ledger.transition_operation(
            "op", OperationState.ARMED, armed_at_utc=NOW
        )
        await self.ledger.transition_operation(
            "op",
            OperationState.IN_FLIGHT,
            transport=TransportStatus.IN_FLIGHT,
            dispatch_id="dispatch",
            dispatch_started_at_utc=NOW,
        )
        event = AcceptedCommand(
            "event",
            "plant",
            proposal.policy.intent.evaluation_id,
            Clock(NOW, 100, "boot"),
            proposal.policy.intent.action.value,
            (
                AcceptedController(
                    "op",
                    uid,
                    "signature:0",
                    "dispatch",
                    3000,
                    target.representable_target_w,
                ),
            ),
            30,
        )
        await self.adapter.event_recorder.record_simulated_acceptance(event)
        return event, target

    def execution(self, at=0, **kw):
        return build_execution_snapshot(
            self.ledger.current,
            self.p.controllers,
            Clock(NOW + at, 100 + at, "boot"),
            self.adapter.event_recorder.current,
            **kw,
        )

    async def test_proposed_accepted_durable_and_no_plan_cooldown(self):
        old = self.adapter.accepted
        q = self.proposal()
        self.assertEqual(self.adapter.accepted, old)
        self.assertEqual(q.policy.intent.cooldown_until_utc, 0)
        await self.adapter.accept_proposal(q, durable=False)
        self.assertNotEqual(self.adapter.accepted, old)
        self.assertEqual(self.adapter.durable, old)
        self.assertFalse(self.adapter.event_recorder.current.events)
        self.assertEqual(self.execution().cooldown_until_utc, 0)
        q2 = self.proposal(1)
        await self.adapter.accept_proposal(q2)
        self.assertEqual(self.adapter.durable, self.adapter.accepted)

    async def test_stale_generation_and_ledger_revision_rejected(self):
        q = self.proposal()
        await self.adapter.accept_proposal(q)
        with self.assertRaises(SchemaError):
            await self.adapter.accept_proposal(q)
        q = self.proposal(1)
        await self.ledger.update(lambda l: l)
        with self.assertRaises(SchemaError):
            await self.adapter.accept_proposal(q)

    async def test_cooldown_only_after_matching_issued_event(self):
        event, target = await self.issue()
        e = self.execution(10)
        self.assertEqual(e.cooldown_until_utc, NOW + 30)
        self.assertEqual(e.last_command_delta_w, target.representable_target_w - 3000)
        self.assertEqual(e.accepted_event_id, event.event_id)
        self.assertTrue(e.pending_verification)
        self.assertFalse(e.physical_writes_authorized)
        # Idempotent acceptance; mutated provenance is rejected.
        await self.adapter.event_recorder.record_simulated_acceptance(event)
        with self.assertRaises(SchemaError):
            await self.adapter.event_recorder.record_simulated_acceptance(
                replace(event, event_id="wrong", owner_epoch="other")
            )
        with self.assertRaises(SchemaError):
            await self.adapter.event_recorder.record_simulated_acceptance(
                replace(event, event_id="wrong", cooldown_seconds=20)
            )
        with self.assertRaises(SchemaError):
            await self.adapter.event_recorder.record_simulated_acceptance(
                replace(
                    event,
                    event_id="wrong",
                    controllers=(replace(event.controllers[0], target_w=123),),
                )
            )
        self.assertEqual(self.execution(31).cooldown_until_utc, 0)

    async def test_policy_to_independent_verification_settling_next_evaluation(self):
        event, target = await self.issue()
        await self.ledger.transition_operation(
            "op",
            OperationState.SERVICE_COMPLETED,
            transport=TransportStatus.COMPLETED,
            service_completed_at_utc=NOW + 1,
        )
        await self.ledger.transition_operation(
            "op",
            OperationState.AWAITING_VERIFICATION,
            verification=VerificationStatus.PENDING,
        )
        op = self.ledger.current.operations[0]
        candidate = EvidenceCandidate(
            "op",
            op.controller_uid,
            op.configuration_signature,
            "simulation",
            "dispatch",
            EvidenceKind.HA,
            target.representable_target_w,
            NOW + 2,
            NOW + 2,
        )
        stale = verify_operation(
            op,
            replace(candidate, reported_at_utc=NOW - 1),
            now=NOW + 2,
            full_power_w=3000,
        )
        self.assertNotEqual(stale.outcome, VerificationOutcome.CONFIRMED)
        verified = verify_operation(op, candidate, now=NOW + 2, full_power_w=3000)
        self.assertEqual(verified.outcome, VerificationOutcome.CONFIRMED)
        await self.ledger.add_evidence(verified.evidence)
        await self.ledger.transition_operation(
            "op",
            OperationState.VERIFIED,
            verification=VerificationStatus.VERIFIED,
            evidence_ids=(verified.evidence.evidence_id,),
        )
        await self.adapter.event_recorder.record_simulated_outcome(
            CommandOutcome(event.event_id, "verified", Clock(NOW + 2, 102, "boot"))
        )
        state = SettlingState(
            "op", NOW, 3000, target.representable_target_w, 2500, NOW - 1
        )
        for at in (3, 4):
            settled = observe_settling(
                state,
                operation_id="op",
                limit_confirmed=True,
                pv=Observation("pv", 1800, Quality.VALID, NOW + at, NOW + at),
                now=NOW + at,
            )
            state = settled.state
        self.assertEqual(settled.outcome, SettlingOutcome.APPLIED)
        self.assertFalse(self.execution(4, settling=settled).pending_verification)
        self.assertFalse(self.execution(4, settling=settled).settling)
        q = self.proposal(31, settling=settled)
        self.assertFalse(q.policy.intent.physical_writes_authorized)
        self.assertEqual(q.policy.intent.cooldown_until_utc, 0)

    async def fail_operation(self, kind):
        event, _ = await self.issue()
        if kind == "verification_failed":
            await self.ledger.transition_operation(
                "op",
                OperationState.SERVICE_COMPLETED,
                transport=TransportStatus.COMPLETED,
            )
            await self.ledger.transition_operation(
                "op", OperationState.AWAITING_VERIFICATION
            )
        state = {
            "service_failed": OperationState.SERVICE_FAILED,
            "verification_failed": OperationState.VERIFICATION_FAILED,
            "outcome_unknown": OperationState.UNKNOWN,
        }[kind]
        await self.ledger.transition_operation(
            "op",
            state,
            transport=TransportStatus.FAILED
            if kind == "service_failed"
            else TransportStatus.UNKNOWN
            if kind == "outcome_unknown"
            else TransportStatus.COMPLETED,
        )
        await self.adapter.event_recorder.record_simulated_outcome(
            CommandOutcome(event.event_id, kind, Clock(NOW + 2, 102, "boot"))
        )
        e = self.execution(2)
        self.assertTrue(e.recovery_required)
        self.assertTrue(e.last_command_verification_failed)
        self.assertEqual(e.write_eligible_uids, ())

    async def test_fake_service_failure(self):
        await self.fail_operation("service_failed")

    async def test_fake_verification_failure(self):
        await self.fail_operation("verification_failed")

    async def test_fake_outcome_unknown(self):
        await self.fail_operation("outcome_unknown")

    async def test_superseded_unsent_never_starts_cooldown(self):
        op = PhysicalOperation(
            "op",
            "batch",
            "main",
            "simulation",
            "number.inv1",
            "generic_number",
            "signature:0",
            "config:1",
        )
        await self.ledger.register_operation(op)
        await self.ledger.transition_operation("op", OperationState.SUPERSEDED)
        e = self.execution()
        self.assertFalse(e.pending_verification)
        self.assertEqual(e.cooldown_until_utc, 0)

    async def test_disable_restoration_obligation_blocks_even_if_helper_full(self):
        obligation = RestoreObligation(
            "restore", "number.inv1", "signature:0", "config:1", "manual_disable", 3000
        )
        await self.ledger.update(
            lambda l: replace(l, restore_obligations=(obligation,))
        )
        e = self.execution()
        self.assertTrue(e.recovery_required)
        self.assertEqual(e.unresolved_obligation_ids, ("restore",))
        self.assertEqual(e.write_eligible_uids, ())
        q = self.adapter.propose(
            replace(self.p, enabled=False),
            (),
            Clock(NOW, 100, "boot"),
            views=self.views,
        )
        self.assertEqual(q.policy.intent.action.value, "none")
        self.assertEqual(self.execution().unresolved_obligation_ids, ("restore",))

    async def test_maintenance_blocks(self):
        await self.ledger.update(
            lambda l: replace(
                l, maintenance=MaintenanceRecord(state=MaintenanceState.REQUESTED)
            )
        )
        self.assertTrue(self.execution().maintenance_active)
        self.assertEqual(self.execution().write_eligible_uids, ())

    async def test_unknown_ownership_and_wrong_plant_facts_block(self):
        await self.ledger.update(lambda l: replace(l, ownership=HandoffRecord()))
        self.assertTrue(self.execution().recovery_required)
        e = build_execution_snapshot(
            self.ledger.current,
            self.p.controllers,
            Clock(NOW, 100, "boot"),
            ExecutionFacts("other"),
        )
        self.assertTrue(e.recovery_required)

    async def test_restart_honors_original_accepted_deadline(self):
        await self.issue()
        new = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        await new.load(Clock(NOW + 10, 1, "new"))
        e = build_execution_snapshot(
            self.ledger.current,
            self.p.controllers,
            Clock(NOW + 10, 1, "new"),
            new.event_recorder.current,
        )
        self.assertEqual(e.cooldown_until_utc, NOW + 30)
        self.assertTrue(e.pending_verification)
        self.assertIsNone(new.accepted.hbc.last_confirmed)

    async def test_corrupt_policy_store_fails_closed(self):
        self.adapter.store.path.write_text("{broken", encoding="utf-8")
        new = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        with self.assertRaises(StorageError):
            await new.load(Clock(NOW, 1, "new"))
        self.assertFalse(new.store.healthy)

    async def test_missing_companion_store_fails_closed(self):
        self.adapter.event_recorder.store.path.unlink()
        new = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        with self.assertRaises(StorageError):
            await new.load(Clock(NOW, 1, "new"))

    async def test_failed_commit_does_not_advance_accepted_or_durable(self):
        before = self.adapter.accepted
        q = self.proposal()
        with patch(
            "custom_components.hpvc.storage.atomic_replace",
            side_effect=OSError("injected disk failure"),
        ):
            with self.assertRaises(OSError):
                await self.adapter.accept_proposal(q)
        self.assertEqual(self.adapter.accepted, before)
        self.assertEqual(self.adapter.durable, before)
        self.assertTrue(self.adapter.fault)
        with self.assertRaises(StorageError):
            self.proposal(1)

    async def test_negative_override_durable_capture_barrier_and_no_fabricated_write(
        self,
    ):
        row = next(
            row
            for seq in HBC["sequences"]
            for row in seq["cycles"]
            if row["expected"]["override_previous_strategy"] is not None
            and row["input"]["all_in"] <= 0
        )
        driver = HbcDriver("negative")
        result, snapshot = driver.step(row)
        self.p = replace(snapshot.policy, controllers=self.p.controllers)
        entities = snapshot.entities
        snapshot = replace(
            snapshot,
            clock=Clock(snapshot.clock.utc, 100 + snapshot.clock.utc - NOW, "boot"),
        )
        q = self.adapter.propose(
            self.p, entities, snapshot.clock, views=self.views, permission=True
        )
        self.assertFalse(q.hbc.override.memory.forced_write_issued)
        self.assertFalse(
            any(a.requires_durable_capture for a in q.hbc.override.actions)
        )
        await self.adapter.accept_proposal(q, durable=False)
        q = self.adapter.propose(
            self.p, entities, snapshot.clock, views=self.views, permission=True
        )
        self.assertFalse(
            any(a.requires_durable_capture for a in q.hbc.override.actions)
        )
        await self.adapter.accept_proposal(q)
        q = self.adapter.propose(
            self.p, entities, snapshot.clock, views=self.views, permission=True
        )
        self.assertTrue(any(a.requires_durable_capture for a in q.hbc.override.actions))
        self.assertFalse(q.hbc.override.memory.forced_write_issued)
        self.assertFalse(self.adapter.event_recorder.current.events)

    async def test_wall_jump_does_not_complete_night_entry(self):
        old = PolicyMemory(night=NightRestoreState(entry_candidate_since_utc=NOW - 10))
        aligned = align_policy(
            old, Clock(NOW, 100, "boot"), Clock(NOW + 10000, 105, "boot")
        )
        self.assertEqual(NOW + 10000 - aligned.night.entry_candidate_since_utc, 15)

    async def test_night_entry_restart_resets_partial_observation_recovery(self):
        self.p = replace(self.p, pv=Observation("pv", 10, Quality.VALID, NOW, NOW))
        await self.adapter.accept_proposal(self.proposal())
        self.p = replace(
            self.p, pv=Observation("pv", 10, Quality.VALID, NOW + 120, NOW + 120)
        )
        q = self.proposal(120)
        await self.adapter.accept_proposal(q)
        self.assertTrue(q.policy.memory.night.active)
        restarted = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        await restarted.load(Clock(NOW + 121, 1, "new"))
        self.assertTrue(restarted.accepted.policy.night.active)
        self.assertIsNone(restarted.accepted.policy.night.recovery_candidate_since_utc)
        self.assertIsNone(restarted.accepted.policy.night.entry_candidate_since_utc)

    async def test_hbc_simulated_forcing_needs_durable_token_and_bound_native_payload(
        self,
    ):
        row = next(
            row
            for seq in HBC["sequences"]
            for row in seq["cycles"]
            if row["expected"]["override_previous_strategy"] is not None
            and row["input"]["all_in"] <= 0
        )
        _, hs = HbcDriver("override").step(row)
        p = replace(hs.policy, controllers=self.p.controllers)
        clock = Clock(p.now, 100 + p.now - NOW, "boot")
        q = self.adapter.propose(
            p, hs.entities, clock, views=self.views, permission=True
        )
        await self.adapter.accept_proposal(q)
        q = self.adapter.propose(
            p, hs.entities, clock, views=self.views, permission=True
        )
        await self.adapter.accept_proposal(q)
        intent = next(a for a in q.hbc.override.actions if a.step == "enter_strategy")
        op = PhysicalOperation(
            "hbc-op",
            "hbc-batch",
            "enter_strategy",
            "simulation",
            "hbc",
            "hbc",
            "hbc-sig",
            "hbc-config",
            lane=Lane.HBC,
            command_fingerprint=fingerprint(
                [intent.step, intent.entity_id, intent.option]
            ),
        )
        await self.ledger.register_operation(op)
        await self.ledger.transition_operation(
            "hbc-op", OperationState.ARMED, armed_at_utc=p.now
        )
        await self.ledger.transition_operation(
            "hbc-op",
            OperationState.IN_FLIGHT,
            transport=TransportStatus.IN_FLIGHT,
            dispatch_id="hbc-dispatch",
            dispatch_started_at_utc=p.now,
        )
        event = AcceptedCommand(
            "hbc-event",
            "plant",
            p.evaluation_id,
            clock,
            "enter_strategy",
            (
                AcceptedController(
                    "hbc-op",
                    "hbc",
                    "hbc-sig",
                    "hbc-dispatch",
                    None,
                    None,
                    intent.entity_id,
                    intent.option,
                ),
            ),
            0,
            lane="hbc_override",
            capture_token=intent.capture_token,
        )
        with self.assertRaises(SchemaError):
            await self.adapter.event_recorder.record_simulated_acceptance(
                replace(event, capture_token="wrong")
            )
        with self.assertRaises(SchemaError):
            await self.adapter.event_recorder.record_simulated_acceptance(
                replace(
                    event,
                    controllers=(replace(event.controllers[0], native_target="Other"),),
                )
            )
        self.assertFalse(self.adapter.accepted.hbc.override.forced_write_issued)
        await self.adapter.event_recorder.record_simulated_acceptance(event)
        q = self.adapter.propose(
            p, hs.entities, clock, views=self.views, permission=True
        )
        self.assertTrue(q.hbc.override.memory.forced_write_issued)
        self.assertIsNone(self.adapter.event_recorder.current.last_inverter)
        self.assertEqual(self.execution().cooldown_until_utc, 0)
