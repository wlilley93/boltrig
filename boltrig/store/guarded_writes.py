"""Atomic create-only writes used by low-consequence control operations."""

from __future__ import annotations

from typing import Protocol

from boltrig.models import AdapterRecord, UserInvitation


class GuardedWritesContract(Protocol):
    async def create_adapter_if_absent(self, adapter: AdapterRecord) -> bool: ...
    async def add_invitation_if_no_pending(self, invitation: UserInvitation) -> bool: ...


class GuardedWritesMem:
    async def create_adapter_if_absent(self, adapter):
        key = (adapter.tenant_id, adapter.id)
        if key in self._adapters:
            return False
        self._adapters[key] = adapter
        return True

    async def add_invitation_if_no_pending(self, invitation):
        target = invitation.email.strip().lower()
        if any(
            tenant == invitation.tenant_id
            and existing.status == "pending"
            and existing.email.strip().lower() == target
            for (tenant, _), existing in self._invites.items()
        ):
            return False
        self._invites[(invitation.tenant_id, invitation.id)] = invitation
        return True


class GuardedWritesPG:
    async def create_adapter_if_absent(self, adapter):
        row = await self._pool.fetchrow(
            """INSERT INTO adapters (id, tenant_id, version, runtime, source, module_ref,
                                     health, spec_ref, created_by, activated)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO NOTHING RETURNING id""",
            adapter.id,
            adapter.tenant_id,
            adapter.version,
            adapter.runtime,
            adapter.source,
            adapter.module_ref,
            adapter.health.value,
            adapter.spec_ref,
            adapter.created_by,
            adapter.activated,
        )
        return row is not None

    async def add_invitation_if_no_pending(self, invitation):
        row = await self._pool.fetchrow(
            """INSERT INTO user_invitations
               (id, tenant_id, email, intended_role, intended_scope, invited_by,
                created_at, expires_at, status, token_hash,
                workspace_id, provision_workspace_name, provision_org_name)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT DO NOTHING RETURNING id""",
            invitation.id,
            invitation.tenant_id,
            invitation.email,
            invitation.intended_role,
            invitation.intended_scope,
            invitation.invited_by,
            invitation.created_at,
            invitation.expires_at,
            invitation.status,
            invitation.token_hash,
            invitation.workspace_id,
            invitation.provision_workspace_name,
            invitation.provision_org_name,
        )
        return row is not None
