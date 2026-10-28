"""Validate pinned dashboard structure; optionally emit a structural review."""

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.hpvc.dashboard.builder import REFERENCE, parity_dashboard
from custom_components.hpvc.dashboard.presentation import CATALOG


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def differences(a, b, path=""):
    if type(a) is not type(b):
        return [{"path": path, "before": a, "after": b}]
    if isinstance(a, dict):
        result = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                result.append(
                    {"path": path + "/" + k, "before": a.get(k), "after": b.get(k)}
                )
            else:
                result += differences(a[k], b[k], path + "/" + k)
        return result
    if isinstance(a, list):
        result = []
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                result.append(
                    {
                        "path": path + "/" + str(i),
                        "before": a[i] if i < len(a) else None,
                        "after": b[i] if i < len(b) else None,
                    }
                )
            else:
                result += differences(a[i], b[i], path + "/" + str(i))
        return result
    return [] if a == b else [{"path": path, "before": a, "after": b}]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--write-review", type=Path)
    a = p.parse_args()
    native = parity_dashboard()
    lock = json.loads(
        (ROOT / "custom_components/hpvc/dashboard/parity-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert digest(native) == lock["native_structure_sha256"], (
        "Dashboard drift: layout/labels/icons/bindings/conditions/graphs changed"
    )
    assert (
        hashlib.sha256((ROOT / CATALOG["reference"]).read_bytes()).hexdigest()
        == CATALOG["reference_sha256"]
    ), "Canonical reference changed"
    assert (
        hashlib.sha256(
            (ROOT / "frontend/hpvc-dashboard.js").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        == lock["frontend_sha256_lf"]
    ), "Frontend presentation drift"
    actual = json.loads(
        (ROOT / "home assistant/hpvc_native_dashboard.json").read_text(encoding="utf-8")
    )
    assert native == actual, "Generated artifact is stale"
    if a.write_review:
        a.write_review.mkdir(parents=True, exist_ok=True)
        delta = differences(REFERENCE, native)
        (a.write_review / "exact-ui-differences.json").write_text(
            json.dumps(delta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (a.write_review / "entity-mapping.json").write_text(
            json.dumps(CATALOG["bindings"], indent=2) + "\n", encoding="utf-8"
        )
        chunks = [
            '<!doctype html><meta charset="utf-8"><title>HPVC dashboard structural parity review</title><style>body{font:14px system-ui;margin:24px;background:#f5f7f8}section{display:grid;grid-template-columns:1fr 1fr;gap:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px;border:1px solid #ccc}h2{margin-top:32px}</style><h1>HPVC v1.6 / native structural review</h1><p>Deterministic structure, not a Home Assistant screenshot. Missing generation/history capabilities remain blockers.</p>'
        ]
        selections = [
            ("Overview", 0, None),
            ("Inverter configuration", 1, 1),
            ("HBC", 1, 5),
            ("Insights", 0, 8),
            ("Reports", 0, 1),
            ("Maintenance", 1, 7),
        ]
        for title, vi, si in selections:
            left = (
                REFERENCE["views"][vi]
                if si is None
                else REFERENCE["views"][vi]["sections"][si]
            )
            right = (
                native["views"][vi]
                if si is None
                else native["views"][vi]["sections"][si]
            )
            chunks.append(
                "<h2>"
                + html.escape(title)
                + "</h2><section><div><h3>Approved v1.6</h3><pre>"
                + html.escape(json.dumps(left, indent=2, ensure_ascii=False))
                + "</pre></div><div><h3>Native UI</h3><pre>"
                + html.escape(json.dumps(right, indent=2, ensure_ascii=False))
                + "</pre></div></section>"
            )
        (a.write_review / "side-by-side-review.html").write_text(
            "".join(chunks), encoding="utf-8"
        )
    print("Pinned dashboard parity structure: PASS")


if __name__ == "__main__":
    main()
