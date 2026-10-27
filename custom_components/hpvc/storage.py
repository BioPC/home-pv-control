"""Independent versioned stores with strict loading and write-ahead commits."""

from __future__ import annotations
import asyncio
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from .codec import Record, SchemaError
from .control.models import PlantConfiguration, ImportTransaction
from .execution.models import (
    ExecutionLedger,
    OperationState,
    TransportStatus,
    ObligationState,
    MaintenanceState,
    OwnershipState,
    OPERATION_TRANSITIONS,
)
from .hbc.models import OverridePhase


class StorageError(RuntimeError):
    """Storage cannot establish a safe, known state."""


class RevisionConflict(StorageError):
    pass


@dataclass(frozen=True)
class ConfigurationState(Record):
    configuration: PlantConfiguration
    imports: tuple[ImportTransaction, ...] = ()

    def __post_init__(self):
        if len(self.imports) > 16 or len(
            {item.transaction_id for item in self.imports}
        ) != len(self.imports):
            raise SchemaError("Invalid import retention/identity")
        if any(
            item.candidate and item.candidate.plant_uid != self.configuration.plant_uid
            for item in self.imports
        ):
            raise SchemaError("Import plant identity mismatch")


@dataclass(frozen=True)
class HistoryState(Record):
    plant_uid: str
    local_date: str | None = None
    insights_json: str = "[]"
    activity_json: str = "[]"
    activity_meta_json: str = "{}"
    report_history_json: str = "null"
    accuracy_json: str = "null"
    eligibility_schema: int = 11
    headline_attribution_revision: int = 22

    def __post_init__(self):
        if (
            not self.plant_uid
            or self.eligibility_schema != 11
            or self.headline_attribution_revision != 22
        ):
            raise SchemaError("Unsupported runtime history contract")
        for value, kind in (
            (self.insights_json, list),
            (self.activity_json, list),
            (self.activity_meta_json, dict),
        ):
            if not isinstance(strict_json(value), kind):
                raise SchemaError("Invalid history payload")
        for value in (self.report_history_json, self.accuracy_json):
            parsed = strict_json(value)
            if parsed is not None and not isinstance(parsed, dict):
                raise SchemaError("Invalid optional history payload")

        accuracy = strict_json(self.accuracy_json)
        if accuracy is not None:
            required = (
                "sumDt",
                "sumSqZDt",
                "sumSqEDt",
                "sumEDt",
                "outsideDeadbandDt",
                "outsideSumSqEDt",
                "outsideSumEDt",
                "targetCount",
                "bandExcursionCount",
                "policyExcludedErrorDt",
                "unattributedErrorDt",
            )
            if (
                accuracy.get("eligibilitySchema") != 11
                or accuracy.get("headlineAttributionRevision") != 22
                or accuracy.get("date") != self.local_date
            ):
                raise SchemaError("Invalid accuracy schema/date")
            if any(
                type(accuracy.get(key)) not in (int, float) or accuracy[key] < 0
                for key in required
            ):
                raise SchemaError("Invalid accuracy accumulators")
            if (
                any(
                    type(accuracy[key]) is not int
                    for key in ("targetCount", "bandExcursionCount")
                )
                or accuracy["bandExcursionCount"] > accuracy["targetCount"]
            ):
                raise SchemaError("Invalid accuracy counts")
            if accuracy["outsideDeadbandDt"] > accuracy["sumDt"] + 1e-6:
                raise SchemaError("Invalid accuracy duration")
            factors = accuracy.get("factorErrorDt", {})
            headline = accuracy.get("headlineFactorSqZDt", {})
            if any(
                type(group.get(key)) not in (int, float) or group[key] < 0
                for group in (factors, headline)
                for key in ("control", "load", "pv", "other")
            ):
                raise SchemaError("Invalid accuracy factors")
            import math

            if not math.isclose(
                sum(factors.values())
                + accuracy["policyExcludedErrorDt"]
                + accuracy["unattributedErrorDt"],
                accuracy["sumEDt"],
                rel_tol=1e-9,
                abs_tol=1e-6,
            ):
                raise SchemaError("Accuracy attribution does not conserve burden")
            if not math.isclose(
                sum(headline.values()), accuracy["sumSqZDt"], rel_tol=1e-9, abs_tol=1e-6
            ):
                raise SchemaError("Accuracy headline factors do not conserve burden")


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SchemaError("Duplicate JSON key")
            result[key] = value
        return result

    def bad_constant(value):
        raise SchemaError(f"Non-finite JSON value {value}")

    try:
        return json.loads(text, parse_constant=bad_constant, object_pairs_hook=pairs)
    except (ValueError, TypeError) as err:
        raise SchemaError("Invalid JSON") from err


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=False,
    )


