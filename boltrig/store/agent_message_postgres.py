"""PostgreSQL immutable named-agent messages and logical sessions."""

from __future__ import annotations

from .agent_mailbox_rows import (
    agent_message_from_row,
    agent_session_from_row,
    agent_summary_from_row,
)
from .tenant_scope import bind_conn_to_tenant

MESSAGE_COLUMNS = """
    m.id, m.tenant_id, m.conversation_id, m.sender, m.recipient,
    m.kind, m.content, m.reply_to, m.correlation_id, m.run_id,
    m.authority, m.created_at
"""


async def insert_agent_message(conn, message) -> bool:
    endpoint_count = await conn.fetchval(
        """SELECT COUNT(*) FROM named_agents
           WHERE tenant_id=$1 AND address=ANY($2::text[])""",
        message.tenant_id,
        [message.sender, message.recipient],
    )
    if endpoint_count != 2:
        raise ValueError("agent message endpoints must be registered named agents")
    row = await conn.fetchrow(
        """INSERT INTO agent_messages
             (id, tenant_id, conversation_id, sender, recipient, kind, content,
              reply_to, correlation_id, run_id, authority, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
           ON CONFLICT (tenant_id, id) DO NOTHING RETURNING id""",
        message.id,
        message.tenant_id,
        message.conversation_id,
        message.sender,
        message.recipient,
        message.kind.value,
        message.content,
        message.reply_to,
        message.correlation_id,
        message.run_id,
        message.authority,
        message.created_at,
    )
    if row is None:
        return False
    await conn.execute(
        """INSERT INTO agent_message_deliveries
             (tenant_id, message_id, recipient, status, attempts, updated_at)
           VALUES ($1,$2,$3,'pending',0,now())""",
        message.tenant_id,
        message.id,
        message.recipient,
    )
    return True


class AgentMessageStorePG:
    async def ensure_agent_session(self, session):
        row = await self._pool.fetchrow(
            """INSERT INTO agent_sessions
                 (id,tenant_id,agent_address,conversation_id,created_at,updated_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id,agent_address,conversation_id) DO UPDATE SET
                 updated_at=GREATEST(agent_sessions.updated_at,EXCLUDED.updated_at)
               RETURNING *""",
            session.id,
            session.tenant_id,
            session.agent_address,
            session.conversation_id,
            session.created_at,
            session.updated_at,
        )
        return agent_session_from_row(row)

    async def get_agent_session(self, tenant_id, agent_address, conversation_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM agent_sessions
               WHERE tenant_id=$1 AND agent_address=$2 AND conversation_id=$3""",
            tenant_id,
            agent_address,
            conversation_id,
        )
        return agent_session_from_row(row)

    async def enqueue_agent_message(self, message):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, message.tenant_id, pool=self._pool)
                return await insert_agent_message(conn, message)

    async def get_agent_message(self, tenant_id, message_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM agent_messages WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            message_id,
        )
        return agent_message_from_row(row)

    async def list_agent_conversation_messages(
        self, tenant_id, conversation_id, *, limit=500
    ):
        if limit is None:
            rows = await self._pool.fetch(
                """SELECT * FROM agent_messages
                   WHERE tenant_id=$1 AND conversation_id=$2
                   ORDER BY created_at,id""",
                tenant_id,
                conversation_id,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM agent_messages
                   WHERE tenant_id=$1 AND conversation_id=$2
                   ORDER BY created_at,id LIMIT $3""",
                tenant_id,
                conversation_id,
                max(1, min(int(limit), 1000)),
            )
        return [agent_message_from_row(row) for row in rows]

    async def list_agent_inbox(self, tenant_id, recipient, *, limit=100):
        rows = await self._pool.fetch(
            """SELECT m.*,d.status AS delivery_status
                 FROM agent_messages m
                 JOIN agent_message_deliveries d
                   ON d.tenant_id=m.tenant_id AND d.message_id=m.id
                WHERE m.tenant_id=$1 AND m.recipient=$2
                ORDER BY m.created_at DESC,m.id DESC LIMIT $3""",
            tenant_id,
            recipient,
            max(1, min(int(limit), 500)),
        )
        return [(agent_message_from_row(row), row["delivery_status"]) for row in rows]

    async def add_agent_session_summary(self, summary):
        await self._pool.execute(
            """INSERT INTO agent_session_summaries
                 (id,tenant_id,session_id,up_to_message_id,covered_count,summary,created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id,id) DO NOTHING""",
            summary.id,
            summary.tenant_id,
            summary.session_id,
            summary.up_to_message_id,
            summary.covered_count,
            summary.summary,
            summary.created_at,
        )

    async def get_latest_agent_session_summary(self, tenant_id, session_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM agent_session_summaries
               WHERE tenant_id=$1 AND session_id=$2
               ORDER BY covered_count DESC,created_at DESC LIMIT 1""",
            tenant_id,
            session_id,
        )
        return agent_summary_from_row(row)
