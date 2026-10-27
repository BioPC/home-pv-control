"""Explicit real-HA test injection. No runtime module imports this helper."""

import asyncio, time, json, uuid
from dataclasses import replace
from test_policy_acceptance import start, snapshot
from custom_components.hpvc.execution.dispatcher import Dispatcher, NativeObservation
from custom_components.hpvc.execution.ha_executor import (
    HaServiceExecutor,
    _TransportTestAdmission,
    _TEST_ADMISSION_KEY,
    TEST_DOMAIN,
)
from custom_components.hpvc.execution.service_plan import (
    InvocationBindings,
    NativeBinding,
)
from custom_components.hpvc.execution.models import HandoffRecord, OwnershipState
from custom_components.hpvc.hbc.state import Clock
from custom_components.hpvc.policy_runtime import capture_entities
from custom_components.hpvc.control.decisions import PolicyController
from custom_components.hpvc.inverter.base import EntityRecord
from custom_components.hpvc.execution.verification import (
    EvidenceCandidate,
    EvidenceKind,
)

ACTIONS = (
    "number.set_value",
    "script.apply_limit",
    "switch.turn_on",
    "switch.turn_off",
    "select.select_option",
    "input_select.select_option",
)


def entity(hass, name):
    s = hass.states.get(name)
    return (
        EntityRecord(
            name,
            str(s.state),
            s.last_updated.timestamp(),
            json.dumps(dict(s.attributes)),
        )
        if s
        else None
    )


class HaHarness:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.runtime = entry.runtime_data
        self.epoch = uuid.uuid4().hex
        self.binding_epoch = self.epoch
        self.elapsed = 0
        self.custom_views = None
        self.native_ids = {}
        self.enabled = True
        self.permission = True
        self.calls = []
        self.handlers = {}
        self.cap = None
        self.executor = None
        self.dispatch = None
        self.evaluation = 0

    def clock(self):
        return Clock(
            time.time(),
            time.monotonic() + self.elapsed,
            self.runtime.policy_runtime.accepted.hbc.boot_id,
        )

    def views(self):
        if self.custom_views is not None:
            return tuple(self.custom_views())
        registry, devices = self.runtime.registry_reader()
        fleet = self.runtime.manager.refresh(
            self.runtime.configuration,
            tuple(self.runtime.states_snapshot_reader(True)),
            registry,
            devices,
            now=time.time(),
        )
        return tuple(row.view for row in fleet.effective)

    def live(self):
        native = tuple(
            NativeBinding(
                name,
                self.native_ids.get(name, name + ":test-binding"),
                self.hass.states.get(name) is not None
                and self.hass.states.get(name).state not in ("unknown", "unavailable"),
            )
            for name in (
                "input_select.house_battery_strategy",
                "input_select.house_battery_strategy_charge_goal",
            )
        )
        return InvocationBindings(
            self.runtime.configuration.plant_uid,
            self.binding_epoch,
            self.clock(),
            self.views(),
            native,
            self.permission,
            True,
            self.enabled,
        )

    async def initialize(self):
        await self.runtime.ledger.update(
            lambda l: replace(
                l, ownership=HandoffRecord(state=OwnershipState.READY_DISABLED)
            )
        )
        aliases = {a: (TEST_DOMAIN, a.replace(".", "_")) for a in ACTIONS}
        self.cap = _TransportTestAdmission(
            _key=_TEST_ADMISSION_KEY, owner_epoch=self.epoch, aliases=aliases
        )
        self.executor = HaServiceExecutor(
            self.hass,
            live_bindings=self.live,
            clock=self.clock,
            _test_admission=self.cap,
        )
        prefix = self.runtime.policy_runtime.store.path.with_name(
            self.runtime.policy_runtime.store.path.name.removesuffix("_policy.json")
        )
        self.dispatch = Dispatcher(
            prefix,
            self.runtime.ledger,
            self.runtime.policy_runtime,
            self.executor,
            owner_epoch=self.epoch,
        )
        await self.dispatch.load(self.clock())
        self.runtime.owner.add_cleanup(self.executor.revoke_admission)
        self.runtime.owner.add_async_cleanup(self.executor.close)
        self.runtime.owner.add_async_cleanup(self.dispatch.close)
        for action in ACTIONS:
            name = action.replace(".", "_")

            async def handler(call, logical=action):
                assert call.domain == TEST_DOMAIN
                self.calls.append(
                    (
                        logical,
                        dict(call.data),
                        self.runtime.ledger.current.operations[-1].state,
                    )
                )
                custom = self.handlers.get(logical)
                if custom:
                    await custom(call)

            self.hass.services.async_register(TEST_DOMAIN, name, handler)
        return self

    async def proposal(
        self, *, all_in=0.1, permission=False, enabled=True, register=False
    ):
        self.evaluation += 1
        self.enabled = enabled
        self.permission = permission
        now = self.clock()
        views = self.views()
        p = snapshot(self.runtime)
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
            evaluation_id="ha-transport:" + str(self.evaluation),
            now=now.utc,
            controllers=controllers,
            enabled=enabled,
            all_in=replace(
                p.all_in, value=all_in, reported_at_utc=now.utc, received_at_utc=now.utc
            ),
        )
        q = await self.runtime.policy_runtime.evaluate_readonly(
            p,
            capture_entities(self.runtime.state_reader),
            now,
            views=views,
            permission=permission,
            settling=self.dispatch.settling_restriction(),
        )
        if register:
            await self.dispatch.submit(q, views, self.clock())
        return q

    async def finish(self):
        tasks = [
            a["task"] for a in self.executor._attempts.values() if a["task"] is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return await self.dispatch.drain_completions()

    async def native(self, request):
        op = self.dispatch._op(request.operation_id)
        reg = self.dispatch._reg(op.batch_id)
        entity_id = json.loads(reg.batch.steps[op.step_index].target_json)["entity_id"]
        self.hass.states.async_set(
            entity_id,
            op.expected_native_value,
            self.hass.states.get(entity_id).attributes,
        )
        raw = self.hass.states.get(entity_id)
        now = self.clock()
        return await self.dispatch.observe_native(
            NativeObservation(
                op.operation_id,
                op.controller_uid,
                op.configuration_signature,
                op.owner_epoch,
                op.dispatch_id,
                entity_id,
                raw.state,
                raw.last_updated.timestamp(),
                now.utc,
            ),
            now,
        )

    def evidence(self, request, **kw):
        op = self.dispatch._op(request.operation_id)
        now = self.clock()
        args = dict(
            operation_id=op.operation_id,
            controller_uid=op.controller_uid,
            configuration_signature=op.configuration_signature,
            owner_epoch=op.owner_epoch,
            dispatch_id=op.dispatch_id,
            kind=EvidenceKind.HA,
            native_value=op.representable_controller_target_w,
            received_at_utc=now.utc,
            reported_at_utc=now.utc,
        )
        args.update(kw)
        return EvidenceCandidate(**args)

    async def unload(self):
        if not self.runtime.owner.closed:
            assert await self.hass.config_entries.async_unload(self.entry.entry_id)


async def start_transport(hass):
    return await HaHarness(hass, await start(hass)).initialize()
