"""Continuous original-JS HBC sequences, immutable memory and restart faults."""

from dataclasses import replace, FrozenInstanceError
import gzip, hashlib, json
from pathlib import Path
import unittest
from hbc_support import HbcDriver, summary, memory_summary, probe_summary
from custom_components.hpvc.hbc.state import Clock, HbcMemory, HbcSnapshot
from custom_components.hpvc.hbc.evaluator import evaluate, after_restart

ROOT = Path(__file__).parents[2]
FIXTURE = json.loads(
    gzip.decompress(
        (ROOT / "tests/fixtures/hbc-v1.6-sequences.json.gz").read_bytes()
    ).decode("utf-8")
)


class HbcDifferentialTests(unittest.TestCase):
    def test_reference_digest(self):
        raw = gzip.decompress(
            (ROOT / "tests/fixtures/policy-v1.6-runtime.json.gz").read_bytes()
        )
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE["source_flow_sha256"])


def case(sequence):
    def test(self):
        driver = HbcDriver(sequence["name"])
        for row in sequence["cycles"]:
            result, snapshot = driver.step(row)
            before = snapshot.to_dict()
            self.assertEqual(evaluate(snapshot), result)
            self.assertEqual(before, snapshot.to_dict())
            actual = summary(result)
            actual["memory"] = memory_summary(result.memory, snapshot.clock)
            actual["probe"] = probe_summary(result.memory.pending_probe, snapshot.clock)
            with self.subTest(at=row["input"]["at"]):
                self.assertEqual(actual, row["expected"])
            self.assertEqual(
                HbcMemory.from_dict(result.memory.to_dict()), result.memory
            )
            self.assertFalse(result.physical_writes_authorized)

    return test


for seq in FIXTURE["sequences"]:
    setattr(
        HbcDifferentialTests,
        "test_sequence_" + seq["name"].replace("-", "_").replace(".", "_"),
        case(seq),
    )


class HbcContinuityTests(unittest.TestCase):
    def test_monotonic_clock_over_wall_jumps(self):
        start = Clock(1000, 100, "boot")
        self.assertEqual(Clock(900, 110, "boot").age(start), 10)
        self.assertEqual(Clock(9000, 110, "boot").age(start), 10)
        self.assertIsNone(Clock(1010, 110, "new").age(start))
        self.assertEqual(Clock(1010, 110, "new").age(start, durable=True), 10)

    def test_restart_clears_all_continuous_windows(self):
        c = Clock(1000, 100, "old")
        m = HbcMemory(
            boot_id="old",
            priority_state="exit_hold",
            last_confirmed=c,
            transition_until=c.shift(15),
            persistent_export_since=c,
            healthy_since=c,
        )
        restored = after_restart(m, Clock(1001, 1, "new"))
        self.assertEqual(restored.priority_state, "off")
        for key in (
            "last_confirmed",
            "transition_until",
            "persistent_export_since",
            "healthy_since",
            "pending_probe",
        ):
            self.assertIsNone(getattr(restored, key))
        with self.assertRaises(FrozenInstanceError):
            restored.priority_state = "active"

    def test_interrupted_probe_requires_independent_recovery(self):
        for seq in FIXTURE["sequences"]:
            d = HbcDriver(seq["name"])
            for row in seq["cycles"]:
                result, snapshot = d.step(row)
                if d.memory.pending_probe:
                    restored = after_restart(
                        d.memory, Clock(snapshot.clock.utc + 1, 1, "new")
                    )
                    self.assertIsNone(restored.pending_probe)
                    self.assertTrue(restored.interrupted_probe)
                    self.assertTrue(
                        any(
                            b.requires_recovery
                            for m in restored.batteries
                            for b in m.bands
                        )
                    )
                    return
        self.fail("No original accepted taper probe covered")

    def test_restart_override_retains_originals_and_phase(self):
        for seq in FIXTURE["sequences"]:
            d = HbcDriver(seq["name"])
            for row in seq["cycles"]:
                result, snapshot = d.step(row)
                if (
                    result.override.memory.phase != "inactive"
                    and result.override.memory.previous_strategy
                ):
                    old = result.memory.override
                    restored = after_restart(
                        result.memory, Clock(snapshot.clock.utc + 1, 1, "new")
                    ).override
                    self.assertEqual(restored.phase, old.phase)
                    self.assertEqual(restored.previous_strategy, old.previous_strategy)
                    self.assertEqual(restored.previous_goal, old.previous_goal)
                    self.assertEqual(restored.capture_token, old.capture_token)
                    self.assertIsNone(restored.last_retry)
                    return
        self.fail("No captured negative override covered")

    def test_override_fault_publication_requires_accepted_event_and_reasserts_helper(
        self,
    ):
        from custom_components.hpvc.hbc.state import (
            OverrideMemory,
            AcceptedOverrideStep,
        )
        from custom_components.hpvc.hbc.override import evaluate_override

        row = next(
            row
            for seq in FIXTURE["sequences"]
            for row in seq["cycles"]
            if row["expected"]["override_phase"] == "recovery_unknown_previous"
        )
        _, snap = HbcDriver("fault").step(row)
        c = snap.clock
        memory = replace(
            snap.memory,
            override=OverrideMemory(
                phase="recovery_unknown_previous",
                phase_since=c,
                capture_token="capture",
                fault=True,
            ),
        )
        snap = replace(snap, memory=memory)
        entities = {e.entity_id: e for e in snap.entities}
        result = evaluate_override(snap, entities)
        self.assertTrue(result.memory.fault)
        self.assertIsNone(result.memory.fault_published)
        self.assertIn("fault_notification", [a.step for a in result.actions])
        accepted = AcceptedOverrideStep("fault_notification", c, "capture")
        snap = replace(snap, accepted_override_events=(accepted,))
        result = evaluate_override(snap, entities)
        self.assertEqual(result.memory.fault_published, c)
        self.assertIn("fault_on", [a.step for a in result.actions])

    def test_fault_notification_acceptance_does_not_delay_select_retry(self):
        from custom_components.hpvc.hbc.state import (
            OverrideMemory,
            AcceptedOverrideStep,
        )
        from custom_components.hpvc.hbc.override import evaluate_override

        row = next(
            row
            for seq in FIXTURE["sequences"]
            for row in seq["cycles"]
            if row["expected"]["override_previous_strategy"] is not None
            and row["input"]["all_in"] <= 0
        )
        _, snap = HbcDriver("retry").step(row)
        c = snap.clock
        memory = replace(
            snap.memory,
            override=OverrideMemory(
                phase="entering_strategy",
                phase_since=c,
                capture_token="capture",
                previous_strategy="Self Consumption",
                previous_goal="adaptive",
            ),
        )
        snap = replace(
            snap,
            memory=memory,
            durable_capture_token="capture",
            accepted_override_events=(
                AcceptedOverrideStep("fault_notification", c, "capture"),
            ),
        )
        result = evaluate_override(snap, {e.entity_id: e for e in snap.entities})
        self.assertIn("enter_strategy", [a.step for a in result.actions])
        self.assertIsNone(result.memory.last_retry)
