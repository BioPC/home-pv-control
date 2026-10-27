"""Actual ServiceRegistry transport, harmless aliases only, with closed production gate."""

import asyncio, json
from dataclasses import replace
from unittest.mock import patch
import pytest
from ha_transport_support import start_transport, entity, TEST_DOMAIN
from test_policy_acceptance import start
from custom_components.hpvc.execution.models import Lane, OperationState as S
from custom_components.hpvc.execution.verification import (
    VerificationOutcome,
)
from custom_components.hpvc.control.models import (
    ControllerConfiguration,
    ControllerIdentity,
    AdapterKind,
    ControlMethod,
)
from custom_components.hpvc.inverter.generic_action import GenericActionAdapter
from custom_components.hpvc.inverter.enphase import EnphaseAdapter
from custom_components.hpvc.inverter.base import DiscoveryCandidate
from custom_components.hpvc.policy_runtime import capture_entities

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def no_actual_actuator_domains(hass, monkeypatch):
    original = type(hass.services).async_call

    async def guarded(registry, domain, service, *args, **kwargs):
        assert domain == TEST_DOMAIN, (
            "Actual inverter/HBC domains are forbidden in acceptance CI"
        )
        return await original(registry, domain, service, *args, **kwargs)

    monkeypatch.setattr(type(hass.services), "async_call", guarded)


