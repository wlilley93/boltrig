"""Atomic idempotency-claim persistence for memory and PostgreSQL stores."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from boltrig.models import utcnow

from .idempotency_contract import IdempotencyClaim, IdempotencyClaimStatus


def _bound(
    actor: str,
    on_behalf_of: str | None,
    workspace_id: str | None,
    noun: str,
    verb: str,
    request_hash: str,
) -> dict[str, str | None]:
    return {
        "actor": actor,
        "on_behalf_of": on_behalf_of,
        "workspace_id": workspace_id,
        "noun": noun,
        "verb": verb,
        "request_hash": request_hash,
    }


class IdempotencyStoreMem:
    _idem: dict[tuple[str, str], dict[str, Any]]

    async def idempotency_claim(
        self,
        tenant_id,
        key,
        *,
        actor,
        on_behalf_of,
        workspace_id,
        noun,
        verb,
        request_hash,
        owner_token,
        lease_seconds,
    ):
        now = utcnow()
        bound = _bound(actor, on_behalf_of, workspace_id, noun, verb, request_hash)
        record = self._idem.get((tenant_id, key))
        if record is None:
            self._idem[(tenant_id, key)] = {
                **bound,
                "status": "claimed",
                "owner_token": owner_token,
                "lease_expires_at": now + timedelta(seconds=max(0, lease_seconds)),
                "result": None,
            }
            return IdempotencyClaim(IdempotencyClaimStatus.ACQUIRED)
        if any(record.get(name) != value for name, value in bound.items()):
            return IdempotencyClaim(IdempotencyClaimStatus.MISMATCH)
        if record["status"] == "completed":
            return IdempotencyClaim(
                IdempotencyClaimStatus.COMPLETED, copy.deepcopy(record["result"])
            )
        if record["status"] == "claimed" and record["lease_expires_at"] <= now:
            record.update(
                owner_token=owner_token,
                lease_expires_at=now + timedelta(seconds=max(0, lease_seconds)),
            )
            return IdempotencyClaim(IdempotencyClaimStatus.ACQUIRED)
        if record["status"] == "executing" and record["lease_expires_at"] <= now:
            record["status"] = "uncertain"
            return IdempotencyClaim(IdempotencyClaimStatus.UNCERTAIN)
        if record["status"] in {"claimed", "executing"}:
            return IdempotencyClaim(IdempotencyClaimStatus.IN_PROGRESS)
        return IdempotencyClaim(IdempotencyClaimStatus(record["status"]))

    async def idempotency_start(self, tenant_id, key, owner_token, lease_seconds):
        record = self._idem.get((tenant_id, key))
        if not _owned(record, owner_token, "claimed"):
            return False
        record["status"] = "executing"
        record["lease_expires_at"] = utcnow() + timedelta(seconds=max(0, lease_seconds))
        return True

    async def idempotency_release(self, tenant_id, key, owner_token):
        record = self._idem.get((tenant_id, key))
        if not _owned(record, owner_token, "claimed"):
            return False
        del self._idem[(tenant_id, key)]
        return True

    async def idempotency_complete(self, tenant_id, key, owner_token, result):
        record = self._idem.get((tenant_id, key))
        if not _owned(record, owner_token, "executing"):
            return False
        record.update(
            status="completed",
            owner_token=None,
            lease_expires_at=None,
            result=copy.deepcopy(result),
        )
        return True

    async def idempotency_uncacheable(self, tenant_id, key, owner_token):
        record = self._idem.get((tenant_id, key))
        if not _owned(record, owner_token, "executing"):
            return False
        record.update(status="uncacheable", owner_token=None, lease_expires_at=None, result=None)
        return True


def _owned(record: dict[str, Any] | None, owner_token: str, status: str) -> bool:
    return bool(
        record is not None and record["status"] == status and record["owner_token"] == owner_token
    )


class IdempotencyStorePG:
    async def idempotency_claim(
        self,
        tenant_id,
        key,
        *,
        actor,
        on_behalf_of,
        workspace_id,
        noun,
        verb,
        request_hash,
        owner_token,
        lease_seconds,
    ):
        bound = (actor, on_behalf_of, workspace_id, noun, verb, request_hash)
        async with self.with_tenant(tenant_id) as conn:
            inserted = await conn.fetchrow(
                """INSERT INTO idempotency_keys
                     (tenant_id, key, actor, on_behalf_of, workspace_id, noun, verb,
                      request_hash, status, owner_token, lease_expires_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'claimed',$9,
                           now() + $10::int * interval '1 second')
                   ON CONFLICT (tenant_id, key) DO NOTHING RETURNING key""",
                tenant_id,
                key,
                *bound,
                owner_token,
                max(0, lease_seconds),
            )
            if inserted is not None:
                return IdempotencyClaim(IdempotencyClaimStatus.ACQUIRED)
            row = await conn.fetchrow(
                """SELECT *, lease_expires_at <= now() AS lease_expired
                     FROM idempotency_keys
                    WHERE tenant_id=$1 AND key=$2 FOR UPDATE""",
                tenant_id,
                key,
            )
            if _pg_bound(row) != bound:
                return IdempotencyClaim(IdempotencyClaimStatus.MISMATCH)
            return await self._existing_claim(conn, row, tenant_id, key, owner_token, lease_seconds)

    async def _existing_claim(
        self,
        conn,
        row,
        tenant_id,
        key,
        owner_token,
        lease_seconds,
    ):
        if row["status"] == "completed":
            return IdempotencyClaim(IdempotencyClaimStatus.COMPLETED, row["result"])
        if row["status"] == "claimed" and row["lease_expired"]:
            await conn.execute(
                """UPDATE idempotency_keys SET owner_token=$3,
                          lease_expires_at=now() + $4::int * interval '1 second',
                          updated_at=now() WHERE tenant_id=$1 AND key=$2""",
                tenant_id,
                key,
                owner_token,
                max(0, lease_seconds),
            )
            return IdempotencyClaim(IdempotencyClaimStatus.ACQUIRED)
        if row["status"] == "executing" and row["lease_expired"]:
            await conn.execute(
                """UPDATE idempotency_keys SET status='uncertain', updated_at=now()
                    WHERE tenant_id=$1 AND key=$2""",
                tenant_id,
                key,
            )
            return IdempotencyClaim(IdempotencyClaimStatus.UNCERTAIN)
        if row["status"] in {"claimed", "executing"}:
            return IdempotencyClaim(IdempotencyClaimStatus.IN_PROGRESS)
        return IdempotencyClaim(IdempotencyClaimStatus(row["status"]))

    async def idempotency_start(self, tenant_id, key, owner_token, lease_seconds):
        return await self._transition(
            """UPDATE idempotency_keys SET status='executing',
                      lease_expires_at=now() + $4::int * interval '1 second',
                      updated_at=now()
                WHERE tenant_id=$1 AND key=$2 AND status='claimed' AND owner_token=$3
                RETURNING key""",
            tenant_id,
            key,
            owner_token,
            max(0, lease_seconds),
        )

    async def idempotency_release(self, tenant_id, key, owner_token):
        return await self._transition(
            """DELETE FROM idempotency_keys
                WHERE tenant_id=$1 AND key=$2 AND status='claimed' AND owner_token=$3
                RETURNING key""",
            tenant_id,
            key,
            owner_token,
        )

    async def idempotency_complete(self, tenant_id, key, owner_token, result):
        return await self._transition(
            """UPDATE idempotency_keys SET status='completed', result=$4,
                      owner_token=NULL, lease_expires_at=NULL, updated_at=now()
                WHERE tenant_id=$1 AND key=$2 AND status='executing' AND owner_token=$3
                RETURNING key""",
            tenant_id,
            key,
            owner_token,
            result,
        )

    async def idempotency_uncacheable(self, tenant_id, key, owner_token):
        return await self._transition(
            """UPDATE idempotency_keys SET status='uncacheable', result=NULL,
                      owner_token=NULL, lease_expires_at=NULL, updated_at=now()
                WHERE tenant_id=$1 AND key=$2 AND status='executing' AND owner_token=$3
                RETURNING key""",
            tenant_id,
            key,
            owner_token,
        )

    async def _transition(self, query: str, *args: Any) -> bool:
        # Bind the tenant explicitly (args[0] is tenant_id in every caller), like
        # idempotency_claim does: a background caller with no request contextvar
        # would otherwise fail-close to an empty GUC under RLS after acquiring.
        async with self.with_tenant(args[0]) as conn:
            return await conn.fetchrow(query, *args) is not None


def _pg_bound(row: Any) -> tuple[Any, ...]:
    names = ("actor", "on_behalf_of", "workspace_id", "noun", "verb", "request_hash")
    return tuple(row[name] for name in names)
