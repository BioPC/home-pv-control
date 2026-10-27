"""Entry-owned scheduler and configuration publication; no actuator services."""

from __future__ import annotations
import asyncio
from dataclasses import replace
import logging
import math
import time
import uuid
from .const import (
    MAIN_INTERVAL,
    STARTUP_DELAY,
    FORCED_FULL_INTERVAL,
)
from .codec import SchemaError
from .control.models import PlantSnapshot, Observation, Quality

from .inverter.manager import InverterManager
from .inverter.hoymiles import async_read_status, parse_status
from .execution.verification import (
    verify_operation,
    readback_candidate,
    opendtu_candidate,
    VerificationOutcome,
)
from .execution.recovery import assess_recovery

_LOGGER = logging.getLogger(__name__)


class LifecycleOwner:
    """Own arbitrary listeners/timers/workers, including future HTTP/report work."""

    def __init__(self, task_factory=None):
        self.closed = False
        self.tasks = set()
        self.cleanups = []
        self.async_cleanups = []
        self.task_factory = task_factory or (
            lambda coro, name: asyncio.create_task(coro, name=name)
        )

    def create_task(self, coro, name):
        if self.closed:
            coro.close()
            raise RuntimeError("Entry runtime is closed")
        task = self.task_factory(coro, name)
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            if not finished.cancelled() and finished.exception():
                _LOGGER.error("HPVC owned task failed: %s", finished.exception())

        task.add_done_callback(done)
        return task

    def add_cleanup(self, callback):
        if self.closed:
            callback()
            raise RuntimeError("Entry runtime is closed")
        self.cleanups.append(callback)
        return callback

    def add_async_cleanup(self, callback):
        if self.closed:
            raise RuntimeError("Entry runtime is closed")
        self.async_cleanups.append(callback)
        return callback

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for cleanup in reversed(self.cleanups):
            try:
                cleanup()
            except Exception:
                _LOGGER.exception("HPVC listener/timer cleanup failed")
        self.cleanups.clear()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        for cleanup in reversed(self.async_cleanups):
            try:
                await cleanup()
            except Exception:
                _LOGGER.exception("HPVC async cleanup failed")
        self.async_cleanups.clear()


class EvaluationScheduler:
    """One worker, two bounded flags. Telemetry never schedules immediate evaluation."""

    def __init__(
        self,
        owner,
        refresh,
        evaluate,
        significant,
        pending_work,
        *,
        clock=None,
        main_interval=MAIN_INTERVAL,
        startup_delay=STARTUP_DELAY,
        forced_interval=FORCED_FULL_INTERVAL,
    ):
        self.owner = owner
        self.refresh = refresh
        self.evaluate = evaluate
        self.significant = significant
        self.pending_work = pending_work
        self.clock = clock or asyncio.get_running_loop().time
        self.main_interval = main_interval
        self.startup_delay = startup_delay
        self.forced_interval = forced_interval
        self.ready = False
        self.settings_pending = False
        self.tick_pending = False
        self.telemetry_dirty = False
        self.event = asyncio.Event()
        self.last_full = None
        self.baseline = None
        self.full_evaluations = 0
        self.skipped_evaluations = 0
        self._handles = []

    def start(self):
        loop = asyncio.get_running_loop()
        self._handles = [
            loop.call_later(self.startup_delay, self.startup_wake),
            loop.call_later(self.main_interval, self._timer),
        ]
        self.owner.add_cleanup(self._cancel_timers)
        self.owner.create_task(self._worker(), "hpvc-evaluation-worker")

    def _cancel_timers(self):
        for handle in self._handles:
            handle.cancel()
        self._handles.clear()

    def _timer(self):
        if self.owner.closed:
            return
        self.timer_wake()
        # Keep only the current startup and periodic timer handles, never a per-tick history.
        self._handles = [
            handle
            for handle in self._handles
            if not handle.cancelled()
            and handle.when() > asyncio.get_running_loop().time()
        ]
        self._handles.append(
            asyncio.get_running_loop().call_later(self.main_interval, self._timer)
        )

    def startup_wake(self):
        if self.owner.closed:
            return
        self.ready = True
        self.settings_pending = True
        self.event.set()

    def timer_wake(self):
        if self.owner.closed:
            return
        self.tick_pending = True
        self.event.set()

    def mark_telemetry_dirty(self):
        if not self.owner.closed:
            self.telemetry_dirty = True

    def request_settings(self):
        if self.owner.closed:
            return
        self.settings_pending = True
        self.event.set()

    async def _worker(self):
        while True:
            await self.event.wait()
            self.event.clear()
            if not self.ready:
                continue
            settings = self.settings_pending
            tick = self.tick_pending
            self.settings_pending = False
            self.tick_pending = False
            self.telemetry_dirty = False
            if not (settings or tick):
                continue
            try:
                snapshot = await self.refresh()
                now = self.clock()
                full = (
                    settings
                    or self.last_full is None
                    or now - self.last_full >= self.forced_interval
                    or self.pending_work()
                    or self.significant(snapshot, self.baseline)
                )
                if full:
                    await self.evaluate(snapshot)
                    self.baseline = snapshot
                    self.last_full = now
                    self.full_evaluations += 1
                else:
                    self.skipped_evaluations += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "HPVC foundation evaluation failed; no actuator capability exists"
                )


