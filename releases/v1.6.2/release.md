# Home PV Control v1.6.2 — Release notes

Version 1.6.2 is a focused safety/recovery fix for v1.6.1. It retains the five-tab health monitoring and Smart Update protections while repairing unattended recovery after a temporary Node-RED health interruption.

## Fixed

### Follow-up fixes — manual stop and orphan activation gate
- A direct Home Assistant user OFF transition (`user_id` present, `parent_id` absent) cancels `hpvc_auto_resume_pending` **and** the healthy-session witness even if recovery was pending; safety automation OFF transitions preserve a valid reservation. If HPVC is already off or a script/integration has ambiguous context, press **Cancel automatic resume** explicitly.
- Correct the Node-RED **Reconcile orphaned activation gate** package-version check from `1.6.0` to `1.6.2`. It continues refusing reconciliation when a recovery transaction or uncertain updater lock exists, and leaves the reload safety gate set until in-progress is cleared.
- Both corrections retain the `1.6.2` release identifier. Source-level tests do not establish live Home Assistant timing or physical inverter behavior.

### Corrected v1.6.2 safety build
- Completing first-install setup marks onboarding complete but **leaves HPVC disabled** until a person enables it.
- Safety shutdown preserves any previously armed auto-resume reservation, including overlapping Node-RED/input failures; an invalid first-enable attempt cannot create one.
- For an already-disabled HPVC with automatic resume pending, the dashboard now shows **Cancel automatic resume**. Press it to prevent unattended re-enabling. Merely toggling an already-off boolean cannot produce an off-state event in Home Assistant.
- Manual switch-off during normal running invalidates the healthy-session witness. A safety-driven off-state transition does not clear an existing recovery reservation.
- Static checks cannot establish every asynchronous Home Assistant event-order or inverter behavior: conduct live testing before unattended deployment.
- The Node-RED runtime safety guard no longer always clears `hpvc_auto_resume_pending` when it disables an already-running HPVC instance. It remembers recovery intent **only** if that instance had previously run with healthy flows, valid configuration/inputs and completed onboarding.
- Recovery now listens for `sensor.hpvc_node_red_runtime_health` returning to `Ready`; otherwise the previous recovery automation could miss the return to normal even when a pending latch existed.
- Recovery waits for five seconds of continuously valid configuration, required inputs and Node-RED runtime health, and refuses automatic re-enable while Smart Update / activation reload flags remain active.
- A direct manual disable cancels recovery and clears the healthy-runtime witness. First-install setup now explicitly leaves HPVC disabled; attempts to enable without a previously healthy runtime cannot arm unattended recovery.
