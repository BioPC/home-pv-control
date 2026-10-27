"""Execution-owned accepted-command DATA. The only recorder is simulation-only."""

from dataclasses import dataclass, replace
import asyncio
from ..codec import Record, SchemaError
from ..hbc.state import Clock
from .models import OperationState, TransportStatus


@dataclass(frozen=True)
class AcceptedController(Record):
    operation_id: str
    controller_uid: str
    configuration_signature: str
    dispatch_id: str
    before_w: float | None
    target_w: float | None
    entity_id: str = ""
    native_target: str | None = None


@dataclass(frozen=True)
class AcceptedCommand(Record):
    event_id: str
    plant_uid: str
    evaluation_id: str
    accepted: Clock
    action: str
    controllers: tuple[AcceptedController, ...]
    cooldown_seconds: float
    lane: str = "inverter"
    capture_token: str = ""
    origin: str = "simulated"
    owner_epoch: str = "simulation"

    def __post_init__(self):
        if (
            self.origin != "simulated"
            or not self.event_id
            or not self.plant_uid
            or not self.evaluation_id
            or not self.controllers
        ):
            raise SchemaError(
                "Only bound simulated accepted-command facts exist in this stage"
            )
        if (
            self.action
            not in (
                "none",
                "adjust",
                "minimum",
                "restore",
                "charge_priority_increase",
                "enter_strategy",
                "enter_goal",
                "restore_goal",
                "restore_strategy",
                "fault_on",
                "fault_off",
                "fault_notification",
                "fault_dismiss",
            )
            or self.lane not in ("inverter", "hbc_override")
            or not 0 <= self.cooldown_seconds <= 60
        ):
            raise SchemaError("Invalid accepted command contract")
        if len({c.operation_id for c in self.controllers}) != len(self.controllers):
            raise SchemaError("Duplicate accepted operation")
        if self.lane == "inverter" and any(
            c.target_w is None for c in self.controllers
        ):
            raise SchemaError("PV accepted event needs represented Watts")
        if self.lane == "hbc_override" and (
            not self.capture_token
            or any(c.native_target is None or not c.entity_id for c in self.controllers)
        ):
            raise SchemaError(
                "HBC accepted event requires captured identity and native target"
            )


@dataclass(frozen=True)
class CommandOutcome(Record):
    event_id: str
    kind: str
    observed: Clock

    def __post_init__(self):
        if self.kind not in (
            "service_failed",
            "verification_failed",
            "outcome_unknown",
            "verified",
        ):
            raise SchemaError("Invalid simulated outcome")


@dataclass(frozen=True)
class ExecutionFacts(Record):
    plant_uid: str
    events: tuple[AcceptedCommand, ...] = ()
    outcomes: tuple[CommandOutcome, ...] = ()

    def __post_init__(self):
        if (
            not self.plant_uid
            or len(self.events) > 128
            or len(self.outcomes) > 128
            or len({e.event_id for e in self.events}) != len(self.events)
        ):
            raise SchemaError("Invalid execution-fact retention/identity")
        if any(e.plant_uid != self.plant_uid for e in self.events) or any(
            o.event_id not in {e.event_id for e in self.events} for o in self.outcomes
        ):
            raise SchemaError("Orphan/wrong-plant execution facts")

    @property
    def last_inverter(self):
        return next((e for e in reversed(self.events) if e.lane == "inverter"), None)

    @property
    def last_release(self):
        return next(
            (
                e
                for e in reversed(self.events)
                if e.lane == "inverter" and e.action == "charge_priority_increase"
            ),
            None,
        )


class SimulatedEventRecorder:
    """Test-only fact acceptance; no executor, service registry or transport handle."""

    def __init__(self, store, plant_uid, ledger):
        self.store = store
        self.plant_uid = plant_uid
        self.ledger = ledger
        self.current = ExecutionFacts(plant_uid)
        self.boot_clock = None
        self.guard = asyncio.Lock()
        self.plan_validator = None

    async def load(self, clock):
        value = await self.store.load()
        if value is not None and value.plant_uid != self.plant_uid:
            raise SchemaError("Accepted facts belong to another plant")
        self.current = value or ExecutionFacts(self.plant_uid)
        self.boot_clock = clock
        return value

    async def record_simulated_acceptance(self, event):
        async with self.guard:
            return await self._record_simulated_acceptance(event)

    async def _record_simulated_acceptance(self, event):
        if (
            not isinstance(event, AcceptedCommand)
            or event.origin != "simulated"
            or event.plant_uid != self.plant_uid
        ):
            raise SchemaError("Invalid simulated event owner")
        old = next(
            (e for e in self.current.events if e.event_id == event.event_id), None
        )
        if old is not None:
            if old != event:
                raise SchemaError("Accepted-command identity cannot mutate")
            return self.current
        if self.plan_validator is not None:
            self.plan_validator(event)
        operations = {op.operation_id: op for op in self.ledger.current.operations}
        for item in event.controllers:
            op = operations.get(item.operation_id)
            if (
                op is None
                or op.state != OperationState.IN_FLIGHT
                or op.transport != TransportStatus.IN_FLIGHT
                or op.controller_uid != item.controller_uid
                or op.configuration_signature != item.configuration_signature
                or op.dispatch_id != item.dispatch_id
                or op.owner_epoch != event.owner_epoch
                or op.representable_controller_target_w != item.target_w
            ):
                raise SchemaError(
                    "Accepted event requires matching execution-owned issued operation"
                )
            if (
                op.dispatch_started_at_utc != event.accepted.utc
                or op.lane.value != event.lane
            ):
                raise SchemaError(
                    "Accepted time/lane must match execution dispatch provenance"
                )
            if event.lane == "hbc_override":
                from ..inverter.base import fingerprint

                if op.command_fingerprint != fingerprint(
                    [event.action, item.entity_id, item.native_target]
                ):
                    raise SchemaError("Accepted HBC native payload identity mismatch")
        value = replace(self.current, events=(*self.current.events, event))
        await self.store.commit(value, self.store.revision)
        self.current = value
        return value

    async def record_simulated_outcome(self, outcome):
        async with self.guard:
            return await self._record_simulated_outcome(outcome)

    async def _record_simulated_outcome(self, outcome):
        if outcome.event_id not in {e.event_id for e in self.current.events}:
            raise SchemaError("Outcome requires accepted event")
        event = next(e for e in self.current.events if e.event_id == outcome.event_id)
        operations = {op.operation_id: op for op in self.ledger.current.operations}
        expected = {
            "service_failed": (OperationState.SERVICE_FAILED,),
            "verification_failed": (OperationState.VERIFICATION_FAILED,),
            "outcome_unknown": (
                OperationState.UNKNOWN,
                OperationState.RECOVERY_REQUIRED,
            ),
            "verified": (OperationState.VERIFIED, OperationState.RETIRED),
        }[outcome.kind]
        if any(
            operations[c.operation_id].state not in expected for c in event.controllers
        ):
            raise SchemaError("Outcome cannot override authoritative operation state")
        previous = tuple(
            o for o in self.current.outcomes if o.event_id != outcome.event_id
        )
        value = replace(self.current, outcomes=(*previous, outcome))
        await self.store.commit(value, self.store.revision)
        self.current = value
        return value
