"""Library store domain (arc-1 structural partial): the adapter and
workflow-definition shelf (policy-is-data) - extracted verbatim from
``store/postgres.py`` + ``store/memory.py``. PG host: ``self._pool``; Mem host:
``self._adapters`` / ``self._workflows`` / McpLifecycleStoreMem's
``_delete_mcp_lifecycle_state``. Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import AdapterRecord, WorkflowDefinition

from .rows import _adapter, _workflow


class LibraryStorePG:
    """Adapter + workflow-definition methods for ``PostgresStore``."""

    async def upsert_adapter(self, a: AdapterRecord):
        await self._pool.execute(
            """INSERT INTO adapters (id, tenant_id, version, runtime, source, module_ref,
                                     health, spec_ref, created_by, activated)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 version=EXCLUDED.version, runtime=EXCLUDED.runtime, source=EXCLUDED.source,
                 module_ref=EXCLUDED.module_ref, health=EXCLUDED.health,
                 spec_ref=EXCLUDED.spec_ref, created_by=EXCLUDED.created_by,
                 activated=EXCLUDED.activated, updated_at=now()""",
            a.id, a.tenant_id, a.version, a.runtime, a.source, a.module_ref,
            a.health.value, a.spec_ref, a.created_by, a.activated,
        )

    async def get_adapter(self, tenant_id, adapter_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM adapters WHERE tenant_id=$1 AND id=$2", tenant_id, adapter_id
        )
        return _adapter(row)

    async def list_adapters(self, tenant_id):
        rows = await self._pool.fetch("SELECT * FROM adapters WHERE tenant_id=$1", tenant_id)
        return [_adapter(r) for r in rows]

    async def delete_adapter(self, tenant_id, adapter_id):
        await self._pool.execute(
            "DELETE FROM adapters WHERE tenant_id=$1 AND id=$2", tenant_id, adapter_id
        )

    async def upsert_workflow(self, w: WorkflowDefinition):
        await self._pool.execute(
            """INSERT INTO workflow_definitions (id, tenant_id, version, source, definition,
                                                 intent_tags, origin_task, workspace_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 source=EXCLUDED.source, definition=EXCLUDED.definition,
                 intent_tags=EXCLUDED.intent_tags, origin_task=EXCLUDED.origin_task,
                 workspace_id=EXCLUDED.workspace_id, updated_at=now()""",
            w.id, w.tenant_id, w.version, w.source.value, w.definition, w.intent_tags,
            w.origin_task, w.workspace_id,
        )

    async def list_workflows(self, tenant_id):
        # Latest version per workflow id (the shelf), mirroring list_skills and
        # the in-memory store, so callers matching a workflow by id never see
        # duplicate or stale versions.
        rows = await self._pool.fetch(
            """SELECT DISTINCT ON (id) * FROM workflow_definitions WHERE tenant_id=$1
               ORDER BY id, version DESC""",
            tenant_id,
        )
        return [_workflow(r) for r in rows]


class LibraryStoreMem:
    """Adapter + workflow-definition methods for ``InMemoryStore``."""

    async def upsert_adapter(self, adapter):
        self._adapters[(adapter.tenant_id, adapter.id)] = adapter

    async def get_adapter(self, tenant_id, adapter_id):
        return self._adapters.get((tenant_id, adapter_id))

    async def list_adapters(self, tenant_id):
        return [a for (t, _), a in self._adapters.items() if t == tenant_id]

    async def delete_adapter(self, tenant_id, adapter_id):
        self._adapters.pop((tenant_id, adapter_id), None)
        self._delete_mcp_lifecycle_state(tenant_id, adapter_id)

    async def upsert_workflow(self, wf):
        # Versioned like Postgres (PK tenant+id+version): every version is kept.
        self._workflows[(wf.tenant_id, wf.id, wf.version)] = wf

    async def list_workflows(self, tenant_id):
        # Latest version per workflow id (the shelf), mirroring list_skills and
        # the PG DISTINCT ON (id) ... ORDER BY id, version DESC.
        latest: dict[str, WorkflowDefinition] = {}
        for (t, wid, _), w in self._workflows.items():
            if t == tenant_id and (wid not in latest or w.version > latest[wid].version):
                latest[wid] = w
        return list(latest.values())
