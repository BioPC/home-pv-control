# Changelog

## v1.0.6
- Updated default threshold values for new installations.
- Removed unused legacy configuration components.
- Reduced unnecessary background processing.
- Internal cleanup and maintenance improvements.
- Updated badges.
- Fixed insight log source labels.
- Aligned expensive price fallback.
- Minor internal logic cleanup.
- Improved entity picker persistence after Home Assistant restart or reload.
- Replaced obsolete inverter count template reference with the existing inverter count helper.
- Removed phantom battery picker dropdown refresh calls.
- Removed redundant PV adjust guard conditions.
- Removed forced startup defaults from user-configurable helpers so user settings persist after restart or reload.
- Added startup restore wait to avoid temporary missing-entity warnings while Home Assistant inputs restore.

## v1.0.5

- Fixed configuration validation for missing entities.
- Fixed negative-price mode forcing PV minimum output.
- Fixed PV minimum insight logging.
- Fixed export threshold fallback consistency.
- Improved entity ID compatibility after rebranding.
- Dashboard renamed to "Home PV Control".
- Added documentation that Home PV Control is optimized for dynamic energy contracts.
- Improved diagnostics and configuration feedback.
- Removed unused functions and variables.
- Removed duplicate example JSON file.
- Simplified internal logic and improved readability.

## v1.0.4
- Fixed template entity ID mismatch on clean Home Assistant installs.
- Fixed missing dashboard entities after rebrand.

## v1.0.3
- Rebranded from PV EMS to Home PV Control.
- Updated banner and logo.
- Improved HBC integration.
- Dashboard improvements and cleanup.

## v1.0.2
- UI improvements.
- Dashboard fixes.
- Stability improvements.

## v1.0.1
- Dropdown persistence fixes.
- Configurable cooldown.
- Faster evaluation cycle.
- HBC battery power support.

## v1.0.0
- Initial public release.