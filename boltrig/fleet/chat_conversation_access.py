"""Conversation access and open-state checks shared by chat projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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


class ConversationAgentSwitchConflict(BoltrigError):
    status_code = 409
    reason = "conversation_agent_switch_conflict"


class ConversationAgentSwitchBusy(BoltrigError):
    status_code = 409
    reason = "conversation_agent_switch_busy"


class ConversationProjectContextMismatch(BoltrigError):
    status_code = 409
    reason = "conversation_project_context_mismatch"


@dataclass(frozen=True)
class ConversationSelection:
    """One authorized ``Conversation`` plus the target for the next turn.

    Resolution does not mutate an existing conversation. Admission performs
    the explicit compare-and-set while holding the cross-replica turn lock, so
    a UI selection can never rewrite history or race an active responder.
    """

    conversation: Conversation
    agent_address: str | None


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
    workspace_id: str | None = None,
) -> ConversationSelection:
    if conversation_id:
        conversation = await store.get_conversation(tenant_id, conversation_id)
        if conversation is None or not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("no such conversation")
        if conversation.status == ConversationStatus.CLOSED:
            raise ConversationClosed("restore the closed conversation before continuing it")
        # Filed project chats execute only while that project is the caller's
        # re-authorized active scope. Legacy/unfiled NULL chats retain their
        # current compatibility behaviour and may run in the active scope.
        if (
            conversation.workspace_id is not None
            and conversation.workspace_id != workspace_id
        ):
            raise ConversationProjectContextMismatch(
                "switch to this conversation's project before continuing it"
            )
        if agent_address is not None:
            # Retargeting is the OWNER's move. A scoped role can read and
            # steer, but letting it assert a different agent onto somebody
            # else's thread would rewrite who answers that person - the old
            # contract refused non-matching assertions, and ownership is the
            # narrowest grant that restores it. Asserting the CURRENT agent
            # stays open to any reader: it retargets nothing.
            if (
                agent_address != conversation.agent_address
                and conversation.user_id != user_id
            ):
                raise ConversationAgentSwitchConflict(
                    "only the conversation owner can change its agent"
                )
            profile = await _resolve_profile(store, tenant_id, agent_address)
            return ConversationSelection(conversation, profile.address)
        if conversation.agent_address is None:
            profile = await _resolve_profile(store, tenant_id, None)
            return ConversationSelection(
                conversation, profile.address if profile is not None else None
            )
        profile = await store.get_named_agent(tenant_id, conversation.agent_address)
        if profile is None:
            raise NamedAgentNotFound("conversation's selected named agent was not found")
        if not profile.enabled:
            raise NamedAgentDisabled("conversation's selected named agent is disabled")
        return ConversationSelection(conversation, profile.address)
    profile = await _resolve_profile(store, tenant_id, agent_address)
    conversation = Conversation(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_address=profile.address if profile is not None else None,
        workspace_id=workspace_id,
        title=message[:60] or "New conversation",
        status=ConversationStatus.ACTIVE,
    )
    await store.create_conversation(conversation)
    return ConversationSelection(conversation, conversation.agent_address)
