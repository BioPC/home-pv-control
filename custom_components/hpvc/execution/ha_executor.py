"""Closed production HA transport. Only this module may access ServiceRegistry."""

import asyncio, time
from dataclasses import dataclass, replace
from types import MappingProxyType
from ..codec import Record, SchemaError
from ..storage import VersionedStore, StorageError
from ..hbc.state import Clock
from .executor import IssueReceipt, Completion, QuiescenceReceipt
from .service_plan import CompiledServiceStep, thaw

_TEST_ADMISSION_KEY = object()
TEST_DOMAIN = "hpvc_transport_test"


def production_transport_admitted():
    """Permanent dev.6 veto. No entity, configuration or storage controls this."""
    return False


class _TransportTestAdmission:
    """Non-serializable capability; only dedicated Python test injection creates it.

    Even an injected capability can only route to the harmless test namespace.
    It cannot unlock actual inverter or HBC service domains.
    """

    def __init__(self, *, _key, owner_epoch, aliases):
        if _key is not _TEST_ADMISSION_KEY:
            raise SchemaError("Dedicated test injection required")
        if (
            not owner_epoch
            or not aliases
            or any(
                d != TEST_DOMAIN or not s or not s.replace("_", "").isalnum()
                for d, s in aliases.values()
            )
        ):
            raise SchemaError(
                "Test admission cannot route to production service domains"
            )
        self._key = _key
        self.owner_epoch = owner_epoch
        self.aliases = MappingProxyType(dict(aliases))
        self.active = True

    def __reduce__(self):
        raise TypeError("Transport test admission cannot be persisted")


