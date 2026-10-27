"""Real HA registry/state/entity/worker acceptance. Physical services are trapped."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers import entity_registry as er, device_registry as dr
from custom_components.hpvc.control.models import (
    PlantConfiguration,
    ControllerConfiguration,
    ControllerIdentity,
    ControlMethod,
)

pytestmark = pytest.mark.asyncio


def controller(**kw):
    values = dict(
        identity=ControllerIdentity("initial", 1),
        signature="initial",
        full_limit_w=1000.0,
        limit_number="number.external_limit",
    )
    values.update(kw)
    return ControllerConfiguration(**values)


async def start(hass, **configuration):
    entry = MockConfigEntry(
        domain="hpvc",
        unique_id="hpvc-primary",
        data={
            "plant_uid": "hpvc-primary",
            "initial_configuration": PlantConfiguration(
                "hpvc-primary", **configuration
            ).to_dict(),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def source(hass, domain="mqtt"):
    entry = MockConfigEntry(domain=domain)
    entry.add_to_hass(hass)
    return entry


def add_opendtu(hass):
    external = source(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=external.entry_id,
        identifiers={("mqtt", "112233445566")},
        manufacturer="Hoymiles",
        model="HMS-1000",
        configuration_url="http://opendtu.local",
    )
    row = er.async_get(hass).async_get_or_create(
        "number",
        "mqtt",
        "112233445566_limit_nonpersistent_absolute",
        suggested_object_id="external_limit",
        config_entry=external,
        device_id=device.id,
    )
    hass.states.async_set(
        row.entity_id,
        500,
        {"min": 0, "max": 9999, "step": 1, "unit_of_measurement": "W"},
    )
    return row, device


async def test_real_number_observation_and_readonly_compatibility(hass):
    hass.states.async_set(
        "number.external_limit",
        500,
        {"min": 0, "max": 1000, "step": 10, "unit_of_measurement": "W"},
    )
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("Actuation forbidden"),
    ) as services:
        entry = await start(hass, inverter_count=1, controllers=(controller(),))
        runtime = entry.runtime_data
        await runtime.refresh_fleet(registry=True)
        await hass.async_block_till_done()
        row = runtime.manager.current.effective[0]
        assert row.view.available and row.view.valid
        assert hass.states.get("sensor.hpvc_pv1_actual_limit").state == "500.0"
        assert hass.states.get("binary_sensor.hpvc_pv1_participating").state == "on"
        assert hass.states.get("binary_sensor.hpvc_pv1_available").state == "on"
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        state = hass.states.get("sensor.hpvc_effective_inverter_runtime")
        assert state.attributes["effective_count"] == 1
        assert state.attributes["physical_writes_authorized"] is False
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_opendtu_registry_get_only_rating_and_worker_cleanup(hass):
    row, device = add_opendtu(hass)
    calls = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def text(self):
            return '{"112233445566":{"max_power":1200,"limit_relative":50,"limit_set_status":"Ok"}}'

    class Session:
        def get(self, url, **kw):
            calls.append((url, kw))
            return Response()

        def post(self, *args, **kw):
            raise AssertionError("HTTP writes forbidden")

    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("Actuation forbidden"),
    ) as services:
        entry = await start(hass)
        runtime = entry.runtime_data
        runtime.http_session_factory = Session
        await runtime.refresh_fleet(registry=True)
        assert len(runtime.manager.current.effective) == 1
        assert runtime.manager.current.effective[0].view.operating_range.full_w == 0
        await runtime.poll_opendtu_status()
        await hass.async_block_till_done()
        view = runtime.manager.current.effective[0].view
        assert view.operating_range.full_w == 1200
        assert view.operating_range.max_power_locked
        assert hass.states.get("binary_sensor.hpvc_pv1_max_power_locked").state == "on"
        assert calls == [
            ("http://opendtu.local/api/limit/status", {"allow_redirects": False})
        ]
        assert not runtime.physical_writes_authorized
        services.assert_not_called()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert (
            runtime.owner.closed and not runtime.owner.tasks and not runtime.listeners
        )
        current = entry.runtime_data
        await current.refresh_fleet(registry=True)
        assert not current.physical_writes_authorized
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert (
            current.owner.closed and not current.owner.tasks and not current.listeners
        )


async def test_real_enphase_renamed_registry_readiness(hass):
    external = source(hass, "enphase_envoy")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=external.entry_id,
        identifiers={("enphase_envoy", "envoy-serial")},
        manufacturer="Enphase",
    )
    registry = er.async_get(hass)
    rows = []
    for domain, uid, value, attrs in [
        (
            "number",
            "serial_dpel_limit",
            500,
            {"min": 0, "max": 5000, "step": 1, "unit_of_measurement": "W"},
        ),
        ("switch", "serial_dpel", "off", {}),
        ("select", "serial_dpel_mode", "Export", {"options": ["Production", "Export"]}),
    ]:
        row = registry.async_get_or_create(
            domain,
            "enphase_envoy",
            uid,
            suggested_object_id="renamed",
            config_entry=external,
            device_id=device.id,
        )
        rows.append(row)
        hass.states.async_set(row.entity_id, value, attrs)
    entry = await start(
        hass,
        inverter_count=1,
        controllers=(controller(limit_number=rows[0].entity_id),),
    )
    runtime = entry.runtime_data
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No DPEL preflight execution"),
    ) as services:
        await runtime.refresh_fleet(registry=True)
        first = runtime.manager.current.effective[0]
        assert first.view.configuration.identity.adapter.value == "enphase"
        assert first.view.available and not first.view.independently_verifiable
        hass.states.async_set(rows[1].entity_id, "on")
        hass.states.async_set(
            rows[2].entity_id, "Production", {"options": ["Production", "Export"]}
        )
        await runtime.refresh_fleet()
        assert runtime.manager.current.effective[0].view.independently_verifiable
        assert runtime.manager.current.effective[0].uid == first.uid
        assert runtime.manager.current.effective[0].view.operating_range.full_w == 1000
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_generic_action_cache_never_actual_limit(hass):
    config = controller(
        method=ControlMethod.ACTION,
        action="mqtt.publish",
        value_field="payload.limit",
        fixed_data_json='{"topic":"test","text":"{{value}} W"}',
    )
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No action execution"),
    ) as services:
        entry = await start(hass, inverter_count=1, controllers=(config,))
        await entry.runtime_data.refresh_fleet(registry=True)
        await hass.async_block_till_done()
        view = entry.runtime_data.manager.current.effective[0].view
        assert view.available and not view.independently_verifiable
        assert view.assumed_limit_w == 1000
        assert hass.states.get("sensor.hpvc_pv1_actual_limit").state == "unknown"
        assert (
            hass.states.get("binary_sensor.hpvc_pv1_independently_verifiable").state
            == "off"
        )
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_manual_optout_changes_participation_not_authorization(hass):
    hass.states.async_set(
        "number.external_limit", 500, {"min": 0, "max": 1000, "step": 1}
    )
    entry = await start(hass, inverter_count=1, controllers=(controller(),))
    runtime = entry.runtime_data
    await runtime.refresh_fleet(registry=True)
    old = runtime.manager.current.effective[0].uid
    await runtime.async_set_configuration(
        replace(
            runtime.configuration,
            controllers=(
                replace(runtime.configuration.controllers[0], control_enabled=False),
            ),
        )
    )
    await runtime.refresh_fleet()
    await hass.async_block_till_done()
    assert runtime.manager.current.effective[0].uid == old
    assert not runtime.manager.current.participating
    assert hass.states.get("binary_sensor.hpvc_pv1_participating").state == "off"
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_registry_rename_and_identity_replacement(hass):
    external = source(hass)
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        "number",
        "number",
        "physical-v1",
        suggested_object_id="external_limit",
        config_entry=external,
    )
    hass.states.async_set(row.entity_id, 500, {"min": 0, "max": 1000, "step": 1})
    entry = await start(
        hass, inverter_count=1, controllers=(controller(limit_number=row.entity_id),)
    )
    runtime = entry.runtime_data
    await runtime.refresh_fleet(registry=True)
    uid = runtime.manager.current.effective[0].uid
    registry.async_update_entity(
        row.entity_id, new_entity_id="number.user_renamed_limit"
    )
    hass.states.async_remove(row.entity_id)
    hass.states.async_set(
        "number.user_renamed_limit", 500, {"min": 0, "max": 1000, "step": 1}
    )
    await runtime.refresh_fleet(registry=True)
    assert runtime.manager.current.effective[0].uid == uid
    registry.async_remove("number.user_renamed_limit")
    registry.async_get_or_create(
        "number",
        "number",
        "physical-v2",
        suggested_object_id="user_renamed_limit",
        config_entry=external,
    )
    # Explicitly select replacement. Reusing the same UI slot cannot inherit proof.
    cfg = replace(
        runtime.configuration.controllers[0], limit_number="number.user_renamed_limit"
    )
    await runtime.async_set_configuration(
        replace(runtime.configuration, controllers=(cfg,))
    )
    await runtime.refresh_fleet(registry=True)
    assert runtime.manager.current.effective[0].uid != uid
    assert not runtime.physical_writes_authorized
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_restart_preserves_unknown_operation_and_restore_obligation(hass):
    from custom_components.hpvc.execution.models import (
        PhysicalOperation,
        OperationState,
    )
    import time

    entry = await start(hass)
    old = entry.runtime_data
    operation = PhysicalOperation(
        "unresolved",
        "batch",
        "main",
        "old-owner",
        "removed-device",
        "generic_number",
        "old-config",
        "old-config-reference",
    )
    await old.ledger.register_operation(operation)
    await old.ledger.transition_operation(
        "unresolved", OperationState.ARMED, armed_at_utc=time.time()
    )
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("Restart cannot dispatch"),
    ) as services:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        runtime = entry.runtime_data
        retained = runtime.ledger.current.operations[0]
        assert retained.state == OperationState.UNKNOWN
        obligation = runtime.ledger.current.restore_obligations[0]
        assert obligation.controller_uid == "removed-device"
        assert obligation.required_target_w is None
        assert runtime.recovery_required
        assert hass.states.get("binary_sensor.hpvc_recovery_required").state == "on"
        assert not runtime.physical_writes_authorized
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)
