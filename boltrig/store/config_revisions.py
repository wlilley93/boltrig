"""Config-revision store domain (arc-1 structural partial): the append-only
config change history - extracted verbatim from ``store/postgres.py`` +
``store/memory.py``. PG host: ``self._pool``; Mem host: ``self._revisions`` /
``self._rev_seq``. Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import ConfigRevision

from .rows import _revision


class ConfigRevisionStorePG:
    """Config-revision methods for ``PostgresStore``."""

    async def add_config_revision(self, rev: ConfigRevision) -> ConfigRevision:
        row = await self._pool.fetchrow(
            """INSERT INTO config_revisions (tenant_id, kind, ref, version, payload, actor, rolled_back)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id, created_at""",
            rev.tenant_id, rev.kind, rev.ref, rev.version, rev.payload, rev.actor, rev.rolled_back,
        )
        rev.id = row["id"]
        rev.created_at = row["created_at"]
        return rev

    async def list_config_revisions(self, tenant_id, kind, ref):
        rows = await self._pool.fetch(
            """SELECT * FROM config_revisions WHERE tenant_id=$1 AND kind=$2 AND ref=$3
               ORDER BY created_at DESC""",
            tenant_id, kind, ref,
        )
        return [_revision(r) for r in rows]

    async def get_config_revision(self, tenant_id, rev_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM config_revisions WHERE tenant_id=$1 AND id=$2", tenant_id, rev_id
        )
        return _revision(row)


class ConfigRevisionStoreMem:
    """Config-revision methods for ``InMemoryStore``."""

    async def add_config_revision(self, rev):
        self._rev_seq += 1
        rev.id = self._rev_seq
        self._revisions.append(rev)
        return rev

    async def list_config_revisions(self, tenant_id, kind, ref):
        return [
            r
            for r in self._revisions
            if r.tenant_id == tenant_id and r.kind == kind and r.ref == ref
        ]

    async def get_config_revision(self, tenant_id, rev_id):
        return next(
            (r for r in self._revisions if r.tenant_id == tenant_id and r.id == rev_id), None
        )
