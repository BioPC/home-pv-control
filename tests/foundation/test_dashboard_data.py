"""Presentation-only evidence, persistence and report regression coverage."""

import json
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.control.models import (
    Observation,
    PlantConfiguration,
    Quality,
)
from custom_components.hpvc.dashboard.builder import REPORT_SECTIONS, parity_dashboard
from custom_components.hpvc.dashboard.data import (
    HISTORY_LIMIT,
    DashboardObserver,
    DashboardState,
    HistoryPoint,
    Insight,
    accuracy,
    collect,
    observe_execution,
    priority_state,
)
from custom_components.hpvc.dashboard.presentation import (
    CONDITION_KEYS,
    dashboard_attributes,
)
from custom_components.hpvc.execution.models import (
    ExecutionLedger,
    HandoffRecord,
    Lane,
    OperationState,
    OwnershipState,
    PhysicalOperation,
    TransportStatus,
    VerificationEvidence,
    VerificationStatus,
)
from custom_components.hpvc.hbc.state import Clock, HbcMemory

NOW = 1800000000.0


def runtime(value=1000, *, priority="off", kind="ha_readback"):
    raw = NS(state="Charge", last_reported=datetime.fromtimestamp(NOW, UTC))
    grid = NS(state="0", last_reported=raw.last_reported)
    proof = VerificationEvidence(
        "proof",
        "controller",
        "signature",
        "operation",
        kind,
        VerificationStatus.VERIFIED,
        observed_value_w=value,
        reported_at_utc=NOW,
        received_at_utc=NOW,
    )
    op = PhysicalOperation(
        "operation",
        "batch",
        "step",
        "native-epoch",
        "controller",
        "generic_number",
        "signature",
        "reference",
        state=OperationState.VERIFIED,
        transport=TransportStatus.COMPLETED,
        verification=VerificationStatus.VERIFIED,
        evidence_ids=("proof",),
        prepared_at_utc=NOW - 2,
        dispatch_id="native-dispatch",
        dispatch_started_at_utc=NOW - 1,
        service_completed_at_utc=NOW,
        representable_controller_target_w=value,
    )
    ledger = ExecutionLedger(
        "dashboard-test",
        ownership=HandoffRecord(
            state=OwnershipState.NATIVE_ACTIVE, owner_epoch="native-epoch"
        ),
        operations=(op,),
        evidence=(proof,),
    )
    row = NS(
        uid="controller",
        view=NS(
            available=True,
            independently_verifiable=True,
            configuration_signature="signature",
            observation=NS(
                limit=Observation("number.limit", value, Quality.VALID, NOW, NOW)
            ),
            operating_range=NS(full_w=1000),
        ),
    )
    cfg = PlantConfiguration(
        "dashboard-test", insights_enabled=True, grid_power_sensor="sensor.grid"
    )
    return NS(
        configuration=cfg,
        ledger=NS(current=ledger),
        manager=NS(current=NS(effective=(row,), faults=())),
        recovery_required=False,
        migration_state="native_active",
        policy_runtime=NS(
            accepted=NS(
                last_clock=Clock(NOW, 100, "boot"),
                hbc=HbcMemory(priority_state=priority),
            ),
            fault=None,
        ),
        policy_proposal=None,
        state_reader=lambda entity: (
            grid
            if entity == "sensor.grid"
            else raw
            if entity == "input_select.house_battery_strategy"
            else None
        ),
        owner=NS(closed=False),
        publish=lambda: None,
    )


