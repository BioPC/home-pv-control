"""Caller-side policy memory acceptance/persistence, without any actuator capability."""

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from .codec import Record, SchemaError
from .storage import StorageError, VersionedStore
from .control.decisions import PolicyMemory, PolicyResult
from .control.engine import evaluate as evaluate_policy
from .control.night_restore import after_restart as restart_policy
from .hbc.state import (
    Clock,
    HbcMemory,
    HbcSnapshot,
    HbcResult,
    RawEntity,
    AcceptedOverrideStep,
    OverrideMemory,
)
from .hbc.evaluator import evaluate as evaluate_hbc, after_restart as restart_hbc
from .hbc.learning import probe_from_accepted
from .execution.facts import ExecutionFacts, SimulatedEventRecorder
from .execution.snapshot import build_execution_snapshot
from .inverter.base import fingerprint, finite


@dataclass(frozen=True)
class RuntimeMemoryState(Record):
    plant_uid: str
    generation: int = 0
    policy: PolicyMemory = field(default_factory=PolicyMemory)
    hbc: HbcMemory = field(default_factory=HbcMemory)
    last_clock: Clock | None = None
    applied_probe_event_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            not self.plant_uid
            or type(self.generation) is not int
            or self.generation < 0
            or len(self.applied_probe_event_ids) > 128
        ):
            raise SchemaError("Invalid runtime policy memory")


@dataclass(frozen=True)
class EvaluationProposal(Record):
    base_generation: int
    ledger_revision: int
    facts_revision: int
    clock: Clock
    policy: PolicyResult
    hbc: HbcResult
    applied_probe_event_ids: tuple[str, ...]
    source_digest: str
    cooldown_seconds: float = 30.0


def align_policy(memory, last_clock, clock):
    if last_clock is None:
        return memory
    elapsed = clock.age(last_clock)
    if elapsed is None:
        raise SchemaError("Policy observation continuity lost; reload runtime memory")
    shift = clock.utc - last_clock.utc - elapsed
    night = memory.night
    shifted = lambda value: value + shift if value is not None else None
    return replace(
        memory,
        night=replace(
            night,
            entry_candidate_since_utc=shifted(night.entry_candidate_since_utc),
            recovery_candidate_since_utc=shifted(night.recovery_candidate_since_utc),
        ),
        release_requested_since_utc=shifted(memory.release_requested_since_utc),
    )


