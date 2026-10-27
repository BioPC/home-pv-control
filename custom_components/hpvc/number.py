"""Native settings; changing a number never writes an inverter."""

from homeassistant.components.number import NumberEntity, NumberMode
from .entity import HpvcEntity, NUMBERS, Setting


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            *(HpvcNumber(entry.runtime_data, setting) for setting in NUMBERS),
            HpvcInverters(entry.runtime_data, Setting("inverters", "number", 0, 10, 1)),
        ]
    )


class HpvcNumber(HpvcEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, setting):
        super().__init__(coordinator, setting)
        self._attr_native_min_value = setting.low
        self._attr_native_max_value = setting.high
        self._attr_native_step = setting.step

    @property
    def native_value(self):
        row = (
            self.coordinator.manager.current.by_slot(self.setting.slot)
            if self.setting.slot
            else None
        )
        if (
            self.setting.field == "full_limit_w"
            and row
            and row.view.operating_range.max_power_locked
        ):
            return row.view.operating_range.full_w
        return self.value

    async def async_set_native_value(self, value):
        await self.set_value(value)


class HpvcInverters(HpvcNumber):
    """Legacy count facade: max(auto slot count, configured count), bounded to ten."""

    @property
    def value(self):
        # HA 2025.12 still probes the legacy NumberEntity.value property.
        return self.native_value

    @property
    def native_min_value(self):
        return sum(
            row.origin == "auto" for row in self.coordinator.manager.current.effective
        )

    @property
    def native_value(self):
        return min(
            10,
            max(self.native_min_value, self.coordinator.configuration.inverter_count),
        )

    async def async_set_native_value(self, value):
        from dataclasses import replace
        from .codec import SchemaError

        if (
            type(value) not in (int, float)
            or value != int(value)
            or not 0 <= value <= 10
        ):
            raise SchemaError("Controller count must be an integer from zero to ten")
        candidate = replace(
            self.coordinator.configuration,
            inverter_count=max(self.native_min_value, int(value)),
        )
        await self.coordinator.async_set_configuration(candidate)