class EvidenceTests(unittest.TestCase):
    def test_normal_needs_verified_independent_execution(self):
        p = observe_execution(runtime(), NOW)
        self.assertEqual((p.mode, p.evidence_ids), ("Normal", ("proof",)))

    def test_limit_is_observed_not_requested(self):
        r = runtime(400)
        r.configuration = replace(r.configuration, enabled_intent=False)
        self.assertEqual(observe_execution(r, NOW).mode, "Limit")

    def test_missing_fleet_is_unknown(self):
        r = runtime()
        r.manager.current.effective = ()
        self.assertEqual(observe_execution(r, NOW).mode, "unknown")

    def test_proposal_cannot_establish_mode(self):
        r = runtime()
        r.ledger.current = replace(r.ledger.current, operations=(), evidence=())
        r.policy_proposal = NS(policy=NS(intent=NS(status="Limit")))
        self.assertEqual(observe_execution(r, NOW).mode, "unknown")

    def test_simulated_epoch_is_rejected(self):
        r = runtime()
        op = replace(r.ledger.current.operations[0], owner_epoch="simulation")
        r.ledger.current = replace(
            r.ledger.current,
            ownership=HandoffRecord(
                state=OwnershipState.NATIVE_ACTIVE, owner_epoch="simulation"
            ),
            operations=(op,),
        )
        self.assertEqual(observe_execution(r, NOW).mode, "unknown")

    def test_stale_or_mismatched_readback_is_unknown(self):
        for update in (
            replace(
                runtime().manager.current.effective[0].view.observation.limit,
                reported_at_utc=NOW - 181,
            ),
            Observation("number.limit", 500, Quality.VALID, NOW, NOW),
        ):
            r = runtime()
            r.manager.current.effective[0].view.observation.limit = update
            self.assertEqual(observe_execution(r, NOW).mode, "unknown")

    def test_stale_proof_or_recovery_is_unknown(self):
        self.assertEqual(observe_execution(runtime(), NOW + 91).mode, "unknown")
        r = runtime()
        r.recovery_required = True
        self.assertEqual(observe_execution(r, NOW).mode, "unknown")

    def test_legacy_helper_proof_is_rejected(self):
        self.assertEqual(
            observe_execution(runtime(kind="legacy_helper"), NOW).mode, "unknown"
        )

    def test_pending_verification_is_not_assumed_settling(self):
        r = runtime()
        op = replace(
            r.ledger.current.operations[0],
            state=OperationState.AWAITING_VERIFICATION,
            verification=VerificationStatus.PENDING,
            evidence_ids=(),
        )
        r.ledger.current = replace(r.ledger.current, operations=(op,), evidence=())
        p = observe_execution(r, NOW)
        self.assertEqual(
            (p.mode, p.verification_pending, p.settling), ("unknown", True, None)
        )

    def test_priority_is_authoritative_memory_and_expires(self):
        for state, expected in (
            ("off", "Off"),
            ("waiting", "Waiting"),
            ("active", "Active"),
            ("exit_hold", "Waiting"),
        ):
            self.assertEqual(priority_state(runtime(priority=state), NOW), expected)
        self.assertEqual(
            priority_state(runtime(priority="active"), NOW + 91), "unknown"
        )

        stable = runtime(priority="active")
        stable.state_reader(
            "input_select.house_battery_strategy"
        ).last_reported = datetime.fromtimestamp(NOW - 86400, UTC)
        self.assertEqual(priority_state(stable, NOW), "Active")

    def test_absent_hbc_priority_is_unknown(self):
        r = runtime()
        r.state_reader = lambda _: None
        self.assertEqual(priority_state(r, NOW), "unknown")

    def test_charge_needs_independent_hbc_proof(self):
        r = runtime(priority="active")
        self.assertEqual(observe_execution(r, NOW).mode, "Normal")
        p = VerificationEvidence(
            "hbc-proof",
            "hbc",
            "hbc-signature",
            "hbc-op",
            "independent_native_state",
            VerificationStatus.VERIFIED,
            reported_at_utc=NOW,
            received_at_utc=NOW,
            observed_native_value="Charge",
            provenance="owner=native-epoch;dispatch=hbc-dispatch",
        )
        op = PhysicalOperation(
            "hbc-op",
            "hbc-batch",
            "hbc-step",
            "native-epoch",
            "hbc",
            "hbc",
            "hbc-signature",
            "hbc-ref",
            lane=Lane.HBC,
            state=OperationState.VERIFIED,
            transport=TransportStatus.COMPLETED,
            verification=VerificationStatus.VERIFIED,
            evidence_ids=("hbc-proof",),
            prepared_at_utc=NOW - 2,
            dispatch_started_at_utc=NOW - 1,
            dispatch_id="hbc-dispatch",
            expected_native_value="Charge",
        )
        r.ledger.current = replace(
            r.ledger.current,
            operations=(*r.ledger.current.operations, op),
            evidence=(*r.ledger.current.evidence, p),
        )
        self.assertEqual(observe_execution(r, NOW).mode, "Charge")

    def test_no_simulated_cooldown_promotion(self):
        self.assertIsNone(observe_execution(runtime(), NOW).cooldown)


