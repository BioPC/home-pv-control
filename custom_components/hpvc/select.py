"""Native selectors."""

from homeassistant.components.select import SelectEntity
from .entity import HpvcEntity, SELECTS


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HpvcSelect(entry.runtime_data, setting) for setting in SELECTS)


class HpvcSelect(HpvcEntity, SelectEntity):
    def __init__(self, coordinator, setting):
        super().__init__(coordinator, setting)
        self._attr_options = list(setting.options)

    @property
    def current_option(self):
        return str(self.value)

    async def async_select_option(self, option):
        await self.set_value(option)
