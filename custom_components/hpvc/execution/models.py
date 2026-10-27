"""Versioned execution records. These types cannot authorize physical writes."""

from dataclasses import dataclass, field
from enum import StrEnum
from ..codec import Record, SchemaError
from ..control.models import NightRestoreState, RepresentedTarget
from ..hbc.models import HbcOverrideRecovery


class OwnershipState(StrEnum):
    UNASSESSED = "unassessed"
    LEGACY_UNKNOWN = "legacy_presence_unknown"
    LEGACY_DETECTED = "legacy_detected"
    IMPORT_PREPARED = "import_prepared"
    HANDOFF_PENDING = "handoff_pending"
    LEGACY_QUIESCING = "legacy_quiescing"
    LEGACY_RECONCILING = "legacy_reconciling"
    LEGACY_RESTORED = "legacy_restored"
    LEGACY_FENCING = "legacy_fencing"
    POST_FENCE_VERIFY = "post_fence_verify"
    NATIVE_OWNER_COMMITTED = "native_owner_committed"
    READY_DISABLED = "ready_disabled"
    NATIVE_ACTIVE = "native_active"
    BLOCKED = "blocked_recovery"


class OperationState(StrEnum):
    PREPARED = "prepared"
    ARMED = "dispatch_armed"
    IN_FLIGHT = "service_in_flight"
    SERVICE_COMPLETED = "service_completed"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    RETIRED = "retired"
    SUPERSEDED = "superseded_unsent"
    SERVICE_FAILED = "service_failed"
    VERIFICATION_FAILED = "verification_failed"
    OPEN_LOOP = "unverifiable_open_loop"
    UNKNOWN = "outcome_unknown"
    RECOVERY_REQUIRED = "recovery_required"


OPERATION_TRANSITIONS = {
    OperationState.PREPARED: {OperationState.ARMED, OperationState.SUPERSEDED},
    OperationState.ARMED: {
        OperationState.IN_FLIGHT,
        OperationState.UNKNOWN,
        OperationState.SUPERSEDED,
    },
    OperationState.IN_FLIGHT: {
        OperationState.SERVICE_COMPLETED,
        OperationState.SERVICE_FAILED,
        OperationState.UNKNOWN,
    },
    OperationState.SERVICE_COMPLETED: {
        OperationState.AWAITING_VERIFICATION,
        OperationState.OPEN_LOOP,
        OperationState.UNKNOWN,
    },
    OperationState.AWAITING_VERIFICATION: {
        OperationState.VERIFIED,
        OperationState.VERIFICATION_FAILED,
        OperationState.UNKNOWN,
    },
    OperationState.VERIFIED: {OperationState.RETIRED},
    OperationState.OPEN_LOOP: {OperationState.UNKNOWN},
    OperationState.UNKNOWN: {OperationState.RECOVERY_REQUIRED},
    OperationState.RECOVERY_REQUIRED: {OperationState.AWAITING_VERIFICATION},
}


class TransportStatus(StrEnum):
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ObligationState(StrEnum):
    UNKNOWN = "unknown"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    VERIFIED = "verified"


class MaintenanceState(StrEnum):
    IDLE = "idle"
    REQUESTED = "requested"
    RESTORING = "restoring"
    VERIFYING = "verifying"
    AUTHORIZED = "authorized"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Lane(StrEnum):
    INVERTER = "inverter"
    HBC = "hbc_override"


@dataclass(frozen=True)
class CommandStep(Record):
    step_id: str
    phase: str
    action: str
    data_json: str = "{}"
    target_json: str = "{}"


@dataclass(frozen=True)
class CommandBatch(Record):
    batch_id: str
    evaluation_id: str
    controller_uid: str
    configuration_signature: str
    sequence_fingerprint: str
    targets: tuple[RepresentedTarget, ...] = ()
    steps: tuple[CommandStep, ...] = ()
    requested_plant_target_w: float | None = None
    requires_readiness: bool = False


