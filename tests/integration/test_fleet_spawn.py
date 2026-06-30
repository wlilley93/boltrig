"""Ephemeral spawn: cheapest-capable selection, depth + context guards (Epic FLT)."""

import pytest

from boltrig.fleet import build_spawner
from boltrig.kernel import Kernel
from boltrig.models import (
    AgentCapability,
    ContextRequirementsUnmet,
    DepthExceeded,
    GrantSet,
    InvocationContext,
    Skill,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel_with_caps() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    # two capable runtimes; the cheap one must win
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 2, True, "cheap")
    )
    await store.upsert_capability(
        AgentCapability("claude-api-worker", T, "claude-api", ["*"], 2, True, "expensive")
    )
    await store.upsert_skill(
        Skill(
            id="analysis/decompose",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Decompose the task.",
            tool_grants=["ticket.read"],
            context_requirements={
                "type": "object",
                "required": ["epic_id"],
                "properties": {"epic_id": {"type": "string"}},
            },
        )
    )
    return Kernel(store)


def _ctx(depth: int = 0, *, epic_id: str | None = "ENG-441") -> InvocationContext:
    extra = {"epic_id": epic_id} if epic_id is not None else {}
    return InvocationContext(
        tenant_id=T, grants=GrantSet.of(["*"]), actor="head", depth=depth, extra=extra
    )


@pytest.mark.invariant("US-FLT-04")
async def test_cheapest_capable_runtime_chosen():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    res = await spawner.spawn(
        T, "decompose epic", ["analysis/decompose"], {}, _ctx(),
    )
    assert res["agent_type"] == "script-worker"  # cheap beats expensive
    assert "run_id" in res


async def test_context_requirements_validated():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    # the spawn context is missing the required epic_id
    with pytest.raises(ContextRequirementsUnmet):
        await spawner.spawn(T, "x", ["analysis/decompose"], {}, _ctx(epic_id=None))


@pytest.mark.invariant("FR-EXE-03")
async def test_depth_limit_enforced():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    # depth already at the capability max_depth (2) -> spawning a child exceeds it
    with pytest.raises(DepthExceeded):
        await spawner.spawn(
            T, "x", ["analysis/decompose"], {}, _ctx(depth=2),
        )
