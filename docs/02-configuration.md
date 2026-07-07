# Configuration

## Entity helpers

Configure these helpers first.

### Grid Power Sensor

Expected sign convention:

```text
negative = export
positive = import
```

Example:

```text
sensor.p1_meter_power
```

### Market / Export Price Sensor

Used for PV limiting decisions.

Usually this should be the market price without taxes.

### All-in Import Price Sensor

Used only for optional HBC strategy switching.

### Total PV Power Sensor

Total current PV production in watts.

### HBC Strategy Entity

Disable `Home PV Control Controls HBC Strategy` if you only want PV limiting.

## PV inverter limits

Each inverter needs:

`limit_entity`  
Writable Home Assistant `number` entity used to set the inverter power limit.

`full_power`  
Normal maximum/full limit in watts.

`minimum_power`  
Lowest limit Home PV Control may set for this inverter. Must be zero or positive and lower than `full_power`; a negative value is reported as a configuration error rather than being silently ignored.

## Default values

These are the recommended defaults applied once by the first-run Home Assistant automation. They're a reasonable, tested starting point — adjust to your own setup once things are running.

| Setting | Default |
|---|---:|
| Home PV Control Enabled | On |
| Notifications | On |
| HBC Strategy Control | On |
| Debug | Off |
| Number of PV Inverters | 1 |
| PV Limiting Price | 0.025 €/kWh |
| Battery Charge All-in Price | 0.10 €/kWh |
| Expensive All-in Price | 0.35 €/kWh |
| Battery Price Hysteresis | 0.02 €/kWh |
| Export Start Threshold | -150 W |
| Export Stop Threshold | -25 W |
| Import Restore Threshold | 150 W |
| PV Minimum Power For Control | 100 W |
| PV Night Restore Power | 10 W |
| PV Cooldown | 60 sec |
| PV Adjustment Deadband | 25 W |
| PV1–PV10 Full Limit | 0 W (must be set per inverter) |
| PV1–PV10 Low Limit | 0 W (must be set per inverter) |
| Balanced Strategy | Dynamic 2 |
| Expensive Strategy | Sell |
| Battery Strategy Entity | `input_select.house_battery_strategy` |

## Notes

The Node-RED flow reads the configured entity IDs from `input_text` helpers, so no Node-RED deploy-time entity discovery is needed. The flow runs on a 15-second timer plus an on-deploy/startup trigger; a separate `server-state-changed` node re-runs the flow immediately whenever one of the configuration helpers itself changes (for example, when you update an inverter limit entity or a threshold). Changes to the live grid/market/PV sensors are picked up on the next 15-second cycle rather than triggering an immediate run.

## Entity configuration

The grid power, prices, PV power, PV limit, and HBC strategy entities are plain `input_text` fields rather than dropdowns. Paste the entity ID directly into each field (for example `sensor.p1_meter_power` or `number.hms_2000_4t_limit_nonpersistent_absolute`). This avoids generating large dynamic dropdown option lists on installations with many entities. If a field is left empty or contains an invalid entity ID, Home PV Control treats that input as unconfigured and reports a configuration error rather than guessing.

## Automatic Adaptive Hidden PV Reveal

Hidden PV Reveal is fully automatic. There is no user-configured reveal power.

When PV is limited and an HBC battery is charging, HPVC calculates a balanced reveal amount from:

- active charging-battery headroom,
- Target Export margin plus dynamic tolerance,
- remaining hidden PV,
- and an internal 800 W safety cap.

The reveal amount is:

`min(800 W cap, battery headroom, Target Export margin + dynamic tolerance, hidden PV remaining)`

The dynamic tolerance is:

`min(max(deadband × 2, active battery headroom × 0.25), 150 W)`

HPVC uses a reveal stability score instead of pausing from one noisy sample. The score rises after good PV response, falls after weak or poor response, pauses reveal below 40%, and recovers when PV production rises again or export increases.

Export Start decides when PV limiting begins. Target Export decides the reveal recovery window.

A 75–100 W gap between Export Start and Target Export is recommended for smooth control, but it is guidance only and is not enforced in the dashboard.

## Advanced Debug

`sensor.hpvc_advanced_debug` exposes the compact latest-calculation JSON from `input_text.pv_ems_last_targets_json`.

The debug payload is intentionally compact so it fits the Home Assistant input-text length limit. It includes key reveal diagnostics such as target, tolerance, margin, hidden PV, reveal candidate, stability score, and guard state.

## First-run defaults and restart persistence

Home PV Control helpers do not use `initial:` values in the shipped YAML. This lets Home Assistant restore user-edited values after a restart.

A Home Assistant first-run automation applies recommended defaults only when `input_boolean.pv_ems_defaults_applied` is still off. After the defaults are applied, that flag is turned on and restored by Home Assistant on later restarts, so user changes are not overwritten.

### Reveal deadband handling

Hidden PV Reveal applies the PV Adjustment Deadband to the **total reveal request**, not to each inverter's proportional share.

If the total reveal is meaningful, HPVC keeps the proportional split across inverters. Every proportional inverter change is applied once the total reveal exceeds the deadband. This prevents smaller inverters from lagging behind during small reveal steps.