class PolicyRuntimeAdapter:
    def __init__(self, prefix, plant_uid, ledger):
        self.plant_uid = plant_uid
        self.ledger = ledger
        self.store = VersionedStore(
            prefix.with_name(prefix.name + "_policy.json"),
            "policy_memory",
            RuntimeMemoryState,
        )
        self.event_recorder = SimulatedEventRecorder(
            VersionedStore(
                prefix.with_name(prefix.name + "_accepted_commands.json"),
                "accepted_commands",
                ExecutionFacts,
            ),
            plant_uid,
            ledger,
        )
        self.accepted = RuntimeMemoryState(plant_uid)
        self.durable = self.accepted
        self.last_proposal = None
        self.fault = None
        self._lock = asyncio.Lock()
        self.event_recorder.guard = self._lock
        self.event_recorder.plan_validator = self._validate_simulated_plan
        self.closed = False

    def _validate_simulated_plan(self, event):
        proposal = self.last_proposal
        if (
            proposal is None
            or event.evaluation_id != proposal.policy.intent.evaluation_id
        ):
            raise SchemaError(
                "Simulated event has no matching accepted policy proposal"
            )
        if (
            event.accepted.boot_id != proposal.clock.boot_id
            or event.accepted.age(proposal.clock) is None
        ):
            raise SchemaError(
                "Accepted event predates evaluation or lost runtime continuity"
            )
        if event.lane == "inverter":
            represented = proposal.policy.represented
            if (
                represented is None
                or proposal.policy.intent.blocked
                or proposal.policy.allocation.blocked
            ):
                raise SchemaError("No eligible represented plan exists")
            if event.action != proposal.policy.intent.action.value:
                raise SchemaError("Accepted command action differs from policy intent")
            if (
                event.action == "none"
                and not proposal.policy.allocation.rebalance_applied
            ):
                raise SchemaError("A hold is not an accepted inverter command")
            expected = {
                target.controller_uid: target.representable_target_w
                for target in represented.targets
            }
            if any(
                expected.get(c.controller_uid) != c.target_w for c in event.controllers
            ):
                raise SchemaError(
                    "Accepted command differs from represented controller plan"
                )
            duration = proposal.cooldown_seconds if event.action != "none" else 0.0
            if event.cooldown_seconds != duration:
                raise SchemaError(
                    "Accepted cooldown duration differs from source policy"
                )
        else:
            intents = proposal.hbc.override.actions
            for item in event.controllers:
                intent = next(
                    (
                        a
                        for a in intents
                        if a.step == event.action and a.entity_id == item.entity_id
                    ),
                    None,
                )
                target = (
                    intent.option
                    if intent and intent.option is not None
                    else intent.data_json
                    if intent
                    else None
                )
                if intent is None or target != item.native_target:
                    raise SchemaError(
                        "Accepted HBC event differs from ordered intent data"
                    )
                if intent.capture_token != event.capture_token:
                    raise SchemaError("Accepted HBC capture identity mismatch")
                if (
                    intent.requires_durable_capture
                    and self.durable.hbc.override.capture_token != event.capture_token
                ):
                    raise SchemaError(
                        "Original HBC capture must be durable before simulated forcing"
                    )

    async def load(self, clock):
        value = await self.store.load()
        facts = await self.event_recorder.load(clock)
        if (value is None) != (facts is None):
            raise StorageError(
                "Policy/execution-fact companion store missing; refusing invented continuity"
            )
        if value is not None and value.plant_uid != self.plant_uid:
            raise StorageError("Policy memory belongs to another plant")
        if value is None:
            policy = PolicyMemory(night=self.ledger.current.night_restore)
            override = self.ledger.current.hbc_override
            hbc = HbcMemory(boot_id=clock.boot_id)
            if override.phase.value != "inactive":
                hbc = replace(
                    hbc,
                    override=OverrideMemory(
                        phase="recovery_unknown_previous",
                        phase_since=clock,
                        previous_strategy=override.saved_strategy,
                        previous_goal=override.saved_charge_goal,
                        forced_write_issued=override.forced_write_issued is not False,
                        fault=True,
                    ),
                )
            value = RuntimeMemoryState(
                self.plant_uid, policy=policy, hbc=hbc, last_clock=clock
            )
            await self.event_recorder.store.commit(self.event_recorder.current, 0)
            await self.store.commit(value, 0)
        restarted = replace(
            restart_policy(value.policy), release_requested_since_utc=None
        )
        value = replace(
            value,
            generation=value.generation + 1,
            policy=restarted,
            hbc=restart_hbc(value.hbc, clock),
            last_clock=clock,
        )
        # Only accepted policy state is stored here. No accepted command is invented.
        await self.store.commit(value, self.store.revision)
        self.accepted = value
        self.durable = value
        self.fault = None
        return value

    def propose(
        self,
        policy,
        entities,
        clock,
        *,
        views=(),
        settling=None,
        permission=False,
        negative_charge_permission=True,
        acknowledge_unknown_override=False,
    ):
        if self.closed or self.fault or not self.store.healthy:
            raise StorageError("Policy memory unavailable/requires recovery")
        ledger = self.ledger.current
        facts = self.event_recorder.current
        if policy.now != clock.utc:
            raise SchemaError("Policy and runtime clock mismatch")
        accepted = self.accepted
        memory = align_policy(accepted.policy, accepted.last_clock, clock)
        hbc_memory = accepted.hbc
        applied = accepted.applied_probe_event_ids
        release = facts.last_release
        # Probe creation comes only from a ledger-bound simulated accepted event.
        if (
            release
            and release.event_id not in applied
            and self.last_proposal is not None
            and self.last_proposal.policy.intent.evaluation_id == release.evaluation_id
        ):
            step = sum(
                max(0, c.target_w - (c.before_w or 0))
                for c in release.controllers
                if c.target_w is not None
            )
            probe = probe_from_accepted(
                release.event_id,
                release.accepted,
                step,
                policy.grid.value or 0,
                self.last_proposal.hbc.batteries,
            )
            hbc_memory = replace(hbc_memory, pending_probe=probe)
            applied = (*applied, release.event_id)
        override_events = [
            e
            for e in facts.events
            if e.lane == "hbc_override"
            and e.capture_token == hbc_memory.override.capture_token
        ]
        accepted_steps = tuple(
            AcceptedOverrideStep(e.action, e.accepted, e.capture_token)
            for e in override_events
        )
        last = facts.last_inverter
        failed = bool(
            last
            and any(
                o.event_id == last.event_id
                and o.kind
                in ("service_failed", "verification_failed", "outcome_unknown")
                for o in facts.outcomes
            )
        )
        delta = (
            sum(
                c.target_w - (c.before_w if c.before_w is not None else c.target_w)
                for c in last.controllers
            )
            if last
            else None
        )
        hbc_snapshot = HbcSnapshot(
            replace(policy, memory=memory),
            clock,
            tuple(entities),
            hbc_memory,
            permission,
            negative_charge_permission,
            durable_capture_token=self.durable.hbc.override.capture_token or None,
            accepted_override_token=hbc_memory.override.capture_token
            if override_events
            else None,
            accepted_override_steps=tuple(e.action for e in override_events),
            accepted_override_events=accepted_steps,
            acknowledge_unknown_override=bool(
                acknowledge_unknown_override
                or (
                    hbc_memory.override.fault_published
                    and any(
                        e.entity_id == "input_boolean.hpvc_negative_override_fault"
                        and e.state == "off"
                        for e in entities
                    )
                )
            ),
            last_release=release.accepted if release else None,
            last_command_delta_w=delta,
            last_command=last.accepted if last else None,
            last_command_failed=failed,
        )
        hbc = evaluate_hbc(hbc_snapshot)
        execution = build_execution_snapshot(
            ledger,
            policy.controllers,
            clock,
            facts,
            settling=settling,
            boot_clock=self.event_recorder.boot_clock,
            hbc_restore_pending=hbc.override.minimum_lock
            and hbc.override.memory.phase != "inactive",
            override_recovery=hbc.override.recovery_required,
        )
        policy_result = evaluate_policy(
            replace(policy, memory=memory, hbc=hbc.resolved, execution=execution),
            views=views,
        )
        digest = fingerprint(
            [
                accepted.generation,
                ledger.revision,
                self.event_recorder.store.revision,
                policy.to_dict(),
                [e.to_dict() for e in entities],
            ]
        )
        return EvaluationProposal(
            accepted.generation,
            ledger.revision,
            self.event_recorder.store.revision,
            clock,
            policy_result,
            hbc,
            applied,
            digest,
            policy.settings.cooldown_seconds,
        )

    async def accept_proposal(self, proposal, *, durable=True):
        async with self._lock:
            if self.closed or self.fault:
                raise StorageError("Policy runtime closed/faulted")
            if (
                proposal.base_generation != self.accepted.generation
                or proposal.ledger_revision != self.ledger.current.revision
                or proposal.facts_revision != self.event_recorder.store.revision
            ):
                raise SchemaError("Stale policy proposal or execution snapshot")
            override = proposal.hbc.memory.override
            facts = self.event_recorder.current
            issued = any(
                e.lane == "hbc_override"
                and e.capture_token == override.capture_token
                and e.action in ("enter_strategy", "enter_goal")
                for e in facts.events
            )
            if (
                override.forced_write_issued
                and not issued
                and self.ledger.current.hbc_override.phase.value == "inactive"
            ):
                raise SchemaError("Policy cannot invent an issued HBC command")
            probe = proposal.hbc.memory.pending_probe
            if probe and probe.accepted_event_id not in {
                e.event_id for e in facts.events
            }:
                raise SchemaError("Policy cannot invent a physical taper probe")
            value = RuntimeMemoryState(
                self.plant_uid,
                self.accepted.generation + 1,
                proposal.policy.memory,
                proposal.hbc.memory,
                proposal.clock,
                proposal.applied_probe_event_ids,
            )
            if durable:
                try:
                    await self.store.commit(value, self.store.revision)
                except Exception:
                    self.fault = "policy_memory_commit_failed"
                    raise
                self.durable = value
            self.accepted = value
            self.last_proposal = proposal
            return value

    async def evaluate_readonly(self, policy, entities, clock, **kwargs):
        proposal = self.propose(policy, entities, clock, **kwargs)
        await self.accept_proposal(proposal)
        return proposal

    def close(self):
        self.closed = True


