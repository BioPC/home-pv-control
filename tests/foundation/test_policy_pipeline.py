"""Frozen original-JS differential scenarios and pure operation-plan acceptance."""

import ast
from dataclasses import replace, FrozenInstanceError
import gzip
import hashlib, json
from pathlib import Path
import unittest
from custom_components.hpvc.control.engine import (
    evaluate,
    command_batches,
    controllers_from_fleet,
)
from custom_components.hpvc.control.decisions import (
    PolicyController,
    PolicyMemory,
    Action,
)
from custom_components.hpvc.control.allocation import allocate
from custom_components.hpvc.control.night_restore import transition, after_restart
from custom_components.hpvc.control.models import (
    Observation,
    Quality,
    NightRestoreState,
    ControllerConfiguration,
    ControllerIdentity,
    ControlMethod,
    AdapterKind,
    PlantConfiguration,
)
from custom_components.hpvc.inverter.base import EntityRecord, DiscoveryCandidate
from custom_components.hpvc.inverter.generic_action import GenericActionAdapter
from custom_components.hpvc.inverter.enphase import EnphaseAdapter
from custom_components.hpvc.inverter.hoymiles import (
    HoymilesAdapter,
    OpenDtuCache,
    OpenDtuStatus,
)
from custom_components.hpvc.inverter.manager import InverterManager
from custom_components.hpvc.execution.models import ExecutionSnapshot
from custom_components.hpvc.hbc.models import HbcPolicyInput
from policy_support import make_snapshot, make_views, NOW

ROOT = Path(__file__).parents[2]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/policy-v1.6-oracles.json").read_text(encoding="utf-8")
)


class DifferentialTests(unittest.TestCase):
    pass


def policy_case(row):
    def test(self):
        s = row["input"]
        expected = row["expected"]
        snapshot = make_snapshot(s)
        before = snapshot.to_dict()
        result = evaluate(snapshot, views=make_views(s))
        intent = result.intent
        actual = dict(
            action=intent.action.value,
            status=intent.status,
            reason=intent.reason,
            requested=intent.requested_plant_target_w,
            calculated=intent.calculated_plant_target_w,
            price_mode=intent.price_limiting,
            remembered_price_mode=result.memory.price_limiting,
            cooldown_active=intent.cooldown_active,
            cooldown_until=intent.cooldown_until_utc * 1000,
            night_active=result.memory.night.active,
            night_pending=not result.memory.night.active
            and result.memory.night.entry_candidate_since_utc is not None,
            night_entry_since=(result.memory.night.entry_candidate_since_utc or 0)
            * 1000,
            night_recovery_since=(result.memory.night.recovery_candidate_since_utc or 0)
            * 1000,
            rebalance_applied=result.allocation.rebalance_applied,
            rebalance_confirmed=result.allocation.rebalance_confirmed,
        )
        for key, value in actual.items():
            source = expected[key]
            # The original ZIP contains a mojibake euro glyph. Correct display only.
            if key == "reason":
                source = source.replace("\u00e2\u201a\u00ac", "\u20ac")
            with self.subTest(field=key):
                self.assertEqual(value, source)
        self.assertEqual(
            {
                t.controller_uid: t.target_w
                for t in result.allocation.result.controller_targets
            },
            {t["uid"]: t["target"] for t in expected["targets"]},
        )
        represented = result.represented.targets if result.represented else ()
        self.assertEqual(
            {t.controller_uid: t.representable_target_w for t in represented},
            {t["uid"]: t["target"] for t in expected["represented"]},
        )
        self.assertEqual(
            {t.controller_uid: t.native_value for t in represented},
            {t["uid"]: t["native"] for t in expected["represented"]},
        )
        self.assertEqual(snapshot.to_dict(), before)
        self.assertFalse(intent.physical_writes_authorized)

    return test


for row in FIXTURE["scenarios"]:
    setattr(
        DifferentialTests,
        "test_policy_" + row["input"]["name"].replace("-", "_").replace(".", "_"),
        policy_case(row),
    )


