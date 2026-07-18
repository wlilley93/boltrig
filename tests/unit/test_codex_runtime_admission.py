from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellSupervisor,
    InitializedCodexCell,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    CodexPhaseAdmission,
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
    SupervisedCodexPhaseCellProvider,
)

from .codex_runtime_fakes import (
    FakeCodexCell,
    admission,
    assignment,
    fake_cell,
    preflight_receipt,
)


class _Source:
    def __init__(self, value: CodexPhaseAdmission) -> None:
        self.value = value
        self.calls = 0

    async def admit(self, _assignment: object) -> CodexPhaseAdmission:
        self.calls += 1
        return self.value


class _Supervisor:
    def __init__(self, cell: FakeCodexCell) -> None:
        self.cell = cell
        self.calls = 0

    async def start(self, _layout: object) -> InitializedCodexCell:
        self.calls += 1
        return self.cell.initialized


class _Probe:
    def __init__(self, receipt: QuarantinedCodexPreflightReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    async def probe(
        self, _client: object, _plan: object
    ) -> QuarantinedCodexPreflightReceipt:
        self.calls += 1
        return self.receipt


class _BlockingProbe(_Probe):
    def __init__(self, receipt: QuarantinedCodexPreflightReceipt) -> None:
        super().__init__(receipt)
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def probe(
        self, _client: object, _plan: object
    ) -> QuarantinedCodexPreflightReceipt:
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        return self.receipt


class _FailingProbe(_Probe):
    async def probe(
        self, _client: object, _plan: object
    ) -> QuarantinedCodexPreflightReceipt:
        self.calls += 1
        raise CodexRuntimeAdmissionError("discovery mismatch")


async def test_supervised_provider_resolves_once_and_starts_exactly_one_cell() -> None:
    value = admission()
    source = _Source(value)
    cell = fake_cell(value)
    supervisor = _Supervisor(cell)
    probe = _Probe(preflight_receipt(value))
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, supervisor),
        probe,
    )

    leased = await provider.acquire(value.assignment)

    assert leased.admission == value
    assert source.calls == supervisor.calls == probe.calls == 1
    assert not cell.closed


async def test_supervised_provider_rejects_cross_assignment_before_starting_cell() -> None:
    requested = assignment("requested")
    source = _Source(admission(assignment("wrong")))
    cell = fake_cell(source.value)
    supervisor = _Supervisor(cell)
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, supervisor),
        _Probe(preflight_receipt(source.value)),
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="another assignment"):
        await provider.acquire(requested)

    assert source.calls == 1 and supervisor.calls == 0


async def test_supervised_provider_reaps_initialized_cell_on_metadata_mismatch() -> None:
    value = admission()
    source = _Source(value)
    wrong = admission(assignment("wrong"))
    cell = fake_cell(value, metadata_admission=wrong)
    supervisor = _Supervisor(cell)
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, supervisor),
        _Probe(preflight_receipt(value)),
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="initialized cell"):
        await provider.acquire(value.assignment)

    assert cell.closed and cell.close_calls == 1


async def test_supervised_provider_reaps_cell_when_preflight_is_cancelled() -> None:
    value = admission()
    source = _Source(value)
    cell = fake_cell(value)
    supervisor = _Supervisor(cell)
    probe = _BlockingProbe(preflight_receipt(value))
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, supervisor),
        probe,
    )
    acquiring = asyncio.create_task(provider.acquire(value.assignment))
    await probe.started.wait()
    assert cell.client.calls == []

    acquiring.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquiring

    assert cell.closed and cell.close_calls == 1


async def test_supervised_provider_reaps_cell_on_preflight_mismatch() -> None:
    value = admission()
    source = _Source(value)
    cell = fake_cell(value)
    probe = _FailingProbe(preflight_receipt(value))
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, _Supervisor(cell)),
        probe,
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="discovery mismatch"):
        await provider.acquire(value.assignment)

    assert cell.closed and cell.close_calls == 1


def test_admission_rejects_instruction_or_provisioned_policy_drift() -> None:
    value = admission()

    with pytest.raises(CodexRuntimeAdmissionError, match="instructions"):
        replace(value, developer_instructions="Different instructions")
    with pytest.raises(CodexRuntimeAdmissionError, match="provisioned policy"):
        replace(value, provisioned_policy_digest="sha256:" + "0" * 64)


@pytest.mark.parametrize("tool", ["filesystem.read", "shell.exec", "mcp.opbox"])
def test_quarantined_admission_rejects_every_unattested_runtime_tool(tool: str) -> None:
    with pytest.raises(CodexRuntimeAdmissionError, match="effective tools"):
        admission(runtime_tools=(tool,))
