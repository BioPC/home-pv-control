# Release Notes

## v1.0.3

Bug fixes and improvements:

- Added automatic HBC detection
- HBC strategy control now defaults off
- HBC control is forced off when no valid HBC strategy entity is found
- Skips all battery strategy actions when HBC is not available
- Improved PV-only mode support
- Hides HBC-related dashboard items when HBC strategy control is off
- HBC strategy entity changes now trigger immediate re-evaluation
- Cleaned up unused Node-RED code and clarified example files
- Updated dashboard, Node-RED flow and documentation

## v1.0.2

### Fixed
- Added seconds to insight timestamps.
- Fixed cooldown helper naming.
- Fixed SVG banner version badge.
- Cleanup and validation improvements.

## v1.0.1

### Improvements
- EMS evaluation increased to 15-second intervals.
- Configurable PV cooldown (15 sec – 15 min).
- Added battery power display in HBC Live Status.
- Added negative-price information on the dashboard.

### Fixes
- Fixed entity dropdowns disappearing after Home Assistant restart/reload.
- Fixed incomplete entity discovery during startup.
- Improved PV cooldown handling and adjustment sequencing.

## v1.0.0

Initial public release of Home PV Control.
