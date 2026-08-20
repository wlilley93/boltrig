"""Fenced completion, retry, and heartbeat for PostgreSQL peer delivery."""

from __future__ import annotations

from .agent_mailbox_rows import agent_turn_lease_from_row
from .agent_message_postgres import insert_agent_message
from .tenant_scope import bind_conn_to_tenant


class AgentDeliverySettleStorePG:
    async def complete_agent_message(
        self,
        tenant_id,
        message_id,
        turn_lease,
        *,
        reply=None,
        completed_at=None,
    ):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                message = await conn.fetchrow(
                    """SELECT m.*
                         FROM agent_messages m
                         JOIN agent_message_deliveries d
                           ON d.tenant_id=m.tenant_id AND d.message_id=m.id
                         JOIN agent_turn_leases l
                           ON l.tenant_id=d.tenant_id AND l.agent_address=d.recipient
                        WHERE d.tenant_id=$1 AND d.message_id=$2
                          AND d.status='in_flight' AND d.lease_owner=$3
                          AND d.lease_expires_at>now()
                          AND l.lease_owner=$3 AND l.lease_token=$4
                          AND l.lane='peer' AND l.lease_expires_at>now()
                        FOR UPDATE OF d,l""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    turn_lease.token,
                )
                if message is None:
                    return False
                if reply is not None:
                    if (
                        reply.tenant_id != tenant_id
                        or reply.reply_to != message_id
                        or reply.sender != message["recipient"]
                        or reply.recipient != message["sender"]
                        or reply.conversation_id != message["conversation_id"]
                    ):
                        raise ValueError("agent reply does not match the claimed message")
                    await insert_agent_message(conn, reply)
                await conn.execute(
                    """UPDATE agent_message_deliveries
                          SET status='delivered',lease_owner=NULL,lease_expires_at=NULL,
                              last_error=NULL,delivered_at=COALESCE($4,now()),updated_at=now()
                        WHERE tenant_id=$1 AND message_id=$2
                          AND status='in_flight' AND lease_owner=$3""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    completed_at,
                )
                await conn.execute(
                    """UPDATE agent_sessions SET updated_at=now()
                        WHERE tenant_id=$1 AND agent_address=$2 AND conversation_id=$3""",
                    tenant_id,
                    message["recipient"],
                    message["conversation_id"],
                )
                await self._release_delivery_turn(
                    conn, tenant_id, message["recipient"], turn_lease
                )
                return True

    async def fail_agent_message(
        self,
        tenant_id,
        message_id,
        turn_lease,
        error_code,
        *,
        retryable,
        max_attempts=3,
        backoff_seconds=2.0,
    ):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                row = await conn.fetchrow(
                    """SELECT d.recipient
                         FROM agent_message_deliveries d
                         JOIN agent_turn_leases l
                           ON l.tenant_id=d.tenant_id AND l.agent_address=d.recipient
                        WHERE d.tenant_id=$1 AND d.message_id=$2
                          AND d.status='in_flight' AND d.lease_owner=$3
                          AND d.lease_expires_at>now()
                          AND l.lease_owner=$3 AND l.lease_token=$4
                          AND l.lane='peer' AND l.lease_expires_at>now()
                        FOR UPDATE OF d,l""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    turn_lease.token,
                )
                if row is None:
                    return False
                await conn.execute(
                    """UPDATE agent_message_deliveries
                          SET status=CASE WHEN $4::boolean AND attempts<$5
                                          THEN 'pending' ELSE 'failed' END,
                              available_at=CASE WHEN $4::boolean AND attempts<$5
                                THEN now()+make_interval(secs=>($6::double precision) *
                                  LEAST(power(2,attempts-1),64)) ELSE NULL END,
                              lease_owner=NULL,lease_expires_at=NULL,
                              last_error=$7,updated_at=now()
                        WHERE tenant_id=$1 AND message_id=$2
                          AND status='in_flight' AND lease_owner=$3
                          AND lease_expires_at>now()""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    bool(retryable),
                    max_attempts,
                    float(max(0.0, backoff_seconds)),
                    str(error_code or "delivery_failed")[:200],
                )
                await self._release_delivery_turn(
                    conn, tenant_id, row["recipient"], turn_lease
                )
                return True

    async def renew_agent_message_claim(
        self, tenant_id, message_id, turn_lease, lease_seconds
    ):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                row = await conn.fetchrow(
                    """UPDATE agent_turn_leases l
                          SET lease_expires_at=now()+make_interval(secs=>$5),updated_at=now()
                         FROM agent_message_deliveries d
                        WHERE l.tenant_id=$1 AND d.tenant_id=l.tenant_id
                          AND d.message_id=$2 AND d.recipient=l.agent_address
                          AND l.lease_owner=$3 AND l.lease_token=$4
                          AND l.lane='peer' AND l.lease_expires_at>now()
                          AND d.status='in_flight' AND d.lease_owner=$3
                          AND d.lease_expires_at>now()
                        RETURNING l.*""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    turn_lease.token,
                    float(max(1, lease_seconds)),
                )
                renewed = agent_turn_lease_from_row(row)
                if renewed is None:
                    return None
                await conn.execute(
                    """UPDATE agent_message_deliveries
                          SET lease_expires_at=$4,updated_at=now()
                        WHERE tenant_id=$1 AND message_id=$2
                          AND status='in_flight' AND lease_owner=$3""",
                    tenant_id,
                    message_id,
                    turn_lease.owner,
                    renewed.expires_at,
                )
                return renewed

    @staticmethod
    async def _release_delivery_turn(conn, tenant_id, recipient, turn_lease) -> None:
        await conn.execute(
            """UPDATE agent_turn_leases
                  SET lease_owner=NULL,lease_token=NULL,lane=NULL,
                      lease_expires_at=NULL,updated_at=now()
                WHERE tenant_id=$1 AND agent_address=$2 AND lease_owner=$3
                  AND lease_token=$4""",
            tenant_id,
            recipient,
            turn_lease.owner,
            turn_lease.token,
        )
