"""Append-only conversation compaction helpers."""

from __future__ import annotations

import uuid

from boltrig.models import ConversationMessage, ConversationSummary

from .continuity import compaction_enabled, plan_compaction, summarize_messages


async def summarise(service, older: list[ConversationMessage]) -> str:
    if service._summariser is not None:  # noqa: SLF001
        try:
            text = await service._summariser(older)  # noqa: SLF001
            if text:
                return text
        except Exception:
            pass
    return summarize_messages(older)


async def maybe_compact(service, tenant_id: str, conversation_id: str) -> None:
    """Append a new derived summary only when its covered prefix advances."""
    if not compaction_enabled(service._cfg):  # noqa: SLF001
        return
    messages = await service._store.list_messages(tenant_id, conversation_id)  # noqa: SLF001
    live = [message for message in messages if message.superseded_by is None]
    older = plan_compaction(live, service._cfg)  # noqa: SLF001
    if not older:
        return
    latest = await service._store.get_latest_conversation_summary(  # noqa: SLF001
        tenant_id, conversation_id
    )
    if latest is not None and len(older) <= latest.covered_count:
        return
    summary_text = await summarise(service, older)
    await service._store.add_conversation_summary(  # noqa: SLF001
        ConversationSummary(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            up_to_message_id=older[-1].id,
            covered_count=len(older),
            summary=summary_text,
        )
    )
