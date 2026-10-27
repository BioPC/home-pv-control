"""Behavioral acceptance of production read-only adapters, fleet and evidence."""

import json
from pathlib import Path
import unittest
from dataclasses import replace, FrozenInstanceError
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.control.models import (
    ControllerConfiguration,
    ControllerIdentity,
    PlantConfiguration,
    ControlMethod,
    LimitUnit,
    Quality,
    Observation,
)
from custom_components.hpvc.inverter.base import (
    EntityRecord,
    RegistryEntity,
    RegistryDevice,
    DiscoveryCandidate,
    ReadbackSource,
)
from custom_components.hpvc.inverter.generic_number import GenericNumberAdapter
from custom_components.hpvc.inverter.generic_action import (
    GenericActionAdapter,
    substitute,
)
from custom_components.hpvc.inverter.detection import discover_controllers
from custom_components.hpvc.inverter.manager import InverterManager
from custom_components.hpvc.inverter.hoymiles import (
    OpenDtuCache,
    OpenDtuStatus,
    HoymilesAdapter,
    parse_status,
    async_read_status,
    status_url,
)
from custom_components.hpvc.inverter.enphase import EnphaseAdapter
from custom_components.hpvc.execution.models import (
    PhysicalOperation,
    OperationState,
    TransportStatus,
    ExecutionLedger,
)
from custom_components.hpvc.execution.verification import (
    EvidenceCandidate,
    EvidenceKind,
    VerificationOutcome,
    verify_operation,
)
from custom_components.hpvc.execution.recovery import (
    assess_recovery,
    reconstruct_restore_obligations,
    classify_operation,
)
from custom_components.hpvc.execution.settling import (
    SettlingState,
    SettlingOutcome,
    observe_settling,
)

NOW = 1000.0


def state(entity="number.limit", value="500", stamp=NOW, **attrs):
    return EntityRecord(entity, value, stamp, json.dumps(attrs))


def config(**kw):
    defaults = dict(
        identity=ControllerIdentity("physical", 1),
        signature="test",
        full_limit_w=1000.0,
        low_limit_w=0.0,
        limit_number="number.limit",
    )
    defaults.update(kw)
    return ControllerConfiguration(**defaults)


def number(value="500", stamp=NOW, **attrs):
    defaults = dict(min=0, max=1000, step=10, unit_of_measurement="W")
    defaults.update(attrs)
    return state(value=value, stamp=stamp, **defaults)


def enphase():
    registry = tuple(
        RegistryEntity(
            entity,
            device_id="envoy",
            platform="enphase_envoy",
            config_entry_id="envoy-entry",
            unique_id=uid,
            registry_id=uid,
        )
        for entity, uid in [
            ("number.renamed", "serial_dpel_limit"),
            ("switch.renamed", "serial_dpel"),
            ("select.renamed", "serial_dpel_mode"),
        ]
    )
    states = (
        state(
            "number.renamed", "500", min=0, max=5000, step=1, unit_of_measurement="W"
        ),
        state("switch.renamed", "on"),
        state("select.renamed", "Production", options=["Production", "Export"]),
    )
    return registry, (RegistryDevice("envoy", "Enphase"),), states


def op(**kw):
    defaults = dict(
        operation_id="op",
        batch_id="batch",
        step_id="main",
        owner_epoch="epoch",
        controller_uid="physical",
        adapter_kind="generic_number",
        configuration_signature="sig",
        configuration_reference="config:1",
        dispatch_id="dispatch",
        dispatch_started_at_utc=900.0,
        representable_controller_target_w=500.0,
        state=OperationState.AWAITING_VERIFICATION,
        transport=TransportStatus.COMPLETED,
    )
    defaults.update(kw)
    return PhysicalOperation(**defaults)


def evidence(**kw):
    defaults = dict(
        operation_id="op",
        controller_uid="physical",
        configuration_signature="sig",
        owner_epoch="epoch",
        dispatch_id="dispatch",
        kind=EvidenceKind.HA,
        native_value=500.0,
        received_at_utc=NOW,
        reported_at_utc=NOW,
    )
    defaults.update(kw)
    return EvidenceCandidate(**defaults)


