"""Typed immutable control inputs and desired outputs. No execution authority."""

from dataclasses import dataclass, field
from enum import StrEnum
import math
from ..codec import Record, SchemaError
from .models import (
    ControlSettings,
    Observation,
    NightRestoreState,
    AllocationResult,
    RepresentedPlan,
)
from ..execution.models import ExecutionSnapshot
from ..hbc.models import HbcPolicyInput


class Action(StrEnum):
    NONE = "none"
    ADJUST = "adjust"
    MINIMUM = "minimum"
    RESTORE = "restore"
    HBC_INCREASE = "charge_priority_increase"


@dataclass(frozen=True)
class PolicyController(Record):
    uid: str
    current_w: float | None
    full_w: float
    minimum_w: float = 0.0
    available: bool = True
    participating: bool = True
    eligible: bool = True
    independently_verifiable: bool = True
    step_w: float = 0.0
    configuration_signature: str = ""
    open_loop: bool = False

    def __post_init__(self):
        if (
            not self.uid
            or not math.isfinite(self.full_w)
            or not math.isfinite(self.minimum_w)
            or self.full_w <= 0
            or not 0 <= self.minimum_w <= self.full_w
        ):
            raise SchemaError("Invalid policy controller range/identity")
        if self.current_w is not None and not math.isfinite(self.current_w):
            raise SchemaError("Non-finite live limit")
        if not math.isfinite(self.step_w) or self.step_w < 0:
            raise SchemaError("Invalid policy step")


@dataclass(frozen=True)
class PolicyMemory(Record):
    price_limiting: bool | None = None
    negative_minimum: bool = False
    night: NightRestoreState = field(default_factory=NightRestoreState)
    release_requested_since_utc: float | None = None
    night_fleet_signature: str | None = None


@dataclass(frozen=True)
class PolicySnapshot(Record):
    evaluation_id: str
    now: float
    grid: Observation
    pv: Observation
    market: Observation
    all_in: Observation
    controllers: tuple[PolicyController, ...] = ()
    settings: ControlSettings = field(default_factory=ControlSettings)
    execution: ExecutionSnapshot = field(default_factory=ExecutionSnapshot)
    hbc: HbcPolicyInput = field(default_factory=HbcPolicyInput)
    memory: PolicyMemory = field(default_factory=PolicyMemory)
    enabled: bool = True
    external_release: bool = False
    sun_below_horizon: bool = False
    rebalance_pending: bool = False
    automatic_safety_pause: bool = False
    negative_price_hbc_charge: bool = True

    def __post_init__(self):
        if not math.isfinite(self.now) or self.now <= 0:
            raise SchemaError("Invalid evaluation time")
        if len(self.controllers) > 10 or len({c.uid for c in self.controllers}) != len(
            self.controllers
        ):
            raise SchemaError("Policy fleet must be deduplicated and at most ten")


@dataclass(frozen=True)
class PolicyIntent(Record):
    evaluation_id: str
    action: Action
    status: str
    reason: str
    requested_plant_target_w: float | None
    calculated_plant_target_w: float | None = None
    raw_grid_target_w: float | None = None
    undamped_target_w: float | None = None
    price_limiting: bool = False
    remembered_price_limiting: bool | None = None
    cooldown_active: bool = False
    cooldown_until_utc: float = 0.0
    import_protection: bool = False
    large_step_damped: bool = False
    reversal_damped: bool = False
    night_suspended: bool = False
    rebalance_requested: bool = False
    external_release_full_observed: bool = False
    external_release_degraded_candidate: bool = False
    hbc_negative_override_requested: bool = False
    restriction_reasons: tuple[str, ...] = ()
    blocked: bool = False

    @property
    def physical_writes_authorized(self):
        return False


@dataclass(frozen=True)
class AllocationOutcome(Record):
    result: AllocationResult
    reasons: tuple[str, ...] = ()
    frozen_uids: tuple[str, ...] = ()
    rebalance_applied: bool = False
    rebalance_confirmed: bool = False
    blocked: bool = False


@dataclass(frozen=True)
class PolicyResult(Record):
    intent: PolicyIntent
    memory: PolicyMemory
    allocation: AllocationOutcome
    represented: RepresentedPlan | None = None
    representation_reasons: tuple[str, ...] = ()
