"""Durable dry-run ownership transaction. No production migration backend exists."""

import asyncio
import uuid
import hashlib
from dataclasses import replace
from ..codec import SchemaError
from ..storage import VersionedStore, canonical
from ..control.models import ImportStage
from .model import Handoff, Stage
from .detector import detect

_TEST_KEY = object()


class _FixturePermit:
    def __init__(self, key):
        if key is not _TEST_KEY:
            raise SchemaError("Explicit contained migration fixture required")
        self.key = key

    def __reduce__(self):
        raise TypeError("Fixture permit cannot be imported or persisted")


class HandoffEngine:
    """A fixture driver is required for disable/fence; normal setup only loads records."""

    def __init__(
        self, path, plant_uid, expected_fingerprint, *, driver=None, permit=None
    ):
        if driver is not None and (
            type(permit) is not _FixturePermit or permit.key is not _TEST_KEY
        ):
            raise SchemaError("Production legacy mutation is not implemented in dev.7")
        self.store = VersionedStore(path, "migration_handoff", Handoff)
        self.current = Handoff(plant_uid)
        self.expected = expected_fingerprint
        self.driver = driver
        self.challenge = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.revalidation_required = False

    async def load(self):
        old = await self.store.load()
        if old:
            if old.plant_uid != self.current.plant_uid:
                raise SchemaError("Wrong migration plant")
            self.current = old
            self.revalidation_required = old.stage != Stage.UNASSESSED
            if old.native_owner_ready:
                await self._save(
                    Stage.POST,
                    native_owner_ready=False,
                    reason="restart_requires_fresh_post_fence_attestation",
                )
        else:
            await self.store.commit(self.current, 0)
        return self.current

    async def _save(self, stage, **changes):
        changes.setdefault("native_owner_ready", False)
        value = replace(
            self.current,
            stage=stage,
            history=(*self.current.history[-127:], stage.value),
            **changes,
        )
        await self.store.commit(value, self.store.revision)
        self.current = value
        return value

    async def block(self, reason):
        return await self._save(
            Stage.BLOCKED,
            reason=reason,
            resume_stage=self.current.resume_stage
            if self.current.stage == Stage.BLOCKED
            else self.current.stage,
        )

    def _bridge(self, inventory, now):
        b = inventory.bridge
        h = self.current
        age = now.age(b.observed) if b else None
        if (
            b is None
            or b.version != "hpvc-migration/1.6.0/1"
            or not b.complete
            or b.transaction_id != h.transaction_id
            or b.challenge != self.challenge
            or b.fingerprint != h.legacy_fingerprint
            or b.runtime_boot != h.runtime_boot
            or age is None
            or age > 15
            or b.safety_unknown
        ):
            raise SchemaError("missing_stale_or_unbound_bridge_evidence")
        return b

    def _drained(self, b):
        return (
            not any(
                (
                    b.active,
                    b.queued,
                    b.potentially_issued,
                    b.pending_verification,
                    b.restore_obligations,
                )
            )
            and b.quiescent
        )

    def _restored(self, b, proofs, now, after):
        if b.controller_bindings != self.current.bindings:
            raise SchemaError("legacy_controller_binding_changed")
        if not self._drained(b):
            raise SchemaError("unresolved_legacy_work")
        if not b.hbc_available or b.hbc_owned or not b.hbc_restored:
            raise SchemaError("HBC_unavailable_or_unrestored")
        if b.hbc_original != b.hbc_current or not all(b.hbc_original):
            raise SchemaError("HBC_original_state_not_independently_observed")
        if (
            b.hbc_observed is None
            or now.age(b.hbc_observed) is None
            or now.age(b.hbc_observed) > 15
            or b.hbc_observed.utc < after
        ):
            raise SchemaError("HBC_restoration_observation_stale")
        if len(proofs) != len(self.current.bindings):
            raise SchemaError("controller_disappeared_or_duplicate_proof")
        for binding in self.current.bindings:
            matches = [p for p in proofs if p.binding == binding]
            if len(matches) != 1:
                raise SchemaError("controller_identity_or_configuration_replaced")
            p = matches[0]
            type(p).from_dict(p.to_dict())  # finite/type validation of live evidence
            if binding.full_w <= 0 or binding.source not in (
                "ha_readback",
                "enphase_readback",
                "opendtu_api",
            ):
                raise SchemaError("unverifiable_controller_source")
            age = now.age(p.observed)
            if age is None or age > 15 or p.observed.utc < after:
                raise SchemaError("full_output_evidence_stale")
            if not p.available:
                # Only the exact source-supported previously confirmed full-output
                # reference can cover unavailable-at-night; no new full assumption.
                refs = [
                    n
                    for n in b.night_evidence
                    if n.reference == p.night_reference and n.binding == binding
                ]
                if len(refs) != 1:
                    raise SchemaError("unavailable_without_bound_Night_Restore_proof")
                n = refs[0]
                if (
                    not n.night_active
                    or not n.independently_verified
                    or n.value_w != binding.full_w
                    or n.confirmed.utc < n.last_possible_issue_utc
                    or n.confirmed.utc > now.utc
                    or now.age(n.current_night_observed) is None
                    or now.age(n.current_night_observed) > 15
                    or n.current_night_observed.utc < after
                ):
                    raise SchemaError("Night_Restore_proof_invalid_or_conflicting")
            elif binding.source == "enphase_readback" and (
                not p.enabled
                or not p.production_mode
                or not binding.device_identity
                or p.device_identity != binding.device_identity
            ):
                raise SchemaError("Enphase_readiness_or_device_identity_unproven")
            elif binding.source == "opendtu_api" and (
                p.command_status != "success"
                or not binding.device_identity
                or p.device_identity != binding.device_identity
            ):
                raise SchemaError("OpenDTU_status_or_device_identity_unproven")
            elif p.value_w is None or abs(p.value_w - binding.full_w) > max(
                1, binding.full_w * 0.001
            ):
                raise SchemaError("full_output_not_observed")

    async def advance(
        self,
        inventory,
        now,
        *,
        import_transaction=None,
        bindings=(),
        configuration_fingerprint="",
        proofs=(),
        finish_disabled=False,
    ):
        async with self.lock:
            if self.driver is None:
                return await self.block("dry_run_driver_unavailable_production_closed")
            h = self.current
            try:
                type(inventory).from_dict(inventory.to_dict())
                state, reason = detect(inventory, now, self.expected)
                if state != Stage.DETECTED:
                    if h.stage in (Stage.UNASSESSED, Stage.UNKNOWN):
                        return await self._save(Stage.UNKNOWN, reason=reason)
                    return await self.block(reason)
                if h.stage in (Stage.UNASSESSED, Stage.UNKNOWN):
                    return await self._save(
                        Stage.DETECTED,
                        transaction_id=uuid.uuid4().hex,
                        legacy_fingerprint=inventory.fingerprint,
                        runtime_boot=inventory.bridge.runtime_boot
                        if inventory.bridge
                        else inventory.heartbeat_boot,
                        reason="",
                    )
                if inventory.fingerprint != h.legacy_fingerprint:
                    raise SchemaError("flow_fingerprint_changed")
                b = self._bridge(inventory, now)
                if (
                    configuration_fingerprint
                    and h.configuration_fingerprint
                    and configuration_fingerprint != h.configuration_fingerprint
                ):
                    raise SchemaError("native_configuration_changed")
                if self.revalidation_required:
                    # Fresh challenge response is mandatory after any restart, including
                    # a restored HA backup. Mutations are idempotent by transaction ID.
                    self.revalidation_required = False
                if h.stage == Stage.BLOCKED:
                    return h  # explicit recovery/new transaction required
                if h.stage == Stage.DETECTED:
                    if (
                        import_transaction is None
                        or import_transaction.issues
                        or import_transaction.candidate is None
                        or import_transaction.stage != ImportStage.COMMITTED
                    ):
                        raise SchemaError("import_validation_required")
                    if (
                        import_transaction.candidate.plant_uid != h.plant_uid
                        or not configuration_fingerprint
                    ):
                        raise SchemaError("import_plant_or_fingerprint_invalid")
                    actual = hashlib.sha256(
                        canonical(import_transaction.candidate.to_dict()).encode()
                    ).hexdigest()
                    if (
                        configuration_fingerprint != actual
                        or bindings != b.controller_bindings
                    ):
                        raise SchemaError(
                            "import_configuration_or_controller_capture_mismatch"
                        )
                    return await self._save(
                        Stage.IMPORT,
                        import_id=import_transaction.transaction_id,
                        bindings=tuple(bindings),
                        configuration_fingerprint=configuration_fingerprint,
                    )
                if h.stage == Stage.IMPORT:
                    return await self._save(Stage.QUIESCING, disabled_requested=now)
                if h.stage == Stage.QUIESCING:
                    await self.driver.request_safe_disable(
                        h.transaction_id, h.legacy_fingerprint
                    )
                    if (
                        not b.master_off
                        or b.disabled_at < h.disabled_requested.utc
                        or b.evaluated_at <= b.disabled_at
                    ):
                        return h
                    return await self._save(Stage.RECONCILING)
                if h.stage == Stage.RECONCILING:
                    self._restored(b, proofs, now, h.disabled_requested.utc)
                    return await self._save(Stage.RESTORED, restored_at=now)
                if h.stage == Stage.RESTORED:
                    self._restored(b, proofs, now, h.restored_at.utc)
                    return await self._save(Stage.FENCING)
                if h.stage == Stage.FENCING:
                    self._restored(b, proofs, now, h.restored_at.utc)
                    # This fixture operation never touches a production runtime.
                    await self.driver.fence(h.transaction_id, h.legacy_fingerprint)
                    return await self._save(Stage.POST)
                if h.stage in (Stage.POST, Stage.READY, Stage.DISABLED, Stage.ACTIVE):
                    if (
                        b.command_capability
                        or not b.auto_resume_blocked
                        or not b.fence_token
                        or not b.master_off
                        or b.evaluated_at <= b.disabled_at
                    ):
                        raise SchemaError(
                            "legacy_command_capability_or_auto_resume_returned"
                        )
                    if h.fence_token and h.fence_token != b.fence_token:
                        raise SchemaError("fence_generation_changed_backup_or_redeploy")
                    if h.fence_observed is None:
                        self._restored(b, proofs, now, h.restored_at.utc)
                        return await self._save(
                            Stage.POST, fence_token=b.fence_token, fence_observed=now
                        )
                    self._restored(b, proofs, now, h.fence_observed.utc)
                    if (
                        tuple(bindings) != h.bindings
                        or configuration_fingerprint != h.configuration_fingerprint
                    ):
                        raise SchemaError(
                            "post_fence_rediscovery_or_configuration_changed"
                        )
                    value = replace(
                        h,
                        stage=Stage.DISABLED
                        if finish_disabled or h.stage == Stage.DISABLED
                        else Stage.READY,
                        native_owner_ready=True,
                        reason="",
                        history=(*h.history[-127:], Stage.READY.value),
                    )
                    await self.store.commit(value, self.store.revision)
                    self.current = value
                    return value
            except SchemaError as error:
                return await self.block(str(error))
            return self.current

    async def recover(self, inventory, now):
        """Explicit evidence-backed recovery; acknowledgement alone has no effect."""
        async with self.lock:
            h = self.current
            if (
                self.driver is None
                or h.stage != Stage.BLOCKED
                or h.resume_stage is None
            ):
                raise SchemaError("No recoverable contained transaction")
            state, _ = detect(inventory, now, self.expected)
            if state != Stage.DETECTED or inventory.fingerprint != h.legacy_fingerprint:
                raise SchemaError("Fresh exact legacy identity required")
            self._bridge(inventory, now)
            stage = (
                Stage.POST
                if h.resume_stage in (Stage.READY, Stage.DISABLED, Stage.ACTIVE)
                else h.resume_stage
            )
            return await self._save(stage, reason="", resume_stage=None)
