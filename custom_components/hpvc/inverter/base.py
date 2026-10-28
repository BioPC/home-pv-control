"""Immutable read-only inverter boundaries. Command steps are DATA, never calls."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
import re
from ..codec import Record, SchemaError
from ..control.models import (
    ControllerConfiguration,
    ControllerObservation,
    Observation,
    Quality,
)
from ..execution.models import CommandBatch, CommandStep
from ..storage import canonical, strict_json

ENTITY_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
ACTION_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


class ReadbackSource(StrEnum):
    LIVE = "readback"
    COMMAND_CACHE = "command-cache"
    STARTUP_ASSUMPTION = "startup-full-assumption"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EntityRecord(Record):
    entity_id: str
    state: str | None = None
    reported_at_utc: float | None = None
    attributes_json: str = "{}"

    @property
    def attributes(self):
        result = strict_json(self.attributes_json)
        if not isinstance(result, dict):
            raise SchemaError("Entity attributes must be an object")
        return result


@dataclass(frozen=True)
class RegistryEntity(Record):
    entity_id: str
    registry_id: str = ""
    device_id: str = ""
    platform: str = ""
    config_entry_id: str = ""
    unique_id: str = ""
    original_name: str = ""
    translation_key: str = ""
    original_entity_id: str = ""
    disabled: bool = False

    @property
    def metadata_values(self):
        return (
            self.unique_id,
            self.original_name,
            self.translation_key,
            self.original_entity_id,
            self.entity_id,
        )


@dataclass(frozen=True)
class RegistryDevice(Record):
    device_id: str
    manufacturer: str = ""
    model: str = ""
    model_id: str = ""
    name: str = ""
    configuration_url: str = ""
    identifiers_json: str = "[]"


@dataclass(frozen=True)
class DiscoveryCandidate(Record):
    uid: str
    kind: str
    limit_entity: str
    device_id: str = ""
    enable_entity: str = ""
    mode_entity: str = ""
    serial: str = ""
    configuration_url: str = ""
    metadata_verified: bool = False


@dataclass(frozen=True)
class NumberCapabilities(Record):
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    native_unit: str | None = None


@dataclass(frozen=True)
class OperatingRange(Record):
    full_w: float
    minimum_w: float
    source: str = "HPVC manual Full limit"
    max_power_locked: bool = False


@dataclass(frozen=True)
class AdapterView(Record):
    configuration: ControllerConfiguration
    capabilities: NumberCapabilities
    operating_range: OperatingRange
    observation: ControllerObservation
    configuration_signature: str
    valid: bool
    available: bool
    writable_capable: bool
    independently_verifiable: bool
    supports_verification: bool
    current_source: ReadbackSource = ReadbackSource.UNAVAILABLE
    assumed_limit_w: float | None = None
    reasons: tuple[str, ...] = ()
    candidate: DiscoveryCandidate | None = None
    readiness_observed: bool = True

    @property
    def physical_writes_authorized(self):
        return False


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def capabilities(entity):
    attrs = entity.attributes if entity else {}
    return NumberCapabilities(
        finite(attrs.get("min")),
        finite(attrs.get("max")),
        finite(attrs.get("step")),
        attrs.get("unit_of_measurement"),
    )


def numeric_observation(entity, now, *, full_w=0, percent=False, max_age=180):
    if entity is None:
        return Observation("missing")
    number = finite(entity.state)
    if entity.state is None or str(entity.state).strip().lower() in (
        "",
        "unknown",
        "unavailable",
        "none",
    ):
        return Observation(
            entity.entity_id,
            quality=Quality.UNAVAILABLE
            if str(entity.state).lower() == "unavailable"
            else Quality.UNKNOWN,
            reported_at_utc=entity.reported_at_utc,
            received_at_utc=now,
        )
    if number is None:
        return Observation(
            entity.entity_id,
            quality=Quality.INVALID,
            reported_at_utc=entity.reported_at_utc,
            received_at_utc=now,
        )
    if percent:
        if full_w <= 0 or not 0 <= number <= 100:
            return Observation(
                entity.entity_id, quality=Quality.INVALID, received_at_utc=now
            )
        number = number / 100 * full_w
    stamp = entity.reported_at_utc
    quality = (
        Quality.VALID
        if stamp is not None and stamp > 0 and -60 <= now - stamp <= max_age
        else Quality.STALE
    )
    return Observation(entity.entity_id, number, quality, stamp, now)


def make_batch(
    view, target, *, batch_id, evaluation_id, steps, requested_plant_target_w=None
):
    if not view.valid:
        raise SchemaError("Cannot plan an invalid controller")
    if not view.configuration.control_enabled:
        raise SchemaError("Controller opted out")
    if not steps:
        raise SchemaError("Command plan is empty")
    built = []
    for index, (phase, action, data, destination) in enumerate(steps):
        if not ACTION_PATTERN.fullmatch(action):
            raise SchemaError("Invalid action identification")
        built.append(
            CommandStep(
                f"{batch_id}:{index}",
                phase,
                action,
                canonical(data),
                canonical(destination),
            )
        )
    return CommandBatch(
        batch_id,
        evaluation_id,
        view.configuration.identity.uid,
        view.configuration_signature,
        fingerprint([item.to_dict() for item in built]),
        (target,),
        tuple(built),
        requested_plant_target_w,
    )


def adapter_signature(config, caps, operating, candidate=None):
    """Physical adapter identity excludes mutable permission/UI bookkeeping."""
    data = config.to_dict()
    for key in ("signature", "control_enabled", "auto_managed", "auto_identity"):
        data.pop(key, None)
    identity = dict(data["identity"])
    if config.method.value != "Action/service" or not any(
        "{{slot}}" in raw
        for raw in (
            config.fixed_data_json,
            config.target_json,
            config.pre_actions_json,
            config.post_actions_json,
        )
    ):
        identity.pop("slot", None)
    data["identity"] = identity
    return fingerprint(
        [
            data,
            caps.to_dict(),
            operating.to_dict(),
            candidate.to_dict() if candidate else None,
        ]
    )