@dataclass(frozen=True)
class PhysicalOperation(Record):
    operation_id: str
    batch_id: str
    step_id: str
    owner_epoch: str
    controller_uid: str
    adapter_kind: str
    configuration_signature: str
    configuration_reference: str
    lane: Lane = Lane.INVERTER
    configuration_revision: int = 1
    requested_plant_target_w: float | None = None
    allocated_controller_target_w: float | None = None
    representable_controller_target_w: float | None = None
    native_command_value: float | None = None
    command_fingerprint: str = ""
    sequence_fingerprint: str = ""
    step_phase: str = "main"
    step_index: int = 0
    state: OperationState = OperationState.PREPARED
    transport: TransportStatus = TransportStatus.NOT_SENT
    verification: VerificationStatus = VerificationStatus.UNKNOWN
    prepared_at_utc: float | None = None
    armed_at_utc: float | None = None
    dispatch_id: str | None = None
    dispatch_started_at_utc: float | None = None
    service_completed_at_utc: float | None = None
    evidence_ids: tuple[str, ...] = ()
    reason: str | None = None
    expected_native_value: str | None = None

    def __post_init__(self):
        if not all(
            (
                self.operation_id,
                self.controller_uid,
                self.owner_epoch,
                self.configuration_signature,
                self.configuration_reference,
            )
        ):
            raise SchemaError("Operation identity/configuration required")
        if (
            self.state in (OperationState.VERIFIED, OperationState.RETIRED)
            and self.verification != VerificationStatus.VERIFIED
        ):
            raise SchemaError("Verified operation needs verification status")
        if self.verification == VerificationStatus.VERIFIED and not self.evidence_ids:
            raise SchemaError("Verified operation needs evidence")
        if self.state == OperationState.ARMED and (
            self.armed_at_utc is None or self.armed_at_utc <= 0
        ):
            raise SchemaError("Armed operation requires durable timestamp")
        if self.state == OperationState.IN_FLIGHT and (
            not self.dispatch_id
            or self.dispatch_started_at_utc is None
            or self.transport != TransportStatus.IN_FLIGHT
        ):
            raise SchemaError(
                "In-flight operation requires dispatch identity/time and transport"
            )
        if (
            self.state
            in (
                OperationState.SERVICE_COMPLETED,
                OperationState.AWAITING_VERIFICATION,
                OperationState.OPEN_LOOP,
            )
            and self.transport != TransportStatus.COMPLETED
        ):
            raise SchemaError("Completed service state requires transport completion")
        if (
            self.state == OperationState.SUPERSEDED
            and self.transport != TransportStatus.NOT_SENT
        ):
            raise SchemaError("Only unsent work can be superseded")
        if (
            self.state == OperationState.SUPERSEDED
            and self.armed_at_utc is not None
            and not (self.reason or "").startswith("executor_confirmed_not_issued:")
        ):
            raise SchemaError(
                "Armed supersession requires executor evidence of no invocation"
            )


@dataclass(frozen=True)
class VerificationEvidence(Record):
    evidence_id: str
    controller_uid: str
    configuration_signature: str
    operation_id: str | None
    kind: str
    verdict: VerificationStatus
    observed_value_w: float | None = None
    reported_at_utc: float | None = None
    poll_started_at_utc: float | None = None
    received_at_utc: float | None = None
    provenance: str = ""
    tolerance_w: float = 0.0
    observed_native_value: str | None = None

    def __post_init__(self):
        if (
            self.kind in ("command-cache", "startup-full-assumption")
            and self.verdict == VerificationStatus.VERIFIED
        ):
            raise SchemaError("Command assumptions are not physical evidence")
        if self.tolerance_w < 0:
            raise SchemaError("Negative verification tolerance")


