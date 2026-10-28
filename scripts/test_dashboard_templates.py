"""Render every dashboard Markdown template with synthetic states, never live HA."""

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from test_enphase_ha_templates import States, build_env

from custom_components.hpvc.dashboard.builder import parity_dashboard
from tests.dashboard.dashboard_fixture import SCENARIOS, fixture, visible_nodes


def walk(value, path=""):
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from walk(item, path + "/" + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, path + "/" + str(index))


def main():
    dashboard = parity_dashboard()
    count = 0
    review = [
        "<!doctype html><meta charset='utf-8'><title>HPVC synthetic fixture review</title><style>body{font:15px system-ui;max-width:1000px;margin:24px auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px}section{border-top:2px solid #888}</style><h1>Synthetic fixture Markdown review</h1><p>Rendered Jinja source, not HA frontend screenshots. No production evidence. Charts/custom cards require separate HA frontend verification.</p>"
    ]
    results = []
    for scenario, native_data in [
        (s, enabled) for enabled in (False, True) for s in SCENARIOS
    ]:
        f = fixture(scenario, native_data=native_data)
        scenario += " (native data)" if native_data else " (observer unavailable)"
        states = States()
        for entity, row in f["states"].items():
            states.add(entity, row["state"], row["attributes"])
        env = build_env(states)
        rendered = {}
        for path, node in walk(dashboard):
            if node.get("type") == "markdown":
                try:
                    rendered[path] = env.from_string(node["content"]).render()
                except Exception as error:
                    raise AssertionError(f"{scenario} {path}: {error}") from error
                count += 1
        visible = {}
        for index, view in enumerate(dashboard["views"]):
            visible.update(
                {f"/views/{index}" + p: n for p, n in visible_nodes(view, f["states"])}
            )
        review.append("<section><h2>" + html.escape(scenario) + "</h2>")
        for path, text in rendered.items():
            if path in visible:
                review.append(
                    "<h3>"
                    + html.escape(path)
                    + "</h3><pre>"
                    + html.escape(text)
                    + "</pre>"
                )
        review.append("</section>")
        results.append(
            {
                "scenario": scenario,
                "templates": len(rendered),
                "visible_nodes": len(visible),
                "rendered": True,
            }
        )
    target = ROOT / "review"
    target.mkdir(exist_ok=True)
    (target / "fixture-template-review.html").write_text(
        "".join(review), encoding="utf-8"
    )
    (target / "fixture-results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{count} Markdown template renders passed across {len(SCENARIOS)} synthetic scenarios in two observer states"
    )


if __name__ == "__main__":
    main()
