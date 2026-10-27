"""Actual HA raw HBC observations and durable read-only policy adapter."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
import time
import pytest
from test_policy_acceptance import start, snapshot
from custom_components.hpvc.hbc.state import Clock
from custom_components.hpvc.policy_runtime import capture_entities
from custom_components.hpvc.storage import StorageError

pytestmark = pytest.mark.asyncio


def hbc(hass):
    values = {
        "input_select.house_battery_strategy": "Self Consumption",
        "input_select.house_battery_strategy_charge_goal": "adaptive",
        "input_text.house_battery_strategy_active_sub_strategy": "Charge PV",
        "input_number.house_battery_count": 1,
        "input_number.house_battery_control_prioritize_battery": 1,
        "select.marstek_m1_rs485_control_mode": "enable",
        "sensor.marstek_m1_battery_state_of_charge": 80,
        "sensor.marstek_m1_ac_power": -100,
        "number.marstek_m1_max_charge_power": 1000,
        "input_number.marstek_m1_charging_cutoff_capacity": 100,
        "input_number.marstek_m1_discharging_cutoff_capacity": 10,
    }
    for entity, value in values.items():
        hass.states.async_set(
            entity,
            value,
            {"options": ["Self Consumption", "Charge", "Charge PV"]}
            if entity == "input_select.house_battery_strategy"
            else {},
        )


async def test_ha_raw_hbc_adapter_persists_proposals_never_execution(hass):
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("Physical writes hard Off"),
    ) as calls:
        entry = await start(hass)
        runtime = entry.runtime_data
        adapter = runtime.policy_runtime
        hbc(hass)
        policy = snapshot(runtime)
        raw = capture_entities(runtime.state_reader)
        assert raw
        clock = Clock(policy.now, time.monotonic(), adapter.accepted.hbc.boot_id)
        q = await adapter.evaluate_readonly(policy, raw, clock, permission=True)
        assert q.hbc.configuration_valid
        assert q.hbc.normal_headroom_w == 900
        assert adapter.accepted == adapter.durable
        assert adapter.store.path.exists()
        assert not adapter.event_recorder.current.events
        assert not q.policy.intent.physical_writes_authorized
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert adapter.closed
        calls.assert_not_called()


async def test_ha_policy_memory_corruption_stops_reload(hass):
    entry = await start(hass)
    adapter = entry.runtime_data.policy_runtime
    assert await hass.config_entries.async_unload(entry.entry_id)
    adapter.store.path.write_text("{broken", encoding="utf-8")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.external_limit").state == "3000"


async def test_ha_reload_clears_hbc_continuous_windows_preserves_no_writes(hass):
    entry = await start(hass)
    old = entry.runtime_data.policy_runtime
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    new = entry.runtime_data.policy_runtime
    assert old.closed
    assert old.accepted.hbc.boot_id != new.accepted.hbc.boot_id
    assert new.accepted.hbc.last_confirmed is None
    assert new.accepted.hbc.pending_probe is None
    assert not new.event_recorder.current.events
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
