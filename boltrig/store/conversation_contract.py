"""Owner-scoped conversation persistence contract."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models import Conversation, ConversationMessage, ConversationSummary


class ConversationStoreContract(Protocol):
    async def create_conversation(self, conv: Conversation) -> None: ...
    async def get_conversation(self, tenant_id: str, conv_id: str) -> Conversation | None: ...
    async def list_conversations(self, tenant_id: str, user_id: str) -> list[Conversation]: ...

    # Stable owner-scoped page, ordered by updated_at DESC with an id tiebreak.
    async def list_conversations_page(
        self, tenant_id: str, user_id: str, *, limit: int, offset: int = 0
    ) -> tuple[list[Conversation], int | None]: ...

    # Search only live, non-superseded messages owned by this tenant and user.
    async def search_conversations(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[tuple[Conversation, str | None]], int | None]: ...

    async def update_conversation(self, conv: Conversation) -> None: ...

    # Atomically restore a retained CLOSED row. The tuple is found, owned, changed.
    async def restore_closed_conversation(
        self,
        tenant_id: str,
        conv_id: str,
        user_id: str,
        restored_at: datetime,
    ) -> tuple[bool, bool, bool]: ...

    async def add_message(self, message: ConversationMessage) -> None: ...
    async def list_messages(self, tenant_id: str, conv_id: str) -> list[ConversationMessage]: ...

    # Marker-only supersession keeps frozen message content and events immutable.
    async def mark_message_superseded(
        self, tenant_id: str, message_id: str, superseded_by: str
    ) -> None: ...

    async def add_conversation_summary(self, summary: ConversationSummary) -> None: ...
    async def get_latest_conversation_summary(
        self, tenant_id: str, conversation_id: str
    ) -> ConversationSummary | None: ...

    # Hard retention purge excludes the tamper-evident audit ledger.
    async def purge_closed_conversations(self, tenant_id: str, older_than: datetime) -> int: ...


__all__ = ["ConversationStoreContract"]
