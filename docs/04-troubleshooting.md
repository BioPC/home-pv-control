[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Troubleshooting

Use the generated support report first. **Executive summary**, **Decision evaluation**, **Sensor health**, **Inverters**, and **Today’s Insights** usually identify the blocking condition quickly.

## Contents

- [Start here](#start-here)
- [Installation and configuration](#installation-and-configuration)
- [PV control and inverter behavior](#pv-limiting-and-restore)
- [HBC and Charge Priority](#hbc-and-charge-priority)
- [Dashboard, accuracy and reports](#dashboard-and-graphs)
- [Node-RED and advanced diagnostics](#node-red-and-advanced-diagnostics)
- [Smart Update](#smart-update-troubleshooting)
- [Manual upgrade / Node-RED flow removal](#manual-upgrade--node-red-flow-removal)
- [Uninstall and reinstall](#uninstall-troubleshooting)

## Start here

1. Confirm **Configuration status** is valid.
2. Check **Sensor health** for unavailable or invalid required inputs.
3. Check **Decision evaluation** and **Status since**.
4. Check **Today’s Insights** for transitions, write warnings, or override faults.
5. Generate a fresh report before changing settings.

## Installation and configuration

### Entities are unavailable after upgrading to v1.3.0

Replace the Home Assistant package, Node-RED flow, and dashboard together. Version 1.3.0 uses `hpvc_*` entity IDs; old `pv_ems_*` helpers are not migrated automatically.

### Restore defaults does not appear or cannot run

Confirm that `script.hpvc_restore_defaults` exists and that the current dashboard YAML is loaded. Reload packages or restart Home Assistant after replacing `hpvc_config.yaml`.

### Configuration error: invalid power thresholds

HPVC requires `Export Start < Target Export < Import Restore` and `Import Restore >= 0 W`. Writes remain blocked until corrected.

### Node-RED says entity not found

Check the exact entity IDs configured for grid power, prices, PV power, inverter limits, and optional HBC entities. Empty or invalid IDs are intentionally treated as configuration errors.

## Negative all-in-price override problems

At a valid all-in price `<= 0`, HPVC always applies PV-minimum protection. Forced HBC charging occurs only when **Enable HBC** and **Force charge at negative price** are both on and the native HBC strategy/charge-goal entities exist. Exit, or disabling either permission, restores the saved charge goal first and then the saved strategy.

If entry or restoration does not complete, check that both HBC entities are available, their required or saved options still exist, `/config/hpvc-data/` is writable, and `runtime-history.json` is valid. After five minutes in an unconfirmed phase, the fault helper and persistent notification identify the stuck phase.

For `recovery_unknown_previous`:

1. Select the intended HBC strategy and charge goal manually.
2. Confirm neither entity still shows the forced values.
3. Turn off `input_boolean.hpvc_negative_override_fault`.
4. Wait for the next HPVC evaluation.

Do not edit `runtime-history.json` manually unless this supported recovery path cannot run.

If the negative-price override journal is lost or fails schema validation while HBC is still left at the forced `Charge` / `batteries are full` values, HPVC cannot safely reconstruct the previous strategy or charge goal. In that case it enters `recovery_unknown_previous`, keeps the fault active, and requires the manual recovery steps above before normal control can resume. This is especially important if the all-in price is already positive when the journal problem is discovered: HPVC will not guess the missing pre-override values.

If the journal filesystem write fails (for example because the filesystem is full or read-only), HPVC clears the active-write guard and leaves the latest state eligible for the normal 10-second persistence retry. A single failed file write therefore does not permanently stall later journal saves.

## HPVC turned itself off after a sensor outage

This is expected. If a required configuration or live control input becomes invalid while HPVC is running, the safety automation switches off the master toggle. HPVC resumes automatically only after all required inputs have been healthy for 5 continuous seconds and only when the shutdown was automatic. A manually disabled HPVC remains off.

### Identify which required sensor failed

**Today’s Insights** records the entity ID and validation reason. Identical faults are de-duplicated. During active Night Restore, expected nighttime loss of PV-power and inverter-limit telemetry is not treated as a daytime fault.

## One inverter is unavailable

During normal daytime control, HPVC isolates an unavailable inverter and continues controlling healthy inverters. If all configured inverter paths are unavailable, it pauses. The unreachable inverter may still produce, so HPVC cannot guarantee the export target during the outage. Release acknowledgement and destructive maintenance still require all configured inverters to be verified.

During active Night Restore, expected nighttime loss of PV-power and inverter-limit telemetry is tolerated while grid and price safety inputs remain monitored.

## PV limiting and restore

### PV does not limit

Check:

- HPVC is enabled;
- configuration status is valid;
- Market/export price is at or below the PV limiting price;
- grid export is more negative than Export Start;
- measured PV is above Min PV for control;
- cooldown is inactive;
- the requested change exceeds Deadband;
- inverter entities are writable and full/minimum powers are correct.

### Repeated export/import reversals

After an inverter write, HPVC waits for fresh or materially changed PV telemetry before making another ordinary closed-loop correction. A bounded timeout prevents control from remaining frozen if timestamps do not advance. If large reversals continue, check for fast house-load changes and verify grid/PV update cadence.

Near-simultaneous identical inverter write requests are suppressed for 2.5 seconds.

### PV restores to full at night

This is expected. Night Restore starts after valid measured PV remains at or below the configured threshold for 120 seconds. After activation, HPVC restores available inverter limits to full and suspends normal PV calculations. Expected nighttime loss of PV-power or inverter-limit telemetry is then tolerated.

If PV telemetry disappears while the timer is already running, **Night Restore pending** may complete only when `sun.sun` also reports `below_horizon`; otherwise strict validation returns. Recovery requires valid PV above `max(25 W, threshold + 15 W)` for 30 continuous seconds.

### Import happens while PV is limited

Import Restore can raise inverter limits even when measured PV is below Min PV for control. Low measured production may itself be caused by the active inverter limit.

### External PV release waits on one inverter

In v1.5.4, healthy inverters may continue restoring to full while a previous command remains unconfirmed on another inverter. External Release stays strict for the first **90 seconds**. If the request remains continuously active and one or more configured inverter readbacks are still genuinely unavailable after 90 seconds, HPVC can acknowledge a **degraded release** only when every reachable inverter is independently confirmed at full. A reachable inverter that is still below full continues to block release. The runtime reason and **Today’s Insights** identify the unavailable inverter(s) and the total PV capacity that could not be confirmed.

### One inverter becomes unavailable

In v1.5.4, a single temporarily unavailable inverter no longer pauses normal control for the rest of the plant. HPVC marks that inverter **Unavailable**, excludes it from active allocation, and continues controlling the remaining healthy inverter(s). If all configured inverter control/readback paths are unavailable, PV control pauses safely.

When communication returns, HPVC marks the inverter **Recovered** and automatically reconciles it with the current target on the next safe control cycle. Today’s Insights records the unavailable/recovery transition; no extra dashboard card or Home Assistant helper is required.

### Inverter targets look wrong

Check inverter count, entity assignment, Full power, Minimum power, current limit, requested target, and Difference from target in the report. A total increase must never reduce an individual inverter, and a total decrease must never raise one.

## Percentage-controlled inverter does not follow the requested Watt target

Set that inverter's **Limit unit** to **Percent**, while keeping Full power and Minimum power configured in watts. In **Number entity** mode HPVC converts the Watt target to 0–100% for the writable number entity and converts the entity state back to watts for command-state verification. If the Home Assistant `number` entity exposes a `step`, HPVC rounds the percentage command to that supported resolution and verifies against the effective Watt equivalent, avoiding false write warnings on whole-percent controls. Confirm that the percentage number entity itself reports a numeric value between 0 and 100 and that its min/max range can represent the configured Minimum power through 100% full power. In **Action/service** mode configure the integration's action/service, dynamic value field and command step instead of creating a bridge number. Add a real numeric readback entity when the integration exposes one. See [Inverter compatibility](05-inverter-compatibility.md) for the current status matrix and the distinction between direct, action/service-adapter, and unsuitable export-limit controls. Command-state or mirrored values do not prove that the physical inverter applied the downstream command.

## Rate limiter and 10-second control

The HPVC trigger remains every 10 seconds. A stable 10-second check may skip the heavier evaluation to reduce CPU and allocation pressure. Grid, PV and Marstek battery AC power use a cumulative 20 W + 2% significance threshold compared with the last full evaluation. Battery SOC is reduced to whole-percentage changes for the stable-input hash, while other control-relevant states remain exact-match. HPVC still forces a complete evaluation at least every 30 seconds and does not skip pending safety, write/recovery, settings or adapter-heartbeat work.

During confirmed Night Restore, the steady nighttime state may now be skipped. This is expected. If valid PV rises above the Night Restore recovery threshold, or a recovery timer has already started, the limiter is bypassed so recovery is checked on the normal timer cadence.

### `settingsTrigger` ReferenceError

If a support report shows `ReferenceError: Cannot access 'settingsTrigger' before initialization` from `Read HPVC Core Configuration`, update to v1.4.2 or later. The settings-trigger flag is now declared before its first use so the 10-second control loop can complete normally.

## Charge Priority repeatedly releases and limits PV

If Charge Priority releases PV but the batteries do not absorb the additional power, grid export can return and HPVC can reduce PV again. A brief loss of confirmed charging first starts the bounded transition-settle window while the exit hold remains active, avoiding an immediate opposite PV correction during that transient. If the batteries still cannot absorb the released PV, persistent export can fall back to normal limiting and a later evaluation may retry the release while HBC still requests charging and usable headroom remains. This can still look like a limit/release cycle at roughly the cooldown/forced-evaluation cadence. Check the HBC executing sub-strategy, measured battery charge power, SOC/cutoff state, telemetry freshness, and the Charge Priority response/settle diagnostics. HPVC intentionally does not add a long exponential backoff because that could delay charging after the battery/plant becomes able to absorb power again.

## HBC and Charge Priority

### Battery should be charging but PV is limited

Check for every configured battery:

- AC power is valid and uses the expected sign while charging;
- SOC is numeric;
- maximum charge power is numeric and greater than 0;
- `input_number.house_battery_count` matches the installation;
- RS485 control is enabled;
- HBC is executing `Charge` or `Charge PV`;
- **Enable HBC** is on.

One healthy battery with usable headroom is enough to continue Charge Priority. Full, stale, unavailable, maximum-power, or taper-saturated batteries are excluded independently.

### Why is Charge Priority off outside the PV-limiting price zone?

This is expected. Outside the normal PV-limiting price zone, PV is already unrestricted, so HPVC does not need a Charge Priority intervention. HBC may still execute `Charge` or `Charge PV` normally.

Negative all-in-price mode is separate: PV is held at minimum, and forced HBC charging requires both HBC permissions.

### HBC strategy changes unexpectedly

During normal operation HPVC does not select HBC strategies. The exception is the optional negative-price override, which may temporarily force `Charge` when both HBC permissions are enabled and later restore the saved strategy. If **Enable HBC** is off, negative-price operation is PV-only.

If the strategy changed outside this case, check HBC itself, other automations, and the report timeline.

### Charge Priority says Off while HBC is executing Charge

This can be correct. Charge Priority is **Off** when HPVC intervention is not needed, such as outside the PV-limiting zone, during negative-price override, or when no battery has eligible headroom. Use the report's Charge Priority reason and per-battery eligibility table for the exact cause.

## Dashboard and graphs

### Insights card is empty

Confirm that `input_text.hpvc_insight_1` through `input_text.hpvc_insight_10` exist, deploy the supplied flow, and wait for the next evaluation. The current-day journal is restored from `hpvc-data/runtime-history.json` when the supported Home Assistant configuration mount is writable.

### Live Inputs does not show inverter 6–10

Rows appear only for slots included by `input_number.hpvc_inverter_count`.

### Price Zones in older or custom dashboards

The packaged dashboard includes the **HBC Price Intervals** graph with theme-aware grid and tooltip styling. It is shown only when onboarding is complete, HBC control is enabled, and `binary_sensor.hpvc_hbc_available` confirms HBC is available.

To have Smart Update manage the dashboard automatically, switch to the file-backed dashboard installation described in [`01-installation.md`](01-installation.md): place `hpvc_dashboard.yaml` in the Home Assistant configuration root, next to `configuration.yaml` (normally `/config/hpvc_dashboard.yaml`), and register it once under `lovelace:`.

### Mobile report navigation buttons appear only after refresh

Use the current v1.5.4 report flow and generate a new report after deployment. Older already-published HTML files do not contain the updated mobile navigation script.

## Accuracy diagnostics

### One or more accuracy-loss factors remain 0.0%

This is not necessarily a problem. The four factors show contributions to the **headline loss**, so a factor stays 0.0% when no eligible harmful excursion was attributed to that cause. If Daily Control Accuracy is 100%, all four factors should be 0.0%.

For deeper analysis, use **Raw attributable shares**, **Attribution coverage**, and the exclusion diagnostics in the support report. These engineering metrics use different eligibility and do not have to match the compact dashboard percentages.

### All headline loss appears as Other

**Other** means HPVC saw a real harmful excursion but did not have enough safe evidence to assign it to House load, PV availability, or Control response. Short causal events can be carried across brief accuracy-ineligible gaps, but HPVC will not guess across weak telemetry continuity. If battery-power telemetry is uncertain, House-load inference is deliberately suppressed.

### A short appliance spike was not shown under House load

The evaluation that starts a normal PV-control cooldown is retained for accuracy, but later cooldown/settling samples are excluded. Very short events can still be missed when they occur entirely between source-sensor updates or inside an already-active cooldown.

### A visible grid spike is not appearing under House load changes

A grid spike is not classified from grid power alone. HPVC briefly reconciles it with PV, battery-power, and inverter-limit movement so cloud changes, battery movement, and controller response are not mistaken for house load. If source sensors never publish a changed value while a very short event exists, the detector cannot recover it later.

### Internal attribution diagnostics

For advanced troubleshooting, Node-RED global context stores the latest attribution diagnostic record and a short rolling history with grid/PV/battery/limit deltas, causal weights, event age, and command verification state. These diagnostics do not alter dashboard behavior.

## Reports

### Generate report does not change to View report

Wait for generation to finish. **View report** appears only after publication succeeds. If report storage was temporarily unavailable during startup/redeploy, HPVC now retries storage initialization automatically every 30 seconds; a Generate report click also queues one request and asks the bounded retry path to re-initialize storage. If a previously-ready mount disappears later, a failed report file write or atomic publication invalidates the cached ready state so the same recovery path can re-probe it instead of remaining falsely marked ready. If publication still does not complete, check the persistent notification and Node-RED error log.

### The report time did not change

The report is an on-demand snapshot. Press **Generate report** again and wait for **View report** before reopening it.

### Generate or View report state appears stuck

Reload the dashboard and check Node-RED for a report-generation error. A successful generation publishes `/local/hpvc/support-report.html` and enables **View report**. Opening the report from the local Home Assistant network clears the Ready state through the bundled local-only webhook; remote viewing intentionally cannot trigger that reset. The file itself remains until a newer report replaces it.

> Security note: `/local/` files are served without Home Assistant authentication. Keep the HPVC report URL limited to trusted network/exposure paths.

### Decision evaluation says Triggered while PV currently limited says No

This is valid. **Triggered** describes the current threshold condition; **PV currently limited** describes the actual control state. Cooldown, deadband, minimum PV, price mode, configuration errors, unavailable inputs, or another guard can prevent a write.

### Action result says No inverter change

The report shows the recorded action. It does not infer Reduce PV or Increase PV from a triggered condition alone.

### TXT export differs from HTML

Both formats use the same report model. HTML groups consecutive identical Insight runs, while TXT keeps every raw Insight event as a separate row. Other field values and diagnostics should match.

### Report tile remains on Generating after a deploy

Startup cleanup clears stale generation state and abandoned temporary files while leaving an already-published valid report intact.

## Node-RED and advanced diagnostics

### The flow imports as four tabs

This is expected. Import the complete `hpvc_flow.json`; Inputs, Engine, Outputs, and Reports are designed to work together.

### No Write warning Insight appears

The plant write/settle lock is bounded by `max(120 seconds, 4 × cooldown)`; with the default 30-second cooldown it releases after 120 seconds so HPVC can retry. Verification continues separately. An unresolved inverter write episode reaches the extended failure warning after `max(120 seconds, 12 × cooldown)`; with the default cooldown this is 360 seconds (6 minutes). Retry writes do not reset that per-inverter episode, so a dead inverter can still reach the final warning. HPVC also warns after three consecutive unconfirmed supersessions for the same inverter.

### Advanced diagnostic data is invalid or truncated

`input_text.hpvc_last_targets_json` is limited to 255 characters. When necessary, HPVC stores a smaller valid diagnostic object instead of truncating JSON mid-field.

### Report shows a runtime data notice

Live grid, PV, and price values are captured when the report is generated, while decision and taper diagnostics describe the latest completed HPVC evaluation. A notice means those runtime diagnostics are old, mismatched in time, or not yet available; it does not change control behavior.

### Repeated or truncated Battery telemetry Insights

The flow records a Battery telemetry warning when a battery becomes unusable and a recovery after 60 seconds of healthy telemetry. Truncated `input_text.hpvc_insight_*` values are startup fallback data only; older duplicate rows disappear at the next local-midnight reset.

For deeper telemetry, cutoff, persistence, attribution, and report semantics, see [How it works](03-how-it-works.md).

## Node-RED latency or heap growth

v1.4.1 removes the two full Home Assistant state-table deep clones present in v1.4.0 and no longer transports the complete HA state map in `msg.hpvc`. If Node-RED latency or memory growth is still observed, first test the current v1.5.4 build unchanged for several hours so the remaining behavior can be isolated from the confirmed v1.4.0 allocation problem.

The runtime stores bounded diagnostics in the Node-RED global context key `homePvControlPerformanceDiagnostics`. It contains the latest cycle total, maximum and rolling average evaluation time, expanded per-stage timings for cooldown gates, battery-capacity learning, HBC charge priority, final-target calculation, transition logging, inverter service-call preparation and Insights/diagnostics, and—when the Function sandbox permits it—a memory sample no more than once per minute. No per-cycle timing or heap history is retained by this diagnostic.

If heap sampling reports unavailable, this only means `process.memoryUsage()` is not exposed to Function nodes in that Node-RED environment; HPVC control continues normally. The HTML and TXT support reports include the current timing and heap diagnostics, so attach a fresh support report when investigating issue #2. Also include the Node-RED version, Home Assistant version, approximate entity count, and whether memory returns after garbage collection or continues establishing a higher baseline.

## Excessive Home Assistant action calls

v1.4.3 deduplicates HPVC-owned status, reason, Insights, targets JSON and accuracy-diagnostics publishing and periodically forces a full dashboard refresh every five minutes. The support report Performance Diagnostics section now includes rate-limiter full/skip counters and the latest limiter reason. On large Home Assistant installations, individual Home Assistant Node-RED action/current-state nodes may still be expensive depending on the installed websocket palette; HPVC reduces how often its dashboard-only actions are invoked but cannot change the palette's internal state-cache implementation.

### Percent target differs slightly from calculated Watts

This is expected when the writable percentage entity has a coarse `step`. HPVC uses the nearest representable percentage for normal targets. At the configured minimum it rounds upward when necessary, so the effective command never falls below the configured minimum Watt limit.

### Action/service adapter does not control the inverter

Check that the action is written as `domain.service`, the fixed-data field contains valid JSON, and the value field matches the integration's service schema. If the inverter requires an enable switch, mode selection, trigger button, or heartbeat, put those calls in the per-inverter pre/post action arrays. Configure a numeric readback entity when available so HPVC can verify the applied limit. The readback must use the same unit as the configured Limit unit. If an action/service call itself fails, HPVC clears that inverter's cached command and retries on a later eligible cycle; check the persistent notification and Node-RED/Home Assistant logs for the rejected payload. Pre/main/post calls execute sequentially and stop on the first failed Home Assistant action, but HPVC does not insert built-in delays. Use a Home Assistant script when timed waits are required. The advanced JSON helper fields are limited to 255 characters.

## Action/service writes again soon after Node-RED restart

After Node-RED loses its runtime command cache, an Action/service inverter performs one synchronization write on the next normal/full evaluation. Startup synchronization itself is not treated as an ordinary PV target change and therefore does not start the normal PV cooldown. If grid/PV conditions then require a different target on the following cycle, a second write can occur sooner than the configured cooldown. This is intentional so startup synchronization cannot block a newly required control response. A real readback entity is recommended when the integration provides one.

### Price zone appears to enter/leave at exactly the threshold

From v1.5.2, Insight transitions use the remembered hysteresis state only when the current market/threshold values are valid. A transition into the limiting zone requires the market price to be at or below the limiting threshold; a transition out requires the price to be above the restore threshold. This prevents false `left`/`entered` alternation at values such as `0.0000` or `-0.0`.

## Smart Update troubleshooting

### Smart Update says another updater process is active

This is a safe refusal. The second detached process does not alter HPVC update helpers, status, resume intent, recovery transaction, or the active owner's result file. Wait for the active Smart Update to finish and then retry if needed. Do not delete `updater.lock` while the recorded owner process is still running. If the lock exists but its ownership metadata is unreadable or incomplete, Smart Update deliberately refuses automatic reclamation; investigate the interrupted update before removing the lock manually. Stale-owner recovery is serialized by `/config/hpvc-data/update-recovery/updater.reclaim.lock`; do not remove that guard while its recorded recovery process is alive. If the detached updater died abruptly **after safe shutdown had already authorized detached launch** and the dashboard still says an update is running, press **Update HPVC** again: HPVC launches a recovery-only probe without clearing the saved resume state. A live owner refuses the probe; a dead owner proceeds through verified transaction recovery only when an interrupted transaction exists. If HPVC is still in the ordinary safe-shutdown/restoration phase, repeated clicks are ignored and cannot bypass that gate. If the terminal transaction was already completed or rolled back but its required HA publication was lost, the same recovery-only probe verifies that recorded outcome and republishes it only while the terminal record is still unacknowledged. Once acknowledged, old terminal history is never replayed. Result-file and notification failures are best effort and cannot roll back a verified installation or block a verified rollback from restoring its saved live state; if the current files/flows no longer match the record, HPVC reports attention instead of changing them.

If rollback recovery cannot restore `hpvc_enabled`, HPVC keeps the update marked in progress and retains the saved resume intention. Press **Update HPVC** again after the Home Assistant service issue is resolved; the retry stays recovery-only and continues the same transaction.


### Update available is not detected

Press **Check for updates** and read the Maintenance status and **Last checked** timestamp. HPVC queries the latest public GitHub release; Internet/DNS/GitHub API failures are reported in `input_text.hpvc_update_status`. A successful process exit is ignored rather than being reported as a failure. The automatic check also runs at Node-RED startup and every six hours. When notifications are enabled, a newly detected newer release creates one persistent **HPVC update available** notification; repeated checks of the same release do not create it again. If the installed HPVC version is newer than GitHub's latest published release, Maintenance reports that state explicitly and does not show the update button.

### Update stops while restoring PV

Smart Update never replaces files or flows until the safe shutdown watcher confirms the post-disable engine evaluation and PV/HBC restoration lifecycle has completed. If that cannot be confirmed within the bounded wait, the update is cancelled before replacement. Check inverter limits/control availability and retry.

### Smart Update says the managed package was not found

Smart Update intentionally requires `/config/packages/hpvc_config.yaml`. If HPVC is installed from a custom package path, use the manual upgrade procedure so the updater cannot create a second package definition beside the custom one.

### Update fails after downloading

The updater validates the downloaded package, dashboard and flow before replacement. If managed-file or Node-RED deployment fails after replacement starts, it attempts to restore the previous managed files and previous complete Node-RED flow set and then returns HPVC to its pre-update enabled state. HPVC entity-registry entries and `hpvc-data` are never deleted by Smart Update.

### Smart Update requires a newer Home Assistant Node-RED integration

The downloaded HPVC flow can declare a newer `node-red-contrib-home-assistant-websocket` version than the current Node-RED global configuration. Smart Update checks this before replacing any HPVC file or flow. Update the Home Assistant Node-RED integration manually, deploy/restart Node-RED if required, then run **Check for updates** and retry. HPVC deliberately does not rewrite shared palette dependencies automatically.


### Custom/pasted dashboard was not updated

This is intentional. Smart Update overwrites `/config/hpvc_dashboard.yaml` only when that exact managed file existed before the update. A dashboard/view pasted into Home Assistant, or a dashboard stored under another path, must be updated manually from the new release.

### HPVC stays Off after Quick Reload

HPVC resumes automatically only when it was enabled before the update. If it was already Off, Smart Update preserves that state. If it was previously On but remains Off after a successful Quick Reload, check the Maintenance status and Home Assistant logs before enabling it manually.

### Quick Reload does not activate a future change

The Maintenance button uses `homeassistant.reload_all`, which reloads YAML domains that support reload and performs Home Assistant's basic configuration check first. If a future HPVC release explicitly requires a full restart for a non-reloadable Home Assistant change, follow that release's notes.

## Manual upgrade / Node-RED flow removal

### Manual upgrade: remove and reinstall the HPVC Node-RED flows

Use **Settings → Maintenance → Manual upgrade → Remove HPVC flows** when the HPVC tabs need to be rebuilt but you want to keep the Home Assistant package, helpers/entities, dashboard and saved HPVC data. The action first runs the same safe PV/HBC shutdown verification used by Smart Update/Full uninstall, then removes only the four HPVC tabs. Re-import the complete current `node-red/hpvc_flow.json` before enabling HPVC again.

After successful removal through the Manual upgrade action, Maintenance shows **Node-RED flows: Removed**. Once the supplied flow is re-imported and starts, it changes to **Ready**. If the HPVC flows were removed manually or the flow state cannot be confirmed, the dashboard shows **Not detected**. If automatic removal fails or leaves an inconsistent state, it shows **Needs attention**.

If a configured inverter is unavailable/unverifiable or cannot be confirmed at full limit, the Manual upgrade flow-removal action stops before removing any tab. Restore connectivity/readback and retry. If automatic tab removal itself fails, the persistent notification identifies the failure; no HPVC Home Assistant configuration or saved data is deleted by this Manual upgrade action.

## Uninstall troubleshooting

### Automatic uninstall fails

Read the persistent notification first. The failure message includes the failing step/source when available.

- If the **Uninstall HPVC** button is still present, correct the reported problem and retry.
- If registry cleanup already removed the button, restart Home Assistant so the helper is recreated, then retry cleanup.
- Do not manually delete inverter configuration before retrying a safe-shutdown failure; HPVC needs that information to decide whether a restore is required.
- A safe-shutdown timeout leaves destructive cleanup unstarted so inverter configuration is not erased.

### Uninstall waits for PV restore

This can be normal while an inverter command or verification is still active.

- With configured and reachable inverters, HPVC waits for the active command and then restores configured full limits.
- With **no inverter configured**, uninstall treats PV restore as unnecessary and continues.
- With sleeping/offline/unavailable or otherwise unverifiable inverter control, HPVC does not treat the missing inverter as already restored. The watcher waits only within the bounded safe-shutdown window, then stops uninstall before configuration/flow removal and identifies the affected inverter(s). Restore connectivity/readback, verify those inverter limits are at their configured full values, and retry.
- If an HPVC-owned HBC negative-price override is still in an unresolved recovery state, restore/acknowledge that HBC state and retry.

### WebSocket error: request requires a `type`

Current v1.5.4 rebuilds a clean `config/entity_registry/list` WebSocket payload immediately before the entity-registry API node and uses the live-proven per-entity removal payload for `config/entity_registry/remove`.

If this error appears with a modified/older flow, re-import the complete current v1.5.4 flow rather than rewriting the registry API node manually.

### Node-RED Global Context Store is disabled

HPVC requires **Enable Global Context Store** on the Home Assistant server configuration used by the supplied Node-RED flow. The bundled server node ships with this enabled. If you replace or rebind that server configuration, verify the option remains enabled.

### Automatic Node-RED tab removal is unavailable

This is a fallback/recovery case. A normal full uninstall removes the HPVC Node-RED tabs automatically. HPVC discovers its tabs by exact labels, not fixed/import-specific flow IDs.

Automatic cleanup tries:

1. local Node-RED Admin API;
2. direct Admin API with `SUPERVISOR_TOKEN`;
3. Supervisor ingress;
4. manual follow-up if none of those paths can remove the tabs.

A Node-RED cleanup failure does not block deletion of HPVC-owned files/data. If the completion notification requests manual follow-up, remove only the remaining HPVC tabs and then restart Home Assistant.

### Reinstall restores old settings

Current v1.5.4 full uninstall resets the complete HPVC helper set to fresh-install defaults and waits 15 seconds for RestoreEntity persistence before entity-registry removal.

If an older or interrupted uninstall left stale values:

1. install/deploy the current complete v1.5.4 package;
2. run **Uninstall HPVC** again and let it complete;
3. restart Home Assistant after the final Inputs tab disappears;
4. reinstall v1.5.4.

A normal update intentionally preserves helper values; only the full uninstall performs the clean-reset sequence.

### External release stays requested but acknowledgement turns off

HPVC protects the handoff with a 45-second verification lease. While the external-release request is active, Node-RED renews an engine heartbeat and verification timestamp on each full evaluation. If Node-RED stops, the HA-side watchdog revokes the lease automatically. Check Node-RED health, stale-input messages, per-inverter readback freshness, pending write verification, and any open-loop Action/service adapter without an independent readback. Open-loop adapters intentionally block degraded acknowledgement.

### Required sensor is numeric but HPVC reports it stale

HPVC checks communication freshness as well as numeric state. Power/inverter observations use `sensor.hpvc_source_freshness`, a Home Assistant template sensor that refreshes every 30 seconds and reads HA-core `last_reported` timestamps directly. Node-RED rejects the data if that snapshot itself stops updating, and it deliberately never uses `last_updated` as a heartbeat for constant valid values. Market/all-in price sensors have a longer scheduled-data window. Unknown freshness fails safe until Home Assistant supplies a valid report timestamp.

[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)
