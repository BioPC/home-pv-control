"""Emit auditable per-section/card classifications and mapping, with explicit gaps."""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.hpvc.dashboard.builder import REFERENCE, parity_dashboard
from custom_components.hpvc.dashboard.presentation import CATALOG


def walk(value, path=""):
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from walk(item, path + "/" + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, path + "/" + str(index))


def main():
    target = ROOT / "review"
    target.mkdir(exist_ok=True)
    native = parity_dashboard()
    nodes = dict(walk(native))
    rows = []
    for path, before in walk(REFERENCE):
        if "type" not in before:
            continue
        if before.get("type") in ("state", "numeric_state", "attribute", "and", "or"):
            continue
        after = nodes.get(path, {})
        text = json.dumps(before, ensure_ascii=False)
        category = "identical" if before == after else "functionally equivalent"
        reason = (
            "Exact configuration retained"
            if before == after
            else "Native entity/attribute substitution; reference position and presentation retained"
        )
        if any(
            token in text
            for token in (
                "hpvc_daily_",
                "hpvc_insight_",
                "hpvc_report_",
                "hpvc_generate_report",
                "history-graph",
                "hpvc_charge_priority_active",
            )
        ):
            category = "missing/blocker"
            reason = "Native report/Insights/accuracy or executed control-state collection is unavailable; unknown/no-data display and disabled actions"
        if path.startswith(("/views/1/sections/6", "/views/1/sections/7")):
            category = "intentionally different"
            reason = "Legacy installation/update/reload/uninstall actions disabled; native development maintenance disclosure"
        if before.get("graph_span") == "6h" and "Power Flow" in text:
            category = "intentionally different"
            reason = "User-requested 12-hour view; native observed attributes, missing values are gaps"
        if before.get("entity") in (
            "script.hpvc_next_inverter",
            "script.hpvc_previous_inverter",
        ):
            category = "functionally equivalent"
            reason = "Custom selection-only navigation wraps within the effective native controller count"
        if after.get("type") == "custom:hpvc-limit-entity-row":
            category = "functionally equivalent"
            reason = "Full ID on second line, lock-outline, horizontal scroll, no editable field/action"
        if before.get("type") == "sections":
            reason += "; same view and section order; enclosed capability gaps listed separately"
        rows.append(
            {
                "path": path,
                "label": before.get("title")
                or before.get("name")
                or before.get("heading")
                or before.get("type", "section"),
                "classification": category,
                "reason": reason,
            }
        )
    # Sections have paths with five slash separators.
    for vi, view in enumerate(REFERENCE["views"]):
        for si, section in enumerate(view["sections"]):
            path = f"/views/{vi}/sections/{si}"
            related = [r for r in rows if r["path"].startswith(path + "/")]
            category = (
                "missing/blocker"
                if any(r["classification"] == "missing/blocker" for r in related)
                else "intentionally different"
                if any(
                    r["classification"] == "intentionally different" for r in related
                )
                else "functionally equivalent"
            )
            rows.append(
                {
                    "path": path,
                    "label": f"{view['title']} section {si + 1}",
                    "classification": category,
                    "reason": "Position retained; classification includes enclosed cards",
                }
            )
    rows.append(
        {
            "path": f"/views/0/sections/8/cards/{len(native['views'][0]['sections'][8]['cards']) - 1}",
            "label": "Native Reports preview addition",
            "classification": "missing/blocker",
            "reason": "Ten collapsible report sections added; report generation/export and daily collection unavailable",
        }
    )
    with (target / "section-card-parity.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("path", "label", "classification", "reason")
        )
        writer.writeheader()
        writer.writerows(rows)
    (target / "section-card-parity.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (target / "entity-mapping.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=sorted({k for r in CATALOG["bindings"] for k in r})
        )
        writer.writeheader()
        writer.writerows(CATALOG["bindings"])
    print(
        f"{len(rows)} section/card checklist entries; {len(CATALOG['bindings'])} source bindings"
    )


if __name__ == "__main__":
    main()
