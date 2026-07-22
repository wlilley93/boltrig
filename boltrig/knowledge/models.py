"""Domain records for the canonical Knowledge catalogue."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
import uuid

from boltrig.kernel.idempotency import sensitive_key

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_SEARCH_LIMIT = 50
MAX_CONTEXT_ITEMS = 20
MAX_CONTEXT_CHARS = 80_000
EMBEDDING_DIM = 256


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class UploadSession:
    id: str
    tenant_id: str
    workspace_id: str | None
    title: str
    filename: str
    media_type: str
    owner_scope: str
    source_kind: str = "upload"
    source_ref: str | None = None
    staged_key: str | None = None
    digest: str | None = None
    byte_size: int | None = None
    status: str = "begun"
    asset_id: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Blob:
    digest: str
    tenant_id: str
    object_key: str
    byte_size: int
    media_type: str
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Asset:
    id: str
    tenant_id: str
    workspace_id: str | None
    title: str
    filename: str
    asset_type: str
    owner_scope: str
    current_revision_id: str
    source_kind: str
    source_ref: str | None = None
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Revision:
    id: str
    tenant_id: str
    asset_id: str
    blob_digest: str
    version: int
    media_type: str
    byte_size: int
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Representation:
    id: str
    tenant_id: str
    revision_id: str
    kind: str
    format: str
    generator: str
    generator_version: str
    content_hash: str
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class SourceOccurrence:
    id: str
    tenant_id: str
    asset_id: str
    source_kind: str
    external_id: str
    external_path: str | None = None
    observed_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Segment:
    id: str
    tenant_id: str
    asset_id: str
    revision_id: str
    representation_id: str
    sequence: int
    text: str
    locator: dict[str, Any]
    content_hash: str
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class Embedding:
    id: str
    tenant_id: str
    subject_type: str
    subject_id: str
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int
    distance_metric: str
    vector: tuple[float, ...]
    created_at: datetime = field(default_factory=now)


@dataclass(frozen=True)
class IngestionBundle:
    blob: Blob
    asset: Asset
    revision: Revision
    representation: Representation
    occurrence: SourceOccurrence
    segments: tuple[Segment, ...]
    embeddings: tuple[Embedding, ...]
    access_scopes: tuple[str, ...]


@dataclass(frozen=True)
class SearchHit:
    asset_id: str
    revision_id: str
    segment_id: str
    title: str
    filename: str
    text: str
    locator: dict[str, Any]
    score: float
    content_hash: str
    source_kind: str
    source_ref: str | None

    def public(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "citation": {
                "asset_id": self.asset_id,
                "revision_id": self.revision_id,
                "segment_id": self.segment_id,
                "title": self.title,
                "filename": self.filename,
                "locator": self.locator,
                "source_kind": self.source_kind,
                "source_ref": self.source_ref,
                "content_hash": self.content_hash,
            },
        }


@dataclass(frozen=True)
class Provider:
    id: str
    tenant_id: str
    display_name: str
    role: str
    enabled: bool
    bundled: bool
    health: str = "unknown"
    status: str = "available"
    last_error: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=now)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["updated_at"] = self.updated_at.isoformat()
        data["config"] = {
            key: value for key, value in self.config.items() if not sensitive_key(key)
        }
        return data


@dataclass(frozen=True)
class ProjectionStatus:
    tenant_id: str
    provider_id: str
    subject_type: str
    subject_id: str
    operation: str
    status: str
    projection_ref: str | None = None
    error: str | None = None
    updated_at: datetime = field(default_factory=now)
