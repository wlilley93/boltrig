"""Runtime resolution of a verified channel message's destination and reply path."""

from __future__ import annotations

import re

from boltrig.config.channel_addressing import effective_intake_target

UNASSIGNED_TARGET = "system:unassigned"
_TARGET_FIELDS = ("chat", "thread", "channel", "chat_id", "thread_id")


def _clean_target(value) -> str | None:
    """Return a short routing slug, or no usable target."""

    slug = str(value or "").strip()
    return slug if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", slug) else None


async def resolve_channel_addressing(kernel, channel, body: dict) -> tuple[str, dict]:
    """Resolve one target and the exact route back to the accepted surface."""

    addressing = (channel.config or {}).get("addressing") or {}
    thread_field = addressing.get("thread_field")
    thread_id = ""
    fields = ([thread_field] if thread_field else []) + [
        field for field in _TARGET_FIELDS if field != thread_field
    ]
    for field_name in fields:
        value = body.get(field_name)
        if value is not None and str(value).strip():
            thread_id = str(value).strip()
            break
    target = _clean_target(body.get("target"))
    if target is None and thread_id:
        target = _clean_target((addressing.get("routes") or {}).get(thread_id))
    if target is None:
        target = _clean_target(addressing.get("default_target"))
    if target is None:
        target = await effective_intake_target(kernel.store, channel.tenant_id)
    reply_route = {
        "channel_id": channel.id,
        "thread": thread_id or None,
        "sender": None,
    }
    return target or UNASSIGNED_TARGET, reply_route


__all__ = ["UNASSIGNED_TARGET", "_clean_target", "resolve_channel_addressing"]
