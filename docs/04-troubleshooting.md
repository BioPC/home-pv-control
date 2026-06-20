# Troubleshooting

## PV does not limit

Check:

- Home PV Control Enabled is on
- Market price is at or below PV Limiting Price
- Grid power is more negative than Start Limiting Export
- PV power is above Minimum PV Power
- Cooldown has passed
- PV inverter helpers is valid
- Limit entities are writable `number` entities

## PV restores to full at night

This is intended.

When PV production falls below the night restore threshold, the EMS restores full limits so the next morning starts clean.

## Import happens while PV is limited

Small import is allowed by design.

PV only recalculates upward when import rises above Import Recalculation Threshold.

Lower that threshold if you want more aggressive correction.

## Node-RED says entity not found

Check exact entity IDs in:

- sensor helpers
- HBC strategy entity helper
- PV inverter helpers

## Inverter targets look wrong

Check:

- full_power values
- minimum_power values
- enabled flags
- total configured full power sensor
- total configured minimum power sensor

## HBC strategy changes unexpectedly

Turn off:

```text
input_boolean.pv_ems_control_hbc_strategy
```

Then Home PV Control only controls PV limits and leaves HBC strategy untouched.