class CollectionTests(unittest.TestCase):
    def point(self, at=NOW):
        return HistoryPoint(at, "Limit", evidence_ids=("proof",))

    def test_accuracy_exact_formula(self):
        s = DashboardState("plant")
        for i, value in enumerate((0, 10, 50)):
            s = collect(
                s,
                self.point(NOW + i),
                day="2027-01-15",
                grid=value,
                grid_stamp=NOW + i,
                target=0,
                deadband=25,
            )
        m = accuracy(s)
        self.assertAlmostEqual(m["accuracy_percent"], 200 / 3)
        self.assertEqual(m["mae_w"], 20)
        self.assertAlmostEqual(m["rmse_w"], math.sqrt(2600 / 3))

    def test_unknown_stale_and_nan_not_measured(self):
        for point, grid, stamp in (
            (HistoryPoint(NOW), 0, NOW),
            (self.point(), 0, NOW - 181),
            (self.point(), float("nan"), NOW),
        ):
            s = collect(
                DashboardState("plant"),
                point,
                day="2027-01-15",
                grid=grid,
                grid_stamp=stamp,
            )
            self.assertEqual((s.measured, s.unavailable), (0, 1))
            self.assertIsNone(accuracy(s)["accuracy_percent"])

    def test_duplicate_grid_sample_not_double_counted(self):
        s = collect(
            DashboardState("plant"),
            self.point(),
            day="2027-01-15",
            grid=0,
            grid_stamp=NOW,
        )
        s = collect(s, self.point(NOW + 30), day="2027-01-15", grid=0, grid_stamp=NOW)
        self.assertEqual((s.measured, s.duplicate), (1, 1))
        self.assertEqual(accuracy(s)["coverage_percent"], 50)

    def test_midnight_resets_day_not_timeline(self):
        s = collect(
            DashboardState("plant"),
            self.point(),
            day="2027-01-15",
            grid=0,
            grid_stamp=NOW,
        )
        s = collect(s, HistoryPoint(NOW + 1), day="2027-01-16", insights_enabled=False)
        self.assertEqual((s.measured, len(s.insights), len(s.points)), (0, 0, 2))

    def test_insights_order_bounds_and_disable(self):
        s = DashboardState("plant")
        for i in range(25):
            s = collect(
                s,
                HistoryPoint(NOW + i),
                day="2027-01-15",
                extra_insights=(("Test", str(i)),),
            )
        self.assertEqual(len(s.insights), 20)
        self.assertEqual(s.insights[0].message, "24")
        s = collect(
            s,
            HistoryPoint(NOW + 26),
            day="2027-01-15",
            extra_insights=(("Test", "disabled"),),
            insights_enabled=False,
        )
        self.assertEqual(s.insights[0].message, "24")

    def test_bounded_history(self):
        points = tuple(HistoryPoint(NOW + i) for i in range(HISTORY_LIMIT))
        s = collect(
            DashboardState("plant", points=points),
            HistoryPoint(NOW + HISTORY_LIMIT),
            day="2027-01-15",
        )
        self.assertEqual(len(s.points), HISTORY_LIMIT)
        self.assertEqual(s.points[0].at, NOW + 1)

    def test_backward_clock_does_not_reset_or_insert_confirmed_state(self):
        s = collect(DashboardState("plant"), self.point(), day="2027-01-15")
        with self.assertRaises(SchemaError):
            collect(s, self.point(NOW - 1), day="2027-01-15")

    def test_codec_rejects_unbounded_or_nonfinite_data(self):
        with self.assertRaises(SchemaError):
            DashboardState(
                "plant", insights=tuple(Insight(NOW, "a", "b") for _ in range(21))
            )
        with self.assertRaises(SchemaError):
            DashboardState("plant", absolute_error=float("nan"))
        self.assertEqual(
            DashboardState.from_dict(DashboardState("plant").to_dict()),
            DashboardState("plant"),
        )

    def test_visibility_conditions_use_plain_native_state_in_both_versions(self):
        def walk(v):
            if isinstance(v, dict):
                if v.get("condition") in ("state", "numeric_state"):
                    self.assertNotIn("attribute", v)
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        walk(parity_dashboard())
        self.assertEqual(len(CONDITION_KEYS), 19)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_populates_measured_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runtime()
            observer = DashboardObserver(r, Path(tmp) / "d.json", clock=lambda: NOW)
            r.dashboard_observer = observer
            await observer.load()
            await observer.sample()
            report = dashboard_attributes(r, [], now=NOW)["ui_report_sections"]
            self.assertEqual(report["Today’s Accuracy"]["accuracy_percent"], 100)
            self.assertEqual(report["Today’s Accuracy"]["measured"], 1)
            self.assertEqual(report["Power Control"]["executed_mode"], "Normal")

    async def test_local_midnight_uses_configured_zone(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2027, 1, 15, 21, 59, 59, tzinfo=UTC).timestamp()
            observer = DashboardObserver(
                runtime(), Path(tmp) / "d.json", clock=lambda: now
            )
            observer.zone = timezone(timedelta(hours=2))
            await observer.load()
            self.assertEqual(observer.state.local_date, "2027-01-15")
            now += 2
            await observer.sample()
            self.assertEqual(observer.state.local_date, "2027-01-16")
            self.assertEqual(observer.state.unavailable, 1)

    async def test_restart_retains_history_but_inserts_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dashboard.json"
            r = runtime()
            o = DashboardObserver(r, path, clock=lambda: NOW)
            await o.load()
            self.assertFalse(o.fault)
            o.clock = lambda: NOW + 1
            await o.sample()
            self.assertEqual(o.latest.mode, "Normal")
            again = DashboardObserver(r, path, clock=lambda: NOW + 2)
            await again.load()
            self.assertEqual(again.latest.mode, "unknown")
            self.assertEqual(len(again.state.points), 3)
            self.assertEqual(again.state.measured, 1)

    async def test_corrupt_store_does_not_overwrite_or_change_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dashboard.json"
            path.write_text("invalid")
            r = runtime()
            ledger = r.ledger.current
            o = DashboardObserver(r, path, clock=lambda: NOW)
            await o.load()
            self.assertTrue(o.fault)
            self.assertEqual(path.read_text(), "invalid")
            self.assertIs(r.ledger.current, ledger)

    async def test_report_populates_ten_sections_and_unknown_zero_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runtime()
            r.manager.current.effective = ()
            o = DashboardObserver(r, Path(tmp) / "d.json", clock=lambda: NOW)
            r.dashboard_observer = o
            await o.load()
            ui = dashboard_attributes(r, [], now=NOW)
            self.assertEqual(list(ui["ui_report_sections"]), list(REPORT_SECTIONS))
            self.assertEqual(
                ui["ui_report_sections"]["Inverters"]["effective_count"], 0
            )
            self.assertEqual(
                ui["ui_report_sections"]["Power Control"]["executed_mode"], "unknown"
            )
            self.assertFalse(ui["ui_maintenance"]["production_transport_authorized"])
            self.assertIsNone(
                ui["ui_report_sections"]["Today’s Accuracy"]["accuracy_percent"]
            )
            self.assertEqual(
                ui["ui_report_sections"]["HBC & Battery Status"]["available"], "on"
            )
            json.dumps(ui, allow_nan=False)

    async def test_stale_presentation_cannot_reuse_current_confirmed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runtime()
            o = DashboardObserver(r, Path(tmp) / "d.json", clock=lambda: NOW)
            await o.load()
            await o.sample()
            self.assertEqual(o.latest.mode, "Normal")
            self.assertEqual(o.presentation(NOW + 91)["current"]["mode"], "unknown")

    async def test_unloaded_entry_does_not_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runtime()
            o = DashboardObserver(r, Path(tmp) / "d.json", clock=lambda: NOW)
            await o.load()
            revision = o.store.revision
            r.owner.closed = True
            await o.sample()
            self.assertEqual(o.store.revision, revision)
