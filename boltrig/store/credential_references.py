"""Credential-reference persistence contracts and secret-free presence reads.

Also hosts the core get/set/delete credential-ref partials (arc-1 structural
move from ``store/postgres.py`` + ``store/memory.py``; sealed at rest per
SEC-04 - see ``store/sealing.py``). PG host: ``self._pool``; Mem host:
``self._creds``. Public surface unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from .sealing import seal_ref, unseal_ref


class CredentialReferenceContract(Protocol):
    """The credential-reference methods required by the kernel store seam."""

    async def get_credential_ref(
        self, tenant_id: str, cred_id: str
    ) -> dict[str, Any] | None: ...

    async def has_credential_ref(self, tenant_id: str, cred_id: str) -> bool:
        """Check row presence without reading or unsealing credential data."""
        ...

    async def set_credential_ref(
        self, tenant_id: str, cred_id: str, ref: dict[str, Any]
    ) -> None:
        """Persist a tenant-scoped reference through the at-rest sealing seam."""
        ...

    async def delete_credential_ref(self, tenant_id: str, cred_id: str) -> None:
        """Delete one credential reference row.

        The caller checks that nothing else references the id first. The
        deletion itself is an idempotent tenant-scoped no-op when absent.
        """
        ...

    async def delete_credential_refs_for_run(
        self, tenant_id: str, run_id: str
    ) -> int:
        """Delete one run's tenant-scoped ephemeral reference rows.

        Rows carry the ``run:<run_id>:`` prefix minted by
        ``CredentialResolver.seal_run_scoped_value``.
        """
        ...


class CredentialReferencePresenceMem:
    """Presence projection for the in-memory credential-reference table."""

    _creds: dict[tuple[str, str], dict[str, Any]]

    async def has_credential_ref(self, tenant_id: str, cred_id: str) -> bool:
        return (tenant_id, cred_id) in self._creds


class CredentialReferencePresencePG:
    """Presence projection for PostgreSQL without selecting encrypted columns."""

    _pool: Any

    async def has_credential_ref(self, tenant_id: str, cred_id: str) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            cred_id,
        )
        return row is not None


class CredentialRefsStorePG:
    """Core credential-reference methods for ``PostgresStore``."""

    async def get_credential_ref(self, tenant_id, cred_id):
        row = await self._pool.fetchrow(
            "SELECT data, store, ref FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            tenant_id, cred_id,
        )
        if row is None:
            return None
        # A falsy-but-present data dict (e.g. a ref cleared to {}) round-trips as
        # written; only a NULL data column falls back to the store/ref pair.
        if row["data"] is not None:
            # Unseal transparently; legacy plaintext rows (no marker) pass through.
            return unseal_ref(row["data"])
        return {"store": row["store"], "ref": row["ref"]}

    async def set_credential_ref(self, tenant_id, cred_id, ref: dict) -> None:
        # Seal before persisting: credential_refs.data is ALWAYS an envelope
        # (ciphertext), never plaintext (SEC-04). The typed store/ref columns keep
        # the reference metadata (an env var name is not secret material).
        await self._pool.execute(
            """INSERT INTO credential_refs (id, tenant_id, store, ref, data, expires_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 store=EXCLUDED.store, ref=EXCLUDED.ref, data=EXCLUDED.data,
                 expires_at=EXCLUDED.expires_at, updated_at=now()""",
            cred_id, tenant_id, ref.get("store", "env"), ref.get("ref", ""), seal_ref(ref),
            ref.get("expires_at"),
        )

    async def delete_credential_ref(self, tenant_id: str, cred_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND id=$2", tenant_id, cred_id
        )

    async def delete_credential_refs_for_run(self, tenant_id: str, run_id: str) -> int:
        # strpos prefix match (no LIKE wildcards to escape): only the run-scoped
        # secure-input ids minted as ``run:<run_id>:<purpose>`` (SEC-181).
        result = await self._pool.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND strpos(id, $2) = 1",
            tenant_id, f"run:{run_id}:",
        )
        return int(result.rsplit(" ", 1)[-1])


class CredentialRefsStoreMem:
    """Core credential-reference methods for ``InMemoryStore``."""

    async def get_credential_ref(self, tenant_id, cred_id):
        ref = self._creds.get((tenant_id, cred_id))
        # Unseal transparently; legacy plaintext rows (no marker) pass through.
        return unseal_ref(ref) if ref is not None else None

    async def set_credential_ref(self, tenant_id: str, cred_id: str, ref: dict) -> None:
        self._creds[(tenant_id, cred_id)] = seal_ref(ref)

    async def delete_credential_ref(self, tenant_id: str, cred_id: str) -> None:
        self._creds.pop((tenant_id, cred_id), None)

    async def delete_credential_refs_for_run(self, tenant_id: str, run_id: str) -> int:
        prefix = f"run:{run_id}:"
        doomed = [key for key in self._creds if key[0] == tenant_id and key[1].startswith(prefix)]
        for key in doomed:
            del self._creds[key]
        return len(doomed)


__all__ = [
    "CredentialReferenceContract",
    "CredentialReferencePresenceMem",
    "CredentialReferencePresencePG",
    "CredentialRefsStoreMem",
    "CredentialRefsStorePG",
]
