"""Pure physical-settling observations. Timeout is never restoration proof."""

from dataclasses import dataclass, replace
from enum import StrEnum
from ..codec import Record
from ..control.models import Observation, Quality


class SettlingOutcome(StrEnum):
    WAITING = "waiting"
    APPLIED = "credibly_applied"
    TIMED_OUT = "timeout_fallback"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SettlingState(Record):
    operation_id: str
    dispatched_at_utc: float
    limit_before_w: float
    target_w: float
    pv_before_w: float
    pv_before_reported_at_utc: float | None = None
    stable_samples: int = 0
    last_pv_w: float | None = None
    last_pv_reported_at_utc: float | None = None


@dataclass(frozen=True)
class SettlingResult(Record):
    state: SettlingState
    outcome: SettlingOutcome
    hold_ordinary_reversal: bool
    physical_restoration_verified: bool = False


def observe_settling(
    state,
    *,
    operation_id,
    limit_confirmed,
    pv: Observation,
    now,
    deadband_w=25,
    cooldown_seconds=30,
):
    if operation_id != state.operation_id:
        return SettlingResult(state, SettlingOutcome.UNKNOWN, True)
    timeout = max(120, cooldown_seconds * 4)
    direction = (
        1
        if state.target_w > state.limit_before_w
        else -1
        if state.target_w < state.limit_before_w
        else 0
    )
    fresh = (
        pv.quality == Quality.VALID
        and pv.value is not None
        and pv.reported_at_utc is not None
        and state.dispatched_at_utc < pv.reported_at_utc <= now + 60
        and now - pv.reported_at_utc <= 180
        and (
            state.pv_before_reported_at_utc is None
            or pv.reported_at_utc > state.pv_before_reported_at_utc
        )
    )
    delta = pv.value - state.pv_before_w if pv.value is not None else None
    directional = delta is not None and (
        direction == 0 or direction * delta >= max(deadband_w, 1)
    )
    opposite = delta is not None and direction * delta < 0
    limit_tolerance = max(5, deadband_w)
    no_response = (
        state.pv_before_w <= state.target_w + limit_tolerance
        if direction < 0
        else state.pv_before_w <= state.limit_before_w - limit_tolerance
        if direction > 0
        else True
    )
    credible_response = fresh and not opposite and (directional or no_response)
    large = abs(state.target_w - state.limit_before_w) >= max(500, deadband_w * 10)
    updated = state
    if (
        large
        and limit_confirmed
        and credible_response
        and (
            state.last_pv_reported_at_utc is None
            or pv.reported_at_utc > state.last_pv_reported_at_utc
        )
    ):
        stable = (
            1
            if state.last_pv_w is None
            or abs(pv.value - state.last_pv_w) > max(75, deadband_w * 3)
            else min(2, state.stable_samples + 1)
        )
        updated = replace(
            state,
            stable_samples=stable,
            last_pv_w=pv.value,
            last_pv_reported_at_utc=pv.reported_at_utc,
        )
    if (
        limit_confirmed
        and credible_response
        and (not large or updated.stable_samples >= 2)
    ):
        return SettlingResult(updated, SettlingOutcome.APPLIED, False)
    if now - state.dispatched_at_utc >= timeout:
        return SettlingResult(updated, SettlingOutcome.TIMED_OUT, False)
    return SettlingResult(updated, SettlingOutcome.WAITING, True)