class NumberTests(unittest.TestCase):
    def test_observation_zero_is_valid(self):
        view = GenericNumberAdapter().normalize(config(), number("0"), NOW)
        self.assertTrue(view.available)
        self.assertEqual(view.observation.limit.value, 0)

    def test_unknown_unavailable_invalid_and_stale(self):
        for value, quality in [
            ("unknown", Quality.UNKNOWN),
            ("unavailable", Quality.UNAVAILABLE),
            ("NaN", Quality.INVALID),
        ]:
            with self.subTest(value=value):
                self.assertEqual(
                    GenericNumberAdapter()
                    .normalize(config(), number(value), NOW)
                    .observation.limit.quality,
                    quality,
                )
        self.assertEqual(
            GenericNumberAdapter()
            .normalize(config(), number(stamp=800), NOW)
            .observation.limit.quality,
            Quality.STALE,
        )

    def test_manual_rating_not_native_maximum(self):
        view = GenericNumberAdapter().normalize(
            config(full_limit_w=800), number(max=9999), NOW
        )
        self.assertEqual(view.operating_range.full_w, 800)

    def test_invalid_ranges_fail_closed(self):
        for attrs in [
            dict(min=1),
            dict(max=900),
            dict(step=0),
            dict(min=2000, max=1000),
        ]:
            with self.subTest(attrs=attrs):
                view = GenericNumberAdapter().normalize(config(), number(**attrs), NOW)
                self.assertFalse(view.valid)
                with self.assertRaises(SchemaError):
                    GenericNumberAdapter().represent(view, 500)

    def test_rounding_ties_and_full_endpoint(self):
        adapter = GenericNumberAdapter()
        view = adapter.normalize(config(full_limit_w=995), number(), NOW)
        for desired, expected in [
            (505, 510),
            (504, 500),
            (995, 995),
            (2000, 995),
            (-10, 0),
        ]:
            with self.subTest(desired=desired):
                self.assertEqual(
                    adapter.represent(view, desired).native_value, expected
                )

    def test_minimum_and_import_floor_round_up(self):
        adapter = GenericNumberAdapter()
        view = adapter.normalize(config(low_limit_w=25), number(), NOW)
        self.assertEqual(adapter.represent(view, 0).native_value, 30)
        self.assertEqual(
            adapter.represent(view, 50, import_floor_w=64).native_value, 70
        )

    def test_percent_representation_and_readback(self):
        adapter = GenericNumberAdapter()
        view = adapter.normalize(
            config(unit=LimitUnit.PERCENT), number("50", max=100, step=1), NOW
        )
        self.assertEqual(view.observation.limit.value, 500)
        target = adapter.represent(view, 505)
        self.assertEqual(
            (
                target.allocated_target_w,
                target.native_value,
                target.representable_target_w,
            ),
            (505, 51, 510),
        )

    def test_528_source_javascript_quantization_oracles(self):
        fixture = json.loads(
            (
                Path(__file__).parents[1] / "fixtures" / "readonly-v1.6-oracle.json"
            ).read_text()
        )
        for case in fixture["cases"]:
            with self.subTest(case=case):
                cfg = config(
                    full_limit_w=case["full"],
                    low_limit_w=case["minimum"],
                    unit=LimitUnit(case["unit"]),
                )
                entity = number(
                    max=9999 if case["unit"] == "Watts" else 100, step=case["step"]
                )
                adapter = GenericNumberAdapter()
                view = adapter.normalize(cfg, entity, NOW)
                represented = adapter.represent(
                    view, case["desired"], import_floor_w=case["floor"]
                )
                self.assertEqual(represented.native_value, case["expected_native"])
                self.assertEqual(
                    represented.representable_target_w, case["expected_effective"]
                )

    def test_plan_is_frozen_data_and_disabled_optout(self):
        adapter = GenericNumberAdapter()
        view = adapter.normalize(config(), number(), NOW)
        plan = adapter.build_plan(
            view, adapter.represent(view, 500), batch_id="b", evaluation_id="e"
        )
        self.assertEqual(plan.steps[0].action, "number.set_value")
        with self.assertRaises(FrozenInstanceError):
            plan.batch_id = "new"
        self.assertFalse(view.physical_writes_authorized)
        view = adapter.normalize(config(control_enabled=False), number(), NOW)
        with self.assertRaises(SchemaError):
            adapter.build_plan(
                view, adapter.represent(view, 500), batch_id="b", evaluation_id="e"
            )


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = GenericActionAdapter()
        self.config = config(
            method=ControlMethod.ACTION,
            action="mqtt.publish",
            value_field="payload.limit",
            fixed_data_json=json.dumps(
                {
                    "typed": "{{value}}",
                    "embedded": "x{{value}}W",
                    "list": ["{{slot}}", "{{unknown}}"],
                    "maximum": "{{maximum_watts}}",
                }
            ),
            target_json='{"entity_id":"number.slot_{{slot}}"}',
            pre_actions_json='[{"action":"switch.turn_on","data":{"v":"{{desired_watts}}"}}]',
            post_actions_json='[{"action":"switch.turn_off","data":{"v":"{{target_watts}}"}}]',
            action_step=10,
        )

    def test_nested_tokens_types_order_and_target(self):
        view = self.adapter.normalize(self.config, None, NOW)
        plan = self.adapter.build_plan(
            view, self.adapter.represent(view, 505), batch_id="b", evaluation_id="e"
        )
        self.assertEqual([step.phase for step in plan.steps], ["pre", "main", "post"])
        main = json.loads(plan.steps[1].data_json)
        self.assertEqual(
            main,
            {
                "typed": 510,
                "embedded": "x510W",
                "list": [1, "{{unknown}}"],
                "maximum": 1000,
                "payload": {"limit": 510},
            },
        )
        self.assertEqual(
            json.loads(plan.steps[1].target_json), {"entity_id": "number.slot_1"}
        )
        self.assertEqual(json.loads(plan.steps[0].data_json)["v"], 505)
        self.assertEqual(json.loads(plan.steps[2].data_json)["v"], 510)

    def test_open_loop_startup_is_not_readback(self):
        view = self.adapter.normalize(self.config, None, NOW)
        self.assertTrue(view.available)
        self.assertFalse(view.supports_verification)
        self.assertFalse(view.independently_verifiable)
        self.assertEqual(view.current_source, ReadbackSource.STARTUP_ASSUMPTION)
        self.assertIsNone(view.observation.limit.value)

    def test_cache_is_not_proof(self):
        view = self.adapter.normalize(self.config, None, NOW, command_cache_w=200)
        self.assertEqual(view.assumed_limit_w, 200)
        self.assertIsNone(view.observation.limit.value)
        self.assertFalse(view.independently_verifiable)

    def test_optional_readback_staleness(self):
        cfg = replace(self.config, readback_entity="sensor.readback")
        self.assertTrue(
            self.adapter.normalize(
                cfg, state("sensor.readback"), NOW
            ).independently_verifiable
        )
        self.assertFalse(
            self.adapter.normalize(
                cfg, state("sensor.readback", stamp=700), NOW
            ).available
        )

    def test_action_zero_step_is_one_percent(self):
        cfg = replace(self.config, unit=LimitUnit.PERCENT, action_step=0)
        view = self.adapter.normalize(cfg, None, NOW)
        self.assertEqual(self.adapter.represent(view, 505).native_value, 51)

    def test_refresh_semantics(self):
        view = self.adapter.normalize(
            replace(self.config, refresh_seconds=30), None, NOW
        )
        self.assertEqual(self.adapter.refresh_reason(view, NOW), "initial_sync")
        self.assertEqual(
            self.adapter.refresh_reason(
                view, NOW, cached_command_w=100, last_write_at_utc=970
            ),
            "heartbeat_due",
        )
        self.assertIsNone(
            self.adapter.refresh_reason(
                view, NOW, cached_command_w=100, last_write_at_utc=971
            )
        )

    def test_invalid_json_actions_and_payloads(self):
        for change in [
            dict(action="bad"),
            dict(fixed_data_json="[]"),
            dict(target_json="null"),
            dict(pre_actions_json='[{"action":"bad"}]'),
            dict(fixed_data_json='{"x":NaN}'),
        ]:
            with self.subTest(change=change):
                self.assertFalse(
                    self.adapter.normalize(
                        replace(self.config, **change), None, NOW
                    ).valid
                )

    def test_recursive_substitution_keeps_unknown(self):
        self.assertEqual(
            substitute(
                {"a": ["{{value}}", "{{percent}}%", "{{nope}}"]},
                {"value": 12, "percent": 25},
            ),
            {"a": [12, "25%", "{{nope}}"]},
        )


