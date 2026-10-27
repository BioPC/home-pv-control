"""Real HA owns the explicitly injected fake dispatcher; no live entity is written."""

import asyncio, time
from dataclasses import replace
from unittest.mock import AsyncMock, patch
import pytest
from test_policy_acceptance import start, snapshot
from custom_components.hpvc.execution.dispatcher import Dispatcher
from custom_components.hpvc.execution.executor import FakeExecutor, Completion
from custom_components.hpvc.execution.models import (
    HandoffRecord,
    OwnershipState,
    OperationState,
    Lane,
)
from custom_components.hpvc.execution.verification import (
    EvidenceCandidate,
    EvidenceKind,
    VerificationOutcome,
)
from custom_components.hpvc.hbc.state import Clock

pytestmark = pytest.mark.asyncio


async def prepare(hass):
    entry = await start(hass)
    runtime = entry.runtime_data
    adapter = runtime.policy_runtime
    await runtime.ledger.update(
        lambda l: replace(
            l, ownership=HandoffRecord(state=OwnershipState.READY_DISABLED)
        )
    )
    prefix = adapter.store.path.with_name(
        adapter.store.path.name.removesuffix("_policy.json")
    )
    fake = FakeExecutor()
    dispatcher = Dispatcher(prefix, runtime.ledger, adapter, fake)
    c = Clock(time.time(), time.monotonic(), adapter.accepted.hbc.boot_id)
    await dispatcher.load(c)
    runtime.owner.add_async_cleanup(dispatcher.close)
    p = replace(snapshot(runtime), now=c.utc)
    views = tuple(r.view for r in runtime.manager.current.effective)
    q = await adapter.evaluate_readonly(p, (), c, views=views)
    await dispatcher.submit(q, views, c)
    return entry, dispatcher, fake, c


async def test_real_ha_fake_dispatch_accept_complete_verify_without_actuator_calls(
    hass,
):
    with patch.object(
        type(hass.services),
        "async_call",
        new_callable=AsyncMock,
        side_effect=AssertionError("No dev.5 real services"),
    ) as calls:
        entry, d, fake, c = await prepare(hass)
        req = await d.pump_lane(Lane.INVERTER, c)
        assert req is not None
        assert d.runtime.event_recorder.current.last_inverter
        await d.receive_completion(Completion(req, "success", c.shift(1)))
        op = d._op(req.operation_id)
        candidate = EvidenceCandidate(
            op.operation_id,
            op.controller_uid,
            op.configuration_signature,
            op.owner_epoch,
            op.dispatch_id,
            EvidenceKind.HA,
            op.representable_controller_target_w,
            c.utc + 2,
            c.utc + 2,
        )
        result = await d.finalize_evidence(op.operation_id, candidate, c.shift(2))
        assert result.outcome == VerificationOutcome.CONFIRMED
        assert hass.states.get("number.external_limit").state == "3000"
        assert (
            hass.states.get("binary_sensor.hpvc_physical_writes_authorized").state
            == "off"
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert d.closed
        calls.assert_not_called()


async def test_real_ha_reload_reconciles_inflight_and_rejects_prior_callback(hass):
    entry, d, fake, c = await prepare(hass)
    req = await d.pump_lane(Lane.INVERTER, c)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert d.closed
    assert not await d.receive_completion(Completion(req, "success", c.shift(2)))
    new = entry.runtime_data
    op = next(
        o for o in new.ledger.current.operations if o.operation_id == req.operation_id
    )
    assert op.state == OperationState.UNKNOWN
    assert new.ledger.current.restore_obligations
    assert hass.states.get("number.external_limit").state == "3000"
    assert not new.physical_writes_authorized
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_real_ha_unload_drains_delayed_fake_invocation_and_owned_tasks(hass):
    entry, d, fake, c = await prepare(hass)
    owner = entry.runtime_data.owner
    fake.acceptance_gate = asyncio.Event()
    task = owner.create_task(d.pump_lane(Lane.INVERTER, c), "hpvc-test-fake-dispatch")
    for _ in range(100):
        if fake.requests:
            break
        await asyncio.sleep(0.001)
    assert fake.requests
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert d.closed and task.done() and not owner.tasks
    assert d.ledger.current.operations[0].state == OperationState.UNKNOWN
    assert hass.states.get("number.external_limit").state == "3000"
