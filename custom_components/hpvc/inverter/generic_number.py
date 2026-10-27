"""Generic Number observation and v1.6.0 target representation; no execution."""

import math
from ..codec import SchemaError
from ..control.models import (
    ControllerObservation,
    LimitUnit,
    RepresentedTarget,
    Quality,
)
from .base import (
    AdapterView,
    NumberCapabilities,
    OperatingRange,
    ReadbackSource,
    capabilities,
    numeric_observation,
    make_batch,
    ENTITY_PATTERN,
    adapter_signature,
)


def js_round(value, decimals=0):
    scale = 10**decimals
    return math.floor(value * scale + 0.5) / scale


def validate_range(config, caps, operating):
    reasons = []
    full = operating.full_w
    low = operating.minimum_w
    if not math.isfinite(full) or full <= 0:
        reasons.append("Full Limit required")
    if not math.isfinite(low) or low < 0 or low > full:
        reasons.append("min_above_max")
    if (
        caps.minimum is not None
        and caps.maximum is not None
        and caps.minimum > caps.maximum
    ):
        reasons.append("invalid_native_range")
    if caps.step is not None and caps.step <= 0:
        reasons.append("invalid_native_step")
    if full > 0:
        required_min = low if config.unit == LimitUnit.WATTS else low / full * 100
        required_max = full if config.unit == LimitUnit.WATTS else 100
        if caps.minimum is not None and caps.minimum > required_min + 1e-9:
            reasons.append("minimum_below_native_range")
        if caps.maximum is not None and caps.maximum < required_max - 1e-9:
            reasons.append("maximum_above_native_range")
    return tuple(reasons)


def represent_target(
    config, allocated_target_w, caps=None, operating=None, *, import_floor_w=None
):
    """Represent an ALLOCATED target, preserving it separately from the command value."""
    caps = caps or NumberCapabilities()
    operating = operating or OperatingRange(config.full_limit_w, config.low_limit_w)
    if validate_range(config, caps, operating):
        raise SchemaError("Invalid representation range")
    if not math.isfinite(allocated_target_w):
        raise SchemaError("Non-finite target")
    full = operating.full_w
    low = max(operating.minimum_w, import_floor_w or 0)
    if low > full:
        raise SchemaError("Import floor exceeds full output")
    clamp = lambda v, a, b: min(max(v, a), b)
    step = caps.step if caps.step is not None and caps.step > 0 else None
    if config.unit == LimitUnit.WATTS:
        origin = caps.minimum if caps.minimum is not None else 0
        lower = max(low, origin)
        upper = min(full, caps.maximum if caps.maximum is not None else full)
        value = clamp(allocated_target_w, lower, upper)
        if allocated_target_w >= upper - 1e-9:
            value = upper
        elif step is not None:
            value = origin + js_round((value - origin) / step) * step
            if value < lower - 1e-9:
                value = (
                    origin + max(0, math.ceil((lower - origin - 1e-12) / step)) * step
                )
            value = clamp(value, lower, upper)
        native = js_round(value, 6)
        effective = native
    else:
        origin = max(0, caps.minimum or 0)
        upper = min(100, caps.maximum if caps.maximum is not None else 100)
        required = clamp(low / full * 100, origin, upper)
        value = clamp(allocated_target_w / full * 100, origin, upper)
        if allocated_target_w >= full - 1e-9:
            value = upper
        elif step is not None:
            value = clamp(
                origin + js_round((value - origin) / step) * step, origin, upper
            )
            if value / 100 * full < low - 1e-9:
                value = clamp(
                    origin
                    + max(0, math.ceil((required - origin - 1e-12) / step)) * step,
                    origin,
                    upper,
                )
        elif value / 100 * full < low - 1e-9:
            value = required
        native = js_round(value, 6)
        effective = js_round(native / 100 * full, 3)
        if effective < low - 0.001:
            native = js_round(required, 6)
            effective = js_round(native / 100 * full, 3)
    return RepresentedTarget(
        config.identity.uid, allocated_target_w, effective, native, config.unit
    )


class GenericNumberAdapter:
    def normalize(self, config, entity, now, *, operating=None, candidate=None):
        caps = capabilities(entity)
        operating = operating or OperatingRange(config.full_limit_w, config.low_limit_w)
        reasons = list(validate_range(config, caps, operating))
        target_entity = config.identity.entity_id or config.limit_number
        if not ENTITY_PATTERN.fullmatch(target_entity) or not target_entity.startswith(
            "number."
        ):
            reasons.append("number_entity_required")
        if entity is None:
            reasons.append("limit_entity_missing")
        observation = numeric_observation(
            entity,
            now,
            full_w=operating.full_w,
            percent=config.unit == LimitUnit.PERCENT,
        )
        valid = not reasons
        available = observation.quality == Quality.VALID
        signature = adapter_signature(config, caps, operating, candidate)
        return AdapterView(
            config,
            caps,
            operating,
            ControllerObservation(config.identity, observation, available, True),
            signature,
            valid,
            available,
            valid,
            available,
            True,
            ReadbackSource.LIVE if available else ReadbackSource.UNAVAILABLE,
            reasons=tuple(reasons),
            candidate=candidate,
        )

    def represent(self, view, allocated_target_w, *, import_floor_w=None):
        if not view.valid:
            raise SchemaError("Invalid controller")
        return represent_target(
            view.configuration,
            allocated_target_w,
            view.capabilities,
            view.operating_range,
            import_floor_w=import_floor_w,
        )

    def build_plan(
        self, view, target, *, batch_id, evaluation_id, requested_plant_target_w=None
    ):
        entity = (
            view.configuration.identity.entity_id or view.configuration.limit_number
        )
        return make_batch(
            view,
            target,
            batch_id=batch_id,
            evaluation_id=evaluation_id,
            steps=[
                (
                    "main",
                    "number.set_value",
                    {"value": target.native_value},
                    {"entity_id": entity},
                )
            ],
            requested_plant_target_w=requested_plant_target_w,
        )
