"""Consume local production exports and write review artifacts locally only."""

import argparse, csv, json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.hpvc.site_audit.schema import (
    MAX_BYTES,
    empty_export,
    redact,
    digest,
)
from custom_components.hpvc.site_audit.engine import audit_site
from custom_components.hpvc.site_audit.render import render_report
from custom_components.hpvc.site_audit.capture import project_observations
from custom_components.hpvc.legacy import MAPPINGS
from custom_components.hpvc.codec import SchemaError


def read_json(p):
    if p.stat().st_size > MAX_BYTES:
        raise SchemaError("Input file exceeds audit bound")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def references(path):
    if path.stat().st_size > MAX_BYTES:
        raise SchemaError("Reference file exceeds bound")
    text = path.read_text(encoding="utf-8-sig")
    mapping = {m.source: m.destination for m in MAPPINGS}
    found = sorted(set(re.findall(r"[a-z0-9_]+\.[a-z0-9_]+", text)))
    return dict(
        source_file=path.name,
        sha256=digest(text),
        references=[
            dict(
                old_entity_id=e,
                proposed_native_entity=mapping.get(e),
                requires_review=bool(mapping.get(e) and mapping[e] != e),
            )
            for e in found
            if e in mapping or ".hpvc_" in e
        ],
        raw_content_exported=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path)
    p.add_argument(
        "--raw-ha-export",
        type=Path,
        help="Project a local authenticated-browser raw read export before auditing",
    )
    p.add_argument(
        "--empty-site",
        action="store_true",
        help="Generate explicit UNKNOWN report without inventing production data",
    )
    p.add_argument("--output-directory", type=Path, required=True)
    p.add_argument("--flows", type=Path)
    p.add_argument("--legacy-context", type=Path)
    p.add_argument(
        "--full-flow-export",
        action="store_true",
        help="Declare that supplied export includes the full current flow inventory",
    )
    p.add_argument("--node", default="node")
    p.add_argument("--reference-file", type=Path, action="append", default=[])
    p.add_argument("--native-configuration", type=Path)
    p.add_argument("--opendtu-capture", type=Path, action="append", default=[])
    a = p.parse_args()
    if sum(bool(x) for x in (a.input, a.raw_ha_export, a.empty_site)) != 1:
        raise SchemaError(
            "Choose a production input, raw HA read export or explicit empty-site mode"
        )
    if a.raw_ha_export:
        raw = read_json(a.raw_ha_export)
        if raw.get("schema") != "hpvc-ha-read-export/1":
            raise SchemaError("Unknown raw read-export schema")
        bundle = project_observations(
            states=raw["states"],
            entities=raw["entity_registry"],
            devices=raw["device_registry"],
            entries=raw["config_entries"],
            ha_version=raw["ha"]["version"],
            now=raw["collected_at_utc"],
            coverage={
                "states": True,
                "entity_registry": True,
                "device_registry": True,
                "config_entries": True,
            },
        )
    else:
        bundle = read_json(a.input) if a.input else empty_export()
    inputs = [
        q.resolve()
        for q in [
            a.input,
            a.raw_ha_export,
            a.flows,
            a.legacy_context,
            a.native_configuration,
            *a.reference_file,
            *a.opendtu_capture,
        ]
        if q
    ]
    targets = [
        a.output_directory / n
        for n in (
            "site-snapshot.json",
            "site-readiness.json",
            "site-readiness-report.txt",
            "import-preview.csv",
            "registry-proposal.json",
            "external-references.json",
        )
    ]
    if any(q.resolve() in inputs for q in targets):
        raise SchemaError("Audit output cannot overwrite an input")
    if a.flows:
        if a.legacy_context:
            read_json(a.legacy_context)  # bound before the scanner reads it
        result = subprocess.run(
            [
                a.node,
                str(ROOT / "audit_tools/inspect_legacy.cjs"),
                str(a.flows),
                str(a.legacy_context) if a.legacy_context else "-",
                "complete" if a.full_flow_export else "partial",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        if result.returncode:
            raise SchemaError(
                "Read-only flow inspection failed; raw flow/error content is not exported"
            )
        bundle["legacy"] = json.loads(result.stdout)
    if a.native_configuration:
        bundle["native_configuration"] = read_json(a.native_configuration)
    for path in a.opendtu_capture:
        bundle.setdefault("opendtu", []).append(read_json(path))
    refs = [references(q) for q in a.reference_file]
    if a.flows:
        refs.append(references(a.flows))
    bundle["references"] = refs
    bundle.setdefault("coverage", {})["reference_files"] = [
        r["source_file"] for r in refs
    ]
    changed = []
    bundle = redact(bundle, changes=changed)
    bundle["redactions"] = sorted(set(bundle.get("redactions", []) + changed))
    report = audit_site(bundle, now=time.time())
    a.output_directory.mkdir(parents=True, exist_ok=True)
    for name, value in [
        ("site-snapshot.json", bundle),
        ("site-readiness.json", report),
        ("registry-proposal.json", report["registry_migration"]),
        ("external-references.json", report["references"]),
    ]:
        (a.output_directory / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    (a.output_directory / "site-readiness-report.txt").write_text(
        render_report(report), encoding="utf-8"
    )
    rows = report["import_preview"]["settings"]
    with (a.output_directory / "import-preview.csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        if rows:
            keys = sorted({k for r in rows for k in r})
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    print(
        "Read-only audit verdict:",
        report["overall_verdict"],
        "; local artifacts:",
        a.output_directory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            "Audit stopped:",
            type(error).__name__,
            "; inspect inputs locally, no raw secret/error payload is logged",
            file=sys.stderr,
        )
        raise SystemExit(1)
