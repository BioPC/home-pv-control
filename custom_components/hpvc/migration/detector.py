"""Multiple-signal detector. Silence never proves legacy absence."""

from .model import Stage

APPROVED_FINGERPRINT = (
    "f9d15c2057a8e570b6d2823574f6abb5720ed0fdbc5d39d16c3f07e7a41dd555"
)


def detect(inventory, now, expected_fingerprint):
    age = now.age(inventory.observed)
    if age is None or age > 15 or not inventory.reachable or not inventory.complete:
        return Stage.UNKNOWN, "runtime_inventory_unavailable_or_stale"
    if inventory.pending_update or inventory.recovery_pending:
        return Stage.UNKNOWN, "legacy_update_or_recovery_pending"
    if inventory.fingerprint and inventory.fingerprint != expected_fingerprint:
        return Stage.UNKNOWN, "unrecognized_or_changed_HPVC_fingerprint"
    signals = (
        bool(inventory.known_nodes),
        inventory.managed_present,
        bool(inventory.helpers),
        bool(inventory.heartbeat_boot),
        inventory.runtime_status in ("running", "disabled", "fenced"),
    )
    if inventory.fingerprint == expected_fingerprint and sum(signals) >= 2:
        return Stage.DETECTED, "version_bound_independent_signals"
    return Stage.UNKNOWN, "absence_not_proven_by_helper_or_intent_state"