class DiscoveryTests(unittest.TestCase):
    def test_enphase_registry_metadata_with_renamed_entities(self):
        registry, devices, states = enphase()
        found = discover_controllers(registry, devices, states)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].uid, "enphase:envoy")
        self.assertEqual(found[0].limit_entity, "number.renamed")

    def test_enphase_wrong_role_missing_mode_disabled_ambiguous(self):
        registry, devices, states = enphase()
        variants = [
            registry[:2],
            (replace(registry[0], unique_id="serial_pv_limit"), *registry[1:]),
            (replace(registry[0], disabled=True), *registry[1:]),
            (*registry, replace(registry[0], entity_id="number.duplicate")),
        ]
        for rows in variants:
            with self.subTest(rows=rows):
                self.assertEqual(discover_controllers(rows, devices, states), ())

    def test_enphase_capability_options_required(self):
        registry, devices, states = enphase()
        states = (
            *states[:2],
            state("select.renamed", "Production", options=["Production"]),
        )
        self.assertEqual(discover_controllers(registry, devices, states), ())

    def test_enphase_readiness_and_preflight_only_plan(self):
        registry, devices, states = enphase()
        candidate = discover_controllers(registry, devices, states)[0]
        adapter = EnphaseAdapter()
        notready = (
            states[0],
            replace(states[1], state="off"),
            replace(states[2], state="Export"),
        )
        view = adapter.normalize(
            config(), states[0], NOW, candidate=candidate, states=notready
        )
        self.assertTrue(view.available)
        self.assertFalse(view.independently_verifiable)
        plan = adapter.build_plan(
            view, adapter.represent(view, 500), batch_id="b", evaluation_id="e"
        )
        self.assertTrue(plan.requires_readiness)
        self.assertEqual(
            [s.phase for s in plan.steps], ["enphase-enable", "enphase-production"]
        )
        ready = adapter.normalize(
            config(), states[0], NOW, candidate=candidate, states=states
        )
        self.assertTrue(ready.independently_verifiable)
        self.assertEqual(
            adapter.build_plan(
                ready, adapter.represent(ready, 500), batch_id="b", evaluation_id="e"
            )
            .steps[0]
            .phase,
            "main",
        )

    def test_enphase_stale_readiness_is_not_ready(self):
        registry, devices, states = enphase()
        candidate = discover_controllers(registry, devices, states)[0]
        view = EnphaseAdapter().normalize(
            config(),
            states[0],
            NOW,
            candidate=candidate,
            states=(states[0], replace(states[1], reported_at_utc=700), states[2]),
        )
        self.assertFalse(view.available)
        self.assertFalse(view.readiness_observed)

    def test_enphase_range_remains_user_owned(self):
        registry, devices, states = enphase()
        candidate = discover_controllers(registry, devices, states)[0]
        view = EnphaseAdapter().normalize(
            config(full_limit_w=1200),
            states[0],
            NOW,
            candidate=candidate,
            states=states,
        )
        self.assertEqual(view.operating_range.full_w, 1200)
        self.assertFalse(view.operating_range.max_power_locked)

    def test_opendtu_rejects_wrong_roles_platform_and_units(self):
        device = RegistryDevice("d", "Hoymiles", "HMS-1000")
        entry = RegistryEntity(
            "number.user_renamed",
            device_id="d",
            platform="mqtt",
            unique_id="112233445566_limit_nonpersistent_absolute",
        )
        states = (state(entry.entity_id, unit_of_measurement="W", max=9999),)
        self.assertEqual(len(discover_controllers((entry,), (device,), states)), 1)
        for role in [
            "limit_persistent_absolute",
            "limit_nonpersistent_relative",
            "limit_persistent_relative",
        ]:
            self.assertEqual(
                discover_controllers(
                    (replace(entry, unique_id=role),), (device,), states
                ),
                (),
            )
        self.assertEqual(
            discover_controllers(
                (replace(entry, platform="other"),), (device,), states
            ),
            (),
        )
        self.assertEqual(
            discover_controllers(
                (entry,),
                (device,),
                (replace(states[0], attributes_json='{"unit_of_measurement":"%"}'),),
            ),
            (),
        )

    def test_opendtu_rating_precedence_never_ha_max(self):
        cache = OpenDtuCache()
        candidate = DiscoveryCandidate("hoymiles:d", "hoymiles", "number.limit", "d")
        adapter = HoymilesAdapter()
        view = adapter.normalize(
            config(full_limit_w=800),
            number(max=99999),
            NOW,
            candidate=candidate,
            cache=cache,
        )
        self.assertEqual(view.operating_range.full_w, 800)
        cache.accept(
            OpenDtuStatus(
                candidate.uid,
                "d",
                "number.limit",
                "112233445566",
                990,
                995,
                1200,
                50,
                "Ok",
            )
        )
        self.assertEqual(
            cache.rated_power(candidate.uid, 800), (1200, "OpenDTU API", True)
        )
        cache.accept(
            OpenDtuStatus(
                candidate.uid,
                "d",
                "number.limit",
                "112233445566",
                996,
                997,
                None,
                50,
                "Ok",
            )
        )
        self.assertEqual(
            cache.rated_power(candidate.uid, 800), (1200, "OpenDTU API cache", True)
        )
        self.assertFalse(
            cache.accept(
                OpenDtuStatus(candidate.uid, "d", "number.limit", "", 900, 901, 1500)
            )
        )
        self.assertEqual(cache.rated_power("unknown", 0)[0], 0)

    def test_opendtu_parse_serial_and_poll_times(self):
        c = DiscoveryCandidate(
            "uid", "hoymiles", "number.limit", "d", serial="112233445566"
        )
        payload = {
            "112233445566": {
                "max_power": 1200,
                "limit_relative": 50,
                "limit_set_status": "Ok",
            }
        }
        self.assertEqual(
            parse_status(payload, (c,), poll_started_at_utc=990, received_at_utc=995)[
                0
            ].controller_uid,
            "uid",
        )
        self.assertEqual(
            parse_status(
                payload,
                (replace(c, serial="other"),),
                poll_started_at_utc=990,
                received_at_utc=995,
            ),
            (),
        )
        self.assertEqual(
            parse_status(payload, (c,), poll_started_at_utc=996, received_at_utc=995),
            (),
        )


