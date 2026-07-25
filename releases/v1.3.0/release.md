# Home PV Control v1.3.0

## Entity renaming and migration
- Renamed all active `pv_ems_*` runtime entities to `hpvc_*`.
- Renamed diagnostics to `sensor.hpvc_diag_*`.
- Migrated `sensor.hpvc_diag_market_price` to `sensor.hpvc_diag_market_export_price` and added an explicit fresh-install entity ID.
- Renamed the Settings helper to `input_boolean.hpvc_config`.
- Added migration guidance for helpers and external references.

## Latest fixes

- Prevented duplicate HBC-options pause Insights while the configured HBC entity or option list remains unavailable; only availability transitions are logged.
- Added live HBC strategy-option synchronization. HPVC refreshes the HBC option list automatically at startup, after entity changes, and once per minute. The read-only Charge strategy always prefers `Charge` when available; Balanced and Expensive prefer `Dynamic`, preserve valid selections, and skip invalid writes. If the HBC entity or its options are unavailable, the user's HBC toggle remains unchanged; only HBC strategy control and battery-assisted reveal pause while normal PV control continues. When HBC is not detected and the toggle is off, periodic checks skip the option-update script while retaining automatic later detection.
- Isolated optional HBC availability from core PV validation: an unavailable strategy entity or empty option list no longer blocks PV limiting/restore or forces the user's HBC toggle off.
- Removed the repeated system-log warning from the minute option synchronizer; Node-RED now reports availability transitions without log spam.
- Removed the obsolete hard-coded HBC strategy-name assumption. The Charge-zone strategy is now automatically managed and read-only, always preferring `Charge` when available; Balanced and Expensive remain user-selectable.
- Corrected multi-battery Hidden PV Reveal documentation so eligible idle batteries are described as SOC-capped bootstrap contributors.
- Removed an unused missing-sensor accumulator from support-report generation.
- Reordered Decision evaluation so **PV currently limited** appears immediately before **Negative-price mode** in both HTML and TXT reports.
- Clarified report decision evaluation by separating the export-limiting condition from the actual current PV-limited state.
- Corrected the high-SOC Reveal documentation and source comments to match the implemented 200/100/50/25 W SOC bands.
- Enforced the documented 1,000-entry cap on the current-day Node-RED Insights log while preserving the newest entries.
- Fixed the support-report status dot so it reflects the actual HPVC enabled state.
- Removed obsolete report parsing and unused HBC diagnostic context writes.
- Fixed HTML support-report generation after the cleanup left the report header referencing the removed `reportLines` array.

## Upgrade notes
- Replace the Home Assistant package and dashboard, then re-import the Node-RED flow.
- Update external references that still use old entity names.
- Review renamed helper values before enabling HPVC.

## Reliability and control safety
- Separated invalid configuration from temporary live-input outages.
- Prevented inverter writes until all required numeric inputs are available and resumed automatically after recovery.
- Fixed the remembered maximum-charge map runtime error.
- Fixed malformed Node-RED output batching and Reveal Accuracy action attribution.
- Added safe report failure recovery and clean report-helper initialization after restart.

## Charge Priority and multi-battery control
- Added independent per-battery Charge Priority using SOC, charging power, telemetry validity, and known headroom.
- Added SOC hysteresis, high-SOC taper handling, and independent battery recovery.
- Added SOC-capped Reveal probes and support for eligible idle batteries.
- Added independent inverter availability, 5 W write suppression, target rebalancing, and verification diagnostics.

## Hidden PV Reveal
- Made Hidden PV Reveal fully automatic and adaptive across multiple batteries.
- Improved sizing, response detection, pause and recovery behavior, and high-SOC limits.
- Kept normal export limiting and Import Restore active when priority charging is not justified.
- Corrected Reveal Insights and made Reveal Accuracy measure movement toward Target Export.

## Price-source guidance
- Renamed the configured **Market price** display label to **Market/export price**.
- Clarified that the configured field accepts either a raw market-price sensor or a net export-price sensor.
- Standardized the shipped PV limiting price and Node-RED fallback at `€0.00/kWh`.
- Added sensor-type-aware guidance for raw market-price and net export-price sensors.

## Diagnostics and reports
- Unified HTML and TXT reports around one synchronized data model.
- Expanded inverter, battery, Reveal, trigger, sensor-health, and Insight diagnostics without adding control entities.
- Made the HTML report responsive for mobile and desktop.
- Added a strictly on-demand six-column report tile: **Generate report**, **Generating…**, then **View report**.
- Removed all startup, periodic, telemetry-driven, and event-driven report generation.
- Added one-time no-cache viewing and automatic reset to **Generate report** through a same-origin Home Assistant webhook.

## Dashboard and onboarding
- Fixed the HBC Price Zones tooltip marker so it matches the selected column colour and displays as a rounded dot.
- Kept the original single-series HBC Price Zones presentation, including the horizontal **Now** annotation, original spacing, automatic Y-axis and per-column zone colours.
- Added a one-minute chart refresh so the custom current-time annotation stays current between 15-minute HBC price updates.
- Preserved the 48-hour forecast and market-to-all-in conversion: a valid sensor-owned learned model is preferred, with the current `all-in − market` difference used as fallback while learning or relearning.
- Synchronized the dynamic price-type indicator with the graph by using the same cents/euros normalization and finite learned-coefficient checks.
- Kept the generator in a literal YAML block (`|`) to prevent the former permanent **Loading…** failure.
- Improved HBC Price Zones source handling: forecast values are normalized to €/kWh, the current timestamped interval is preferred, invalid or stale sources fall back safely, and exact zero prices remain valid.
- Detected Market forecasts use a restart-safe learned all-in formula after at least 12 hours, eight distinct prices and €0.05/kWh spread; the graph stays live with the current `all-in − market` fallback while learning or relearning.
- Learning uses averaged repeated values and the four lowest/highest distinct prices, preserves exact sensor ownership, and validates monthly with three aligned pairs; graph status, Insights and support-report diagnostics remain synchronized.
- Reorganized Main, Settings, diagnostics, accuracy, graphs, and Insights.
- Added guided first-install onboarding while keeping HBC optional.
- Restored native top badges and the native Home Assistant Power Flow graph.
- Improved accuracy availability handling and simplified the current-day accuracy display.
- Reorganized the Node-RED canvas into clearly labeled functional sections.

## Runtime cleanup and publishing
- Aligned the Node-RED Export Start and Import Restore safety fallbacks with the shipped `−150 W` and `150 W` defaults, including support-report fallbacks.
- Cached one Home Assistant state snapshot per Node-RED evaluation and report build for consistent reads and fewer global-context lookups.
- Restored change-only publishing for status, reason, Last action, and accuracy diagnostics to reduce unnecessary Home Assistant writes.
- Made Last action use a combined status-and-reason signature so repeated adjustments with the same broad status still update when the reason or target changes.
- Removed unused diagnostic and report calculations that had no runtime effect.

## Documentation
- Removed the duplicated Wiki folder and consolidated documentation under `/docs`.
- Reorganized the main documentation with consistent navigation, shipped-default wording, clearer installation steps, and symptom-based troubleshooting.
- Updated installation, configuration, How it Works, troubleshooting, migration, and upgrade guidance.
- Removed obsolete report-generation descriptions.
- Synchronized the changelog, release notes, and this release page.

