"""Immutable raw HBC observations, clocks, learning memory and proposed intents."""

from dataclasses import dataclass, field
import math
from ..codec import Record, SchemaError
from ..control.decisions import PolicySnapshot
from .models import HbcPolicyInput


@dataclass(frozen=True)
class Clock(Record):
    utc: float
    monotonic: float
    boot_id: str

    def __post_init__(self):
        if (
            not self.boot_id
            or not math.isfinite(self.utc)
            or self.utc <= 0
            or not math.isfinite(self.monotonic)
            or self.monotonic < 0
        ):
            raise SchemaError("Invalid runtime clock")

    def age(self, other, *, durable=False):
        if other is None:
            return None
        value = (
            self.monotonic - other.monotonic
            if self.boot_id == other.boot_id
            else self.utc - other.utc
            if durable
            else None
        )
        return value if value is not None and value >= 0 else None

    def shift(self, seconds):
        return Clock(self.utc + seconds, self.monotonic + seconds, self.boot_id)

    def remaining(self, deadline):
        if deadline is None:
            return 0.0
        return max(
            0,
            deadline.monotonic - self.monotonic
            if self.boot_id == deadline.boot_id
            else deadline.utc - self.utc,
        )


@dataclass(frozen=True)
class RawEntity(Record):
    entity_id: str
    state: str | None = None
    updated_at_utc: float | None = None
    heartbeat_at_utc: float | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaperBand(Record):
    key: str
    ceiling_w: float | None = None
    samples: int = 0
    last_seen: Clock | None = None
    last_probe: Clock | None = None
    stable_since: Clock | None = None
    last_power_w: float | None = None
    result: str = ""
    absorbed_ratio: float | None = None
    expected_share_w: float = 0.0
    export_increase_w: float = 0.0
    failure_count: int = 0
    failure_until: Clock | None = None
    failure_baseline_w: float = 0.0
    requires_recovery: bool = False
    idle_until: Clock | None = None
    contamination_count: int = 0
    contamination_until: Clock | None = None
    contaminated_delta_w: float | None = None
    contaminated_limit_w: float | None = None

    def __post_init__(self):
        if self.key not in ("90-92", "92-94", "94-96", "96-98", "98-100"):
            raise SchemaError("Invalid taper SOC band")
        if any(
            type(n) is not int or n < 0
            for n in (self.samples, self.failure_count, self.contamination_count)
        ):
            raise SchemaError("Invalid taper sample/counter state")
        if self.ceiling_w is not None and (
            not math.isfinite(self.ceiling_w) or self.ceiling_w < 0
        ):
            raise SchemaError("Invalid learned taper capacity")


@dataclass(frozen=True)
class BatteryMemory(Record):
    index: int
    max_charge_w: float | None = None
    max_updated: Clock | None = None
    charging_cutoff: float | None = None
    discharging_cutoff: float | None = None
    cutoff_updated: Clock | None = None
    bands: tuple[TaperBand, ...] = ()

    def __post_init__(self):
        if (
            type(self.index) is not int
            or not 1 <= self.index <= 6
            or len(self.bands) > 5
            or len({b.key for b in self.bands}) != len(self.bands)
        ):
            raise SchemaError("Invalid battery memory identity/bands")


@dataclass(frozen=True)
class ProbeBattery(Record):
    index: int
    band: str
    charging_w: float
    effective_ceiling_w: float
    expected_share_w: float
    power_updated_at_utc: float | None
    idle_startup: bool = False


@dataclass(frozen=True)
class PendingProbe(Record):
    accepted_event_id: str
    accepted: Clock
    step_w: float
    export_before_w: float
    batteries: tuple[ProbeBattery, ...]


@dataclass(frozen=True)
class OverrideMemory(Record):
    phase: str = "inactive"
    phase_since: Clock | None = None
    capture_token: str = ""
    previous_strategy: str | None = None
    previous_goal: str | None = None
    last_retry: Clock | None = None
    last_step: str = ""
    retries: int = 0
    forced_write_issued: bool = False
    fault: bool = False
    fault_published: Clock | None = None
    error: str | None = None

    def __post_init__(self):
        if self.phase not in (
            "inactive",
            "entering_strategy",
            "entering_goal",
            "active",
            "restoring_goal",
            "restoring_strategy",
            "recovery_unknown_previous",
        ):
            raise SchemaError("Invalid override phase")


