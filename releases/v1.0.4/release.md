# Home PV Control v1.0.4

Bugfix release for clean Home Assistant installs.

## Fixed
- Fixed template entity ID mismatch caused by renamed template sensor names.
- Dashboard now loads expected `sensor.pv_ems_*` and `binary_sensor.pv_ems_*` entities correctly.
- Fixes errors like `entity not found: sensor.pv_ems_configured_inverter_count`.

## Files included
- `home assistant/pv_ems_config.yaml`
- `home assistant/pv_ems_dashboard.yaml`
- `node-red/pv_ems_flow.json`
