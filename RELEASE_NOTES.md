# Home PV Control v1.3.0 — Release Notes

## Entity migration
- Renamed all runtime entities to the `hpvc_*` prefix.
- Renamed diagnostic entities to `sensor.hpvc_diag_*`.
- Migrated `sensor.hpvc_diag_market_price` to `sensor.hpvc_diag_market_export_price` and added an explicit fresh-install entity ID.
- Renamed the Settings helper to `input_boolean.hpvc_config`.
- Existing installations must update external references.
- Review migrated helper values before enabling HPVC.

## Latest fixes

- Prevented duplicate HBC-options pause Insights while the configured HBC entity or option list remains unavailable; only availability transitions are logged.
- Added live HBC strategy-option synchronization. HPVC refreshes the HBC option list automatically at startup, after entity changes, and once per minute. The read-only Charge strategy always prefers `Charge` when available; Balanced prefers `Dynamic` and Expensive prefers `Self-consumption`; both preserve valid selections and skip invalid writes. If the HBC entity or its options are unavailable, the user's HBC toggle remains unchanged; only HBC strategy control and battery-assisted reveal pause while normal PV control continues. When HBC is not detected and the toggle is off, periodic checks skip the option-update script while retaining automatic later detection.
- Isolated optional HBC availability from core PV validation: an unavailable strategy entity or empty option list no longer blocks PV limiting/restore or forces the user's HBC toggle off.
- Removed the repeated system-log warning from the minute option synchronizer; Node-RED now reports availability transitions without log spam.
- Removed the obsolete hard-coded HBC strategy-name assumption. The Charge-zone strategy is now automatically managed and read-only, always preferring `Charge` when available; Balanced and Expensive remain user-selectable.
- Corrected multi-battery Hidden PV Reveal documentation so eligible idle batteries are described as SOC-capped bootstrap contributors.
- Removed an unused missing-sensor accumulator from support-report generation.
- Reordered Decision evaluation so **PV currently limited** appears immediately before **Negative-price mode** in both HTML and TXT reports.
- Removed the duplicated Wiki folder and consolidated documentation under `/docs`.
- Improved documentation navigation, terminology, installation clarity, and symptom-based troubleshooting.
- Clarified report decision evaluation by separating the export-limiting condition from the actual current PV-limited state.
- Corrected the high-SOC Reveal documentation and source comments to match the implemented 200/100/50/25 W SOC bands.
- Enforced the documented 1,000-entry cap on the current-day Node-RED Insights log while preserving the newest entries.
- Aligned the Node-RED Export Start and Import Restore safety fallbacks with the shipped `−150 W` and `150 W` defaults.
- Cached one Home Assistant state snapshot per Node-RED evaluation for consistent reads and fewer global-context lookups.
- Restored change-only publishing for status, reason, last action, and accuracy diagnostics to reduce unnecessary Home Assistant state writes.
- Fixed Last action publishing so repeated adjustments with the same status still update when the control reason or target changes.
- Removed unused diagnostic and report calculations that had no runtime effect.
- Fixed the support-report status dot so it reflects the actual HPVC enabled state.
- Removed obsolete report parsing and unused HBC diagnostic context writes.
- Fixed HTML support-report generation after the cleanup left the report header referencing the removed `reportLines` array.
- Improved Target Accuracy attribution while retaining its four existing factors.

## Upgrade notes
- Replace `home assistant/hpvc_config.yaml`.
- Replace `home assistant/hpvc_dashboard.yaml`.
- Re-import `node-red/hpvc_flow.json`.
- Update automations, dashboards, scripts, and external references using old entity names.
- Review renamed helper values before enabling HPVC.
- Generate and open a new report to verify the three-state report workflow.
- Restored the complete original HBC Price Zones ApexCharts presentation block, including its exact horizontal `Now` annotation placement, chart spacing, single-series rendering and automatic rounded Y-axis layout; only the YAML JavaScript block style was changed from folded to literal to prevent the loading failure.

