"""PostgreSQL row mappers for named-agent mailbox state."""

from __future__ import annotations

from boltrig.models import (
    AgentDelivery,
    AgentDeliveryStatus,
    AgentMessage,
    AgentMessageKind,
    AgentSession,
    AgentSessionSummary,
    AgentTurnLane,
    AgentTurnLease,
    NamedAgent,
)


def named_agent_from_row(row):
    if row is None:
        return None
    return NamedAgent(
        tenant_id=row["tenant_id"],
        address=row["address"],
        name=row["name"],
        runtime=row["runtime"],
        model_endpoint=row["model_endpoint"],
        supported_skills=list(row["supported_skills"] or []),
        max_depth=row["max_depth"],
        cost_tier=row["cost_tier"],
        purpose=row["purpose"] or "",
        brief=row["brief"] or "",
        scope_id=row["scope_id"],
        default_for_intake=bool(row["default_for_intake"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def agent_message_from_row(row):
    if row is None:
        return None
    return AgentMessage(
        id=row["id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        sender=row["sender"],
        recipient=row["recipient"],
        kind=AgentMessageKind(row["kind"]),
        content=row["content"],
        reply_to=row["reply_to"],
        correlation_id=row["correlation_id"],
        run_id=row["run_id"],
        authority=dict(row["authority"] or {}),
        created_at=row["created_at"],
    )


def agent_delivery_from_row(row):
    if row is None:
        return None
    return AgentDelivery(
        tenant_id=row["tenant_id"],
        message_id=row["message_id"],
        recipient=row["delivery_recipient"] if "delivery_recipient" in row else row["recipient"],
        status=AgentDeliveryStatus(row["delivery_status"] if "delivery_status" in row else row["status"]),
        attempts=row["attempts"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        available_at=row["available_at"],
        last_error=row["last_error"],
        delivered_at=row["delivered_at"],
        updated_at=row["delivery_updated_at"] if "delivery_updated_at" in row else row["updated_at"],
    )


def agent_turn_lease_from_row(row):
    if row is None or row["lease_owner"] is None:
        return None
    return AgentTurnLease(
        tenant_id=row["tenant_id"],
        agent_address=row["agent_address"],
        owner=row["lease_owner"],
        token=row["lease_token"],
        lane=AgentTurnLane(row["lane"]),
        expires_at=row["lease_expires_at"],
    )


def agent_session_from_row(row):
    if row is None:
        return None
    return AgentSession(
        id=row["id"],
        tenant_id=row["tenant_id"],
        agent_address=row["agent_address"],
        conversation_id=row["conversation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def agent_summary_from_row(row):
    if row is None:
        return None
    return AgentSessionSummary(
        id=row["id"],
        tenant_id=row["tenant_id"],
        session_id=row["session_id"],
        up_to_message_id=row["up_to_message_id"],
        covered_count=row["covered_count"],
        summary=row["summary"],
        created_at=row["created_at"],
    )


__all__ = [
    "agent_delivery_from_row",
    "agent_message_from_row",
    "agent_session_from_row",
    "agent_summary_from_row",
    "agent_turn_lease_from_row",
    "named_agent_from_row",
]
