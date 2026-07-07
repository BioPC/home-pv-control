## v1.2.0

> v1.1.2 was never released. All work that was temporarily staged as v1.1.2 is included in this v1.2.0 public release. Users can upgrade directly from v1.1.1 to v1.2.0.

### Final documentation and HACS metadata cleanup
- Fixed `hacs.json` so it is valid JSON instead of YAML.
- Updated configuration docs to describe first-run default seeding instead of removed `initial:` values.
- Added v1.2.0 Hidden PV Reveal, stability score, sun recovery, negative-price and final-restore behavior to the how-it-works documentation.
- Fixed troubleshooting references to removed or nonexistent entities.
- Removed the redundant `anyBelowFull` alias in the Node-RED flow.

### Cooldown debug sensor fix
- Added compact `cd` cooldown flag to the last-calculation JSON.
- Updated `binary_sensor.pv_ems_cooldown_active` to read the compact cooldown flag so the dashboard Cooldown active indicator works again.

### Reveal deadband handling
- Hidden PV Reveal now applies the PV Adjustment Deadband to the total reveal request instead of each inverter share.
- Proportional inverter distribution is preserved for small reveal steps.
- Every proportional inverter change is applied once the total reveal exceeds the deadband.

### First-run defaults persistence fix
- Removed Node-RED flow-context default initialization.
- Added `input_boolean.pv_ems_defaults_applied` as a Home Assistant first-run marker.
- Added a Home Assistant startup automation that applies recommended defaults only once on a new install.
- Helpers still have no `initial:` values, so user-edited values restore normally after Home Assistant restarts.

### Default seeding cleanup
- First-run default seeding now uses a 60 second cooldown to match the README recommended default.

### Adaptive Hidden PV Reveal foundation
- Added Adaptive Hidden PV Reveal for grid-following batteries.
- Reveal can restore hidden PV while PV is limited and an HBC battery is charging.
- Added mixed-inverter support so reveal works when one inverter is already closer to full than another.
- Added HBC battery-count handling using `input_number.house_battery_count`.
- Added safe fallback to one battery when `input_number.house_battery_count` is missing.
- Honored explicit `input_number.house_battery_count = 0`; fallback is used only when the helper is missing.
- Ignored missing HBC battery power sensors instead of treating them as idle `0 W` batteries.
- Added HBC max-charge awareness using `number.marstek_mX_max_charge_power`.
- Used the active charging-battery headroom instead of summing all battery headroom, matching HBC behavior where only one battery charges at a time.

### Automatic Adaptive Hidden PV Reveal
- Removed the old user-configurable Hidden PV Reveal step / Maximum Hidden PV Reveal Step helper before public release.
- Removed Recommended Values sensors and the Apply Recommended Values UI before public release.
- Removed the export-gap warning card, helper sensor, binary sensor, and auto-fix script before public release.
- Hidden PV Reveal is now fully automatic with no user-configured reveal power.
- Added an internal non-configurable **800 W safety cap**.
- Balanced reveal amount is calculated from:
  - active charging-battery headroom,
  - Target Export margin plus dynamic tolerance,
  - remaining hidden PV,
  - internal 800 W safety cap.
- Dynamic tolerance is calculated as:
  - `min(max(deadband × 2, active battery headroom × 0.25), 150 W)`.
- Export Start decides when PV limiting begins.
- Target Export decides the reveal recovery window.

### Reveal stability and solar response
- Added a real-PV response guard.
- After each reveal, HPVC verifies that actual PV production increased enough.
- If raising inverter limits does not increase real PV production, HPVC pauses further reveal instead of repeatedly increasing limits when the sun cannot produce more.
- Added reveal response history so one noisy sample does not immediately pause reveal.
- Added a reveal stability score from **0–100%**:
  - good response raises the score,
  - weak response lowers it slightly,
  - poor response lowers it strongly,
  - reveal pauses below 40%.
- Added sun-recovery detection so reveal can resume when PV production rises again or export increases.

### Restore and import behavior
- Added final exact restore after Hidden PV Reveal completes.
- If one inverter is still slightly below its configured full limit, HPVC sends one final per-inverter restore command.
- Fixed import recalculation so high grid import no longer lowers PV limits when all inverters are already restored to full.
- Kept the normal PV Adjustment Deadband for regular control decisions.

### Diagnostics and dashboard
- Added improved Insights for reveal pause, resume and completion decisions.
- Pause Insights now include measured PV response, required PV response and stability score.
- Added compact debug JSON fields for reveal diagnostics.
- Added `sensor.hpvc_advanced_debug`, based on compact JSON from `input_text.pv_ems_last_targets_json`.
- Kept debug JSON compact so it fits the Home Assistant input-text length limit.

### Runtime and packaging fixes
- Fixed Node-RED function scope issues so debug fields cannot crash the function node.

## v1.1.1

- Maintenance release based on v1.1.0.
- Updated `pv_ems_config.yaml`, `pv_ems_dashboard.yaml`, and `node-red/pv_ems_flow.json` with the latest uploaded fixes.
- Keeps the v1.1.x helper names compatible while improving input-text based entity configuration.
- Changed recommended `initial:` values to all Home Assistant helpers.
- Minor dashboard fixes and cleanup.
- Added `input_text.pv_ems_battery_strategy_entity` to the settings-changed watch list so editing the HBC strategy entity re-runs the flow immediately instead of waiting up to 15s.
- Added explicit validation for a negative inverter minimum power (`low_limit`); it is now reported as a configuration error instead of silently dropping the inverter from control.
- Aligned `pv_ems_config.yaml` default values, the documentation's default-values table, and `hacs.json` domain list (removed unused `automation`, added `binary_sensor`) so shipped config, docs, and packaging metadata all agree.

