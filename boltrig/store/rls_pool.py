"""The RLS fence machinery: the GUC/role binding and the pool facade that applies it.

Extracted from ``postgres.py``, which sits at its size ratchet. Grouping it with
``tenant_scope`` puts every part of the fence in one place, which matters because
the fence's failures have twice come from its parts disagreeing:

* ``_apply_guc`` read a tenant contextvar while every store method took the tenant
  as an argument, and the two drifted (fixed by ``bind_tenant_on_store_methods``);
* ``_apply_guc`` was called WITHOUT ``assume_role`` at 22 explicit-transaction
  sites, so the GUC was set and the policies never applied - a superuser bypasses
  RLS even under FORCE (fixed by ``bind_conn_to_tenant``).

``acquire()`` deliberately passes through UNFENCED. That is what lets a method opt
out on purpose (see ``control_plane_reads``), and it is also why a method holding
its own transaction gets no protection unless it asks: the guard in
tests/security/test_rls_covers_explicit_transactions.py exists for that.
"""

from __future__ import annotations

import asyncpg

from .tenant_scope import _current_tenant


async def _apply_guc(conn: asyncpg.Connection, *, assume_role: bool = False) -> None:
    """SET LOCAL app.tenant_id from the request context. An unset tenant becomes
    '' so the RLS predicate is never true (fail-closed, never wide-open).

    ``assume_role`` drops to ``boltrig_app``; WITHOUT IT THE POLICIES DO NOTHING,
    because the app connects as the owner and a superuser bypasses RLS even under
    FORCE. Must be a plain statement: SET LOCAL inside PL/pgSQL is reverted on exit,
    so a pg_roles guard would be the very no-op it was written to avoid. See
    tests/integration/test_rls.py for the measurement.
    """
    if assume_role:
        await conn.execute("SET LOCAL ROLE boltrig_app")
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", _current_tenant.get() or "")


class _RlsPool:
    """An asyncpg-pool facade that runs every convenience call inside a transaction
    with app.tenant_id set from the request context. This is what makes RLS LIVE:
    the store's existing ``self._pool.fetch/fetchrow/execute`` calls become
    tenant-scoped at the DB without touching any method body. acquire()/close()
    pass through - the few explicit-transaction methods set the GUC themselves."""

    def __init__(self, pool: asyncpg.Pool, *, assume_role: bool = False) -> None:
        self._pool = pool
        # False when rls.sql was never applied, so this stays a no-op rather than
        # erroring on a role that does not exist.
        self._assume_role = assume_role

    @property
    def assumes_role(self) -> bool:
        """Whether the fence is live on this pool. Read by ``bind_conn_to_tenant``.

        Public so a store method holding its OWN transaction can ask the pool
        instead of each store carrying a duplicate copy of the answer.
        """
        return self._assume_role

    async def _scoped(self, op: str, query: str, *args):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=self._assume_role)
                return await getattr(conn, op)(query, *args)

    async def fetch(self, query, *args):
        return await self._scoped("fetch", query, *args)

    async def fetchrow(self, query, *args):
        return await self._scoped("fetchrow", query, *args)

    async def execute(self, query, *args):
        return await self._scoped("execute", query, *args)

    def acquire(self):
        return self._pool.acquire()

    async def close(self):
        await self._pool.close()
