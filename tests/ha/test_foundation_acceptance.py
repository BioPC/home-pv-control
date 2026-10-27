"""Additional real-HA acceptance invariants required before adapter expansion."""

from pathlib import Path
from unittest.mock import Mock
import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.loader import async_get_integration
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.hpvc.control.models import PlantConfiguration

pytestmark = pytest.mark.asyncio


def make_entry(hass, **configuration):
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
    return entry


async def start(hass, **configuration):
    entry = make_entry(hass, **configuration)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_integration_discovery_manifest(hass):
    integration = await async_get_integration(hass, "hpvc")
    assert integration.domain == "hpvc"
    assert integration.manifest["config_flow"] is True
    assert integration.manifest["requirements"] == []


async def test_all_native_unique_ids_stable_across_reload(hass):
    entry = await start(hass)
    registry = er.async_get(hass)
    before = {
        (item.domain, item.unique_id): item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert len(before) == 282
    assert len(set(before.values())) == 282
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = {
        (item.domain, item.unique_id): item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert before == after
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_user_entity_rename_survives_reload(hass):
    entry = await start(hass)
    registry = er.async_get(hass)
    registry.async_update_entity(
        "text.hpvc_grid_power_sensor", new_entity_id="text.user_hpvc_grid_source"
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        registry.async_get_entity_id("text", "hpvc", "hpvc-primary:grid_power_sensor")
        == "text.user_hpvc_grid_source"
    )
    assert hass.states.get("text.user_hpvc_grid_source") is not None
    assert hass.states.get("text.hpvc_grid_power_sensor") is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_source_listener_and_timer_cleanup(hass):
    entry = await start(hass, grid_power_sensor="sensor.hpvc_acceptance_grid")
    runtime = entry.runtime_data
    runtime.scheduler.mark_telemetry_dirty = Mock(
        wraps=runtime.scheduler.mark_telemetry_dirty
    )
    hass.states.async_set("sensor.hpvc_acceptance_grid", 100)
    await hass.async_block_till_done()
    assert runtime.scheduler.mark_telemetry_dirty.call_count == 1
    handles = tuple(runtime.scheduler._handles)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert all(handle.cancelled() for handle in handles)
    assert runtime.owner.closed and not runtime.owner.tasks and not runtime.listeners
    runtime.scheduler.mark_telemetry_dirty.reset_mock()
    hass.states.async_set("sensor.hpvc_acceptance_grid", 200)
    await hass.async_block_till_done()
    runtime.scheduler.mark_telemetry_dirty.assert_not_called()


async def test_corrupt_execution_ledger_never_becomes_empty_success(hass):
    entry = await start(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    path = Path(hass.config.path(".storage", f"hpvc_{entry.entry_id}_execution.json"))
    await hass.async_add_executor_job(path.write_text, "{corrupt", "utf-8")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.SETUP_RETRY
    assert getattr(entry, "runtime_data", None) is None
    entry.async_cancel_retry_setup()
    assert path.read_text(encoding="utf-8") == "{corrupt"


async def test_missing_execution_ledger_blocks_existing_install(hass):
    entry = await start(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    path = Path(hass.config.path(".storage", f"hpvc_{entry.entry_id}_execution.json"))
    await hass.async_add_executor_job(path.unlink)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.SETUP_RETRY
    assert getattr(entry, "runtime_data", None) is None
    entry.async_cancel_retry_setup()
    assert not path.exists()


async def test_partial_legacy_detection_requires_recovery(hass):
    hass.states.async_set("input_text.hpvc_status", "Idle")
    entry = await start(hass)
    assert entry.runtime_data.migration_state == "legacy_presence_unknown"
    assert entry.runtime_data.recovery_required
    assert not entry.runtime_data.physical_writes_authorized
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_malformed_legacy_preview_does_not_create_entry(hass):
    hass.states.async_set("input_number.hpvc_inverter_count", "not-a-number")
    result = await hass.config_entries.flow.async_init(
        "hpvc", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"import_legacy": True, "inverter_count": 0}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_legacy"
    assert hass.config_entries.async_entries("hpvc") == []
