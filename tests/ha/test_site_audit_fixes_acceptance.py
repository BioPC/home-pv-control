"""Real HA regression for audit fixes; all production mutations are trapped."""

import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.hpvc.site_audit.capture import capture_hass
from custom_components.hpvc.site_audit.engine import audit_site
from custom_components.hpvc.site_audit.schema import EXPECTED
from custom_components.hpvc.legacy import build_preview

pytestmark = pytest.mark.asyncio
FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/site-audit-production-redacted.json"
)


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


async def test_actual_ha_optional_blank_helper_states_and_no_service_write(hass):
    b = fixture()
    for r in b["states"]:
        hass.states.async_set(r["entity_id"], r["state"], r["attributes"])
    before = {s.entity_id: s.as_dict() for s in hass.states.async_all()}
    values = {s.entity_id: s.state for s in hass.states.async_all()}
    with patch.object(
        type(hass.services),
        "async_call",
        side_effect=AssertionError("No services allowed"),
    ):
        p = build_preview(values, "audit-only")
    assert not p.issues
    assert not p.candidate.enabled_intent
    assert {s.entity_id: s.as_dict() for s in hass.states.async_all()} == before


async def test_actual_ha_capture_keeps_fixture_marker_and_excludes_fake_controller(
    hass,
):
    b = fixture()
    for r in b["states"]:
        hass.states.async_set(r["entity_id"], r["state"], r["attributes"])
    # A renamed HPVC fixture is also excluded by its literal marker.
    for prefix, value, attrs in (
        ("number", "1000", {"unit_of_measurement": "W", "hpvc_test_fixture": True}),
        ("select", "Export", {"options": ["Production", "Export"]}),
        ("switch", "on", {}),
    ):
        tail = {"number": "limit", "select": "mode", "switch": "enabled"}[prefix]
        row = er.async_get(hass).async_get_or_create(
            prefix,
            "template",
            "renamed_envoy_dpel_" + tail,
            suggested_object_id="renamed_envoy_dpel_" + tail,
        )
        hass.states.async_set(row.entity_id, value, attrs)
    with patch.object(
        type(hass.services),
        "async_call",
        side_effect=AssertionError("No services allowed"),
    ):
        captured = capture_hass(hass, ha_version="test", now=b["collected_at_utc"])
        marked = next(
            s
            for s in captured["states"]
            if s["entity_id"] == "number.renamed_envoy_dpel_limit"
        )
        assert marked["attributes"]["hpvc_test_fixture"] is True
        result = audit_site(captured, now=b["collected_at_utc"])
    assert {c["writable_entity"] for c in result["controllers"]} == set(EXPECTED)
    assert not result["production_transport_authorized"]


async def test_actual_ha_registry_renamed_legacy_identity_classified_without_mutation(
    hass,
):
    b = fixture()
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        "binary_sensor",
        "template",
        "hpvc_required_inputs_ready",
        suggested_object_id="renamed_readiness",
    )
    b["entity_registry"] = [
        dict(
            entity_id=row.entity_id,
            unique_id=row.unique_id,
            platform=row.platform,
            config_entry_id=row.config_entry_id,
        )
    ]
    before = copy.deepcopy(dict(registry.entities))
    with (
        patch.object(
            type(registry),
            "async_update_entity",
            side_effect=AssertionError("No registry writes"),
        ),
        patch.object(
            type(hass.services), "async_call", side_effect=AssertionError("No services")
        ),
    ):
        result = audit_site(b, now=b["collected_at_utc"])
    proof = next(
        r for r in result["registry_ownership"] if r["entity_id"] == row.entity_id
    )
    assert proof["classification"] == "proven_legacy_hpvc_owned"
    assert dict(registry.entities) == before
    assert not result["production_transport_authorized"]
    assert not result["handoff_projection"]["production_state_advanced"]
