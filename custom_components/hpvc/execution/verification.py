"""Independent read-only evidence interpretation. No service completion is invented."""

from dataclasses import dataclass
from enum import StrEnum
from ..codec import Record
from ..control.models import LimitUnit
from .models import VerificationStatus, VerificationEvidence
from ..inverter.base import finite


class EvidenceKind(StrEnum):
    HA = "ha_readback"
    OPENDTU = "opendtu_api"
    ENPHASE = "enphase_readback"
    COMMAND_CACHE = "command-cache"
    STARTUP_ASSUMPTION = "startup-full-assumption"
    LEGACY_HELPER = "legacy_helper"


class VerificationOutcome(StrEnum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    IDENTITY_MISMATCH = "identity_mismatch"
    STALE = "stale"
    NOT_READY = "not_ready"
    VALUE_MISMATCH = "value_mismatch"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class EvidenceCandidate(Record):
    operation_id: str
    controller_uid: str
    configuration_signature: str
    owner_epoch: str
    dispatch_id: str | None
    kind: EvidenceKind
    native_value: float | None
    received_at_utc: float | None
    reported_at_utc: float | None = None
    poll_started_at_utc: float | None = None
    unit: LimitUnit = LimitUnit.WATTS
    max_power_w: float | None = None
    relative_limit: float | None = None
    command_status: str | None = None
    device_id: str | None = None
    serial: str | None = None
    enabled: bool | None = None
    production_mode: bool | None = None


@dataclass(frozen=True)
class VerificationResult(Record):
    outcome: VerificationOutcome
    verdict: VerificationStatus
    reason: str
    evidence: VerificationEvidence | None = None
    observed_limit_w: float | None = None


def verify_operation(
    operation,
    candidate,
    *,
    now,
    full_power_w,
    expected_device_id=None,
    expected_serial=None,
    step_w=None,
    deadband_w=25,
):
    def result(outcome, verdict, reason, observed=None):
        return VerificationResult(outcome, verdict, reason, observed_limit_w=observed)

    if candidate.kind in (
        EvidenceKind.COMMAND_CACHE,
        EvidenceKind.STARTUP_ASSUMPTION,
        EvidenceKind.LEGACY_HELPER,
    ):
        return result(
            VerificationOutcome.UNVERIFIABLE,
            VerificationStatus.UNAVAILABLE,
            "Not independent physical evidence",
        )
    identity = (
        candidate.operation_id == operation.operation_id
        and candidate.controller_uid == operation.controller_uid
        and candidate.configuration_signature == operation.configuration_signature
        and candidate.owner_epoch == operation.owner_epoch
        and candidate.dispatch_id == operation.dispatch_id
    )
    if not identity:
        return result(
            VerificationOutcome.IDENTITY_MISMATCH,
            VerificationStatus.UNKNOWN,
            "Operation/controller/configuration/dispatch ownership mismatch",
        )
    dispatched = finite(operation.dispatch_started_at_utc)
    target = finite(operation.representable_controller_target_w)
    if (
        dispatched is None
        or dispatched <= 0
        or operation.dispatch_id is None
        or target is None
    ):
        return result(
            VerificationOutcome.UNKNOWN,
            VerificationStatus.UNKNOWN,
            "No authoritative physical dispatch identity/target",
        )
    received = finite(candidate.received_at_utc)
    if received is None or received < dispatched or received > now + 60:
        return result(
            VerificationOutcome.STALE,
            VerificationStatus.UNKNOWN,
            "Invalid or pre-dispatch receive time",
        )
    is_enphase = operation.adapter_kind in ("enphase", "enphase_dpel")
    if is_enphase and (
        candidate.enabled is not True or candidate.production_mode is not True
    ):
        return result(
            VerificationOutcome.NOT_READY,
            VerificationStatus.PENDING,
            "DPEL enable and Production must be independently observed",
        )
    base = max(2, min(deadband_w, 10))
    step = finite(step_w)
    tolerance = max(base, step / 2 + 0.5 if step is not None and step > 0 else 0)
    if candidate.kind == EvidenceKind.OPENDTU:
        if operation.adapter_kind not in ("hoymiles", "opendtu_absolute"):
            return result(
                VerificationOutcome.IDENTITY_MISMATCH,
                VerificationStatus.UNKNOWN,
                "OpenDTU evidence for a different adapter",
            )
        if expected_device_id and candidate.device_id != expected_device_id:
            return result(
                VerificationOutcome.IDENTITY_MISMATCH,
                VerificationStatus.UNKNOWN,
                "OpenDTU device mismatch",
            )
        if expected_serial and candidate.serial != expected_serial:
            return result(
                VerificationOutcome.IDENTITY_MISMATCH,
                VerificationStatus.UNKNOWN,
                "OpenDTU established serial mismatch",
            )
        polled = finite(candidate.poll_started_at_utc)
        if (
            polled is None
            or polled < dispatched
            or received < polled
            or not 0 <= now - received <= 120
        ):
            return result(
                VerificationOutcome.STALE,
                VerificationStatus.PENDING,
                "OpenDTU poll must start after dispatch and remain fresh",
            )
        maximum = finite(candidate.max_power_w)
        relative = finite(candidate.relative_limit)
        if (
            maximum is None
            or maximum <= 0
            or relative is None
            or not 0 <= relative <= 100
            or str(candidate.command_status or "").strip().lower() != "ok"
        ):
            return result(
                VerificationOutcome.UNKNOWN,
                VerificationStatus.PENDING,
                "OpenDTU command status/rating/relative limit is not credible",
            )
        observed = maximum * relative / 100
        tolerance = max(tolerance, maximum * 0.01 + 0.5)
    else:
        reported = finite(candidate.reported_at_utc)
        if (
            reported is None
            or reported < dispatched
            or reported <= 0
            or not -60 <= now - reported <= 180
            or now - received > 180
        ):
            return result(
                VerificationOutcome.STALE,
                VerificationStatus.PENDING,
                "Readback must be fresh and post-dispatch",
            )
        observed = finite(candidate.native_value)
        if observed is None:
            return result(
                VerificationOutcome.UNKNOWN,
                VerificationStatus.PENDING,
                "Readback unavailable or non-numeric",
            )
        if candidate.unit == LimitUnit.PERCENT:
            if full_power_w <= 0 or not 0 <= observed <= 100:
                return result(
                    VerificationOutcome.UNKNOWN,
                    VerificationStatus.PENDING,
                    "Invalid percentage readback",
                )
            observed = observed / 100 * full_power_w
    if abs(observed - target) > tolerance:
        return result(
            VerificationOutcome.VALUE_MISMATCH,
            VerificationStatus.PENDING,
            "Independent readback differs from effective target",
            observed,
        )
    evidence = VerificationEvidence(
        "evidence:" + operation.operation_id + ":" + str(received),
        operation.controller_uid,
        operation.configuration_signature,
        operation.operation_id,
        candidate.kind.value,
        VerificationStatus.VERIFIED,
        observed,
        candidate.reported_at_utc,
        candidate.poll_started_at_utc,
        received,
        "owner=" + operation.owner_epoch + ";dispatch=" + operation.dispatch_id,
        tolerance,
    )
    return VerificationResult(
        VerificationOutcome.CONFIRMED,
        VerificationStatus.VERIFIED,
        "Matching independent physical limit evidence",
        evidence,
        observed,
    )


def readback_candidate(operation, view):
    observed = view.observation.limit
    candidate = view.candidate
    kind = (
        EvidenceKind.ENPHASE
        if view.configuration.identity.adapter.value == "enphase"
        else EvidenceKind.HA
    )
    if view.current_source.value == "command-cache":
        kind = EvidenceKind.COMMAND_CACHE
    if view.current_source.value == "startup-full-assumption":
        kind = EvidenceKind.STARTUP_ASSUMPTION
    # observation.limit is already normalized to Watts by the adapter.
    return EvidenceCandidate(
        operation.operation_id,
        view.configuration.identity.uid,
        view.configuration_signature,
        operation.owner_epoch,
        operation.dispatch_id,
        kind,
        observed.value,
        observed.received_at_utc,
        observed.reported_at_utc,
        unit=LimitUnit.WATTS,
        device_id=candidate.device_id if candidate else None,
        serial=candidate.serial if candidate else None,
        enabled=view.observation.enabled,
        production_mode=view.observation.production_mode,
    )


def opendtu_candidate(operation, view, status):
    return EvidenceCandidate(
        operation.operation_id,
        status.controller_uid,
        view.configuration_signature,
        operation.owner_epoch,
        operation.dispatch_id,
        EvidenceKind.OPENDTU,
        None,
        status.received_at_utc,
        poll_started_at_utc=status.poll_started_at_utc,
        max_power_w=status.max_power,
        relative_limit=status.limit_relative,
        command_status=status.limit_set_status,
        device_id=status.device_id,
        serial=status.serial,
    )
