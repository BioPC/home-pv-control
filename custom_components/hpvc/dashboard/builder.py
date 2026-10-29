"""Reference-derived Lovelace presentation; no HA mutation capability."""

import copy
import json
import re
from pathlib import Path

from ..codec import SchemaError
from .presentation import CATALOG, ui_key

ROOT = Path(__file__).parent
REFERENCE = json.loads((ROOT / "reference.json").read_text(encoding="utf-8"))
BINDINGS = {r["source"]: r for r in CATALOG["bindings"]}
STATUS = "sensor.hpvc_status"
RUNTIME = "sensor.hpvc_effective_inverter_runtime"
ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
REPORT_SECTIONS = (
    "Executive Summary",
    "Live Status",
    "Decision Evaluation",
    "Today’s Insights",
    "Power Control",
    "Today’s Accuracy",
    "HBC & Battery Status",
    "Inverters",
    "Sensor Health",
    "Control Settings",
)


def history_generator(entity):
    value = {
        "binary_sensor.hpvc_pv_limited": "p.limited === true ? 1 : p.limited === false ? 0 : null",
        "binary_sensor.hpvc_cooldown_active": "p.cooldown === true ? 1 : p.cooldown === false ? 0 : null",
        "binary_sensor.hpvc_charge_priority_active": "p.priority === 'Active' ? 1 : ['Off','Waiting'].includes(p.priority) ? 0 : null",
    }.get(entity, "null")
    return (
        "const points = entity.attributes.ui_dashboard_data?.history || []; const result = [];\n"
        "for (let i=0; i<points.length; i++) { const p=points[i]; const value="
        + value
        + ";\n"
        "result.push([p.at*1000,value]); if (!points[i+1] || points[i+1].at > p.at+90) result.push([(p.at+90)*1000,null]); } return result;"
    )


def live_report():
    sections = []
    for index, heading in enumerate(REPORT_SECTIONS):
        body = (
            "{% set sections = state_attr('sensor.hpvc_status','ui_report_sections') or {} %}"
            "{% if " + repr(heading) + " in sections %}"
            "{% for label, value in sections[" + repr(heading) + "].items() %}"
            "<p><strong>{{ label | replace('_', ' ') | e }}:</strong> "
            "{{ (value if value is not none else 'Unavailable') | e }}</p>"
            "{% endfor %}{% else %}Unavailable: native report observer has not supplied a fresh snapshot.{% endif %}"
        )
        sections.append(
            # Keep each disclosure in one HTML block. HA sanitizes Markdown
            # tokens separately, so blank-line Markdown bodies escape details.
            f"<details{' open' if index == 0 else ''}><summary>{heading}</summary>{body}</details>"
        )
    return {"type": "markdown", "title": "Reports", "content": "\n\n".join(sections)}


