"""Authorization is hard closed, independent of enable intent or imported data."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import FOUNDATION_WRITE_BLOCK
from .entity import HpvcEntity, Setting

KEYS = ("physical_writes_authorized", "recovery_required", "required_inputs_ready")


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        HpvcBinarySensor(entry.runtime_data, Setting(key, "binary_sensor"))
        for key in KEYS
    )


class HpvcBinarySensor(HpvcEntity, BinarySensorEntity):
    @property
    def is_on(self):
        if self.setting.key == "physical_writes_authorized":
            return False
        if self.setting.key == "required_inputs_ready":
            return False
        return self.coordinator.recovery_required

    @property
    def extra_state_attributes(self):
        if self.setting.key == "physical_writes_authorized":
            return {"blocking_reason": FOUNDATION_WRITE_BLOCK}
        return None
