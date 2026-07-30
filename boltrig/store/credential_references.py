"""Credential-reference persistence contracts and secret-free presence reads."""

from __future__ import annotations

from typing import Any, Protocol


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


__all__ = [
    "CredentialReferenceContract",
    "CredentialReferencePresenceMem",
    "CredentialReferencePresencePG",
]
