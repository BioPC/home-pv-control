# Home PV Control v1.4.2

Home PV Control v1.4.2 is a runtime-efficiency follow-up to v1.4.1.

## CPU and memory improvements

- Insights/dashboard helpers are rebuilt only when their underlying Insight sources change instead of rescanning the full current-day history every 10 seconds.
- Power Control activity remains event-based, but activity arrays and metadata are now written only when activity actually changes.
- Activity-history pruning is performed periodically instead of allocating a filtered copy every control cycle.
- Selected unchanged scalar/context values are no longer rewritten unnecessarily.
- Runtime cadence history is only rewritten when its bounded sample window actually changes.

## Diagnostics

- Added internal `measuredStageMs` and `unaccountedMs` timing so unexplained cycle time can be separated from explicitly timed HPVC stages.
- The user-facing Performance Diagnostics report remains compact.

## Issue #3 / #4 follow-up

- Added an HBC-inspired stable-input rate limiter: HPVC may skip downstream work when grid, PV and other live control inputs remain unchanged, while forcing a complete evaluation at least every 30 seconds.
- Added a high-load signal based on the previous cycle (>1 s); stable cycles use the rate limiter as a cooldown while control/safety evaluations are never disabled.
- The rate limiter is bypassed for startup/settings rebuilds, cooldowns, Night Restore state, write verification, physical-event attribution, HBC safety/settling and battery recovery timing.
- Fixed a Settings-changed race: configuration changes received while the runtime lock is active are now marked dirty and applied by the next successful evaluation.
- Added an event-driven cache for 68 configuration/helper entities.
- The 10-second control cycle now refreshes only 30 genuinely live whitelist entities plus dynamically resolved targets.
- Configuration cache is initialized on startup and rebuilt after any watched settings change.
- Expanded the Settings changed watcher to cover all 68 cached helper/configuration entities.
- The bounded cycle snapshot is reused between serialized HPVC evaluations instead of reconstructing all 98 static whitelist entries every cycle.
- Dynamic grid, price, PV and inverter target entities are still resolved from current configuration and read live every cycle.
- Completed runtime messages explicitly release their `cycleStates` reference.
- Added bounded internal retention counters for the main activity/history structures to help diagnose issue #3 without creating another diagnostic history.


## Compatibility

- No helper renames or configuration migrations are required from v1.4.1.
- Control logic, HBC coordination, inverter handling, Daily Control Accuracy, safety behavior and report functionality are unchanged.
- Replace the Home Assistant package, Node-RED flow and dashboard together when upgrading.

## Rate-limiter baseline correction

- Corrected the HBC-inspired stable-input rate limiter so grid/PV changes are compared with the **last full HPVC evaluation**, not the previous 10-second lightweight check.
- The existing **20 W + 2%** thresholds are unchanged; gradual changes now accumulate against the last full baseline and can trigger a full evaluation sooner.
- The normal **10-second trigger** and mandatory full evaluation at least every **30 seconds** remain unchanged.
- Fixed a v1.4.2 runtime regression where `settingsTrigger` could be referenced before initialization in `Read HPVC Core Configuration`, causing the HPVC control loop to throw and stop completing evaluations.
