"""Read-only recovery classification and durable obligation reconstruction."""

from dataclasses import dataclass, replace
from ..codec import Record
from .models import (
    OperationState,
    Lane,
    TransportStatus,
    ObligationState,
    RestoreObligation,
    MaintenanceState,
)
from ..hbc.models import OverridePhase
from ..inverter.base import fingerprint


@dataclass(frozen=True)
class OperationRecovery(Record):
    operation_id: str
    execution_quiescent: bool
    physical_outcome_unknown: bool
    reason: str


@dataclass(frozen=True)
class RecoveryAssessment(Record):
    required: bool
    operations: tuple[OperationRecovery, ...] = ()
    unresolved_obligation_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def physical_writes_authorized(self):
        return False


def classify_operation(operation):
    unsent = operation.state in (OperationState.PREPARED, OperationState.SUPERSEDED)
    quiescent = unsent or operation.transport in (
        TransportStatus.COMPLETED,
        TransportStatus.FAILED,
    )
    verified = operation.state in (OperationState.VERIFIED, OperationState.RETIRED)
    unknown = not unsent and not verified
    reason = (
        "unsent_data_only"
        if unsent
        else "physical_evidence_required"
        if quiescent and unknown
        else "execution_continuity_unresolved"
        if not quiescent
        else "verified_record"
    )
    return OperationRecovery(operation.operation_id, quiescent, unknown, reason)


def assess_recovery(ledger):
    rows = tuple(classify_operation(item) for item in ledger.operations)
    unresolved = tuple(
        item.obligation_id
        for item in ledger.restore_obligations
        if item.state != ObligationState.VERIFIED
    )
    reasons = []
    if any(
        not item.execution_quiescent or item.physical_outcome_unknown for item in rows
    ):
        reasons.append("unresolved_physical_operation")
    if unresolved:
        reasons.append("unresolved_restore_obligations")
    if ledger.maintenance.state not in (
        MaintenanceState.IDLE,
        MaintenanceState.COMPLETE,
        MaintenanceState.CANCELLED,
    ):
        reasons.append("maintenance_requires_reconciliation")
    if ledger.hbc_override.phase != OverridePhase.INACTIVE:
        reasons.append("owned_HBC_override_requires_reconciliation")
    return RecoveryAssessment(bool(reasons), rows, unresolved, tuple(reasons))


def reconstruct_restore_obligations(ledger, configuration_archive=None):
    """Never use a replacement controller in the same slot to resolve old work.

    Archives are keyed by the operation's immutable configuration_reference. Missing
    historical ranges remain explicit unknown obligations, never a guessed full limit.
    """
    archive = configuration_archive or {}
    obligations = list(ledger.restore_obligations)
    for operation in ledger.operations:
        if operation.lane == Lane.HBC:
            continue
        if operation.state in (
            OperationState.PREPARED,
            OperationState.SUPERSEDED,
            OperationState.VERIFIED,
            OperationState.RETIRED,
        ):
            continue
        if any(operation.operation_id in item.operation_ids for item in obligations):
            continue
        known = archive.get(operation.configuration_reference)
        full = (
            getattr(known, "full_w", getattr(known, "full_limit_w", None))
            if known is not None
            else None
        )
        if full is not None and full <= 0:
            full = None
        obligations.append(
            RestoreObligation(
                "recovery:"
                + fingerprint(
                    [
                        operation.operation_id,
                        operation.controller_uid,
                        operation.configuration_signature,
                    ]
                )[:32],
                operation.controller_uid,
                operation.configuration_signature,
                operation.configuration_reference,
                "restart_unresolved_operation",
                full,
                operation_ids=(operation.operation_id,),
            )
        )
    return tuple(obligations)


async def reconcile_restart(repository, configuration_archive=None):
    await repository.reconcile_restart()
    obligations = reconstruct_restore_obligations(
        repository.current, configuration_archive
    )
    if obligations != repository.current.restore_obligations:
        await repository.update(
            lambda value: replace(value, restore_obligations=obligations)
        )
    return assess_recovery(repository.current)
