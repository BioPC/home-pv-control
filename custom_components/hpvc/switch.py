"""Native user intent and controller permission. No physical switching."""

from homeassistant.components.switch import SwitchEntity
from .entity import HpvcEntity, SWITCHES


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HpvcSwitch(entry.runtime_data, setting) for setting in SWITCHES)


class HpvcSwitch(HpvcEntity, SwitchEntity):
    @property
    def is_on(self):
        return bool(self.value)

    async def async_turn_on(self, **kwargs):
        await self.set_value(True)

    async def async_turn_off(self, **kwargs):
        await self.set_value(False)
