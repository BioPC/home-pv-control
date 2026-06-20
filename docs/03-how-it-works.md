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
