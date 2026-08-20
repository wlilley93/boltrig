"""Atomic PostgreSQL claim path for one durable peer message."""

from __future__ import annotations

import uuid

from boltrig.models import ClaimedAgentMessage

from .agent_mailbox_rows import (
    agent_delivery_from_row,
    agent_message_from_row,
    agent_turn_lease_from_row,
)
from .agent_message_postgres import MESSAGE_COLUMNS
from .tenant_scope import bind_conn_to_tenant


async def _expire_deliveries(conn, tenant_id, max_attempts) -> None:
    await conn.execute(
        """UPDATE agent_message_deliveries d
              SET status='failed',lease_owner=NULL,lease_expires_at=NULL,
                  last_error='named_agent_recipient_disabled',updated_at=now()
             FROM named_agents a
            WHERE d.tenant_id=$1 AND a.tenant_id=d.tenant_id
              AND a.address=d.recipient AND NOT a.enabled
              AND (d.status='pending' OR
                   (d.status='in_flight' AND d.lease_expires_at<=now()))""",
        tenant_id,
    )
    await conn.execute(
        """UPDATE agent_message_deliveries
              SET status='failed',lease_owner=NULL,lease_expires_at=NULL,
                  last_error='delivery_attempts_exhausted',updated_at=now()
            WHERE tenant_id=$1 AND status='in_flight'
              AND lease_expires_at<=now() AND attempts >= $2""",
        tenant_id,
        max_attempts,
    )


async def _select_mailbox(conn, tenant_id, max_attempts):
    return await conn.fetchrow(
        """SELECT l.agent_address
             FROM agent_turn_leases l
            WHERE l.tenant_id=$1
              AND (l.lease_expires_at IS NULL OR l.lease_expires_at<=now())
              AND NOT EXISTS (
                SELECT 1 FROM agent_turn_waiters w
                 WHERE w.tenant_id=l.tenant_id
                   AND w.agent_address=l.agent_address
                   AND w.lane='interactive' AND w.expires_at>now()
              )
              AND EXISTS (
                SELECT 1
                  FROM agent_message_deliveries d
                  JOIN agent_messages m
                    ON m.tenant_id=d.tenant_id AND m.id=d.message_id
                  JOIN named_agents a
                    ON a.tenant_id=m.tenant_id AND a.address=m.recipient
                 WHERE d.tenant_id=l.tenant_id
                   AND d.recipient=l.agent_address AND a.enabled
                   AND d.attempts < $2
                   AND ((d.status='pending' AND
                         (d.available_at IS NULL OR d.available_at<=now()))
                        OR (d.status='in_flight' AND d.lease_expires_at<=now()))
              )
            ORDER BY (
              SELECT MIN(m.created_at)
                FROM agent_message_deliveries d
                JOIN agent_messages m
                  ON m.tenant_id=d.tenant_id AND m.id=d.message_id
               WHERE d.tenant_id=l.tenant_id
                 AND d.recipient=l.agent_address
                 AND d.attempts < $2
                 AND ((d.status='pending' AND
                       (d.available_at IS NULL OR d.available_at<=now()))
                      OR (d.status='in_flight' AND d.lease_expires_at<=now()))
            ),l.agent_address
            FOR UPDATE SKIP LOCKED LIMIT 1""",
        tenant_id,
        max_attempts,
    )


async def _lease_mailbox(conn, tenant_id, recipient, worker_id, token, lease_seconds):
    return await conn.fetchrow(
        """UPDATE agent_turn_leases
              SET lease_owner=$3,lease_token=$4,lane='peer',
                  lease_expires_at=now()+make_interval(secs=>$5),updated_at=now()
            WHERE tenant_id=$1 AND agent_address=$2 RETURNING *""",
        tenant_id,
        recipient,
        worker_id,
        token,
        float(max(1, lease_seconds)),
    )


async def _oldest_message(conn, tenant_id, recipient, max_attempts):
    return await conn.fetchrow(
        f"""SELECT {MESSAGE_COLUMNS}
              FROM agent_messages m
              JOIN agent_message_deliveries d
                ON d.tenant_id=m.tenant_id AND d.message_id=m.id
             WHERE d.tenant_id=$1 AND d.recipient=$2 AND d.attempts < $3
               AND ((d.status='pending' AND
                     (d.available_at IS NULL OR d.available_at<=now()))
                    OR (d.status='in_flight' AND d.lease_expires_at<=now()))
             ORDER BY m.created_at,m.id
             FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
        tenant_id,
        recipient,
        max_attempts,
    )


async def _release_mailbox(conn, tenant_id, recipient, worker_id, token) -> None:
    await conn.execute(
        """UPDATE agent_turn_leases
              SET lease_owner=NULL,lease_token=NULL,lane=NULL,
                  lease_expires_at=NULL,updated_at=now()
            WHERE tenant_id=$1 AND agent_address=$2
              AND lease_owner=$3 AND lease_token=$4""",
        tenant_id,
        recipient,
        worker_id,
        token,
    )


async def _mark_message_claimed(
    conn, tenant_id, message_id, worker_id, lease_seconds
):
    return await conn.fetchrow(
        """UPDATE agent_message_deliveries
              SET status='in_flight',attempts=attempts+1,lease_owner=$3,
                  lease_expires_at=now()+make_interval(secs=>$4),
                  available_at=NULL,updated_at=now()
            WHERE tenant_id=$1 AND message_id=$2 RETURNING *""",
        tenant_id,
        message_id,
        worker_id,
        float(max(1, lease_seconds)),
    )


class AgentDeliveryClaimStorePG:
    async def claim_next_agent_message(
        self, tenant_id, worker_id, lease_seconds, *, max_attempts=3
    ):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                await conn.execute(
                    "DELETE FROM agent_turn_waiters WHERE tenant_id=$1 AND expires_at<=now()",
                    tenant_id,
                )
                await _expire_deliveries(conn, tenant_id, max_attempts)
                mailbox = await _select_mailbox(conn, tenant_id, max_attempts)
                if mailbox is None:
                    return None
                recipient = mailbox["agent_address"]
                token = f"atl_{uuid.uuid4().hex}"
                turn_row = await _lease_mailbox(
                    conn, tenant_id, recipient, worker_id, token, lease_seconds
                )
                message_row = await _oldest_message(
                    conn, tenant_id, recipient, max_attempts
                )
                if message_row is None:
                    await _release_mailbox(
                        conn, tenant_id, recipient, worker_id, token
                    )
                    return None
                delivery_row = await _mark_message_claimed(
                    conn, tenant_id, message_row["id"], worker_id, lease_seconds
                )
                message = agent_message_from_row(message_row)
                delivery = agent_delivery_from_row(delivery_row)
                turn_lease = agent_turn_lease_from_row(turn_row)
                assert message is not None and delivery is not None and turn_lease is not None
                return ClaimedAgentMessage(message, delivery, turn_lease)
