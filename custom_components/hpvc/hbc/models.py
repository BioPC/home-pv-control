"""External HBC boundaries; no HBC writes are implemented."""

from dataclasses import dataclass
from enum import StrEnum
import math
from ..codec import Record, SchemaError
from ..control.models import Observation


class ChargePriorityState(StrEnum):
    OFF = "off"
    REQUESTED = "requested"
    WAITING = "waiting"
    ACTIVE = "active"
    EXIT_HOLD = "exit_hold"


class OverridePhase(StrEnum):
    INACTIVE = "inactive"
    ENTERING_STRATEGY = "entering_strategy"
    ENTERING_GOAL = "entering_goal"
    ACTIVE = "active"
    RESTORING_GOAL = "restoring_goal"
    RESTORING_STRATEGY = "restoring_strategy"
    UNKNOWN_PREVIOUS = "recovery_unknown_previous"


@dataclass(frozen=True)
class HbcState(Record):
    available: bool | None = None
    execution_strategy: str | None = None
    charge_priority: ChargePriorityState = ChargePriorityState.OFF
    battery_observations: tuple[Observation, ...] = ()
    response_window_until_utc: float | None = None
    transition_settle_until_utc: float | None = None


@dataclass(frozen=True)
class HbcOverrideRecovery(Record):
    phase: OverridePhase = OverridePhase.INACTIVE
    saved_strategy: str | None = None
    saved_charge_goal: str | None = None
    forced_write_issued: bool | None = None
    persistence_token: str | None = None
    operation_ids: tuple[str, ...] = ()
    fault: str | None = None

    def __post_init__(self):
        if self.phase not in (
            OverridePhase.INACTIVE,
            OverridePhase.UNKNOWN_PREVIOUS,
        ) and (not self.saved_strategy or not self.saved_charge_goal):
            raise SchemaError("Active override requires saved strategy and goal")


@dataclass(frozen=True)
class HbcPolicyInput(Record):
    """Resolved HBC observations/intents; no external entity or write interface.

    Full battery-selection/response/taper derivation remains a separate substage.
    Supplied priority flags must come from that typed evaluator, never HA helpers.
    """

    available: bool = False
    control_enabled: bool = False
    execution_strategy: str | None = None
    usable_batteries: int = 0
    eligible_headroom_w: float = 0.0
    response_window_active: bool = False
    transition_settle_active: bool = False
    persistent_export_fallback: bool = False
    suppress_export_limiting: bool = False
    priority_operational: bool = False
    increase_required: bool = False
    increase_target_w: float | None = None
    taper_release_requested: bool = False
    override_restore_pending: bool = False
    override_entities_present: bool = False
    minimum_lock_reason: str | None = None

    def __post_init__(self):
        if type(self.usable_batteries) is not int or self.usable_batteries < 0:
            raise SchemaError("Invalid usable battery count")
        if not math.isfinite(self.eligible_headroom_w) or self.eligible_headroom_w < 0:
            raise SchemaError("Invalid eligible HBC headroom")
        if self.increase_target_w is not None and (
            not math.isfinite(self.increase_target_w) or self.increase_target_w < 0
        ):
            raise SchemaError("Invalid HBC PV target")

    @property
    def ready(self):
        return (
            self.available
            and self.control_enabled
            and self.usable_batteries > 0
            and self.execution_strategy in ("Charge", "Charge PV")
        )
