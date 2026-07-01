# Home PV Control v1.1.1

## Changes

- Removed the dynamic input dropdown dependency and replaced with an input-text based entity configuration, keeping the existing helper names.
- Changed recommended `initial:` values to all Home Assistant helpers.
- Minor dashboard fixes and cleanup.

---

# Home PV Control v1.1.0

> v1.0.7 was never released. This v1.1.0 package includes all changes originally planned for v1.0.7 plus the final v1.1.0 HBC battery-aware Hidden PV Reveal improvements.

## Highlights

- Hidden PV Reveal for HBC/grid-following batteries.
- Configurable Hidden PV Reveal step: 50–250 W, default 100 W.
- Improved multi-inverter reveal allocator.
- HBC battery-aware reveal gating.
- HBC Batteries max-charge-power awareness.
- Cleaner Debug Insights with pause, resume, completed and restore-finished messages.
- 48-hour HBC strategy price graph and 20-row Insights dashboard.

## Timeline of changes since v1.0.6

### 1. Debug and dashboard improvements

- Expanded Debug Insights from 10 to 20 items.
- Removed repetitive cooldown-finished entries.
- Fixed cooldown Insight time formatting to 24-hour `HH:MM:SS`.
- Added a 48-hour HBC strategy price graph in €/kWh.
- Added user-threshold-based graph colors and a compact price-zone legend.

### 2. Cooldown and PV recovery fixes

- PV decisions can run immediately after cooldown expires.
- Heavy import while PV is limited now uses normal fast import recalculation.
- Mixed-inverter Hidden PV Reveal is avoided unless all configured inverters are below full output.

### 3. HBC strategy and price hysteresis

- HBC strategy notification wording now correctly describes entry thresholds and hysteresis exits.
- HBC strategy control remains optional and can be disabled when HBC is unavailable.

### 4. Hidden PV Reveal

- Added Hidden PV Reveal to gradually expose curtailed PV while an HBC battery is charging.
- Added a user-configurable reveal step in PV Export Control.
- Set reveal step range to 50–250 W with a 100 W default.
- Improved the allocator so reveal steps are preserved across multi-inverter systems.
- Added HBC battery charging gate.
- Added battery count fallback when `input_number.house_battery_count` is missing.
- Honored `house_battery_count = 0` when explicitly configured.
- Ignored missing Marstek battery power sensors.
- Added max-charge-power awareness using `number.marstek_mX_max_charge_power`.
- Added one-time pause, resume and completed Insights for reveal state changes.
- Added a specific reason when reveal is active but the increase is below deadband.

### 5. Startup and diagnostics

- Added an Insight when Home Assistant inputs finish restoring and control resumes.
- Added compact debug JSON fields including `at_max_chg`.
- Fixed `revealHiddenPv` scope so startup/waiting states cannot crash the flow.

### 6. Internal cleanup

- Removed unused battery detail code.
- Removed unused active battery summary string building.
- Reorganized documentation and removed the unreleased v1.0.7 release file.

## Files changed

- `node-red/pv_ems_flow.json`
- `home assistant/pv_ems_config.yaml`
- `home assistant/pv_ems_dashboard.yaml`
- `README.md`
- `CHANGELOG.md`
- `RELEASE_NOTES.md`
- `releases/v1.1.0/release.md`

## Upgrade note

Replace the Home Assistant config, dashboard and Node-RED flow from this package. Import the Home Assistant package first, reload or restart Home Assistant, then import and deploy the Node-RED flow.
