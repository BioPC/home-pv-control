# Examples

`hoymiles-opendtu-2-inverters.reference.json` is reference configuration data showing example inverter values. It is not a Node-RED flow and should not be imported directly. Use the values in the Home PV Control dashboard/settings.

## New in v1.3.0

- Active legacy Home PV Control entity IDs were renamed from `pv_ems_*` to `hpvc_*`.
- Added `script.hpvc_restore_defaults` and the **Restore defaults** dashboard tile.
- Existing installations should follow the entity-name migration guidance in `docs/02-configuration.md`.

## Adaptive Hidden PV Reveal

Hidden PV Reveal calculates the actual PV increase for each control cycle automatically.

The reveal amount is limited by:

- the internal, non-configurable 800 W safety cap,
- available HBC battery charge headroom,
- the export-target margin,
- and the remaining hidden PV capacity.

This allows reveal to use the combined capacity of multiple actively charging batteries while preventing an excessive increase in a single control cycle.

### HBC multi-battery charge headroom

HBC can charge multiple batteries in the same cycle. Adaptive Hidden PV Reveal sums usable headroom from all eligible batteries. Actively charging batteries contribute known remaining charge headroom, while eligible idle batteries may contribute an SOC-capped initial probe. Discharging, full, unavailable, or nonnumeric batteries contribute zero.

**Example:** M1 is charging at 470 W with a 2200 W maximum (1730 W headroom), while M2 is charging at 2175 W with a 2200 W maximum (25 W headroom). HPVC uses 1755 W combined headroom, still limited by Target Export margin, hidden PV, response checks, and the internal 800 W cap.


## Control boundaries used by the example

Use Export Start as the entry threshold for limiting and Target Export as the desired grid target. Keep `Export Start < Target Export <= 0 W`; Import Restore must be zero or positive. Min PV for control blocks only new limiting, not import recovery or reveal. Reveal is allowed only after grid export has recovered to at least Export Start.

Night restore uses `sun.sun` when available and waits for `below_horizon` to remain active for 120 seconds. The Night Restore PV Fallback Threshold is used only when `sun.sun` is unavailable.

## First-run defaults and restart persistence

User-configurable Home PV Control helpers do not use `initial:` values in the shipped YAML, allowing Home Assistant to restore user-edited settings after a restart. The transient `hpvc_report_ready` and `hpvc_report_generating` helpers intentionally use `initial: false` so stale report states are not restored.

A Home Assistant first-run automation applies the shipped defaults only while `input_boolean.hpvc_defaults_applied` is off. After the defaults are applied, the automation turns this marker on. Home Assistant restores that state after later restarts, so user changes are not overwritten.

The dashboard's **Restore defaults** tile runs `script.hpvc_restore_defaults`, allowing the shipped values to be applied again manually after confirmation.


## Price forecast graph

The graph uses HBC's normalized price-data sensor:

```text
sensor.hbc_energy_prices_data
```

HPVC reads this sensor directly. No extra HPVC forecast helper is required, but graph data is available only when HBC publishes forecast data to this sensor.
