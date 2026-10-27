"""Real HA read-only observation to pure policy/plan acceptance."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
import json, time
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.hpvc.control.models import (
    PlantConfiguration,
    ControllerConfiguration,
    ControllerIdentity,
    Observation,
    Quality,
    NightRestoreState,
)
from custom_components.hpvc.control.decisions import (
    PolicySnapshot,
    PolicyMemory,
    Action,
)
from custom_components.hpvc.control.engine import (
    evaluate,
    controllers_from_fleet,
    command_batches,
)
from custom_components.hpvc.control.night_restore import after_restart
from custom_components.hpvc.execution.models import ExecutionSnapshot

pytestmark = pytest.mark.asyncio


async def start(hass):
    cfg = ControllerConfiguration(
        ControllerIdentity("initial", 1),
        "sig",
        full_limit_w=3000,
        limit_number="number.external_limit",
    )
    config = PlantConfiguration("hpvc-primary", inverter_count=1, controllers=(cfg,))
    hass.states.async_set(
        "number.external_limit",
        3000,
        {"min": 0, "max": 3000, "step": 1, "unit_of_measurement": "W"},
    )
    entry = MockConfigEntry(
        domain="hpvc",
        unique_id="hpvc-primary",
        data={"plant_uid": "hpvc-primary", "initial_configuration": config.to_dict()},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.refresh_fleet(registry=True)
    return entry


def snapshot(runtime, **kw):
    now = time.time()
    observation = lambda source, value: Observation(
        source, value, Quality.VALID, now, now
    )
    values = dict(
        evaluation_id="real-ha-policy",
        now=now,
        grid=observation("grid", -600),
        pv=observation("pv", 2500),
        market=observation("market", -0.01),
        all_in=observation("allin", 0.1),
        controllers=controllers_from_fleet(runtime.manager.current),
        enabled=True,
    )
    values.update(kw)
    return PolicySnapshot(**values)


async def test_real_ha_observation_policy_allocation_representation_plan(hass):
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No live policy dispatcher"),
    ) as services:
        entry = await start(hass)
        runtime = entry.runtime_data
        views = tuple(row.view for row in runtime.manager.current.effective)
        snap = snapshot(runtime)
        before = snap.to_dict()
        result = evaluate(snap, views=views)
        assert result.intent.action == Action.ADJUST
        assert result.intent.requested_plant_target_w == 2285
        assert result.allocation.result.allocated_plant_target_w == 2285
        assert result.represented.representable_plant_target_w == 2285
        batches = command_batches(result, views, snap.execution)
        assert [step.action for batch in batches for step in batch.steps] == [
            "number.set_value"
        ]
        assert json.loads(batches[0].steps[0].data_json) == {"value": 2285}
        assert snap.to_dict() == before
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        assert hass.states.get("number.external_limit").state == "3000"
        services.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "restriction", ["pending", "settling", "recovery", "maintenance"]
)
async def test_real_ha_policy_consumes_execution_restrictions_without_dispatch(
    hass, restriction
):
    entry = await start(hass)
    runtime = entry.runtime_data
    execution = ExecutionSnapshot(
        pending_verification=restriction == "pending",
        settling=restriction == "settling",
        recovery_required=restriction == "recovery",
        maintenance_active=restriction == "maintenance",
    )
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No execution calls"),
    ) as services:
        views = tuple(row.view for row in runtime.manager.current.effective)
        result = evaluate(snapshot(runtime, execution=execution), views=views)
        assert result.intent.action == Action.NONE
        assert command_batches(result, views, execution) == ()
        assert not runtime.physical_writes_authorized
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_ha_pure_planning_does_not_start_cooldown_or_orphan_tasks(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No planning side effects"),
    ) as services:
        before = runtime.ledger.current
        views = tuple(row.view for row in runtime.manager.current.effective)
        result = evaluate(snapshot(runtime), views=views)
        command_batches(result, views, ExecutionSnapshot())
        assert result.intent.cooldown_until_utc == 0
        assert runtime.ledger.current == before
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert (
            runtime.owner.closed and not runtime.owner.tasks and not runtime.listeners
        )
        assert hass.states.get("number.external_limit").state == "3000"
        assert not entry.runtime_data.physical_writes_authorized
        services.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_ha_night_active_persistence_partial_window_reset(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    now = time.time()
    night = NightRestoreState(
        active=True, active_since_utc=now - 500, recovery_candidate_since_utc=now - 29
    )
    await runtime.ledger.update(lambda value: replace(value, night_restore=night))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restored = entry.runtime_data.ledger.current.night_restore
    assert restored.active and restored.recovery_candidate_since_utc is None
    assert (
        after_restart(PolicyMemory(night=night)).night.recovery_candidate_since_utc
        is None
    )
    assert not entry.runtime_data.physical_writes_authorized
    assert await hass.config_entries.async_unload(entry.entry_id)
