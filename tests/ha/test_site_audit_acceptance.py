"""Actual HA read APIs and audit mutation traps. No PV/HBC service call is permitted."""

import json, sys, time, copy
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock
import pytest
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.setup import async_setup_component
from test_policy_acceptance import start

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "foundation"))
from site_audit_fixture import sample
from custom_components.hpvc.site_audit.capture import capture_hass, read_device_entries
from custom_components.hpvc.site_audit.engine import audit_site
from custom_components.hpvc.site_audit.schema import EXPECTED
from audit_tools.protocol import ReadOnlyHAClient
from audit_tools.collect_site import collect

pytestmark = pytest.mark.asyncio


async def test_actual_HA_audit_cannot_mutate_any_installation_boundary(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    before_states = {s.entity_id: s.as_dict() for s in hass.states.async_all()}
    before_er = dict(registry.entities)
    before_dr = {r.id: r for r in read_device_entries(devices)}
    before_cfg = copy.deepcopy(dict(entry.data))
    before_handoff = runtime.handoff.current
    before_ledger = runtime.ledger.current
    before_manager = runtime.manager.current
    mutations = []

    def deny(*args, **kwargs):
        mutations.append(True)
        raise AssertionError("Audit attempted a production mutation")

    with ExitStack() as stack:
        for obj, names in [
            (type(hass.services), ("async_call",)),
            (type(hass.states), ("async_set", "async_remove")),
            (
                type(registry),
                ("async_update_entity", "async_remove", "async_get_or_create"),
            ),
            (
                type(devices),
                ("async_update_device", "async_remove_device", "async_get_or_create"),
            ),
            (
                type(hass.config_entries),
                ("async_update_entry", "async_reload", "async_remove", "async_add"),
            ),
        ]:
            for name in names:
                if hasattr(obj, name):
                    stack.enter_context(patch.object(obj, name, side_effect=deny))
        for store in (
            runtime.config_store,
            runtime.history_store,
            runtime.ledger.store,
            runtime.handoff.store,
        ):
            stack.enter_context(patch.object(store, "commit", side_effect=deny))
        bundle = capture_hass(hass, ha_version="test-pinned", now=time.time())
        result = audit_site(bundle, now=time.time())
    assert not mutations
    assert (
        dict(registry.entities) == before_er
        and {r.id: r for r in read_device_entries(devices)} == before_dr
    )
    assert {s.entity_id: s.as_dict() for s in hass.states.async_all()} == before_states
    assert entry.data == before_cfg
    assert (
        runtime.handoff.current == before_handoff
        and runtime.ledger.current == before_ledger
    )
    assert runtime.manager.current is before_manager
    assert not result["production_transport_authorized"]
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_actual_HA_capture_preserves_last_reported_and_never_invents_sensor_Off(
    hass,
):
    hass.states.async_set(
        EXPECTED[0],
        "2000",
        {"min": 0, "max": 9999, "step": 1, "unit_of_measurement": "W"},
    )
    hass.states.async_set("input_boolean.hpvc_enabled", "on")
    b = capture_hass(hass, ha_version="test-pinned", now=time.time())
    row = next(r for r in b["states"] if r["entity_id"] == EXPECTED[0])
    assert (
        row["last_reported"] == hass.states.get(EXPECTED[0]).last_reported.timestamp()
    )
    r = audit_site(b, now=time.time())
    assert r["native"]["installed"] is False
    assert r["native"]["physical_write_sensor_observed"] is None
    assert not r["production_transport_authorized"]
    assert not r["expected_controllers"][0]["verified"]


async def test_actual_HA_websocket_read_allowlist_uses_full_registry_response(
    hass, hass_ws_client
):
    assert await async_setup_component(hass, "config", {})
    registry = er.async_get(hass)
    owned = registry.async_get_or_create(
        "number",
        "mqtt",
        "112233445566_limit_nonpersistent_absolute",
        suggested_object_id="audit_limit",
    )
    client = await hass_ws_client(hass)
    ro = ReadOnlyHAClient(client)
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No services"),
    ) as calls:
        assert isinstance(await ro.read("get_states"), list)
        assert isinstance(await ro.read("get_config"), dict)
        assert isinstance(await ro.read("config/entity_registry/list"), list)
        full = await ro.read(
            "config/entity_registry/get_entries", entity_ids=[owned.entity_id]
        )
        assert full[owned.entity_id]["unique_id"] == owned.unique_id
        assert isinstance(await ro.read("config/device_registry/list"), list)
        assert isinstance(await ro.read("config_entries/get"), list)
        calls.assert_not_called()


async def test_external_collector_against_contained_actual_HA_server(
    hass, hass_client, hass_access_token
):
    assert await async_setup_component(hass, "config", {})
    assert await async_setup_component(hass, "websocket_api", {})
    hass.states.async_set("input_number.hpvc_inverter_count", "0")
    http = await hass_client()
    base = str(http.server.make_url("/")).rstrip("/")
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No audit services"),
    ) as calls:
        result = await collect(base, hass_access_token, read_opendtu=False)
        calls.assert_not_called()
    assert result["source"] == "production_export"
    assert result["coverage"]["states"] is True
    assert hass_access_token not in json.dumps(result)
    assert not result["opendtu"]


@pytest.mark.parametrize(
    "failure",
    [
        "device_owner",
        "entry_missing",
        "api_serial",
        "api_status",
        "api_stale",
        "legacy_owner",
        "HBC_owned",
        "flow_unknown",
    ],
)
async def test_exported_audit_blocks_each_unknown_without_activating_native(
    hass, failure
):
    entry = await start(hass)
    now = time.time()
    b = sample(now)
    if failure == "device_owner":
        b["device_registry"][0]["config_entries"] = []
    elif failure == "entry_missing":
        b["config_entries"] = []
    elif failure == "api_serial":
        b["opendtu"][0]["payload"] = {}
    elif failure == "api_status":
        b["opendtu"][0]["payload"]["112233445566"]["limit_set_status"] = "Pending"
    elif failure == "api_stale":
        b["opendtu"][0]["received_at_utc"] = now - 60
    elif failure == "legacy_owner":
        b["legacy"]["bridge"]["runtime_owner"] = "old"
    elif failure == "HBC_owned":
        b["legacy"]["bridge"]["hbc_override_owned"] = True
    else:
        b["legacy"]["fingerprint"] = "unknown"
    before = entry.runtime_data.handoff.current
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No audit services"),
    ) as calls:
        r = audit_site(b, now=now)
        calls.assert_not_called()
    assert r["overall_verdict"] != "READY_FOR_CONTROLLED_HANDOFF"
    assert entry.runtime_data.handoff.current == before
    assert not entry.runtime_data.service_executor.production_admitted
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
