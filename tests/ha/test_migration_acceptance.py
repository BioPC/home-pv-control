"""Real HA lifecycle/registry and controlled legacy handoff; no service calls."""

import sys
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from test_policy_acceptance import start

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "foundation"))
from migration_fixture import LegacyFixture
from custom_components.hpvc.migration.model import Stage
from custom_components.hpvc.migration.registry import (
    RegistryIdentity,
    RegistryMigrator,
    plan_registry_migration,
)
from custom_components.hpvc.migration.dashboard import native_dashboard
from custom_components.hpvc.codec import SchemaError

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def no_ha_service_invocations(hass):
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError(
            "No dev.7 actuator or production migration services"
        ),
    ) as calls:
        yield calls
        calls.assert_not_called()


async def fixture_runtime(hass, tmp_path):
    entry = await start(hass)
    f = await LegacyFixture(
        tmp_path, entry.runtime_data.configuration.plant_uid
    ).initialize()
    return entry, f


async def test_real_ha_ownership_ready_does_not_open_executor_or_sensor(hass, tmp_path):
    entry, f = await fixture_runtime(hass, tmp_path)
    await f.until(Stage.READY)
    runtime = entry.runtime_data
    runtime.handoff = f.engine
    runtime.publish()
    await hass.async_block_till_done()
    assert runtime.handoff.current.native_owner_ready
    assert not runtime.physical_writes_authorized
    assert not runtime.service_executor.production_admitted
    assert runtime.service_executor._test_admission is None
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert hass.states.get("sensor.hpvc_migration_state").state == "native_owner_ready"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "stage",
    [
        Stage.UNASSESSED,
        Stage.DETECTED,
        Stage.IMPORT,
        Stage.QUIESCING,
        Stage.RECONCILING,
        Stage.RESTORED,
        Stage.FENCING,
        Stage.POST,
        Stage.READY,
    ],
)
async def test_real_ha_durable_restart_at_handoff_boundaries(hass, tmp_path, stage):
    entry, f = await fixture_runtime(hass, tmp_path)
    await f.until(stage)
    await f.restart()
    await f.until(Stage.READY)
    assert not f.engine.current.production_transport_authorized
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "change",
    [
        "unreachable",
        "changed_flow",
        "queued",
        "possible_issue",
        "pending_verification",
        "inverter_restore",
        "hbc_restore",
        "hbc_unavailable",
        "stale_full",
        "controller_missing",
        "identity_replacement",
        "legacy_reappearance",
        "backup_return",
    ],
)
async def test_real_ha_ambiguous_migration_remains_blocked(hass, tmp_path, change):
    entry, f = await fixture_runtime(hass, tmp_path)
    await f.until(
        Stage.READY
        if change in ("legacy_reappearance", "backup_return")
        else Stage.RECONCILING
    )
    if change == "unreachable":
        f.reachable = False
    elif change == "changed_flow":
        f.fingerprint = "changed"
    elif change == "queued":
        f.queued = ("queued",)
    elif change == "possible_issue":
        f.possible = ("issued-maybe",)
    elif change == "pending_verification":
        f.pending = ("pending",)
    elif change == "inverter_restore":
        f.obligations = ("restore",)
    elif change == "hbc_restore":
        f.hbc_owned = True
    elif change == "hbc_unavailable":
        f.hbc_available = False
    elif change == "stale_full":
        f.proof_stale = True
    elif change == "controller_missing":
        f.current_bindings = ()
    elif change == "identity_replacement":
        f.current_bindings = (replace(f.binding, uid="replacement"),)
    elif change == "legacy_reappearance":
        f.fenced = False
    else:
        f.fence_token = "old-backup-token"
    value = await f.step()
    assert value.stage == Stage.BLOCKED
    assert not value.native_owner_ready and not value.production_transport_authorized
    assert not entry.runtime_data.service_executor.production_admitted
    assert await hass.config_entries.async_unload(entry.entry_id)


def identity(row):
    return RegistryIdentity(
        row.entity_id, row.unique_id, row.platform, row.config_entry_id
    )


async def test_actual_entity_registry_reclaims_proven_owned_collision_and_rollback(
    hass, tmp_path
):
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", "template", "hpvc-v1.6-status", suggested_object_id="hpvc_status"
    )
    entry, f = await fixture_runtime(hass, tmp_path)
    await f.until(Stage.READY)
    native_id = registry.async_get_entity_id(
        "sensor", "hpvc", entry.runtime_data.configuration.plant_uid + ":status"
    )
    assert native_id == "sensor.hpvc_status_2"
    native = registry.async_get(native_id)
    old = registry.async_get(old.entity_id)
    plan = plan_registry_migration(
        tuple(identity(r) for r in registry.entities.values()),
        identity(old),
        identity(native),
        "sensor.hpvc_status",
        ownership_manifest=(identity(old),),
    )
    m = RegistryMigrator(
        tmp_path / "registry-moves.json",
        f.engine.current.transaction_id,
        registry=registry,
        permit=f.permit,
    )
    await m.load()
    await m.apply(plan, f.engine.current)
    await hass.async_block_till_done()
    assert registry.async_get("sensor.hpvc_status").unique_id == native.unique_id
    assert hass.states.get("sensor.hpvc_status") is not None
    await m.apply(plan, f.engine.current)
    await m.rollback()
    await hass.async_block_till_done()
    assert registry.async_get("sensor.hpvc_status").unique_id == old.unique_id
    assert registry.async_get("sensor.hpvc_status_2").unique_id == native.unique_id
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_actual_registry_unrelated_collision_remains_untouched(hass, tmp_path):
    registry = er.async_get(hass)
    unrelated = registry.async_get_or_create(
        "sensor", "template", "unrelated", suggested_object_id="hpvc_status"
    )
    entry, f = await fixture_runtime(hass, tmp_path)
    await f.until(Stage.READY)
    native = registry.async_get(
        registry.async_get_entity_id("sensor", "hpvc", "hpvc-primary:status")
    )
    with pytest.raises(SchemaError):
        plan_registry_migration(
            tuple(identity(r) for r in registry.entities.values()),
            identity(unrelated),
            identity(native),
            "sensor.hpvc_status",
            ownership_manifest=(),
        )
    assert registry.async_get(unrelated.entity_id).unique_id == "unrelated"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_dashboard_templates_render_full_limit_entity_and_auto_manual_status(
    hass, tmp_path
):
    entry, f = await fixture_runtime(hass, tmp_path)
    runtime = entry.runtime_data
    long = "number." + "very_long_external_limit_identity_" * 4
    hass.states.async_set(
        "sensor.hpvc_effective_inverter_runtime",
        "1",
        {
            "controller_ui_json": [
                {
                    "status": "Available",
                    "source": "auto",
                    "control_method": "Number entity",
                    "limit_entity": long,
                }
            ]
        },
    )
    d = native_dashboard(configuration=runtime.configuration)
    pv = d["views"][1]
    limit = pv["cards"][1]["content"]
    rendered = Template(limit, hass).async_render()
    assert "**Limit entity**" in rendered and long in rendered and "```text" in rendered
    status = Template(pv["cards"][0]["content"], hass).async_render()
    assert "Available" in status and "auto" in status
    paths = {v["path"] for v in d["views"]}
    assert {"insights", "reports", "power-control", "price-interval"} <= paths
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_normal_real_ha_setup_has_no_migration_mutation_driver(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    assert runtime.handoff.driver is None
    assert not runtime.handoff.current.native_owner_ready
    assert not runtime.handoff.current.production_transport_authorized
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.handoff.driver is None
    assert (
        hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state == "off"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
