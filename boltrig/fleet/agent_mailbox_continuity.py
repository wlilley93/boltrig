"""Bounded logical-session continuity and deterministic compaction."""

from __future__ import annotations

import hashlib

from boltrig.models import AgentMessage, AgentSession, AgentSessionSummary
from boltrig.text_envelope import wrap_untrusted

DEFAULT_AGENT_COMPACTION_THRESHOLD = 40
DEFAULT_AGENT_COMPACTION_KEEP_RECENT = 12
MAX_AGENT_SUMMARY_BYTES = 16 * 1024


def digest_id(prefix: str, *parts: object, size: int = 32) -> str:
    material = "\0".join(str(part) for part in parts)
    return prefix + hashlib.sha256(material.encode("utf-8")).hexdigest()[:size]


def agent_session_id(tenant_id: str, address: str, conversation_id: str) -> str:
    return digest_id("as_", tenant_id, address, conversation_id)


def _bounded_summary(value: str) -> str:
    """Keep the oldest frame and newest facts when a derived summary is full."""
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_AGENT_SUMMARY_BYTES:
        return value
    marker = "\n[older summary elided]\n"
    marker_bytes = marker.encode("utf-8")
    available = MAX_AGENT_SUMMARY_BYTES - len(marker_bytes)
    head = available // 2
    tail = available - head
    return (
        encoded[:head].decode("utf-8", errors="ignore")
        + marker
        + encoded[-tail:].decode("utf-8", errors="ignore")
    )


def _message_block(position: int, message: AgentMessage) -> str:
    return "\n".join(
        (
            f"Message {position} ({message.kind.value}) "
            f"{message.sender} -> {message.recipient}:",
            wrap_untrusted("agent_message", message.sender, message.content),
        )
    )


def _through_current(
    messages: list[AgentMessage], current: AgentMessage
) -> list[AgentMessage]:
    """Return history only through this serialized turn, never later queued work."""
    for index, message in enumerate(messages):
        if message.id == current.id:
            return messages[: index + 1]
    raise RuntimeError("claimed agent message is absent from its conversation")


class AgentMailboxContinuity:
    """Mixin supplying summary-plus-tail continuity to a mailbox service."""

    async def _continuity(self, message: AgentMessage) -> str:
        session = await self._store.ensure_agent_session(
            AgentSession(
                id=agent_session_id(
                    message.tenant_id, message.recipient, message.conversation_id
                ),
                tenant_id=message.tenant_id,
                agent_address=message.recipient,
                conversation_id=message.conversation_id,
            )
        )
        messages = _through_current(
            await self._store.list_agent_conversation_messages(
                message.tenant_id, message.conversation_id, limit=None
            ),
            message,
        )
        summary = await self._store.get_latest_agent_session_summary(
            message.tenant_id, session.id
        )
        covered = min(summary.covered_count, len(messages)) if summary else 0
        blocks: list[str] = []
        if summary is not None:
            blocks.extend(
                (
                    f"Derived summary of messages 1-{covered}:",
                    wrap_untrusted(
                        "agent_session_summary", message.recipient, summary.summary
                    ),
                )
            )
        blocks.extend(
            _message_block(index, row)
            for index, row in enumerate(messages[covered:], start=covered + 1)
        )
        return "\n\n".join(blocks)

    async def _compact(self, message: AgentMessage) -> None:
        if not self.compaction_threshold:
            return
        messages = _through_current(
            await self._store.list_agent_conversation_messages(
                message.tenant_id, message.conversation_id, limit=None
            ),
            message,
        )
        if len(messages) < self.compaction_threshold:
            return
        covered_count = len(messages) - self.keep_recent
        if covered_count <= 0:
            return
        session = await self._store.ensure_agent_session(
            AgentSession(
                id=agent_session_id(
                    message.tenant_id, message.recipient, message.conversation_id
                ),
                tenant_id=message.tenant_id,
                agent_address=message.recipient,
                conversation_id=message.conversation_id,
            )
        )
        current = await self._store.get_latest_agent_session_summary(
            message.tenant_id, session.id
        )
        if current is not None and current.covered_count >= covered_count:
            return
        boundary = messages[covered_count - 1]
        lines = [current.summary] if current is not None else []
        lines.extend(
            f"{row.sender} -> {row.recipient} [{row.kind.value}]: "
            f"{row.content.replace(chr(10), ' ')[:240]}"
            for row in messages[
                current.covered_count if current is not None else 0 : covered_count
            ]
        )
        await self._store.add_agent_session_summary(
            AgentSessionSummary(
                id=digest_id(
                    "ass_", message.tenant_id, session.id, boundary.id, covered_count
                ),
                tenant_id=message.tenant_id,
                session_id=session.id,
                up_to_message_id=boundary.id,
                covered_count=covered_count,
                summary=_bounded_summary("\n".join(lines)),
            )
        )
