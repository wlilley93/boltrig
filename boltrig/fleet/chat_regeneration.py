"""Eligibility resolution for append-plus-supersede regeneration."""

from __future__ import annotations

from boltrig.fleet.chat_conversation_access import ConversationClosed
from boltrig.models import BoltrigError, ConversationStatus, MessageRole


class RegenerateNotEligible(BoltrigError):
    status_code = 409
    reason = "regenerate_not_eligible"


async def regeneration_inputs(
    store,
    tenant_id: str,
    conversation_id: str,
    target_message_id: str,
):
    conversation = await store.get_conversation(tenant_id, conversation_id)
    if conversation is not None and conversation.status == ConversationStatus.CLOSED:
        raise ConversationClosed("restore the closed conversation before regenerating a reply")
    messages = await store.list_messages(tenant_id, conversation_id)
    live = [message for message in messages if message.superseded_by is None]
    assistant = next(
        (message for message in reversed(live) if message.role == MessageRole.ASSISTANT),
        None,
    )
    if assistant is None or assistant.id != target_message_id:
        raise RegenerateNotEligible("only the last assistant message may be regenerated")
    user = next(
        (message for message in reversed(live) if message.role == MessageRole.USER),
        None,
    )
    if user is None:
        raise RegenerateNotEligible("no user message to regenerate")
    return assistant, user, conversation.agent_address if conversation is not None else None
