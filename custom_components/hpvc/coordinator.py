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
    FOUNDATION_WRITE_BLOCK,
)
from .codec import SchemaError
from .control.models import PlantSnapshot, Observation, Quality
from .execution.models import ExecutionSnapshot, OperationState, ObligationState

_LOGGER = logging.getLogger(__name__)


class LifecycleOwner:
    """Own arbitrary listeners/timers/workers, including future HTTP/report work."""

    def __init__(self, task_factory=None):
        self.closed = False
        self.tasks = set()
        self.cleanups = []
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
        return bool(self.storage_fault or self.ledger.recovery_required)

    @property
    def required_inputs_ready(self):
        return False  # no effective fleet/control implementation in this phase

    def add_listener(self, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def publish(self):
        for callback in tuple(self.listeners):
            callback()

    def start(self):
        self.scheduler.start()

    async def refresh(self):
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
        # Foundation publishes observations only: no policy engine, commands or dispatch.
        self.snapshot = snapshot
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
    return ExecutionSnapshot(
        tuple(
            item.operation_id
            for item in ledger.current.operations
            if item.state
            not in (
                OperationState.VERIFIED,
                OperationState.RETIRED,
                OperationState.SUPERSEDED,
            )
        ),
        tuple(
            item.obligation_id
            for item in ledger.current.restore_obligations
            if item.state != ObligationState.VERIFIED
        ),
        ledger.recovery_required,
        FOUNDATION_WRITE_BLOCK,
    )