class TransportRefused(SchemaError):
    """Positive evidence that the registry invocation boundary was not crossed."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ServiceAudit(Record):
    operation_id: str
    dispatch_id: str
    owner_epoch: str
    controller_uid: str
    configuration_signature: str
    sequence_fingerprint: str
    domain: str
    service: str
    target_json: str
    data_json: str
    called_domain: str
    called_service: str
    armed: Clock
    issued: Clock | None = None
    completed: Clock | None = None
    result: str = "armed"
    exception_type: str = ""
    exception_message: str = ""


@dataclass(frozen=True)
class TransportJournal(Record):
    plant_uid: str
    owner_epoch: str
    attempts: tuple[ServiceAudit, ...] = ()

    def __post_init__(self):
        if (
            not self.plant_uid
            or not self.owner_epoch
            or len(self.attempts) > 128
            or len({a.dispatch_id for a in self.attempts}) != len(self.attempts)
        ):
            raise SchemaError("Invalid transport journal identity/retention")


class HaServiceExecutor:
    def __init__(
        self,
        hass,
        *,
        live_bindings=None,
        clock=None,
        _test_admission=None,
        timeout_seconds=30,
    ):
        if (
            _test_admission is not None
            and type(_test_admission) is not _TransportTestAdmission
        ):
            raise SchemaError("Unrecognized transport admission")
        if not 0 < timeout_seconds <= 120:
            raise SchemaError("Bounded transport timeout required")
        self._hass = hass
        self._live_bindings = live_bindings
        self._clock = clock
        self._test_admission = _test_admission
        self.timeout_seconds = timeout_seconds
        self.closed = False
        self._dispatcher = None
        self.store = None
        self.current = None
        self._refusals = {}
        self._plans = {}
        self._authority = None
        self._attempts = {}
        self._outbox = []
        self._journal_lock = asyncio.Lock()
        self.results_ready = asyncio.Event()

    @property
    def physical_writes_authorized(self):
        return False

    @property
    def production_admitted(self):
        return production_transport_admitted()

    def bind_dispatcher(self, dispatcher, prefix):
        if self._dispatcher is not None:
            raise SchemaError("HA executor already has a dispatcher")
        self._dispatcher = dispatcher
        self._authority = object()
        epoch = dispatcher.owner_epoch
        if not epoch.isalnum():
            raise SchemaError("Internal transport epoch must be an opaque identifier")
        self.store = VersionedStore(
            prefix.with_name(prefix.name + "_transport_" + epoch + ".json"),
            "ha_transport",
            TransportJournal,
        )
        self.current = TransportJournal(dispatcher.ledger.plant_uid, epoch)
        return self._authority

    async def load(self):
        value = await self.store.load()
        if value is not None:
            raise StorageError(
                "A transport owner epoch cannot be reused across runtime continuity"
            )
        await self.store.commit(self.current, 0)

    def install_plans(self, plans, authority):
        if authority is not self._authority:
            raise SchemaError("Only the dispatcher registers executable service plans")
        for plan in plans:
            if type(plan) is not CompiledServiceStep:
                raise SchemaError("Immutable compiled service plan required")
            self._plans[plan.operation_id] = plan

    def now(self):
        return (
            self._clock()
            if self._clock
            else Clock(
                time.time(),
                time.monotonic(),
                self._dispatcher.runtime.accepted.hbc.boot_id,
            )
        )

    def live_bindings(self):
        if self._live_bindings is None:
            raise TransportRefused("independent_live_binding_provider_missing")
        return self._live_bindings()

    def _route(self, plan):
        permit = self._test_admission
        if permit is not None:
            if (
                permit._key is not _TEST_ADMISSION_KEY
                or not permit.active
                or self.closed
                or permit.owner_epoch != self._dispatcher.owner_epoch
            ):
                raise TransportRefused("test_transport_admission_revoked")
            target = permit.aliases.get(plan.domain + "." + plan.service)
            if target is None or target[0] != TEST_DOMAIN:
                raise TransportRefused("service_has_no_harmless_test_alias")
            return target
        if not production_transport_admitted():
            raise TransportRefused("production_transport_permanently_closed")
        if (
            not self._dispatcher.physical_writes_authorized
            or self._dispatcher.ledger.current.ownership.state.value != "native_active"
        ):
            raise TransportRefused(
                "production_ownership_or_physical_authorization_closed"
            )
        return plan.domain, plan.service

    def _preflight(self, request, plan):
        if self.closed or self._dispatcher is None or self._dispatcher.closed:
            raise TransportRefused("executor_or_dispatcher_closed")
        route = self._route(plan)
        if self.store is None or not self.store.loaded or not self.store.healthy:
            raise TransportRefused("transport_journal_unavailable")
        self._dispatcher.recheck_service_invocation(
            request, plan, self.live_bindings(), self.now()
        )
        for entity_id in plan.entity_ids:
            state = self._hass.states.get(entity_id)
            if state is None:
                raise TransportRefused("target_entity_not_found:" + entity_id)
            if str(state.state).lower() in ("unknown", "unavailable", "none", ""):
                raise TransportRefused("target_entity_unavailable:" + entity_id)
            if (
                plan.service == "select_option"
                and plan.domain in ("select", "input_select")
                and thaw(plan.frozen_data).get("option")
                not in (state.attributes.get("options") or ())
            ):
                raise TransportRefused("select_option_no_longer_available")
        if not self._hass.services.has_service(*route):
            raise TransportRefused("service_not_found:" + ".".join(route))
        return route

    async def _audit(self, row):
        async with self._journal_lock:
            rows = tuple(
                a for a in self.current.attempts if a.dispatch_id != row.dispatch_id
            )
            value = replace(self.current, attempts=(*rows, row))
            await self.store.commit(value, self.store.revision)
            self.current = value

    async def issue(self, request):
        if (
            self._dispatcher is None
            or asyncio.current_task() not in self._dispatcher._running
        ):
            raise TransportRefused("dispatcher_is_the_only_issuer")
        plan = self._plans.get(request.operation_id)
        if plan is None:
            raise TransportRefused("unregistered_service_plan")
        try:
            route = self._preflight(request, plan)
        except TransportRefused as error:
            self._refusals[request.dispatch_id] = (request, error.reason)
            if self.store is not None and self.store.loaded and self.store.healthy:
                alias = (
                    self._test_admission.aliases.get(
                        plan.domain + "." + plan.service, ("", "")
                    )
                    if self._test_admission is not None
                    else ("", "")
                )
                row = ServiceAudit(
                    request.operation_id,
                    request.dispatch_id,
                    request.owner_epoch,
                    request.controller_uid,
                    request.configuration_signature,
                    plan.sequence_fingerprint,
                    plan.domain,
                    plan.service,
                    plan.target_json,
                    plan.data_json,
                    *alias,
                    request.issued,
                    completed=self.now(),
                    result="not_issued",
                    exception_type=type(error).__name__,
                    exception_message=str(error)[:512],
                )
                await self._audit(row)
            raise
        started = asyncio.get_running_loop().create_future()
        attempt = {
            "route": route,
            "request": request,
            "invoked": False,
            "started": started,
            "issued": None,
            "task": None,
            "watcher": None,
            "result": None,
        }
        if request.dispatch_id in self._attempts:
            raise TransportRefused("dispatch_identity_already_used")
        self._attempts[request.dispatch_id] = attempt
        task = asyncio.create_task(
            self._run_call(request, plan, attempt),
            name="hpvc-ha-service-" + request.dispatch_id,
        )
        attempt["task"] = task
        # Shielding preserves knowledge of a possibly issued call through owner unload.
        try:
            return await asyncio.shield(started)
        except asyncio.CancelledError:
            if not attempt["invoked"]:
                task.cancel()
            raise

    async def _run_call(self, request, plan, attempt):
        route = attempt["route"]
        row = ServiceAudit(
            request.operation_id,
            request.dispatch_id,
            request.owner_epoch,
            request.controller_uid,
            request.configuration_signature,
            plan.sequence_fingerprint,
            plan.domain,
            plan.service,
            plan.target_json,
            plan.data_json,
            *route,
            request.issued,
        )
        try:
            await self._audit(row)
            # No await between this final complete recheck and ServiceRegistry entry.
            route = self._preflight(request, plan)
            issued = self.now()
            attempt["invoked"] = True
            attempt["issued"] = issued
            row = replace(row, issued=issued, result="invoked")
            attempt["started"].set_result(IssueReceipt(request, True, issued))
            watcher = asyncio.create_task(
                self._watch(request, attempt),
                name="hpvc-ha-timeout-" + request.dispatch_id,
            )
            attempt["watcher"] = watcher
            # Sole actual HA service-call site in the entire native integration.
            await self._hass.services.async_call(
                route[0],
                route[1],
                service_data=thaw(plan.frozen_data),
                target=thaw(plan.frozen_target),
                blocking=True,
                return_response=False,
            )
            attempt["result"] = "success"
            completion = Completion(request, "success", self.now())
        except TransportRefused as error:
            if attempt["invoked"]:
                # A service handler may raise this exception too. Once invoked,
                # its exception is transport failure, never evidence of non-issue.
                attempt["result"] = "transport_failure"
                completion = Completion(
                    request,
                    "transport_failure",
                    self.now(),
                    type(error).__name__,
                    str(error)[:512],
                )
            else:
                attempt["result"] = "not_issued"
                self._refusals[request.dispatch_id] = (request, error.reason)
                if not attempt["started"].done():
                    attempt["started"].set_exception(error)
                await self._audit(
                    replace(
                        row,
                        result="not_issued",
                        completed=self.now(),
                        exception_type=type(error).__name__,
                        exception_message=str(error)[:512],
                    )
                )
                return
        except asyncio.CancelledError:
            if not attempt["invoked"]:
                attempt["result"] = "not_issued"
                if not attempt["started"].done():
                    attempt["started"].set_exception(
                        TransportRefused("cancelled_before_registry_invocation")
                    )
                return
            attempt["result"] = "outcome_unknown"
            completion = Completion(
                request,
                "outcome_unknown",
                self.now(),
                "CancelledError",
                "Registry invocation cancelled after possible issue",
            )
        except Exception as error:
            if not attempt["invoked"]:
                if not attempt["started"].done():
                    attempt["started"].set_exception(
                        TransportRefused(
                            "preissue_persistence_or_validation_failed:"
                            + type(error).__name__
                        )
                    )
                attempt["result"] = "not_issued"
                return
            attempt["result"] = "transport_failure"
            completion = Completion(
                request,
                "transport_failure",
                self.now(),
                type(error).__name__,
                str(error)[:512],
            )
        finally:
            if attempt["watcher"] is not None and not attempt.get("timed_out"):
                attempt["watcher"].cancel()
        if attempt.get("timed_out"):
            row = replace(
                row,
                result="late_" + attempt["result"],
                completed=self.now(),
                exception_type=completion.exception_type,
                exception_message=completion.exception_message,
            )
        else:
            row = replace(
                row,
                result=attempt["result"],
                completed=self.now(),
                exception_type=completion.exception_type,
                exception_message=completion.exception_message,
            )
        try:
            await self._audit(row)
        except Exception as error:
            completion = Completion(
                request,
                "outcome_unknown",
                self.now(),
                type(error).__name__,
                "Transport result could not commit; physical outcome remains unverified",
            )
            self._outbox.append(completion)
            self.results_ready.set()
            return
        if not attempt.get("timed_out"):
            self._outbox.append(completion)
            self.results_ready.set()

    async def _watch(self, request, attempt):
        try:
            await asyncio.sleep(self.timeout_seconds)
            attempt["timed_out"] = True
            completion = Completion(
                request,
                "outcome_unknown",
                self.now(),
                "TimeoutError",
                "Service has not completed; issued work was not cancelled",
            )
            self._outbox.append(completion)
            self.results_ready.set()
            row = next(
                a for a in self.current.attempts if a.dispatch_id == request.dispatch_id
            )
            await self._audit(
                replace(
                    row,
                    issued=attempt["issued"],
                    result="outcome_unknown",
                    completed=self.now(),
                    exception_type="TimeoutError",
                    exception_message=completion.exception_message,
                )
            )
        except asyncio.CancelledError:
            pass

    def take_completions(self):
        rows = tuple(self._outbox)
        self._outbox.clear()
        self.results_ready.clear()
        return rows

    def knows_not_issued(self, dispatch_id):
        if dispatch_id in self._refusals:
            return True
        attempt = self._attempts.get(dispatch_id)
        return bool(
            attempt
            and not attempt["invoked"]
            and (self.closed or attempt["result"] == "not_issued")
        )

    def confirm_quiescent(self, request, clock, result=None):
        attempt = self._attempts.get(request.dispatch_id)
        if (
            not attempt
            or attempt["request"] != request
            or not attempt["invoked"]
            or not attempt["task"].done()
        ):
            raise SchemaError("Issued registry work is not proven quiescent")
        actual = (
            "completed"
            if attempt["result"] == "success"
            else "failed"
            if attempt["result"] == "transport_failure"
            else None
        )
        if actual is None:
            raise SchemaError("Cancellation cannot prove external transport quiescence")
        return QuiescenceReceipt(request, clock, actual)

    def revoke_admission(self):
        self.closed = True
        if self._test_admission is not None:
            self._test_admission.active = False
        for attempt in self._attempts.values():
            if not attempt["invoked"] and attempt["task"] is not None:
                attempt["task"].cancel()

    async def close(self):
        self.revoke_admission()
        pending = [
            a["task"]
            for a in self._attempts.values()
            if not a["invoked"] and a["task"] is not None
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # Issued registry calls are deliberately not cancelled or reclassified as success.
