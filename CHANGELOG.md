# Changelog

All notable changes to this project will be documented here.

## [1.0.2] - Maintenance release

### Fixed
- Added seconds to insight timestamps.
- Fixed cooldown helper naming and cleanup.
- Fixed SVG banner version badge.
- Validation and stability improvements.

### Changed
- Preserved release history and documentation structure.

## [1.0.1] - Stability and control update

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
- Added HBC battery AC power display in the live status tab.
- Added main-screen notice explaining negative-price PV limiting.

## [1.0.0] - First public release

### Added
- Generic Home PV Control Node-RED flow.
- Home Assistant package helpers.
- Separate HBC-style dashboard.
- Multi-inverter support.
- Dynamic PV limiting and restore logic.
- Optional HBC strategy handoff.
