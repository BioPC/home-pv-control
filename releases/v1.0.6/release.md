# Home PV Control v1.0.6

## Changes

- Added startup restore wait to avoid temporary missing-entity warnings while Home Assistant inputs restore.
- Removed forced startup defaults from user-configurable helpers so user settings persist after restart or reload.
- Removed phantom battery picker dropdown refresh calls.
- Removed redundant PV adjust guard conditions.
- Replaced obsolete inverter count template reference with the existing inverter count helper.
- Improved entity picker persistence after Home Assistant restart or reload.
- Fixed insight log source labels.
- Aligned expensive price fallback.
- Minor internal logic cleanup.
- Removed unused legacy configuration components.
- Reduced unnecessary background processing.
- Internal cleanup and maintenance improvements.
- Updated default threshold values for new installations.
- Updated dashboard.
- Updated badges.
