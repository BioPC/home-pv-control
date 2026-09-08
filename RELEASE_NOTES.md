# Home PV Control v1.4.1

Home PV Control v1.4.1 is a focused performance and memory release addressing GitHub issue #2 while preserving the v1.4.0 control behavior and configuration model.

## Performance and memory

- Removed the 10-second full deep clone of `homeassistant.homeAssistant.states`.
- Removed the full Home Assistant state-table deep clone used during support-report generation.
- Replaced the runtime-wide `msg.hpvc.haStates` payload with a compact `msg.hpvc.cycleStates` snapshot containing only entities HPVC needs for the current evaluation.
- Dynamic grid, market-price, all-in-price, PV-power and inverter-limit entities are resolved first and then included individually in the compact snapshot.
- HBC/Marstek state requirements remain automatic through predictable battery entity families and the configured HBC helpers.
- Added a migration guard that removes any legacy `msg.hpvc.haStates` property before output/service publication.

## Allocation reductions

- Replaced the Daily Control Accuracy command snapshot `JSON.parse(JSON.stringify(...))` with a small object copy.
- Reduced the maximum in-memory activity history from 9,000 to 3,000 rows to lower the retained-heap ceiling while keeping substantial same-day diagnostic context.

## Temporary issue #2 diagnostics

- Added bounded per-stage runtime timing for the main evaluation path.
- Added aggregate last/max/average cycle timing in `homePvControlPerformanceDiagnostics`.
- Added guarded heap telemetry using `process.memoryUsage()` when the Node-RED Function sandbox exposes it.
- Heap sampling occurs at most once per minute. No per-cycle heap history is retained.
- If heap access is unavailable, control continues normally and diagnostics mark heap sampling unavailable.
- The HTML and TXT support reports now show the performance timing and heap diagnostics directly.

## Compatibility

- No helper renames or setting migrations are required from v1.4.0.
- Existing inverter, HBC, negative-price, safety, accuracy, persistence and report behavior is retained.
- Replace the Home Assistant package, Node-RED flow and dashboard together when upgrading.

