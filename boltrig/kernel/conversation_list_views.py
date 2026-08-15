"""Content-safe conversation-list projections shared by list and search routes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_SNIPPET_MAX = 240


def conversation_views(
    chat_service: Any, tenant_id: str, conversations: Iterable[Any]
) -> list[dict[str, Any]]:
    return [_conversation_view(chat_service, tenant_id, item) for item in conversations]


def conversation_search_views(
    chat_service: Any,
    tenant_id: str,
    pairs: Iterable[tuple[Any, str | None]],
) -> list[dict[str, Any]]:
    return [
        {**_conversation_view(chat_service, tenant_id, item), "snippet": _snippet(snippet)}
        for item, snippet in pairs
    ]


def _conversation_view(chat_service: Any, tenant_id: str, conversation: Any) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "status": conversation.status.value,
        "updated_at": conversation.updated_at.isoformat(),
        "working": chat_service.conversation_is_working(tenant_id, conversation.id),
        "origin": conversation.origin.value,
        "source_ref": conversation.source_ref,
        "source_run_id": conversation.source_run_id,
        "companion_id": conversation.companion_id,
    }


def _snippet(text: str | None) -> str | None:
    """Return enough matched content to explain a hit, never the full message."""
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= _SNIPPET_MAX else text[:_SNIPPET_MAX].rstrip() + "..."