@dataclass(frozen=True)
class RestoreObligation(Record):
    obligation_id: str
    controller_uid: str
    configuration_signature: str
    configuration_reference: str
    origin: str
    required_target_w: float | None
    state: ObligationState = ObligationState.UNRESOLVED
    operation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    established_at_utc: float | None = None
    owner_epoch: str | None = None

    def __post_init__(self):
        if not all(
            (
                self.obligation_id,
                self.controller_uid,
                self.configuration_signature,
                self.configuration_reference,
            )
        ):
            raise SchemaError("Restore obligation identity required")
        if self.state == ObligationState.VERIFIED and not self.evidence_ids:
            raise SchemaError("Restore resolution requires evidence")


@dataclass(frozen=True)
class HandoffRecord(Record):
    transaction_id: str | None = None
    state: OwnershipState = OwnershipState.UNASSESSED
    owner_epoch: str | None = None
    legacy_fingerprint: str | None = None
    fence_evidence: tuple[str, ...] = ()
    blocked_reason: str | None = None


@dataclass(frozen=True)
class MaintenanceRecord(Record):
    transaction_id: str | None = None
    owner_token: str | None = None
    state: MaintenanceState = MaintenanceState.IDLE
    requested_action: str | None = None
    saved_enable_intent: bool | None = None
    obligation_ids: tuple[str, ...] = ()
    authorization_revision: int | None = None
    requested_at_utc: float | None = None
    post_disable_evaluation_id: str | None = None
    owner_epoch: str | None = None
    requested_monotonic: float | None = None
    boot_id: str | None = None


@dataclass(frozen=True)
class ExecutionSnapshot(Record):
    unresolved_operation_ids: tuple[str, ...] = ()
    unresolved_hbc_operation_ids: tuple[str, ...] = ()
    unresolved_obligation_ids: tuple[str, ...] = ()
    recovery_required: bool = False
    blocked_reason: str = "foundation_phase_no_actuator_implementation"
    pending_verification: bool = False
    settling: bool = False
    settling_timed_out: bool = False
    frozen_controller_uids: tuple[str, ...] = ()
    write_eligible_uids: tuple[str, ...] | None = None
    maintenance_active: bool = False
    hbc_restore_pending: bool = False
    cooldown_until_utc: float = 0.0
    last_command_delta_w: float | None = None
    last_command_at_utc: float | None = None
    last_command_verification_failed: bool = False
    pending_action: str | None = None
    pending_since_utc: float | None = None
    write_lock_reason: str = ""
    ownership_state: str = "unassessed"
    accepted_event_id: str | None = None
    accepted_controller_uids: tuple[str, ...] = ()
    authorization_block_reasons: tuple[str, ...] = ("physical_writes_hard_off",)

    @property
    def physical_writes_authorized(self) -> bool:
        return False


