# Home PV Control v1.2.0

> v1.1.2 was never released. All work that was temporarily staged as v1.1.2 is included in this v1.2.0 public release. Users can upgrade directly from v1.1.1 to v1.2.0.

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

### First-run defaults persistence fix

- Removed Node-RED flow-context default initialization.
- Added `input_boolean.pv_ems_defaults_applied` as a Home Assistant first-run marker.
- Added a Home Assistant startup automation that applies recommended defaults only once on a new install.
- Helpers still have no `initial:` values, so user-edited values restore normally after Home Assistant restarts.

### Default seeding cleanup

- First-run default seeding now uses a 60 second cooldown to match the README recommended default.

### Reveal deadband handling

- Hidden PV Reveal now applies the PV Adjustment Deadband to the total reveal request instead of each inverter share.
- Proportional inverter distribution is preserved for small reveal steps.
- Every proportional inverter change is applied once the total reveal exceeds the deadband.

### Cooldown debug sensor fix

- Added compact `cd` cooldown flag to the last-calculation JSON.
- Updated `binary_sensor.pv_ems_cooldown_active` to read the compact cooldown flag so the dashboard Cooldown active indicator works again.

### Final documentation and HACS metadata cleanup

- Fixed `hacs.json` so it is valid JSON instead of YAML.
- Updated configuration docs to describe first-run default seeding instead of removed `initial:` values.
- Added v1.2.0 Hidden PV Reveal, stability score, sun recovery, negative-price and final-restore behavior to the how-it-works documentation.
- Fixed troubleshooting references to removed or nonexistent entities.
- Removed the redundant `anyBelowFull` alias in the Node-RED flow.

