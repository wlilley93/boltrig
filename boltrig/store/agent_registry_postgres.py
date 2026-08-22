"""PostgreSQL persistence for the durable named-agent registry."""

from __future__ import annotations

from .agent_mailbox_rows import named_agent_from_row
from .tenant_scope import bind_conn_to_tenant


class AgentRegistryStorePG:
    async def upsert_named_agent(self, agent):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, agent.tenant_id, pool=self._pool)
                if agent.default_for_intake:
                    await conn.execute(
                        """UPDATE named_agents
                              SET default_for_intake=FALSE, updated_at=now()
                            WHERE tenant_id=$1 AND address<>$2
                              AND default_for_intake""",
                        agent.tenant_id,
                        agent.address,
                    )
                await conn.execute(
                    """INSERT INTO named_agents
                         (tenant_id,address,name,runtime,model_endpoint,
                          supported_skills,max_depth,cost_tier,purpose,brief,
                          scope_id,default_for_intake,enabled,created_at,updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,now())
                       ON CONFLICT (tenant_id,address) DO UPDATE SET
                         name=EXCLUDED.name,runtime=EXCLUDED.runtime,
                         model_endpoint=EXCLUDED.model_endpoint,
                         supported_skills=EXCLUDED.supported_skills,
                         max_depth=EXCLUDED.max_depth,cost_tier=EXCLUDED.cost_tier,
                         purpose=EXCLUDED.purpose,brief=EXCLUDED.brief,
                         scope_id=EXCLUDED.scope_id,
                         default_for_intake=EXCLUDED.default_for_intake,
                         enabled=EXCLUDED.enabled,updated_at=now()""",
                    agent.tenant_id,
                    agent.address,
                    agent.name,
                    agent.runtime,
                    agent.model_endpoint,
                    agent.supported_skills,
                    agent.max_depth,
                    agent.cost_tier,
                    agent.purpose,
                    agent.brief,
                    agent.scope_id,
                    agent.default_for_intake,
                    agent.enabled,
                    agent.created_at,
                )
                await conn.execute(
                    """INSERT INTO agent_turn_leases (tenant_id,agent_address)
                       VALUES ($1,$2) ON CONFLICT (tenant_id,agent_address) DO NOTHING""",
                    agent.tenant_id,
                    agent.address,
                )

    async def get_named_agent(self, tenant_id, address):
        row = await self._pool.fetchrow(
            "SELECT * FROM named_agents WHERE tenant_id=$1 AND address=$2",
            tenant_id,
            address,
        )
        return named_agent_from_row(row)

    async def list_named_agents(self, tenant_id, *, include_disabled=False):
        rows = await self._pool.fetch(
            """SELECT * FROM named_agents
               WHERE tenant_id=$1 AND ($2::boolean OR enabled)
               ORDER BY address""",
            tenant_id,
            include_disabled,
        )
        return [named_agent_from_row(row) for row in rows]

    async def deactivate_absent_named_agents(self, tenant_id, declared_addresses):
        rows = await self._pool.fetch(
            """UPDATE named_agents
                  SET enabled=FALSE,default_for_intake=FALSE,updated_at=now()
                WHERE tenant_id=$1 AND enabled
                  AND NOT (address=ANY($2::text[]))
                RETURNING address""",
            tenant_id,
            list(declared_addresses),
        )
        return sorted(row["address"] for row in rows)
