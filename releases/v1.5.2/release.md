# Home PV Control v1.5.2

v1.5.2 fixes the two control problems reported in GitHub issue #7 while keeping the v1.5.1 manual-install architecture.

## In-flight inverter handling

A single inverter that is still confirming a previous command no longer freezes every inverter when the grid is importing and HPVC needs more PV.

For an import-driven upward correction, HPVC now:

- identifies the inverter control paths that have not confirmed the previous write;
- freezes only those inverter(s) at their live limit;
- redistributes the available increase across the remaining healthy inverters;
- caps the temporary plant target at what the healthy inverters can actually reach;
- keeps the stricter write lock for export/downward corrections.

Small device/readback quantization outside a configured limit, such as a live value of 4.95 W with a configured 5 W minimum, is treated as a bound correction rather than a direction-reversal control error.

## Safe disable restore

Switching HPVC Off no longer waits for an older in-flight normal-control command before restoring PV. If any configured inverter is below full, HPVC immediately requests full output from all configured inverters. The existing write-verification/retry path then confirms the restore.

## Price-zone boundary stability

Price-zone Insights no longer flap at the exact limiting-price boundary. `0.0000` and `-0.0` are treated consistently at a `0.0000 €/kWh` limit. A partial or disabled evaluation cannot turn an absent remembered state into a false `left the PV-limiting zone` event.

An enter transition is accepted only when the market price is at or below the limiting threshold. A leave transition is accepted only when the market price is above the restore threshold.

## Audit hardening

The final v1.5.2 package also includes release-audit cleanup: Power Flow zero-line annotations use the explicit ApexCharts `y` field, post-allocation control diagnostics are reconciled with the final reachable target, and current documentation consistently describes the v1.5.2 in-flight exceptions.

## Upgrade

Replace the Home Assistant package, Node-RED flow and dashboard from the same v1.5.2 package. Existing v1.5.1 configuration remains compatible.
