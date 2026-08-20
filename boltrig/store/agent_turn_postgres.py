"""PostgreSQL per-identity scheduler shared by every named-agent wake lane."""

from __future__ import annotations

import uuid

from boltrig.models import AgentTurnLane, utcnow

from .agent_mailbox_rows import agent_turn_lease_from_row
from .tenant_scope import bind_conn_to_tenant


async def _prepare_turn(conn, tenant_id, agent_address, owner):
    await conn.execute(
        "DELETE FROM agent_turn_waiters WHERE tenant_id=$1 AND expires_at<=now()",
        tenant_id,
    )
    enabled = await conn.fetchval(
        "SELECT enabled FROM named_agents WHERE tenant_id=$1 AND address=$2",
        tenant_id,
        agent_address,
    )
    if enabled is not True:
        raise ValueError("agent turn requires an enabled named agent")
    current_row = await conn.fetchrow(
        """SELECT * FROM agent_turn_leases
           WHERE tenant_id=$1 AND agent_address=$2 FOR UPDATE""",
        tenant_id,
        agent_address,
    )
    current = agent_turn_lease_from_row(current_row)
    if current is not None and current.expires_at > utcnow():
        return current
    if current is not None:
        await conn.execute(
            """UPDATE agent_turn_leases
                  SET lease_owner=NULL,lease_token=NULL,lane=NULL,
                      lease_expires_at=NULL,updated_at=now()
                WHERE tenant_id=$1 AND agent_address=$2""",
            tenant_id,
            agent_address,
        )
    return None


async def _queue_waiter(
    conn, tenant_id, agent_address, owner, lane, waiter_ttl_seconds
) -> None:
    await conn.execute(
        """INSERT INTO agent_turn_waiters
             (tenant_id,agent_address,waiter_id,lane,requested_at,expires_at)
           VALUES ($1,$2,$3,$4,now(),now()+make_interval(secs=>$5))
           ON CONFLICT (tenant_id,agent_address,waiter_id) DO UPDATE SET
             lane=EXCLUDED.lane,expires_at=EXCLUDED.expires_at""",
        tenant_id,
        agent_address,
        owner,
        lane.value,
        float(max(1, waiter_ttl_seconds)),
    )


async def _waiter_is_selected(conn, tenant_id, agent_address, owner, lane) -> bool:
    selected = await conn.fetchrow(
        """SELECT waiter_id,lane FROM agent_turn_waiters
           WHERE tenant_id=$1 AND agent_address=$2 AND expires_at>now()
           ORDER BY CASE lane WHEN 'interactive' THEN 0
                              WHEN 'peer' THEN 10 ELSE 20 END,
                    requested_at,waiter_id
           LIMIT 1""",
        tenant_id,
        agent_address,
    )
    if selected is None or selected["waiter_id"] != owner:
        return False
    if lane is not AgentTurnLane.BACKGROUND:
        return True
    due_peer = await conn.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM agent_message_deliveries d
             WHERE d.tenant_id=$1 AND d.recipient=$2
               AND ((d.status='pending' AND
                     (d.available_at IS NULL OR d.available_at<=now()))
                    OR (d.status='in_flight' AND d.lease_expires_at<=now())))""",
        tenant_id,
        agent_address,
    )
    return not due_peer


async def _write_turn_lease(
    conn, tenant_id, agent_address, owner, lane, lease_seconds
):
    token = f"atl_{uuid.uuid4().hex}"
    row = await conn.fetchrow(
        """UPDATE agent_turn_leases
              SET lease_owner=$3,lease_token=$4,lane=$5,
                  lease_expires_at=now()+make_interval(secs=>$6),updated_at=now()
            WHERE tenant_id=$1 AND agent_address=$2 RETURNING *""",
        tenant_id,
        agent_address,
        owner,
        token,
        lane.value,
        float(max(1, lease_seconds)),
    )
    await conn.execute(
        """DELETE FROM agent_turn_waiters
           WHERE tenant_id=$1 AND agent_address=$2 AND waiter_id=$3""",
        tenant_id,
        agent_address,
        owner,
    )
    return agent_turn_lease_from_row(row)


class AgentTurnStorePG:
    async def acquire_agent_turn(
        self,
        tenant_id,
        agent_address,
        owner,
        lane,
        lease_seconds,
        *,
        waiter_ttl_seconds=600,
    ):
        """Join the durable per-identity queue and acquire its one active turn."""
        lane = AgentTurnLane(lane)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                current = await _prepare_turn(conn, tenant_id, agent_address, owner)
                if current is not None and current.owner == owner:
                    return current
                await _queue_waiter(
                    conn,
                    tenant_id,
                    agent_address,
                    owner,
                    lane,
                    waiter_ttl_seconds,
                )
                if current is not None or not await _waiter_is_selected(
                    conn, tenant_id, agent_address, owner, lane
                ):
                    return None
                return await _write_turn_lease(
                    conn, tenant_id, agent_address, owner, lane, lease_seconds
                )

    async def renew_agent_turn(self, lease, lease_seconds):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, lease.tenant_id, pool=self._pool)
                row = await conn.fetchrow(
                    """UPDATE agent_turn_leases
                          SET lease_expires_at=now()+make_interval(secs=>$6),updated_at=now()
                        WHERE tenant_id=$1 AND agent_address=$2 AND lease_owner=$3
                          AND lease_token=$4 AND lane=$5 AND lease_expires_at>now()
                        RETURNING *""",
                    lease.tenant_id,
                    lease.agent_address,
                    lease.owner,
                    lease.token,
                    lease.lane.value,
                    float(max(1, lease_seconds)),
                )
        return agent_turn_lease_from_row(row)

    async def release_agent_turn(self, lease):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, lease.tenant_id, pool=self._pool)
                result = await conn.execute(
                    """UPDATE agent_turn_leases
                          SET lease_owner=NULL,lease_token=NULL,lane=NULL,
                              lease_expires_at=NULL,updated_at=now()
                        WHERE tenant_id=$1 AND agent_address=$2 AND lease_owner=$3
                          AND lease_token=$4""",
                    lease.tenant_id,
                    lease.agent_address,
                    lease.owner,
                    lease.token,
                )
        return result == "UPDATE 1"

    async def cancel_agent_turn_waiter(self, tenant_id, agent_address, owner):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                await conn.execute(
                    """DELETE FROM agent_turn_waiters
                       WHERE tenant_id=$1 AND agent_address=$2 AND waiter_id=$3""",
                    tenant_id,
                    agent_address,
                    owner,
                )
