"""Authoritative durable sequencing, available only with the concrete fake executor."""

import asyncio, json, uuid
from functools import wraps
from dataclasses import dataclass, replace
from ..codec import Record, SchemaError
from ..storage import VersionedStore, StorageError
from ..policy_runtime import EvaluationProposal
from ..hbc.state import Clock
from ..control.engine import command_batches
from ..inverter.base import fingerprint
from .models import (
    CommandBatch,
    CommandStep,
    PhysicalOperation,
    OperationState as S,
    TransportStatus as T,
    VerificationStatus as V,
    Lane,
    RestoreObligation,
    ObligationState,
    VerificationEvidence,
)
from .executor import FakeExecutor, ExecutionRequest, QuiescenceReceipt
from .facts import AcceptedCommand, AcceptedController, CommandOutcome
from .verification import verify_operation, VerificationOutcome
from .settling import SettlingState, SettlingOutcome, SettlingResult, observe_settling
from .snapshot import build_execution_snapshot


@dataclass(frozen=True)
class Registration(Record):
    batch: CommandBatch
    proposal: EvaluationProposal
    lane: Lane
    owner_epoch: str
    configuration_reference: str
    adapter_kind: str
    full_w: float
    before_w: float | None
    pv_before_w: float
    step_w: float
    open_loop: bool = False
    device_id: str | None = None
    serial: str | None = None
    hbc_step: str = ""
    capture_token: str = ""
    maintenance_token: str = ""


@dataclass(frozen=True)
class AuditEvent(Record):
    operation_id: str
    kind: str
    clock: Clock


@dataclass(frozen=True)
class DispatchJournal(Record):
    plant_uid: str
    registrations: tuple[Registration, ...] = ()
    settling: tuple[SettlingState, ...] = ()
    history: tuple[AuditEvent, ...] = ()
    settled_operation_ids: tuple[str, ...] = ()
    superseded_settling_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            not self.plant_uid
            or len(self.registrations) > 128
            or len(self.history) > 256
        ):
            raise SchemaError("Dispatcher journal retention exceeded")
        if len({r.batch.batch_id for r in self.registrations}) != len(
            self.registrations
        ):
            raise SchemaError("Duplicate registered batch")


@dataclass(frozen=True)
class NativeObservation(Record):
    operation_id: str
    controller_uid: str
    configuration_signature: str
    owner_epoch: str
    dispatch_id: str
    entity_id: str
    state: str
    reported_at_utc: float
    received_at_utc: float


def owned_work(method):
    @wraps(method)
    async def run(self, *args, **kwargs):
        if self.closed and method.__name__ == "receive_completion":
            return False
        task = asyncio.current_task()
        self._running.add(task)
        try:
            self._healthy()
            return await method(self, *args, **kwargs)
        finally:
            self._running.discard(task)

    return run


