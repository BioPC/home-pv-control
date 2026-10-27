"""Dedicated test injection. Never imported by native runtime code."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from dispatch_support import Harness
from custom_components.hpvc.execution.dispatcher import Dispatcher
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

ALIASES = {
    action: (TEST_DOMAIN, action.replace(".", "_"))
    for action in (
        "number.set_value",
        "script.apply_limit",
        "switch.turn_on",
        "switch.turn_off",
        "select.select_option",
        "input_select.select_option",
    )
}


def test_admission(epoch, aliases=None):
    return _TransportTestAdmission(
        _key=_TEST_ADMISSION_KEY, owner_epoch=epoch, aliases=aliases or ALIASES
    )


class TestRegistry:
    def __init__(self):
        self.calls = []
        self.handler = None
        self.found = True

    def has_service(self, domain, service):
        return self.found and domain == TEST_DOMAIN

    async def async_call(self, domain, service, **kwargs):
        assert domain == TEST_DOMAIN, "No actuator domains in transport tests"
        self.calls.append((domain, service, kwargs))
        if self.handler:
            await self.handler(domain, service, kwargs)


class TransportHarness(Harness):
    async def start(self):
        await super().start()
        await self.dispatch.close()
        self.at = 0
        self.binding_epoch = "haepoch"
        self.live_views = None
        self.native_bindings = ()
        self.permission = True
        self.enabled = True
        self.registry = TestRegistry()
        self.states = {}
        self.hass = SimpleNamespace(
            services=self.registry,
            states=SimpleNamespace(get=lambda entity: self.states.get(entity)),
        )
        self.permit = test_admission("haepoch")
        self.executor = HaServiceExecutor(
            self.hass,
            live_bindings=self.live,
            clock=lambda: self.clock(self.at),
            _test_admission=self.permit,
        )
        self.dispatch = Dispatcher(
            self.prefix, self.ledger, self.runtime, self.executor, owner_epoch="haepoch"
        )
        await self.dispatch.load(self.clock())
        return self

    def live(self):
        return InvocationBindings(
            "plant",
            self.binding_epoch,
            self.clock(self.at),
            self.live_views
            if self.live_views is not None
            else getattr(self, "views", ()),
            self.native_bindings,
            self.permission,
            True,
            self.enabled,
        )

    async def submit(self, at=0, **kw):
        self.at = at
        q = await super().submit(at, **kw)
        self.populate_states()
        return q

    def populate_states(self):
        for view in self.views:
            c = view.configuration
            for entity in (c.limit_number, c.readback_entity):
                if entity:
                    self.states.setdefault(
                        entity, SimpleNamespace(state="3000", attributes={})
                    )

    async def finish_transport(self):
        tasks = [
            a["task"] for a in self.executor._attempts.values() if a["task"] is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return await self.dispatch.drain_completions()

    async def stop(self):
        await self.dispatch.close()
        await self.executor.close()
        # Every unit test releases issued handlers before cleanup.
        tasks = [
            a["task"] for a in self.executor._attempts.values() if a["task"] is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.runtime.close()
        self.temp.cleanup()
