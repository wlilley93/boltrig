"""Opt-in policy controls for channel intake.

The key distinction is compatibility: an absent ``allowed_chats`` key means the
channel keeps its historical behaviour. Once an operator declares the key, the
channel is in allowlist mode and an unknown/missing chat fails closed. Thread
ceilings are likewise opt-in and can only narrow the resolved principal's grants.
"""

from __future__ import annotations

from typing import Any

from boltrig.kernel.work_authority import CHANNEL_THREAD_CEILING_KEY
from boltrig.models import Channel, GrantSet, WorkItem

_CHAT_FIELDS = ("chat", "chat_id", "channel", "channel_id", "thread", "thread_id")
_CEILING_KEY = CHANNEL_THREAD_CEILING_KEY


def chat_id(channel: Channel, body: dict[str, Any]) -> str | None:
    """Return the verified event's chat key, using only configured/body routing fields."""
    addressing = dict((channel.config or {}).get("addressing") or {})
    configured = addressing.get("chat_field") or addressing.get("thread_field")
    fields = ([str(configured)] if configured else []) + [
        field for field in _CHAT_FIELDS if field != configured
    ]
    for field in fields:
        value = body.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def chat_is_allowed(channel: Channel, body: dict[str, Any]) -> bool:
    """Apply the opt-in chat allowlist; absent key preserves legacy behaviour."""
    config = channel.config or {}
    if "allowed_chats" not in config:
        return True
    allowed = config.get("allowed_chats")
    if not isinstance(allowed, (list, tuple, set, frozenset)):
        return False
    if not all(isinstance(value, str) and value.strip() for value in allowed):
        return False
    current = chat_id(channel, body)
    return current is not None and current in {value.strip() for value in allowed}


def _safe_grant_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return None
    if not all(isinstance(entry, str) and entry.strip() for entry in value):
        return None
    return [entry.strip() for entry in value]


def thread_ceiling(channel: Channel, thread_id: str | None) -> GrantSet | None:
    """Resolve an opt-in thread ceiling, failing closed on malformed policy data.

    ``None`` means no ceiling was configured for this thread. A malformed map or
    entry returns an empty grant set, never an accidental wildcard.
    """
    if not thread_id:
        return None
    ceilings = (channel.config or {}).get("thread_ceilings")
    if ceilings is None:
        return None
    if not isinstance(ceilings, dict):
        return GrantSet.of([])
    raw = ceilings.get(thread_id)
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        allow, deny = _safe_grant_list(raw), []
    elif isinstance(raw, dict):
        allow = _safe_grant_list(raw.get("allow"))
        deny = _safe_grant_list(raw.get("deny"))
    else:
        return GrantSet.of([])
    if allow is None or deny is None:
        return GrantSet.of([])
    try:
        return GrantSet.of(allow, deny)
    except (TypeError, ValueError):
        return GrantSet.of([])


def stamp_thread_ceiling(item: WorkItem, thread_id: str | None, ceiling: GrantSet | None) -> None:
    """Stamp the resolved narrowing onto the durable work item.

    The value is descriptive and narrowing-only; ``authority.context_for``
    intersects it again at execution time, so a modified item can never widen
    the principal's grants.
    """
    if ceiling is None:
        return
    item.constraints[_CEILING_KEY] = {
        "thread": thread_id,
        "allow": list(ceiling.allow),
        "deny": list(ceiling.deny),
    }


def ceiling_from_item(item: WorkItem) -> GrantSet | None:
    """Read the intake stamp for the execution-side narrowing."""
    raw = (item.constraints or {}).get(_CEILING_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return GrantSet.of([])
    allow = _safe_grant_list(raw.get("allow"))
    deny = _safe_grant_list(raw.get("deny"))
    if allow is None or deny is None:
        return GrantSet.of([])
    try:
        return GrantSet.of(allow, deny)
    except (TypeError, ValueError):
        return GrantSet.of([])


__all__ = [
    "chat_id",
    "chat_is_allowed",
    "ceiling_from_item",
    "stamp_thread_ceiling",
    "thread_ceiling",
]
