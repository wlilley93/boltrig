"""Read-scoped persistence contract for immutable Worker artifacts."""

from __future__ import annotations

from typing import Protocol

from boltrig.models.artifacts import Artifact


class ArtifactStoreContract(Protocol):
    async def record_artifact(self, artifact: Artifact, content: bytes) -> bool:
        """Internal producer seam; no HTTP route delegates caller bytes here."""
        ...

    async def get_artifact_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> Artifact | None: ...

    async def list_artifacts_scoped(
        self,
        tenant_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
        conversation_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> list[Artifact]: ...

    async def get_artifact_download_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> tuple[Artifact, bytes] | None: ...
