"""Tenancy store domain (arc-1 structural partial): orgs, workspaces,
org/workspace membership, the pre-tenant email->orgs identity index and
per-org/workspace/user AI configs - extracted verbatim from
``store/postgres.py`` + ``store/memory.py``. PG host: ``self._pool``; Mem host:
``self._orgs``/``_workspaces``/``_org_members``/``_identity_orgs``/
``_workspace_members``/``_ai_configs``. Public surface unchanged.
(list_orgs PG-side lives in ControlPlaneReadsPG - cross-tenant by definition.)
"""

from __future__ import annotations

from boltrig.models import (
    Organisation, OrgMember,
    WORKSPACE_ROLES,
    Workspace, WorkspaceMember,
    utcnow,
)
from boltrig.models.errors import SchemaValidationError

from .rls_pool import _apply_guc
from .rows import _org, _org_member, _workspace, _workspace_member
from .tenant_scope import pool_assumes_app_role


def _norm_email_key(value) -> str:
    """Normalise an identity key (the email == user_id in the first-party flow) so
    the global email -> orgs index is case/space-insensitive, matching the login
    normalisation ([2026] VJS-COUNTY 11)."""
    return value.strip().lower() if isinstance(value, str) else ""


class TenancyStorePG:
    """Org/workspace tenancy + AI configs for ``PostgresStore``."""

    async def create_org(self, org: Organisation):
        # Idempotent create (D1): ON CONFLICT DO NOTHING so ensure_default_org is a
        # safe no-op for a tenant that already has its org. The org id IS the
        # tenant_id.
        await self._pool.execute(
            """INSERT INTO organisations
               (id, name, slug, settings, allow_own_ai_keys, require_two_factor,
                created_at, updated_at, allow_own_integration_credentials)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (id) DO NOTHING""",
            org.id, org.name, org.slug, org.settings,
            org.allow_own_ai_keys, org.require_two_factor, org.created_at, org.updated_at,
            org.allow_own_integration_credentials,
        )

    async def get_org(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM organisations WHERE id=$1", tenant_id
        )
        return _org(row)

    # list_orgs lives in ControlPlaneReadsPG: it is cross-tenant BY DEFINITION and
    # so runs outside the fence, which is a decision that needs its own guard.

    async def update_org(self, org: Organisation):
        await self._pool.execute(
            """UPDATE organisations SET name=$2, slug=$3, settings=$4,
                   allow_own_ai_keys=$5, require_two_factor=$6, updated_at=now(),
                   allow_own_integration_credentials=$7
               WHERE id=$1""",
            org.id, org.name, org.slug, org.settings,
            org.allow_own_ai_keys, org.require_two_factor,
            org.allow_own_integration_credentials,
        )

    async def create_workspace(self, workspace: Workspace):
        await self._pool.execute(
            """INSERT INTO workspaces
               (id, tenant_id, name, slug, settings, status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            workspace.id, workspace.tenant_id, workspace.name, workspace.slug,
            workspace.settings, workspace.status,
            workspace.created_at, workspace.updated_at,
        )

    async def get_workspace(self, tenant_id, workspace_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM workspaces WHERE tenant_id=$1 AND id=$2",
            tenant_id, workspace_id,
        )
        return _workspace(row)

    async def list_workspaces(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM workspaces WHERE tenant_id=$1 ORDER BY created_at DESC",
            tenant_id,
        )
        return [_workspace(r) for r in rows]

    async def update_workspace(self, workspace: Workspace):
        await self._pool.execute(
            """UPDATE workspaces SET name=$3, slug=$4, settings=$5, status=$6,
                   updated_at=now()
               WHERE tenant_id=$1 AND id=$2""",
            workspace.tenant_id, workspace.id, workspace.name, workspace.slug,
            workspace.settings, workspace.status,
        )

    async def add_org_member(self, member: OrgMember):
        # Both writes commit or neither does (base.py's lockstep invariant): a
        # failure between the org_members row and the identity_orgs index would
        # otherwise leave a dangling switch candidate.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
                await conn.execute(
                    """INSERT INTO org_members (tenant_id, user_id, role, created_at)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (tenant_id, user_id) DO UPDATE SET role=EXCLUDED.role""",
                    member.tenant_id, member.user_id, member.role, member.created_at,
                )
                # Keep the global email -> orgs INDEX in lockstep ([2026] VJS-COUNTY 11, D1).
                # identity_orgs is RLS-EXCLUDED (the pre-tenant lookup, keyed by the normalised
                # email), so this write does not need the bound tenant and is safe under RLS.
                await conn.execute(
                    """INSERT INTO identity_orgs (email, tenant_id, role, created_at)
                       VALUES (lower($1),$2,$3,$4)
                       ON CONFLICT (email, tenant_id) DO UPDATE SET role=EXCLUDED.role""",
                    member.user_id, member.tenant_id, member.role, member.created_at,
                )

    async def remove_org_member(self, tenant_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
                await conn.execute(
                    "DELETE FROM org_members WHERE tenant_id=$1 AND user_id=$2",
                    tenant_id, user_id,
                )
                # Drop the index pointer too so a revoked membership is no longer a switch
                # candidate (the resolver also fail-closes on the org_members re-check).
                await conn.execute(
                    "DELETE FROM identity_orgs WHERE email=lower($1) AND tenant_id=$2",
                    user_id, tenant_id,
                )

    async def get_org_member(self, tenant_id, user_id):
        # Tenant-scoped single-membership re-auth ([2026] VJS-COUNTY 11, D2).
        row = await self._pool.fetchrow(
            "SELECT * FROM org_members WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return _org_member(row)

    async def list_orgs_for_email(self, email):
        # The pre-tenant email -> orgs index (D1): the tenant_ids an email is a member
        # of. Resolved by the normalised email key (RLS-EXCLUDED), like get_pat_by_hash.
        rows = await self._pool.fetch(
            "SELECT tenant_id FROM identity_orgs WHERE email=lower($1) ORDER BY tenant_id",
            email,
        )
        return [r["tenant_id"] for r in rows]

    async def list_org_members(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM org_members WHERE tenant_id=$1 ORDER BY created_at",
            tenant_id,
        )
        return [_org_member(r) for r in rows]

    async def list_orgs_for_user(self, tenant_id, user_id):
        # Tenant-scoped membership query (switching seam): only the bound tenant's
        # org, never another tenant's, joined through org_members.
        rows = await self._pool.fetch(
            """SELECT o.* FROM organisations o
               JOIN org_members m ON m.tenant_id = o.id
               WHERE m.tenant_id=$1 AND m.user_id=$2
               ORDER BY o.created_at DESC""",
            tenant_id, user_id,
        )
        return [_org(r) for r in rows]

    async def add_workspace_member(self, member: WorkspaceMember):
        # A per-workspace role must be one of the allowed set (D3): reject an
        # out-of-set role before it can be persisted.
        if member.role not in WORKSPACE_ROLES:
            raise SchemaValidationError(
                f"invalid workspace role: {member.role!r}",
                errors=[f"role must be one of {sorted(WORKSPACE_ROLES)}"],
            )
        await self._pool.execute(
            """INSERT INTO workspace_members
               (workspace_id, user_id, tenant_id, role, permissions, created_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, workspace_id, user_id) DO UPDATE SET
                 role=EXCLUDED.role, permissions=EXCLUDED.permissions""",
            member.workspace_id, member.user_id, member.tenant_id, member.role,
            member.permissions, member.created_at,
        )

    async def remove_workspace_member(self, tenant_id, workspace_id, user_id):
        await self._pool.execute(
            """DELETE FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 AND user_id=$3""",
            tenant_id, workspace_id, user_id,
        )

    async def list_workspace_members(self, tenant_id, workspace_id):
        rows = await self._pool.fetch(
            """SELECT * FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 ORDER BY created_at""",
            tenant_id, workspace_id,
        )
        return [_workspace_member(r) for r in rows]

    async def get_workspace_member(self, tenant_id, workspace_id, user_id):
        # Tenant-scoped single-membership lookup (D11): the WHERE binds tenant_id, so
        # it can never return another tenant's row (None when absent, fail-closed).
        row = await self._pool.fetchrow(
            """SELECT * FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 AND user_id=$3""",
            tenant_id, workspace_id, user_id,
        )
        return _workspace_member(row)

    async def list_workspaces_for_user(self, tenant_id, user_id):
        # Tenant-scoped membership query (switching seam): only workspaces inside
        # the bound tenant the user belongs to.
        rows = await self._pool.fetch(
            """SELECT w.* FROM workspaces w
               JOIN workspace_members m
                 ON m.tenant_id = w.tenant_id AND m.workspace_id = w.id
               WHERE m.tenant_id=$1 AND m.user_id=$2
               ORDER BY w.created_at DESC""",
            tenant_id, user_id,
        )
        return [_workspace(r) for r in rows]

class TenancyStoreMem:
    """Org/workspace tenancy + AI configs for ``InMemoryStore``."""

    async def create_org(self, org):
        # Idempotent (mirrors the add_* ON CONFLICT DO NOTHING contract): a repeat
        # create for an existing tenant_id is a no-op, so ensure_default_org is safe
        # to call on every boot. The org id IS the tenant_id (D1).
        self._orgs.setdefault(org.id, org)

    async def get_org(self, tenant_id):
        return self._orgs.get(tenant_id)

    async def list_orgs(self):
        # Cross-tenant enumeration for the control plane (no tenant is bound at the
        # backfill). Not reachable from a tenant-scoped HTTP surface.
        return list(self._orgs.values())

    async def update_org(self, org):
        org.updated_at = utcnow()
        self._orgs[org.id] = org

    async def create_workspace(self, workspace):
        self._workspaces[(workspace.tenant_id, workspace.id)] = workspace

    async def get_workspace(self, tenant_id, workspace_id):
        return self._workspaces.get((tenant_id, workspace_id))

    async def list_workspaces(self, tenant_id):
        return [w for (t, _), w in self._workspaces.items() if t == tenant_id]

    async def update_workspace(self, workspace):
        workspace.updated_at = utcnow()
        self._workspaces[(workspace.tenant_id, workspace.id)] = workspace

    async def add_org_member(self, member):
        self._org_members[(member.tenant_id, member.user_id)] = member
        # Keep the global email -> orgs INDEX in lockstep ([2026] VJS-COUNTY 11, D1):
        # the email (== user_id in the first-party flow) is now a member of this org.
        email = _norm_email_key(member.user_id)
        self._identity_orgs.setdefault(email, {})[member.tenant_id] = member.role

    async def remove_org_member(self, tenant_id, user_id):
        self._org_members.pop((tenant_id, user_id), None)
        # Drop the index pointer too so a revoked membership is no longer a switch
        # candidate (the resolver also fail-closes on the org_members re-check).
        email = _norm_email_key(user_id)
        orgs = self._identity_orgs.get(email)
        if orgs is not None:
            orgs.pop(tenant_id, None)
            if not orgs:
                self._identity_orgs.pop(email, None)

    async def get_org_member(self, tenant_id, user_id):
        # Tenant-scoped single-membership re-auth ([2026] VJS-COUNTY 11, D2): only the
        # bound tenant's row, None otherwise (fail-closed).
        return self._org_members.get((tenant_id, user_id))

    async def list_orgs_for_email(self, email):
        # The pre-tenant email -> orgs index (D1): the tenant_ids the email is a member
        # of. Cross-tenant BY KEY (the normalised email), like get_pat_by_hash - never
        # inside a tenant fence. Deterministic order so a default pick is stable.
        return sorted(self._identity_orgs.get(_norm_email_key(email), {}).keys())

    async def list_org_members(self, tenant_id):
        return [m for (t, _), m in self._org_members.items() if t == tenant_id]

    async def list_orgs_for_user(self, tenant_id, user_id):
        # The membership query switching will later use. Still tenant-scoped: it
        # only ever returns the bound tenant's org, never another tenant's.
        out = []
        for (t, u), _m in self._org_members.items():
            if t == tenant_id and u == user_id:
                org = self._orgs.get(t)
                if org is not None:
                    out.append(org)
        return out

    async def add_workspace_member(self, member):
        # A per-workspace role must be one of the allowed set (D3): reject an
        # out-of-set role so it can never be persisted.
        if member.role not in WORKSPACE_ROLES:
            raise SchemaValidationError(
                f"invalid workspace role: {member.role!r}",
                errors=[f"role must be one of {sorted(WORKSPACE_ROLES)}"],
            )
        self._workspace_members[(member.tenant_id, member.workspace_id, member.user_id)] = member

    async def remove_workspace_member(self, tenant_id, workspace_id, user_id):
        self._workspace_members.pop((tenant_id, workspace_id, user_id), None)

    async def list_workspace_members(self, tenant_id, workspace_id):
        return [
            m
            for (t, w, _), m in self._workspace_members.items()
            if t == tenant_id and w == workspace_id
        ]

    async def get_workspace_member(self, tenant_id, workspace_id, user_id):
        # Tenant-scoped single-membership lookup (D11): only return the row when it
        # is inside the bound tenant, else None (fail-closed, never crosses tenants).
        return self._workspace_members.get((tenant_id, workspace_id, user_id))

    async def list_workspaces_for_user(self, tenant_id, user_id):
        # Tenant-scoped: only workspaces in the bound tenant whose id the user is a
        # member of. Never crosses a tenant boundary.
        out = []
        for (t, w, u), _m in self._workspace_members.items():
            if t == tenant_id and u == user_id:
                ws = self._workspaces.get((tenant_id, w))
                if ws is not None:
                    out.append(ws)
        return out