@dataclass(frozen=True)
class HbcMemory(Record):
    boot_id: str = ""
    batteries: tuple[BatteryMemory, ...] = ()
    priority_state: str = "off"
    last_confirmed: Clock | None = None
    transition_until: Clock | None = None
    persistent_export_since: Clock | None = None
    safety_paused: bool = False
    healthy_since: Clock | None = None
    pending_probe: PendingProbe | None = None
    override: OverrideMemory = field(default_factory=OverrideMemory)
    interrupted_probe: bool = False

    def __post_init__(self):
        if (
            len(self.batteries) > 6
            or len({b.index for b in self.batteries}) != len(self.batteries)
            or self.priority_state not in ("off", "waiting", "active", "exit_hold")
        ):
            raise SchemaError("Invalid HBC memory")


@dataclass(frozen=True)
class AcceptedOverrideStep(Record):
    step: str
    accepted: Clock
    capture_token: str


@dataclass(frozen=True)
class HbcSnapshot(Record):
    policy: PolicySnapshot
    clock: Clock
    entities: tuple[RawEntity, ...] = ()
    memory: HbcMemory = field(default_factory=HbcMemory)
    permission: bool = False
    negative_charge_permission: bool = True
    durable_capture_token: str | None = None
    accepted_override_token: str | None = None
    accepted_override_steps: tuple[str, ...] = ()
    accepted_override_events: tuple[AcceptedOverrideStep, ...] = ()
    override_step_error: str | None = None
    acknowledge_unknown_override: bool = False
    last_release: Clock | None = None
    last_command_delta_w: float | None = None
    last_command: Clock | None = None
    last_command_failed: bool = False

    def __post_init__(self):
        if len({e.entity_id for e in self.entities}) != len(self.entities):
            raise SchemaError("Duplicate raw HBC entity")


@dataclass(frozen=True)
class BatteryTelemetry(Record):
    index: int
    soc: float | None
    power_w: float | None
    power_updated_at_utc: float | None
    charging_cutoff: float | None
    discharging_cutoff: float | None
    cutoff_usable: bool
    power_fresh: bool
    soc_fresh: bool
    telemetry_usable: bool
    control_enabled: bool
    usable: bool
    freshness_mode: str
    cutoff_source: str
    faults: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatteryResult(Record):
    telemetry: BatteryTelemetry
    status: str
    max_charge_w: float = 0.0
    max_source: str = "unknown"
    charging: bool = False
    eligible: bool = False
    raw_headroom_w: float = 0.0
    normal_headroom_w: float = 0.0
    taper_allowance_w: float = 0.0
    effective_ceiling_w: float = 0.0
    learned_ceiling_w: float | None = None
    band: str | None = None
    probe_eligible: bool = False
    awaiting_confirmation: bool = False
    idle_startup: bool = False
    step_cap_w: float = 0.0
    stable_seconds: float = 0.0
    exclusion: str = ""


@dataclass(frozen=True)
class HbcActionIntent(Record):
    step: str
    action: str
    entity_id: str
    option: str | None = None
    capture_token: str = ""
    requires_durable_capture: bool = False
    data_json: str = "{}"


@dataclass(frozen=True)
class OverrideResult(Record):
    memory: OverrideMemory
    actions: tuple[HbcActionIntent, ...] = ()
    capture_required: bool = False
    minimum_lock: bool = False
    recovery_required: bool = False
    hbc_force_requested: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HbcResult(Record):
    memory: HbcMemory
    resolved: HbcPolicyInput
    batteries: tuple[BatteryResult, ...]
    order: tuple[int, ...]
    configuration_valid: bool
    control_available: bool
    safety_recovering: bool
    state: str
    display_state: str
    normal_headroom_w: float
    taper_headroom_w: float
    total_power_w: float
    confirmed_enter: bool
    confirmed_remain: bool
    engaged: bool
    increase_w: float
    unshaped_increase_w: float
    step_cap_w: float
    large_step_damped: bool
    reversal_damped: bool
    response_remaining_s: float
    transition_remaining_s: float
    exit_hold_remaining_s: float
    persistent_export_age_s: float
    override: OverrideResult
    faults: tuple[str, ...] = ()

    @property
    def physical_writes_authorized(self):
        return False
