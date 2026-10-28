"""Read-only v1.6 registry provenance; no registry or migration capability."""

import json
from pathlib import Path

REFERENCE = json.loads(
    Path(__file__).with_name("legacy_ownership.json").read_text(encoding="utf-8")
)
KNOWN = frozenset(
    (r["domain"], r["platform"], r["unique_id"]) for r in REFERENCE["entities"]
)


def identity(row):
    return (
        row.get("entity_id"),
        row.get("unique_id"),
        row.get("platform"),
        row.get("config_entry_id"),
    )


def classify_ownership(row, bundle):
    """Match exact package identities even after a rename; names prove nothing.

    Both evidence paths require the approved domain/platform/unique-ID tuple.
    These catalogue identities are YAML-owned templates, so a config-entry ID
    cannot be reconciled as their owner: unresolved entries and resolved foreign
    owners both fail closed. Exact operator provenance supplements these facts;
    it never overrides them. Contradictory manifest rows also veto proof.
    """
    domain = row.get("entity_id", "").split(".", 1)[0]
    key = (domain, row.get("platform"), row.get("unique_id"))
    legacy = bundle.get("legacy", {})
    evidence = legacy.get("registry_ownership", [])
    explicit = any(
        isinstance(r, dict) and identity(r) == identity(row) for r in evidence
    )
    manifest_conflict = any(
        isinstance(r, dict)
        and r.get("entity_id") == row.get("entity_id")
        and identity(r) != identity(row)
        for r in evidence
    )
    known = key in KNOWN
    supplied_hash = legacy.get("source_sha256")
    reference_mismatch = (
        legacy.get("approved_v16_package_match") is False
        or (supplied_hash is not None and supplied_hash != REFERENCE["sha256"])
        or (
            legacy.get("package_reference") is not None
            and legacy["package_reference"] != REFERENCE["reference"]
        )
    )
    entry_id = row.get("config_entry_id")
    entry_owned = entry_id not in (None, "")
    entry_matches = (
        [e for e in bundle.get("config_entries", []) if e.get("entry_id") == entry_id]
        if entry_owned
        else []
    )
    unresolved_entry = entry_owned and len(entry_matches) != 1
    duplicates = (
        sum(
            (
                r.get("entity_id", "").split(".", 1)[0],
                r.get("platform"),
                r.get("unique_id"),
            )
            == key
            for r in bundle.get("entity_registry", [])
        )
        > 1
    )
    if known and not (
        entry_owned or reference_mismatch or duplicates or manifest_conflict
    ):
        return dict(
            classification="proven_legacy_hpvc_owned",
            proof="exact_supplied_registry_manifest"
            if explicit
            else "approved_v1.6_unique_id_domain_platform",
            reference=REFERENCE["reference"],
            reference_sha256=REFERENCE["sha256"],
        )
    suspected = (
        known
        or explicit
        or manifest_conflict
        or row.get("entity_id", "").split(".", 1)[-1].startswith("hpvc_")
    )
    return dict(
        classification="unproven_collision" if suspected else "unrelated",
        proof="package_mismatch"
        if reference_mismatch
        else "manifest_registry_identity_mismatch"
        if manifest_conflict
        else "config_entry_ownership_unresolved"
        if unresolved_entry
        else "config_entry_ownership_conflict"
        if entry_owned
        else "duplicate_legacy_identity"
        if duplicates
        else "insufficient_exact_legacy_provenance",
    )


def ownership_inventory(bundle):
    """Include renamed entities as well as occupants of intended native IDs."""
    return [
        dict(
            entity_id=r["entity_id"],
            unique_id=r.get("unique_id"),
            platform=r.get("platform"),
            config_entry_id=r.get("config_entry_id"),
            **classify_ownership(r, bundle),
        )
        for r in bundle.get("entity_registry", [])
    ]
