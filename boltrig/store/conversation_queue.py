"""Durable, reorderable queue for conversational steers.

Message content remains frozen in ``conversation_messages``.  This table is the
small mutable scheduling projection: it records only message ids, order, and the
run that claimed an item.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from threading import Lock
from typing import TYPE_CHECKING, cast

import asyncpg  # type: ignore[import-untyped]

from boltrig.models import ConversationMessage

from .rows import _message


_LOCK_PREFIX = "conversation-steer-queue:"


async def _lock_queue(conn: asyncpg.Connection, tenant_id: str, conversation_id: str) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"{_LOCK_PREFIX}{tenant_id}:{conversation_id}",
    )


class ConversationQueueStoreMem:
    if TYPE_CHECKING:
        _conversation_lifecycle_lock: Lock
        _messages: dict[str, list[ConversationMessage]]

    def _init_conversation_queue_state(self) -> None:
        self._steer_queues: dict[tuple[str, str], list[str]] = {}

    async def enqueue_conversation_steer(self, message: ConversationMessage) -> None:
        key = (message.tenant_id, message.conversation_id)
        with self._conversation_lifecycle_lock:
            messages = self._messages.setdefault(message.conversation_id, [])
            if not any(
                item.tenant_id == message.tenant_id and item.id == message.id
                for item in messages
            ):
                messages.append(message)
            queue = self._steer_queues.setdefault(key, [])
            if message.id not in queue:
                queue.append(message.id)

    async def pending_conversation_steer_ids(
        self, tenant_id: str, conversation_id: str
    ) -> list[str]:
        with self._conversation_lifecycle_lock:
            return list(self._steer_queues.get((tenant_id, conversation_id), []))

    async def claim_next_conversation_steer(
        self, tenant_id: str, conversation_id: str, run_id: str
    ) -> ConversationMessage | None:
        del run_id  # Postgres retains this receipt; memory needs only queue parity.
        with self._conversation_lifecycle_lock:
            queue = self._steer_queues.get((tenant_id, conversation_id), [])
            while queue:
                message_id = queue.pop(0)
                message = next(
                    (
                        item
                        for item in self._messages.get(conversation_id, [])
                        if item.tenant_id == tenant_id and item.id == message_id
                    ),
                    None,
                )
                if message is not None:
                    return message
            return None

    async def reorder_conversation_steers(
        self,
        tenant_id: str,
        conversation_id: str,
        expected_message_ids: list[str],
        message_ids: list[str],
    ) -> bool:
        with self._conversation_lifecycle_lock:
            key = (tenant_id, conversation_id)
            current = self._steer_queues.get(key, [])
            if current != expected_message_ids:
                return False
            if len(message_ids) != len(current) or set(message_ids) != set(current):
                return False
            self._steer_queues[key] = list(message_ids)
            return True


class ConversationQueueStorePG:
    if TYPE_CHECKING:
        def with_tenant(
            self, tenant_id: str
        ) -> AbstractAsyncContextManager[asyncpg.Connection]: ...

    async def enqueue_conversation_steer(self, message: ConversationMessage) -> None:
        async with self.with_tenant(message.tenant_id) as conn:
            await _lock_queue(conn, message.tenant_id, message.conversation_id)
            await conn.execute(
                """INSERT INTO conversation_messages
                     (id, conversation_id, tenant_id, role, content, run_id,
                      hitl_request_id, events, attachments, superseded_by, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (tenant_id, id) DO NOTHING""",
                message.id,
                message.conversation_id,
                message.tenant_id,
                message.role.value,
                message.content,
                message.run_id,
                message.hitl_request_id,
                message.events,
                message.attachments,
                message.superseded_by,
                message.created_at,
            )
            next_position = await conn.fetchval(
                """SELECT COALESCE(MAX(queue_position), 0) + 1
                   FROM conversation_steer_queue
                   WHERE tenant_id=$1 AND conversation_id=$2""",
                message.tenant_id,
                message.conversation_id,
            )
            await conn.execute(
                """INSERT INTO conversation_steer_queue
                     (tenant_id, conversation_id, message_id, queue_position, enqueued_at)
                   SELECT $1,$2,$3,$4,$5
                   WHERE EXISTS (
                     SELECT 1 FROM conversation_messages
                     WHERE tenant_id=$1 AND conversation_id=$2 AND id=$3
                       AND role='user' AND run_id IS NULL
                   )
                   ON CONFLICT (tenant_id, message_id) DO NOTHING""",
                message.tenant_id,
                message.conversation_id,
                message.id,
                next_position,
                message.created_at,
            )

    async def pending_conversation_steer_ids(
        self, tenant_id: str, conversation_id: str
    ) -> list[str]:
        async with self.with_tenant(tenant_id) as conn:
            rows = await conn.fetch(
                """SELECT message_id FROM conversation_steer_queue
                   WHERE tenant_id=$1 AND conversation_id=$2 AND claimed_run_id IS NULL
                   ORDER BY queue_position, enqueued_at, message_id""",
                tenant_id,
                conversation_id,
            )
        return [row["message_id"] for row in rows]

    async def claim_next_conversation_steer(
        self, tenant_id: str, conversation_id: str, run_id: str
    ) -> ConversationMessage | None:
        async with self.with_tenant(tenant_id) as conn:
            await _lock_queue(conn, tenant_id, conversation_id)
            row = await conn.fetchrow(
                """WITH next_item AS (
                     SELECT message_id FROM conversation_steer_queue
                     WHERE tenant_id=$1 AND conversation_id=$2
                       AND claimed_run_id IS NULL
                     ORDER BY queue_position, enqueued_at, message_id
                     LIMIT 1 FOR UPDATE
                   ), claimed AS (
                     UPDATE conversation_steer_queue AS queue
                     SET claimed_run_id=$3, claimed_at=now()
                     FROM next_item
                     WHERE queue.tenant_id=$1 AND queue.message_id=next_item.message_id
                     RETURNING queue.message_id
                   )
                   SELECT message.* FROM conversation_messages AS message
                   JOIN claimed ON claimed.message_id=message.id
                   WHERE message.tenant_id=$1 AND message.conversation_id=$2""",
                tenant_id,
                conversation_id,
                run_id,
            )
        return cast(
            ConversationMessage | None,
            _message(row),  # type: ignore[no-untyped-call]
        )

    async def reorder_conversation_steers(
        self,
        tenant_id: str,
        conversation_id: str,
        expected_message_ids: list[str],
        message_ids: list[str],
    ) -> bool:
        async with self.with_tenant(tenant_id) as conn:
            await _lock_queue(conn, tenant_id, conversation_id)
            rows = await conn.fetch(
                """SELECT message_id FROM conversation_steer_queue
                   WHERE tenant_id=$1 AND conversation_id=$2 AND claimed_run_id IS NULL
                   ORDER BY queue_position, enqueued_at, message_id
                   FOR UPDATE""",
                tenant_id,
                conversation_id,
            )
            current = [row["message_id"] for row in rows]
            if current != expected_message_ids:
                return False
            if len(message_ids) != len(current) or set(message_ids) != set(current):
                return False
            for position, message_id in enumerate(message_ids, start=1):
                await conn.execute(
                    """UPDATE conversation_steer_queue SET queue_position=$4
                       WHERE tenant_id=$1 AND conversation_id=$2 AND message_id=$3
                         AND claimed_run_id IS NULL""",
                    tenant_id,
                    conversation_id,
                    message_id,
                    position,
                )
            return True


__all__ = ["ConversationQueueStoreMem", "ConversationQueueStorePG"]
