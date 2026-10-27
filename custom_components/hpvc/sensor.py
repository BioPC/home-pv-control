"""Read-only compatibility views of the authoritative fleet."""

from homeassistant.components.sensor import SensorEntity
from .const import VERSION, FOUNDATION_WRITE_BLOCK
from .entity import HpvcEntity, Setting
from .control.models import Quality, ControlMethod

KEYS = (
    "migration_state",
    "installed_version",
    "status",
    "reason",
    "effective_inverter_runtime",
    "inverter_limit_validation",
    "inverter_limit_entity_display",
    "enphase_registry",
)
SLOT_KEYS = ("actual_limit",)


def slot_count(runtime):
    return min(
        10,
        max(
            len(runtime.manager.current.configured),
            max((row.slot for row in runtime.manager.current.effective), default=0),
        ),
    )


def controller_ui(runtime):
    rows = []
    for slot in range(1, slot_count(runtime) + 1):
        row = runtime.manager.current.by_slot(slot)
        if row is None:
            rows.append(
                {
                    "status": "Not configured",
                    "valid": False,
                    "source": "manual",
                    "kind": "generic",
                    "control_method": "Number entity",
                    "limit_entity": "",
                    "limit_unit": "Watts",
                    "max_power": 0,
                    "min_power": 0,
                    "max_power_locked": False,
                }
            )
            continue
        view = row.view
        config = view.configuration
        kind = (
            "opendtu"
            if config.identity.adapter.value == "hoymiles"
            else "enphase"
            if config.identity.adapter.value == "enphase"
            else "generic"
        )
        rows.append(
            {
                "status": row.status,
                "valid": view.valid,
                "source": row.origin,
                "kind": kind,
                "control_method": config.method.value,
                "limit_entity": config.identity.entity_id
                or config.limit_number
                or config.readback_entity,
                "limit_unit": config.unit.value,
                "max_power": view.operating_range.full_w,
                "min_power": view.operating_range.minimum_w,
                "max_power_locked": view.operating_range.max_power_locked,
                "controller_uid": row.uid,
                "configuration_signature": view.configuration_signature,
                "participating": row.participating,
                "available": view.available,
                "writable_capable": view.writable_capable,
                "independently_verifiable": view.independently_verifiable,
                "supports_verification": view.supports_verification,
                "current_source": view.current_source.value,
                "assumed_command_w": view.assumed_limit_w,
                "readiness_observed": view.readiness_observed,
                "reasons": list(view.reasons),
            }
        )
    return rows


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            *(HpvcSensor(entry.runtime_data, Setting(key, "sensor")) for key in KEYS),
            *(
                HpvcSensor(
                    entry.runtime_data,
                    Setting(
                        f"pv{slot}_actual_limit",
                        "sensor",
                        slot=slot,
                        field="actual_limit",
                    ),
                )
                for slot in range(1, 11)
            ),
        ]
    )


class HpvcSensor(HpvcEntity, SensorEntity):
    @property
    def native_value(self):
        key = self.setting.key
        if self.setting.slot:
            row = self.coordinator.manager.current.by_slot(self.setting.slot)
            return (
                row.view.observation.limit.value
                if row and row.view.observation.limit.quality == Quality.VALID
                else None
            )
        if key == "effective_inverter_runtime":
            return slot_count(self.coordinator)
        if key == "inverter_limit_validation":
            return (
                "invalid"
                if self.coordinator.manager.current.faults
                or any(
                    not row.view.valid
                    for row in self.coordinator.manager.current.effective
                )
                else "valid"
            )
        if key == "inverter_limit_entity_display":
            return "\u200b"
        if key == "enphase_registry":
            return self.coordinator.registry_refreshed_at_utc
        return {
            "migration_state": self.coordinator.migration_state,
            "installed_version": VERSION,
            "status": "Read-only architecture - physical writes disabled",
            "reason": FOUNDATION_WRITE_BLOCK,
        }[key]

    @property
    def extra_state_attributes(self):
        key = self.setting.key
        runtime = self.coordinator
        fleet = runtime.manager.current
        if self.setting.slot:
            row = fleet.by_slot(self.setting.slot)
            return {
                "controller_uid": row.uid if row else None,
                "independently_verifiable": row.view.independently_verifiable
                if row
                else False,
                "current_source": row.view.current_source.value
                if row
                else "unavailable",
                "physical_writes_authorized": False,
            }
        if key == "migration_state":
            return {
                "import_count": len(runtime.state.imports),
                "handoff_implemented": False,
                "external_references_inspected": False,
                "full_evaluations": runtime.scheduler.full_evaluations,
            }
        if key == "effective_inverter_runtime":
            ui = controller_ui(runtime)
            return {
                "configured_count": len(fleet.configured),
                "effective_count": len(fleet.effective),
                "participating_count": len(fleet.participating),
                "available_count": len(fleet.available),
                "writable_capable_count": len(fleet.writable_capable),
                "independently_verifiable_count": len(fleet.independently_verifiable),
                "runtime_json": [
                    "|".join(
                        (
                            row["limit_entity"],
                            row["limit_unit"],
                            str(row["max_power"]),
                            str(row["min_power"]),
                            row["kind"],
                            row["control_method"],
                            row["source"],
                        )
                    )
                    for row in ui
                ],
                "controller_ui_json": ui,
                "available_capacity_w": fleet.available_capacity_w,
                "overflow_uids": list(fleet.overflow_uids),
                "removed_uids": list(fleet.removed_uids),
                "recovered_uids": list(fleet.recovered_uids),
                "replacement_pairs": [list(pair) for pair in fleet.replacement_pairs],
                "rebalance_uids": list(fleet.rebalance_uids),
                "faults": list(fleet.faults),
                "physical_writes_authorized": False,
                "verification_results": [
                    {
                        "operation_id": key,
                        "outcome": value.outcome.value,
                        "reason": value.reason,
                    }
                    for key, value in runtime.verification_results
                ],
            }
        if key == "inverter_limit_validation":
            return {
                "validation_json": [
                    {
                        "slot": index + 1,
                        "status": "valid"
                        if row["valid"]
                        else "min_above_max"
                        if "min_above_max" in row.get("reasons", [])
                        else "incomplete",
                        "reasons": row.get("reasons", []),
                    }
                    for index, row in enumerate(controller_ui(runtime))
                ]
            }
        if key == "inverter_limit_entity_display":
            return {
                f"pv{slot}_limit_entity": (
                    row.view.configuration.identity.entity_id
                    or row.view.configuration.limit_number
                )
                if (row := fleet.by_slot(slot))
                and row.view.configuration.method == ControlMethod.NUMBER
                else ""
                for slot in range(1, 11)
            }
        if key == "enphase_registry":

            def record(candidate):
                return {
                    "device_id": candidate.device_id,
                    "limit_entity": candidate.limit_entity,
                    "mode_entity": candidate.mode_entity,
                    "enable_entity": candidate.enable_entity,
                    "serial": candidate.serial,
                    "configuration_url": candidate.configuration_url,
                }

            return {
                "controllers": [
                    record(candidate)
                    for candidate in runtime.manager.candidates
                    if candidate.kind == "enphase"
                ],
                "opendtu_controllers": [
                    record(candidate)
                    for candidate in runtime.manager.candidates
                    if candidate.kind == "hoymiles"
                ],
                "registry_entities": [
                    item.entity_id for item in runtime.manager.registry
                ],
            }
        return None
