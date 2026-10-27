"""Reusable fake end-to-end runtime with actual durable repositories and adapters."""

from dataclasses import replace
from pathlib import Path
import tempfile, json
from custom_components.hpvc.storage import VersionedStore, LedgerRepository
from custom_components.hpvc.execution.models import (
    ExecutionLedger,
    HandoffRecord,
    OwnershipState,
)
from custom_components.hpvc.policy_runtime import PolicyRuntimeAdapter
from custom_components.hpvc.execution.dispatcher import Dispatcher, NativeObservation
from custom_components.hpvc.execution.executor import FakeExecutor, Completion
from custom_components.hpvc.execution.maintenance import Maintenance
from custom_components.hpvc.execution.verification import (
    EvidenceCandidate,
    EvidenceKind,
)
from custom_components.hpvc.hbc.state import Clock
from custom_components.hpvc.control.models import Observation, Quality
from policy_support import make_snapshot, make_views, NOW


class Harness:
    async def start(self):
        self.temp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temp.name) / "plant"
        self.ledger = LedgerRepository(
            VersionedStore(
                self.prefix.with_suffix(".json"), "execution", ExecutionLedger
            ),
            "plant",
        )
        await self.ledger.load()
        await self.ledger.update(
            lambda l: replace(
                l, ownership=HandoffRecord(state=OwnershipState.READY_DISABLED)
            )
        )
        self.runtime = PolicyRuntimeAdapter(self.prefix, "plant", self.ledger)
        await self.runtime.load(self.clock())
        self.fake = FakeExecutor()
        self.dispatch = Dispatcher(
            self.prefix, self.ledger, self.runtime, self.fake, owner_epoch="epoch"
        )
        await self.dispatch.load(self.clock())
        self.maintenance = Maintenance(self.dispatch)
        self.scenario = dict(
            name="cycle",
            grid=-600,
            pv=2500,
            market=-0.01,
            all_in=0.1,
            controllers=[self.controller()],
        )
        return self

    @staticmethod
    def controller(**kw):
        return dict(
            dict(
                full=3000,
                minimum=0,
                current=3000,
                unit="Watts",
                step=1,
                available=True,
                participating=True,
            ),
            **kw,
        )

    @staticmethod
    def clock(at=0, boot="boot"):
        return Clock(NOW + at, 100 + at, boot)

    async def proposal(self, at=0, entities=(), permission=False, **kw):
        s = {**self.scenario, **kw, "name": "cycle:" + str(at)}
        views = make_views(s)
        p = make_snapshot(s)
        signatures = {
            v.configuration.identity.uid: v.configuration_signature for v in views
        }
        p = replace(
            p,
            now=NOW + at,
            controllers=tuple(
                replace(
                    c,
                    configuration_signature=signatures.get(
                        c.uid, c.configuration_signature
                    ),
                )
                for c in p.controllers
            ),
        )
        p = replace(
            p,
            **{
                key: replace(
                    getattr(p, key), reported_at_utc=NOW + at, received_at_utc=NOW + at
                )
                for key in ("grid", "pv", "market", "all_in")
            },
        )
        q = await self.runtime.evaluate_readonly(
            p,
            entities,
            self.clock(at),
            views=views,
            permission=permission,
            settling=self.dispatch.settling_restriction(),
        )
        self.views = views
        self.policy = p
        return q

    async def submit(self, at=0, **kw):
        q = await self.proposal(at, **kw)
        await self.dispatch.submit(q, self.views, self.clock(at))
        return q

    def completion(self, request, at=1, result="success"):
        return Completion(request, result, self.clock(at))

    def candidate(self, request, at=2, **kw):
        op = self.dispatch._op(request.operation_id)
        values = dict(
            operation_id=op.operation_id,
            controller_uid=op.controller_uid,
            configuration_signature=op.configuration_signature,
            owner_epoch=op.owner_epoch,
            dispatch_id=op.dispatch_id,
            kind=EvidenceKind.HA,
            native_value=op.representable_controller_target_w,
            received_at_utc=NOW + at,
            reported_at_utc=NOW + at,
        )
        values.update(kw)
        return EvidenceCandidate(**values)

    async def verify(self, request, at=2, **kw):
        return await self.dispatch.finalize_evidence(
            request.operation_id, self.candidate(request, at, **kw), self.clock(at)
        )

    async def native(self, request, at=2, state=None):
        op = self.dispatch._op(request.operation_id)
        entity = json.loads(request.step.target_json)["entity_id"]
        observation = NativeObservation(
            op.operation_id,
            op.controller_uid,
            op.configuration_signature,
            op.owner_epoch,
            op.dispatch_id,
            entity,
            op.expected_native_value if state is None else state,
            NOW + at,
            NOW + at,
        )
        return await self.dispatch.observe_native(observation, self.clock(at))

    async def settle(self, request, at=3):
        op = self.dispatch._op(request.operation_id)
        reg = self.dispatch._reg(op.batch_id)
        pv_value = (
            min(reg.pv_before_w, op.representable_controller_target_w)
            if op.representable_controller_target_w < (reg.before_w or 0)
            else max(reg.pv_before_w, op.representable_controller_target_w)
        )
        for t in (at, at + 1):
            result = await self.dispatch.observe_pv(
                op.operation_id,
                Observation(
                    "pv",
                    pv_value,
                    Quality.VALID,
                    NOW + t,
                    NOW + t,
                ),
                self.clock(t),
            )
        return result

    async def stop(self):
        await self.dispatch.close()
        self.runtime.close()
        self.temp.cleanup()

    async def proposal_views(self, views, at=0, **kw):
        from custom_components.hpvc.control.decisions import PolicyController

        s = {**self.scenario, **kw, "name": "custom:" + str(at)}
        p = make_snapshot(s)
        controllers = tuple(
            PolicyController(
                v.configuration.identity.uid,
                v.observation.limit.value
                if v.observation.limit.value is not None
                else v.assumed_limit_w,
                v.operating_range.full_w,
                v.operating_range.minimum_w,
                v.available,
                True,
                v.valid,
                v.independently_verifiable,
                v.capabilities.step or 0,
                v.configuration_signature,
                not v.supports_verification,
            )
            for v in views
        )
        p = replace(
            p,
            now=NOW + at,
            controllers=controllers,
            **{
                key: replace(
                    getattr(p, key), reported_at_utc=NOW + at, received_at_utc=NOW + at
                )
                for key in ("grid", "pv", "market", "all_in")
            },
        )
        q = await self.runtime.evaluate_readonly(
            p,
            (),
            self.clock(at),
            views=views,
            settling=self.dispatch.settling_restriction(),
        )
        self.views = views
        self.policy = p
        return q
