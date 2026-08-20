"""The named interactive lane runs under the SAME skill narrowing as a spawn.

THE COUNTEREXAMPLE THIS PINS. ``Spawner.spawn`` intersects a child's grants
with the loaded skills' declared ``tool_grants`` - the mechanism the
kernel-tools attestation bound assumes ("skills narrow it to ~74 today", the
bound's own comment). ``run_named_chat_turn`` bypassed the spawner and ran on
the caller's RAW grants, so a role whose ceiling is allow:["*"] over a kernel
registering more verbs than the bound compiled every one of them, and every
interactive turn on such a deployment fell back to the read-only phase -
voice without hands (measured live 2026-08-20: 164 verbs against 128).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from boltrig.fleet import named_chat_turn as module
from boltrig.fleet.named_chat_turn import run_named_chat_turn
from boltrig.models import GrantSet, InvocationContext, Skill
from boltrig.store import InMemoryStore

T = "acme"


class _Turn:
    ok = True
    degraded = False
    output: dict = {}
    summary = "done"
    tokens_used = 0
    cost_micros = 0
    new_work_items: tuple = ()


class _RecordingRuntime:
    def __init__(self) -> None:
        self.seen: dict = {}

    async def run_agent_turn(self, task, context, *, tools):
        self.seen = {"grants": context.grants, "tools": tuple(tools)}
        return _Turn()


class _Item:
    id = "item-1"
    tenant_id = T


class _Profile:
    address = "cos"


class _Kernel:
    def __init__(self, store) -> None:
        self.store = store


@pytest.fixture()
def recording(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(
        module.PermanentAgentRuntime,
        "from_named_agent",
        classmethod(lambda cls, spawner, profile, tenant_id: runtime),
    )

    @asynccontextmanager
    async def _hold(self, *args, **kwargs):
        yield

    monkeypatch.setattr(module.AgentTurnCoordinator, "hold", _hold)
    return runtime


async def _store_with_skill() -> InMemoryStore:
    store = InMemoryStore()
    await store.upsert_skill(
        Skill(
            id="browser/visual",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="look things up",
            tool_grants=["browser.navigate", "browser.snapshot"],
        )
    )
    return store


async def test_skills_narrow_a_wildcard_ceiling_to_their_tool_grants(recording):
    store = await _store_with_skill()
    context = InvocationContext(tenant_id=T, run_id="r1", grants=GrantSet.of(["*"]))

    await run_named_chat_turn(
        _Kernel(store), object(), _Item(), _Profile(), "task",
        context, skills=["browser/visual"],
    )

    assert sorted(recording.seen["grants"].allow) == [
        "browser.navigate", "browser.snapshot",
    ]
    assert sorted(recording.seen["tools"]) == [
        "browser.navigate", "browser.snapshot",
    ]


async def test_a_role_with_no_skills_gets_the_empty_set_not_the_ceiling(recording):
    # Legacy spawns gave a skill-less child EMPTY grants; the named lane must
    # not hand the same child the whole ceiling instead. The runtime answers
    # the empty set with the read-only phase, observably.
    store = await _store_with_skill()
    context = InvocationContext(tenant_id=T, run_id="r2", grants=GrantSet.of(["*"]))

    await run_named_chat_turn(
        _Kernel(store), object(), _Item(), _Profile(), "task", context, skills=[],
    )

    assert recording.seen["grants"].allow == ()
    assert recording.seen["tools"] == ()


async def test_callers_that_pass_no_skills_keep_the_raw_context(recording):
    # Peer/background lanes mint their own contexts; only the chat path opts
    # into narrowing by passing the turn's loaded skills.
    store = await _store_with_skill()
    context = InvocationContext(
        tenant_id=T, run_id="r3", grants=GrantSet.of(["ticket.read"])
    )

    await run_named_chat_turn(
        _Kernel(store), object(), _Item(), _Profile(), "task", context,
    )

    assert recording.seen["grants"].allow == ("ticket.read",)