class FleetTests(unittest.TestCase):
    def test_zero_and_ten_with_overflow(self):
        manager = InverterManager()
        self.assertEqual(
            manager.refresh(PlantConfiguration("plant"), (), now=NOW).effective, ()
        )
        states = tuple(
            state(
                f"number.d{i}_limit_nonpersistent_absolute",
                "500",
                min=0,
                max=1000,
                unit_of_measurement="W",
            )
            for i in range(11)
        )
        result = manager.refresh(PlantConfiguration("plant"), states, (), (), now=NOW)
        self.assertEqual(len(result.effective), 10)
        self.assertEqual(len(result.overflow_uids), 1)
        self.assertFalse(result.physical_writes_authorized)

    def test_dedup_manual_auto_and_optout(self):
        registry, devices, states = enphase()
        cfg = config(limit_number="number.renamed", control_enabled=False)
        result = InverterManager().refresh(
            PlantConfiguration("plant", inverter_count=1, controllers=(cfg,)),
            states,
            registry,
            devices,
            now=NOW,
        )
        self.assertEqual(len(result.effective), 1)
        self.assertEqual(len(result.participating), 0)
        self.assertEqual(result.available_capacity_w, 0)

    def test_replacement_in_same_slot_changes_identity(self):
        manager = InverterManager()
        plant = PlantConfiguration("plant", inverter_count=1, controllers=(config(),))
        registry = (RegistryEntity("number.limit", registry_id="old", device_id="old"),)
        old = (
            manager.refresh(plant, (number(),), registry, (), now=NOW).effective[0].uid
        )
        result = manager.refresh(
            plant,
            (number(),),
            (replace(registry[0], registry_id="new", device_id="new"),),
            (),
            now=NOW,
        )
        self.assertNotEqual(old, result.effective[0].uid)
        self.assertEqual(result.replacement_pairs, ((old, result.effective[0].uid, 1),))

    def test_registry_entity_rename_keeps_identity(self):
        manager = InverterManager()
        plant = PlantConfiguration("plant", inverter_count=1, controllers=(config(),))
        entry = RegistryEntity("number.limit", registry_id="stable", device_id="device")
        old = (
            manager.refresh(plant, (number(),), (entry,), (), now=NOW).effective[0].uid
        )
        result = manager.refresh(
            plant,
            (replace(number(), entity_id="number.renamed"),),
            (replace(entry, entity_id="number.renamed"),),
            (),
            now=NOW,
        )
        self.assertEqual(result.effective[0].uid, old)
        self.assertFalse(result.replacement_pairs)

    def test_removed_reappears_with_rebalance(self):
        manager = InverterManager()
        registry, devices, states = enphase()
        plant = PlantConfiguration("plant")
        uid = (
            manager.refresh(plant, states, registry, devices, now=NOW).effective[0].uid
        )
        self.assertEqual(
            manager.refresh(plant, (), (), (), now=NOW).removed_uids, (uid,)
        )
        returned = manager.refresh(plant, states, registry, devices, now=NOW)
        self.assertEqual(returned.recovered_uids, (uid,))
        self.assertEqual(returned.rebalance_uids, (uid,))

    def test_auto_optout_follows_identity_after_slot_move(self):
        manager = InverterManager()
        a = state(
            "number.a_limit_nonpersistent_absolute",
            "500",
            min=0,
            max=1000,
            unit_of_measurement="W",
        )
        b = state(
            "number.b_limit_nonpersistent_absolute",
            "500",
            min=0,
            max=1000,
            unit_of_measurement="W",
        )
        first = manager.refresh(PlantConfiguration("plant"), (a, b), (), (), now=NOW)
        old = first.effective[0]
        bound = config(
            identity=ControllerIdentity(old.uid, 1),
            auto_managed=True,
            auto_identity=old.uid,
            limit_number=a.entity_id,
            control_enabled=False,
        )
        # Manual slot 1 forces the same automatic controller to another slot.
        manual = config(
            identity=ControllerIdentity("manual", 1), limit_number="number.limit"
        )
        bound = replace(bound, identity=replace(bound.identity, slot=2))
        plant = PlantConfiguration(
            "plant", inverter_count=2, controllers=(manual, bound)
        )
        moved = manager.refresh(plant, (number(), a, b), (), (), now=NOW)
        row = next(row for row in moved.effective if row.uid == old.uid)
        self.assertFalse(row.participating)
        self.assertTrue(
            next(
                row
                for row in moved.effective
                if row.uid != old.uid and row.origin == "auto"
            ).participating
        )

    def test_mixed_fleet_and_availability_dimensions(self):
        registry, devices, states = enphase()
        action = config(
            identity=ControllerIdentity("action", 2),
            method=ControlMethod.ACTION,
            action="mqtt.publish",
            full_limit_w=600,
        )
        generic = config(
            identity=ControllerIdentity("generic", 3), limit_number="number.limit"
        )
        od = state(
            "number.hm_limit_nonpersistent_absolute",
            "300",
            min=0,
            max=1000,
            unit_of_measurement="W",
        )
        result = InverterManager().refresh(
            PlantConfiguration(
                "plant", inverter_count=3, controllers=(action, generic)
            ),
            (*states, number(), od),
            registry,
            devices,
            now=NOW,
        )
        self.assertEqual(
            {row.view.configuration.identity.adapter.value for row in result.effective},
            {"generic_action", "generic_number", "hoymiles", "enphase"},
        )
        self.assertFalse(
            next(
                row for row in result.effective if row.slot == 2
            ).view.independently_verifiable
        )


