# Changelog

All notable changes to this project will be documented here.

## [1.0.1] - Maintenance release

### Fixed

- Fixed entity dropdown persistence after Home Assistant restart or Quick Reload.
- Fixed incomplete dropdown entity discovery.
- Prevented PV limit, restore and recalculation actions during PV cooldown.
- Ensured cooldown finished is logged before a new PV action is allowed.
- Updated cooldown logic to use seconds correctly.

### Changed

- EMS evaluation interval changed from 60 seconds to 15 seconds.
- PV cooldown is now configurable from 15 seconds to 15 minutes.
- Default PV cooldown is 60 seconds.
- Debug messages now show the actual cooldown value.

### Added

- Added HBC battery AC power display in the live status tab for M1, M2, M3 and higher.
- Added main-screen notice explaining that negative all-in prices force PV to the configured minimum limits.

## [1.0.0] - First public release

### Added

- Generic Home PV Control Node-RED flow.
- Home Assistant package helpers.
- Separate HBC-style dashboard.
- Multi-inverter support.
- Per-inverter full and minimum power.
- Proportional target splitting.
- Dynamic PV limiting.
- Dynamic PV increase on import.
- Night restore to full PV.
- Optional HBC strategy handoff.
- Documentation and placeholders.
