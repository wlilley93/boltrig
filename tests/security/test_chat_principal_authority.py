"""The chat (direct-spawn) lane runs at the CALLER's authority, by construction (SEC-174).

Sibling to ``test_pump_principal_authority`` (SEC-164/165): the pump was the lane that
built its execution context from the tenant ceiling. The chat lane never had that live
escalation - its spawn was capped by a SEPARATE ``grant_ceiling`` argument - but the
context it handed to the spawner still carried the TENANT-WIDE grant set, so the cap was
rescued by convention (remembering the argument) rather than by construction. If a later
edit dropped that argument, the tenant-wide context would have become the operative cap.

SEC-174 makes the safe thing the only expressible thing: the chat context now carries the
caller's capped grants directly (mirroring ``authority.context_for``), and the redundant
``grant_ceiling`` is removed, so ``ctx.grants`` is the single load-bearing caller cap. The
tenant ceiling stays the separate axis it always was, enforced independently at dispatch
(``kernel/grants.py``, US-IAM-04).

Like the pump tests, these assert on EFFECTIVE authority - the grants the spawned child
ACTUALLY received (``effective_grants``, = ``child_grants.allow``) and what the kernel
chokepoint actually permits - never merely on a parameter being passed. Bound to SEC-174.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.config.manifest import ChatConfig
from boltrig.fleet import build_spawner
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    AgentCapability,
    GrantMissing,
    GrantSet,
    InvocationContext,
    Skill,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"
WS = "ws1"
RISKY_VERB = "ticket.create"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    # The tenant ceiling is wide open: the ONLY thing that may narrow a chat turn is the
    # caller. This is the exact condition the tenant-wide context used to obscure.
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 3, True, "cheap")
    )
    # A skill that DECLARES the risky grant. Under a tenant-wide context this alone, plus
    # a dropped ceiling, would have been enough to hand the verb to any caller's turn.
    await store.upsert_skill(
        Skill(id="risky", tenant_id=T, version="1.0.0", prompt_fragment="p",
              tool_grants=[RISKY_VERB], context_requirements={})
    )
    return kernel


class _RecordingSpawner:
    """Delegates to the real spawner and captures each spawn RESULT so a test can read
    the child's ``effective_grants`` - the authority it actually received, not an arg."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.results: list[dict] = []

    async def spawn(self, *args, **kwargs):
        result = await self._inner.spawn(*args, **kwargs)
        self.results.append(result)
        return result


async def _turn_child_grants(kernel: Kernel, caller_grants: GrantSet) -> set[str]:
    """Drive one full chat turn at ``caller_grants`` and return the grants the spawned
    child actually received. The role 'engineer' maps to the risky skill, so the turn
    spawns with a skill that declares RISKY_VERB - the child gets it only if the caller
    ceiling permits it."""
    spawner = _RecordingSpawner(build_spawner(kernel))
    chat = ChatService(
        kernel.store,
        EventRelay(),
        turn_executor=build_turn_executor(
            kernel, spawner, continuity=False,
            chat_config=ChatConfig(skills_by_role={"engineer": ("risky",)}),
        ),
    )
    async for _ in chat.handle_turn(
        tenant_id=T, user_id="alice", role="engineer", message="file a ticket",
        workspace_id=WS, grants=caller_grants,
    ):
        pass
    assert spawner.results, "the chat turn never reached the spawner"
    return set(spawner.results[0].get("effective_grants") or [])


@pytest.mark.security
@pytest.mark.invariant("SEC-174")
async def test_a_narrow_caller_never_gets_a_verb_it_lacks_though_the_skill_declares_it():
    """A caller whose ceiling lacks the verb does not get it, even though the selected
    skill declares it and the tenant ceiling permits it. The cap now lives in the
    context by construction, not in a separate argument that could be forgotten."""
    kernel = await _kernel()

    eff = await _turn_child_grants(kernel, GrantSet.of(["ticket.read"]))  # no ticket.create

    # effective authority, not a passed parameter: the child never received the verb.
    assert RISKY_VERB not in eff

    # and the chokepoint actually refuses it under a context carrying those grants.
    ctx = InvocationContext(tenant_id=T, grants=GrantSet.of(sorted(eff)), run_id="probe")
    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", RISKY_VERB, {"title": "escalated"}, ctx)


@pytest.mark.security
@pytest.mark.invariant("SEC-174")
async def test_a_caller_holding_the_verb_still_gets_it():
    """The contrast case - without it the escalation test could pass vacuously (e.g. if
    a chat turn simply never granted anything)."""
    kernel = await _kernel()

    eff = await _turn_child_grants(kernel, GrantSet.of([RISKY_VERB]))

    assert RISKY_VERB in eff
    ctx = InvocationContext(tenant_id=T, grants=GrantSet.of(sorted(eff)), run_id="probe")
    await kernel.invoke("ticket", RISKY_VERB, {"title": "legitimate"}, ctx)  # no raise


@pytest.mark.security
@pytest.mark.invariant("SEC-174")
async def test_a_caller_ceiling_wider_than_the_skill_is_bound_by_the_skill():
    """Composition still binds from both sides: a caller granted everything only gets
    what the turn's skill declares (child = skill ∩ caller), never a blanket '*'."""
    kernel = await _kernel()

    eff = await _turn_child_grants(kernel, GrantSet.of(["*"]))

    # The wide caller does receive the skill's declared verb...
    assert RISKY_VERB in eff
    # ...but not a blanket wildcard: the skill, not the caller, bounds the allow set.
    assert "*" not in eff
