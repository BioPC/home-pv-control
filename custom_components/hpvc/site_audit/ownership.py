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

    Retain dev.8's explicitly supplied exact-tuple ownership manifest channel.
    A known conflicting config entry, duplicate identity, or supplied package
    mismatch vetoes both channels. An inferred YAML identity requires no entry.
    The supplied manifest is an operator provenance assertion, not inferred
    from entity names or generated from arbitrary registry rows.
    """
    domain = row.get("entity_id", "").split(".", 1)[0]
    key = (domain, row.get("platform"), row.get("unique_id"))
    legacy = bundle.get("legacy", {})
    evidence = legacy.get("registry_ownership", [])
    explicit = any(
        isinstance(r, dict) and identity(r) == identity(row) for r in evidence
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
    conflicting_entry = bool(
        entry_id
        and any(e.get("entry_id") == entry_id for e in bundle.get("config_entries", []))
    )
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
    if (
        known
        and not entry_id
        or explicit
        and row.get("unique_id")
        and row.get("platform") == "template"
    ) and not (reference_mismatch or conflicting_entry or duplicates):
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
        or row.get("entity_id", "").split(".", 1)[-1].startswith("hpvc_")
    )
    return dict(
        classification="unproven_collision" if suspected else "unrelated",
        proof="package_mismatch"
        if reference_mismatch
        else "config_entry_ownership_conflict"
        if conflicting_entry
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
