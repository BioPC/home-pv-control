# Native dashboard parity, local development package

Historical layout-stage document. The current data implementation and remaining
acceptance gaps are documented in [dashboard-data-parity.md](dashboard-data-parity.md).

Verdict: **VISUAL_PARITY_INCOMPLETE**. This is a local UI implementation based on
published commit `7c49d2691139dac45364dfa7eacc647bfd27e36f`. It is not a production
release or an authorization for installation, handoff or physical writes.

## Artifacts and reproduction

`home assistant/hpvc_dashboard.yaml` is the unmodified approved v1.6 reference.
`custom_components/hpvc/dashboard/reference.json` preserves that source using YAML
1.2 boolean semantics (including `on`, `off` and ApexCharts `y` keys).
`home assistant/hpvc_native_dashboard.json` is generated from that reference:

```console
python scripts/build_native_dashboard.py
python scripts/validate_dashboard_parity.py --write-review review
python scripts/build_dashboard_review.py
python scripts/test_dashboard_templates.py
node scripts/test_dashboard_frontend.cjs
python -B scripts/test_foundation.py
```

The template-render check needs PyYAML and Jinja2, as the existing legacy template
checks do. The foundation suite and dashboard generator remain dependency-free.
The old migration dashboard API is unchanged; CLI configuration/history snapshot
exports can still use `--compatibility-layout`.

`review/entity-mapping.json` and `.csv` enumerate every literal source binding.
Native targets are exact entity substitutions. Projection entries identify the
status attribute holding a read-only observation or an explicit unknown value.
Dynamic PV1..PV10 setup expressions replace the `input_number.hpvc_`,
`input_select.hpvc_`, `input_text.hpvc_` prefixes with `number.hpvc_`, `select.hpvc_`,
`text.hpvc_`; their slot fields are also individually catalogued.
The two navigation scripts become a native select-only custom card, rather than
reintroducing helper scripts. Legacy service/action references are disabled.

If a separate future test installation has registry-suffixed IDs, supply a JSON
dictionary of intended native IDs to actual native IDs with `--mapping path.json`.
Mapping domains are validated; no registry edit is performed. Read-only status
attributes are presentation values, never readiness or authorization evidence.
No legacy HPVC YAML helper state is read by the new presentation module.
Existing external HBC battery/strategy/price entities remain optional observations.

## Frontend setup instructions for a future isolated test system

These are instructions only; this task did not install or change any HA system.
In a separately authorized test installation, the module
`frontend/hpvc-dashboard.js` would be copied to `config/www/hpvc-dashboard.js` and
registered as a JavaScript module resource at `/local/hpvc-dashboard.js`.
The generated JSON can be used as the dashboard raw configuration.
The reference's ApexCharts resource remains required (`custom:apexcharts-card`).
No automatic resource registration or dashboard/registry write is implemented.

This layout targets the attribute conditions supported by the frontend paired
with **HA 2026.10.4**. HA 2025.12's frontend does not support those conditions;
its dashboard compatibility remains a blocker. Backend foundation support is
separate from dashboard frontend compatibility. Sources:

- [HA 2026.10.4 frontend pin](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/components/frontend/manifest.json)
- [Frontend 20260930.5 attribute conditions](https://github.com/home-assistant/frontend/blob/20260930.5/src/panels/lovelace/common/validate-condition.ts)
- [Frontend 20251203.3 conditions](https://github.com/home-assistant/frontend/blob/20251203.3/src/panels/lovelace/common/validate-condition.ts)
- [ApexCharts configuration](https://github.com/RomRider/apexcharts-card)

## Preserved presentation and intentional differences

Main then Settings, 10 then 8 sections, reference card order, headings/icons and
groupings are retained. The Reports live preview is appended to Insights.
All relevant Settings remain visible; no old settings switch is required.
Native configuration switches/numbers/selects/texts save intent only, subject to
the unchanged development transport veto. Enable HBC remains conditional.

The inverter Limit entity row has a lock icon, `Limit entity:` first line and
full entity ID second line, horizontal scroll, keyboard focus and no editable
input or action. Navigation wraps only over the effective fleet. Detected
Hoymiles/Enphase wording and the zero-inverter monitoring warning are retained.
The total shows auto-detected count before manual count.

Power Flow intentionally changes from 6h to the requested 12h. Colors, names and
48h HBC price appearance are retained. Native status attributes provide observed
values. Stale/missing values are gaps, never invented zeroes; actual zero remains
zero. Power and battery observations expire after 180 seconds, prices after two
hours. Price interval fields are sanitized, not arbitrary attributes forwarded.
New history starts only once a future test installation records these native
attributes; no legacy recorder history is transferred.

The native development status explicitly says monitoring only. Legacy automatic
enable/resume promises are removed. Legacy Generate/View report, update, reload,
Node-RED removal and uninstall actions are disabled. Maintenance text explains
native development maintenance. No action requests a production operation.

## Exact remaining gaps

1. Native report generation/export/publication and View report workflow are not
   implemented. The ten collapsible sections are a live read-only preview only.
2. Native current-day Insights and accuracy collection are not implemented.
   Original cards show unknown/no data; this is not parity approval.
3. Executed Normal / Charge / Limit and cooldown history is unavailable in this
   read-only stage. Timeline frames use steplines with unknown gaps. No executed
   Charge Priority state is fabricated; it explicitly remains unavailable.
4. Legacy maintenance operations have no enabled native equivalent in this build.
5. HA 2025.12 frontend compatibility is unresolved, as described above.
6. No live HA frontend or pixel/spacing comparison was performed. Structural
   side-by-side JSON and synthetic rendered Markdown are review aids, not HA
   screenshots. Browser integration/resource loading needs an isolated HA test.

The per-section/card classifications in `review/section-card-parity.csv` compare
configuration and intended presentation. “Functionally equivalent” entries still
need frontend acceptance; no entry implies production testing.

## Regression and safety boundaries

Eleven synthetic scenarios cover zero, one, multiple (auto and manual), Hoymiles,
Enphase, mixed Hoymiles/Enphase, missing HBC, stale and unavailable telemetry,
monitoring-only and partial discovery. These are synthetic UI fixtures, not a
production export. Template rendering is Jinja-level; DOM tests use an isolated
model and chart generators execute in Node. Neither replaces HA frontend QA.

Only the existing status sensor gains read-only attributes. No new integration
entity is introduced. Production transport authorization remains **false**.
Control, allocation, HBC decisions, dispatcher/executor/recovery, migration,
Node-RED, OpenDTU and physical write sources are unchanged. The reference SHA and
structure/frontend pins detect drift; the authorized preservation-hash update
is confined to the generated dashboard artifact. GitHub and production systems
were not modified for this UI task.