async def test_normal_installed_executor_exists_and_remains_closed(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    assert runtime.service_executor is not None
    assert not runtime.service_executor.production_admitted
    assert runtime.service_executor._test_admission is None
    assert not runtime.service_executor.physical_writes_authorized
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_number_registry_invocation_receipt_cooldown_and_no_physical_proof(hass):
    h = await start_transport(hass)
    original = type(hass.services).async_call
    called = []

    async def guard(registry, domain, service, *args, **kwargs):
        assert domain == TEST_DOMAIN, "Acceptance must never invoke an actuator domain"
        called.append((domain, service))
        return await original(registry, domain, service, *args, **kwargs)

    with patch.object(type(hass.services), "async_call", guard):
        await h.proposal(register=True)
        assert not h.runtime.policy_runtime.event_recorder.current.events
        request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
        assert request
        await h.finish()
        assert called == [(TEST_DOMAIN, "number_set_value")]
        assert h.calls[0][1] == {"value": 2285, "entity_id": "number.external_limit"}
        assert h.calls[0][2] == S.ARMED
        assert h.runtime.policy_runtime.event_recorder.current.last_inverter
        assert h.dispatch._op(request.operation_id).state == S.AWAITING_VERIFICATION
        assert not h.dispatch._op(request.operation_id).evidence_ids
        assert hass.states.get("number.external_limit").state == "3000"
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        proof = await h.dispatch.finalize_evidence(
            request.operation_id, h.evidence(request), h.clock()
        )
        assert proof.outcome == VerificationOutcome.CONFIRMED
        await h.unload()


@pytest.mark.parametrize("failure", ["service_exception", "validation_failure"])
async def test_real_registry_errors_are_not_verification(hass, failure):
    from homeassistant.exceptions import ServiceValidationError

    h = await start_transport(hass)
    if failure == "service_exception":

        async def handler(call):
            raise RuntimeError("controlled handler exception")

        h.handlers["number.set_value"] = handler
    else:

        def invalid(data):
            raise ServiceValidationError("controlled schema rejection")

        async def never(call):
            raise AssertionError("Invalid data cannot reach handler")

        hass.services.async_register(
            TEST_DOMAIN, "number_set_value", never, schema=invalid
        )
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert h.dispatch._op(request.operation_id).state == S.SERVICE_FAILED
    assert h.executor.current.attempts[-1].exception_type
    assert not h.dispatch._op(request.operation_id).evidence_ids
    assert h.runtime.ledger.current.restore_obligations
    await h.unload()


@pytest.mark.parametrize(
    "change",
    [
        "missing_service",
        "missing_entity",
        "unavailable",
        "configuration",
        "opt_out",
        "epoch",
    ],
)
async def test_real_registry_admission_rechecks_before_issue(hass, change):
    h = await start_transport(hass)
    await h.proposal(register=True)

    async def checkpoint(name, op):
        if name != "before_executor_call":
            return
        if change == "missing_service":
            hass.services.async_remove(TEST_DOMAIN, "number_set_value")
        elif change == "missing_entity":
            hass.states.async_remove("number.external_limit")
        elif change == "unavailable":
            hass.states.async_set("number.external_limit", "unavailable")
        elif change == "epoch":
            h.binding_epoch = "stale"
        else:
            cfg = h.runtime.configuration
            updated = replace(
                cfg.controllers[0],
                **(
                    {"full_limit_w": 3100}
                    if change == "configuration"
                    else {"control_enabled": False}
                ),
            )
            await h.runtime.async_set_configuration(
                replace(cfg, controllers=(updated,))
            )

    h.dispatch.checkpoint = checkpoint
    assert await h.dispatch.pump_lane(Lane.INVERTER, h.clock()) is None
    assert not h.calls and not h.runtime.policy_runtime.event_recorder.current.events
    assert h.runtime.ledger.current.operations[-1].state == S.SUPERSEDED
    await h.unload()


async def test_delayed_completion_after_reload_cannot_advance_old_owner(hass):
    h = await start_transport(hass)
    release = asyncio.Event()
    completed = []

    async def delayed(call):
        await release.wait()
        completed.append(True)

    h.handlers["number.set_value"] = delayed
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    assert request
    assert await hass.config_entries.async_reload(h.entry.entry_id)
    await hass.async_block_till_done()
    assert (
        h.dispatch.closed
        and not h.executor._attempts[request.dispatch_id]["task"].done()
    )
    release.set()
    await h.finish()
    assert completed
    new = h.entry.runtime_data
    assert (
        next(
            o
            for o in new.ledger.current.operations
            if o.operation_id == request.operation_id
        ).state
        == S.UNKNOWN
    )
    assert hass.states.get("number.external_limit").state == "3000"
    assert not new.physical_writes_authorized
    assert await hass.config_entries.async_unload(h.entry.entry_id)


async def test_unload_after_issue_does_not_cancel_service_or_claim_restore(hass):
    h = await start_transport(hass)
    release = asyncio.Event()
    completed = []

    async def delayed(call):
        await release.wait()
        completed.append(True)

    h.handlers["number.set_value"] = delayed
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.unload()
    assert not h.executor._attempts[request.dispatch_id]["task"].done()
    assert h.dispatch._op(request.operation_id).state == S.UNKNOWN
    release.set()
    await h.finish()
    assert completed and h.dispatch._op(request.operation_id).state == S.UNKNOWN


async def test_generic_action_executes_resolved_pre_main_post_without_retemplating(
    hass,
):
    h = await start_transport(hass)
    for name, state in [
        ("sensor.dev6_limit", "3000"),
        ("number.dev6_target", "3000"),
        ("switch.dev6_pre", "off"),
        ("switch.dev6_post", "on"),
    ]:
        hass.states.async_set(name, state)
    cfg = ControllerConfiguration(
        ControllerIdentity("ha_action", 1, AdapterKind.ACTION),
        "sig",
        method=ControlMethod.ACTION,
        full_limit_w=3000,
        readback_entity="sensor.dev6_limit",
        action="script.apply_limit",
        value_field="payload.limit",
        fixed_data_json='{"typed":true,"count":2,"slot":"{{slot}}","literal":"{{unresolved}}"}',
        target_json='{"entity_id":"number.dev6_target"}',
        pre_actions_json='[{"action":"switch.turn_on","target":{"entity_id":"switch.dev6_pre"}}]',
        post_actions_json='[{"action":"switch.turn_off","target":{"entity_id":"switch.dev6_post"}}]',
    )
    h.custom_views = lambda: (
        GenericActionAdapter().normalize(
            cfg, entity(hass, "sensor.dev6_limit"), h.clock().utc
        ),
    )
    await h.proposal(register=True)
    pre = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert await h.dispatch.pump_lane(Lane.INVERTER, h.clock()) is None
    assert await h.native(pre)
    main = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    post = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert await h.native(post)
    assert [x[0] for x in h.calls] == [
        "switch.turn_on",
        "script.apply_limit",
        "switch.turn_off",
    ]
    data = h.calls[1][1]
    assert data["typed"] is True and data["count"] == 2 and data["slot"] == 1
    assert data["literal"] == "{{unresolved}}" and data["payload"]["limit"] == 2285
    assert h.dispatch._op(main.operation_id).state == S.AWAITING_VERIFICATION
    await h.unload()


async def test_enphase_preflight_is_separate_from_main_number_service(hass):
    h = await start_transport(hass)
    hass.states.async_set(
        "number.dev6_enphase", 3000, {"min": 0, "max": 3000, "step": 1}
    )
    hass.states.async_set("switch.dev6_enphase", "off")
    hass.states.async_set(
        "select.dev6_enphase", "Export", {"options": ["Production", "Export"]}
    )
    c = DiscoveryCandidate(
        "enphase:ha",
        "enphase",
        "number.dev6_enphase",
        "device",
        "switch.dev6_enphase",
        "select.dev6_enphase",
    )
    cfg = ControllerConfiguration(
        ControllerIdentity("enphase:ha", 1, AdapterKind.ENPHASE),
        "sig",
        full_limit_w=3000,
        limit_number="number.dev6_enphase",
    )
    h.custom_views = lambda: (
        EnphaseAdapter().normalize(
            cfg,
            entity(hass, "number.dev6_enphase"),
            h.clock().utc,
            candidate=c,
            states=(
                entity(hass, "switch.dev6_enphase"),
                entity(hass, "select.dev6_enphase"),
            ),
        ),
    )
    await h.proposal(register=True)
    enable = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert await h.dispatch.pump_lane(Lane.INVERTER, h.clock()) is None
    assert await h.native(enable)
    mode = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert await h.native(mode)
    assert [x[0] for x in h.calls] == ["switch.turn_on", "select.select_option"]
    assert not h.runtime.policy_runtime.event_recorder.current.events
    await h.proposal(register=True)
    main = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert h.calls[-1][0] == "number.set_value"
    assert h.dispatch._op(main.operation_id).state == S.AWAITING_VERIFICATION
    assert hass.states.get("number.dev6_enphase").state == "3000"
    await h.unload()


async def test_hbc_entry_and_restoration_services_use_independent_select_confirmation(
    hass,
):
    h = await start_transport(hass)
    hass.states.async_set(
        "input_select.house_battery_strategy",
        "Self Consumption",
        {"options": ["Self Consumption", "Charge", "Charge PV"]},
    )
    hass.states.async_set(
        "input_select.house_battery_strategy_charge_goal",
        "adaptive",
        {"options": ["adaptive", "batteries are full"]},
    )
    await h.proposal(all_in=-0.1, permission=True)
    await h.proposal(all_in=-0.1, permission=True)
    observed = []
    for i, price in enumerate([-0.1, -0.1, 0.1, 0.1]):
        if i:
            h.elapsed += 6
            await h.proposal(all_in=price, permission=True)
        q = h.runtime.policy_runtime.last_proposal
        await h.dispatch.submit_hbc(q, h.clock())
        request = await h.dispatch.pump_lane(Lane.HBC, h.clock())
        assert request
        op = h.dispatch._op(request.operation_id)
        observed.append(h.dispatch._reg(op.batch_id).hbc_step)
        await h.finish()
        assert (
            op.expected_native_value
            != hass.states.get(json.loads(request.step.target_json)["entity_id"]).state
        )
        assert await h.native(request)
    h.elapsed += 6
    q = await h.proposal(all_in=0.1, permission=True)
    assert observed == [
        "enter_strategy",
        "enter_goal",
        "restore_goal",
        "restore_strategy",
    ]
    assert await h.dispatch.confirm_hbc_restored(
        q, capture_entities(h.runtime.state_reader), h.clock()
    )
    assert all(
        row.domain == "input_select" and row.called_domain == TEST_DOMAIN
        for row in h.executor.current.attempts
    )
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    await h.unload()


async def test_owner_epoch_change_after_issue_preserves_unknown_result(hass):
    h = await start_transport(hass)
    release = asyncio.Event()

    async def delayed(call):
        await release.wait()

    h.handlers["number.set_value"] = delayed
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    h.binding_epoch = "new-owner-epoch"
    release.set()
    await h.finish()
    assert h.dispatch._op(request.operation_id).state == S.UNKNOWN
    assert h.runtime.ledger.current.restore_obligations
    await h.unload()


async def test_actual_registry_timeout_keeps_issued_task_running(hass):
    h = await start_transport(hass)
    release = asyncio.Event()
    h.executor.timeout_seconds = 0.02

    async def delayed(call):
        await release.wait()

    h.handlers["number.set_value"] = delayed
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    try:
        await asyncio.wait_for(h.executor.results_ready.wait(), 2)
        await h.dispatch.drain_completions()
        assert h.dispatch._op(request.operation_id).state == S.UNKNOWN
        assert not h.executor._attempts[request.dispatch_id]["task"].done()
    finally:
        release.set()
        await h.finish()
    assert h.dispatch._op(request.operation_id).state == S.UNKNOWN
    assert h.executor.current.attempts[-1].result == "late_success"
    await h.unload()


async def test_actual_registry_cancellation_is_not_success(hass):
    h = await start_transport(hass)

    async def cancelled(call):
        raise asyncio.CancelledError()

    h.handlers["number.set_value"] = cancelled
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    await h.finish()
    assert h.dispatch._op(request.operation_id).state == S.UNKNOWN
    assert h.executor.current.attempts[-1].exception_type == "CancelledError"
    await h.unload()


async def test_unload_before_registry_boundary_prevents_the_call(hass):
    h = await start_transport(hass)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = h.executor._audit

    async def gated(row):
        entered.set()
        await release.wait()
        await original(row)

    await h.proposal(register=True)
    with patch.object(h.executor, "_audit", side_effect=gated):
        task = h.runtime.owner.create_task(
            h.dispatch.pump_lane(Lane.INVERTER, h.clock()), "hpvc-test-preissue-unload"
        )
        await entered.wait()
        await h.unload()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert not h.calls
    assert not h.runtime.policy_runtime.event_recorder.current.events
    assert h.runtime.ledger.current.operations[-1].state in (S.SUPERSEDED, S.UNKNOWN)


async def test_opaque_action_transport_cannot_supply_physical_or_maintenance_proof(hass):
    h = await start_transport(hass)
    cfg = ControllerConfiguration(
        ControllerIdentity("opaque_action", 1, AdapterKind.ACTION),
        "sig", method=ControlMethod.ACTION, full_limit_w=3000,
        action="script.apply_limit", value_field="payload.limit",
    )
    h.custom_views = lambda: (
        GenericActionAdapter().normalize(cfg, None, h.clock().utc),
    )
    await h.proposal(register=True)
    request = await h.dispatch.pump_lane(Lane.INVERTER, h.clock())
    assert request
    await h.finish()
    op = h.dispatch._op(request.operation_id)
    assert op.state == S.OPEN_LOOP
    assert not op.evidence_ids
    assert h.runtime.ledger.current.restore_obligations
    assert not h.runtime.physical_writes_authorized
    await h.unload()
