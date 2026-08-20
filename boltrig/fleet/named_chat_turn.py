"""Direct interactive execution through a durable named identity."""

from __future__ import annotations

import uuid
from typing import Any

from boltrig.models import AgentTurnLane

from .agent_turns import AgentTurnCoordinator
from .permanent_runtime import PermanentAgentRuntime


async def run_named_chat_turn(
    kernel: Any,
    spawner: Any,
    item: Any,
    profile: Any,
    task: str,
    context: Any,
) -> dict[str, Any]:
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
