"""Narrow decoder for captured v1.6 context. No network or service capability."""

from ..codec import SchemaError
from .model import Bridge

REQUIRED = (
    "homePvControlAdapterRequests",
    "homePvControlAdapterScheduler",
    "homePvControlPendingWriteVerification",
    "homePvControlDisableRestoreState",
    "homePvControlNegativePriceHbcOverride",
    "homePvControlAdapterSafetyBlocked",
    "homePvControlAdapterResync",
    "homePvControlRuntimeEvaluationLock",
    "homePvControlUninstallShutdownActive",
    "homePvControlUninstallShutdownStartedAt",
    "homePvControlUninstallShutdownLastEvaluationAt",
    "homePvControlUninstallShutdownCompletedAt",
    "homePvControlAdapterRuntimeOwner",
    "homePvControlAdapterConfigSignatures",
    "homePvControlNightRestoreFullConfirmation",
)


def decode_context_export(
    export,
    *,
    observed,
    controller_bindings,
    hbc_original,
    hbc_current,
    hbc_observed,
    hbc_available,
    master_off,
    fence_receipt=None,
    night_evidence=(),
):
    """The host must retain pre-disable HBC originals independently of clearing context.

    A disabled tab in a flow JSON export is not a runtime deployment receipt.
    A fence receipt must come from the controlled host's complete live inventory.
    """
    if (
        export.get("schema") != "hpvc-migration/1.6.0/1"
        or export.get("complete") is not True
    ):
        raise SchemaError("Incomplete/version-mismatched migration bridge")
    if export.get("foreignHpvcCandidates"):
        raise SchemaError("Unrecognized HPVC-like flows require recovery")
    raw = export.get("raw")
    if not isinstance(raw, dict) or not all(k in raw for k in REQUIRED):
        raise SchemaError("Missing dispatcher context is unknown, never empty")
    requests = raw["homePvControlAdapterRequests"]
    scheduler = raw["homePvControlAdapterScheduler"]
    restore = raw["homePvControlDisableRestoreState"]
    if (
        not isinstance(requests, dict)
        or not isinstance(scheduler, dict)
        or not isinstance(scheduler.get("queue"), list)
        or "busy" not in scheduler
    ):
        raise SchemaError("Unknown v1.6 dispatcher shape")
    if not isinstance(restore, dict) or type(restore.get("active")) is not bool:
        raise SchemaError("Unknown disable restoration lifecycle")
    active = ("legacy-scheduler",) if scheduler["busy"] is not None else ()
    queued = tuple(str(k) for k in requests) + tuple(
        "queue:" + str(i) for i, _ in enumerate(scheduler["queue"])
    )
    pending = (
        ("legacy-verification",)
        if raw["homePvControlPendingWriteVerification"] is not None
        else ()
    )
    obligations = ("legacy-restore",) if restore["active"] else ()
    hbc_owned = raw["homePvControlNegativePriceHbcOverride"] is not None
    unknown = bool(
        raw["homePvControlAdapterSafetyBlocked"]
        or raw["homePvControlAdapterResync"]
        or raw["homePvControlRuntimeEvaluationLock"]
    )
    if raw["homePvControlAdapterRuntimeOwner"] != export["runtimeBoot"]:
        raise SchemaError("Legacy dispatcher runtime owner is not bound")
    if night_evidence:
        night = export.get("night") or {}
        confirmation = raw["homePvControlNightRestoreFullConfirmation"]
        if (
            night.get("active") is not True
            or not isinstance(confirmation, dict)
            or night.get("confirmation") != confirmation
            or confirmation.get("confirmed") is not True
            or confirmation.get("fullTotal")
            != sum(b.full_w for b in controller_bindings)
            or any(
                n.reference != confirmation.get("signature")
                or n.confirmed.utc * 1000 != confirmation.get("confirmedAt")
                or n.current_night_observed != observed
                or not n.independently_verified
                for n in night_evidence
            )
        ):
            raise SchemaError(
                "Night Restore receipt is not the source-confirmed current fleet proof"
            )
    token = ""
    fenced = False
    if fence_receipt:
        if set(fence_receipt) != {
            "fingerprint",
            "runtime_boot",
            "transaction_id",
            "challenge",
            "token",
            "all_owned_tabs_disabled",
            "runtime_inventory_complete",
            "auto_resume_blocked",
        }:
            raise SchemaError("Unknown fence receipt fields")
        if (
            fence_receipt["fingerprint"] != export["fingerprint"]
            or fence_receipt["runtime_boot"] != export["runtimeBoot"]
            or fence_receipt["transaction_id"] != export["transactionId"]
            or fence_receipt["challenge"] != export["challenge"]
        ):
            raise SchemaError("Unbound fence deployment receipt")
        fenced = (
            all(
                fence_receipt[k] is True
                for k in (
                    "all_owned_tabs_disabled",
                    "runtime_inventory_complete",
                    "auto_resume_blocked",
                )
            )
            and export.get("commandTabsDisabled") is True
        )
        token = fence_receipt["token"] if fenced else ""
    return Bridge(
        "hpvc-migration/1.6.0/1",
        export["runtimeBoot"],
        export["fingerprint"],
        export["transactionId"],
        export["challenge"],
        observed,
        complete=True,
        master_off=master_off is True,
        disabled_at=float(raw["homePvControlUninstallShutdownStartedAt"]) / 1000,
        evaluated_at=float(raw["homePvControlUninstallShutdownLastEvaluationAt"])
        / 1000,
        active=active,
        queued=queued,
        potentially_issued=active,
        pending_verification=pending,
        restore_obligations=obligations,
        hbc_owned=hbc_owned,
        hbc_restored=not hbc_owned and hbc_original == hbc_current,
        hbc_available=hbc_available,
        hbc_original=hbc_original,
        hbc_current=hbc_current,
        hbc_observed=hbc_observed,
        quiescent=not any((active, queued, pending, obligations, unknown)),
        safety_unknown=unknown,
        fence_token=token,
        command_capability=not fenced,
        auto_resume_blocked=fenced,
        night_evidence=tuple(night_evidence),
        controller_bindings=tuple(controller_bindings),
    )