## Reliability and safety
- Restore defaults now preserves the user's current HBC Strategy Control on/off state instead of forcing it off.
- HPVC now validates required inputs before controlling inverter limits.
- Missing telemetry pauses control safely until recovery.
- Improved restart handling, cooldown logic, validation, and `sun.sun` night restore.
- Fixed `rememberedMaxChargePowers is not defined`.
- Fixed HBC status output batching.
- Fixed Reveal Accuracy attribution.
- Report failures now reset report helpers and create a persistent notification.

## Charge Priority
- Batteries are evaluated independently using SOC, charging power, telemetry validity, and charge headroom.
- One unavailable or tapering battery no longer blocks another.
- Stable telemetry remains usable during unchanged values.
- Eligible idle batteries can start charging automatically.
- Maximum charge power is retained through temporary telemetry loss.
- Inverters are controlled independently with post-clamp balancing and write verification.

## Hidden PV Reveal
- Daily Reveal Accuracy is watt-weighted, so larger probes count more than tiny probes.
- Expected response is capped by an independent pre-reveal PV-availability estimate, so a weak observed response cannot make itself appear fully successful.
- Stale grid/PV telemetry and unsettled inverter-limit writes are excluded from scoring.
- Reveal allowance is summed across all eligible HBC batteries.
- Below **90% SOC**, allowance follows available charger headroom.
- Probe limits are **200 W (90–94%)**, **100 W (95–96%)**, **50 W (97–98%)**, **25 W (99%)**, and **0 W (100%)**.
- Every probe is verified before another reveal is allowed.
- Final reveal is limited by Target Export margin, remaining hidden PV, and the internal **800 W** safety cap.
- Batteries are managed independently; tapering one battery does not pause the others.
- Stale grid telemetry now creates a Reveal Insight instead of affecting Reveal Accuracy.

## Price-source guidance
- Renamed the configured **Market price** display label to **Market/export price**.
- Clarified that the configured field accepts either a raw market-price sensor or a net export-price sensor.
- Standardized the shipped PV limiting price and Node-RED fallback at `€0.00/kWh`.
- Added sensor-type-aware guidance for raw market-price and net export-price sensors.

## Diagnostics and reports
- HTML and TXT reports now use the same data model.
- Expanded inverter, battery, Reveal, and Sensor Health diagnostics.
- Improved report accuracy and consistency.
- Target Accuracy now samples only during active limiting.
- Genuine **0%** accuracy remains valid.
- Reports are generated only on demand.
- Report workflow is **Generate → Generating → View**.

## Dashboard
- Fixed the HBC Price Zones tooltip marker so it matches the selected green, yellow, red, or blue column and displays as a rounded dot.
- Kept the original single-series HBC Price Zones presentation, including the horizontal **Now** annotation, original spacing, automatic Y-axis and per-column zone colours.
- Added a one-minute chart refresh so the custom current-time annotation stays current between 15-minute HBC price updates.
- Preserved the 48-hour forecast and market-to-all-in conversion: a valid sensor-owned learned model is preferred, with the current `all-in − market` difference used as fallback while learning or relearning.
- Synchronized the dynamic price-type indicator with the graph by using the same cents/euros normalization and finite learned-coefficient checks.
- Kept the generator in a literal YAML block (`|`) to prevent the former permanent **Loading…** failure.
- Improved HBC Price Zones source handling: forecast values are normalized to €/kWh, the current timestamped interval is preferred, invalid or stale sources fall back safely, and exact zero prices remain valid.
- Detected Market forecasts use a restart-safe learned all-in formula after at least 12 hours, eight distinct prices and €0.05/kWh spread; the graph stays live with the current `all-in − market` fallback while learning or relearning.
- Learning uses averaged repeated values and the four lowest/highest distinct prices, preserves exact sensor ownership, and validates monthly with three aligned pairs; graph status, Insights and support-report diagnostics remain synchronized.
- Reorganized Main, Settings, Diagnostics, Accuracy, Graphs, and Insights.
- Renamed **Restore recommended settings** to **Restore defaults**.
- Improved badge layout and conditional HBC visibility.
- Added native history graphs and current-day accuracy tiles.
- Improved report tile workflow and layout.
- Reorganized the Node-RED canvas without changing functionality.

## Documentation
- Updated installation, configuration, operation, troubleshooting, migration, and upgrade guides.
- Removed obsolete references to automatic report generation.
- Standardized all v1.3.0 documentation.

