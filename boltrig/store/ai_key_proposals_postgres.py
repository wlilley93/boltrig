"""PostgreSQL one-time AI-key secret proposal persistence."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import AiConfig

from .ai_key_proposal_contract import (
    AI_KEY_PROPOSAL_PAGE_LIMIT,
    matches_exact,
    proposal_from_row,
    validate_proposal,
)
from .sealing import seal_ref


async def _bind_tenant(conn, tenant_id):
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)


class AiKeyProposalStorePG:
    async def create_ai_key_secret_proposal(self, proposal, secret):
        validate_proposal(proposal, secret)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _bind_tenant(conn, proposal.tenant_id)
                await conn.execute(
                    """INSERT INTO credential_refs
                         (id,tenant_id,store,ref,data,expires_at)
                       VALUES ($1,$2,'sealed','',$3,$4)""",
                    proposal.secret_ref,
                    proposal.tenant_id,
                    seal_ref({"secret": secret, "purpose": "ai_key_proposal"}),
                    proposal.expires_at,
                )
                await conn.execute(
                    """INSERT INTO ai_key_secret_proposals
                         (id,tenant_id,requested_by,requested_on_behalf_of,
                          workspace_id,level,scope_id,provider,model,base_url,
                          secret_ref,secret_digest,status,approval_id,
                          created_at,expires_at,updated_at,consumed_at)
                       VALUES
                         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                          $15,$16,$17,$18)""",
                    proposal.id,
                    proposal.tenant_id,
                    proposal.requested_by,
                    proposal.requested_on_behalf_of,
                    proposal.workspace_id,
                    proposal.level,
                    proposal.scope_id,
                    proposal.provider,
                    proposal.model,
                    proposal.base_url,
                    proposal.secret_ref,
                    proposal.secret_digest,
                    proposal.status,
                    proposal.approval_id,
                    proposal.created_at,
                    proposal.expires_at,
                    proposal.updated_at,
                    proposal.consumed_at,
                )

    async def attach_ai_key_proposal_approval(
        self, tenant_id, proposal_id, requested_by, approval_id
    ):
        row = await self._pool.fetchrow(
            """UPDATE ai_key_secret_proposals
                  SET approval_id=$4,updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND requested_by=$3
                  AND status='pending' AND approval_id IS NULL
              RETURNING *""",
            tenant_id,
            proposal_id,
            requested_by,
            approval_id,
        )
        return proposal_from_row(row)

    async def get_ai_key_secret_proposal(self, tenant_id, proposal_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM ai_key_secret_proposals
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id,
            proposal_id,
        )
        return proposal_from_row(row)

    async def list_ai_key_secret_proposals(self, tenant_id, requested_by, requested_on_behalf_of):
        rows = await self._pool.fetch(
            """SELECT * FROM ai_key_secret_proposals
               WHERE tenant_id=$1 AND requested_by=$2
                 AND requested_on_behalf_of IS NOT DISTINCT FROM $3
               ORDER BY created_at DESC,id DESC
               LIMIT $4""",
            tenant_id,
            requested_by,
            requested_on_behalf_of,
            AI_KEY_PROPOSAL_PAGE_LIMIT,
        )
        return [proposal_from_row(row) for row in rows]

    async def invalidate_ai_key_secret_proposal(
        self, tenant_id, proposal_id, requested_by, terminal_status, now
    ):
        _validate_terminal_status(terminal_status)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _bind_tenant(conn, tenant_id)
                row = await conn.fetchrow(
                    """SELECT * FROM ai_key_secret_proposals
                       WHERE tenant_id=$1 AND id=$2 AND requested_by=$3
                       FOR UPDATE""",
                    tenant_id,
                    proposal_id,
                    requested_by,
                )
                proposal = proposal_from_row(row)
                if proposal is None or proposal.status != "pending":
                    return proposal
                await _invalidate_locked(conn, proposal, terminal_status, now)
                return replace(
                    proposal,
                    status=terminal_status,
                    secret_ref=None,
                    updated_at=now,
                )

    async def invalidate_ai_key_proposal_for_approval(
        self, tenant_id, approval_id, terminal_status, now
    ):
        _validate_terminal_status(terminal_status)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _bind_tenant(conn, tenant_id)
                row = await conn.fetchrow(
                    """SELECT * FROM ai_key_secret_proposals
                       WHERE tenant_id=$1 AND approval_id=$2 AND status='pending'
                       FOR UPDATE""",
                    tenant_id,
                    approval_id,
                )
                proposal = proposal_from_row(row)
                if proposal is None:
                    return False
                await _invalidate_locked(conn, proposal, terminal_status, now)
                return True

    async def expire_due_ai_key_secret_proposals(self, tenant_id, now):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _bind_tenant(conn, tenant_id)
                rows = await conn.fetch(
                    """SELECT id,secret_ref,approval_id
                       FROM ai_key_secret_proposals
                       WHERE tenant_id=$1 AND status='pending'
                         AND expires_at <= $2
                       FOR UPDATE""",
                    tenant_id,
                    now,
                )
                if not rows:
                    return []
                await _expire_rows(conn, tenant_id, rows, now)
                return [row["approval_id"] for row in rows if row["approval_id"]]

    async def consume_ai_key_secret_proposal(
        self,
        tenant_id,
        proposal_id,
        *,
        requested_by,
        requested_on_behalf_of,
        workspace_id,
        level,
        scope_id,
        provider,
        model,
        base_url,
        secret_digest,
        now,
    ):
        evidence = {
            "requested_by": requested_by,
            "requested_on_behalf_of": requested_on_behalf_of,
            "workspace_id": workspace_id,
            "level": level,
            "scope_id": scope_id,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "secret_digest": secret_digest,
        }
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _bind_tenant(conn, tenant_id)
                return await _consume_locked(conn, tenant_id, proposal_id, evidence, now)


def _validate_terminal_status(terminal_status):
    if terminal_status not in {"rejected", "expired", "invalidated"}:
        raise ValueError("invalid proposal terminal status")


async def _invalidate_locked(conn, proposal, terminal_status, now):
    await conn.execute(
        """UPDATE ai_key_secret_proposals
              SET status=$4,secret_ref=NULL,updated_at=$5
            WHERE tenant_id=$1 AND id=$2 AND requested_by=$3""",
        proposal.tenant_id,
        proposal.id,
        proposal.requested_by,
        terminal_status,
        now,
    )
    if proposal.secret_ref is not None:
        await conn.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            proposal.tenant_id,
            proposal.secret_ref,
        )


async def _expire_rows(conn, tenant_id, rows, now):
    ids = [row["id"] for row in rows]
    refs = [row["secret_ref"] for row in rows if row["secret_ref"]]
    await conn.execute(
        """UPDATE ai_key_secret_proposals
              SET status='expired',secret_ref=NULL,updated_at=$3
            WHERE tenant_id=$1 AND id=ANY($2::text[])""",
        tenant_id,
        ids,
        now,
    )
    if refs:
        await conn.execute(
            """DELETE FROM credential_refs
               WHERE tenant_id=$1 AND id=ANY($2::text[])""",
            tenant_id,
            refs,
        )


async def _consume_locked(conn, tenant_id, proposal_id, evidence, now):
    row = await conn.fetchrow(
        """SELECT * FROM ai_key_secret_proposals
           WHERE tenant_id=$1 AND id=$2
           FOR UPDATE""",
        tenant_id,
        proposal_id,
    )
    proposal = proposal_from_row(row)
    if proposal is None or not matches_exact(proposal, **evidence):
        return None
    if proposal.status != "pending" or proposal.secret_ref is None:
        return None
    if proposal.expires_at <= now:
        await _invalidate_locked(conn, proposal, "expired", now)
        return None
    staged = await conn.fetchval(
        """SELECT 1 FROM credential_refs
           WHERE tenant_id=$1 AND id=$2""",
        tenant_id,
        proposal.secret_ref,
    )
    if staged is None:
        return None
    previous_ref = await conn.fetchval(
        """SELECT credential_ref FROM ai_configs
           WHERE tenant_id=$1 AND level=$2 AND scope_id=$3""",
        tenant_id,
        proposal.level,
        proposal.scope_id,
    )
    await _upsert_ai_config(conn, proposal, now)
    await conn.execute(
        """UPDATE ai_key_secret_proposals
              SET status='consumed',secret_ref=NULL,
                  consumed_at=$3,updated_at=$3
            WHERE tenant_id=$1 AND id=$2""",
        tenant_id,
        proposal_id,
        now,
    )
    if previous_ref and previous_ref != proposal.secret_ref:
        await conn.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            previous_ref,
        )
    return _ai_config_from_proposal(proposal, now)


async def _upsert_ai_config(conn, proposal, now):
    await conn.execute(
        """INSERT INTO ai_configs
             (tenant_id,level,scope_id,provider,model,credential_ref,
              base_url,created_at,updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
           ON CONFLICT (tenant_id,level,scope_id) DO UPDATE SET
             provider=EXCLUDED.provider,
             model=EXCLUDED.model,
             credential_ref=EXCLUDED.credential_ref,
             base_url=EXCLUDED.base_url,
             updated_at=EXCLUDED.updated_at""",
        proposal.tenant_id,
        proposal.level,
        proposal.scope_id,
        proposal.provider,
        proposal.model,
        proposal.secret_ref,
        proposal.base_url,
        now,
    )


def _ai_config_from_proposal(proposal, now):
    return AiConfig(
        tenant_id=proposal.tenant_id,
        level=proposal.level,
        scope_id=proposal.scope_id,
        provider=proposal.provider,
        model=proposal.model,
        credential_ref=proposal.secret_ref,
        base_url=proposal.base_url,
        created_at=now,
        updated_at=now,
    )


__all__ = ["AiKeyProposalStorePG"]
