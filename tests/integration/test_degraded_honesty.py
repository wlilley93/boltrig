"""Degraded honesty: a degraded run is marked end to end (US-FLT-07, Beat 1)."""

import pytest

from boltrig.fleet import build_spawner
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    ActionType,
    AgentCapability,
    GrantSet,
    InvocationContext,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


def _kernel_hermes_only() -> Kernel:
    """A kernel whose only capability is hermes with no endpoint configured, so
    every spawn degrades (no_endpoint) rather than reasoning (P9)."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


async def _add_hermes_cap(kernel: Kernel) -> None:
    await kernel.store.upsert_capability(
        AgentCapability("hermes-worker", T, "hermes", ["*"], 2, True, "standard")
    )


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="head")


@pytest.mark.invariant("US-FLT-07")
async def test_spawn_without_runtime_is_marked_degraded_and_audited():
    kernel = _kernel_hermes_only()
    await _add_hermes_cap(kernel)
    spawner = build_spawner(kernel)
    res = await spawner.spawn(T, "summarise the quarter", [], {}, _ctx())
    # the spawn result carries the first-class flag, not just the payload marker
    assert res["degraded"] is True
    assert res["output"]["_degraded"]["reason"] == "no_endpoint"
    # the AGENT_SPAWN audit row says "degraded", never "ok"
    rows = await kernel.store.audit_query(T)
    spawn_rows = [r for r in rows if r.action_type == ActionType.AGENT_SPAWN]
    assert spawn_rows and spawn_rows[-1].status == "degraded"


@pytest.mark.invariant("US-FLT-07")
async def test_chat_turn_surfaces_a_degraded_spawn():
    kernel = _kernel_hermes_only()
    await _add_hermes_cap(kernel)
    spawner = build_spawner(kernel)
    relay = EventRelay()
    chat = ChatService(
        kernel.store, relay,
        turn_executor=build_turn_executor(kernel, spawner, continuity=False),
    )
    out = [e async for e in chat.handle_turn(
        tenant_id=T, user_id="alice", role="engineer", message="do the thing"
    )]
    # the reply event visibly carries degradation: the flag plus a degraded text
    deltas = [e for e in out if e.get("type") == "text_delta"]
    assert any(e.get("degraded") is True for e in deltas)
    reply = "".join(e.get("delta", "") for e in deltas)
    assert "degraded" in reply  # echo is never presented as ordinary success
    # the persisted assistant message carries the same degraded reply
    convs = await kernel.store.list_conversations(T, "alice")
    msgs = await kernel.store.list_messages(T, convs[0].id)
    assert "degraded" in msgs[1].content
    # and the turn's AGENT_SPAWN audit row is "degraded" (the work item gains a
    # persisted degraded column in Beat 3)
    rows = await kernel.store.audit_query(T)
    spawn_rows = [r for r in rows if r.action_type == ActionType.AGENT_SPAWN]
    assert spawn_rows and spawn_rows[-1].status == "degraded"
