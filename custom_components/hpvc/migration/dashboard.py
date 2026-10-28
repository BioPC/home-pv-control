"""Native Lovelace artifact generation using verified actual entity IDs."""

import re
from ..codec import SchemaError
from ..storage import strict_json

ENTITY = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+$")


def native_dashboard(actual_ids=None, configuration=None, history=None):
    actual_ids = actual_ids or {}
    if any(
        not ENTITY.fullmatch(k) or not ENTITY.fullmatch(v)
        for k, v in actual_ids.items()
    ):
        raise SchemaError("Invalid entity mapping")

    def eid(n):
        return actual_ids.get(n, n)

    def ref(n):
        return "'" + eid(n) + "'"

    def md(content):
        return dict(type="markdown", content=content)

    runtime = eid("sensor.hpvc_effective_inverter_runtime")
    home = [
        md("## Home PV Control 2.0\nDevelopment dry-run: physical writes remain Off."),
        dict(
            type="entities",
            entities=[
                eid("switch.hpvc_enabled"),
                eid("select.hpvc_selected_inverter"),
                eid("sensor.hpvc_status"),
                eid("sensor.hpvc_reason"),
                eid("sensor.hpvc_migration_state"),
                eid("binary_sensor.hpvc_physical_writes_authorized"),
            ],
        ),
        dict(
            type="conditional",
            conditions=[dict(entity=runtime, state="0")],
            card=md(
                "**No inverters configured or discovered.** Configure a controller before control can become ready."
            ),
        ),
    ]
    nav = []
    for i in range(1, 11):
        nav.append(
            dict(
                type="conditional",
                conditions=[
                    dict(condition="numeric_state", entity=runtime, above=i - 1)
                ],
                card=dict(
                    type="button",
                    name=f"PV{i}",
                    icon="mdi:solar-panel",
                    tap_action=dict(
                        action="navigate", navigation_path=f"/hpvc-native/pv{i}"
                    ),
                ),
            )
        )
    home.append(dict(type="grid", columns=5, square=False, cards=nav))
    home.append(
        dict(
            type="entities",
            title="HBC permissions and status",
            entities=[
                eid("switch.hpvc_control_hbc_strategy"),
                eid("switch.hpvc_negative_price_hbc_charge"),
                eid("sensor.hpvc_migration_state"),
            ],
        )
    )
    home.append(
        md(
            "HBC strategy: {{ states('input_select.house_battery_strategy') }}\n\nCharge goal: {{ states('input_select.house_battery_strategy_charge_goal') }}"
        )
    )
    views = [dict(title="Overview", path="overview", cards=home)]
    for i in range(1, 11):
        prefix = f"hpvc_pv{i}_"
        row = (
            "{% set rows = state_attr("
            + ref("sensor.hpvc_effective_inverter_runtime")
            + ", 'controller_ui_json') or [] %}{% set row = rows["
            + str(i - 1)
            + "] if rows|length >= "
            + str(i)
            + " else {} %}"
        )
        status = md(
            row
            + f"### PV{i}\n**Inverter status:** {{{{ row.get('status', 'Not configured') }}}}\n\nSource: {{{{ row.get('source', 'manual') }}}} · {{{{ row.get('control_method', '') }}}}"
        )
        # A separate label line followed by a fenced code line preserves the full
        # entity value. HA Markdown's preformatted block scrolls horizontally.
        limit = md(
            row + "**Limit entity**\n\n```text\n{{ row.get('limit_entity', '') }}\n```"
        )
        cards = [
            status,
            limit,
            dict(
                type="entities",
                entities=[
                    eid("switch." + prefix + "control"),
                    eid("sensor." + prefix + "actual_limit"),
                    eid("sensor." + prefix + "auto_identity"),
                ],
            ),
            dict(
                type="conditional",
                conditions=[
                    dict(
                        entity=eid("sensor." + prefix + "auto_identity"),
                        state="unknown",
                    )
                ],
                card=dict(
                    type="entities",
                    title="Manual controller settings",
                    entities=[
                        eid(d + "." + prefix + k)
                        for d, k in [
                            ("select", "control_method"),
                            ("select", "limit_unit"),
                            ("text", "limit_number"),
                            ("number", "full_limit"),
                            ("number", "low_limit"),
                            ("text", "action"),
                            ("text", "value_field"),
                            ("text", "fixed_data_json"),
                            ("text", "target_json"),
                            ("text", "pre_actions_json"),
                            ("text", "post_actions_json"),
                            ("text", "readback_entity"),
                        ]
                    ],
                ),
            ),
            md(
                row
                + "{% if row.get('source') == 'auto' %}Automatic identity and power-range provenance are maintained by discovery.{% endif %}"
            ),
            dict(
                type="button",
                name="Overview",
                tap_action=dict(
                    action="navigate", navigation_path="/hpvc-native/overview"
                ),
            ),
        ]
        views.append(dict(title=f"PV{i}", path=f"pv{i}", visible=False, cards=cards))

    def series(keys, extra=()):
        result = [eid(n) for n in extra]
        if configuration:
            result += [
                getattr(configuration, k) for k in keys if getattr(configuration, k)
            ]
        return list(dict.fromkeys(result))

    views.append(
        dict(
            title="Power Control",
            path="power-control",
            cards=[
                dict(
                    type="history-graph",
                    title="Power Control",
                    hours_to_show=24,
                    entities=series(
                        ("grid_power_sensor", "pv_power_sensor"),
                        ("sensor.hpvc_pv1_actual_limit",),
                    ),
                )
            ],
        )
    )
    views.append(
        dict(
            title="Price Interval",
            path="price-interval",
            cards=[
                dict(
                    type="history-graph",
                    title="Price Interval",
                    hours_to_show=24,
                    entities=series(
                        ("market_price_sensor", "all_in_price_sensor"),
                        ("number.hpvc_pv_limiting_price",),
                    ),
                )
            ],
        )
    )
    insight = "No compatible current-day Insights history imported."
    reports = "No compatible current-day report snapshot imported."
    if history:
        insight = (
            "Imported day: "
            + str(history.local_date)
            + "\n\n```json\n"
            + history.insights_json
            + "\n```"
        )
        reports = (
            "Imported day: "
            + str(history.local_date)
            + "\n\n```json\n"
            + history.report_history_json
            + "\n```"
        )
        strict_json(history.insights_json)
        strict_json(history.report_history_json)
    views += [
        dict(
            title="Insights",
            path="insights",
            cards=[
                dict(type="entities", entities=[eid("switch.hpvc_insights_enabled")]),
                md(insight),
            ],
        ),
        dict(title="Reports", path="reports", cards=[md(reports)]),
    ]
    return dict(title="Home PV Control", views=views)
