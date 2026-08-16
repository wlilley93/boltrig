"""Permanent Chief/Department runtime policy, metering, and fallback."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boltrig.fleet.permanent_runtime import PermanentAgentRuntime
from boltrig.fleet.result import AgentResult
from boltrig.models import (
    ActionType,
    AgentCapability,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
)

T = "permanent-runtime"


def _capability(*, runtime: str = "codex") -> AgentCapability:
    return AgentCapability(
        name="head-of-research",
        tenant_id=T,
        runtime=runtime,
        supported_skills=["research/*"],
        max_depth=3,
        is_ephemeral=False,
        cost_tier="expensive",
        model_endpoint="authored-model",
        source="manifest",
    )


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id="root-work",
        workspace_id="workspace-1",
        actor="chief-of-staff",
        actor_tier="tier1",
        on_behalf_of="alice",
        grants=GrantSet.of(["ticket.read"]),
    )


class _Cost:
    def __init__(self) -> None:
        self.reserve = AsyncMock()
        self.reconcile = AsyncMock()


class _Audit:
    def __init__(self) -> None:
        self.rows = []

    async def write(self, row) -> None:
        self.rows.append(row)


class _Runtime:
    runtime = "codex"
    cost_tier = "expensive"
    model_route = {"provider": "openai", "model": "authored-model"}

    def __init__(self) -> None:
        self.calls = []

    async def run(self, prompt, context, *, tools):
        self.calls.append((prompt, context, tools))
        return AgentResult.succeeded(
            {"tasks": ["inspect evidence"]},
            summary="inspect evidence",
            tokens_used=7,
            input_tokens=5,
            output_tokens=2,
        )


def _spawner(runtime_or_error):
    audit = _Audit()
    cost = _Cost()
    if isinstance(runtime_or_error, BaseException):
        resolve = AsyncMock(side_effect=runtime_or_error)
    else:
        resolve = AsyncMock(return_value=runtime_or_error)
    return SimpleNamespace(
        _kernel=SimpleNamespace(cost=cost, audit=audit),
        _runtime_resolver=SimpleNamespace(runtime_for=resolve),
        _true_up_cost=AsyncMock(return_value=37),
    )


@pytest.mark.invariant("SEC-WRK-27")
@pytest.mark.invariant("SEC-WRK-30")
async def test_permanent_profile_is_pinned_metered_and_redacted_in_audit():
    resolved = _Runtime()
    spawner = _spawner(resolved)
    runtime = PermanentAgentRuntime(
        spawner,
        _capability(),
        role="tier2",
        purpose="Own evidence-backed research",
        brief="Prefer primary sources.",
        department="research",
    )

    result = await runtime.run("Decompose the item.", _context(), tools=[])

    assert result.ok and not result.degraded
    spawner._runtime_resolver.runtime_for.assert_awaited_once()
    tenant, capability, phase_context = (
        spawner._runtime_resolver.runtime_for.await_args.args
    )
    assert tenant == T
    assert capability == _capability()
    # SEC-13: the routing seam also receives the egress prompt it is about to
    # run (the PII classification input) - the same string the runtime gets.
    assert spawner._runtime_resolver.runtime_for.await_args.kwargs == {
        "pinned_policy": True,
        "allow_kernel_tools": False,
        "outbound_text": resolved.calls[0][0],
    }
    assert phase_context.actor == "head-of-research"
    assert phase_context.actor_tier == "tier2"
    assert phase_context.parent_run_id == "root-work"
    assert phase_context.run_id != "root-work"
    assert phase_context.grants == _context().grants
    prompt, called_context, tools = resolved.calls[0]
    assert "Purpose: Own evidence-backed research" in prompt
    assert "Brief: Prefer primary sources." in prompt
    assert prompt.endswith("Task:\nDecompose the item.")
    assert called_context is phase_context
    assert tools == []
    reserve = spawner._kernel.cost.reserve.await_args
    assert reserve.args == (T,)
    assert reserve.kwargs["scope_ids"] == [T, "research"]
    spawner._true_up_cost.assert_awaited_once()

    assert len(spawner._kernel.audit.rows) == 1
    row = spawner._kernel.audit.rows[0]
    assert row.action_type == ActionType.MODEL_CALL
    assert row.actor == "head-of-research"
    assert row.actor_tier == "tier2"
    assert row.status == "ok"
    assert row.cost_micros == 37
    assert row.detail["model_route"] == {
        "provider": "openai",
        "model": "authored-model",
    }
    rendered = repr(row)
    assert "Own evidence-backed research" not in rendered
    assert "Prefer primary sources" not in rendered
    assert "Decompose the item" not in rendered


@pytest.mark.invariant("SEC-WRK-27")
@pytest.mark.invariant("SEC-WRK-30")
async def test_refused_runtime_resolution_is_typed_refunded_and_deterministic(
    monkeypatch,
):
    from boltrig.fleet.runtime_resolver import RuntimeResolver

    class Store:
        async def get_model_endpoint(self, tenant_id, endpoint_id):
            return ModelEndpoint(
                id="authored-model",
                tenant_id=T,
                kind="openai",
                model="gpt-test",
                data_class="standard",
            )

    class Mcp:
        def issue_run_token(self, *args, **kwargs):
            return "unused"

        def revoke(self, token):
            return None

    audit = _Audit()
    cost = _Cost()
    kernel = SimpleNamespace(store=Store(), audit=audit, cost=cost, mcp=Mcp())
    resolver = RuntimeResolver(
        kernel,
        codex_config={
            "trusted": True,
            "provider": object(),
            "stack_root": Path("/tmp"),
            "model_id": "gpt-test",
        },
    )
    resolver._resolve_ai_key = AsyncMock(return_value=(None, None))
    spawner = SimpleNamespace(
        _kernel=kernel,
        _runtime_resolver=resolver,
        _true_up_cost=AsyncMock(return_value=37),
    )
    monkeypatch.setenv("BOLTRIG_PRODUCTION", "1")
    monkeypatch.setenv("BOLTRIG_CODEX_TRUSTED", "1")
    runtime = PermanentAgentRuntime(
        spawner,
        _capability(),
        role="tier2",
        purpose="Research",
        brief="",
        department="research",
    )

    result = await runtime.run("Decompose the item.", _context(), tools=[])

    assert result.ok and result.degraded
    assert result.degrade_reason == (
        "permanent_runtime_unavailable:CodexTrustedPostureError"
    )
    spawner._kernel.cost.reconcile.assert_awaited_once()
    reconcile = spawner._kernel.cost.reconcile.await_args
    assert reconcile.args == (cost.reserve.return_value,)
    assert reconcile.kwargs["delta_tokens"] < 0
    assert reconcile.kwargs["delta_micros"] < 0
    spawner._true_up_cost.assert_not_awaited()
    row = spawner._kernel.audit.rows[0]
    assert row.status == "degraded"
    assert row.detail["reason"] == result.degrade_reason
    assert "production_ready stays False" not in repr(row)
