# Changelog

All notable changes to this project will be documented here.

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

## [0.1.0] - Internal draft

### Added

- First working draft for a 2-inverter Hoymiles/OpenDTU setup.


## v1.0.2
- Fixed Node-RED inverter parser to support compact inverter JSON keys (`n`, `e`, `f`, `m`, `en`).
- Keeps Home Assistant `input_text` values under the 255 character limit.


## v1.0.3

- Verified `pv_ems_config.yaml` parses as valid YAML.
- Fixed compact inverter template sensors to respect `en:false`.
- Removed duplicated tuning inputs from the dashboard; `Minimum Minutes Between PV Changes` and `PV Adjustment Deadband` now appear only under Control Tuning.


## Entity dropdown update
- Replaced typed entity `input_text` helpers with `input_select` dropdowns.
- Added Node-RED entity discovery that populates dropdown options automatically.
- Updated dashboard and EMS logic to read the new dropdown helpers.
