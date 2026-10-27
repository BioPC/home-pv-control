"""Negative-price override state transitions and ordered intent DATA; never services."""

from dataclasses import replace
import json
from .state import OverrideMemory, OverrideResult, HbcActionIntent
from .observations import text, available
from ..inverter.base import fingerprint
from ..control.night_restore import fresh

STRATEGY = "input_select.house_battery_strategy"
GOAL = "input_select.house_battery_strategy_charge_goal"
FORCED_STRATEGY = "Charge"
FORCED_GOAL = "batteries are full"


def evaluate_override(snapshot, entities):
    clock = snapshot.clock
    policy = snapshot.policy
    old = snapshot.memory.override
    memory = old
    strategy = entities.get(STRATEGY)
    goal = entities.get(GOAL)
    sv = text(strategy)
    gv = text(goal)
    present = strategy is not None and goal is not None
    valid = fresh(policy.all_in, clock.utc, max_age=7200)
    negative = valid and policy.all_in.value <= 0
    positive = valid and policy.all_in.value > 0
    force = (
        policy.enabled
        and negative
        and snapshot.permission
        and snapshot.negative_charge_permission
        and present
    )
    revoked = not snapshot.permission or not snapshot.negative_charge_permission
    disable = not policy.enabled and not policy.automatic_safety_pause
    exit_requested = positive or revoked or disable
    actions = []
    capture = False
    reason = "Negative all-in override inactive."
    if memory.phase == "inactive" and force:
        unknown = sv == FORCED_STRATEGY and gv == FORCED_GOAL
        token = fingerprint(
            [clock.boot_id, clock.monotonic, policy.evaluation_id, sv, gv]
        )[:32]
        memory = OverrideMemory(
            phase="recovery_unknown_previous" if unknown else "entering_strategy",
            phase_since=clock,
            capture_token=token,
            previous_strategy=None if unknown or not available(strategy) else sv,
            previous_goal=None if unknown or not available(goal) else gv,
            fault=unknown,
        )
    issued = memory.forced_write_issued or bool(
        snapshot.accepted_override_token == memory.capture_token
        and any(
            step in ("enter_strategy", "enter_goal")
            for step in snapshot.accepted_override_steps
        )
    )
    memory = replace(
        memory,
        forced_write_issued=issued,
        error=snapshot.override_step_error or memory.error,
    )
    if (
        memory.phase in ("entering_strategy", "entering_goal", "active")
        and exit_requested
        and not issued
    ):
        memory = OverrideMemory()
        reason = "Override request ended before any forced write was issued; no restore sequence is needed."
    if memory.phase == "inactive":
        if negative:
            reason = (
                "Negative all-in protection active: PV is locked at configured inverter minimums; "
                + (
                    "native HBC override entities are not installed, so no HBC strategy is changed."
                    if not present
                    else "Enable HBC is off, so no HBC strategy is changed."
                    if not snapshot.permission
                    else "negative-price HBC charging is disabled, so no HBC strategy is changed."
                )
            )
        return OverrideResult(
            memory,
            minimum_lock=negative,
            hbc_force_requested=bool(force),
            reason=reason,
        )

    def phase(name):
        nonlocal memory
        if memory.phase != name:
            memory = replace(
                memory, phase=name, phase_since=clock, retries=0, error=None
            )

    frozen = not valid and not revoked and not disable
    if frozen:
        reason = "All-in price unavailable while the override is active; preserving the current HBC override state."
    elif (
        exit_requested
        and not memory.phase.startswith("restoring")
        and memory.phase != "recovery_unknown_previous"
    ):
        phase("restoring_goal")
    elif force and memory.phase.startswith("restoring"):
        phase("entering_strategy")

    def queue(step, action, entity, option=None):
        nonlocal memory
        events = [
            event
            for event in snapshot.accepted_override_events
            if event.capture_token == memory.capture_token
            and event.step
            in ("enter_strategy", "enter_goal", "restore_goal", "restore_strategy")
        ]
        last = events[-1] if events else None
        age = clock.age(last.accepted) if last else None
        in_phase = [
            event
            for event in events
            if event.step == step
            and (
                memory.phase_since is None
                or event.accepted.utc >= memory.phase_since.utc
            )
        ]
        memory = replace(
            memory,
            last_retry=last.accepted if last else None,
            last_step=last.step if last else memory.last_step,
            retries=len(in_phase),
        )
        if last is None or age is None or age >= 5:
            actions.append(
                HbcActionIntent(
                    step,
                    action,
                    entity,
                    option,
                    memory.capture_token,
                    step in ("enter_strategy", "enter_goal"),
                )
            )

    if memory.phase == "recovery_unknown_previous":
        acknowledged = snapshot.acknowledge_unknown_override
        if (
            available(strategy)
            and sv != FORCED_STRATEGY
            and available(goal)
            and gv != FORCED_GOAL
            and acknowledged
        ):
            memory = OverrideMemory()
            reason = "Unknown previous values acknowledged only after non-forced HBC values were independently observed."
        else:
            reason = "Previous HBC values are unknown; non-forced strategy/goal observations and explicit acknowledgement are required."
    if not frozen and memory.phase == "entering_strategy":
        durable = snapshot.durable_capture_token == memory.capture_token and bool(
            memory.capture_token
        )
        if not durable:
            capture = True
            reason = "Saving the original HBC strategy and charge goal durably before the first forced HBC write."
        elif not available(strategy) or not available(goal):
            reason = "Waiting for both HBC input_select entities; PV remains locked at inverter minimums."
        elif not memory.previous_strategy or not memory.previous_goal:
            memory = replace(
                memory,
                previous_strategy=memory.previous_strategy or sv,
                previous_goal=memory.previous_goal or gv,
                capture_token=fingerprint(
                    [memory.capture_token, clock.monotonic, sv, gv]
                )[:32],
                last_retry=None,
                retries=0,
            )
            capture = True
            reason = "Saving newly recovered original HBC values durably before the first forced HBC write."
        elif FORCED_STRATEGY not in strategy.options:
            reason = "HBC strategy option Charge is missing; PV remains locked."
        elif FORCED_GOAL not in goal.options:
            reason = "HBC charge-goal option batteries are full is missing; PV remains locked."
        elif sv == FORCED_STRATEGY:
            phase("entering_goal")
            reason = (
                "HBC strategy confirmed as Charge; preparing the forced charge goal."
            )
        else:
            queue(
                "enter_strategy",
                "input_select.select_option",
                STRATEGY,
                FORCED_STRATEGY,
            )
            reason = "Setting HBC strategy to Charge before changing the charge goal."
    if not frozen and memory.phase == "entering_goal":
        if sv != FORCED_STRATEGY:
            phase("entering_strategy")
            reason = "HBC strategy is not yet confirmed as Charge."
        elif not available(goal) or FORCED_GOAL not in goal.options:
            reason = "Waiting for forced charge-goal option; PV remains locked."
        elif gv == FORCED_GOAL:
            phase("active")
            memory = replace(memory, fault=False, fault_published=None)
            reason = "Negative all-in override active: PV locked at user minimums and HBC grid charging forced."
        else:
            queue("enter_goal", "input_select.select_option", GOAL, FORCED_GOAL)
            reason = "Setting the forced HBC charge goal after Charge was confirmed."
    if memory.phase == "active":
        if valid:
            reason = "Negative all-in override active: PV locked at user minimums and HBC grid charging forced."
        if force and sv != FORCED_STRATEGY:
            phase("entering_strategy")
        elif force and gv != FORCED_GOAL:
            phase("entering_goal")
    if not frozen and memory.phase == "restoring_goal":
        if not memory.previous_goal:
            phase("recovery_unknown_previous")
            reason = "Saved charge goal is unavailable; refusing to guess."
        elif gv == memory.previous_goal:
            phase("restoring_strategy")
            reason = "Saved HBC charge goal confirmed; restoring the previous strategy."
        elif not available(goal) or memory.previous_goal not in goal.options:
            reason = "Cannot restore the saved HBC charge goal yet; PV remains locked."
        else:
            queue(
                "restore_goal", "input_select.select_option", GOAL, memory.previous_goal
            )
            reason = "Restoring the saved HBC charge goal before the strategy."
    if not frozen and memory.phase == "restoring_strategy":
        if not memory.previous_strategy:
            phase("recovery_unknown_previous")
            reason = "Saved strategy is unavailable; refusing to guess."
        elif sv == memory.previous_strategy:
            memory = OverrideMemory()
            reason = "Saved HBC charge goal and strategy are confirmed restored; normal HPVC control may resume."
        elif (
            not available(strategy) or memory.previous_strategy not in strategy.options
        ):
            reason = "Cannot restore the saved HBC strategy yet; PV remains locked."
        else:
            queue(
                "restore_strategy",
                "input_select.select_option",
                STRATEGY,
                memory.previous_strategy,
            )
            reason = (
                "Restoring the saved HBC strategy after the charge goal was confirmed."
            )
    age = clock.age(memory.phase_since)
    stuck = (
        memory.phase not in ("inactive", "active") and age is not None and age >= 300
    )
    fault = memory.phase == "recovery_unknown_previous" or stuck
    memory = replace(memory, fault=fault if memory.phase != "inactive" else False)
    if fault and memory.phase != "inactive":
        accepted_publication = next(
            (
                event
                for event in reversed(snapshot.accepted_override_events)
                if event.capture_token == memory.capture_token
                and event.step in ("fault_on", "fault_notification")
            ),
            None,
        )
        if accepted_publication:
            memory = replace(memory, fault_published=accepted_publication.accepted)
        published_age = clock.age(memory.fault_published)
        publication_due = (
            memory.fault_published is None
            or published_age is None
            or published_age >= 300
        )
        helper_on = (
            text(entities.get("input_boolean.hpvc_negative_override_fault")) == "on"
        )
        if not helper_on:
            actions.append(
                HbcActionIntent(
                    "fault_on",
                    "input_boolean.turn_on",
                    "input_boolean.hpvc_negative_override_fault",
                    capture_token=memory.capture_token,
                )
            )
        if publication_due or not helper_on:
            actions.append(
                HbcActionIntent(
                    "fault_notification",
                    "persistent_notification.create",
                    "",
                    capture_token=memory.capture_token,
                    data_json=json.dumps(
                        {
                            "notification_id": "hpvc_negative_override_fault",
                            "title": "HPVC negative-price override needs attention",
                            "message": reason,
                        }
                    ),
                )
            )
    if old.fault and not memory.fault:
        if not snapshot.acknowledge_unknown_override:
            actions.append(
                HbcActionIntent(
                    "fault_off",
                    "input_boolean.turn_off",
                    "input_boolean.hpvc_negative_override_fault",
                )
            )
        actions.append(
            HbcActionIntent(
                "fault_dismiss",
                "persistent_notification.dismiss",
                "",
                data_json=json.dumps(
                    {"notification_id": "hpvc_negative_override_fault"}
                ),
            )
        )
    return OverrideResult(
        memory,
        tuple(actions),
        capture,
        negative or memory.phase != "inactive",
        memory.phase == "recovery_unknown_previous" or memory.fault,
        bool(force),
        reason,
    )