HEARTBEATS = (
    "last_seen",
    "lastSeen",
    "last_update",
    "lastUpdate",
    "updated_at",
    "updatedAt",
    "timestamp",
    "device_timestamp",
    "deviceTimestamp",
    "heartbeat",
    "last_communication",
    "lastCommunication",
    "last_received",
    "lastReceived",
)


def capture_entities(reader):
    names = [
        "input_select.house_battery_strategy",
        "input_select.house_battery_strategy_charge_goal",
        "input_text.house_battery_strategy_active_sub_strategy",
        "input_number.house_battery_count",
        "input_number.house_battery_control_prioritize_battery",
        "input_select.house_battery_control_priority_change_interval",
        "input_boolean.hpvc_negative_override_fault",
    ]
    for i in range(1, 7):
        names.extend(
            (
                f"sensor.marstek_m{i}_ac_power",
                f"sensor.marstek_m{i}_battery_state_of_charge",
                f"input_number.marstek_m{i}_charging_cutoff_capacity",
                f"input_number.marstek_m{i}_discharging_cutoff_capacity",
                f"select.marstek_m{i}_rs485_control_mode",
                f"number.marstek_m{i}_max_charge_power",
            )
        )
    result = []
    for name in names:
        state = reader(name)
        if state is None:
            continue
        attrs = getattr(state, "attributes", {}) or {}
        heartbeat = []
        for key in HEARTBEATS:
            if key not in attrs:
                continue
            raw = attrs[key]
            number = finite(raw)
            if number is not None and number > 1e9:
                heartbeat.append(number / 1000 if number > 1e12 else number)
                continue
            if isinstance(raw, str):
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    parsed = (
                        parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                    )
                    heartbeat.append(parsed.timestamp())
                except ValueError:
                    pass
        stamp = getattr(state, "last_updated", None)
        result.append(
            RawEntity(
                name,
                str(state.state) if state.state is not None else None,
                stamp.timestamp() if stamp is not None else None,
                max(heartbeat) if heartbeat else None,
                tuple(str(o) for o in attrs.get("options", ())),
            )
        )
    return tuple(result)
