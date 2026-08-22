"""Owner-scoped scheduling operations for queued conversational steers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from boltrig.models import ConversationMessage

from .chat_conversation_access import (
    ConversationClosed,
    ConversationForbidden,
    can_read_conversation,
)


@dataclass(frozen=True)
class ConversationWorkspaceMove:
    """The authoritative result of an idle-only project membership CAS."""

    found: bool
    busy: bool
    workspace_id: str | None


class ChatQueueService:
    _store: Any

    def _lock_for(self, tenant_id: str, conversation_id: str): ...

    async def _next_pending_steer(
        self, tenant_id: str, conversation_id: str, run_id: str
    ) -> ConversationMessage | None:
        """Atomically claim the first pending steer in its current durable order."""
        return await self._store.claim_next_conversation_steer(tenant_id, conversation_id, run_id)

    async def pending_steer_ids(
        self, tenant_id: str, user_id: str, role: str, conversation_id: str
    ) -> list[str] | None:
        conversation = await self._store.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            return None
        if not can_read_conversation(conversation, user_id, role):
            raise ConversationForbidden("not permitted to read this conversation")
        return await self._store.pending_conversation_steer_ids(tenant_id, conversation_id)

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

    async def move_conversation_workspace_if_idle(
        self,
        tenant_id: str,
        conversation_id: str,
        expected_workspace_id: str | None,
        workspace_id: str | None,
    ) -> ConversationWorkspaceMove:
        """CAS project membership only when no turn or queued steer can observe it.

        Turn reservation, steer enqueueing, and project moves share this
        cross-replica conversation lock. A turn that resolved just before the
        move revalidates the stored project after acquiring the lock, so neither
        operation can execute against a stale authority scope.
        """
        async with self._lock_for(tenant_id, conversation_id):
            if self._active_run_for(tenant_id, conversation_id) is not None:
                conversation = await self._store.get_conversation(tenant_id, conversation_id)
                return ConversationWorkspaceMove(
                    found=conversation is not None,
                    busy=True,
                    workspace_id=(conversation.workspace_id if conversation is not None else None),
                )
            pending = await self._store.pending_conversation_steer_ids(tenant_id, conversation_id)
            if pending:
                conversation = await self._store.get_conversation(tenant_id, conversation_id)
                return ConversationWorkspaceMove(
                    found=conversation is not None,
                    busy=True,
                    workspace_id=(conversation.workspace_id if conversation is not None else None),
                )
            found, converged = await self._store.move_conversation_workspace(
                tenant_id,
                conversation_id,
                expected_workspace_id,
                workspace_id,
            )
            return ConversationWorkspaceMove(
                found=found,
                busy=False,
                workspace_id=converged,
            )


__all__ = ["ChatQueueService", "ConversationWorkspaceMove"]
