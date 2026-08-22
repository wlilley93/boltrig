"""Author-visible named-agent roster and durable mailbox reads."""

from __future__ import annotations

from fastapi import HTTPException

from boltrig.models import GrantMissing

from ._shared import require_author, scope_depts


def _agent_view(agent) -> dict:
    return {
        "address": agent.address,
        "name": agent.name,
        "topology": "tier1_peer",
        "session": "durable_logical",
        "runtime": agent.runtime,
        "model_endpoint": agent.model_endpoint,
        "supported_skills": list(agent.supported_skills),
        "max_depth": agent.max_depth,
        "cost_tier": agent.cost_tier,
        "purpose": agent.purpose,
        "scope_id": agent.scope_id,
        "default_for_intake": agent.default_for_intake,
        "enabled": agent.enabled,
    }


def _message_view(message, status: str) -> dict:
    # The captured authority envelope is intentionally not projected. It can
    # contain principal scope and provenance fields that are irrelevant to a
    # mailbox reader; the kernel and delivery worker are its only consumers.
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender": message.sender,
        "recipient": message.recipient,
        "kind": message.kind.value,
        "content": message.content,
        "reply_to": message.reply_to,
        "correlation_id": message.correlation_id,
        "run_id": message.run_id,
        "status": status,
        "created_at": message.created_at.isoformat(),
    }


def _require_visible(agent, principal) -> None:
    visible = scope_depts(principal)
    if visible is not None and agent.scope_id and agent.scope_id not in visible:
        raise GrantMissing("named agent is outside the caller's scope")


def register(app, P, K) -> None:
    @app.get("/v1/named-agents")
    async def list_named_agents(k=K, p=P) -> dict:
        require_author(p)
        visible = scope_depts(p)
        rows = await k.store.list_named_agents(p.tenant_id, include_disabled=True)
        if visible is not None:
            rows = [row for row in rows if not row.scope_id or row.scope_id in visible]
        return {"named_agents": [_agent_view(row) for row in rows]}

    @app.get("/v1/named-agents/{address}/inbox")
    async def named_agent_inbox(address: str, limit: int = 100, k=K, p=P) -> dict:
        require_author(p)
        agent = await k.store.get_named_agent(p.tenant_id, address)
        if agent is None:
            raise HTTPException(status_code=404, detail="named agent not found")
        _require_visible(agent, p)
        rows = await k.store.list_agent_inbox(
            p.tenant_id, address, limit=max(1, min(limit, 500))
        )
        return {
            "agent": _agent_view(agent),
            "messages": [_message_view(message, status) for message, status in rows],
        }


__all__ = ["register"]
