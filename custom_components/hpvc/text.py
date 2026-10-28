"""Configuration text entities; action payloads are stored, never executed."""

from homeassistant.components.text import TextEntity, TextMode
from .entity import HpvcEntity, TEXTS


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HpvcText(entry.runtime_data, setting) for setting in TEXTS)


class HpvcText(HpvcEntity, TextEntity):
    _attr_native_min = 0
    _attr_native_max = 255
    _attr_mode = TextMode.TEXT

    @property
    def native_value(self):
        return self.value

    async def async_set_value(self, value):
        await self.set_value(value)
