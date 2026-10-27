"""External HBC boundaries; no HBC writes are implemented."""

from dataclasses import dataclass
from enum import StrEnum
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
