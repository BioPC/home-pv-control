"""Immutable executor protocol and the only concrete implementation: a fake."""

from dataclasses import dataclass
from typing import Protocol
from ..codec import Record, SchemaError
from ..hbc.state import Clock
from .models import CommandStep, Lane


@dataclass(frozen=True)
class ExecutionRequest(Record):
    operation_id: str
    dispatch_id: str
    owner_epoch: str
    controller_uid: str
    configuration_signature: str
    lane: Lane
    step: CommandStep
    issued: Clock


@dataclass(frozen=True)
class IssueReceipt(Record):
    request: ExecutionRequest
    simulated: bool = True
    issued: Clock | None = None


@dataclass(frozen=True)
class Completion(Record):
    request: ExecutionRequest
    result: str
    observed: Clock
    exception_type: str = ""
    exception_message: str = ""

    def __post_init__(self):
        if self.result not in ("success", "transport_failure", "outcome_unknown"):
            raise SchemaError("Invalid fake completion")


class Executor(Protocol):
    async def issue(self, request: ExecutionRequest) -> IssueReceipt: ...


class FakeExecutor:
    """No service/network handles. Tests explicitly release acceptance/callbacks.

    Duplicate/stale/old-epoch callbacks are represented by immutable Completion DATA.
    A missing completion remains in flight until explicit recovery, never by age.
    """

    def __init__(self):
        self.requests = []
        self.outbox = []
        self.acceptance_gate = None
        self.raise_on_issue = None
        self.issue_hook = None

    async def issue(self, request):
        self.requests.append(request)
        if self.issue_hook is not None:
            await self.issue_hook(request)
        if self.acceptance_gate is not None:
            await self.acceptance_gate.wait()
        if self.raise_on_issue is not None:
            raise self.raise_on_issue
        return IssueReceipt(request)

    def complete(self, request, result="success", clock=None):
        completion = Completion(request, result, clock or request.issued)
        self.outbox.append(completion)
        return completion

    def confirm_quiescent(self, request, clock, result="completed"):
        if request not in self.requests:
            raise SchemaError("Fake did not issue this request")
        return QuiescenceReceipt(request, clock, result)

    def take_completions(self):
        result = tuple(self.outbox)
        self.outbox.clear()
        return result


@dataclass(frozen=True)
class QuiescenceReceipt(Record):
    request: ExecutionRequest
    observed: Clock
    transport_result: str

    def __post_init__(self):
        if self.transport_result not in ("completed", "failed"):
            raise SchemaError("Quiescence needs an explicit terminal transport result")
