"""Native settings; changing a number never writes an inverter."""

from homeassistant.components.number import NumberEntity, NumberMode
from .entity import HpvcEntity, NUMBERS


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(HpvcNumber(entry.runtime_data, setting) for setting in NUMBERS)


class HpvcNumber(HpvcEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, setting):
        super().__init__(coordinator, setting)
        self._attr_native_min_value = setting.low
        self._attr_native_max_value = setting.high
        self._attr_native_step = setting.step

    @property
    def native_value(self):
        return self.value

    async def async_set_native_value(self, value):
        await self.set_value(value)
