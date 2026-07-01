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
Lowest limit Home PV Control may set for this inverter.

## Recommended values

| Setting | Recommended |
|---|---:|
| PV Limiting Price | 0.00 €/kWh |
| Start Limiting Export | -200 W |
| Target Export | -25 W |
| Import Recalculation | 200 W |
| Minimum PV Power | 100 W |
| Night Restore | 10 W |
| Minimum PV Change | 1 min |
| Deadband | 25 W |

## Notes

The Node-RED flow reads the configured entity IDs from `input_text` helpers, so no Node-RED deploy-time entity discovery is needed. The flow runs on a 15-second timer plus an on-deploy/startup trigger; a separate `server-state-changed` node re-runs the flow immediately whenever one of the configuration helpers itself changes (for example, when you update an inverter limit entity or a threshold). Changes to the live grid/market/PV sensors are picked up on the next 15-second cycle rather than triggering an immediate run.

## Entity configuration

The grid power, prices, PV power, PV limit, and HBC strategy entities are plain `input_text` fields rather than dropdowns. Paste the entity ID directly into each field (for example `sensor.p1_meter_power` or `number.hms_2000_4t_limit_nonpersistent_absolute`). This avoids generating large dynamic dropdown option lists on installations with many entities. If a field is left empty or contains an invalid entity ID, Home PV Control treats that input as unconfigured and reports a configuration error rather than guessing.