def atomic_replace(path: Path, content: bytes) -> None:
    """Sync a same-directory temp file, atomically replace, sync directory on POSIX.

    Windows provides file fsync + atomic replace; directory fsync is platform-specific.
    Unsupported/corrupt future reads fail closed. This is not a universal power-loss claim.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


async def complete_io(func, *args):
    """Drain filesystem work even when both HA and our owner cancel the task."""
    task = asyncio.create_task(asyncio.to_thread(func, *args), name="hpvc-storage-io")
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                result = task.result()
                break
    if cancelled:
        raise asyncio.CancelledError
    return result


class VersionedStore:
    def __init__(self, path: Path, kind: str, model):
        self.path = path
        self.kind = kind
        self.model = model
        self.revision = 0
        self.loaded = False
        self.healthy = True
        self._lock = asyncio.Lock()

    async def load(self):
        async with self._lock:
            try:
                raw = await complete_io(self._read)
                if raw is None:
                    self.revision = 0
                    self.loaded = True
                    return None
                if not isinstance(raw, dict) or set(raw) != {
                    "schema_version",
                    "kind",
                    "revision",
                    "payload",
                    "sha256",
                }:
                    raise SchemaError("Invalid store envelope")
                if (
                    raw["schema_version"] != 1
                    or type(raw["schema_version"]) is not int
                    or raw["kind"] != self.kind
                ):
                    raise SchemaError("Unsupported store schema/kind")
                if type(raw["revision"]) is not int or raw["revision"] < 1:
                    raise SchemaError("Invalid store revision")
                expected = hashlib.sha256(
                    canonical(raw["payload"]).encode()
                ).hexdigest()
                if raw["sha256"] != expected:
                    raise SchemaError("Store checksum mismatch")
                payload = raw["payload"]
                if self.model is ExecutionLedger:
                    payload = migrate_execution_additions(payload)
                value = self.model.from_dict(payload)
                if (
                    isinstance(value, ExecutionLedger)
                    and value.revision != raw["revision"]
                ):
                    raise SchemaError("Ledger envelope revision mismatch")
                self.revision = raw["revision"]
                self.loaded = True
                self.healthy = True
                return value
            except (OSError, SchemaError, UnicodeError) as err:
                self.healthy = False
                raise StorageError(f"Cannot load {self.kind}: {err}") from err

    def _read(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
        except FileNotFoundError:
            return None
        if len(raw) > 4 * 1024 * 1024:
            raise SchemaError("Store exceeds safety limit")
        return strict_json(raw)

    async def commit(self, value, expected_revision: int):
        async with self._lock:
            if not self.loaded or not self.healthy:
                raise StorageError("Load healthy store before commit")
            if expected_revision != self.revision:
                raise RevisionConflict("Store revision changed")
            payload = value.to_dict()
            self.model.from_dict(payload)
            revision = self.revision + 1
            if isinstance(value, ExecutionLedger) and value.revision != revision:
                raise SchemaError("Ledger revision must match next durable commit")
            envelope = {
                "schema_version": 1,
                "kind": self.kind,
                "revision": revision,
                "payload": payload,
                "sha256": hashlib.sha256(canonical(payload).encode()).hexdigest(),
            }
            data = canonical(envelope).encode("utf-8")
            if len(data) > 4 * 1024 * 1024:
                raise SchemaError("Store exceeds safety limit")
            try:
                await complete_io(atomic_replace, self.path, data)
            except BaseException:
                self.healthy = False
                raise
            self.revision = revision
            return revision


class LedgerRepository:
    """Serialize validated record transitions; no service execution capability."""

    def __init__(self, store: VersionedStore, plant_uid: str):
        self.store = store
        self.plant_uid = plant_uid
        self.current = ExecutionLedger(plant_uid)
        self._lock = asyncio.Lock()

    async def load(self):
        value = await self.store.load()
        if value is not None and value.plant_uid != self.plant_uid:
            raise StorageError("Ledger belongs to another plant")
        self.current = value or ExecutionLedger(self.plant_uid)
        return self.current

    async def update(self, transform):
        async with self._lock:
            candidate = transform(self.current)
            old_ops = {item.operation_id: item for item in self.current.operations}
            new_ops = {item.operation_id: item for item in candidate.operations}
            terminal = {
                OperationState.VERIFIED,
                OperationState.RETIRED,
                OperationState.SUPERSEDED,
            }
            mutable = {
                "state",
                "transport",
                "verification",
                "armed_at_utc",
                "dispatch_id",
                "dispatch_started_at_utc",
                "service_completed_at_utc",
                "evidence_ids",
                "reason",
            }
            for key, previous in old_ops.items():
                current = new_ops.get(key)
                if current is None:
                    if previous.state not in terminal:
                        raise SchemaError("Cannot discard unresolved operation")
                    continue
                if (
                    current.state != previous.state
                    and current.state
                    not in OPERATION_TRANSITIONS.get(previous.state, set())
                ):
                    raise SchemaError("Illegal operation lifecycle transition")
                if any(
                    getattr(previous, name) != getattr(current, name)
                    for name in previous.__dataclass_fields__
                    if name not in mutable
                ):
                    raise SchemaError("Cannot mutate operation identity/target")
            new_obligations = {
                item.obligation_id: item for item in candidate.restore_obligations
            }
            for previous in self.current.restore_obligations:
                current = new_obligations.get(previous.obligation_id)
                if current is None and previous.state != ObligationState.VERIFIED:
                    raise SchemaError("Cannot discard unresolved restoration")
                if current is not None and any(
                    getattr(current, name) != getattr(previous, name)
                    for name in (
                        "controller_uid",
                        "configuration_signature",
                        "configuration_reference",
                        "required_target_w",
                    )
                ):
                    raise SchemaError("Cannot mutate restoration identity/target")
            if candidate.plant_uid != self.plant_uid:
                raise SchemaError("Cannot replace plant identity")
            candidate = replace(
                candidate,
                revision=self.store.revision + 1,
                committed_at_utc=time.time(),
            )
            await self.store.commit(candidate, self.store.revision)
            self.current = candidate
            return candidate

    async def register_operation(self, operation):
        if operation.state != OperationState.PREPARED:
            raise SchemaError("Register only prepared work")

        def change(ledger):
            if any(
                item.operation_id == operation.operation_id
                for item in ledger.operations
            ):
                raise SchemaError("Operation identity already registered")
            return replace(ledger, operations=(*ledger.operations, operation))

        return await self.update(change)

    async def transition_operation(self, operation_id, state, **changes):
        """Data transition only. A transition never invokes an actuator."""
        mutable = {
            "transport",
            "verification",
            "armed_at_utc",
            "dispatch_id",
            "dispatch_started_at_utc",
            "service_completed_at_utc",
            "evidence_ids",
            "reason",
        }
        if set(changes) - mutable:
            raise SchemaError("Operation identity/targets are immutable")

        def change(ledger):
            previous = next(
                (
                    item
                    for item in ledger.operations
                    if item.operation_id == operation_id
                ),
                None,
            )
            if not previous or state not in OPERATION_TRANSITIONS.get(
                previous.state, set()
            ):
                raise SchemaError("Illegal operation transition")
            updated = replace(previous, state=state, **changes)
            return replace(
                ledger,
                operations=tuple(
                    updated if item.operation_id == operation_id else item
                    for item in ledger.operations
                ),
            )

        return await self.update(change)

    async def add_evidence(self, evidence):
        def change(ledger):
            if any(
                item.evidence_id == evidence.evidence_id for item in ledger.evidence
            ):
                raise SchemaError("Evidence identity reused")
            referenced = {
                key
                for item in (*ledger.operations, *ledger.restore_obligations)
                for key in item.evidence_ids
            }
            if ledger.night_restore.full_output_proof_reference:
                referenced.add(ledger.night_restore.full_output_proof_reference)
            items = (*ledger.evidence, evidence)
            while len(items) > 128:
                disposable = next(
                    (
                        i
                        for i, item in enumerate(items)
                        if item.evidence_id not in referenced
                        and item.evidence_id != evidence.evidence_id
                    ),
                    None,
                )
                if disposable is None:
                    raise SchemaError(
                        "Evidence bound reached; referenced proof cannot be dropped"
                    )
                items = items[:disposable] + items[disposable + 1 :]
            return replace(ledger, evidence=items)

        return await self.update(change)

    async def reconcile_restart(self):
        """Preserve uncertainty; never replay/resolve writes or grant ownership."""

        def change(ledger):
            uncertain = {
                OperationState.ARMED,
                OperationState.IN_FLIGHT,
                OperationState.SERVICE_COMPLETED,
                OperationState.AWAITING_VERIFICATION,
                OperationState.OPEN_LOOP,
            }
            operations = tuple(
                replace(
                    item,
                    state=OperationState.UNKNOWN,
                    transport=TransportStatus.UNKNOWN
                    if item.state in (OperationState.ARMED, OperationState.IN_FLIGHT)
                    else item.transport,
                    reason="execution_continuity_lost",
                )
                if item.state in uncertain
                else item
                for item in ledger.operations
            )
            maintenance = ledger.maintenance
            if maintenance.state not in (
                MaintenanceState.IDLE,
                MaintenanceState.COMPLETE,
                MaintenanceState.CANCELLED,
            ):
                maintenance = replace(
                    maintenance,
                    state=MaintenanceState.BLOCKED,
                    authorization_revision=None,
                )
            night = replace(
                ledger.night_restore,
                entry_candidate_since_utc=None,
                recovery_candidate_since_utc=None,
            )
            ownership = replace(
                ledger.ownership,
                blocked_reason="foundation_phase_no_actuator_implementation",
            )
            return replace(
                ledger,
                operations=operations,
                maintenance=maintenance,
                night_restore=night,
                ownership=ownership,
            )

        return await self.update(change)

    @property
    def recovery_required(self):
        ledger = self.current
        terminal = {
            OperationState.RETIRED,
            OperationState.SUPERSEDED,
            OperationState.VERIFIED,
        }
        return (
            any(item.state not in terminal for item in ledger.operations)
            or any(
                item.state != ObligationState.VERIFIED
                for item in ledger.restore_obligations
            )
            or ledger.maintenance.state
            not in (
                MaintenanceState.IDLE,
                MaintenanceState.COMPLETE,
                MaintenanceState.CANCELLED,
            )
            or ledger.hbc_override.phase != OverridePhase.INACTIVE
            or ledger.ownership.state
            in (OwnershipState.LEGACY_UNKNOWN, OwnershipState.BLOCKED)
        )


def migrate_execution_additions(payload):
    """Explicit additive dev.4 migration after verifying the original checksum.

    Only the complete old field set or complete new set is accepted per record.
    This does not relax the strict codec for arbitrary missing/extra fields.
    """
    from dataclasses import fields
    from .execution.models import (
        PhysicalOperation,
        VerificationEvidence,
        RestoreObligation,
        MaintenanceRecord,
    )

    additions = (
        ("operations", PhysicalOperation, {"expected_native_value": None}),
        ("evidence", VerificationEvidence, {"observed_native_value": None}),
        (
            "restore_obligations",
            RestoreObligation,
            {"established_at_utc": None, "owner_epoch": None},
        ),
    )
    if not isinstance(payload, dict):
        raise SchemaError("Invalid execution payload")
    result = dict(payload)

    def upgrade(row, model, defaults):
        if not isinstance(row, dict):
            raise SchemaError("Invalid execution record")
        expected = {f.name for f in fields(model)}
        return {**row, **defaults} if set(row) == expected - set(defaults) else row

    for key, model, defaults in additions:
        if key in result and isinstance(result[key], list):
            result[key] = [upgrade(row, model, defaults) for row in result[key]]
    if "maintenance" in result:
        result["maintenance"] = upgrade(
            result["maintenance"],
            MaintenanceRecord,
            {
                "requested_at_utc": None,
                "post_disable_evaluation_id": None,
                "owner_epoch": None,
                "requested_monotonic": None,
                "boot_id": None,
            },
        )
    return result
