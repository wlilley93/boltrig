"""CAS next-agent and project projections for PostgreSQL conversations."""

from __future__ import annotations

from boltrig.models import Conversation

from .rows import _conversation


class ConversationBindingStorePG:
    """Conversation CRUD with explicit compare-and-set routing changes."""

    async def create_conversation(self, c: Conversation):
        await self._pool.execute(
            """INSERT INTO conversations (id, tenant_id, user_id, agent_address, workspace_id, title, status, origin, source_ref, source_run_id, companion_id, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            c.id,
            c.tenant_id,
            c.user_id,
            c.agent_address,
            c.workspace_id,
            c.title,
            c.status.value,
            c.origin.value,
            c.source_ref,
            c.source_run_id,
            c.companion_id,
            c.created_at,
            c.updated_at,
        )

    async def get_conversation(self, tenant_id, conv_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM conversations WHERE tenant_id=$1 AND id=$2", tenant_id, conv_id
        )
        return _conversation(row)

    async def switch_conversation_agent(
        self, tenant_id, conv_id, expected_address, agent_address
    ):
        # One statement gives explicit CAS semantics across worker replicas.
        return await self._pool.fetchval(
            """WITH bound AS (
                   UPDATE conversations SET agent_address=$4, updated_at=now()
                    WHERE tenant_id=$1 AND id=$2
                      AND agent_address IS NOT DISTINCT FROM $3
                   RETURNING agent_address
               )
               SELECT agent_address FROM bound
               UNION ALL
               SELECT agent_address FROM conversations
                WHERE tenant_id=$1 AND id=$2
                  AND NOT EXISTS (SELECT 1 FROM bound)
               LIMIT 1""",
            tenant_id,
            conv_id,
            expected_address,
            agent_address,
        )

    async def move_conversation_workspace(
        self, tenant_id, conv_id, expected_workspace_id, workspace_id
    ):
        row = await self._pool.fetchrow(
            """WITH moved AS (
                   UPDATE conversations SET workspace_id=$4, updated_at=now()
                    WHERE tenant_id=$1 AND id=$2
                      AND workspace_id IS NOT DISTINCT FROM $3
                   RETURNING workspace_id
               )
               SELECT TRUE AS found, workspace_id FROM moved
               UNION ALL
               SELECT TRUE AS found, workspace_id FROM conversations
                WHERE tenant_id=$1 AND id=$2
                  AND NOT EXISTS (SELECT 1 FROM moved)
               LIMIT 1""",
            tenant_id,
            conv_id,
            expected_workspace_id,
            workspace_id,
        )
        if row is None:
            return False, None
        return bool(row["found"]), row["workspace_id"]

    async def update_conversation(self, c: Conversation):
        # Deliberately excludes agent_address and workspace_id: generic metadata
        # updates cannot silently reroute the next turn or move a project.
        await self._pool.execute(
            """UPDATE conversations SET title=$3, status=$4, origin=$5, source_ref=$6, source_run_id=$7, companion_id=$8, updated_at=$9
               WHERE tenant_id=$1 AND id=$2""",
            c.tenant_id,
            c.id,
            c.title,
            c.status.value,
            c.origin.value,
            c.source_ref,
            c.source_run_id,
            c.companion_id,
            c.updated_at,
        )


__all__ = ["ConversationBindingStorePG"]