class EvidenceTests(unittest.TestCase):
    def verdict(self, candidate, operation=None, **kw):
        return verify_operation(
            operation or op(), candidate, now=NOW, full_power_w=1000, **kw
        ).outcome

    def test_matching_fresh_independent_evidence(self):
        self.assertEqual(self.verdict(evidence()), VerificationOutcome.CONFIRMED)

    def test_all_callback_identity_components_match(self):
        for key in [
            "operation_id",
            "controller_uid",
            "configuration_signature",
            "owner_epoch",
            "dispatch_id",
        ]:
            with self.subTest(key=key):
                self.assertEqual(
                    self.verdict(evidence(**{key: "wrong"})),
                    VerificationOutcome.IDENTITY_MISMATCH,
                )

    def test_cache_assumptions_and_helper_never_success(self):
        for kind in [
            EvidenceKind.COMMAND_CACHE,
            EvidenceKind.STARTUP_ASSUMPTION,
            EvidenceKind.LEGACY_HELPER,
        ]:
            self.assertEqual(
                self.verdict(evidence(kind=kind)), VerificationOutcome.UNVERIFIABLE
            )

    def test_stale_predispatch_target_shaped_readback(self):
        for stamp in [899, 700, None, 1100]:
            with self.subTest(stamp=stamp):
                self.assertEqual(
                    self.verdict(evidence(reported_at_utc=stamp)),
                    VerificationOutcome.STALE,
                )

    def test_mismatch_and_missing_value(self):
        self.assertEqual(
            self.verdict(evidence(native_value=800)), VerificationOutcome.VALUE_MISMATCH
        )
        self.assertEqual(
            self.verdict(evidence(native_value=None)), VerificationOutcome.UNKNOWN
        )

    def test_evidence_source_cannot_cross_adapter_kind(self):
        self.assertEqual(
            self.verdict(
                evidence(kind=EvidenceKind.ENPHASE, enabled=True, production_mode=True)
            ),
            VerificationOutcome.IDENTITY_MISMATCH,
        )

    def test_no_dispatch_identity_is_unknown(self):
        self.assertEqual(
            self.verdict(evidence(dispatch_id=None), op(dispatch_id=None)),
            VerificationOutcome.UNKNOWN,
        )

    def test_enphase_readiness_is_mandatory(self):
        operation = op(adapter_kind="enphase")
        self.assertEqual(
            self.verdict(
                evidence(
                    kind=EvidenceKind.ENPHASE, enabled=False, production_mode=True
                ),
                operation,
            ),
            VerificationOutcome.NOT_READY,
        )
        self.assertEqual(
            self.verdict(
                evidence(kind=EvidenceKind.ENPHASE, enabled=True, production_mode=True),
                operation,
            ),
            VerificationOutcome.CONFIRMED,
        )

    def test_opendtu_poll_timing_serial_status_and_freshness(self):
        operation = op(adapter_kind="hoymiles")
        candidate = evidence(
            kind=EvidenceKind.OPENDTU,
            poll_started_at_utc=950,
            max_power_w=1000,
            relative_limit=50,
            command_status="Ok",
            device_id="d",
            serial="112233445566",
        )

        def verdict(c):
            return self.verdict(
                c, operation, expected_device_id="d", expected_serial="112233445566"
            )

        self.assertEqual(verdict(candidate), VerificationOutcome.CONFIRMED)
        self.assertEqual(
            verdict(replace(candidate, poll_started_at_utc=899)),
            VerificationOutcome.STALE,
        )
        self.assertEqual(
            verdict(replace(candidate, serial="wrong")),
            VerificationOutcome.IDENTITY_MISMATCH,
        )
        self.assertEqual(
            verdict(replace(candidate, command_status="Pending")),
            VerificationOutcome.UNKNOWN,
        )
        self.assertEqual(
            verdict(replace(candidate, received_at_utc=800)), VerificationOutcome.STALE
        )

    def test_percent_normalization(self):
        self.assertEqual(
            self.verdict(evidence(unit=LimitUnit.PERCENT, native_value=50)),
            VerificationOutcome.CONFIRMED,
        )


