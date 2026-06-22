# Home PV Control Release Notes

## v1.0.4

Bugfix release for clean Home Assistant installs.

### Fixed
- Fixed template entity ID mismatch after the PV EMS → Home PV Control rebrand.
- Template sensors now keep the expected `sensor.pv_ems_*` and `binary_sensor.pv_ems_*` entity IDs.
- Fixes missing dashboard entities such as `sensor.pv_ems_configured_inverter_count`.

### Included
- Home Assistant config
- Home Assistant dashboard
- Node-RED flow
