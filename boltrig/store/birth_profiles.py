"""Birth-profile startup receipt store contract and adapters."""

from __future__ import annotations

from .tenant_scope import bind_conn_to_tenant

from typing import Protocol

from boltrig.models import (
    BIRTH_PROFILE_MAX_RETURNED_RECEIPTS,
    BIRTH_PROFILE_RECEIPTS_PER_PROCESS,
    BirthProfileReceipt,
)


class BirthProfileStoreContract(Protocol):
    async def upsert_birth_profile_receipt(self, receipt: BirthProfileReceipt) -> None: ...

    async def list_birth_profile_receipts(self, tenant_id: str) -> list[BirthProfileReceipt]: ...


class BirthProfileStoreMem:
    async def upsert_birth_profile_receipt(self, receipt):
        key = (
            receipt.tenant_id,
            receipt.process_kind,
            receipt.instance_identity,
        )
        self._birth_profile_receipts[key] = receipt
        retained = sorted(
            (
                row
                for row in self._birth_profile_receipts.values()
                if row.tenant_id == receipt.tenant_id and row.process_kind == receipt.process_kind
            ),
            key=lambda row: (row.observed_at, row.instance_identity),
            reverse=True,
        )
        for expired in retained[BIRTH_PROFILE_RECEIPTS_PER_PROCESS:]:
            del self._birth_profile_receipts[
                (
                    expired.tenant_id,
                    expired.process_kind,
                    expired.instance_identity,
                )
            ]

    async def list_birth_profile_receipts(self, tenant_id):
        rows = [
            receipt
            for (row_tenant, _, _), receipt in self._birth_profile_receipts.items()
            if row_tenant == tenant_id
        ]
        rows.sort(key=lambda row: row.instance_identity, reverse=True)
        rows.sort(key=lambda row: row.observed_at, reverse=True)
        rows.sort(key=lambda row: row.process_kind)
        return rows[:BIRTH_PROFILE_MAX_RETURNED_RECEIPTS]


def _receipt(row):
    if row is None:
        return None
    return BirthProfileReceipt(
        tenant_id=row["tenant_id"],
        process_kind=row["process_kind"],
        instance_identity=row["instance_identity"],
        manifest_generation=row["manifest_generation"],
        addon_set_identity=row["addon_set_identity"],
        codex_provider_identity=row["codex_provider_identity"],
        codex_provider_state=row["codex_provider_state"],
        sensitive_role_identity=row["sensitive_role_identity"],
        sensitive_role_state=row["sensitive_role_state"],
        observed_at=row["observed_at"],
        expires_at=row["expires_at"],
        receipt_kind=row["receipt_kind"],
    )


class BirthProfileStorePG:
    async def upsert_birth_profile_receipt(self, receipt):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Startup publication has no request context. Bind the RLS GUC
                # from the validated receipt tenant inside this transaction.
                await bind_conn_to_tenant(
                    conn, receipt.tenant_id, pool=self._pool
                )
                # Serialize pruning for this tenant/process pair. Otherwise two
                # concurrent boots could each observe the pre-insert count and
                # leave the hard retention cap exceeded.
                await conn.execute(
                    """SELECT pg_advisory_xact_lock(
                         hashtext($1), hashtext($2)
                       )""",
                    receipt.tenant_id,
                    receipt.process_kind,
                )
                await conn.execute(
                    """INSERT INTO birth_profile_receipts
                 (tenant_id, process_kind, instance_identity,
                  manifest_generation, addon_set_identity,
                  codex_provider_identity, codex_provider_state,
                  sensitive_role_identity, sensitive_role_state,
                  receipt_kind, observed_at, expires_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (tenant_id, process_kind, instance_identity) DO UPDATE SET
                 manifest_generation=EXCLUDED.manifest_generation,
                 addon_set_identity=EXCLUDED.addon_set_identity,
                 codex_provider_identity=EXCLUDED.codex_provider_identity,
                 codex_provider_state=EXCLUDED.codex_provider_state,
                 sensitive_role_identity=EXCLUDED.sensitive_role_identity,
                 sensitive_role_state=EXCLUDED.sensitive_role_state,
                 receipt_kind=EXCLUDED.receipt_kind,
                 observed_at=EXCLUDED.observed_at,
                 expires_at=EXCLUDED.expires_at""",
                    receipt.tenant_id,
                    receipt.process_kind,
                    receipt.instance_identity,
                    receipt.manifest_generation,
                    receipt.addon_set_identity,
                    receipt.codex_provider_identity,
                    receipt.codex_provider_state,
                    receipt.sensitive_role_identity,
                    receipt.sensitive_role_state,
                    receipt.receipt_kind,
                    receipt.observed_at,
                    receipt.expires_at,
                )
                await conn.execute(
                    """DELETE FROM birth_profile_receipts
                       WHERE tenant_id=$1 AND process_kind=$2
                         AND instance_identity IN (
                           SELECT instance_identity
                           FROM birth_profile_receipts
                           WHERE tenant_id=$1 AND process_kind=$2
                           ORDER BY observed_at DESC, instance_identity DESC
                           OFFSET $3
                         )""",
                    receipt.tenant_id,
                    receipt.process_kind,
                    BIRTH_PROFILE_RECEIPTS_PER_PROCESS,
                )

    async def list_birth_profile_receipts(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM birth_profile_receipts
               WHERE tenant_id=$1
               ORDER BY process_kind, observed_at DESC, instance_identity DESC
               LIMIT $2""",
            tenant_id,
            BIRTH_PROFILE_MAX_RETURNED_RECEIPTS,
        )
        return [_receipt(row) for row in rows]


__all__ = [
    "BirthProfileStoreContract",
    "BirthProfileStoreMem",
    "BirthProfileStorePG",
]
