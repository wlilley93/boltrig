"""Conversation access and open-state checks shared by chat projections."""

from __future__ import annotations

import uuid
from typing import Any

from boltrig.models import BoltrigError, Conversation, ConversationStatus


_SCOPED_ROLES = {"org-admin", "compliance"}


class ConversationForbidden(BoltrigError):
    status_code = 403
    reason = "conversation_forbidden"


class ConversationClosed(BoltrigError):
    """A retained conversation cannot accept a turn until explicitly restored."""

    status_code = 409
    reason = "conversation_closed"


class NamedAgentNotFound(BoltrigError):
    status_code = 404
    reason = "named_agent_not_found"


class NamedAgentDisabled(BoltrigError):
    status_code = 409
    reason = "conversation_agent_disabled"


class NamedAgentRequired(BoltrigError):
    status_code = 409
    reason = "named_agent_required"


class ConversationAgentMismatch(BoltrigError):
    status_code = 409
    reason = "conversation_agent_mismatch"


def can_read_conversation(conversation: Conversation, user_id: str, role: str) -> bool:
    return conversation.user_id == user_id or role in _SCOPED_ROLES


async def _resolve_profile(
    store: Any, tenant_id: str, requested_address: str | None
) -> Any | None:
    if requested_address:
        profile = await store.get_named_agent(tenant_id, requested_address)
        if profile is None:
            raise NamedAgentNotFound("named agent not found")
        if not profile.enabled:
            raise NamedAgentDisabled("named agent is disabled")
        return profile
    # Include disabled rows to distinguish an adopted named-agent registry from
    # an empty legacy tenant. The branches below handle those cases separately.
    roster = await store.list_named_agents(tenant_id, include_disabled=True)
    profile = next(
        (agent for agent in roster if agent.enabled and agent.default_for_intake),
        None,
    )
    if profile is not None:
        return profile
    if roster:
        # More than zero choices without an authored default is ambiguity, not
        # permission to let row order silently pick an identity.
        raise NamedAgentRequired("choose a named agent for this conversation")
    # Compatibility for tenants that have not enabled named agents at all.
    return None


async def resolve_conversation(
    store: Any,
    tenant_id: str,
    conversation_id: str | None,
    user_id: str,
    role: str,
    message: str,
    agent_address: str | None = None,
) -> Conversation:
    if conversation_id:
        conversation = await store.get_conversation(tenant_id, conversation_id)
        if conversation is None or not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("no such conversation")
        if conversation.status == ConversationStatus.CLOSED:
            raise ConversationClosed("restore the closed conversation before continuing it")
        if conversation.agent_address is not None:
            if agent_address and agent_address != conversation.agent_address:
                raise ConversationAgentMismatch(
                    "conversation is bound to another named agent"
                )
            profile = await store.get_named_agent(
                tenant_id, conversation.agent_address
            )
            if profile is None:
                raise NamedAgentNotFound("conversation's named agent was not found")
            if not profile.enabled:
                raise NamedAgentDisabled("conversation's named agent is disabled")
            return conversation

        # A legacy NULL row is claimed exactly once. The store operation is an
        # atomic compare-and-set, so concurrent first continuations converge on
        # one binding even across worker replicas.
        profile = await _resolve_profile(store, tenant_id, agent_address)
        if profile is None:
            return conversation
        bound = await store.bind_conversation_agent(
            tenant_id, conversation.id, profile.address
        )
        if bound != profile.address:
            raise ConversationAgentMismatch(
                "conversation was concurrently bound to another named agent"
            )
        conversation.agent_address = bound
        return conversation
    profile = await _resolve_profile(store, tenant_id, agent_address)
    conversation = Conversation(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_address=profile.address if profile is not None else None,
        title=message[:60] or "New conversation",
        status=ConversationStatus.ACTIVE,
    )
    await store.create_conversation(conversation)
    return conversation
