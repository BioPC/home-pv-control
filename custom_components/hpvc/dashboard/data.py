"""Entry-owned observation and bounded dashboard data; never a control caller."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..codec import Record, SchemaError
from ..storage import VersionedStore

TTL = 90.0
HISTORY_LIMIT = 2880


@dataclass(frozen=True)
class HistoryPoint(Record):
    at: float
    mode: str = "unknown"
    priority: str = "unknown"
    cooldown: bool | None = None
    settling: bool | None = None
    evidence_ids: tuple[str, ...] = ()
    reason: str = "No confirmed execution evidence"
    verification_pending: bool | None = None
    limited: bool | None = None

    def __post_init__(self):
        if (
            not math.isfinite(self.at)
            or self.at <= 0
            or self.mode not in ("Normal", "Charge", "Limit", "unknown")
            or self.priority not in ("Off", "Waiting", "Active", "unknown")
        ):
            raise SchemaError("Invalid dashboard history point")
        if self.mode != "unknown" and not self.evidence_ids:
            raise SchemaError("Executed mode needs independent evidence")
        if (
            len(self.evidence_ids) > 11
            or any(len(k) > 64 for k in self.evidence_ids)
            or len(self.reason) > 160
        ):
            raise SchemaError("Dashboard point exceeds retention budget")


@dataclass(frozen=True)
class Insight(Record):
    at: float
    category: str
    message: str

    def __post_init__(self):
        if (
            not math.isfinite(self.at)
            or len(self.message) > 512
            or len(self.category) > 40
        ):
            raise SchemaError("Invalid dashboard Insight")


@dataclass(frozen=True)
class DashboardState(Record):
    plant_uid: str
    local_date: str = ""
    points: tuple[HistoryPoint, ...] = ()
    insights: tuple[Insight, ...] = ()
    measured: int = 0
    unavailable: int = 0
    duplicate: int = 0
    within: int = 0
    absolute_error: float = 0.0
    squared_error: float = 0.0
    last_grid_stamp: float | None = None

    def __post_init__(self):
        if (
            not self.plant_uid
            or len(self.points) > HISTORY_LIMIT
            or len(self.insights) > 20
        ):
            raise SchemaError("Invalid dashboard storage bound")
        if (
            any(
                type(v) is not int or not 0 <= v <= 172800
                for v in (self.measured, self.unavailable, self.duplicate, self.within)
            )
            or self.within > self.measured
        ):
            raise SchemaError("Invalid dashboard sample counts")
        if any(
            not math.isfinite(v) or v < 0
            for v in (self.absolute_error, self.squared_error)
        ):
            raise SchemaError("Invalid dashboard accuracy totals")
        if any(b.at < a.at for a, b in zip(self.points, self.points[1:])) or any(
            b.at > a.at for a, b in zip(self.insights, self.insights[1:])
        ):
            raise SchemaError("Invalid dashboard time ordering")


def fresh(stamp, now, ttl=TTL):
    return (
        type(stamp) in (int, float) and math.isfinite(stamp) and 0 <= now - stamp <= ttl
    )


def priority_state(runtime, now):
    """Present accepted HBC memory, never re-evaluate Charge Priority."""
    adapter = getattr(runtime, "policy_runtime", None)
    accepted = getattr(adapter, "accepted", None)
    clock = getattr(accepted, "last_clock", None)
    strategy = runtime.state_reader("input_select.house_battery_strategy")
    if (
        not strategy
        or strategy.state in ("unknown", "unavailable", "")
        or not accepted
        or getattr(adapter, "fault", None)
        or not clock
        or not fresh(clock.utc, now)
    ):
        return "unknown"
    # This is the authoritative HBC runtime state, not an issued-command claim.
    return {
        "off": "Off",
        "waiting": "Waiting",
        "active": "Active",
        "exit_hold": "Waiting",
    }.get(accepted.hbc.priority_state, "unknown")


def observe_execution(runtime, now):
    """Only independently verified native operations can label executed modes.

    Requested intent, accepted simulation facts, startup assumptions and helper
    readbacks cannot prove execution. An incomplete fleet always leaves a gap.
    """
    priority = priority_state(runtime, now)
    ledger = runtime.ledger.current
    fleet = runtime.manager.current.effective
    unknown = HistoryPoint(now, priority=priority)
    if (
        not fleet
        or runtime.recovery_required
        or ledger.ownership.state.value != "native_active"
    ):
        return unknown
    proofs = {p.evidence_id: p for p in ledger.evidence}
    used = []
    full = True
    for row in fleet:
        observation = row.view.observation.limit
        if (
            not row.view.available
            or not row.view.independently_verifiable
            or observation.quality.value != "valid"
            or not fresh(observation.reported_at_utc, now)
        ):
            return replace(
                unknown, reason="Missing or stale independent fleet readback"
            )
        candidates = [
            op
            for op in ledger.operations
            if op.controller_uid == row.uid
            and op.configuration_signature == row.view.configuration_signature
            and op.lane.value == "inverter"
        ]
        if not candidates:
            return unknown
        op = max(candidates, key=lambda op: op.prepared_at_utc or 0)
        if (
            op.owner_epoch == ledger.ownership.owner_epoch
            and not op.owner_epoch.startswith("simulation")
            and op.dispatch_id
            and op.transport.value == "completed"
            and op.state.value in ("service_completed", "awaiting_verification")
            and fresh(op.service_completed_at_utc, now)
        ):
            return replace(
                unknown,
                verification_pending=True,
                reason="Physical service completed; independent verification pending",
            )
        if (
            op.owner_epoch != ledger.ownership.owner_epoch
            or op.owner_epoch.startswith("simulation")
            or not op.dispatch_id
            or op.transport.value != "completed"
            or op.state.value not in ("verified", "retired")
        ):
            return unknown
        confirmed = [
            proofs[k]
            for k in op.evidence_ids
            if k in proofs
            and proofs[k].kind in ("ha_readback", "opendtu_api", "enphase_readback")
            and proofs[k].verdict.value == "verified"
            and proofs[k].operation_id == op.operation_id
            and fresh(proofs[k].reported_at_utc, now)
            and proofs[k].observed_value_w is not None
            and abs(proofs[k].observed_value_w - observation.value)
            <= proofs[k].tolerance_w
        ]
        if not confirmed:
            return unknown
        proof = max(confirmed, key=lambda p: p.reported_at_utc)
        if len(proof.evidence_id) > 64:
            return unknown
        used.append(proof.evidence_id)
        full = full and abs(observation.value - row.view.operating_range.full_w) <= max(
            p.tolerance_w for p in confirmed
        )
    # A Charge label additionally requires independently verified HBC execution.
    hbc_ops = [
        op
        for op in ledger.operations
        if op.lane.value == "hbc_override"
        and op.owner_epoch == ledger.ownership.owner_epoch
    ]
    op = max(hbc_ops, key=lambda op: op.prepared_at_utc or 0) if hbc_ops else None
    strategy = runtime.state_reader("input_select.house_battery_strategy")
    charge = bool(
        op
        and strategy
        and strategy.state == op.expected_native_value
        and op.transport.value == "completed"
        and op.state.value in ("verified", "retired")
        and op.expected_native_value in ("Charge", "Charge PV")
        and any(
            k in proofs
            and proofs[k].kind == "independent_native_state"
            and proofs[k].verdict.value == "verified"
            and proofs[k].operation_id == op.operation_id
            and fresh(proofs[k].reported_at_utc, now)
            and proofs[k].observed_native_value == op.expected_native_value
            for k in op.evidence_ids
        )
    )
    # No physical accepted-command cooldown feed exists in dev.8. Do not use
    # simulated cooldown snapshots or recompute a second control state machine.
    if charge and priority == "Active":
        proof = next(
            proofs[k]
            for k in op.evidence_ids
            if k in proofs
            and proofs[k].kind == "independent_native_state"
            and proofs[k].verdict.value == "verified"
            and fresh(proofs[k].reported_at_utc, now)
        )
        if len(proof.evidence_id) > 64:
            return unknown
        used.append(proof.evidence_id)
    return HistoryPoint(
        now,
        "Charge" if charge and priority == "Active" else "Normal" if full else "Limit",
        priority,
        evidence_ids=tuple(used),
        limited=not full,
        reason="Independent native operation/readback evidence; cooldown unavailable",
    )


def collect(
    state,
    point,
    *,
    day,
    grid=None,
    grid_stamp=None,
    target=0.0,
    deadband=25.0,
    insights_enabled=True,
    extra_insights=(),
):
    if state.points and point.at < state.points[-1].at:
        raise SchemaError("Dashboard clock moved backwards")
    if state.local_date and day < state.local_date:
        raise SchemaError("Dashboard local date moved backwards")
    if day != state.local_date:
        state = DashboardState(state.plant_uid, day, state.points)
    measured, unavailable, duplicate, within = (
        state.measured,
        state.unavailable,
        state.duplicate,
        state.within,
    )
    absolute, squared = state.absolute_error, state.squared_error
    stamp = state.last_grid_stamp
    if (
        point.mode == "unknown"
        or not fresh(grid_stamp, point.at, 180)
        or type(grid) not in (float, int)
        or not math.isfinite(grid)
    ):
        unavailable += 1
    elif grid_stamp == stamp:
        duplicate += 1
    else:
        error = grid - target
        if not math.isfinite(absolute + abs(error)) or not math.isfinite(
            squared + error * error
        ):
            unavailable += 1
        else:
            measured += 1
            within += abs(error) <= deadband
            absolute += abs(error)
            squared += error * error
            stamp = grid_stamp
    insights = list(state.insights)
    previous = state.points[-1] if state.points else None
    if insights_enabled:
        messages = list(extra_insights)
        if previous is None or (point.mode, point.reason) != (
            previous.mode,
            previous.reason,
        ):
            messages.append(("Control observation", f"{point.mode}: {point.reason}"))
        if previous is None or point.priority != previous.priority:
            messages.append(("Charge Priority runtime", point.priority))
        for category, message in messages:
            # State transitions/events only; never invent a decision or action.
            insights.insert(0, Insight(point.at, category[:40], message[:512]))
    return DashboardState(
        state.plant_uid,
        day,
        (*state.points, point)[-HISTORY_LIMIT:],
        tuple(insights[:20]),
        measured,
        unavailable,
        duplicate,
        within,
        absolute,
        squared,
        stamp,
    )


def accuracy(state):
    n = state.measured
    attempts = n + state.unavailable + state.duplicate
    return {
        "measured": n,
        "unavailable": state.unavailable,
        "duplicate": state.duplicate,
        "within": state.within,
        "coverage_percent": 100 * n / attempts if attempts else None,
        "accuracy_percent": 100 * state.within / n if n else None,
        "mae_w": state.absolute_error / n if n else None,
        "rmse_w": math.sqrt(state.squared_error / n) if n else None,
        "formula": "100 × unique measured samples within configured PV adjust deadband of Target Export / unique measured samples; sampled coverage, not whole-day duration",
    }


class DashboardObserver:
    """A separate, entry-owned store and worker. Errors never write control state."""

    def __init__(self, runtime, path, timezone_name="UTC", *, clock=time.time):
        self.runtime = runtime
        self.store = VersionedStore(path, "dashboard_observations", DashboardState)
        self.state = DashboardState(runtime.configuration.plant_uid)
        self.zone = UTC if timezone_name == "UTC" else ZoneInfo(timezone_name)
        self.clock = clock
        self.fault = None
        self.latest = None
        self.last_policy_id = None
        self.lock = asyncio.Lock()

    async def load(self):
        try:
            value = await self.store.load()
            if value is not None and value.plant_uid != self.state.plant_uid:
                raise SchemaError("Dashboard store belongs to another plant")
            self.state = value or self.state
            # Retained history is not current evidence after a restart.
            await self.sample(restart=True)
        except Exception as error:  # noqa: BLE001 -- isolate presentation storage failures from control setup
            self.fault = "Dashboard storage unavailable: " + type(error).__name__

    async def sample(self, *, restart=False):
        async with self.lock:
            if self.fault or self.runtime.owner.closed:
                return
            now = self.clock()
            day = datetime.fromtimestamp(now, self.zone).date().isoformat()
            point = (
                HistoryPoint(
                    now, reason="HA restart: live evidence must be re-established"
                )
                if restart
                else observe_execution(self.runtime, now)
            )
            raw = self.runtime.state_reader(
                self.runtime.configuration.grid_power_sensor
            )
            try:
                grid, stamp = float(raw.state), raw.last_reported.timestamp()
            except (AttributeError, TypeError, ValueError):
                grid = stamp = None
            messages = []
            proposal = getattr(self.runtime, "policy_proposal", None)
            identity = getattr(getattr(proposal, "policy", None), "intent", None)
            event_id = getattr(identity, "evaluation_id", None)
            if (
                event_id
                and event_id != self.last_policy_id
                and fresh(proposal.clock.utc, now)
            ):
                messages.append(
                    (
                        "Read-only policy evaluation",
                        f"{identity.status}: {identity.reason} (proposal, not executed)",
                    )
                )
            candidate = collect(
                self.state,
                point,
                day=day,
                grid=grid,
                grid_stamp=stamp,
                target=self.runtime.configuration.settings.export_stop_threshold,
                deadband=self.runtime.configuration.settings.pv_adjust_deadband,
                insights_enabled=self.runtime.configuration.insights_enabled,
                extra_insights=messages,
            )
            await self.store.commit(candidate, self.store.revision)
            self.state, self.latest, self.last_policy_id = candidate, point, event_id
            self.runtime.publish()

    async def run(self):
        while not self.runtime.owner.closed:
            await asyncio.sleep(30)
            try:
                await self.sample()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- the entry-owned observer must fail visibly without changing control
                self.fault = "Dashboard sampling unavailable: " + type(error).__name__
                self.latest = None
                self.runtime.publish()

    def presentation(self, now):
        current = (
            self.latest
            if self.latest and fresh(self.latest.at, now) and not self.fault
            else HistoryPoint(now, reason=self.fault or "Stale dashboard observation")
        )
        day = datetime.fromtimestamp(now, self.zone).date().isoformat()
        state = (
            self.state
            if day == self.state.local_date
            else DashboardState(self.state.plant_uid, day, self.state.points)
        )
        return {
            "current": current.to_dict(),
            "accuracy": accuracy(state),
            "insights": [
                {
                    **i.to_dict(),
                    "time": datetime.fromtimestamp(i.at, self.zone).strftime(
                        "%H:%M:%S"
                    ),
                }
                for i in state.insights
            ],
            "history": [p.to_dict() for p in state.points],
            "local_date": day,
            "fault": self.fault,
            "sampled_at": self.latest.at if self.latest else None,
            "stale": current is not self.latest,
        }
