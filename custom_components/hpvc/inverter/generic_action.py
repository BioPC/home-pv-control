"""Generic Action/service DATA plans. This module has no execution interface."""

import re
from decimal import Decimal
from ..codec import SchemaError
from ..control.models import ControllerObservation, LimitUnit, Quality
from ..storage import strict_json
from .base import (
    AdapterView,
    NumberCapabilities,
    OperatingRange,
    ReadbackSource,
    ACTION_PATTERN,
    ENTITY_PATTERN,
    numeric_observation,
    finite,
    make_batch,
    adapter_signature,
)
from .generic_number import represent_target, validate_range

TOKEN = re.compile(r"\{\{([a-z_]+)\}\}")


def js_string(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if value == 0:
            return "0"
        if 1e-6 <= abs(value) < 1e21:
            return (
                format(Decimal(str(value)), "f").rstrip("0").rstrip(".")
                if isinstance(value, float) and not value.is_integer()
                else str(int(value))
            )
        raw = str(float(value)).lower()
        if "e" in raw:
            mantissa, exponent = raw.split("e")
            mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
            power = int(exponent)
            return mantissa + "e" + ("+" if power >= 0 else "-") + str(abs(power))
    return str(value)


def substitute(value, tokens):
    if isinstance(value, list):
        return [substitute(item, tokens) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, tokens) for key, item in value.items()}
    if isinstance(value, str):
        full = TOKEN.fullmatch(value)
        if full and full[1] in tokens:
            return tokens[full[1]]
        return TOKEN.sub(
            lambda match: (
                js_string(tokens[match[1]]) if match[1] in tokens else match[0]
            ),
            value,
        )
    return value


def set_path(data, path, value):
    parts = [part.strip() for part in path.split(".") if part.strip()]
    if not parts:
        raise SchemaError("Nested value field required")
    cursor = data
    for part in parts[:-1]:
        if not isinstance(cursor.get(part), dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[parts[-1]] = value


def parse_configuration(config):
    if not ACTION_PATTERN.fullmatch(config.action.strip().lower()):
        raise SchemaError("Invalid Action/service")
    if not config.value_field.strip():
        raise SchemaError("Value field required")
    fixed = strict_json(config.fixed_data_json)
    target = strict_json(config.target_json)
    pre = strict_json(config.pre_actions_json)
    post = strict_json(config.post_actions_json)
    if (
        not isinstance(fixed, dict)
        or not isinstance(target, dict)
        or not isinstance(pre, list)
        or not isinstance(post, list)
    ):
        raise SchemaError("Invalid action JSON shape")
    for item in pre + post:
        if not isinstance(item, dict) or not ACTION_PATTERN.fullmatch(
            str(item.get("action", "")).strip().lower()
        ):
            raise SchemaError("Invalid pre/post action")
        if not isinstance(item.get("data", {}), dict) or not isinstance(
            item.get("target", {}), dict
        ):
            raise SchemaError("Invalid pre/post payload")
    max_step = 100 if config.unit == LimitUnit.PERCENT else config.full_limit_w
    if (
        not 0 <= config.action_step <= max_step
        or not 0 <= config.refresh_seconds <= 3600
    ):
        raise SchemaError("Action step/refresh outside range")
    if config.readback_entity and not ENTITY_PATTERN.fullmatch(config.readback_entity):
        raise SchemaError("Invalid readback entity")
    return fixed, target, pre, post


class GenericActionAdapter:
    def normalize(self, config, entity, now, *, command_cache_w=None):
        operating = OperatingRange(config.full_limit_w, config.low_limit_w)
        caps = NumberCapabilities(
            step=config.action_step if config.action_step > 0 else 1
        )
        reasons = list(validate_range(config, caps, operating))
        try:
            parse_configuration(config)
        except SchemaError as err:
            reasons.append(str(err))
        supports = bool(
            config.readback_entity and ENTITY_PATTERN.fullmatch(config.readback_entity)
        )
        observation = numeric_observation(
            entity,
            now,
            full_w=config.full_limit_w,
            percent=config.unit == LimitUnit.PERCENT,
        )
        live = supports and observation.quality == Quality.VALID
        assumed = None
        source = ReadbackSource.LIVE if live else ReadbackSource.UNAVAILABLE
        if not supports:
            cached = finite(command_cache_w)
            assumed = (
                cached
                if cached is not None
                else config.full_limit_w
                if config.full_limit_w > 0
                else None
            )
            source = (
                ReadbackSource.COMMAND_CACHE
                if cached is not None
                else ReadbackSource.STARTUP_ASSUMPTION
                if assumed is not None
                else ReadbackSource.UNAVAILABLE
            )
        available = live or (not supports and assumed is not None)
        return AdapterView(
            config,
            caps,
            operating,
            ControllerObservation(config.identity, observation, available, supports),
            adapter_signature(config, caps, operating),
            not reasons,
            available,
            not reasons,
            live,
            supports,
            source,
            assumed,
            tuple(reasons),
        )

    def represent(self, view, allocated_target_w, *, import_floor_w=None):
        if not view.valid:
            raise SchemaError("Invalid Action/service controller")
        return represent_target(
            view.configuration,
            allocated_target_w,
            view.capabilities,
            view.operating_range,
            import_floor_w=import_floor_w,
        )

    def refresh_reason(
        self, view, now, *, cached_command_w=None, last_write_at_utc=None
    ):
        if finite(cached_command_w) is None:
            return "initial_sync"
        seconds = view.configuration.refresh_seconds
        if seconds > 0 and (
            last_write_at_utc is None or now - last_write_at_utc >= seconds
        ):
            return "heartbeat_due"
        return None

    def build_plan(
        self, view, target, *, batch_id, evaluation_id, requested_plant_target_w=None
    ):
        config = view.configuration
        fixed, destination, pre, post = parse_configuration(config)
        tokens = {
            "value": target.native_value,
            "target_watts": target.representable_target_w,
            "desired_watts": target.allocated_target_w,
            "percent": target.native_value
            if config.unit == LimitUnit.PERCENT
            else target.representable_target_w / view.operating_range.full_w * 100,
            "maximum_watts": view.operating_range.full_w,
            "minimum_watts": view.operating_range.minimum_w,
            "slot": config.identity.slot,
        }
        steps = []
        for item in pre:
            steps.append(
                (
                    "pre",
                    item["action"].strip().lower(),
                    substitute(item.get("data", {}), tokens),
                    substitute(item.get("target", {}), tokens),
                )
            )
        set_path(fixed, config.value_field, target.native_value)
        steps.append(
            (
                "main",
                config.action.strip().lower(),
                substitute(fixed, tokens),
                substitute(destination, tokens),
            )
        )
        for item in post:
            steps.append(
                (
                    "post",
                    item["action"].strip().lower(),
                    substitute(item.get("data", {}), tokens),
                    substitute(item.get("target", {}), tokens),
                )
            )
        return make_batch(
            view,
            target,
            batch_id=batch_id,
            evaluation_id=evaluation_id,
            steps=steps,
            requested_plant_target_w=requested_plant_target_w,
        )