class HpvcCoordinator:
    def __init__(
        self,
        config_store,
        history_store,
        ledger,
        configuration_state,
        owner,
        state_reader=None,
        *,
        states_snapshot_reader=None,
        registry_reader=None,
        http_session_factory=None,
        policy_runtime=None,
    ):
        self.config_store = config_store
        self.history_store = history_store
        self.ledger = ledger
        self.state = configuration_state
        self.owner = owner
        self.state_reader = state_reader or (lambda entity: None)
        self._config_lock = asyncio.Lock()
        self.listeners = set()
        self.snapshot = None
        self.scheduler = EvaluationScheduler(
            owner,
            self.refresh,
            self.evaluate,
            self.significant,
            lambda: self.ledger.recovery_required,
        )
        self.storage_fault = None
        self.manager = InverterManager()
        self.states_snapshot_reader = states_snapshot_reader
        self.registry_reader = registry_reader
        self.http_session_factory = http_session_factory
        self.readonly_states = ()
        self.readonly_faults = ()
        self.verification_results = ()
        self.registry_refreshed_at_utc = None
        self.policy_runtime = policy_runtime
        self.policy_proposal = None

    @property
    def configuration(self):
        return self.state.configuration

    @property
    def physical_writes_authorized(self):
        return False

    @property
    def migration_state(self):
        if any(
            item.stage.value == "config_committed_handoff_pending"
            for item in self.state.imports
        ):
            return "handoff_pending"
        return self.ledger.current.ownership.state.value

    @property
    def recovery_required(self):
        return bool(
            self.storage_fault
            or self.ledger.recovery_required
            or (self.policy_runtime and self.policy_runtime.fault)
            or (
                self.policy_proposal
                and self.policy_proposal.hbc.override.recovery_required
            )
        )

    @property
    def required_inputs_ready(self):
        return False  # The final control engine and ownership cutover remain disabled.

    def add_listener(self, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def publish(self):
        for callback in tuple(self.listeners):
            callback()

    def start(self):
        self.scheduler.start()
        if self.states_snapshot_reader and self.registry_reader:
            self.owner.create_task(
                self._registry_worker(), "hpvc-readonly-registry-worker"
            )
        if self.http_session_factory:
            self.owner.create_task(
                self._opendtu_worker(), "hpvc-readonly-opendtu-worker"
            )

    async def _registry_worker(self):
        await asyncio.sleep(2)
        while not self.owner.closed:
            try:
                await self.refresh_fleet(registry=True)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.readonly_faults = (
                    *self.readonly_faults,
                    "registry: " + str(error),
                )[-32:]
            await asyncio.sleep(60)

    async def _opendtu_worker(self):
        await asyncio.sleep(8)
        while not self.owner.closed:
            await self.poll_opendtu_status()
            await asyncio.sleep(30)

    async def poll_opendtu_status(self):
        if not self.http_session_factory or self.owner.closed:
            return
        groups = {}
        for row in self.manager.current.effective:
            candidate = row.view.candidate
            if (
                candidate
                and candidate.kind == "hoymiles"
                and candidate.configuration_url
            ):
                groups.setdefault(candidate.configuration_url, []).append(candidate)
        for url, candidates in groups.items():
            if self.owner.closed:
                return
            polled = time.time()
            try:
                payload = await async_read_status(self.http_session_factory(), url)
                records = parse_status(
                    payload,
                    tuple(candidates),
                    poll_started_at_utc=polled,
                    received_at_utc=time.time(),
                )
                for record in records:
                    self.manager.status_cache.accept(record)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.readonly_faults = (
                    *self.readonly_faults,
                    "OpenDTU read-only status: " + str(error),
                )[-32:]
        if groups:
            await self.refresh_fleet()

    async def refresh_fleet(self, *, registry=False):
        if self.owner.closed or not self.states_snapshot_reader:
            return self.manager.current
        registry_rows = devices = None
        if registry and self.registry_reader:
            registry_rows, devices = self.registry_reader()
            self.registry_refreshed_at_utc = time.time()
        self.readonly_states = tuple(self.states_snapshot_reader(registry))
        fleet = self.manager.refresh(
            self.configuration,
            self.readonly_states,
            registry_rows,
            devices,
            now=time.time(),
        )
        outcomes = []
        for operation in self.ledger.current.operations:
            row = next(
                (
                    item
                    for item in fleet.effective
                    if item.uid == operation.controller_uid
                ),
                None,
            )
            if row is None:
                continue
            view = row.view
            step = view.capabilities.step
            if step is not None and view.configuration.unit.value == "Percent":
                step = step / 100 * view.operating_range.full_w
            result = verify_operation(
                operation,
                readback_candidate(operation, view),
                now=time.time(),
                full_power_w=view.operating_range.full_w,
                step_w=step,
                deadband_w=self.configuration.settings.pv_adjust_deadband,
            )
            status = self.manager.status_cache.status.get(row.uid)
            if status and result.outcome != VerificationOutcome.CONFIRMED:
                candidate = view.candidate
                api = verify_operation(
                    operation,
                    opendtu_candidate(operation, view, status),
                    now=time.time(),
                    full_power_w=view.operating_range.full_w,
                    step_w=step,
                    expected_device_id=candidate.device_id if candidate else None,
                    expected_serial=candidate.serial if candidate else None,
                    deadband_w=self.configuration.settings.pv_adjust_deadband,
                )
                if api.outcome == VerificationOutcome.CONFIRMED:
                    result = api
            outcomes.append((operation.operation_id, result))
        self.verification_results = tuple(outcomes)
        # Evidence is diagnostic only. Unknown execution occupancy is NOT cleared.
        self.publish()
        return fleet

    @property
    def recovery_assessment(self):
        return assess_recovery(self.ledger.current)

    async def refresh(self):
        await self.refresh_fleet()

        observations = []
        for role in (
            "grid_power_sensor",
            "pv_power_sensor",
            "market_price_sensor",
            "all_in_price_sensor",
        ):
            entity = getattr(self.configuration, role)
            raw = self.state_reader(entity) if entity else None
            value = None
            quality = Quality.UNKNOWN
            if raw is not None:
                try:
                    value = float(raw.state)
                    quality = Quality.VALID if math.isfinite(value) else Quality.INVALID
                    if not math.isfinite(value):
                        value = None
                except (ValueError, TypeError):
                    quality = Quality.UNAVAILABLE
            reported = getattr(raw, "last_reported", None)
            timestamp = reported.timestamp() if reported is not None else None
            now = time.time()
            if quality == Quality.VALID:
                ttl = (
                    7200
                    if role in ("market_price_sensor", "all_in_price_sensor")
                    else 180
                )
                if timestamp is None or timestamp > now + 60 or now - timestamp > ttl:
                    quality = Quality.STALE
            observations.append(Observation(role, value, quality, timestamp, now))
        return PlantSnapshot(
            uuid.uuid4().hex,
            time.time(),
            self.configuration.revision,
            tuple(observations),
        )

    @staticmethod
    def significant(current, previous):
        if (
            previous is None
            or current.configuration_revision != previous.configuration_revision
        ):
            return True
        for a, b in zip(current.observations, previous.observations):
            if a.quality != b.quality or (a.value is None) != (b.value is None):
                return True
            if a.value is None:
                continue
            if a.source in ("grid_power_sensor", "pv_power_sensor"):
                delta = abs(a.value - b.value)
                percent = (
                    delta / abs(b.value) * 100
                    if abs(b.value) > 1
                    else (100 if delta > 0 else 0)
                )
                if delta > 20 and percent > 2:
                    return True
            elif a.value != b.value:
                return True
        return False

    async def evaluate(self, snapshot):
        self.snapshot = snapshot
        if self.policy_runtime:
            from .control.decisions import PolicySnapshot
            from .control.engine import controllers_from_fleet
            from .hbc.state import Clock
            from .policy_runtime import capture_entities

            by_role = {value.source: value for value in snapshot.observations}
            unknown = lambda role: by_role.get(role, Observation(role))
            now = time.time()
            clock = Clock(
                now, time.monotonic(), self.policy_runtime.accepted.hbc.boot_id
            )
            sun = self.state_reader("sun.sun")
            config = self.configuration
            policy = PolicySnapshot(
                snapshot.snapshot_id,
                now,
                unknown("grid_power_sensor"),
                unknown("pv_power_sensor"),
                unknown("market_price_sensor"),
                unknown("all_in_price_sensor"),
                controllers_from_fleet(self.manager.current),
                config.settings,
                enabled=config.enabled_intent,
                external_release=config.external_release_request,
                sun_below_horizon=bool(sun and sun.state == "below_horizon"),
                rebalance_pending=bool(self.manager.current.rebalance_uids),
                negative_price_hbc_charge=config.negative_price_hbc_charge,
            )
            try:
                self.policy_proposal = await self.policy_runtime.evaluate_readonly(
                    policy,
                    capture_entities(self.state_reader),
                    clock,
                    views=tuple(row.view for row in self.manager.current.effective),
                    permission=config.control_hbc_strategy,
                    negative_charge_permission=config.negative_price_hbc_charge,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self.storage_fault = "policy_memory_or_execution_snapshot_failed"
                raise
        # Proposed memory is durable; no plan is accepted or dispatched here.
        self.publish()

    async def async_set_configuration(self, configuration):
        if self.owner.closed:
            raise RuntimeError("Entry unloaded")

        async def persist():
            async with self._config_lock:
                if self.owner.closed:
                    raise RuntimeError("Entry unloaded")
                if configuration.plant_uid != self.configuration.plant_uid:
                    raise SchemaError("Cannot replace plant identity")
                if configuration.revision != self.configuration.revision:
                    raise SchemaError("Configuration revision changed")
                candidate = replace(
                    configuration, revision=self.configuration.revision + 1
                )
                state = replace(self.state, configuration=candidate)
                try:
                    await self.config_store.commit(state, self.config_store.revision)
                except Exception:
                    self.storage_fault = "configuration_commit_failed"
                    self.publish()
                    raise
                self.state = state
                self.scheduler.request_settings()
                self.publish()

        await self.owner.create_task(persist(), "hpvc-configuration-commit")

    async def close(self):
        await self.owner.close()
        self.listeners.clear()


def execution_snapshot(ledger):
    from .execution.snapshot import build_execution_snapshot
    from .execution.facts import ExecutionFacts
    from .hbc.state import Clock

    return build_execution_snapshot(
        ledger.current,
        (),
        Clock(time.time(), time.monotonic(), "snapshot-only"),
        ExecutionFacts(ledger.current.plant_uid),
    )
