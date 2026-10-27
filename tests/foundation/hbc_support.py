"""Independent raw fixture inputs to typed native HBC evaluation and fake events."""

from dataclasses import replace
from custom_components.hpvc.hbc.state import (
    Clock,
    RawEntity,
    HbcSnapshot,
    HbcMemory,
    AcceptedOverrideStep,
)
from custom_components.hpvc.hbc.evaluator import evaluate
from custom_components.hpvc.hbc.learning import probe_from_accepted
from custom_components.hpvc.control.decisions import (
    PolicySnapshot,
    PolicyController,
    PolicyMemory,
)
from custom_components.hpvc.control.models import Observation, Quality
from custom_components.hpvc.control.engine import evaluate as control_evaluate

N = 1800000000.0


class HbcDriver:
    def __init__(self, name):
        self.name = name
        self.memory = HbcMemory()
        self.policy_memory = PolicyMemory()
        self.durable = None
        self.override_events = []
        self.last_release = None
        self.last_command = None
        self.last_delta = None

    def step(self, record):
        s = record["input"]
        now = N + s["at"]
        clock = Clock(now, 1000000 + s["at"], self.name)

        def observation(name, value):
            return Observation(
                name,
                value,
                Quality.VALID if value is not None else Quality.UNAVAILABLE,
                now,
                now,
            )

        p = PolicySnapshot(
            self.name + ":" + str(s["at"]),
            now,
            observation("grid", s["grid"]),
            observation("pv", s["pv"]),
            observation("market", s["market"]),
            observation("allin", s["all_in"]),
            (PolicyController("pv1", s["current"], s["full"], s["minimum"]),),
            memory=self.policy_memory,
            enabled=s["enabled"],
        )
        if s.get("last_delta") is not None:
            self.last_delta = s["last_delta"]
            self.last_command = Clock(
                N - s["last_age"], 1000000 - s["last_age"], self.name
            )
        entities = tuple(
            RawEntity(
                e["entity_id"],
                e["state"],
                e["updated_at_utc"],
                e["heartbeat_at_utc"],
                tuple(e["options"]),
            )
            for e in s["entities"]
        )
        token = self.memory.override.capture_token
        events = tuple(e for e in self.override_events if e.capture_token == token)
        snapshot = HbcSnapshot(
            p,
            clock,
            entities,
            self.memory,
            s["permission"],
            s["negative_charge"],
            durable_capture_token=self.durable,
            accepted_override_token=token if events else None,
            accepted_override_steps=tuple(e.step for e in events),
            accepted_override_events=events,
            last_release=self.last_release,
            last_command_delta_w=self.last_delta,
            last_command=self.last_command,
        )
        result = evaluate(snapshot)
        self.memory = result.memory
        self.policy_memory = control_evaluate(replace(p, hbc=result.resolved)).memory
        if s["accept_release"] and result.resolved.increase_required:
            event_id = self.name + ":" + str(s["at"])
            self.memory = replace(
                self.memory,
                pending_probe=probe_from_accepted(
                    event_id, clock, result.increase_w, s["grid"], result.batteries
                ),
            )
            self.last_release = clock
            self.last_command = clock
            self.last_delta = result.increase_w
        # Original queue requests are accepted by a fake event owner; raw HA response
        # may remain delayed. They are never interpreted as physical confirmation.
        for action in result.override.actions:
            self.override_events.append(
                AcceptedOverrideStep(
                    action.step, clock, result.override.memory.capture_token
                )
            )
        if s["durable"]:
            self.durable = self.memory.override.capture_token or None
        return result, snapshot


def summary(result):
    r = result
    batteries = []
    for b in r.batteries:
        t = b.telemetry
        batteries.append(
            dict(
                i=t.index,
                status=b.status,
                maximum=b.max_charge_w,
                max_source=b.max_source,
                eligible=b.eligible,
                headroom=b.raw_headroom_w,
                normal=b.normal_headroom_w,
                taper=b.taper_allowance_w,
                effective=b.effective_ceiling_w,
                learned=b.learned_ceiling_w,
                band=b.band,
                probe=b.probe_eligible,
                awaiting=b.awaiting_confirmation,
                idle=b.idle_startup,
                stable=b.stable_seconds,
                freshness=t.freshness_mode,
                usable=t.telemetry_usable,
                power_fresh=t.power_fresh,
                soc_fresh=t.soc_fresh,
            )
        )
    return dict(
        paused=r.memory.safety_paused,
        recovering=r.safety_recovering,
        valid=r.configuration_valid,
        control=r.control_available,
        order=list(r.order),
        state=r.state,
        display=r.display_state,
        normal=r.normal_headroom_w,
        taper=r.taper_headroom_w,
        total=r.total_power_w,
        enter=r.confirmed_enter,
        remain=r.confirmed_remain,
        engaged=r.engaged,
        increase=r.increase_w,
        unshaped=r.unshaped_increase_w,
        cap=r.step_cap_w,
        target=r.resolved.increase_target_w,
        response=r.response_remaining_s,
        transition=r.transition_remaining_s,
        exit=r.exit_hold_remaining_s,
        export_age=r.persistent_export_age_s,
        suppressed=r.resolved.suppress_export_limiting,
        fallback=r.resolved.persistent_export_fallback,
        large=r.large_step_damped,
        reversal=r.reversal_damped,
        override_phase=r.override.memory.phase,
        override_previous_strategy=r.override.memory.previous_strategy,
        override_previous_goal=r.override.memory.previous_goal,
        override_actions=[
            dict(step=a.step, entity=a.entity_id, option=a.option)
            for a in r.override.actions
            if a.step
            in ("enter_strategy", "enter_goal", "restore_goal", "restore_strategy")
        ],
        batteries=batteries,
    )


def memory_summary(memory, clock):
    out = {}
    for b in memory.batteries:
        bands = {}
        for v in b.bands:
            bands[v.key] = dict(
                ceiling=v.ceiling_w,
                samples=v.samples,
                result=v.result,
                failures=v.failure_count,
                contamination=v.contamination_count,
                recovery=v.requires_recovery,
                last_power=v.last_power_w,
                stable_age=clock.age(v.stable_since) or 0,
                failure_remaining=clock.remaining(v.failure_until),
                contamination_remaining=clock.remaining(v.contamination_until),
                idle_remaining=clock.remaining(v.idle_until),
                last_seen_age=clock.age(v.last_seen, durable=True),
                last_probe_age=clock.age(v.last_probe, durable=True),
                ratio=v.absorbed_ratio,
                expected_share=v.expected_share_w,
                export_increase=v.export_increase_w,
                contaminated_delta=v.contaminated_delta_w,
                contaminated_limit=v.contaminated_limit_w,
            )
        out[str(b.index)] = dict(
            maximum=b.max_charge_w,
            max_age=clock.age(b.max_updated, durable=True),
            charging_cutoff=b.charging_cutoff,
            discharging_cutoff=b.discharging_cutoff,
            bands=bands,
        )
    return out


def probe_summary(probe, clock):
    return (
        None
        if probe is None
        else dict(
            step=probe.step_w,
            export_before=probe.export_before_w,
            age=clock.age(probe.accepted),
            batteries=[
                dict(
                    i=b.index,
                    band=b.band,
                    charging=b.charging_w,
                    ceiling=b.effective_ceiling_w,
                    share=b.expected_share_w,
                    updated=b.power_updated_at_utc,
                    idle=b.idle_startup,
                )
                for b in probe.batteries
            ],
        )
    )
