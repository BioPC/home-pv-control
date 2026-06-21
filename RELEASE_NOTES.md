# Release Notes

## v1.0.1 - Maintenance release

Bug-fix and control-behavior update for Home PV Control.

### Fixed

- Entity dropdowns no longer disappear after Home Assistant restart or Quick Reload.
- Dropdown entity discovery no longer stops at partial lists.
- PV limit / restore / recalculation actions are blocked during cooldown.
- Cooldown finished is logged before the next PV action is allowed.
- Cooldown now uses seconds consistently.

### Changed

- EMS evaluation interval is now 15 seconds.
- PV cooldown can be configured from 15 seconds to 15 minutes.
- Default PV cooldown remains 60 seconds.
- Debug output shows the actual cooldown value.

### Added

- HBC live status now shows battery AC power for M1, M2, M3 and higher.
- Main dashboard now explains that, during negative all-in prices, PV is automatically reduced to the user-configured minimum limits.

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
