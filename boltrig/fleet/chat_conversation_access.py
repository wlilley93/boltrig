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


def can_read_conversation(conversation: Conversation, user_id: str, role: str) -> bool:
    return conversation.user_id == user_id or role in _SCOPED_ROLES


async def resolve_conversation(
    store: Any,
    tenant_id: str,
    conversation_id: str | None,
    user_id: str,
    role: str,
    message: str,
) -> Conversation:
    if conversation_id:
        conversation = await store.get_conversation(tenant_id, conversation_id)
        if conversation is None or not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("no such conversation")
        if conversation.status == ConversationStatus.CLOSED:
            raise ConversationClosed("restore the closed conversation before continuing it")
        return conversation
    conversation = Conversation(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        title=message[:60] or "New conversation",
        status=ConversationStatus.ACTIVE,
    )
    await store.create_conversation(conversation)
    return conversation
