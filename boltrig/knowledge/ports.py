"""Infrastructure ports owned by the Knowledge extension."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .models import (
    Asset,
    IngestionBundle,
    ProjectionStatus,
    Provider,
    SearchHit,
    Segment,
    UploadSession,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


def safe_id(value: str, label: str) -> str:
    """Validate a tenant/upload id before it becomes a vault key segment."""
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class StagedObject:
    key: str
    digest: str
    byte_size: int


class ObjectVault(Protocol):
    async def stage(self, tenant_id: str, upload_id: str, data: bytes) -> StagedObject: ...

    async def commit(self, tenant_id: str, staged: StagedObject) -> str: ...

    async def read(self, object_key: str) -> bytes: ...

    async def erase(self, object_key: str) -> None: ...


class KnowledgeRepository(Protocol):
    async def create_upload(self, upload: UploadSession) -> None: ...

    async def get_upload(self, tenant_id: str, upload_id: str) -> UploadSession | None: ...

    async def set_upload_staged(
        self, tenant_id: str, upload_id: str, staged: StagedObject
    ) -> UploadSession: ...

    async def save_ingestion(
        self, tenant_id: str, upload_id: str, bundle: IngestionBundle
    ) -> None: ...

    async def get_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> Asset | None: ...

    async def list_assets(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        limit: int,
        offset: int = 0,
    ) -> list[dict]: ...

    async def segments_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> list[Segment]: ...

    async def provenance_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> dict: ...

    async def original_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[str, str, str] | None: ...

    async def search(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        query: str,
        embedding: list[float],
        limit: int,
    ) -> list[SearchHit]: ...

    async def erase_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[list[str], list[str]]: ...

    async def ensure_providers(self, tenant_id: str, providers: list[Provider]) -> None: ...

    async def list_providers(self, tenant_id: str) -> list[Provider]: ...

    async def get_provider(self, tenant_id: str, provider_id: str) -> Provider | None: ...

    async def save_provider(self, provider: Provider) -> None: ...

    async def save_projection(self, status: ProjectionStatus) -> None: ...

    async def list_projections(
        self, tenant_id: str, subject_id: str | None = None
    ) -> list[ProjectionStatus]: ...
