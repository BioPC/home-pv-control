"""Read-only foundation status."""

from homeassistant.components.sensor import SensorEntity
from .const import VERSION, FOUNDATION_WRITE_BLOCK
from .entity import HpvcEntity, Setting

KEYS = ("migration_state", "installed_version", "status", "reason")


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        HpvcSensor(entry.runtime_data, Setting(key, "sensor")) for key in KEYS
    )


class HpvcSensor(HpvcEntity, SensorEntity):
    @property
    def native_value(self):
        return {
            "migration_state": self.coordinator.migration_state,
            "installed_version": VERSION,
            "status": "Foundation - physical writes disabled",
            "reason": FOUNDATION_WRITE_BLOCK,
        }[self.setting.key]

    @property
    def extra_state_attributes(self):
        if self.setting.key != "migration_state":
            return None
        return {
            "import_count": len(self.coordinator.state.imports),
            "handoff_implemented": False,
            "external_references_inspected": False,
            "full_evaluations": self.coordinator.scheduler.full_evaluations,
        }
