# v1.0.2 - Maintenance release

## Highlights

- Fixed entity dropdowns after Home Assistant restart / Quick Reload
- EMS now evaluates every 15 seconds
- PV cooldown is configurable from 15 seconds to 15 minutes
- PV adjustments are blocked during cooldown
- HBC live status shows battery AC power
- Main dashboard explains negative-price PV minimum behavior

## Install / Update

Replace these files in your Home Assistant / Node-RED setup:

- `home assistant/pv_ems_config.yaml`
- `home assistant/pv_ems_dashboard.yaml`
- `node-red/pv_ems_flow.json`

Then reload Home Assistant helpers/dashboard and re-import the Node-RED flow.

## Notes

During negative all-in electricity prices, Home PV Control automatically reduces PV to the user-configured minimum limits. Set those minimum limits to `0 W` only if your inverter supports it.


### Internal fixes
- Fixed legacy text entity fallback when dropdowns are not selected.
- Fixed notification collision when PV and HBC actions occur in the same cycle.
- Fixed possible minimum/restore oscillation after export limiting.
- Cleaned duplicate YAML key and inactive flow leftovers.
