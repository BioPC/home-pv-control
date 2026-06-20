# Release Notes

## v1.0.0 - First public release

First public GitHub-style release of Home PV Control for HBC users.

### Added

- Generic standalone Home PV Control Node-RED flow.
- Home Assistant package with user-configurable helpers.
- Separate HBC-style dashboard.
- Multi-inverter support through JSON configuration.
- Per-inverter `full_power`.
- Per-inverter `minimum_power`.
- Proportional target split across all configured inverters.
- Dynamic PV limiting based on market/export price.
- Dynamic PV increase on import without forced full restore.
- Night / low-PV restore to full inverter limits.
- Optional HBC strategy handoff.
- Documentation pages.
- Placeholder screenshots.
- Basic GitHub issue template.
- HACS metadata placeholder.

### Compatibility

- Home Assistant 2024.8+
- Node-RED with Home Assistant nodes
- Home Battery Control users
- Any PV inverter exposing writable HA `number` limit entities

### Notes

This project does not modify Home Battery Control.


- Fixed cooldown state so it turns off automatically after the configured cooldown time.
- Fixed HBC live status and battery SOC visibility.
- Fixed HBC strategy selector as read-only default `input_select.house_battery_strategy`.


- Prevented dynamic PV adjustment commands when the calculated target equals full/max inverter power. Full-power changes are treated as restore, and PV limiting turns off once actual limits are back at max.


- Prevented repeated PV commands when calculated target is already at configured minimum and inverter limits are already at minimum. The next command is only sent when a higher-than-minimum target is needed.
