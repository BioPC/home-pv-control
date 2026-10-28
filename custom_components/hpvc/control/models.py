"""Immutable policy boundaries. No Home Assistant objects or side effects."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
import math
import re
from ..codec import Record, SchemaError


class Quality(StrEnum):
    UNKNOWN = "unknown"
    VALID = "valid"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    INVALID = "invalid"


class AdapterKind(StrEnum):
    NUMBER = "generic_number"
    ACTION = "generic_action"
    HOYMILES = "hoymiles"
    ENPHASE = "enphase"


class LimitUnit(StrEnum):
    WATTS = "Watts"
    PERCENT = "Percent"


class ControlMethod(StrEnum):
    NUMBER = "Number entity"
    ACTION = "Action/service"


class DecisionMode(StrEnum):
    FOUNDATION = "foundation_disabled"
    HOLD = "hold"
    RESTORE = "restore"
    MINIMUM = "minimum"
    ADJUST = "adjust"
    EXTERNAL_RELEASE = "external_release"
    HBC_PRIORITY = "hbc_priority"


class ImportStage(StrEnum):
    DETECTED = "detected"
    PREVIEW = "preview_ready"
    INVALID = "invalid"
    COMMITTED = "config_committed_handoff_pending"


@dataclass(frozen=True)
class Observation(Record):
    source: str
    value: float | None = None
    quality: Quality = Quality.UNKNOWN
    reported_at_utc: float | None = None
    received_at_utc: float | None = None

    def __post_init__(self):
        if self.value is not None and not math.isfinite(self.value):
            raise SchemaError("Non-finite observation")
        if self.quality == Quality.VALID and self.value is None:
            raise SchemaError("Valid observation requires a value")


@dataclass(frozen=True)
class ControlSettings(Record):
    pv_limiting_price: float = 0.0
    battery_price_hysteresis: float = 0.02
    export_start_threshold: float = -150.0
    export_stop_threshold: float = 0.0
    import_restore_threshold: float = 150.0
    pv_min_power_for_control: float = 100.0
    pv_night_restore_power: float = 10.0
    cooldown_seconds: float = 30.0
    pv_adjust_deadband: float = 25.0

    def __post_init__(self):
        bounds = (
            (self.pv_limiting_price, -0.5, 0.2),
            (self.battery_price_hysteresis, 0, 0.1),
            (self.export_start_threshold, -5000, 0),
            (self.export_stop_threshold, -5000, 500),
            (self.import_restore_threshold, 0, 5000),
            (self.pv_min_power_for_control, 0, 5000),
            (self.pv_night_restore_power, 0, 1000),
            (self.cooldown_seconds, 10, 60),
            (self.pv_adjust_deadband, 1, 500),
        )
        if any(not math.isfinite(v) or not low <= v <= high for v, low, high in bounds):
            raise SchemaError("Control setting outside v1.6.0 range")
        if (
            not self.export_start_threshold
            < self.export_stop_threshold
            < self.import_restore_threshold
        ):
            raise SchemaError("Require Export Start < Target Export < Import Restore")


@dataclass(frozen=True)
class ControllerIdentity(Record):
    uid: str
    slot: int
    adapter: AdapterKind = AdapterKind.NUMBER
    device_id: str | None = None
    entity_id: str | None = None

    def __post_init__(self):
        if not self.uid or type(self.slot) is not int or not 1 <= self.slot <= 10:
            raise SchemaError("Invalid controller identity/slot")


@dataclass(frozen=True)
class ControllerConfiguration(Record):
    identity: ControllerIdentity
    signature: str
    method: ControlMethod = ControlMethod.NUMBER
    unit: LimitUnit = LimitUnit.WATTS
    full_limit_w: float = 0.0
    low_limit_w: float = 0.0
    action_step: float = 0.0
    refresh_seconds: float = 0.0
    control_enabled: bool = True
    auto_managed: bool = False
    auto_identity: str = ""
    limit_number: str = ""
    action: str = ""
    value_field: str = "value"
    fixed_data_json: str = "{}"
    target_json: str = "{}"
    pre_actions_json: str = "[]"
    post_actions_json: str = "[]"
    readback_entity: str = ""

    def __post_init__(self):
        values = (
            self.full_limit_w,
            self.low_limit_w,
            self.action_step,
            self.refresh_seconds,
        )
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise SchemaError("Invalid controller range")
        if self.low_limit_w > self.full_limit_w:
            raise SchemaError("Controller minimum exceeds maximum")
        if (
            self.full_limit_w > 10000
            or self.action_step > 10000
            or self.refresh_seconds > 3600
        ):
            raise SchemaError("Controller setting outside legacy range")


@dataclass(frozen=True)
class PlantConfiguration(Record):
    plant_uid: str
    revision: int = 1
    inverter_count: int = 0
    settings: ControlSettings = field(default_factory=ControlSettings)
    controllers: tuple[ControllerConfiguration, ...] = ()
    market_price_sensor: str = ""
    all_in_price_sensor: str = ""
    grid_power_sensor: str = ""
    pv_power_sensor: str = ""
    selected_inverter: str = "PV1"
    enabled_intent: bool = False
    external_release_request: bool = False
    insights_enabled: bool = False
    notifications: bool = True
    control_hbc_strategy: bool = False
    negative_price_hbc_charge: bool = True

    def __post_init__(self):
        if not self.plant_uid or type(self.revision) is not int or self.revision < 1:
            raise SchemaError("Invalid plant identity/revision")
        if type(self.inverter_count) is not int or not 0 <= self.inverter_count <= 10:
            raise SchemaError("Controller count must be an integer from zero to ten")
        if self.selected_inverter not in tuple(f"PV{i}" for i in range(1, 11)):
            raise SchemaError("Invalid selected inverter")
        if len(self.controllers) > 10 or len(
            {c.identity.slot for c in self.controllers}
        ) != len(self.controllers):
            raise SchemaError("Duplicate/excess controller slots")
        if len({c.identity.uid for c in self.controllers}) != len(self.controllers):
            raise SchemaError("Duplicate controller identity")
        for value in (
            self.market_price_sensor,
            self.all_in_price_sensor,
            self.grid_power_sensor,
            self.pv_power_sensor,
        ):
            if value and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value):
                raise SchemaError("Invalid source entity reference")


@dataclass(frozen=True)
class ControllerObservation(Record):
    identity: ControllerIdentity
    limit: Observation
    available: bool = False
    verification_available: bool = False
    enabled: bool | None = None
    production_mode: bool | None = None


@dataclass(frozen=True)
class PlantSnapshot(Record):
    snapshot_id: str
    observed_at_utc: float
    configuration_revision: int
    observations: tuple[Observation, ...] = ()
    controllers: tuple[ControllerObservation, ...] = ()


@dataclass(frozen=True)
class PolicyDecision(Record):
    evaluation_id: str
    mode: DecisionMode = DecisionMode.FOUNDATION
    requested_plant_target_w: float | None = None
    reason: str = "No control engine in foundation phase"


@dataclass(frozen=True)
class ControllerTarget(Record):
    controller_uid: str
    target_w: float


@dataclass(frozen=True)
class AllocationResult(Record):
    evaluation_id: str
    requested_plant_target_w: float | None
    allocated_plant_target_w: float | None
    controller_targets: tuple[ControllerTarget, ...] = ()
    shortfall_reason: str | None = None


@dataclass(frozen=True)
class RepresentedTarget(Record):
    controller_uid: str
    allocated_target_w: float
    representable_target_w: float
    native_value: float
    unit: LimitUnit


@dataclass(frozen=True)
class RepresentedPlan(Record):
    evaluation_id: str
    requested_plant_target_w: float | None
    allocated_plant_target_w: float | None
    representable_plant_target_w: float | None
    targets: tuple[RepresentedTarget, ...] = ()


@dataclass(frozen=True)
class NightRestoreState(Record):
    active: bool = False
    active_since_utc: float | None = None
    entry_candidate_since_utc: float | None = None
    recovery_candidate_since_utc: float | None = None
    full_output_proof_reference: str | None = None


@dataclass(frozen=True)
class LegacyValue(Record):
    entity_id: str
    raw: str | None


@dataclass(frozen=True)
class ImportIssue(Record):
    entity_id: str
    reason: str


@dataclass(frozen=True)
class EntityMapping(Record):
    source: str
    destination: str | None
    disposition: str


@dataclass(frozen=True)
class ImportTransaction(Record):
    transaction_id: str
    fingerprint: str
    stage: ImportStage
    candidate: PlantConfiguration | None
    captured_values: tuple[LegacyValue, ...] = ()
    issues: tuple[ImportIssue, ...] = ()
    mappings: tuple[EntityMapping, ...] = ()
    saved_enabled_intent: bool | None = None
    external_references_inspected: bool = False
