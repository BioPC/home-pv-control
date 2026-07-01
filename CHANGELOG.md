# Changelog

## v1.1.1

- Maintenance release based on v1.1.0.
- Updated `pv_ems_config.yaml`, `pv_ems_dashboard.yaml`, and `node-red/pv_ems_flow.json` with the latest uploaded fixes.
- Keeps the v1.1.x helper names compatible while improving input-text based entity configuration.
- Changed recommended `initial:` values to all Home Assistant helpers.
- Minor dashboard fixes and cleanup.

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
- Set Hidden PV Reveal step range to 50–250 W with 100 W default.
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
