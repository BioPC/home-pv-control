"""Shared native entity descriptors; setters only persist native configuration."""

from dataclasses import dataclass, replace
import hashlib
import re
from homeassistant.helpers.entity import Entity
from .codec import SchemaError
from .const import DOMAIN, VERSION
from .control.models import (
    ControllerConfiguration,
    ControllerIdentity,
    ControlMethod,
    LimitUnit,
)
from .storage import canonical, strict_json


@dataclass(frozen=True)
class Setting:
    key: str
    domain: str
    low: float | None = None
    high: float | None = None
    step: float | None = None
    options: tuple[str, ...] = ()
    slot: int | None = None
    field: str | None = None


SWITCHES = tuple(
    Setting(key, "switch")
    for key in (
        "enabled",
        "external_release_request",
        "insights_enabled",
        "notifications",
        "control_hbc_strategy",
        "negative_price_hbc_charge",
    )
) + tuple(
    Setting(f"pv{i}_control", "switch", slot=i, field="control_enabled")
    for i in range(1, 11)
)
NUMBERS = (
    (Setting("inverter_count", "number", 0, 10, 1),)
    + tuple(
        Setting(key, "number", low, high, step)
        for key, low, high, step in (
            ("pv_limiting_price", -0.5, 0.2, 0.01),
            ("battery_price_hysteresis", 0, 0.1, 0.01),
            ("export_start_threshold", -5000, 0, 10),
            ("export_stop_threshold", -5000, 500, 5),
            ("import_restore_threshold", 0, 5000, 10),
            ("pv_min_power_for_control", 0, 5000, 10),
            ("pv_night_restore_power", 0, 1000, 5),
            ("cooldown_seconds", 10, 60, 5),
            ("pv_adjust_deadband", 1, 500, 1),
        )
    )
    + tuple(
        Setting(f"pv{i}_{suffix}", "number", 0, high, step, slot=i, field=field)
        for i in range(1, 11)
        for suffix, field, high, step in (
            ("full_limit", "full_limit_w", 10000, 1),
            ("low_limit", "low_limit_w", 10000, 1),
            ("action_step", "action_step", 10000, 0.001),
            ("refresh_seconds", "refresh_seconds", 3600, 1),
        )
    )
)
SELECTS = (
    Setting(
        "selected_inverter", "select", options=tuple(f"PV{i}" for i in range(1, 11))
    ),
) + tuple(
    Setting(f"pv{i}_{suffix}", "select", options=options, slot=i, field=field)
    for i in range(1, 11)
    for suffix, field, options in (
        ("control_method", "method", ("Number entity", "Action/service")),
        ("limit_unit", "unit", ("Watts", "Percent")),
    )
)
TEXTS = tuple(
    Setting(key, "text")
    for key in (
        "market_price_sensor",
        "all_in_price_sensor",
        "grid_power_sensor",
        "pv_power_sensor",
    )
) + tuple(
    Setting(f"pv{i}_{key}", "text", slot=i, field=key)
    for i in range(1, 11)
    for key in (
        "limit_number",
        "action",
        "value_field",
        "fixed_data_json",
        "target_json",
        "pre_actions_json",
        "post_actions_json",
        "readback_entity",
    )
)


class HpvcEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, setting):
        self.coordinator = coordinator
        self.setting = setting
        self._attr_unique_id = f"{coordinator.configuration.plant_uid}:{setting.key}"
        self.entity_id = f"{setting.domain}.hpvc_{setting.key}"
        self._attr_name = setting.key.replace("_", " ").capitalize()
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.configuration.plant_uid)},
            "name": "Home PV Control",
            "manufacturer": "HPVC",
            "model": "Native foundation",
            "sw_version": VERSION,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.add_listener(self.async_write_ha_state))

    @property
    def available(self):
        return not self.coordinator.owner.closed and not self.coordinator.storage_fault

    def _controller(self):
        return next(
            (
                item
                for item in self.coordinator.configuration.controllers
                if item.identity.slot == self.setting.slot
            ),
            None,
        ) or ControllerConfiguration(
            ControllerIdentity(
                f"{self.coordinator.configuration.plant_uid}:slot:{self.setting.slot}",
                self.setting.slot,
            ),
            signature="unconfigured",
        )

    @property
    def value(self):
        config = self.coordinator.configuration
        key = self.setting.key
        if self.setting.slot:
            return getattr(self._controller(), self.setting.field)
        if key == "enabled":
            return config.enabled_intent
        if hasattr(config.settings, key):
            return getattr(config.settings, key)
        return getattr(config, key)

    async def set_value(self, value):
        config = self.coordinator.configuration
        key = self.setting.key
        if self.setting.domain == "switch" and type(value) is not bool:
            raise SchemaError("Expected boolean")
        if self.setting.domain == "number":
            if (
                type(value) not in (int, float)
                or not self.setting.low <= value <= self.setting.high
            ):
                raise SchemaError("Number outside range")
            if key == "inverter_count":
                if value != int(value):
                    raise SchemaError("Count must be integer")
                value = int(value)
        if self.setting.options and value not in self.setting.options:
            raise SchemaError("Invalid selector option")
        if self.setting.domain == "text":
            if not isinstance(value, str) or len(value) > 255:
                raise SchemaError("Invalid text")
            if (
                key.endswith("_sensor")
                and value
                and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value)
            ):
                raise SchemaError("Invalid entity reference")
            if self.setting.field in (
                "fixed_data_json",
                "target_json",
                "pre_actions_json",
                "post_actions_json",
            ):
                parsed = strict_json(value)
                expected = (
                    list
                    if self.setting.field in ("pre_actions_json", "post_actions_json")
                    else dict
                )
                if not isinstance(parsed, expected):
                    raise SchemaError("Invalid JSON shape")
                if expected is list:
                    for item in parsed:
                        if not isinstance(item, dict) or not re.fullmatch(
                            r"[a-z0-9_]+\.[a-z0-9_]+", str(item.get("action", ""))
                        ):
                            raise SchemaError("Invalid pre/post action")
                        if not isinstance(item.get("data", {}), dict) or not isinstance(
                            item.get("target", {}), dict
                        ):
                            raise SchemaError("Invalid sequence payload")
            if (
                self.setting.field == "limit_number"
                and value
                and not re.fullmatch(r"number\.[a-z0-9_]+", value)
            ):
                raise SchemaError("Expected number entity")
            if (
                self.setting.field == "readback_entity"
                and value
                and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value)
            ):
                raise SchemaError("Invalid readback entity")
            if (
                self.setting.field == "action"
                and value
                and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value)
            ):
                raise SchemaError("Invalid action")
        if self.setting.slot:
            if self.coordinator.ledger.recovery_required:
                raise SchemaError(
                    "Resolve retained obligations before changing controller configuration"
                )
            controller = self._controller()
            if self.setting.field == "method":
                value = ControlMethod(value)
            if self.setting.field == "unit":
                value = LimitUnit(value)
            controller = replace(
                controller, **{self.setting.field: value}, signature=""
            )
            signature = hashlib.sha256(
                canonical(controller.to_dict()).encode()
            ).hexdigest()
            controller = replace(controller, signature=signature)
            controllers = tuple(
                item
                for item in config.controllers
                if item.identity.slot != self.setting.slot
            ) + (controller,)
            config = replace(
                config,
                controllers=tuple(
                    sorted(controllers, key=lambda item: item.identity.slot)
                ),
            )
        elif hasattr(config.settings, key):
            config = replace(config, settings=replace(config.settings, **{key: value}))
        else:
            config = replace(
                config, **{"enabled_intent" if key == "enabled" else key: value}
            )
        await self.coordinator.async_set_configuration(config)