## v1.1.0

> v1.0.7 was never released. All planned v1.0.7 work has been merged into this v1.1.0 release. Users can upgrade directly from v1.0.6 to v1.1.0.

### Timeline of changes

#### Debug and dashboard polish
- Expanded Debug Insights from 10 to 20 items.
- Removed repetitive cooldown-finished entries from Insights so the history stays focused on useful events.
- Fixed cooldown insight time formatting to use 24-hour `HH:MM:SS` format.
- Added a 48-hour HBC strategy price graph using all-in prices in €/kWh.
- Added graph zone colors based on the configured Charge and Expensive price thresholds.
- Added a compact price-zone legend for Charge, Balanced and Expensive HBC strategy zones.
- Updated dashboard text for Hidden PV Reveal and v1.1.0 behavior.

#### Cooldown and PV recalculation behavior
- Allowed PV decisions immediately after cooldown expires instead of blocking the first post-cooldown evaluation.
- Fixed hidden-PV reveal so heavy grid import uses the normal fast import-recalculation path.
- Fixed mixed-inverter reveal behavior by only using Hidden PV Reveal when all configured inverters are below full output.
- Fixed PV recalculation to avoid losing recovery speed during significant import while PV is limited.

#### HBC strategy selection
- Improved HBC strategy notification wording during price hysteresis so entry and exit threshold messages are factually correct.
- Kept HBC strategy control optional; HPVC still works as a standalone PV controller when HBC is unavailable.

#### Hidden PV Reveal
- Added Hidden PV Reveal for grid-following batteries: when PV is limited and export is small, HPVC can gradually reveal extra PV so an HBC battery can see more available solar power.
- Added configurable Hidden PV Reveal step in the PV Export Control section.
- Set Hidden PV Reveal step range to 50–800 W with 100 W default.
- Improved the reveal allocator so small reveal steps are preserved across multi-inverter setups instead of being lost to per-inverter deadband.
- Added HBC battery-charging gate: reveal only runs when HBC strategy control is enabled and at least one active HBC battery is charging.
- Added HBC battery-count handling using `input_number.house_battery_count`.
- Added safe fallback to one battery when `input_number.house_battery_count` is missing.
- Honored an explicit `input_number.house_battery_count = 0`; fallback to one battery is used only when the helper is missing.
- Ignored missing HBC battery power sensors instead of treating them as idle `0 W` batteries.
- Added HBC Batteries max-charge awareness using `number.marstek_mX_max_charge_power`.
- Paused Hidden PV Reveal when active batteries are already at or near their configured maximum charge power.
- Added one-time pause and resume Insights for Hidden PV Reveal battery-charge availability.
- Added one-time completion Insight when Hidden PV Reveal fully restores PV output.
- Added clear reason text when Hidden PV Reveal is active but the calculated increase is below the PV deadband.
- Stopped repeat logging of Hidden PV Reveal pause messages; pause/resume/completion events now log only on state changes.

#### Startup and diagnostics
- Added a startup Insight when Home Assistant inputs finish restoring and HPVC resumes control.
- Added compact debug JSON fields for battery power, battery charging state, charge headroom and max-charge state.
- Added compact `at_max_chg` debug JSON field for max-charge reveal diagnostics.
- Fixed Hidden PV Reveal scope so startup or waiting states cannot throw `revealHiddenPv is not defined`.

#### Internal cleanup
- Removed unused battery detail variables from the Node-RED flow.
- Removed unused active battery summary string building.
- Cleaned and reorganized release documentation so all unreleased v1.0.7 work is documented under v1.1.0.

## v1.0.6

- Updated default threshold values for new installations.
- Removed unused legacy configuration components.
- Reduced unnecessary background processing.
- Internal cleanup and maintenance improvements.
- Updated badges.
- Fixed insight log source labels.
- Aligned expensive price fallback.
- Minor internal logic cleanup.
- Improved entity picker persistence after Home Assistant restart or reload.
- Replaced obsolete inverter count template reference with the existing inverter count helper.
- Removed phantom battery picker dropdown refresh calls.
- Removed redundant PV adjust guard conditions.
- Removed forced startup defaults from user-configurable helpers so user settings persist after restart or reload.
- Added startup restore wait to avoid temporary missing-entity warnings while Home Assistant inputs restore.

## v1.0.5

- Fixed configuration validation for missing entities.
- Fixed negative-price mode forcing PV minimum output.
- Fixed PV minimum insight logging.
- Fixed export threshold fallback consistency.
- Improved entity ID compatibility after rebranding.
- Dashboard renamed to "Home PV Control".
- Added documentation that Home PV Control is optimized for dynamic energy contracts.
- Improved diagnostics and configuration feedback.
- Removed unused functions and variables.
- Removed duplicate example JSON file.
- Simplified internal logic and improved readability.

## v1.0.4

- Fixed template entity ID mismatch on clean Home Assistant installs.
- Fixed missing dashboard entities after rebrand.

## v1.0.3

- Rebranded from PV EMS to Home PV Control.
- Updated banner and logo.
- Improved HBC integration.
- Dashboard improvements and cleanup.

## v1.0.2

- UI improvements.
- Dashboard fixes.
- Stability improvements.

## v1.0.1

- Dropdown persistence fixes.
- Configurable cooldown.
- Faster evaluation cycle.
- HBC battery power support.

## v1.0.0

- Initial public release.
