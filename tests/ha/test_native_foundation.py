"""Real Home Assistant setup/config-flow/entity/unload acceptance tests.

Run unchanged assertions on the pinned minimum/current Linux HA matrix.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.hpvc.control.models import PlantConfiguration, ControlSettings

pytestmark = pytest.mark.asyncio


def entry_data():
    return {
        "plant_uid": "hpvc-primary",
        "initial_configuration": PlantConfiguration("hpvc-primary").to_dict(),
    }


async def setup(hass, data=None):
    entry = MockConfigEntry(
        domain="hpvc", unique_id="hpvc-primary", data=data or entry_data()
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_real_setup_zero_and_authorization(hass):
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No service calls in foundation"),
    ) as calls:
        entry = await setup(hass)
        assert hass.states.get("number.hpvc_inverter_count").state == "0"
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        assert (
            hass.states.get("binary_sensor.hpvc_required_inputs_ready").state == "off"
        )
        runtime = entry.runtime_data
        await runtime.async_set_configuration(
            replace(runtime.configuration, enabled_intent=True, inverter_count=10)
        )
        runtime.scheduler.startup_wake()
        await hass.async_block_till_done()
        assert hass.states.get("switch.hpvc_enabled").state == "on"
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        calls.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_reload_and_no_owned_work(hass):
    entry = await setup(hass)
    old = entry.runtime_data
    await old.async_set_configuration(replace(old.configuration, enabled_intent=True))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert old.owner.closed and not old.owner.tasks and not old.listeners
    assert entry.runtime_data is not old
    assert entry.runtime_data.configuration.enabled_intent
    assert entry.runtime_data.physical_writes_authorized is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert getattr(entry, "runtime_data", None) is None


async def test_real_user_flow_accepts_zero(hass):
    result = await hass.config_entries.flow.async_init(
        "hpvc", context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"inverter_count": 0, "import_legacy": False}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["initial_configuration"]["inverter_count"] == 0
    await hass.async_block_till_done()
    entry = result["result"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_legacy_import_preview_is_not_handoff(hass):
    values = {
        "input_number.hpvc_inverter_count": "0",
        "input_boolean.hpvc_enabled": "on",
    }
    values.update(
        {
            "input_number.hpvc_" + key: str(getattr(ControlSettings(), key))
            for key in ControlSettings.__dataclass_fields__
        }
    )
    for key, value in values.items():
        hass.states.async_set(key, value)
    result = await hass.config_entries.flow.async_init(
        "hpvc", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"import_legacy": True, "inverter_count": 0}
    )
    assert result["step_id"] == "legacy_preview"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.runtime_data.migration_state == "handoff_pending"
    assert hass.states.get("input_boolean.hpvc_enabled").state == "on"
    assert entry.runtime_data.physical_writes_authorized is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_native_entity_setters_do_not_target_inverters(hass):
    entry = await setup(hass)
    calls = []
    original = type(hass.services).async_call

    async def guarded(registry, domain, service, service_data=None, *args, **kwargs):
        calls.append((domain, service, service_data))
        target = (service_data or {}).get("entity_id", "")
        assert isinstance(target, str) and target.startswith(
            ("switch.hpvc_", "number.hpvc_", "text.hpvc_", "select.hpvc_")
        )
        return await original(registry, domain, service, service_data, *args, **kwargs)

    with patch.object(type(hass.services), "async_call", new=guarded):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.hpvc_enabled"}, blocking=True
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.hpvc_inverter_count", "value": 10},
            blocking=True,
        )
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": "text.hpvc_pv1_action", "value": "number.set_value"},
            blocking=True,
        )
        await hass.async_block_till_done()
    assert len(calls) == 3
    assert entry.runtime_data.physical_writes_authorized is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_registry_collision_does_not_take_legacy_ownership(hass):
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        "template",
        "hpvc_installed_version",
        suggested_object_id="hpvc_installed_version",
    )
    hass.states.async_set(legacy.entity_id, "1.6.0")
    entry = await setup(hass)
    native = registry.async_get_entity_id(
        "sensor", "hpvc", "hpvc-primary:installed_version"
    )
    assert native and native != legacy.entity_id
    assert hass.states.get(legacy.entity_id).state == "1.6.0"
    assert await hass.config_entries.async_unload(entry.entry_id)
