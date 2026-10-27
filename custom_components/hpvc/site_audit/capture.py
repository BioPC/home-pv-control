"""Read-only projection of supplied HA observations, shared by live read/export tests."""

import json
import re
from ..inverter.base import RegistryEntity, RegistryDevice
from ..inverter.detection import opendtu_role, looks_opendtu, enphase_role
from ..codec import SchemaError
from .schema import SCHEMA, MAX_ROWS, NATIVE_IDS, EXPECTED, ATTRIBUTES, redact
from ..legacy import MAPPINGS

REGISTRY_FIELDS = (
    "entity_id",
    "id",
    "device_id",
    "platform",
    "config_entry_id",
    "unique_id",
    "original_name",
    "translation_key",
    "original_entity_id",
    "disabled_by",
)
DEVICE_FIELDS = (
    "id",
    "manufacturer",
    "model",
    "model_id",
    "name",
    "name_by_user",
    "configuration_url",
    "identifiers",
    "config_entries",
)
ENTRY_FIELDS = (
    "entry_id",
    "domain",
    "title",
    "state",
    "source",
    "version",
    "disabled_by",
)


def project_observations(
    *,
    states,
    entities,
    devices,
    entries,
    ha_version,
    now,
    coverage=None,
    native_configuration=None,
):
    """Input lists are copied/filtered; arbitrary HA objects and write APIs are absent."""
    if any(len(x) > MAX_ROWS for x in (states, entities, devices, entries)):
        raise SchemaError(
            "Production export exceeds row bound; provide a scoped export"
        )
    mappings = {m.source for m in MAPPINGS}
    intended = set(NATIVE_IDS)
    explicit = set(EXPECTED) | mappings | intended
    for row in states:
        name = row.get("entity_id", "")
        if name.startswith(("input_text.hpvc_", "text.hpvc_")):
            explicit.update(
                re.findall(r"[a-z0-9_]+\.[a-z0-9_]+", str(row.get("state", "")))
            )
    device_models = {
        r.get("id") or r.get("device_id"): RegistryDevice(
            str(r.get("id") or r.get("device_id") or ""),
            str(r.get("manufacturer") or ""),
            str(r.get("model") or ""),
            str(r.get("model_id") or ""),
            str(r.get("name") or ""),
            str(r.get("configuration_url") or ""),
            json.dumps(list(r.get("identifiers") or [])),
        )
        for r in devices
    }
    relevant = set(explicit)
    for r in entities:
        name = r.get("entity_id", "")
        e = RegistryEntity(
            name,
            str(r.get("id") or r.get("registry_id") or ""),
            str(r.get("device_id") or ""),
            str(r.get("platform") or ""),
            str(r.get("config_entry_id") or ""),
            str(r.get("unique_id") or ""),
            str(r.get("original_name") or ""),
            str(r.get("translation_key") or ""),
            str(r.get("original_entity_id") or ""),
            bool(r.get("disabled_by")),
        )
        if (
            ".hpvc_" in name
            or e.platform == "hpvc"
            or enphase_role(e)
            or opendtu_role(e)
            and looks_opendtu(device_models.get(e.device_id), e)
        ):
            relevant.add(name)
    filtered = []
    for row in states:
        name = row.get("entity_id", "")
        if (
            name not in relevant
            and not name.startswith(
                (
                    "sensor.marstek_m",
                    "input_number.marstek_m",
                    "input_select.house_battery_",
                    "input_text.house_battery_",
                    "input_number.house_battery_",
                )
            )
            and ".hpvc_" not in name
        ):
            continue
        filtered.append(
            dict(
                entity_id=name,
                state=row.get("state"),
                last_reported=row.get("last_reported"),
                last_updated=row.get("last_updated"),
                attributes={
                    k: v
                    for k, v in (row.get("attributes") or {}).items()
                    if k in ATTRIBUTES
                },
            )
        )
    erows = []
    for r in entities:
        if r.get("entity_id") not in relevant:
            continue
        v = {k: r.get(k) for k in REGISTRY_FIELDS}
        v["registry_id"] = str(v.pop("id") or r.get("registry_id") or "")
        erows.append(v)
    device_ids = {r["device_id"] for r in erows if r.get("device_id")}
    drows = []
    for r in devices:
        if (r.get("id") or r.get("device_id")) not in device_ids:
            continue
        v = {k: r.get(k) for k in DEVICE_FIELDS}
        v["device_id"] = str(v.pop("id") or r.get("device_id") or "")
        drows.append(v)
    entry_ids = {r["config_entry_id"] for r in erows if r.get("config_entry_id")}
    for d in drows:
        entry_ids.update(d.get("config_entries") or [])
    crows = [
        {k: r.get(k) for k in ENTRY_FIELDS}
        for r in entries
        if r.get("entry_id") in entry_ids
        or r.get("domain") in ("hpvc", "mqtt", "nodered")
    ]
    value = dict(
        schema=SCHEMA,
        source="production_export",
        collected_at_utc=float(now),
        ha={"version": ha_version},
        states=filtered,
        entity_registry=erows,
        device_registry=drows,
        config_entries=crows,
        native_configuration=native_configuration,
        native_runtime={},
        legacy={},
        opendtu=[],
        references=[],
        coverage=dict(coverage or {}),
        collection_errors=[],
        redactions=[],
    )
    paths = []
    result = redact(value, changes=paths)
    result["redactions"] = sorted(set(paths))
    return result


def capture_hass(hass, *, ha_version, now):
    """In-process read adapter for acceptance; never registers itself in HA.

    Production need not install HPVC. The external collector uses read-only HA
    WebSocket list commands and calls project_observations on that local data.
    """
    from homeassistant.helpers import entity_registry as er, device_registry as dr

    def row(obj, fields):
        value = {k: getattr(obj, k, None) for k in fields}
        for k, v in tuple(value.items()):
            if hasattr(v, "value"):
                value[k] = v.value
            elif isinstance(v, (set, frozenset, tuple)):
                value[k] = list(v)
        return value

    states = []
    for s in hass.states.async_all():
        states.append(
            dict(
                entity_id=s.entity_id,
                state=s.state,
                last_reported=getattr(s, "last_reported", s.last_updated).timestamp(),
                last_updated=s.last_updated.timestamp(),
                attributes=dict(s.attributes),
            )
        )
    entities = [row(r, REGISTRY_FIELDS) for r in er.async_get(hass).entities.values()]
    devices = [row(r, DEVICE_FIELDS) for r in dr.async_get(hass).devices.values()]
    entries = [row(r, ENTRY_FIELDS) for r in hass.config_entries.async_entries()]
    return project_observations(
        states=states,
        entities=entities,
        devices=devices,
        entries=entries,
        ha_version=ha_version,
        now=now,
        coverage={
            "states": True,
            "entity_registry": True,
            "device_registry": True,
            "config_entries": True,
            "native_configuration": False,
        },
    )