class Dispatcher:
    """Explicitly driven fake scheduling; never constructed by live policy evaluation.

    The ledger is the operation authority. The companion journal captures immutable
    plans, archived configuration, simulated audit history and settling observations.
    Ambiguous journal/ledger commits fail closed; no armed operation is replayed.
    """

    def __init__(
        self, prefix, ledger, runtime, executor, *, owner_epoch=None, checkpoint=None
    ):
        if type(executor) is not FakeExecutor:
            raise SchemaError("dev.5 permits only the concrete FakeExecutor")
        if getattr(ledger, "_dispatcher", None) is not None:
            raise SchemaError("Ledger already has a dispatcher owner")
        ledger._dispatcher = self
        self.ledger = ledger
        self.runtime = runtime
        self.executor = executor
        self.owner_epoch = owner_epoch or uuid.uuid4().hex
        self.store = VersionedStore(
            prefix.with_name(prefix.name + "_dispatch.json"),
            "fake_dispatch",
            DispatchJournal,
        )
        self.current = DispatchJournal(ledger.plant_uid)
        self.closed = False
        self.fault = None
        self.checkpoint = checkpoint
        self._journal_lock = asyncio.Lock()
        self._registration_lock = asyncio.Lock()
        self._lanes = {lane: asyncio.Lock() for lane in Lane}
        self._running = set()
        self.identities = {}
        self.settling_results = {}
        self._old_validator = runtime.event_recorder.plan_validator
        runtime.event_recorder.plan_validator = self._validate_registered_event

    @property
    def physical_writes_authorized(self):
        return False

    async def _point(self, name, operation=None):
        if self.checkpoint is not None:
            await self.checkpoint(name, operation)

    def _healthy(self):
        if self.closed or self.fault or not self.store.healthy:
            raise StorageError("Fake dispatcher closed or requires recovery")

    async def _journal(self, transform):
        async with self._journal_lock:
            value = transform(self.current)
            try:
                await self.store.commit(value, self.store.revision)
            except BaseException:
                self.fault = "dispatcher_journal_commit_failed"
                raise
            self.current = value
            return value

    async def load(self, clock):
        value = await self.store.load()
        if value is not None and value.plant_uid != self.ledger.plant_uid:
            raise StorageError("Wrong plant dispatcher journal")
        self.current = value or self.current
        if value is None and self.ledger.current.operations:
            self.fault = "dispatcher_journal_missing_with_existing_operations"
            raise StorageError(
                "Cannot reconstruct issued plans from an absent dispatcher journal"
            )
        if value is None:
            await self._journal(lambda j: j)
        else:
            # Reload is a continuity boundary. Prepared work is safely discarded;
            # possibly issued work is reconciled by the existing durable model.
            await self.ledger.reconcile_restart()
            await self._reconstruct_obligations()
            for op in tuple(self.ledger.current.operations):
                if op.state == S.PREPARED:
                    await self.ledger.transition_operation(
                        op.operation_id,
                        S.SUPERSEDED,
                        reason="new_runtime_requires_new_intent",
                    )
            await self._journal(
                lambda j: replace(
                    j,
                    settling=tuple(
                        replace(
                            s,
                            stable_samples=0,
                            last_pv_w=None,
                            last_pv_reported_at_utc=None,
                        )
                        for s in j.settling
                    ),
                )
            )
        return self.current

    def _reg(self, batch_id):
        return next(
            r for r in self.current.registrations if r.batch.batch_id == batch_id
        )

    def _op(self, op_id):
        return next(
            o for o in self.ledger.current.operations if o.operation_id == op_id
        )

    def update_identities(self, views):
        self.identities = {
            **{k: v for k, v in self.identities.items() if k.startswith("hbc:")},
            **{
                v.configuration.identity.uid: v.configuration_signature
                for v in views
                if v.available and v.configuration.control_enabled
            },
        }

    @staticmethod
    def _shape(batch):
        return fingerprint(
            [[s.phase, s.action, s.data_json, s.target_json] for s in batch.steps]
            + [t.to_dict() for t in batch.targets]
        )

    def _validate_registered_event(self, event):
        regs = {self._op(c.operation_id).batch_id for c in event.controllers}
        if len(regs) != 1:
            raise SchemaError("Accepted event crosses registered batches")
        reg = self._reg(next(iter(regs)))
        if reg.owner_epoch != self.owner_epoch or event.owner_epoch != reg.owner_epoch:
            raise SchemaError("Prior owner cannot accept commands")
        if reg.maintenance_token:
            m = self.ledger.current.maintenance
            c = event.controllers[0]
            if (
                m.owner_token != reg.maintenance_token
                or m.post_disable_evaluation_id is None
                or event.action != "restore"
                or len(event.controllers) != 1
                or c.target_w != reg.full_w
                or c.before_w != reg.before_w
                or c.configuration_signature != reg.batch.configuration_signature
                or event.evaluation_id != reg.batch.evaluation_id
                or event.cooldown_seconds != reg.proposal.cooldown_seconds
            ):
                raise SchemaError("Unowned maintenance restoration acceptance")
        else:
            self.runtime._validate_simulated_plan(event, reg.proposal)

    @owned_work
    async def submit(self, proposal, views, clock):
        self._healthy()
        if proposal != self.runtime.last_proposal:
            raise SchemaError("Register only the accepted runtime proposal")
        self.update_identities(views)
        snapshot = build_execution_snapshot(
            self.ledger.current,
            proposal.controller_provenance,
            clock,
            self.runtime.event_recorder.current,
        )
        batches = command_batches(proposal.policy, views, snapshot)
        by_uid = {v.configuration.identity.uid: v for v in views}
        ids = []
        for batch in batches:
            v = by_uid[batch.controller_uid]
            p = next(
                c
                for c in proposal.controller_provenance
                if c.uid == batch.controller_uid
            )
            if p.configuration_signature != batch.configuration_signature:
                raise SchemaError("Policy and adapter configuration provenance differ")
            candidate = v.candidate
            reg = Registration(
                batch,
                proposal,
                Lane.INVERTER,
                self.owner_epoch,
                "config:" + batch.configuration_signature,
                v.configuration.identity.adapter.value,
                v.operating_range.full_w,
                p.current_w,
                proposal.policy.intent.raw_grid_target_w or 0,
                p.step_w,
                not v.supports_verification,
                candidate.device_id if candidate else None,
                candidate.serial if candidate else None,
            )
            # The raw PV sample, not grid target, owns the settling baseline.
            reg = replace(reg, pv_before_w=getattr(proposal, "pv_before_w", 0.0))
            ids.append(await self._register(reg, clock))
        return tuple(ids)

    @owned_work
    async def submit_hbc(self, proposal, clock):
        self._healthy()
        if proposal != self.runtime.last_proposal:
            raise SchemaError("HBC registration needs accepted proposal")
        ids = []
        for intent in proposal.hbc.override.actions:
            if intent.step not in (
                "enter_strategy",
                "enter_goal",
                "restore_goal",
                "restore_strategy",
                "fault_on",
                "fault_off",
            ):
                continue
            if (
                intent.requires_durable_capture
                and self.runtime.durable.hbc.override.capture_token
                != intent.capture_token
            ):
                raise SchemaError("HBC original capture is not durable")
            uid = "hbc:" + intent.entity_id
            signature = fingerprint([uid, intent.capture_token])
            step = CommandStep(
                proposal.policy.intent.evaluation_id + ":" + intent.step,
                "main",
                intent.action,
                json.dumps({"option": intent.option})
                if intent.option is not None
                else "{}",
                json.dumps({"entity_id": intent.entity_id}),
            )
            batch = CommandBatch(
                proposal.policy.intent.evaluation_id + ":hbc:" + intent.step,
                proposal.policy.intent.evaluation_id,
                uid,
                signature,
                fingerprint(step.to_dict()),
                steps=(step,),
            )
            self.identities[uid] = signature
            reg = Registration(
                batch,
                proposal,
                Lane.HBC,
                self.owner_epoch,
                "hbc:" + signature,
                "hbc",
                0,
                None,
                0,
                0,
                hbc_step=intent.step,
                capture_token=intent.capture_token,
            )
            ids.append(await self._register(reg, clock))
        return tuple(ids)

    async def _register(self, reg, clock):
        async with self._registration_lock:
            self._healthy()
            batch = reg.batch
            old = next(
                (
                    r
                    for r in reversed(self.current.registrations)
                    if r.batch.controller_uid == batch.controller_uid
                    and r.batch.configuration_signature == batch.configuration_signature
                    and self._shape(r.batch) == self._shape(batch)
                    and any(
                        o.batch_id == r.batch.batch_id
                        and o.state
                        not in (
                            S.RETIRED,
                            S.SUPERSEDED,
                            S.VERIFIED,
                            S.SERVICE_FAILED,
                            S.VERIFICATION_FAILED,
                        )
                        for o in self.ledger.current.operations
                    )
                ),
                None,
            )
            if old:
                return old.batch.batch_id
            if any(
                r.batch.batch_id == batch.batch_id for r in self.current.registrations
            ):
                return batch.batch_id
            operations = []
            for i, step in enumerate(batch.steps):
                native = None
                data = json.loads(step.data_json)
                if reg.lane == Lane.HBC or step.phase != "main":
                    native = (
                        str(data.get("option"))
                        if "option" in data
                        else "on"
                        if step.action.endswith(".turn_on")
                        else "off"
                        if step.action.endswith(".turn_off")
                        else None
                    )
                target = batch.targets[0] if batch.targets else None
                operation = PhysicalOperation(
                    batch.batch_id + ":op:" + str(i),
                    batch.batch_id,
                    step.step_id,
                    self.owner_epoch,
                    batch.controller_uid,
                    reg.adapter_kind,
                    batch.configuration_signature,
                    reg.configuration_reference,
                    lane=reg.lane,
                    requested_plant_target_w=batch.requested_plant_target_w,
                    representable_controller_target_w=target.representable_target_w
                    if target and step.phase == "main" and reg.lane == Lane.INVERTER
                    else None,
                    native_command_value=target.native_value
                    if target and step.phase == "main"
                    else None,
                    command_fingerprint=fingerprint(
                        [
                            reg.hbc_step,
                            json.loads(step.target_json).get("entity_id", ""),
                            native,
                        ]
                    )
                    if reg.lane == Lane.HBC
                    else fingerprint(step.to_dict()),
                    sequence_fingerprint=batch.sequence_fingerprint,
                    step_phase=step.phase,
                    step_index=i,
                    prepared_at_utc=clock.utc,
                    expected_native_value=native,
                )
                operations.append(operation)
            await self._point("before_prepared_commit")
            await self._journal(
                lambda j: replace(j, registrations=(*j.registrations, reg))
            )

            def register(l):
                started_batches = {
                    o.batch_id
                    for o in l.operations
                    if o.state not in (S.PREPARED, S.SUPERSEDED)
                }
                old = tuple(
                    replace(o, state=S.SUPERSEDED, reason="newer_unsent_generation")
                    if o.state == S.PREPARED
                    and o.controller_uid == batch.controller_uid
                    and o.batch_id not in started_batches
                    else o
                    for o in l.operations
                )
                return replace(l, operations=(*old, *operations))

            try:
                await self.ledger.update(register)
            except BaseException:
                self.fault = "prepared_commit_failed"
                raise
            await self._point("after_prepared_commit", operations[0])
            return batch.batch_id

    def _lane_busy(self, lane):
        return any(
            o.lane == lane
            and (
                o.state in (S.ARMED, S.IN_FLIGHT)
                or o.state in (S.UNKNOWN, S.RECOVERY_REQUIRED)
                and o.transport in (T.IN_FLIGHT, T.UNKNOWN)
            )
            for o in self.ledger.current.operations
        )

    def _next(self, lane):
        for op in self.ledger.current.operations:
            if (
                op.lane != lane
                or op.state != S.PREPARED
                or op.owner_epoch != self.owner_epoch
            ):
                continue
            reg = self._reg(op.batch_id)
            if self.identities.get(op.controller_uid) != op.configuration_signature:
                continue
            predecessors = [
                o
                for o in self.ledger.current.operations
                if o.batch_id == op.batch_id and o.step_index < op.step_index
            ]
            if any(
                o.state not in (S.VERIFIED, S.RETIRED)
                and not (
                    o.step_phase == "main"
                    and o.state in (S.AWAITING_VERIFICATION, S.OPEN_LOOP)
                )
                and not (
                    o.expected_native_value is None
                    and o.step_phase != "main"
                    and o.state == S.OPEN_LOOP
                )
                for o in predecessors
            ):
                continue
            other = [
                o
                for o in self.ledger.current.operations
                if o.controller_uid == op.controller_uid
                and o.batch_id != op.batch_id
                and o.state not in (S.VERIFIED, S.RETIRED, S.SUPERSEDED, S.PREPARED)
            ]
            # Completed HBC failures permit an explicit fresh policy retry; unknown
            # transport remains a lane-wide barrier.
            if (
                other
                and not (
                    reg.maintenance_token
                    and all(o.transport in (T.COMPLETED, T.FAILED) for o in other)
                )
                and not (
                    lane == Lane.HBC
                    and all(
                        o.state in (S.SERVICE_FAILED, S.VERIFICATION_FAILED)
                        and o.transport in (T.FAILED, T.COMPLETED)
                        for o in other
                    )
                )
            ):
                continue
            return op, reg
        return None

    async def pump(self, clock):
        self._healthy()
        return await asyncio.gather(*(self.pump_lane(lane, clock) for lane in Lane))

    async def pump_lane(self, lane, clock):
        task = asyncio.current_task()
        self._running.add(task)
        try:
            async with self._lanes[lane]:
                self._healthy()
                if self._lane_busy(lane):
                    return None
                item = self._next(lane)
                if item is None:
                    return None
                op, reg = item
                if reg.lane == Lane.HBC:
                    current = self.runtime.last_proposal
                    if current is None or not any(
                        a.step == reg.hbc_step and a.capture_token == reg.capture_token
                        for a in current.hbc.override.actions
                    ):
                        await self.ledger.transition_operation(
                            op.operation_id,
                            S.SUPERSEDED,
                            reason="HBC intent no longer current",
                        )
                        return None
                dispatch_id = uuid.uuid4().hex

                def arm(l):
                    armed = replace(
                        op,
                        state=S.ARMED,
                        armed_at_utc=clock.utc,
                        dispatch_id=dispatch_id,
                        dispatch_started_at_utc=clock.utc,
                    )
                    return replace(
                        l,
                        operations=tuple(
                            armed if o.operation_id == op.operation_id else o
                            for o in l.operations
                        ),
                    )

                try:
                    await self.ledger.update(arm)
                    await self._point("after_armed_commit", self._op(op.operation_id))
                    request = ExecutionRequest(
                        op.operation_id,
                        dispatch_id,
                        self.owner_epoch,
                        op.controller_uid,
                        op.configuration_signature,
                        lane,
                        reg.batch.steps[op.step_index],
                        clock,
                    )
                    await self._point("before_executor_call", self._op(op.operation_id))
                    receipt = await self.executor.issue(request)
                    await self._point(
                        "after_executor_call_before_inflight", self._op(op.operation_id)
                    )
                    if receipt.request != request or not receipt.simulated:
                        raise SchemaError("Executor receipt provenance mismatch")
                    await self.ledger.transition_operation(
                        op.operation_id, S.IN_FLIGHT, transport=T.IN_FLIGHT
                    )
                    await self._point(
                        "after_inflight_commit", self._op(op.operation_id)
                    )
                    if op.step_phase == "main":
                        await self._accept(self._op(op.operation_id), reg, clock)
                    await self._audit(op.operation_id, "issued", clock)
                    return request
                except BaseException:
                    possible = self._op(op.operation_id)
                    if possible.state in (S.ARMED, S.IN_FLIGHT):
                        try:
                            await self.ledger.transition_operation(
                                op.operation_id,
                                S.UNKNOWN,
                                transport=T.UNKNOWN,
                                reason="issue_boundary_uncertain",
                            )
                        except BaseException:
                            self.fault = "issue_commit_uncertain"
                    raise
        finally:
            self._running.discard(task)

    async def _accept(self, op, reg, clock):
        native = op.expected_native_value
        entity = json.loads(reg.batch.steps[op.step_index].target_json).get(
            "entity_id", ""
        )
        event = AcceptedCommand(
            "accepted:" + op.operation_id,
            self.ledger.plant_uid,
            reg.batch.evaluation_id,
            clock,
            reg.hbc_step
            if reg.lane == Lane.HBC
            else (
                "restore"
                if reg.maintenance_token
                else reg.proposal.policy.intent.action.value
            ),
            (
                AcceptedController(
                    op.operation_id,
                    op.controller_uid,
                    op.configuration_signature,
                    op.dispatch_id,
                    reg.before_w,
                    op.representable_controller_target_w,
                    entity,
                    native,
                ),
            ),
            0
            if reg.lane == Lane.HBC
            or (
                not reg.maintenance_token
                and reg.proposal.policy.intent.action.value == "none"
            )
            else reg.proposal.cooldown_seconds,
            lane=reg.lane.value,
            capture_token=reg.capture_token,
            owner_epoch=self.owner_epoch,
        )
        await self.runtime.event_recorder.record_simulated_acceptance(event)
        if op.lane == Lane.INVERTER:
            older = tuple(
                s.operation_id
                for s in self.current.settling
                if s.operation_id != op.operation_id
                and self._op(s.operation_id).controller_uid == op.controller_uid
            )
            if older:
                await self._journal(
                    lambda j: replace(
                        j,
                        superseded_settling_ids=tuple(
                            dict.fromkeys((*j.superseded_settling_ids, *older))
                        ),
                    )
                )

    async def _audit(self, op_id, kind, clock):
        await self._journal(
            lambda j: replace(
                j, history=(*j.history[-255:], AuditEvent(op_id, kind, clock))
            )
        )

    @owned_work
    async def receive_completion(self, completion):
        if self.closed:
            return False
        request = completion.request
        async with self._lanes[request.lane]:
            self._healthy()
            op = next(
                (
                    o
                    for o in self.ledger.current.operations
                    if o.operation_id == request.operation_id
                ),
                None,
            )
            if (
                op is None
                or request.owner_epoch != self.owner_epoch
                or (
                    op.owner_epoch,
                    op.dispatch_id,
                    op.controller_uid,
                    op.configuration_signature,
                )
                != (
                    request.owner_epoch,
                    request.dispatch_id,
                    request.controller_uid,
                    request.configuration_signature,
                )
                or op.state != S.IN_FLIGHT
            ):
                return False
            reg = self._reg(op.batch_id)
            if (
                request.step != reg.batch.steps[op.step_index]
                or completion.observed.age(request.issued) is None
            ):
                return False
            if completion.result != "success":
                state = (
                    S.SERVICE_FAILED
                    if completion.result == "transport_failure"
                    else S.UNKNOWN
                )
                transport = (
                    T.FAILED if completion.result == "transport_failure" else T.UNKNOWN
                )
                await self.ledger.transition_operation(
                    op.operation_id,
                    state,
                    transport=transport,
                    reason=completion.result,
                )
                await self._isolate(op.batch_id, op.step_index)
                await self._ensure_obligation(op, reg, completion.observed)
                await self._record_outcome(
                    op,
                    "service_failed"
                    if state == S.SERVICE_FAILED
                    else "outcome_unknown",
                    completion.observed,
                )
            else:
                await self.ledger.transition_operation(
                    op.operation_id,
                    S.SERVICE_COMPLETED,
                    transport=T.COMPLETED,
                    service_completed_at_utc=completion.observed.utc,
                )
                await self._point("after_service_completed", self._op(op.operation_id))
                state = (
                    S.AWAITING_VERIFICATION
                    if op.expected_native_value is not None
                    or op.step_phase == "main"
                    and not reg.open_loop
                    else S.OPEN_LOOP
                )
                await self.ledger.transition_operation(
                    op.operation_id,
                    state,
                    verification=V.PENDING
                    if state == S.AWAITING_VERIFICATION
                    else V.UNAVAILABLE,
                )
            await self._audit(op.operation_id, completion.result, completion.observed)
            return True

    async def drain_completions(self):
        return tuple(
            [await self.receive_completion(c) for c in self.executor.take_completions()]
        )

    async def _isolate(self, batch_id, after):
        for op in tuple(self.ledger.current.operations):
            if (
                op.batch_id == batch_id
                and op.step_index > after
                and op.state == S.PREPARED
            ):
                await self.ledger.transition_operation(
                    op.operation_id, S.SUPERSEDED, reason="earlier_sequence_step_failed"
                )

    async def _record_outcome(self, op, kind, clock):
        event = next(
            (
                e
                for e in self.runtime.event_recorder.current.events
                if any(c.operation_id == op.operation_id for c in e.controllers)
            ),
            None,
        )
        if event:
            await self.runtime.event_recorder.record_simulated_outcome(
                CommandOutcome(event.event_id, kind, clock)
            )

    @owned_work
    async def finalize_evidence(self, op_id, candidate, clock, *, final_failure=False):
        self._healthy()
        op = self._op(op_id)
        reg = self._reg(op.batch_id)
        if op.state != S.AWAITING_VERIFICATION:
            return None
        # A fresh sample after completed post-actions can confirm the main target.
        # An older generation cannot finalize through a different newer generation.
        newer = [
            o
            for o in self.ledger.current.operations
            if o.controller_uid == op.controller_uid
            and o.operation_id != op_id
            and o.dispatch_started_at_utc is not None
            and o.dispatch_started_at_utc > op.dispatch_started_at_utc
        ]
        if any(
            o.batch_id != op.batch_id
            or o.transport not in (T.COMPLETED, T.FAILED)
            or candidate.received_at_utc is None
            or candidate.received_at_utc < o.dispatch_started_at_utc
            or candidate.kind.value != "opendtu_api"
            and (
                candidate.reported_at_utc is None
                or candidate.reported_at_utc < o.dispatch_started_at_utc
            )
            for o in newer
        ):
            return None
        await self._point("before_verification", op)
        verdict = verify_operation(
            op,
            candidate,
            now=clock.utc,
            full_power_w=reg.full_w,
            step_w=reg.step_w,
            expected_device_id=reg.device_id,
            expected_serial=reg.serial,
        )
        if verdict.outcome == VerificationOutcome.CONFIRMED:
            await self._verified(op, verdict.evidence, clock)
        elif final_failure and verdict.outcome == VerificationOutcome.VALUE_MISMATCH:
            await self.ledger.transition_operation(
                op_id,
                S.VERIFICATION_FAILED,
                verification=V.FAILED,
                reason=verdict.reason,
            )
            await self._isolate(op.batch_id, op.step_index)
            await self._ensure_obligation(op, reg, clock)
            await self._record_outcome(op, "verification_failed", clock)
        return verdict

    @owned_work
    async def observe_native(self, observation, clock):
        self._healthy()
        op = self._op(observation.operation_id)
        if op.state != S.AWAITING_VERIFICATION or op.expected_native_value is None:
            return False
        reg = self._reg(op.batch_id)
        step = reg.batch.steps[op.step_index]
        entity = json.loads(step.target_json).get("entity_id")
        if (
            observation.controller_uid,
            observation.configuration_signature,
            observation.owner_epoch,
            observation.dispatch_id,
        ) != (
            op.controller_uid,
            op.configuration_signature,
            op.owner_epoch,
            op.dispatch_id,
        ):
            return False
        if (
            observation.entity_id != entity
            or observation.state != op.expected_native_value
            or not (
                op.dispatch_started_at_utc
                <= observation.reported_at_utc
                <= clock.utc + 60
                and op.dispatch_started_at_utc
                <= observation.received_at_utc
                <= clock.utc + 60
                and clock.utc - observation.reported_at_utc <= 180
            )
        ):
            return False
        proof = VerificationEvidence(
            "native:" + op.operation_id + ":" + str(observation.received_at_utc),
            op.controller_uid,
            op.configuration_signature,
            op.operation_id,
            "independent_native_state",
            V.VERIFIED,
            reported_at_utc=observation.reported_at_utc,
            received_at_utc=observation.received_at_utc,
            provenance="owner=" + op.owner_epoch + ";dispatch=" + str(op.dispatch_id),
            observed_native_value=observation.state,
        )
        await self._verified(op, proof, clock)
        return True

    async def _verified(self, op, proof, clock):
        reg = self._reg(op.batch_id)
        await self.ledger.add_evidence(proof)
        if op.lane == Lane.INVERTER and op.step_phase == "main":
            state = SettlingState(
                op.operation_id,
                op.dispatch_started_at_utc,
                reg.before_w or 0,
                op.representable_controller_target_w,
                reg.pv_before_w,
                reg.proposal.clock.utc,
            )
            await self._journal(lambda j: replace(j, settling=(*j.settling, state)))
        await self.ledger.transition_operation(
            op.operation_id,
            S.VERIFIED,
            verification=V.VERIFIED,
            evidence_ids=(proof.evidence_id,),
        )
        await self._record_outcome(op, "verified", clock)
        await self._point("after_verification", self._op(op.operation_id))
        if op.lane != Lane.INVERTER or op.step_phase != "main":
            await self.ledger.transition_operation(op.operation_id, S.RETIRED)
        await self._audit(op.operation_id, "independently_verified", clock)

    @owned_work
    async def observe_pv(self, op_id, pv, clock):
        self._healthy()
        op = self._op(op_id)
        state = next(s for s in self.current.settling if s.operation_id == op_id)
        event = next(
            (
                e
                for e in self.runtime.event_recorder.current.events
                if any(c.operation_id == op_id for c in e.controllers)
            ),
            None,
        )
        elapsed = clock.age(event.accepted) if event else None
        now = clock.utc
        observed = pv
        if elapsed is not None:
            now = event.accepted.utc + elapsed
            shift = clock.utc - now
            observed = replace(
                pv,
                reported_at_utc=pv.reported_at_utc - shift
                if pv.reported_at_utc is not None
                else None,
                received_at_utc=pv.received_at_utc - shift
                if pv.received_at_utc is not None
                else None,
            )
        result = observe_settling(
            state,
            operation_id=op_id,
            limit_confirmed=op.state in (S.VERIFIED, S.RETIRED),
            pv=observed,
            now=now,
        )
        if elapsed is None and result.outcome == SettlingOutcome.TIMED_OUT:
            result = replace(
                result, outcome=SettlingOutcome.UNKNOWN, hold_ordinary_reversal=True
            )
        if op_id in self.current.superseded_settling_ids:
            return replace(
                result, outcome=SettlingOutcome.UNKNOWN, hold_ordinary_reversal=False
            )
        if result.outcome == SettlingOutcome.APPLIED:
            await self._journal(
                lambda j: replace(
                    j,
                    settled_operation_ids=tuple(
                        dict.fromkeys((*j.settled_operation_ids, op_id))
                    ),
                )
            )
        await self._journal(
            lambda j: replace(
                j,
                settling=tuple(
                    result.state if s.operation_id == op_id else s for s in j.settling
                ),
            )
        )
        self.settling_results[op_id] = result
        if result.outcome == SettlingOutcome.APPLIED and op.state == S.VERIFIED:
            await self.ledger.transition_operation(op_id, S.RETIRED)
        return result

    async def close(self):
        if self.closed:
            return
        self.closed = True
        active = [t for t in self._running if t is not asyncio.current_task()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        for op in tuple(self.ledger.current.operations):
            if op.owner_epoch == self.owner_epoch and op.state in (
                S.ARMED,
                S.IN_FLIGHT,
            ):
                try:
                    await self.ledger.transition_operation(
                        op.operation_id,
                        S.UNKNOWN,
                        transport=T.UNKNOWN,
                        reason="fake_dispatcher_unloaded",
                    )
                except Exception:
                    self.fault = "unload_commit_failed"
        if self.store.healthy and self.ledger.store.healthy:
            await self._reconstruct_obligations()
        self.runtime.event_recorder.plan_validator = self._old_validator
        if getattr(self.ledger, "_dispatcher", None) is self:
            self.ledger._dispatcher = None

    async def _ensure_obligation(self, op, reg, clock):
        if op.lane != Lane.INVERTER or any(
            op.operation_id in o.operation_ids
            for o in self.ledger.current.restore_obligations
        ):
            return
        obligation = RestoreObligation(
            "restore:" + op.operation_id,
            op.controller_uid,
            op.configuration_signature,
            op.configuration_reference,
            "unresolved_simulated_operation",
            reg.full_w,
            operation_ids=(op.operation_id,),
            established_at_utc=clock.utc,
            owner_epoch=op.owner_epoch,
        )
        await self.ledger.update(
            lambda l: replace(
                l, restore_obligations=(*l.restore_obligations, obligation)
            )
        )

    async def _reconstruct_obligations(self):
        for op in tuple(self.ledger.current.operations):
            if op.state not in (S.PREPARED, S.SUPERSEDED, S.VERIFIED, S.RETIRED):
                try:
                    reg = self._reg(op.batch_id)
                except StopIteration:
                    continue
                await self._ensure_obligation(
                    op,
                    reg,
                    Clock(max(op.dispatch_started_at_utc or 1, 1), 0, self.owner_epoch),
                )

    @owned_work
    async def submit_restoration(self, views, clock, owner_token):
        from ..control.engine import _adapter
        from ..execution.models import MaintenanceState

        m = self.ledger.current.maintenance
        if (
            m.owner_token != owner_token
            or m.state not in (MaintenanceState.RESTORING, MaintenanceState.VERIFYING)
            or not m.post_disable_evaluation_id
        ):
            raise SchemaError("Maintenance has no post-disable restoration authority")
        proposal = self.runtime.last_proposal
        if proposal is None or proposal.enabled_intent:
            raise SchemaError("Restoration requires accepted disabled observation")
        self.update_identities(views)
        ids = []
        for view in views:
            uid = view.configuration.identity.uid
            sig = view.configuration_signature
            obligation = next(
                (
                    o
                    for o in self.ledger.current.restore_obligations
                    if o.controller_uid == uid
                    and o.configuration_signature == sig
                    and o.state != ObligationState.VERIFIED
                ),
                None,
            )
            if obligation is None or not view.available:
                continue
            if obligation.required_target_w != view.operating_range.full_w:
                raise SchemaError(
                    "Replacement range cannot discharge an archived obligation"
                )
            target = _adapter(view).represent(view, view.operating_range.full_w)
            batch = _adapter(view).build_plan(
                view,
                target,
                batch_id=m.transaction_id
                + ":"
                + proposal.policy.intent.evaluation_id
                + ":"
                + uid,
                evaluation_id=proposal.policy.intent.evaluation_id,
                requested_plant_target_w=view.operating_range.full_w,
            )
            reg = Registration(
                batch,
                proposal,
                Lane.INVERTER,
                self.owner_epoch,
                obligation.configuration_reference,
                view.configuration.identity.adapter.value,
                view.operating_range.full_w,
                view.observation.limit.value,
                proposal.pv_before_w,
                view.capabilities.step or 0,
                not view.supports_verification,
                view.candidate.device_id if view.candidate else None,
                view.candidate.serial if view.candidate else None,
                maintenance_token=owner_token,
            )
            ids.append(await self._register(reg, clock))
        return tuple(ids)

    def settling_restriction(self):
        for state in self.current.settling:
            if (
                state.operation_id in self.current.settled_operation_ids
                or state.operation_id in self.current.superseded_settling_ids
            ):
                continue
            result = self.settling_results.get(state.operation_id)
            if result is None:
                return SettlingResult(state, SettlingOutcome.UNKNOWN, True)
            if result.outcome in (SettlingOutcome.WAITING, SettlingOutcome.UNKNOWN):
                return result
        return next(
            (
                r
                for r in self.settling_results.values()
                if r.outcome == SettlingOutcome.TIMED_OUT
            ),
            None,
        )

    def execution_snapshot(self, controllers, clock):
        return build_execution_snapshot(
            self.ledger.current,
            controllers,
            clock,
            self.runtime.event_recorder.current,
            settling=self.settling_restriction(),
        )

    async def reconcile_quiescence(self, receipt):
        self._healthy()
        if type(receipt) is not QuiescenceReceipt:
            raise SchemaError("Independent fake executor receipt required")
        r = receipt.request
        op = self._op(r.operation_id)
        if op.state != S.UNKNOWN or (
            op.dispatch_id,
            op.owner_epoch,
            op.controller_uid,
            op.configuration_signature,
        ) != (
            r.dispatch_id,
            r.owner_epoch,
            r.controller_uid,
            r.configuration_signature,
        ):
            return False
        if receipt.observed.utc < op.dispatch_started_at_utc:
            return False
        await self.ledger.transition_operation(
            op.operation_id,
            S.RECOVERY_REQUIRED,
            transport=T.COMPLETED
            if receipt.transport_result == "completed"
            else T.FAILED,
            reason="transport_quiescent_physical_proof_still_required",
        )
        return True

    async def resume_verification(self, op_id):
        op = self._op(op_id)
        if op.state != S.RECOVERY_REQUIRED or op.transport != T.COMPLETED:
            raise SchemaError("Verification requires proven completed transport")
        await self.ledger.transition_operation(
            op_id, S.AWAITING_VERIFICATION, verification=V.PENDING
        )