def allocation_case(row):
    def test(self):
        s = row["input"]
        expected = row["expected"]
        controllers = tuple(
            PolicyController(c["uid"], c["current"], c["full"], c["minimum"])
            for c in s["controllers"]
        )
        result = allocate(
            s["name"],
            s["target"],
            controllers,
            frozen_uids=tuple(s["frozen"]),
            rebalance=s["rebalance"],
        )
        self.assertEqual(
            {t.controller_uid: t.target_w for t in result.result.controller_targets},
            {t["uid"]: t["target"] for t in expected["targets"]},
        )
        self.assertEqual(result.rebalance_applied, expected["rebalance_applied"])
        self.assertEqual(result.rebalance_confirmed, expected["rebalance_confirmed"])
        self.assertEqual(result.blocked, expected["halted"])
        self.assertEqual(result.result.requested_plant_target_w, s["target"])
        if controllers:
            self.assertAlmostEqual(
                sum(t.target_w for t in result.result.controller_targets),
                result.result.allocated_plant_target_w,
                places=3,
            )

    return test


for row in FIXTURE["allocations"]:
    setattr(
        DifferentialTests,
        "test_" + row["input"]["name"].replace("-", "_"),
        allocation_case(row),
    )


class PolicySafetyTests(unittest.TestCase):
    def setUp(self):
        self.scenario = FIXTURE["scenarios"][1]["input"]
        self.snapshot = make_snapshot(self.scenario)

    def test_original_flow_digest_matches_oracle(self):
        self.assertEqual(
            hashlib.sha256(
                gzip.decompress(
                    (ROOT / "tests/fixtures/policy-v1.6-runtime.json.gz").read_bytes()
                )
            ).hexdigest(),
            FIXTURE["source_flow_sha256"],
        )

    def test_no_ha_transport_tasks_or_storage_in_policy(self):
        for path in (ROOT / "custom_components/hpvc/control").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    self.fail("Policy cannot run async work: " + str(path))
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = getattr(node, "module", "") or ""
                    names = [a.name for a in node.names]
                    self.assertFalse(
                        any(
                            n.startswith(
                                (
                                    "homeassistant",
                                    "aiohttp",
                                    "requests",
                                    "asyncio",
                                    "os",
                                    "pathlib",
                                    "socket",
                                )
                            )
                            for n in [module, *names]
                        )
                    )
                if isinstance(node, ast.Name):
                    self.assertNotEqual(node.id, "hass")
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(
                        node.attr,
                        (
                            "async_call",
                            "create_task",
                            "commit",
                            "write_text",
                            "write_bytes",
                        ),
                    )

    def test_deterministic_and_immutable(self):
        a = evaluate(self.snapshot)
        b = evaluate(self.snapshot)
        self.assertEqual(a, b)
        with self.assertRaises(FrozenInstanceError):
            a.intent.action = Action.RESTORE
        self.assertEqual(type(a).from_dict(a.to_dict()), a)

    def test_price_freshness_uses_source_two_hour_window(self):
        for age, blocked in [(7200, False), (7201, True)]:
            snap = replace(
                self.snapshot,
                market=replace(self.snapshot.market, reported_at_utc=NOW - age),
                all_in=replace(self.snapshot.all_in, reported_at_utc=NOW - age),
            )
            self.assertEqual(evaluate(snap).intent.blocked, blocked)

    def test_policy_plans_do_not_start_cooldown(self):
        result = evaluate(self.snapshot, views=make_views(self.scenario))
        command_batches(result, make_views(self.scenario), self.snapshot.execution)
        self.assertEqual(result.intent.cooldown_until_utc, 0)

    def test_execution_owns_cooldown_start(self):
        snapshot = replace(
            self.snapshot, execution=ExecutionSnapshot(cooldown_until_utc=NOW + 30)
        )
        self.assertEqual(evaluate(snapshot).intent.action, Action.NONE)
        self.assertEqual(
            evaluate(replace(snapshot, now=NOW + 30)).intent.action, Action.ADJUST
        )

    def test_recovery_and_maintenance_block_plans(self):
        for execution in [
            ExecutionSnapshot(recovery_required=True),
            ExecutionSnapshot(maintenance_active=True),
            ExecutionSnapshot(unresolved_obligation_ids=("restore",)),
        ]:
            result = evaluate(
                replace(self.snapshot, execution=execution),
                views=make_views(self.scenario),
            )
            self.assertEqual(
                command_batches(result, make_views(self.scenario), execution), ()
            )

    def test_write_eligibility_does_not_reallocate_frozen_controller(self):
        s = dict(
            self.scenario,
            controllers=[
                dict(self.scenario["controllers"][0], current=1000),
                dict(self.scenario["controllers"][0], current=1000),
            ],
            grid=1000,
            pv=1000,
        )
        snap = make_snapshot(s)
        snap = replace(
            snap, execution=ExecutionSnapshot(write_eligible_uids=("number.inv2",))
        )
        result = evaluate(snap)
        self.assertEqual(result.allocation.result.controller_targets[0].target_w, 1000)
        self.assertIn("frozen_controller:number.inv1", result.allocation.reasons)

    def test_target_stages_not_overwritten(self):
        s = next(
            r["input"]
            for r in FIXTURE["scenarios"]
            if r["input"]["name"] == "pending-import-saturated"
        )
        result = evaluate(make_snapshot(s), views=make_views(s))
        self.assertEqual(result.intent.requested_plant_target_w, 6000)
        self.assertEqual(result.allocation.result.allocated_plant_target_w, 4000)
        self.assertEqual(result.represented.requested_plant_target_w, 6000)
        self.assertIn("capacity_shortfall", result.allocation.reasons)

    def test_negative_pv_minimum_independent_of_hbc_permission(self):
        snap = replace(
            self.snapshot,
            all_in=Observation("allin", 0, Quality.VALID, NOW, NOW),
            negative_price_hbc_charge=False,
        )
        self.assertEqual(evaluate(snap).intent.action, Action.MINIMUM)
        self.assertFalse(evaluate(snap).intent.hbc_negative_override_requested)

    def test_hbc_request_requires_present_entities_and_permission(self):
        snap = replace(
            self.snapshot,
            all_in=Observation("allin", 0, Quality.VALID, NOW, NOW),
            hbc=HbcPolicyInput(
                available=True, control_enabled=True, override_entities_present=True
            ),
        )
        self.assertTrue(evaluate(snap).intent.hbc_negative_override_requested)
        self.assertFalse(
            evaluate(
                replace(snap, negative_price_hbc_charge=False)
            ).intent.hbc_negative_override_requested
        )

    def test_hbc_restoration_lock_does_not_request_new_negative_override(self):
        snap = replace(
            self.snapshot,
            execution=ExecutionSnapshot(hbc_restore_pending=True),
            hbc=HbcPolicyInput(
                available=True, control_enabled=True, override_entities_present=True
            ),
        )
        result = evaluate(snap)
        self.assertEqual(result.intent.action, Action.MINIMUM)
        self.assertFalse(result.intent.hbc_negative_override_requested)

    def test_no_sun_only_night_entry(self):
        result = transition(
            NightRestoreState(),
            Observation("pv"),
            now=NOW,
            threshold=10,
            sun_below_horizon=True,
        )
        self.assertFalse(result.state.active)
        self.assertFalse(result.pending)

    def test_stale_candidate_without_sun_expires(self):
        result = transition(
            NightRestoreState(entry_candidate_since_utc=NOW - 120),
            Observation("pv"),
            now=NOW,
            threshold=10,
        )
        self.assertFalse(result.state.active)
        self.assertIsNone(result.state.entry_candidate_since_utc)

    def test_restart_keeps_active_resets_partial_windows(self):
        memory = PolicyMemory(
            night=NightRestoreState(True, NOW - 500, NOW - 600, NOW - 29)
        )
        restarted = after_restart(memory)
        self.assertTrue(restarted.night.active)
        self.assertIsNone(restarted.night.entry_candidate_since_utc)
        self.assertIsNone(restarted.night.recovery_candidate_since_utc)

    def test_recovery_requires_continuous_above_threshold(self):
        state = NightRestoreState(
            True, NOW - 500, recovery_candidate_since_utc=NOW - 29
        )
        interrupted = transition(
            state, Observation("pv", 25, Quality.VALID, NOW, NOW), now=NOW, threshold=10
        )
        self.assertTrue(interrupted.state.active)
        self.assertIsNone(interrupted.state.recovery_candidate_since_utc)

    def test_full_proof_invalidates_on_replacement_partial_pending(self):
        state = NightRestoreState(True, NOW - 1000, full_output_proof_reference="proof")
        for controllers, execution, signature in [
            ((PolicyController("a", 500, 1000),), ExecutionSnapshot(), None),
            (
                (PolicyController("a", 1000, 1000),),
                ExecutionSnapshot(pending_verification=True),
                None,
            ),
            (
                (PolicyController("b", None, 1000, available=False),),
                ExecutionSnapshot(),
                "old-signature",
            ),
        ]:
            result = transition(
                state,
                Observation("pv"),
                now=NOW,
                threshold=10,
                controllers=controllers,
                execution=execution,
                previous_fleet_signature=signature,
            )
            self.assertIsNone(result.state.full_output_proof_reference)
            self.assertFalse(result.maintenance_candidate)

    def test_unknown_proof_binding_cannot_survive_missing_telemetry(self):
        result = transition(
            NightRestoreState(True, NOW - 500, full_output_proof_reference="unbound"),
            Observation("pv"),
            now=NOW,
            threshold=10,
            controllers=(PolicyController("a", None, 1000, available=False),),
        )
        self.assertIsNone(result.state.full_output_proof_reference)
        self.assertFalse(result.maintenance_candidate)

    def test_settling_consumed_without_mutating_execution(self):
        execution = ExecutionSnapshot(
            settling=True, frozen_controller_uids=("number.inv1",)
        )
        snapshot = replace(self.snapshot, execution=execution)
        result = evaluate(snapshot, views=make_views(self.scenario))
        self.assertEqual(result.intent.action, Action.NONE)
        self.assertEqual(snapshot.execution, execution)
        self.assertEqual(
            command_batches(result, make_views(self.scenario), execution), ()
        )

    def test_missing_write_eligibility_blocks_downward_plans(self):
        execution = ExecutionSnapshot(write_eligible_uids=())
        result = evaluate(
            replace(self.snapshot, execution=execution), views=make_views(self.scenario)
        )
        self.assertEqual(result.intent.action, Action.NONE)
        self.assertEqual(
            command_batches(result, make_views(self.scenario), execution), ()
        )

    def test_hbc_restore_restricts_maintenance_even_full(self):
        result = transition(
            NightRestoreState(True, NOW - 500),
            Observation("pv"),
            now=NOW,
            threshold=10,
            controllers=(PolicyController("a", 1000, 1000),),
            execution=ExecutionSnapshot(hbc_restore_pending=True),
        )
        self.assertFalse(result.maintenance_candidate)

    def test_open_loop_full_assumption_cannot_be_proof(self):
        result = transition(
            NightRestoreState(True, NOW - 500),
            Observation("pv"),
            now=NOW,
            threshold=10,
            controllers=(PolicyController("a", 1000, 1000, open_loop=True),),
        )
        self.assertFalse(result.full_observed)
        self.assertFalse(result.maintenance_candidate)


