# How it works

Home PV Control calculates a target total PV limit and then distributes that target over all configured inverters.

## Target calculation

```text
target_total = pv_power + grid_power - target_grid_power
```

Example:

```text
PV power = 2500 W
Grid power = -600 W
Target export = -25 W

target_total = 2500 - 600 + 25 = 1925 W
```

## Splitting over inverters

The target is split proportionally by `full_power`.

Example:

```text
PV1 full = 2000 W
PV2 full = 1000 W
Total full = 3000 W
```

PV1 gets 2/3 of the target, PV2 gets 1/3.

If another user has:

```text
PV1 = 1500 W
PV2 = 1500 W
```

both get 50%.

## Minimum power

Every inverter has its own `minimum_power`.

The EMS never sets an inverter below this value.

## Restore conditions

PV is restored to full power when:

- market price is unavailable
- market price rises above the PV limiting price
- PV production falls below the night/low-PV threshold

## Dynamic adjustment conditions

PV limits are adjusted dynamically when:

- market price is at or below the PV limiting price
- PV production is above the minimum PV power
- export is above the start threshold, or import is above the recalculation threshold
- cooldown has passed
- target change is larger than the deadband

## Import recalculation

High import does not force full restore.

It wakes the flow and lets the dynamic target calculation raise PV only as much as needed.

## Automatic Adaptive Hidden PV Reveal

When PV is limited and HBC strategy control is enabled, HPVC can reveal hidden PV for a charging HBC battery.

Reveal is allowed only when PV is already limited, at least one active HBC battery is charging, the grid is inside the Target Export plus dynamic tolerance window, and the real-PV response guard allows reveal.

The reveal amount is:

`min(800 W cap, battery headroom, Target Export margin + dynamic tolerance, hidden PV remaining)`

The PV Adjustment Deadband is applied to the total reveal request. Once the total reveal is above the deadband, HPVC keeps the proportional split across inverters.

## Reveal response guard and stability score

After each reveal, HPVC checks whether real PV production increased enough.

The reveal stability score ranges from 0–100%:
- good response raises the score,
- weak response lowers it slightly,
- poor response lowers it strongly,
- reveal pauses below 40%,
- sun recovery raises the score enough to allow reveal again.

Sun recovery is detected when PV production rises again or export increases enough to indicate more solar is available.

## Negative price and final restore behavior

When the all-in import price is zero or negative, HPVC forces PV to minimum output.

When Hidden PV Reveal finishes, HPVC verifies that all inverters are actually restored to full power. If one inverter remains slightly below full, HPVC sends one final per-inverter restore command.

## Automatic Adaptive Hidden PV Reveal

Hidden PV Reveal is fully automatic. There is no user-configured reveal power.

When PV is limited and an HBC battery is charging, HPVC calculates a balanced reveal amount from:

- active charging-battery headroom,
- Target Export margin plus dynamic tolerance,
- remaining hidden PV,
- and an internal 800 W safety cap.

The reveal amount is:

`min(800 W cap, battery headroom, Target Export margin + dynamic tolerance, hidden PV remaining)`

The dynamic tolerance is:

`min(max(deadband × 2, active battery headroom × 0.25), 150 W)`

HPVC uses a reveal stability score instead of pausing from one noisy sample. The score rises after good PV response, falls after weak or poor response, pauses reveal below 40%, and recovers when PV production rises again or export increases.

Export Start decides when PV limiting begins. Target Export decides the reveal recovery window.

A 75–100 W gap between Export Start and Target Export is recommended for smooth control, but it is guidance only and is not enforced in the dashboard.

## Advanced Debug

`sensor.hpvc_advanced_debug` exposes the compact latest-calculation JSON from `input_text.pv_ems_last_targets_json`.

The debug payload is intentionally compact so it fits the Home Assistant input-text length limit. It includes key reveal diagnostics such as target, tolerance, margin, hidden PV, reveal candidate, stability score, and guard state.

## First-run defaults and restart persistence

Home PV Control helpers do not use `initial:` values in the shipped YAML. This lets Home Assistant restore user-edited values after a restart.

A Home Assistant first-run automation applies recommended defaults only when `input_boolean.pv_ems_defaults_applied` is still off. After the defaults are applied, that flag is turned on and restored by Home Assistant on later restarts, so user changes are not overwritten.

### Reveal deadband handling

Hidden PV Reveal applies the PV Adjustment Deadband to the **total reveal request**, not to each inverter's proportional share.

If the total reveal is meaningful, HPVC keeps the proportional split across inverters. Every proportional inverter change is applied once the total reveal exceeds the deadband. This prevents smaller inverters from lagging behind during small reveal steps.