class RecoverySettlingTests(unittest.TestCase):
    def test_quiescence_does_not_prove_physical_success(self):
        result = classify_operation(op())
        self.assertTrue(result.execution_quiescent)
        self.assertTrue(result.physical_outcome_unknown)

    def test_unsent_plan_has_no_restore_obligation(self):
        ledger = ExecutionLedger(
            "plant",
            operations=(
                op(
                    state=OperationState.PREPARED,
                    transport=TransportStatus.NOT_SENT,
                    dispatch_id=None,
                    dispatch_started_at_utc=None,
                ),
            ),
        )
        self.assertFalse(assess_recovery(ledger).required)
        self.assertEqual(reconstruct_restore_obligations(ledger), ())

    def test_restart_reconstructs_identity_bound_unknown_range(self):
        ledger = ExecutionLedger("plant", operations=(op(),))
        rows = reconstruct_restore_obligations(ledger)
        self.assertEqual(rows[0].controller_uid, "physical")
        self.assertIsNone(rows[0].required_target_w)
        self.assertTrue(assess_recovery(ledger).required)
        self.assertEqual(
            reconstruct_restore_obligations(replace(ledger, restore_obligations=rows)),
            rows,
        )

    def test_archived_range_not_replacement_slot(self):
        ledger = ExecutionLedger("plant", operations=(op(),))
        rows = reconstruct_restore_obligations(
            ledger,
            {
                "config:1": config(full_limit_w=1200),
                "replacement": config(full_limit_w=2000),
            },
        )
        self.assertEqual(rows[0].required_target_w, 1200)

    def test_settling_stale_and_wrong_operation_never_release(self):
        settling = SettlingState("op", 900, 1000, 500, 1000)
        for stamp, operation in [(899, "op"), (950, "old")]:
            result = observe_settling(
                settling,
                operation_id=operation,
                limit_confirmed=True,
                pv=Observation("pv", 500, Quality.VALID, stamp),
                now=1000,
            )
            self.assertTrue(result.hold_ordinary_reversal)
            self.assertFalse(result.physical_restoration_verified)

    def test_large_change_needs_two_distinct_stable_samples(self):
        settling = SettlingState("op", 900, 1000, 500, 1000)

        def observe(s, stamp, value=500):
            return observe_settling(
                s,
                operation_id="op",
                limit_confirmed=True,
                pv=Observation("pv", value, Quality.VALID, stamp),
                now=1000,
            )

        first = observe(settling, 950)
        self.assertTrue(first.hold_ordinary_reversal)
        self.assertTrue(observe(first.state, 950).hold_ordinary_reversal)
        second = observe(first.state, 960)
        self.assertEqual(second.outcome, SettlingOutcome.APPLIED)
        self.assertFalse(second.physical_restoration_verified)

    def test_timeout_without_evidence_never_physical_success(self):
        result = observe_settling(
            SettlingState("op", 800, 1000, 500, 1000),
            operation_id="op",
            limit_confirmed=False,
            pv=Observation("pv"),
            now=1000,
        )
        self.assertEqual(result.outcome, SettlingOutcome.TIMED_OUT)
        self.assertFalse(result.physical_restoration_verified)


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_get_fixed_endpoint_and_no_redirect(self):
        calls = []

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def text(self):
                return '{"serial":{"max_power":1000}}'

        class Session:
            def get(self, url, **kw):
                calls.append((url, kw))
                return Response()

            def post(self, *args, **kw):
                raise AssertionError("No write HTTP")

        result = await async_read_status(Session(), "http://opendtu.local")
        self.assertEqual(result["serial"]["max_power"], 1000)
        self.assertEqual(
            calls,
            [("http://opendtu.local/api/limit/status", {"allow_redirects": False})],
        )

    async def test_unsafe_status_urls_rejected(self):
        for url in [
            "file:///tmp",
            "http://user:pass@host",
            "http://host?x=1",
            "http://host/#write",
        ]:
            with self.subTest(url=url), self.assertRaises(SchemaError):
                status_url(url)