class SimulatedPlans(unittest.TestCase):
    def check(self, view, expected_actions):
        snapshot = make_snapshot(FIXTURE["scenarios"][1]["input"])
        controller = PolicyController(
            view.configuration.identity.uid,
            view.observation.limit.value or view.assumed_limit_w,
            view.operating_range.full_w,
            view.operating_range.minimum_w,
        )
        result = evaluate(replace(snapshot, controllers=(controller,)), views=(view,))
        plans = command_batches(result, (view,), snapshot.execution)
        self.assertEqual(
            [step.action for batch in plans for step in batch.steps], expected_actions
        )
        for batch in plans:
            self.assertEqual(
                batch.requested_plant_target_w, result.intent.requested_plant_target_w
            )
            self.assertFalse(hasattr(batch, "execute"))
        return result, plans

    def test_generic_number_sequence(self):
        view = make_views(FIXTURE["scenarios"][1]["input"])[0]
        result, plans = self.check(view, ["number.set_value"])
        self.assertEqual(json.loads(plans[0].steps[0].data_json), {"value": 2285})
        self.assertEqual(
            json.loads(plans[0].steps[0].target_json), {"entity_id": "number.inv1"}
        )

    def test_generic_action_exact_pre_main_post(self):
        cfg = ControllerConfiguration(
            ControllerIdentity("action", 1, AdapterKind.ACTION),
            "sig",
            method=ControlMethod.ACTION,
            full_limit_w=3000,
            action_step=1,
            action="mqtt.publish",
            value_field="payload.limit",
            fixed_data_json='{"topic":"test","text":"{{value}} W"}',
            pre_actions_json='[{"action":"switch.turn_on","target":{"entity_id":"switch.enable"}}]',
            post_actions_json='[{"action":"switch.turn_off","target":{"entity_id":"switch.finish"}}]',
        )
        view = GenericActionAdapter().normalize(cfg, None, NOW)
        result, plans = self.check(
            view, ["switch.turn_on", "mqtt.publish", "switch.turn_off"]
        )
        self.assertEqual(
            json.loads(plans[0].steps[1].data_json),
            {"topic": "test", "text": "2285 W", "payload": {"limit": 2285}},
        )

    def test_enphase_preflight_then_separately_observed_main(self):
        candidate = DiscoveryCandidate(
            "enphase:device",
            "enphase",
            "number.limit",
            "device",
            "switch.enable",
            "select.mode",
        )
        cfg = ControllerConfiguration(
            ControllerIdentity("e", 1),
            "sig",
            full_limit_w=3000,
            limit_number="number.limit",
        )
        limit = EntityRecord(
            "number.limit", "3000", NOW, '{"min":0,"max":3000,"step":1}'
        )
        states = (
            limit,
            EntityRecord("switch.enable", "off", NOW),
            EntityRecord(
                "select.mode", "Export", NOW, '{"options":["Production","Export"]}'
            ),
        )
        adapter = EnphaseAdapter()
        view = adapter.normalize(cfg, limit, NOW, candidate=candidate, states=states)
        _, plans = self.check(view, ["switch.turn_on", "select.select_option"])
        self.assertTrue(plans[0].requires_readiness)
        ready = adapter.normalize(
            cfg,
            limit,
            NOW,
            candidate=candidate,
            states=(
                limit,
                replace(states[1], state="on"),
                replace(states[2], state="Production"),
            ),
        )
        self.check(ready, ["number.set_value"])

    def test_opendtu_absolute_watt_plan_only(self):
        candidate = DiscoveryCandidate(
            "hoymiles:device", "hoymiles", "number.limit", "device"
        )
        cache = OpenDtuCache()
        cache.accept(
            OpenDtuStatus(
                candidate.uid,
                "device",
                "number.limit",
                "serial",
                NOW - 1,
                NOW,
                3000,
                100,
                "Ok",
            )
        )
        cfg = ControllerConfiguration(
            ControllerIdentity("h", 1),
            "sig",
            full_limit_w=1000,
            limit_number="number.limit",
        )
        view = HoymilesAdapter().normalize(
            cfg,
            EntityRecord("number.limit", "3000", NOW, '{"min":0,"max":9999,"step":1}'),
            NOW,
            candidate=candidate,
            cache=cache,
        )
        result, plans = self.check(view, ["number.set_value"])
        self.assertEqual(json.loads(plans[0].steps[0].data_json), {"value": 2285})

    def test_manual_auto_dedup_feeds_pure_pipeline(self):
        cfg = ControllerConfiguration(
            ControllerIdentity("manual", 1),
            "sig",
            full_limit_w=3000,
            limit_number="number.a_limit_nonpersistent_absolute",
        )
        state = EntityRecord(
            cfg.limit_number,
            "3000",
            NOW,
            '{"min":0,"max":3000,"step":1,"unit_of_measurement":"W"}',
        )
        fleet = InverterManager().refresh(
            PlantConfiguration("plant", inverter_count=1, controllers=(cfg,)),
            (state,),
            (),
            (),
            now=NOW,
        )
        controllers = controllers_from_fleet(fleet)
        self.assertEqual(len(controllers), 1)
        result = evaluate(
            replace(
                make_snapshot(FIXTURE["scenarios"][1]["input"]), controllers=controllers
            ),
            views=tuple(r.view for r in fleet.effective),
        )
        self.assertEqual(result.intent.action, Action.ADJUST)
