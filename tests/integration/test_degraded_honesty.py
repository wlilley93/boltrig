"""Degraded honesty: a degraded run is marked end to end (US-FLT-07, Beat 1)."""

import pytest

from boltrig.fleet import build_spawner, make_agent_invoker
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.fleet.spawn import Spawner
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


def _kernel_with_retired_runtime() -> Kernel:
    """A kernel whose only capability names a removed runtime."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


async def _add_retired_capability(kernel: Kernel, *, runtime: str = "removed-runtime") -> None:
    await kernel.store.upsert_capability(
        AgentCapability("retired-worker", T, runtime, ["*"], 2, True, "standard")
    )


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="head")


@pytest.mark.invariant("US-FLT-07")
async def test_spawn_without_runtime_is_marked_degraded_and_audited():
    kernel = _kernel_with_retired_runtime()
    await _add_retired_capability(kernel)
    spawner = build_spawner(kernel)
    res = await spawner.spawn(T, "summarise the quarter", [], {}, _ctx())
    # the spawn result carries the first-class flag, not just the payload marker
    assert res["degraded"] is True
    assert res["output"]["_degraded"]["reason"] == "runtime_unavailable"
    # the AGENT_SPAWN audit row says "degraded", never "ok"
    rows = await kernel.store.audit_query(T)
    spawn_rows = [r for r in rows if r.action_type == ActionType.AGENT_SPAWN]
    assert spawn_rows and spawn_rows[-1].status == "degraded"


@pytest.mark.invariant("US-FLT-07")
async def test_chat_turn_surfaces_a_degraded_spawn():
    kernel = _kernel_with_retired_runtime()
    await _add_retired_capability(kernel)
    spawner = build_spawner(kernel)
    relay = EventRelay()
    chat = ChatService(
        kernel.store,
        relay,
        turn_executor=build_turn_executor(kernel, spawner, continuity=False),
    )
    out = [
        e
        async for e in chat.handle_turn(
            tenant_id=T,
            user_id="alice",
            role="engineer",
            message="do the thing",
            grants=GrantSet.of(["*"]),
        )
    ]
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


@pytest.mark.invariant("US-FLT-07")
async def test_agent_invoker_runtime_failure_is_marked_degraded_not_echoed(monkeypatch):
    # A resolved runtime that RAISES must not be papered over with a plain
    # ScriptRuntime echo (ok=True / degraded=False); the invoker must surface a
    # degrade-marked result with an audit-visible reason (US-FLT-07).
    kernel = _kernel_with_retired_runtime()
    await _add_retired_capability(kernel, runtime="codex")

    class _Boom:
        runtime = "codex"
        cost_tier = "standard"

        async def run(self, prompt, context, *, tools):
            raise RuntimeError("gateway exploded")

    async def _boom_runtime_for(self, tenant_id, capability, context=None, *, outbound_text=None):
        return _Boom()

    monkeypatch.setattr(Spawner, "_runtime_for", _boom_runtime_for)

    invoker = make_agent_invoker(kernel)
    result = await invoker("demo.verb", {"x": 1}, _ctx(), "retired-worker")
    # ok stays True so the tree keeps running (P9), but the crash is NEVER an
    # unmarked success: the _degraded marker with an audit-visible reason is set.
    assert result.ok is True
    assert "_degraded" in result.output
    assert result.output["_degraded"]["reason"] == "RuntimeError"
    # regression guard: the old echo left no marker and no runtime kind.
    assert result.output["_degraded"]["runtime"] == "codex"
