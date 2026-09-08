# Home PV Control v1.4.2

Home PV Control v1.4.2 is a runtime-efficiency maintenance release.

## Main changes

- Incremental Insights/dashboard rendering instead of rebuilding unchanged history every 10 seconds.
- Event-based Power Control history now avoids unchanged per-cycle history and metadata writes.
- Activity pruning runs periodically rather than on every evaluation.
- Selected unchanged scalar/context values are no longer rewritten.
- Added internal measured-stage and unaccounted-cycle timing for deeper performance analysis.

> [!IMPORTANT]
> Replace the Home Assistant package, Node-RED flow, and dashboard together when upgrading.

No configuration migration is required from v1.4.1.

## Issue #3 / #4 follow-up

- Added conservative HBC-style stable-input rate limiting and high-load cooldown signalling.
- Stable timer cycles can skip downstream work, but HPVC still forces a full evaluation at least every 30 seconds and never skips pending safety/write/recovery work.
- Fixed a Settings-changed race: configuration changes received while the runtime lock is active are now marked dirty and applied by the next successful evaluation.
- Event-driven cache for 68 helper/configuration entities.
- Normal 10-second evaluations refresh only 30 live whitelist states plus dynamic targets.
- Settings changes rebuild the cache before control runs.
- Added bounded retention counters for diagnosing remaining heap growth.


## Rate-limiter baseline correction

- Fixed cumulative-change handling in the HBC-inspired rate limiter. Small grid/PV changes now accumulate relative to the last full evaluation, while the 20 W + 2% thresholds remain unchanged.
- Fixed a declaration-order regression in the HPVC input function that could stop runtime evaluations with a `settingsTrigger` ReferenceError.
