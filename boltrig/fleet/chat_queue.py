"""Owner-scoped scheduling operations for queued conversational steers."""

from __future__ import annotations

from typing import Any

from boltrig.models import ConversationMessage

from .chat_conversation_access import (
    ConversationClosed,
    ConversationForbidden,
    can_read_conversation,
)


class ChatQueueService:
    _store: Any

    def _lock_for(self, tenant_id: str, conversation_id: str): ...

    async def _next_pending_steer(
        self, tenant_id: str, conversation_id: str, run_id: str
    ) -> ConversationMessage | None:
        """Atomically claim the first pending steer in its current durable order."""
        return await self._store.claim_next_conversation_steer(
            tenant_id, conversation_id, run_id
        )

    async def pending_steer_ids(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> list[str] | None:
        conversation = await self._store.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            return None
        if not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("not permitted to read this conversation")
        return await self._store.pending_conversation_steer_ids(
            tenant_id, conversation_id
        )

    async def reorder_pending_steers(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        expected_message_ids: list[str],
        message_ids: list[str],
    ) -> bool:
        """Owner-only compare-and-swap of the complete pending queue order."""
        conversation = await self._store.get_conversation(tenant_id, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationForbidden("no such conversation")
        if conversation.status.value == "closed":
            raise ConversationClosed("restore the closed conversation before reordering it")
        async with self._lock_for(tenant_id, conversation_id):
            return await self._store.reorder_conversation_steers(
                tenant_id,
                conversation_id,
                expected_message_ids,
                message_ids,
            )


__all__ = ["ChatQueueService"]
