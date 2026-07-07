# Examples

`hoymiles-opendtu-2-inverters.reference.json` is reference configuration data showing example inverter values. It is not a Node-RED flow and should not be imported directly. Use the values in the Home PV Control dashboard/settings.


## New in v1.2.0

- Adaptive Export Target Aware Hidden PV Reveal.
- Hidden PV Reveal now supports mixed inverter states.


## Adaptive Hidden PV Reveal

Hidden PV Reveal now calculates the actual PV increase per control cycle dynamically.

The reveal amount is limited by:
- the configured maximum Maximum Hidden PV Reveal Step,
- available HBC battery charge headroom,
- the export target margin,
- and the remaining hidden PV capacity.

This keeps the user setting as a maximum cap while allowing smaller reveal amounts when the battery can only absorb part of a full step.


### HBC single-battery charge headroom

For HBC systems that charge one battery at a time, Adaptive Hidden PV Reveal uses the **largest active charging-battery headroom** instead of summing headroom across all configured batteries. This avoids revealing PV based on batteries that are present but not currently accepting charge.

## First-run defaults and restart persistence

Home PV Control helpers do not use `initial:` values in the shipped YAML. This lets Home Assistant restore user-edited values after a restart.

A Home Assistant first-run automation applies recommended defaults only when `input_boolean.pv_ems_defaults_applied` is still off. After the defaults are applied, that flag is turned on and restored by Home Assistant on later restarts, so user changes are not overwritten.

### Reveal deadband handling

Hidden PV Reveal applies the PV Adjustment Deadband to the **total reveal request**, not to each inverter's proportional share.

If the total reveal is meaningful, HPVC keeps the proportional split across inverters. Every proportional inverter change is applied once the total reveal exceeds the deadband. This prevents smaller inverters from lagging behind during small reveal steps.

