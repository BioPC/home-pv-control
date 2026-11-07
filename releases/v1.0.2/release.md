# v1.0.2 - Maintenance release

## Improvements
- Insight timestamps now include seconds for clearer 15-second EMS debugging.
- Cleaned up cooldown helper naming and internal flow references.
- Updated banner and dashboard version to v1.0.2.

## Fixes
- Fixed text input fallback handling for entity selectors.
- Prevented battery and PV notifications from overwriting each other.
- Fixed possible PV minimum / restore oscillation.
- Removed unused/dead Node-RED nodes and duplicate YAML entries.
- Added validation for inverter minimum limit vs full limit.

## Notes
Home PV Control requires PV inverters with writable power limit entities for PV curtailment features.
