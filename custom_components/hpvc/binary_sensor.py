"""Read-only participation, capability and authorization diagnostics."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import FOUNDATION_WRITE_BLOCK
from .entity import HpvcEntity, Setting
from .sensor import slot_count

KEYS = ("physical_writes_authorized", "recovery_required", "required_inputs_ready")
SLOT_KEYS = (
    "auto_detected",
    "limit_range_invalid",
    "max_power_locked",
    "participating",
    "available",
    "writable_capable",
    "independently_verifiable",
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            *(
                HpvcBinarySensor(entry.runtime_data, Setting(key, "binary_sensor"))
                for key in KEYS
            ),
            *(
                HpvcBinarySensor(
                    entry.runtime_data,
                    Setting(f"pv{slot}_{key}", "binary_sensor", slot=slot, field=key),
                )
                for slot in range(1, 11)
                for key in SLOT_KEYS
            ),
            *(
                HpvcBinarySensor(
                    entry.runtime_data,
                    Setting(
                        f"show_inverter_slot_{slot}",
                        "binary_sensor",
                        slot=slot,
                        field="show_slot",
                    ),
                )
                for slot in range(2, 11)
            ),
        ]
    )


class HpvcBinarySensor(HpvcEntity, BinarySensorEntity):
    @property
    def is_on(self):
        if self.setting.slot:
            row = self.coordinator.manager.current.by_slot(self.setting.slot)
            key = self.setting.field
            if key == "show_slot":
                return slot_count(self.coordinator) >= self.setting.slot
            if row is None:
                return False
            if key == "auto_detected":
                return row.origin == "auto"
            if key == "limit_range_invalid":
                return "min_above_max" in row.view.reasons
            if key == "max_power_locked":
                return row.view.operating_range.max_power_locked
            if key == "participating":
                return row.participating
            return bool(getattr(row.view, key))
        if self.setting.key in ("physical_writes_authorized", "required_inputs_ready"):
            return False
        return self.coordinator.recovery_required

    @property
    def extra_state_attributes(self):
        if self.setting.key == "physical_writes_authorized":
            return {"blocking_reason": FOUNDATION_WRITE_BLOCK}
        if self.setting.slot:
            row = self.coordinator.manager.current.by_slot(self.setting.slot)
            attrs = {
                "controller_uid": row.uid if row else None,
                "physical_writes_authorized": False,
            }
            if row:
                view = row.view
                config = view.configuration
                attrs.update(
                    {
                        "limit_entity": config.identity.entity_id
                        or config.limit_number,
                        "control_method": config.method.value,
                        "limit_unit": config.unit.value,
                        "max_power": str(view.operating_range.full_w) + " W",
                        "max_power_locked": view.operating_range.max_power_locked,
                        "readiness_observed": view.readiness_observed,
                        "reasons": list(view.reasons),
                    }
                )
            return attrs
        if self.setting.key == "recovery_required":
            assessment = self.coordinator.recovery_assessment
            return {
                "unresolved_obligation_ids": list(assessment.unresolved_obligation_ids),
                "reasons": list(assessment.reasons),
            }
        return None