@dataclass(frozen=True)
class ExecutionLedger(Record):
    plant_uid: str
    schema_version: int = 1
    revision: int = 0
    committed_at_utc: float | None = None
    ownership: HandoffRecord = field(default_factory=HandoffRecord)
    operations: tuple[PhysicalOperation, ...] = ()
    restore_obligations: tuple[RestoreObligation, ...] = ()
    maintenance: MaintenanceRecord = field(default_factory=MaintenanceRecord)
    hbc_override: HbcOverrideRecovery = field(default_factory=HbcOverrideRecovery)
    night_restore: NightRestoreState = field(default_factory=NightRestoreState)
    evidence: tuple[VerificationEvidence, ...] = ()

    def __post_init__(self):
        if not self.plant_uid or self.schema_version != 1 or self.revision < 0:
            raise SchemaError("Unsupported execution ledger")
        for items, key in (
            (self.operations, "operation_id"),
            (self.restore_obligations, "obligation_id"),
            (self.evidence, "evidence_id"),
        ):
            ids = [getattr(item, key) for item in items]
            if len(set(ids)) != len(ids):
                raise SchemaError("Duplicate ledger identities")
        if len(self.evidence) > 128:
            raise SchemaError("Evidence retention bound exceeded")
        evidence = {item.evidence_id: item for item in self.evidence}
        for item in (*self.operations, *self.restore_obligations):
            for evidence_id in item.evidence_ids:
                proof = evidence.get(evidence_id)
                if (
                    not proof
                    or proof.controller_uid != item.controller_uid
                    or proof.configuration_signature != item.configuration_signature
                ):
                    raise SchemaError("Evidence identity/configuration mismatch")
                if (
                    isinstance(item, PhysicalOperation)
                    and proof.operation_id != item.operation_id
                ):
                    raise SchemaError("Evidence operation mismatch")
                if proof.verdict != VerificationStatus.VERIFIED:
                    raise SchemaError("Unverified evidence cannot resolve work")
                target = (
                    item.representable_controller_target_w
                    if isinstance(item, PhysicalOperation)
                    else item.required_target_w
                )
                if (
                    isinstance(item, PhysicalOperation)
                    and item.expected_native_value is not None
                ):
                    if (
                        proof.kind != "independent_native_state"
                        or proof.observed_native_value != item.expected_native_value
                        or proof.received_at_utc is None
                        or proof.reported_at_utc is None
                        or item.dispatch_started_at_utc is None
                        or min(proof.reported_at_utc, proof.received_at_utc)
                        < item.dispatch_started_at_utc
                        or proof.provenance
                        != "owner="
                        + item.owner_epoch
                        + ";dispatch="
                        + str(item.dispatch_id)
                    ):
                        raise SchemaError(
                            "Native step proof does not match dispatched identity/value"
                        )
                    continue
                if (
                    target is None
                    or proof.observed_value_w is None
                    or proof.received_at_utc is None
                ):
                    raise SchemaError(
                        "Resolution requires numeric target and timed observation"
                    )
                if abs(proof.observed_value_w - target) > proof.tolerance_w:
                    raise SchemaError(
                        "Evidence does not confirm requested physical target"
                    )
                if isinstance(item, PhysicalOperation):
                    if (
                        item.dispatch_started_at_utc is None
                        or proof.received_at_utc < item.dispatch_started_at_utc
                    ):
                        raise SchemaError("Evidence predates dispatch")
                    if proof.kind == "opendtu_api" and (
                        proof.poll_started_at_utc is None
                        or proof.poll_started_at_utc < item.dispatch_started_at_utc
                    ):
                        raise SchemaError("OpenDTU poll predates dispatch")
        operation_ids = {item.operation_id for item in self.operations}
        obligation_ids = {item.obligation_id for item in self.restore_obligations}
        if any(
            key not in operation_ids
            for item in self.restore_obligations
            for key in item.operation_ids
        ):
            raise SchemaError("Missing referenced operation")
        if any(key not in obligation_ids for key in self.maintenance.obligation_ids):
            raise SchemaError("Missing maintenance obligation")
        if (
            self.night_restore.full_output_proof_reference
            and self.night_restore.full_output_proof_reference not in evidence
        ):
            raise SchemaError("Missing Night Restore proof")
        if any(key not in operation_ids for key in self.hbc_override.operation_ids):
            raise SchemaError("Missing HBC override operation")
        terminal_states = {
            OperationState.RETIRED,
            OperationState.VERIFIED,
            OperationState.SUPERSEDED,
        }
        if sum(item.state in terminal_states for item in self.operations) > 128:
            raise SchemaError("Terminal operation retention bound exceeded")
        active = [
            item
            for item in self.operations
            if item.lane == Lane.INVERTER
            and (
                item.state in (OperationState.ARMED, OperationState.IN_FLIGHT)
                or (
                    item.state
                    in (OperationState.UNKNOWN, OperationState.RECOVERY_REQUIRED)
                    and item.transport
                    in (TransportStatus.UNKNOWN, TransportStatus.IN_FLIGHT)
                )
            )
        ]
        if len(active) > 1:
            raise SchemaError("Multiple armed/in-flight inverter operations")
