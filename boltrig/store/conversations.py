"""Conversations store domain (arc-1 structural partial).

Conversation listing/search/restore, messages, summaries and closed-conversation
purge - extracted verbatim from ``store/postgres.py`` + ``store/memory.py``.
``PostgresStore`` mixes in :class:`ConversationsStorePG`; ``InMemoryStore``
mixes in :class:`ConversationsStoreMem`. Public surface unchanged.
(conversation lifecycle WRITES live in ``store/conversation_binding_*.py``;
queue/steer state in ``store/conversation_queue.py``.)

Host contract: PG uses ``self._pool``; Mem uses ``self._convs`` /
``self._messages`` / ``self._summaries`` / ``self._conversation_agent_bindings``
/ ``self._steer_queues`` / ``self._conversation_lifecycle_lock``.
"""

from __future__ import annotations

from boltrig.models import (
    ConversationMessage,
    ConversationStatus,
    ConversationSummary,
)

from .rls_pool import _apply_guc
from .rows import _conversation, _message, _summary
from .tenant_scope import pool_assumes_app_role


def _like_escape(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so a user query is a pure substring match
    (US-CONV-10). Paired with ``ESCAPE '\\'`` in the SQL: a literal backslash,
    percent or underscore in the query is neutralised, so a caller can never turn a
    search term into a wildcard. This is substring hygiene; injection is already
    foreclosed because the value is a bound parameter, never interpolated."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConversationsStorePG:
    """Conversation list/search/messages/summaries/purge for ``PostgresStore``."""

    async def list_conversations(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM conversations WHERE tenant_id=$1 AND user_id=$2
               ORDER BY updated_at DESC, id ASC""",
            tenant_id, user_id,
        )
        return [_conversation(r) for r in rows]

    async def list_conversations_page(self, tenant_id, user_id, *, limit, offset=0):
        # Owner scope (SEC-25) + stable ordering (updated_at DESC, id ASC tiebreak),
        # bounded by the resolved page size. Fetch limit+1 to learn whether a next
        # page exists without a second COUNT query; parameterised throughout.
        off = max(0, offset)
        rows = await self._pool.fetch(
            """SELECT * FROM conversations WHERE tenant_id=$1 AND user_id=$2
               ORDER BY updated_at DESC, id ASC
               LIMIT $3 OFFSET $4""",
            tenant_id, user_id, limit + 1, off,
        )
        has_more = len(rows) > limit
        items = [_conversation(r) for r in rows[:limit]]
        return items, (off + limit if has_more else None)

    async def search_conversations(self, tenant_id, user_id, query, *, limit, offset=0):
        # Owner-scoped substring search (US-CONV-10): the WHERE pins the caller's own
        # (tenant, user) rows, so another user's thread can never surface. A
        # conversation matches on its title OR a LIVE (superseded_by IS NULL,
        # [2026] VJS-COUNTY 4) message's content, so a superseded turn is never a live
        # hit. ``query`` is a BOUND parameter with LIKE metacharacters escaped (see
        # ``_like_escape`` + ESCAPE), so there is no SQL-injection or wildcard surface.
        # The snippet is the matched live message content, or NULL when only the title
        # matched (mirrors the in-memory store). Fetch limit+1 for the next offset.
        off = max(0, offset)
        pattern = f"%{_like_escape(query or '')}%"
        rows = await self._pool.fetch(
            r"""SELECT c.*,
                       CASE WHEN c.title ILIKE $3 ESCAPE '\' THEN NULL ELSE (
                         SELECT m.content FROM conversation_messages m
                          WHERE m.tenant_id = c.tenant_id AND m.conversation_id = c.id
                            AND m.superseded_by IS NULL
                            AND m.content ILIKE $3 ESCAPE '\'
                          ORDER BY m.created_at ASC
                          LIMIT 1
                       ) END AS matched_snippet
                  FROM conversations c
                 WHERE c.tenant_id = $1 AND c.user_id = $2
                   AND (
                         c.title ILIKE $3 ESCAPE '\'
                         OR EXISTS (
                              SELECT 1 FROM conversation_messages m
                               WHERE m.tenant_id = c.tenant_id
                                 AND m.conversation_id = c.id
                                 AND m.superseded_by IS NULL
                                 AND m.content ILIKE $3 ESCAPE '\'
                            )
                       )
                 ORDER BY c.updated_at DESC, c.id ASC
                 LIMIT $4 OFFSET $5""",
            tenant_id, user_id, pattern, limit + 1, off,
        )
        has_more = len(rows) > limit
        out = [(_conversation(r), r["matched_snippet"]) for r in rows[:limit]]
        return out, (off + limit if has_more else None)

    async def restore_closed_conversation(
        self, tenant_id, conv_id, user_id, restored_at
    ):
        # The target CTE locks the lifecycle row, and the conditional UPDATE is in
        # the same statement. This returns honest found/owned/changed semantics
        # without a read-then-write window in which retention could delete it.
        row = await self._pool.fetchrow(
            """WITH target AS MATERIALIZED (
                   SELECT tenant_id, id, user_id, status
                     FROM conversations
                    WHERE tenant_id=$1 AND id=$2
                      FOR UPDATE
               ),
               updated AS (
                   UPDATE conversations AS c
                      SET status=$4, updated_at=$5
                     FROM target AS t
                    WHERE c.tenant_id=t.tenant_id AND c.id=t.id
                      AND t.user_id=$3 AND t.status=$6
                   RETURNING 1
               )
               SELECT EXISTS(SELECT 1 FROM target) AS found,
                      COALESCE((SELECT user_id=$3 FROM target), FALSE) AS owned,
                      EXISTS(SELECT 1 FROM updated) AS changed""",
            tenant_id,
            conv_id,
            user_id,
            ConversationStatus.ACTIVE.value,
            restored_at,
            ConversationStatus.CLOSED.value,
        )
        return bool(row["found"]), bool(row["owned"]), bool(row["changed"])

    async def add_message(self, m: ConversationMessage):
        await self._pool.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, tenant_id, role, content, run_id, recipient_agent_address, author_agent_address, hitl_request_id, events, attachments, superseded_by, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            m.id, m.conversation_id, m.tenant_id, m.role.value, m.content, m.run_id,
            m.recipient_agent_address, m.author_agent_address, m.hitl_request_id,
            m.events, m.attachments, m.superseded_by, m.created_at,
        )

    async def list_messages(self, tenant_id, conv_id):
        rows = await self._pool.fetch(
            """SELECT * FROM conversation_messages WHERE tenant_id=$1 AND conversation_id=$2
               ORDER BY created_at ASC""",
            tenant_id, conv_id,
        )
        return [_message(r) for r in rows]

    async def mark_message_superseded(self, tenant_id, message_id, superseded_by):
        # Marker-only ([2026] VJS-COUNTY 4, D3): the UPDATE touches superseded_by and
        # NOTHING else, so content/events/run_id/created_at are frozen. Tenant-scoped.
        await self._pool.execute(
            """UPDATE conversation_messages SET superseded_by=$3
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, message_id, superseded_by,
        )

    async def add_conversation_summary(self, s: ConversationSummary):
        # Append-only ([2026] VJS-COUNTY 4 keeps message content frozen): a summary
        # is DERIVED data INSERTED here; it never mutates a conversation_messages
        # row. A re-compaction appends a new row, so ON CONFLICT DO NOTHING keeps
        # the insert idempotent without ever overwriting.
        await self._pool.execute(
            """INSERT INTO conversation_summaries
               (id, conversation_id, tenant_id, up_to_message_id, covered_count,
                summary, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            s.id, s.conversation_id, s.tenant_id, s.up_to_message_id,
            s.covered_count, s.summary, s.created_at,
        )

    async def get_latest_conversation_summary(self, tenant_id, conversation_id):
        # The latest summary covers the most messages (widest boundary); break ties
        # by created_at so a re-compaction's fresh row wins.
        row = await self._pool.fetchrow(
            """SELECT * FROM conversation_summaries
               WHERE tenant_id=$1 AND conversation_id=$2
               ORDER BY covered_count DESC, created_at DESC
               LIMIT 1""",
            tenant_id, conversation_id,
        )
        return _summary(row)

    async def purge_closed_conversations(self, tenant_id, older_than):
        # M11 / SEC-74 right-to-erasure: HARD-DELETE CLOSED conversations past the
        # cutoff (updated_at is the close timestamp - the soft-close stamps it) and
        # their conversation_messages + derived conversation_summaries. Neither
        # child table carries an FK to conversations, so the child rows are deleted
        # explicitly first. The audit log is EXEMPT and never touched here (erasing
        # the SEC-16 hash chain would break tamper-evidence). Tenant-scoped (SEC-08).
        # One atomic transaction: a crash mid-purge cannot strand a conversation
        # whose messages/summaries are already erased.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
                rows = await conn.fetch(
                    """SELECT id FROM conversations
                       WHERE tenant_id=$1 AND status=$2 AND updated_at <= $3
                       FOR UPDATE""",
                    tenant_id, ConversationStatus.CLOSED.value, older_than,
                )
                conv_ids = [r["id"] for r in rows]
                if not conv_ids:
                    return 0
                await conn.execute(
                    """DELETE FROM conversation_messages
                       WHERE tenant_id=$1 AND conversation_id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                await conn.execute(
                    """DELETE FROM conversation_summaries
                       WHERE tenant_id=$1 AND conversation_id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                await conn.execute(
                    """DELETE FROM conversations WHERE tenant_id=$1 AND id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                return len(conv_ids)


class ConversationsStoreMem:
    """Conversation list/search/messages/summaries/purge for ``InMemoryStore``."""

    async def list_conversations(self, tenant_id, user_id):
        return self._owned_conversations(tenant_id, user_id)

    def _owned_conversations(self, tenant_id, user_id):
        # Owner scope (SEC-25) + stable ordering: updated_at DESC with an id ASC
        # tiebreak. Python's sort is stable, so sorting by id first then by
        # updated_at (reverse) leaves ties ordered by ascending id deterministically.
        out = [c for (t, _), c in self._convs.items() if t == tenant_id and c.user_id == user_id]
        out.sort(key=lambda c: c.id)
        out.sort(key=lambda c: c.updated_at, reverse=True)
        return out

    @staticmethod
    def _page(rows, limit, offset):
        # A stable window over an already-ordered list: the slice plus the next
        # offset (None once the list is exhausted). Mirrors the postgres LIMIT/OFFSET.
        start = max(0, offset)
        window = rows[start : start + limit]
        nxt = start + limit if start + limit < len(rows) else None
        return window, nxt

    async def list_conversations_page(self, tenant_id, user_id, *, limit, offset=0):
        return self._page(self._owned_conversations(tenant_id, user_id), limit, offset)

    async def search_conversations(self, tenant_id, user_id, query, *, limit, offset=0):
        # Owner-scoped substring search (US-CONV-10): only the caller's own
        # conversations are ever considered, so another user's thread can never
        # surface. A conversation matches on its title OR any LIVE (non-superseded,
        # [2026] VJS-COUNTY 4) message content; the snippet is the matched live
        # message content, or None when only the title matched.
        needle = (query or "").casefold()
        matches: list[tuple] = []
        for conv in self._owned_conversations(tenant_id, user_id):
            snippet = None
            # An empty needle still requires a non-NULL title (mirrors the PG
            # ILIKE '%%' semantics: a NULL title never matches, it can only
            # surface via a live message-content hit below).
            if conv.title is not None and needle in conv.title.casefold():
                matches.append((conv, None))
                continue
            for m in self._messages.get(conv.id, []):
                if (
                    m.tenant_id == tenant_id
                    and m.superseded_by is None  # a superseded turn is never a live hit
                    and m.content
                    and needle in m.content.casefold()
                ):
                    snippet = m.content
                    break
            if snippet is not None:
                matches.append((conv, snippet))
        return self._page(matches, limit, offset)

    async def restore_closed_conversation(self, tenant_id, conv_id, user_id, restored_at):
        # One critical section decides existence, ownership, and CLOSED -> ACTIVE.
        # `restore_closed_conversation` never upserts; a concurrent purge stays final.
        with self._conversation_lifecycle_lock:
            conv = self._convs.get((tenant_id, conv_id))
            if conv is None:
                return False, False, False
            if conv.user_id != user_id:
                return True, False, False
            if conv.status != ConversationStatus.CLOSED:
                return True, True, False
            conv.status = ConversationStatus.ACTIVE
            conv.updated_at = restored_at
            return True, True, True

    async def add_message(self, message):
        # Insert-if-absent on (tenant_id, id) (mirrors the PG ON CONFLICT DO
        # NOTHING): a replayed message id is a no-op, never a duplicate row.
        msgs = self._messages.setdefault(message.conversation_id, [])
        if not any(m.tenant_id == message.tenant_id and m.id == message.id for m in msgs):
            msgs.append(message)

    async def list_messages(self, tenant_id, conv_id):
        return [m for m in self._messages.get(conv_id, []) if m.tenant_id == tenant_id]

    async def mark_message_superseded(self, tenant_id, message_id, superseded_by):
        # Marker-only ([2026] VJS-COUNTY 4, D3): set superseded_by and NOTHING else,
        # so content/events/run_id/created_at stay immutable. Tenant-scoped.
        for msgs in self._messages.values():
            for m in msgs:
                if m.tenant_id == tenant_id and m.id == message_id:
                    m.superseded_by = superseded_by
                    return

    async def add_conversation_summary(self, summary):
        # Append-only ([2026] VJS-COUNTY 4 keeps message content frozen): a summary
        # is derived data, INSERTED here and never mutating any message row.
        self._summaries.setdefault(summary.conversation_id, []).append(summary)

    async def get_latest_conversation_summary(self, tenant_id, conversation_id):
        rows = [s for s in self._summaries.get(conversation_id, []) if s.tenant_id == tenant_id]
        if not rows:
            return None
        # The latest summary covers the most messages (widest boundary); break ties
        # by created_at so a re-compaction's fresh row wins.
        return max(rows, key=lambda s: (s.covered_count, s.created_at))

    async def purge_closed_conversations(self, tenant_id, older_than):
        # M11 / SEC-74: hard-erase CLOSED conversations past the cutoff plus their
        # messages AND their derived summaries; audit rows are elsewhere and never
        # touched. Tenant-scoped.
        with self._conversation_lifecycle_lock:
            doomed = [
                c
                for (t, _), c in self._convs.items()
                if t == tenant_id
                and c.status == ConversationStatus.CLOSED
                and c.updated_at <= older_than
            ]
            for conv in doomed:
                self._convs.pop((conv.tenant_id, conv.id), None)
                self._conversation_agent_bindings.pop((conv.tenant_id, conv.id), None)
                self._messages.pop(conv.id, None)
                self._summaries.pop(conv.id, None)
                self._steer_queues.pop((conv.tenant_id, conv.id), None)
            return len(doomed)
