# Home PV Control v1.5.4

**Release date:** 2026-10-05

v1.5.4 focuses first on control safety and multi-inverter reliability, then on resilient maintenance/update recovery, and finally on diagnostics and release validation.

## Control and safety

- Full-output restore now remains **Restoring PV** until inverter limits are actually confirmed at full output.
- Restore verification emits specific delayed/failure Insights when one or more inverter limits remain unconfirmed.
- Automatic safety pauses caused by invalid sensor/configuration state hold the current inverter limits instead of forcing full output; healthy manual disable and verified maintenance paths still restore configured full limits.
- Watt target rounding is corrected when an inverter minimum does not align exactly with its configured step.
- Negative all-in-price protection remains authoritative through the inverter stage and continues to request the configured minimum PV target when the all-in sensor is valid.
- Telemetry freshness is evaluated through a Home Assistant-side `last_reported` snapshot refreshed every 30 seconds. Node-RED validates the snapshot and source age and fails safe on missing, stale, invalid or implausibly future freshness.
- External Release acknowledgement has a 45-second HA-side verification lease, preventing a historical release ACK from surviving a stalled Node-RED engine.

## Inverter and External Release reliability

- HPVC now tracks internal per-inverter health (`Healthy`, `Unconfirmed`, `Slow`, `Unavailable`, `Recovered`) and isolates a temporarily unavailable inverter instead of pausing the entire plant.
- Recovered inverters automatically rejoin control and Action/service adapters resynchronize their target rather than trusting a stale command cache.
- Configured readback failure remains unavailable instead of being replaced by cached command state.
- Healthy inverters can continue restoring during External Release while an older command remains unresolved on another inverter.
- Every configured inverter is explicitly classified for release eligibility; open-loop/unverified adapters cannot disappear from the decision and reachable pending writes/active settling still block ACK.
- For the first **90 seconds**, External Release remains strict and requires plant-wide independent confirmation at full output. After 90 continuous seconds, degraded release is allowed only when every independently reachable inverter is confirmed full, the remaining inverter(s) are genuinely unavailable, no reachable command is still pending/settling, and no configured adapter is open-loop/unverified.
- Expired/timed-out settle records no longer block later release; only an actively settling command does.
- Degraded release reports unavailable/unverified inverter(s) and total unconfirmed PV capacity in runtime reason/Insights.

## Smart Update and recovery

- Smart Update uses Node-RED API v2 revision protection, transactional backups/recovery, managed-flow fingerprints, and preservation of unrelated Node-RED changes.
- Release tags are pinned to immutable Git commits before download.
- Package/dashboard YAML requires the complete `yaml` 2.x parser with duplicate-key rejection, actual structure/version checks, post-write revalidation, and Home Assistant configuration validation before flow deployment.
- Detached updater ownership is published atomically only after full owner metadata exists; stale recovery is serialized by a separate recovery-owner guard. A refused contender cannot mutate the active owner's helpers, transaction state, resume intent or result file.
- Ordinary safe-shutdown waiting and detached recovery are separate. Repeated clicks while PV/HBC restoration is incomplete cannot reach the installer, and recovery-only mode cannot start a fresh install when no interrupted transaction exists.
- Abrupt updater death can be recovered through the same transaction without losing the saved enabled/disabled intent.
- Verified `complete` and `rolled-back` terminal transactions can republish missing HA helper/status state after a crash, but mismatched terminal records fail safe without rollback or a fresh install.
- A verified install is never rolled back because a result file or notification failed. Required helper/status publication is completed before durable acknowledgement; notification/result artifacts are best effort.
- Acknowledged terminal history is not replayed. A fresh launch marker is persisted before the first awaited resume-intent read so stale rollback history cannot override a later manual disable.
- If rollback recovery cannot restore `hpvc_enabled`, the transaction remains unacknowledged and **in progress**, the saved resume intention is preserved, and the next click remains recovery-only until restoration succeeds.

## Diagnostics, performance and reports

- Daily Control Accuracy persistence now uses one schema/revision contract, including `headlineAttributionRevision`.
- Runtime profiling now attributes cooldown gates, battery-capacity learning, HBC charge priority, final target, transition logging, inverter service-call preparation, and Insights/diagnostics.
- The runtime stale-lock watchdog is increased from **12 s to 30 s** to reduce overlap risk during unusually slow operations.
- Smart Update and full uninstall now use that same **30-second** runtime-lock window before maintenance can proceed, so an evaluation still valid to the controller cannot be treated as idle by maintenance.
- Support reports retain the familiar **Generate report → Generating… → View report** flow. The HTML report is served from `/local/hpvc/support-report.html`.
- The report-reset webhook is local-only. Local viewing resets the tile; remote viewing does not. `/local/` content is not protected by Home Assistant authentication, so expose it only through trusted network paths.
- The old report cache-busting label is replaced by the neutral `hpvc-report` token.

## Maintenance and validation

- Full uninstall now also cleans the HPVC freshness sensor and External Release heartbeat/lease helpers using exact ownership matching.
- Release validation covered control safety, External Release, updater recovery, lock ownership, YAML/templates, safe-shutdown behavior and PV allocation.
- Runtime requirements now follow the supported Node-RED/Node.js matrix rather than the older JavaScript syntax floor.

## Upgrade notes

Supported Home Assistant OS/Supervised Node-RED add-on installations can use **Settings → Maintenance → HPVC updates**. Smart Update preserves HPVC entities, helper values, configuration and saved data. Manual replacement of the Home Assistant package, Node-RED flow and dashboard remains supported.

After a successful Smart Update, use **Quick Reload Home Assistant** from Maintenance when prompted.
