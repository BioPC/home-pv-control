"""Simulated safe-disable/maintenance transactions and durable full-output barriers."""

from dataclasses import dataclass, replace
import uuid
from ..codec import Record, SchemaError
from ..inverter.base import fingerprint
from .models import (
    MaintenanceRecord,
    MaintenanceState as M,
    RestoreObligation,
    ObligationState as O,
    VerificationEvidence,
    VerificationStatus as V,
    OperationState as S,
    Lane,
    TransportStatus as T,
)
from .settling import SettlingOutcome


@dataclass(frozen=True)
class FullOutputObservation(Record):
    controller_uid: str
    configuration_signature: str
    configuration_reference: str
    owner_epoch: str
    value_w: float
    source: str
    reported_at_utc: float
    received_at_utc: float


@dataclass(frozen=True)
class MaintenanceDecision(Record):
    state: M
    authorized: bool
    reasons: tuple[str, ...]
    desired_enable_intent: bool = False

    @property
    def physical_writes_authorized(self):
        return False


class Maintenance:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.ledger = dispatcher.ledger

    async def request(self, action, saved_enable_intent, views, clock):
        self.dispatcher._healthy()
        if action not in ("disable", "update", "uninstall", "remove"):
            raise SchemaError("Unknown maintenance request")
        old = self.ledger.current.maintenance
        if old.state not in (M.IDLE, M.COMPLETE, M.CANCELLED):
            raise SchemaError("An existing maintenance owner must reconcile first")
        token = uuid.uuid4().hex
        tx = "maintenance:" + token
        captured = {
            (v.configuration.identity.uid, v.configuration_signature): (
                "config:" + v.configuration_signature,
                v.operating_range.full_w,
            )
            for v in views
        }
        # Historical identities remain obligations even with zero rediscovered controllers.
        for reg in self.dispatcher.current.registrations:
            if reg.lane == Lane.INVERTER and any(
                o.batch_id == reg.batch.batch_id
                and o.state not in (S.PREPARED, S.SUPERSEDED)
                for o in self.ledger.current.operations
            ):
                captured.setdefault(
                    (reg.batch.controller_uid, reg.batch.configuration_signature),
                    (reg.configuration_reference, reg.full_w),
                )
        obligations = list(self.ledger.current.restore_obligations)
        for (uid, sig), (ref, full) in captured.items():
            if any(
                o.controller_uid == uid
                and o.configuration_signature == sig
                and o.state != O.VERIFIED
                for o in obligations
            ):
                continue
            operations = tuple(
                o.operation_id
                for o in self.ledger.current.operations
                if o.controller_uid == uid
                and o.configuration_signature == sig
                and o.state not in (S.PREPARED, S.SUPERSEDED)
            )
            obligations.append(
                RestoreObligation(
                    tx + ":" + fingerprint([uid, sig])[:24],
                    uid,
                    sig,
                    ref,
                    "safe_disable",
                    full,
                    operation_ids=operations,
                    established_at_utc=clock.utc,
                    owner_epoch=self.dispatcher.owner_epoch,
                )
            )
        m = MaintenanceRecord(
            tx,
            token,
            M.REQUESTED,
            action,
            bool(saved_enable_intent),
            tuple(o.obligation_id for o in obligations if o.state != O.VERIFIED),
            requested_at_utc=clock.utc,
            owner_epoch=self.dispatcher.owner_epoch,
            requested_monotonic=clock.monotonic,
            boot_id=clock.boot_id,
        )
        await self.ledger.update(
            lambda l: replace(l, maintenance=m, restore_obligations=tuple(obligations))
        )
        # Unsent normal-control work cannot run after a safe-disable transaction.
        for op in tuple(self.ledger.current.operations):
            if op.state == S.PREPARED and op.lane == Lane.INVERTER:
                await self.ledger.transition_operation(
                    op.operation_id, S.SUPERSEDED, reason="maintenance_safe_disable"
                )
        return MaintenanceDecision(
            M.REQUESTED, False, ("post_disable_evaluation_required",)
        )

    async def observe_disabled(self, proposal, clock, owner_token):
        m = self._owner(owner_token)
        if (
            proposal != self.dispatcher.runtime.last_proposal
            or proposal.enabled_intent
            or proposal.clock.utc < m.requested_at_utc
            or proposal.clock.boot_id != m.boot_id
            or proposal.clock.monotonic < m.requested_monotonic
        ):
            raise SchemaError("Fresh accepted post-disable evaluation required")
        if m.state == M.BLOCKED:
            raise SchemaError("Blocked maintenance cannot self-authorize")
        await self.ledger.update(
            lambda l: replace(
                l,
                maintenance=replace(
                    l.maintenance,
                    state=M.RESTORING,
                    post_disable_evaluation_id=proposal.policy.intent.evaluation_id,
                ),
            )
        )

    def _owner(self, token):
        m = self.ledger.current.maintenance
        if (
            not token
            or m.owner_token != token
            or m.owner_epoch != self.dispatcher.owner_epoch
        ):
            raise SchemaError("Maintenance transaction ownership mismatch")
        return m

    def _conflicting(self, obligation, reported_at):
        return any(
            o.controller_uid == obligation.controller_uid
            and (
                (
                    o.state in (S.ARMED, S.IN_FLIGHT)
                    or o.state in (S.UNKNOWN, S.RECOVERY_REQUIRED)
                    and o.transport not in (T.COMPLETED, T.FAILED)
                )
                or o.dispatch_started_at_utc is not None
                and o.dispatch_started_at_utc > reported_at
            )
            for o in self.ledger.current.operations
        )

    async def already_full(self, observation, clock, owner_token, *, view=None):
        m = self._owner(owner_token)
        if not m.post_disable_evaluation_id:
            return False
        if (
            view is None
            or not view.available
            or not view.independently_verifiable
            or view.current_source.value != "readback"
            or view.configuration.identity.uid != observation.controller_uid
            or view.configuration_signature != observation.configuration_signature
            or view.observation.limit.value != observation.value_w
            or view.observation.limit.reported_at_utc != observation.reported_at_utc
            or view.observation.limit.received_at_utc != observation.received_at_utc
        ):
            return False
        if (
            observation.owner_epoch != self.dispatcher.owner_epoch
            or observation.source
            not in ("ha_readback", "enphase_readback", "opendtu_api")
        ):
            return False
        if not (
            0 <= clock.utc - observation.reported_at_utc <= 180
            and observation.reported_at_utc
            <= observation.received_at_utc
            <= clock.utc + 60
        ):
            return False
        matches = [
            o
            for o in self.ledger.current.restore_obligations
            if o.state != O.VERIFIED
            and (o.controller_uid, o.configuration_signature, o.configuration_reference)
            == (
                observation.controller_uid,
                observation.configuration_signature,
                observation.configuration_reference,
            )
        ]
        matches = [
            o
            for o in matches
            if o.required_target_w is not None
            and abs(o.required_target_w - observation.value_w) <= 1e-7
            and o.established_at_utc is not None
            and observation.reported_at_utc
            >= max(o.established_at_utc, m.requested_at_utc)
            and not self._conflicting(o, observation.reported_at_utc)
        ]
        if not matches:
            return False
        # OpenDTU and Enphase require their complete structured verification verdict;
        # an unstructured full-W observation cannot prove their readiness/status.
        if observation.source != "ha_readback":
            return False
        proof = VerificationEvidence(
            "already-full:" + uuid.uuid4().hex,
            observation.controller_uid,
            observation.configuration_signature,
            None,
            observation.source,
            V.VERIFIED,
            observation.value_w,
            observation.reported_at_utc,
            received_at_utc=observation.received_at_utc,
            provenance="owner=" + observation.owner_epoch,
        )
        await self.ledger.add_evidence(proof)
        ids = {o.obligation_id for o in matches}
        await self.ledger.update(
            lambda l: replace(
                l,
                restore_obligations=tuple(
                    replace(o, state=O.VERIFIED, evidence_ids=(proof.evidence_id,))
                    if o.obligation_id in ids
                    else o
                    for o in l.restore_obligations
                ),
            )
        )
        return True

    async def resolve_verified_restores(self, clock, owner_token):
        self._owner(owner_token)
        resolved = {}
        for obligation in self.ledger.current.restore_obligations:
            if obligation.state == O.VERIFIED:
                continue
            for op in reversed(self.ledger.current.operations):
                if (
                    op.controller_uid != obligation.controller_uid
                    or op.configuration_signature != obligation.configuration_signature
                    or op.configuration_reference != obligation.configuration_reference
                    or op.state not in (S.VERIFIED, S.RETIRED)
                    or op.representable_controller_target_w
                    != obligation.required_target_w
                ):
                    continue
                proof = next(
                    (
                        e
                        for e in self.ledger.current.evidence
                        if e.evidence_id in op.evidence_ids
                    ),
                    None,
                )
                if (
                    proof
                    and proof.received_at_utc is not None
                    and not self._conflicting(obligation, proof.received_at_utc)
                ):
                    resolved[obligation.obligation_id] = proof.evidence_id
                    break
        if resolved:
            await self.ledger.update(
                lambda l: replace(
                    l,
                    restore_obligations=tuple(
                        replace(
                            o,
                            state=O.VERIFIED,
                            evidence_ids=(resolved[o.obligation_id],),
                        )
                        if o.obligation_id in resolved
                        else o
                        for o in l.restore_obligations
                    ),
                )
            )

    async def night_exception(self, owner_token):
        self._owner(owner_token)
        night = self.ledger.current.night_restore
        if not night.active or not night.full_output_proof_reference:
            return False
        proof = next(
            (
                e
                for e in self.ledger.current.evidence
                if e.evidence_id == night.full_output_proof_reference
            ),
            None,
        )
        if (
            proof is None
            or proof.kind not in ("ha_readback", "enphase_readback", "opendtu_api")
            or proof.verdict != V.VERIFIED
            or proof.received_at_utc is None
        ):
            return False
        matches = [
            o
            for o in self.ledger.current.restore_obligations
            if o.state != O.VERIFIED
            and (o.controller_uid, o.configuration_signature)
            == (proof.controller_uid, proof.configuration_signature)
            and o.required_target_w == proof.observed_value_w
            and not self._conflicting(o, proof.received_at_utc)
        ]
        if not matches:
            return False
        ids = {o.obligation_id for o in matches}
        await self.ledger.update(
            lambda l: replace(
                l,
                restore_obligations=tuple(
                    replace(o, state=O.VERIFIED, evidence_ids=(proof.evidence_id,))
                    if o.obligation_id in ids
                    else o
                    for o in l.restore_obligations
                ),
            )
        )
        return True

    async def evaluate(self, clock, owner_token):
        m = self._owner(owner_token)
        reasons = []
        if m.state == M.BLOCKED:
            return MaintenanceDecision(
                M.BLOCKED, False, ("blocked_requires_explicit_recovery",)
            )
        if (
            clock.boot_id != m.boot_id
            or m.requested_monotonic is None
            or clock.monotonic < m.requested_monotonic
        ):
            reasons.append("observation_continuity_lost")
        elif clock.monotonic - m.requested_monotonic >= 180:
            reasons.append("maintenance_timeout_180s")
        if reasons:
            await self.ledger.update(
                lambda l: replace(
                    l,
                    maintenance=replace(
                        l.maintenance, state=M.BLOCKED, authorization_revision=None
                    ),
                )
            )
            return MaintenanceDecision(M.BLOCKED, False, tuple(reasons))
        if not m.post_disable_evaluation_id:
            reasons.append("post_disable_evaluation_required")
        if (
            self.dispatcher.runtime.last_proposal is None
            or self.dispatcher.runtime.last_proposal.enabled_intent
        ):
            reasons.append("enable_intent_not_disabled")
        if any(not self._reconciled(o) for o in self.ledger.current.operations):
            reasons.append("execution_not_drained_or_verified")
        if any(o.state != O.VERIFIED for o in self.ledger.current.restore_obligations):
            reasons.append("restore_obligations_unresolved")
        if (
            self.dispatcher.runtime.accepted.hbc.override.phase != "inactive"
            or self.ledger.current.hbc_override.phase.value != "inactive"
        ):
            reasons.append("HBC_restore_unconfirmed")
        if any(
            self.dispatcher.settling_results.get(s.operation_id) is None
            or self.dispatcher.settling_results[s.operation_id].outcome
            != SettlingOutcome.APPLIED
            for s in self.dispatcher.current.settling
            if s.operation_id not in self.dispatcher.current.settled_operation_ids
            and s.operation_id not in self.dispatcher.current.superseded_settling_ids
            and not self._night_covers(s.operation_id)
        ):
            reasons.append("settling_not_confirmed")
        state = M.VERIFYING if reasons else M.AUTHORIZED
        await self.ledger.update(
            lambda l: replace(
                l,
                maintenance=replace(
                    l.maintenance,
                    state=state,
                    authorization_revision=l.revision + 1 if not reasons else None,
                ),
            )
        )
        return MaintenanceDecision(state, not reasons, tuple(reasons))

    def _reconciled(self, op):
        if op.state in (S.SUPERSEDED, S.RETIRED, S.VERIFIED):
            return True
        if op.transport not in (T.COMPLETED, T.FAILED):
            return False
        bound = [
            o
            for o in self.ledger.current.restore_obligations
            if op.operation_id in o.operation_ids
        ]
        return bool(bound) and all(o.state == O.VERIFIED for o in bound)

    def authorization_valid(self, owner_token, clock):
        m = self._owner(owner_token)
        return (
            m.state == M.AUTHORIZED
            and m.boot_id == clock.boot_id
            and m.requested_monotonic is not None
            and 0 <= clock.monotonic - m.requested_monotonic < 180
            and m.authorization_revision == self.ledger.current.revision
            and self.dispatcher.runtime.last_proposal is not None
            and not self.dispatcher.runtime.last_proposal.enabled_intent
        )

    def _night_covers(self, op_id):
        l = self.ledger.current
        if (
            not l.night_restore.active
            or not l.night_restore.full_output_proof_reference
        ):
            return False
        proof = next(
            (
                e
                for e in l.evidence
                if e.evidence_id == l.night_restore.full_output_proof_reference
            ),
            None,
        )
        op = next((o for o in l.operations if o.operation_id == op_id), None)
        if (
            not op
            or not proof
            or proof.kind not in ("ha_readback", "enphase_readback", "opendtu_api")
            or proof.verdict != V.VERIFIED
        ):
            return False
        return any(
            o.controller_uid == op.controller_uid
            and o.configuration_signature == op.configuration_signature
            and o.required_target_w
            == op.representable_controller_target_w
            == proof.observed_value_w
            and (proof.controller_uid, proof.configuration_signature)
            == (op.controller_uid, op.configuration_signature)
            and proof.received_at_utc is not None
            and not self._conflicting(o, proof.received_at_utc)
            for o in l.restore_obligations
        )

    async def recover_request(self, old_owner_token, proposal, clock):
        """Explicit new request after BLOCKED; never resume an old authorization.

        It retains every obligation and saved intent. A caller must explicitly
        request recovery with the existing transaction token and a fresh accepted
        disabled observation. Transport uncertainty still needs separate proof.
        """
        self.dispatcher._healthy()
        old = self.ledger.current.maintenance
        if (
            old.state != M.BLOCKED
            or old.owner_token != old_owner_token
            or not old_owner_token
        ):
            raise SchemaError("Only the blocked transaction token can request recovery")
        age = clock.age(proposal.clock)
        if (
            proposal != self.dispatcher.runtime.last_proposal
            or proposal.enabled_intent
            or age is None
            or age > 10
        ):
            raise SchemaError("Recovery needs a fresh accepted disabled observation")
        token = uuid.uuid4().hex
        new = MaintenanceRecord(
            "maintenance:" + token,
            token,
            M.RESTORING,
            old.requested_action,
            old.saved_enable_intent,
            tuple(
                o.obligation_id
                for o in self.ledger.current.restore_obligations
                if o.state != O.VERIFIED
            ),
            requested_at_utc=clock.utc,
            post_disable_evaluation_id=proposal.policy.intent.evaluation_id,
            owner_epoch=self.dispatcher.owner_epoch,
            requested_monotonic=clock.monotonic,
            boot_id=clock.boot_id,
        )
        await self.ledger.update(lambda l: replace(l, maintenance=new))
        await self.dispatcher._audit(
            old.transaction_id or "", "explicit_maintenance_recovery_request", clock
        )
        return token
