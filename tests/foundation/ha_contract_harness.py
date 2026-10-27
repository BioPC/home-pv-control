"""Small explicit contract doubles, not a Home Assistant runtime substitute.

Only installed in the dependency-free unittest process. Real HA tests run separately.
"""

import asyncio
from datetime import datetime, timezone
import importlib
import sys
import types
from unittest.mock import AsyncMock
from pathlib import Path


def install():
    def module(name):
        item = types.ModuleType(name)
        item.__path__ = []
        sys.modules[name] = item
        return item

    ha = module("homeassistant")
    components = module("homeassistant.components")
    helpers = module("homeassistant.helpers")
    core = module("homeassistant.core")
    core.callback = lambda function: function
    for name, attribute in (
        ("entity_registry", "entities"),
        ("device_registry", "devices"),
    ):
        registry = module("homeassistant.helpers." + name)
        registry.async_get = lambda hass, attribute=attribute: types.SimpleNamespace(
            **{attribute: {}}
        )
    entity = module("homeassistant.helpers.entity")

    class Entity:
        def __init__(self):
            self._removes = []

        async def async_added_to_hass(self):
            pass

        def async_on_remove(self, callback):
            if not hasattr(self, "_removes"):
                self._removes = []
            self._removes.append(callback)

        def async_write_ha_state(self):
            pass

    entity.Entity = Entity
    for domain, name in (
        ("switch", "SwitchEntity"),
        ("number", "NumberEntity"),
        ("select", "SelectEntity"),
        ("text", "TextEntity"),
        ("sensor", "SensorEntity"),
        ("binary_sensor", "BinarySensorEntity"),
    ):
        item = module("homeassistant.components." + domain)
        setattr(item, name, type(name, (Entity,), {}))
        if domain == "number":
            item.NumberMode = types.SimpleNamespace(BOX="box")
        if domain == "text":
            item.TextMode = types.SimpleNamespace(TEXT="text")
    entries = module("homeassistant.config_entries")
    ha.config_entries = entries

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

        async def async_set_unique_id(self, value):
            self.unique_id = value

        def _abort_if_unique_id_configured(self):
            if getattr(self, "already_configured", False):
                raise ValueError("already_configured")

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    entries.ConfigFlow = Flow
    exceptions = module("homeassistant.exceptions")
    exceptions.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
    exceptions.ConfigEntryError = type("ConfigEntryError", (Exception,), {})
    issue = module("homeassistant.helpers.issue_registry")
    issue.IssueSeverity = types.SimpleNamespace(WARNING="warning", ERROR="error")
    issue.async_create_issue = lambda hass, domain, key, **kw: hass.issues.update(
        {key: kw}
    )
    issue.async_delete_issue = lambda hass, domain, key: hass.issues.pop(key, None)
    event = module("homeassistant.helpers.event")

    def subscribe(hass, entities, callback):
        key = object()
        hass.subscriptions[key] = (entities, callback)
        return lambda: hass.subscriptions.pop(key, None)

    event.async_track_state_change_event = subscribe
    vol = module("voluptuous")

    class Marker:
        def __init__(self, key, **kwargs):
            self.key = key

    vol.Optional = vol.Required = Marker
    vol.Schema = lambda value: value
    vol.All = lambda *args: args
    vol.Coerce = lambda value: value
    vol.Range = lambda **kwargs: kwargs


class States:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = types.SimpleNamespace(
            entity_id=key, state=str(value), last_reported=datetime.now(timezone.utc)
        )

    def get(self, key):
        return self.values.get(key)

    def async_all(self):
        return list(self.values.values())


class Entry:
    def __init__(self, data, entry_id="entry"):
        self.data = data
        self.entry_id = entry_id
        self.runtime_data = None
        self.created_tasks = []

    def async_create_background_task(self, hass, coro, name):
        task = asyncio.create_task(coro, name=name)
        self.created_tasks.append(task)
        return task


class Hass:
    def __init__(self, path):
        self.data = {}
        self.states = States()
        self.issues = {}
        self.subscriptions = {}
        self.entities = {}
        self.config = types.SimpleNamespace(
            path=lambda *parts: str(Path(path).joinpath(*parts))
        )
        self.services = types.SimpleNamespace(
            async_call=AsyncMock(side_effect=AssertionError("Actuator call forbidden"))
        )
        self.config_entries = types.SimpleNamespace(
            async_forward_entry_setups=self.forward, async_unload_platforms=self.unload
        )
        self.fail_forward = False

    async def forward(self, entry, platforms):
        for platform in platforms:
            module = importlib.import_module("custom_components.hpvc." + platform)
            created = []
            await module.async_setup_entry(
                self, entry, lambda entities: created.extend(entities)
            )
            for entity in created:
                self.entities[entity.entity_id] = entity
                entity.hass = self
                await entity.async_added_to_hass()
        if self.fail_forward:
            raise RuntimeError("platform setup failed")

    async def unload(self, entry, platforms):
        for entity in self.entities.values():
            for callback in getattr(entity, "_removes", []):
                callback()
        self.entities.clear()
        return True
