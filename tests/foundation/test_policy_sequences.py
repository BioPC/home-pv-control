"""Continuous original policy Function-node sequences and next memory."""

from pathlib import Path
from dataclasses import replace
import json, unittest
from policy_support import make_snapshot, make_views, NOW
from custom_components.hpvc.control.engine import evaluate
from custom_components.hpvc.control.decisions import PolicyMemory
from custom_components.hpvc.execution.models import ExecutionSnapshot

FIXTURE = json.loads(
    (Path(__file__).parents[2] / "tests/fixtures/policy-v1.6-sequences.json").read_text(
        encoding="utf-8"
    )
)


class PolicySequenceTests(unittest.TestCase):
    pass


def case(sequence):
    def test(self):
        memory = PolicyMemory()
        for row in sequence["cycles"]:
            s = row["input"]
            source = row["expected"]
            now = NOW + s["at"]
            p = make_snapshot(s)
            ex = s["execution"]
            last = ex["last"] or {}
            execution = replace(
                p.execution,
                pending_verification=ex["pending"],
                settling=ex["settling"],
                write_lock_reason=ex["lock_reason"],
                pending_action=ex["pending_action"],
                frozen_controller_uids=tuple(
                    str(x).replace("pv", "number.inv") for x in ex["blocked"]
                ),
                cooldown_until_utc=ex["cooldown_until"],
                last_command_delta_w=last.get("delta"),
                last_command_at_utc=last.get("ts", 0) / 1000 if last else None,
            )
            p = replace(
                p,
                now=now,
                memory=memory,
                execution=execution,
                grid=replace(p.grid, reported_at_utc=now, received_at_utc=now),
                pv=replace(p.pv, reported_at_utc=now, received_at_utc=now),
                market=replace(p.market, reported_at_utc=now, received_at_utc=now),
                all_in=replace(p.all_in, reported_at_utc=now, received_at_utc=now),
            )
            p = replace(
                p,
                rebalance_pending=s.get("rebalance", False)
                or (
                    sequence["name"] == "controller-recovery-rebalance"
                    and s["at"] >= 61
                ),
            )
            views = make_views(s)
            r = evaluate(p, views=views)
            memory = r.memory
            actual = dict(
                action=r.intent.action.value,
                status=r.intent.status,
                requested=r.intent.requested_plant_target_w,
                calculated=r.intent.calculated_plant_target_w,
                price_mode=r.intent.price_limiting,
                remembered_price_mode=memory.price_limiting,
                cooldown_active=r.intent.cooldown_active,
                cooldown_until=r.intent.cooldown_until_utc * 1000,
                night_active=memory.night.active,
                night_pending=not memory.night.active
                and memory.night.entry_candidate_since_utc is not None,
                night_entry_since=(memory.night.entry_candidate_since_utc or 0) * 1000,
                night_recovery_since=(memory.night.recovery_candidate_since_utc or 0)
                * 1000,
                rebalance_applied=r.allocation.rebalance_applied,
                rebalance_confirmed=r.allocation.rebalance_confirmed,
            )
            with self.subTest(at=s["at"]):
                for k, v in actual.items():
                    with self.subTest(field=k):
                        self.assertEqual(v, source[k])
                self.assertEqual(
                    {
                        t.controller_uid: t.target_w
                        for t in r.allocation.result.controller_targets
                    },
                    {t["uid"]: t["target"] for t in source["targets"]},
                )
                self.assertEqual(
                    {t.controller_uid: t.native_value for t in r.represented.targets}
                    if r.represented
                    else {},
                    {t["uid"]: t["native"] for t in source["represented"]},
                )

    return test


for seq in FIXTURE["sequences"]:
    setattr(
        PolicySequenceTests, "test_sequence_" + seq["name"].replace("-", "_"), case(seq)
    )
