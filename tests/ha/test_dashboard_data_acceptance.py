"""New dashboard backend acceptance; requires the exact real-HA test matrix."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from test_foundation_acceptance import start

from custom_components.hpvc.dashboard.builder import REPORT_SECTIONS, parity_dashboard
from custom_components.hpvc.dashboard.data import (
    HISTORY_LIMIT,
    DashboardState,
    HistoryPoint,
    Insight,
)
from custom_components.hpvc.dashboard.presentation import CONDITION_KEYS
from custom_components.hpvc.storage import VersionedStore

pytestmark = pytest.mark.asyncio


async def test_dashboard_native_condition_entities_have_initial_states(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    assert runtime.dashboard_observer.store.path.is_file()
    assert entry.entry_id in runtime.dashboard_observer.store.path.name
    assert runtime.dashboard_observer.store.path.name.endswith("_dashboard.json")
    assert runtime.dashboard_observer.state.points[-1].mode == "unknown"
    for key in CONDITION_KEYS:
        assert hass.states.get("sensor.hpvc_dashboard_" + key) is not None
    status = hass.states.get("sensor.hpvc_status")
    assert status.attributes["ui_report_data_available"] is True
    assert len(status.attributes["ui_report_sections"]) == 10
    assert list(status.attributes["ui_report_sections"]) == list(REPORT_SECTIONS)
    assert (
        status.attributes["ui_maintenance"]["production_transport_authorized"] is False
    )
    await hass.config_entries.async_unload(entry.entry_id)
    assert not runtime.owner.tasks


async def test_dashboard_restart_does_not_promote_historical_execution(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    await runtime.dashboard_observer.sample()
    observer = runtime.dashboard_observer
    now = observer.clock()
    # Synthetic historical fixture; must never become current execution truth.
    seed = replace(
        observer.state,
        points=(
            *observer.state.points,
            HistoryPoint(now, "Limit", evidence_ids=("historical-fixture",)),
        ),
        insights=(Insight(now, "Persisted fixture", "Historical observation"),),
        measured=2,
        within=1,
        absolute_error=30.0,
        squared_error=500.0,
    )
    await observer.store.commit(seed, observer.store.revision)
    observer.state = seed
    count = len(runtime.dashboard_observer.state.points)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    observer = entry.runtime_data.dashboard_observer
    assert len(observer.state.points) >= count + 1
    assert observer.state.points[-1].mode == "unknown"
    assert any(point.mode == "Limit" for point in observer.state.points[:-1])
    assert any(
        item.message == "Historical observation" for item in observer.state.insights
    )
    assert observer.state.measured == 2 and observer.state.within == 1
    assert observer.state.unavailable >= count
    await hass.config_entries.async_unload(entry.entry_id)


async def test_dashboard_bounds_and_local_midnight_in_real_ha(hass):
    entry = await start(hass)
    observer = entry.runtime_data.dashboard_observer
    assert str(observer.zone) == hass.config.time_zone
    moment = datetime(2026, 10, 28, 23, 59, 59, tzinfo=observer.zone).timestamp()
    observer.clock = lambda: moment
    points = tuple(
        HistoryPoint(moment - HISTORY_LIMIT + i) for i in range(HISTORY_LIMIT)
    )
    seed = DashboardState(
        observer.state.plant_uid,
        "2026-10-28",
        points,
        tuple(
            Insight(moment - i, "Fixture", "Historical observation") for i in range(20)
        ),
        measured=2,
        within=1,
    )
    await observer.store.commit(seed, observer.store.revision)
    observer.state = seed
    await observer.sample()
    assert len(observer.state.points) == HISTORY_LIMIT
    assert len(observer.state.insights) <= 20
    moment += 2
    await observer.sample()
    assert observer.state.local_date == "2026-10-29"
    assert observer.state.measured == observer.state.within == 0
    assert not observer.state.insights
    assert len(observer.state.points) == HISTORY_LIMIT
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("damage", ["corrupt", "wrong-plant"])
async def test_dashboard_store_failure_is_visible_and_readonly(hass, damage):
    entry = await start(hass)
    path = entry.runtime_data.dashboard_observer.store.path
    await hass.config_entries.async_unload(entry.entry_id)
    if damage == "corrupt":
        await hass.async_add_executor_job(path.write_text, "invalid fixture")
    else:
        store = VersionedStore(path, "dashboard_observations", DashboardState)
        await store.load()
        await store.commit(DashboardState("another-plant"), store.revision)
    damaged = await hass.async_add_executor_job(path.read_bytes)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    assert runtime.dashboard_observer.fault
    assert not runtime.physical_writes_authorized
    status = hass.states.get("sensor.hpvc_status")
    assert status.attributes["ui_maintenance"]["dashboard_storage"] == "unavailable"
    assert status.attributes["ui_dashboard_data"]["current"]["mode"] == "unknown"
    assert await hass.async_add_executor_job(path.read_bytes) == damaged
    await hass.config_entries.async_unload(entry.entry_id)


async def test_generated_dashboard_loads_through_real_lovelace_backend(hass):
    from homeassistant.components.lovelace import CONFIG_SCHEMA
    from homeassistant.components.lovelace.dashboard import LovelaceYAML

    entry = await start(hass)
    config = parity_dashboard()
    path = Path(hass.config.path("hpvc-ci-dashboard.yaml"))
    # Match the generated artifact's UTF-8 serialization. YAML parsers do not
    # combine JSON's escaped UTF-16 surrogate pairs for non-BMP icons.
    await hass.async_add_executor_job(
        path.write_text, json.dumps(config, ensure_ascii=False), "utf-8"
    )
    dashboard = {"mode": "yaml", "title": "HPVC CI", "filename": str(path)}
    CONFIG_SCHEMA({"lovelace": {"dashboards": {"hpvc-ci": dashboard}}})
    loader = LovelaceYAML(hass, "hpvc-ci", dashboard)
    assert await loader.async_load(True) == config
    assert await loader.async_json(False) is not None
    assert [view["title"] for view in config["views"]] == ["Main", "Settings"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_native_report_templates_render_without_control_services(hass):
    from homeassistant.helpers.template import Template

    entry = await start(hass)

    def markdown(value):
        if isinstance(value, dict):
            if value.get("type") == "markdown":
                yield value
            for child in value.values():
                yield from markdown(child)
        elif isinstance(value, list):
            for child in value:
                yield from markdown(child)

    with patch.object(
        type(hass.services),
        "async_call",
        AsyncMock(side_effect=AssertionError("Report invoked a service")),
    ) as service:
        rendered = [
            (card, Template(card["content"], hass).async_render(parse_result=False))
            for card in markdown(parity_dashboard())
        ]
        service.assert_not_called()
    assert len(rendered) == 64
    report = next(result for card, result in rendered if card.get("title") == "Reports")
    assert all(f"<summary>{title}</summary>" in report for title in REPORT_SECTIONS)
    status = hass.states.get("sensor.hpvc_status")
    assert status.attributes["ui_report_sections"]["Inverters"]["effective_count"] == 0
    assert (
        status.attributes["ui_report_sections"]["Power Control"]["executed_mode"]
        == "unknown"
    )
    assert (
        status.attributes["ui_report_sections"]["HBC & Battery Status"]["available"]
        == "off"
    )
    await hass.config_entries.async_unload(entry.entry_id)
