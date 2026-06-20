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

The Node-RED flow reads the configured entity IDs from helpers. The two wake-up event nodes still default to common sensor names. If you use different grid/market sensors, either edit those trigger nodes or rely on the 1-minute timer.

## Entity dropdowns

The grid power, prices, PV power and PV limits helpers are dropdowns, not text fields. After importing the Node-RED flow, deploy it once or click **Refresh entity dropdowns**. Node-RED will populate the dropdowns from Home Assistant entities so you can select instead of typing.
