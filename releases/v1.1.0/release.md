# Home PV Control v1.1.0

> v1.0.7 was never released. All planned v1.0.7 changes are included in this v1.1.0 release, so v1.1.0 is the direct upgrade path from v1.0.6.

Home PV Control v1.1.0 improves Debug Insights, cooldown behavior, the HBC strategy price graph, and Hidden PV Reveal for HBC/grid-following battery systems.

## Release timeline

### Debug and dashboard polish

- Debug Insights expanded from 10 to 20 items.
- Cooldown-finished messages removed from the Insights history.
- Cooldown timestamps changed to 24-hour `HH:MM:SS` format.
- Added 48-hour HBC strategy price graph using all-in prices in €/kWh.
- Added graph colors based on configured Charge and Expensive thresholds.
- Added compact HBC price-zone legend.

### PV cooldown and recovery behavior

- First evaluation after cooldown expiry can now act immediately.
- Heavy import while PV is limited uses normal fast import recovery.
- Hidden PV Reveal no longer takes over the heavy-import recalculation path.
- Mixed-inverter reveal only runs when all configured inverters are below full output.

### HBC strategy selection

- Hysteresis notification wording now distinguishes entry thresholds from hysteresis exits.
- HBC strategy control remains optional; HPVC can still run standalone.

### Hidden PV Reveal

- Added Hidden PV Reveal for HBC/grid-following batteries.
- Added configurable Hidden PV Reveal step in PV Export Control.
- Reveal step range is 50–250 W with 100 W default.
- Improved reveal allocator preserves small reveal steps across multiple inverters.
- Reveal only runs when an active HBC battery is charging.
- Uses `input_number.house_battery_count` when available.
- Falls back to one battery only when `input_number.house_battery_count` is missing.
- Respects an explicit `input_number.house_battery_count = 0`.
- Missing HBC Batteries power sensors are ignored instead of treated as 0 W.
- Uses HBC Batteries max charge power entities (`number.marstek_mX_max_charge_power`) to pause reveal when batteries are at or near maximum charge power.
- Logs one-time pause, resume and completion Insights for Hidden PV Reveal state changes.
- Shows a clear reason when reveal is active but the requested increase is below the deadband.

### Startup and diagnostics

- Adds an Insight when Home Assistant inputs finish restoring and HPVC resumes control.
- Adds compact debug JSON fields for battery power, charging state, charge headroom and max-charge state.
- Adds `at_max_chg` to the compact debug JSON.
- Fixes `revealHiddenPv` scope so waiting/startup states cannot throw a ReferenceError.

### Internal cleanup

- Removed unused battery detail variables.
- Removed unused active battery summary string building.
- Reorganized documentation and merged unreleased v1.0.7 notes into v1.1.0.

## Update notes

1. Import or replace `home assistant/pv_ems_config.yaml`.
2. Reload packages or restart Home Assistant so helpers are created.
3. Import and deploy `node-red/pv_ems_flow.json`.
4. Import or replace `home assistant/pv_ems_dashboard.yaml`.
5. Recheck selected entities in the dashboard after the dropdowns refresh.

No battery picker helpers are required. HBC/Marstek battery power and max-charge entities are read directly when HBC strategy control is enabled.
