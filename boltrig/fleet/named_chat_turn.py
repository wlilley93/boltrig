"""Direct interactive execution through a durable named identity."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from boltrig.models import AgentTurnLane, GrantSet

from .agent_turns import AgentTurnCoordinator
from .permanent_runtime import PermanentAgentRuntime
from .spawn_skills import resolve_skills


async def _narrowed_context(
    kernel: Any, item: Any, skills: list[str], context: Any
) -> Any:
    """The turn's context under the same skill narrowing every spawn applies.

    ``Spawner.spawn`` intersects a child's grants with the loaded skills'
    declared ``tool_grants`` - that intersection is what keeps a bare chat
    turn's effective verb set at the size the kernel-tools attestation bound
    assumes ("skills narrow it to ~74 today", the bound's own comment). The
    named lane bypassed the spawner and ran on the CALLER'S RAW grants, so a
    role whose ceiling is allow:["*"] compiled every registered verb, blew
    the bound, and every interactive turn fell back to the read-only phase:
    voice without hands, on precisely the deployments that configured the
    most. Same skills, same intersection, same result as the legacy lane -
    and a role that loads no skills still gets the empty set, which the
    runtime already answers with the read-only phase, observably.
    """

    merged = await resolve_skills(kernel.store, item.tenant_id, skills)
    # ``agent.send`` is the LANE's intrinsic capability - chat_turn_inputs
    # appends it after the role ceiling so a durable identity can always reach
    # its peers (FLT-PEER-01). Narrowing by skills must not strip it; the
    # intersection still only keeps it when the lane actually granted it.
    allow = [*merged.tool_grants, "agent.send"]
    narrowed = GrantSet.of(allow=allow).intersect(context.grants)
    return replace(context, grants=narrowed)


async def run_named_chat_turn(
    kernel: Any,
    spawner: Any,
    item: Any,
    profile: Any,
    task: str,
    context: Any,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    if skills is not None:
        context = await _narrowed_context(kernel, item, skills, context)
    runtime = PermanentAgentRuntime.from_named_agent(spawner, profile, item.tenant_id)
    coordinator = AgentTurnCoordinator(kernel.store)
    async with coordinator.hold(
        item.tenant_id,
        profile.address,
        f"chat:{item.id}:{uuid.uuid4().hex}",
        AgentTurnLane.INTERACTIVE,
    ):
        turn = await runtime.run_agent_turn(
            task, context, tools=list(context.grants.allow)
        )
    return {
        "status": "ok" if turn.ok else "error",
        "degraded": turn.degraded,
        "output": turn.output,
        "summary": turn.summary,
        "tokens_used": turn.tokens_used,
        "cost_micros": turn.cost_micros,
        "new_work_items": list(turn.new_work_items),
    }
