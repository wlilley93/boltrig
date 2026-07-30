"""Safe, caller-actionable projections of ChatService configuration and context."""

from __future__ import annotations

from typing import Any

from boltrig.config.manifest import ChatConfig
from boltrig.models import ConversationMessage

from .continuity import compaction_enabled


def attachment_config(config: ChatConfig) -> dict[str, Any]:
    return {
        "max_count": config.max_attachments,
        "max_bytes": config.max_attachment_bytes,
        "max_total_bytes": config.max_total_attachment_bytes,
        "model_readable_media_types": ["text/*"],
    }


async def context_compaction(
    store: Any,
    config: ChatConfig,
    tenant_id: str,
    conversation_id: str,
    messages: list[ConversationMessage],
) -> dict[str, Any]:
    live = [message for message in messages if message.superseded_by is None]
    inactive = {
        "compacted": False,
        "covered_count": 0,
        "recent_exact_count": len(live),
        "up_to_message_id": None,
        "summary": None,
    }
    if not compaction_enabled(config):
        return inactive
    summary = await store.get_latest_conversation_summary(tenant_id, conversation_id)
    if summary is None or len(live) < int(config.compaction_threshold):
        return inactive
    boundary = next(
        (
            index
            for index, message in enumerate(live)
            if message.id == summary.up_to_message_id
        ),
        None,
    )
    if boundary is None or boundary >= len(live) - 1:
        return inactive
    return {
        "compacted": True,
        "covered_count": summary.covered_count,
        "recent_exact_count": len(live) - boundary - 1,
        "up_to_message_id": summary.up_to_message_id,
        "summary": summary.summary,
    }