def parity_dashboard(actual_ids=None):
    actual_ids = actual_ids or {}
    if any(
        k not in CATALOG["native_entities"]
        or not ENTITY.fullmatch(v)
        or k.split(".")[0] != v.split(".")[0]
        for k, v in actual_ids.items()
    ):
        raise SchemaError("Invalid native dashboard entity mapping")

    def eid(entity):
        return actual_ids.get(entity, entity)

    def rewrite(text):
        for source, b in sorted(BINDINGS.items(), key=lambda kv: -len(kv[0])):
            if b["target"]:
                text = text.replace(source, eid(b["target"]))
                continue
            value = f"state_attr('{eid(STATUS)}', '{b['attribute']}')"
            attrs = f"(state_attr('{eid(STATUS)}', 'ui_source_attributes') or {{}}).get('{source}', {{}}).get("
            for q in ("'", '"'):
                text = text.replace(
                    f"states({q}{source}{q})",
                    f"(({value} | string) if {value} is not none else 'unknown')",
                )
                text = text.replace(f"is_state({q}{source}{q},", f"({value} ==")
                text = text.replace(f"state_attr({q}{source}{q},", attrs)
        # The v1.6 setup templates construct slot IDs dynamically.
        for a, b in (
            ("input_number.hpvc_", "number.hpvc_"),
            ("input_select.hpvc_", "select.hpvc_"),
            ("input_text.hpvc_", "text.hpvc_"),
        ):
            text = text.replace(a, b)
        for intended, actual in actual_ids.items():
            text = re.sub(
                r"(?<![a-z0-9_.])" + re.escape(intended) + r"(?![a-z0-9_])",
                actual,
                text,
            )
        return (
            text.replace("Hoymiles detected", "Hoymiles Detected")
            .replace("Enphase detected", "Enphase Detected")
            .replace("Home PV Control (v1.6.0)", "Home PV Control (2.0 development)")
            .replace(
                "Once setup and all required live inputs are valid, HPVC switches on automatically.",
                "Settings save native user intent. Physical control remains disabled in this build.",
            )
            .replace(
                "All required inputs are ready, but HPVC is off because it was switched off or its Node-RED flows were removed. Press <b>Enable HPVC</b> to start control.",
                "HPVC enable intent is off. <b>Enable HPVC</b> saves native configuration intent; physical control remains disabled in this development build.",
            )
        )

    def convert(node, path=""):
        if isinstance(node, list):
            return [convert(v, path + "/" + str(i)) for i, v in enumerate(node)]
        if not isinstance(node, dict):
            return rewrite(node) if isinstance(node, str) else node
        original = copy.deepcopy(node)
        # Only selection changes are implemented by the custom navigation card.
        if node.get("entity") in (
            "script.hpvc_previous_inverter",
            "script.hpvc_next_inverter",
        ):
            return {
                "type": "custom:hpvc-inverter-navigation",
                "direction": "previous" if "previous" in node["entity"] else "next",
                "entity": eid("select.hpvc_selected_inverter"),
                "runtime_entity": eid(RUNTIME),
                "icon": node["icon"],
                "name": node.get("name", ""),
            }
        if (
            node.get("entity") == "sensor.hpvc_inverter_limit_entity_display"
            and "secondary_info" in node
        ):
            return {
                "type": "custom:hpvc-limit-entity-row",
                "entity": eid(node["entity"]),
                "attribute": node["secondary_info"],
                "name": "Limit entity:",
                "icon": "mdi:lock-outline",
            }
        if node.get("action") in ("perform-action", "call-service", "toggle"):
            return {"action": "none"}
        if node.get("action") == "url" and "/local/" in node.get("url_path", ""):
            return {"action": "none"}
        result = {k: convert(v, path + "/" + k) for k, v in node.items()}
        source = original.get("entity")
        binding = BINDINGS.get(source)
        if binding:
            if binding["target"]:
                result["entity"] = eid(binding["target"])
            else:
                result["entity"] = eid(STATUS)
                if (
                    "state" in node
                    or "state_not" in node
                    or "above" in node
                    or "below" in node
                ):
                    result["attribute"] = binding["attribute"]
                    result.setdefault(
                        "condition",
                        "numeric_state"
                        if "above" in node or "below" in node
                        else "state",
                    )
                elif node.get("type") in ("attribute", "simple-entity") or (
                    "type" not in node
                    and ("/entities/" in path or path.endswith("/row"))
                ):
                    result.update(type="attribute", attribute=binding["attribute"])
                elif node.get("type") in ("tile", "entity"):
                    result["state_content"] = binding["attribute"]
                    result["features"] = []
                    for action in (
                        "tap_action",
                        "icon_tap_action",
                        "hold_action",
                        "double_tap_action",
                    ):
                        result[action] = {"action": "none"}
        if node.get("type") == "attribute":
            result["icon"] = "mdi:lock-outline"
        if node.get("type") == "custom:apexcharts-card":
            if "HBC Price Intervals" in node.get("header", {}).get("title", ""):
                result.setdefault("apex_config", {}).setdefault("noData", {})[
                    "text"
                ] = "Price data unavailable or stale"
            if node.get("header", {}).get("title", "").endswith("Power Flow"):
                result["graph_span"] = "12h"
            for before, series in zip(node.get("series", []), result.get("series", [])):
                b = BINDINGS.get(before.get("entity"))
                if b and not b["target"]:
                    series["entity"] = eid(STATUS)
                    series["attribute"] = b["attribute"]
                    if "data_generator" in before:
                        # Preserve the reference generator, with its optional HBC
                        # data observed through a read-only native attribute.
                        proxy = f"({{state: entity.attributes[{json.dumps(b['attribute'])}], attributes: entity.attributes.ui_source_attributes?.[{json.dumps(before['entity'])}] || {{}}}})"
                        generator = re.sub(
                            r"\bentity\b", proxy, before["data_generator"]
                        )
                        if "entity.state" in before["data_generator"]:
                            generator = (
                                f"const raw = entity.attributes[{json.dumps(b['attribute'])}];\n"
                                "if (raw === null || raw === undefined || raw === '' || raw === 'unknown' || raw === 'unavailable') return [];\n"
                                + generator
                            )
                        series["data_generator"] = generator
                        series.pop("attribute", None)
                    else:
                        series["transform"] = (
                            "if (x === null || x === undefined || x === '' || x === 'unknown' || x === 'unavailable') return null;\n"
                            + series.get("transform", "return Number(x);")
                        )
                        if "group_by" in series:
                            series["group_by"]["fill"] = "null"
                        series["fill_raw"] = "null"
        if node.get("type") == "history-graph":
            return {
                "type": "custom:apexcharts-card",
                "graph_span": f"{node.get('hours_to_show', 6)}h",
                "header": {"show": True, "title": "HPVC control/state history"},
                "series": [
                    {
                        "entity": eid(STATUS),
                        "attribute": ui_key(r["entity"]),
                        "name": r["name"],
                        "type": "line",
                        "curve": "stepline",
                        "transform": "return x === 'on' ? 1 : x === 'off' ? 0 : null;",
                        "data_generator": history_generator(r["entity"]),
                        "extend_to": False,
                    }
                    for r in node["entities"]
                ],
            }
        if "content" in node:
            content = node["content"]
            if "input_text.hpvc_insight_" in content:
                result["content"] = (
                    "{% set data = state_attr('sensor.hpvc_status','ui_dashboard_data') or {} %}"
                    "{% for entry in data.get('insights', []) %}**{{ entry.category }}** · {{ entry.time }}\n\n{{ entry.message }}\n\n"
                    "{% else %}No native Insights recorded today.{% endfor %}"
                )
            if "**Total inverters:**" in content:
                result["content"] = (
                    "{% set rows = state_attr('"
                    + eid(RUNTIME)
                    + "','controller_ui_json') or [] %}{% set ns = namespace(auto=0) %}{% for row in rows %}{% if row.source == 'auto' %}{% set ns.auto = ns.auto + 1 %}{% endif %}{% endfor %}{% set total = state_attr('"
                    + eid(RUNTIME)
                    + "','effective_count') | int(0) %}**Total inverters:** _{{ ns.auto }} auto-detected · {{ [0, total - ns.auto] | max }} manual_"
                )
            if "No PV inverters available" in content:
                result["content"] = (
                    '<ha-alert alert-type="warning">No PV inverters available. HPVC is monitoring only.</ha-alert>'
                )
            if "Home PV Control unavailable" in content:
                result["content"] = (
                    '<ha-alert alert-type="info">HPVC is monitoring only. Physical control is disabled in this development build. {% if state_attr(\''
                    + eid(STATUS)
                    + "','ui_telemetry_ready') != 'on' %}Telemetry is unavailable or stale; power values are not reliable.{% endif %}</ha-alert>"
                )
            if path.startswith(
                ("/views/1/sections/6", "/views/1/sections/7")
            ) and not content.lstrip().startswith("###"):
                result["content"] = (
                    "{% set status = state_attr('sensor.hpvc_status','ui_maintenance') or {} %}{% for key, value in status.items() %}**{{ key | replace('_',' ') }}:** {{ value }}\n\n{% else %}Native maintenance observations unavailable.{% endfor %}\n\nLegacy update, reload, remove and uninstall operations are unavailable in native development mode."
                )
            if (
                path.startswith("/views/0/sections/5")
                and "No eligible control-accuracy samples" in content
            ):
                result["content"] = (
                    "{% set data = state_attr('sensor.hpvc_status','ui_dashboard_data') or {} %}{% set m = data.get('accuracy', {}) %}"
                    "Measured: {{ m.get('measured', 0) }} · Unavailable: {{ m.get('unavailable', 0) }} · Duplicate observations: {{ m.get('duplicate', 0) }}\n\n"
                    "Sampled coverage: {{ m.get('coverage_percent') if m.get('coverage_percent') is not none else 'Unavailable' }}%\n\n"
                    "MAE: {{ m.get('mae_w') if m.get('mae_w') is not none else 'Unavailable' }} W · RMSE: {{ m.get('rmse_w') if m.get('rmse_w') is not none else 'Unavailable' }} W\n\n"
                    "Native observed target-band accuracy; unavailable without fresh verified execution and unique grid samples. Estimated v1.6 loss attribution is unavailable."
                )
        return result

    dashboard = convert(REFERENCE)
    # Monitoring-only messaging is useful even with missing inputs or no slots.
    dashboard["views"][0]["sections"][0]["cards"][1]["conditions"] = [
        {
            "condition": "numeric_state",
            "entity": eid(STATUS),
            "attribute": "ui_effective_count",
            "below": 1,
        }
    ]
    report = live_report()
    report["content"] = rewrite(report["content"])
    dashboard["views"][0]["sections"][8]["cards"].append(report)

    # Plain state/numeric_state conditions work in both supported HA frontends.
    def compatible(value):
        if isinstance(value, list):
            for child in value:
                compatible(child)
        elif isinstance(value, dict):
            if "content" in value:
                value["content"] = rewrite(value["content"])
            if value.get("header", {}).get("title") == "HPVC control/state history":
                # Bound legend wrapping independently of Apex's initial canvas
                # width; HA 2026 sections can shrink after the chart mounts.
                value["all_series_config"] = {"show": {"legend_value": False}}
                value["apex_config"] = {
                    "legend": {
                        "width": 280,
                        "horizontalAlign": "left",
                        "fontSize": "12px",
                        "itemMargin": {"horizontal": 4, "vertical": 3},
                    }
                }
                value["series"].append(
                    {
                        "entity": eid(STATUS),
                        "name": "Executed mode: Normal=0 Charge=1 Limit=2",
                        "type": "line",
                        "curve": "stepline",
                        "extend_to": False,
                        "transform": "return x === null ? null : Number(x);",
                        "data_generator": history_generator("mode").replace(
                            "const value=null;",
                            "const value=({Normal:0,Charge:1,Limit:2})[p.mode] ?? null;",
                        ),
                    }
                )
            if (
                value.get("condition") in ("state", "numeric_state")
                and value.get("entity") == eid(STATUS)
                and "attribute" in value
            ):
                attribute = value.pop("attribute")
                value["entity"] = eid("sensor.hpvc_dashboard_" + attribute)
            for child in value.values():
                compatible(child)

    compatible(dashboard)
    return dashboard
