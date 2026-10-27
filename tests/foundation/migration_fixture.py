"""Contained legacy runtime fixture; never imports HA actuator services."""

from dataclasses import replace
import hashlib
from custom_components.hpvc.migration.model import (
    Binding,
    Proof,
    Bridge,
    Inventory,
    Stage,
)
from custom_components.hpvc.migration.handoff import (
    HandoffEngine,
    _FixturePermit,
    _TEST_KEY,
)
from custom_components.hpvc.migration.detector import APPROVED_FINGERPRINT
from custom_components.hpvc.migration.imports import ImportFinalizer
from custom_components.hpvc.legacy import build_preview
from custom_components.hpvc.control.models import (
    PlantConfiguration,
    ControlSettings,
    ImportStage,
)
from custom_components.hpvc.storage import (
    VersionedStore,
    ConfigurationState,
    HistoryState,
    canonical,
)
from custom_components.hpvc.hbc.state import Clock


class LegacyFixture:
    def __init__(self, root, plant_uid="migration-test"):
        self.root = root
        self.plant_uid = plant_uid
        self.at = 100
        self.disabled = False
        self.disabled_at = 0.0
        self.fenced = False
        self.fence_token = ""
        self.runtime_boot = "legacy-runtime-1"
        self.fingerprint = APPROVED_FINGERPRINT
        self.reachable = True
        self.complete = True
        self.pending_update = False
        self.recovery_pending = False
        self.active = ()
        self.queued = ()
        self.possible = ()
        self.pending = ()
        self.obligations = ()
        self.hbc_owned = False
        self.hbc_restored = True
        self.hbc_available = True
        self.hbc_original = ("Self Consumption", "adaptive")
        self.hbc_current = self.hbc_original
        self.hbc_stale = False
        self.safety_unknown = False
        self.stale = False
        self.proof_stale = False
        self.binding = Binding("pv1", "adapter-sig", "number.fixture_limit", 3000)
        self.current_bindings = (self.binding,)
        self.nights = ()
        self.unavailable = False
        self.native_value = 3000.0
        self.disable_calls = []
        self.fence_calls = []
        self.permit = _FixturePermit(_TEST_KEY)
        self.values = {
            "input_number.hpvc_inverter_count": "1",
            "input_number.hpvc_pv1_full_limit": "3000",
            "input_number.hpvc_pv1_low_limit": "0",
            "input_text.hpvc_pv1_limit_number": "number.fixture_limit",
            "input_boolean.hpvc_enabled": "on",
        }
        self.values.update(
            {
                "input_number.hpvc_" + k: str(getattr(ControlSettings(), k))
                for k in ControlSettings.__dataclass_fields__
            }
        )
        self.tx = build_preview(self.values, plant_uid)
        assert self.tx.candidate and not self.tx.issues
        self.config_hash = hashlib.sha256(
            canonical(self.tx.candidate.to_dict()).encode()
        ).hexdigest()

    def clock(self):
        return Clock(1800000000 + self.at, self.at, "migration-clock")

    async def initialize(self):
        self.cs = VersionedStore(
            self.root / "config.json", "configuration", ConfigurationState
        )
        await self.cs.load()
        self.config = ConfigurationState(PlantConfiguration(self.plant_uid))
        await self.cs.commit(self.config, 0)
        self.hs = VersionedStore(self.root / "history.json", "history", HistoryState)
        await self.hs.load()
        self.history = HistoryState(self.plant_uid)
        await self.hs.commit(self.history, 0)
        self.finalizer = ImportFinalizer(
            self.root / "history-import.json", self.plant_uid
        )
        await self.finalizer.load()
        await self.restart()
        return self

    async def restart(self):
        self.engine = HandoffEngine(
            self.root / "handoff.json",
            self.plant_uid,
            APPROVED_FINGERPRINT,
            driver=self,
            permit=self.permit,
        )
        await self.engine.load()

    def inventory(self):
        now = self.clock()
        stamp = (
            replace(now, utc=now.utc - 30, monotonic=now.monotonic - 30)
            if self.stale
            else now
        )
        b = Bridge(
            "hpvc-migration/1.6.0/1",
            self.runtime_boot,
            self.fingerprint,
            self.engine.current.transaction_id,
            self.engine.challenge,
            stamp,
            complete=self.complete,
            master_off=self.disabled,
            disabled_at=self.disabled_at,
            evaluated_at=self.clock().utc
            if self.disabled and self.clock().utc > self.disabled_at
            else 0,
            active=self.active,
            queued=self.queued,
            potentially_issued=self.possible,
            pending_verification=self.pending,
            restore_obligations=self.obligations,
            hbc_owned=self.hbc_owned,
            hbc_restored=self.hbc_restored,
            hbc_available=self.hbc_available,
            hbc_original=self.hbc_original,
            hbc_current=self.hbc_current,
            hbc_observed=replace(now, utc=now.utc - 30, monotonic=now.monotonic - 30)
            if self.hbc_stale
            else now,
            quiescent=not any(
                (
                    self.active,
                    self.queued,
                    self.possible,
                    self.pending,
                    self.obligations,
                )
            ),
            safety_unknown=self.safety_unknown,
            fence_token=self.fence_token,
            command_capability=not self.fenced,
            auto_resume_blocked=self.fenced,
            night_evidence=self.nights,
            controller_bindings=self.current_bindings,
        )
        return Inventory(
            stamp,
            self.reachable,
            self.complete,
            self.fingerprint,
            ("HPVC-owned-tab",),
            ("input_boolean.hpvc_enabled",),
            "fenced" if self.fenced else "running",
            self.runtime_boot,
            True,
            self.pending_update,
            self.recovery_pending,
            b,
        )

    def proofs(self):
        now = self.clock()
        stamp = (
            replace(now, utc=now.utc - 30, monotonic=now.monotonic - 30)
            if self.proof_stale
            else now
        )
        return tuple(
            Proof(
                b,
                self.native_value,
                stamp,
                not self.unavailable,
                night_reference=self.nights[0].reference if self.nights else "",
            )
            for b in self.current_bindings
        )

    async def request_safe_disable(self, tx, fp):
        assert fp == self.fingerprint
        if tx not in self.disable_calls:
            self.disable_calls.append(tx)
        if not self.disabled:
            self.disabled = True
            self.disabled_at = self.clock().utc

    async def fence(self, tx, fp):
        assert (
            fp == self.fingerprint
            and self.disabled
            and not any(
                (
                    self.active,
                    self.queued,
                    self.possible,
                    self.pending,
                    self.obligations,
                    self.hbc_owned,
                )
            )
        )
        if tx not in self.fence_calls:
            self.fence_calls.append(tx)
        self.fenced = True
        self.fence_token = "fenced:" + tx

    async def step(self):
        self.at += 2
        if (
            self.engine.current.stage == Stage.DETECTED
            and self.tx.stage != ImportStage.COMMITTED
        ):
            self.config, self.tx, self.history = await self.finalizer.commit(
                self.cs, self.config, self.tx, self.hs, self.history, today="2026-10-27"
            )
        return await self.engine.advance(
            self.inventory(),
            self.clock(),
            import_transaction=self.tx,
            bindings=self.current_bindings,
            configuration_fingerprint=self.config_hash,
            proofs=self.proofs(),
        )

    async def until(self, stage):
        for _ in range(20):
            if self.engine.current.stage == stage:
                return self.engine.current
            value = await self.step()
            if value.stage == Stage.BLOCKED:
                raise AssertionError(value.reason)
        raise AssertionError("Handoff did not reach " + str(stage))
