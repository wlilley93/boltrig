"""Tenant-permissions store domain (arc-1 structural partial): the tenant grant
sets (allow/deny) - extracted verbatim from ``store/postgres.py`` +
``store/memory.py``. PG host: ``self._pool``; Mem host: ``self._perms``.
Public surface unchanged.
"""

from __future__ import annotations

from boltrig.models import EMPTY_GRANTS, GrantSet, TenantPermissions


class TenantPermissionsStorePG:
    """Tenant permission methods for ``PostgresStore``."""

    async def get_tenant_permissions(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT allow, deny FROM tenant_permissions WHERE tenant_id=$1", tenant_id
        )
        if row is None:
            return TenantPermissions(tenant_id, EMPTY_GRANTS)
        return TenantPermissions(
            tenant_id, GrantSet.of(list(row["allow"] or []), list(row["deny"] or []))
        )

    async def set_tenant_permissions(self, perms: TenantPermissions) -> None:
        await self._pool.execute(
            """INSERT INTO tenant_permissions (tenant_id, allow, deny)
               VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id) DO UPDATE SET
                 allow=EXCLUDED.allow, deny=EXCLUDED.deny, updated_at=now()""",
            perms.tenant_id, list(perms.grants.allow), list(perms.grants.deny),
        )


class TenantPermissionsStoreMem:
    """Tenant permission methods for ``InMemoryStore``."""

    async def get_tenant_permissions(self, tenant_id):
        return self._perms.get(tenant_id, TenantPermissions(tenant_id, EMPTY_GRANTS))

    def set_tenant_permissions(self, perms: TenantPermissions) -> None:
        """Seeding helper (manifest load / tests). Not part of the runtime contract."""
        self._perms[perms.tenant_id] = perms
