"""Tenant-fenced in-memory KnowledgeRepository for tests and personal demos."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import re

from boltrig.memory.embeddings import cosine

from .models import (
    Asset,
    Blob,
    Embedding,
    IngestionBundle,
    ProjectionStatus,
    Provider,
    SearchHit,
    Segment,
    UploadSession,
)
from .ports import StagedObject


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self._uploads: dict[tuple[str, str], UploadSession] = {}
        self._blobs: dict[tuple[str, str], Blob] = {}
        self._assets: dict[tuple[str, str], Asset] = {}
        self._revisions: dict[tuple[str, str], object] = {}
        self._representations: dict[tuple[str, str], object] = {}
        self._occurrences: dict[tuple[str, str], object] = {}
        self._segments: dict[tuple[str, str], Segment] = {}
        self._embeddings: dict[tuple[str, str], Embedding] = {}
        self._access: dict[tuple[str, str], set[str]] = {}
        self._providers: dict[tuple[str, str], Provider] = {}
        self._projections: dict[tuple[str, str, str, str], ProjectionStatus] = {}
        self._lock = asyncio.Lock()

    async def create_upload(self, upload: UploadSession) -> None:
        async with self._lock:
            key = (upload.tenant_id, upload.id)
            if key in self._uploads:
                raise ValueError("upload already exists")
            self._uploads[key] = upload

    async def get_upload(self, tenant_id: str, upload_id: str) -> UploadSession | None:
        return self._uploads.get((tenant_id, upload_id))

    async def set_upload_staged(
        self, tenant_id: str, upload_id: str, staged: StagedObject
    ) -> UploadSession:
        async with self._lock:
            upload = self._uploads.get((tenant_id, upload_id))
            if upload is None:
                raise LookupError("upload not found")
            if upload.status not in {"begun", "staged"}:
                raise ValueError("upload cannot be staged in its current state")
            updated = replace(
                upload,
                staged_key=staged.key,
                digest=staged.digest,
                byte_size=staged.byte_size,
                status="staged",
            )
            self._uploads[(tenant_id, upload_id)] = updated
            return updated

    async def save_ingestion(
        self, tenant_id: str, upload_id: str, bundle: IngestionBundle
    ) -> None:
        async with self._lock:
            upload = self._uploads.get((tenant_id, upload_id))
            if upload is None or upload.status != "staged":
                raise ValueError("upload is not ready to commit")
            if bundle.asset.tenant_id != tenant_id or bundle.blob.tenant_id != tenant_id:
                raise ValueError("bundle crosses tenant boundary")
            self._blobs[(tenant_id, bundle.blob.digest)] = bundle.blob
            self._assets[(tenant_id, bundle.asset.id)] = bundle.asset
            self._revisions[(tenant_id, bundle.revision.id)] = bundle.revision
            key = (tenant_id, bundle.representation.id)
            self._representations[key] = bundle.representation
            self._occurrences[(tenant_id, bundle.occurrence.id)] = bundle.occurrence
            for segment in bundle.segments:
                self._segments[(tenant_id, segment.id)] = segment
            for embedding in bundle.embeddings:
                self._embeddings[(tenant_id, embedding.subject_id)] = embedding
            self._access[(tenant_id, bundle.asset.id)] = set(bundle.access_scopes)
            self._uploads[(tenant_id, upload_id)] = replace(
                upload, status="committed", asset_id=bundle.asset.id
            )

    def _allowed(self, tenant_id: str, asset_id: str, scopes: list[str]) -> bool:
        allowed = self._access.get((tenant_id, asset_id), set())
        return bool(allowed.intersection(scopes))

    async def get_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> Asset | None:
        if not self._allowed(tenant_id, asset_id, scopes):
            return None
        return self._assets.get((tenant_id, asset_id))

    async def list_assets(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        limit: int,
        offset: int = 0,
    ) -> list[dict]:
        assets = [
            asset
            for (tenant, _), asset in self._assets.items()
            if tenant == tenant_id
            and (workspace_id is None or asset.workspace_id == workspace_id)
            and self._allowed(tenant_id, asset.id, scopes)
        ]
        assets.sort(key=lambda item: item.created_at, reverse=True)
        return [
            self._asset_public(asset) for asset in assets[offset : offset + limit]
        ]

    def _asset_public(self, asset: Asset) -> dict:
        count = sum(
            1
            for (tenant, _), segment in self._segments.items()
            if tenant == asset.tenant_id and segment.asset_id == asset.id
        )
        return {
            "id": asset.id,
            "title": asset.title,
            "filename": asset.filename,
            "asset_type": asset.asset_type,
            "workspace_id": asset.workspace_id,
            "revision_id": asset.current_revision_id,
            "source_kind": asset.source_kind,
            "source_ref": asset.source_ref,
            "segment_count": count,
            "created_at": asset.created_at.isoformat(),
        }

    async def segments_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> list[Segment]:
        if not self._allowed(tenant_id, asset_id, scopes):
            return []
        rows = [
            segment
            for (tenant, _), segment in self._segments.items()
            if tenant == tenant_id and segment.asset_id == asset_id
        ]
        return sorted(rows, key=lambda item: item.sequence)

    async def provenance_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> dict:
        if not self._allowed(tenant_id, asset_id, scopes):
            return {"occurrences": [], "embeddings": []}
        segment_ids = {
            segment.id
            for (tenant, _), segment in self._segments.items()
            if tenant == tenant_id and segment.asset_id == asset_id
        }
        occurrences = [
            {
                "id": row.id,
                "source_kind": row.source_kind,
                "external_id": row.external_id,
                "external_path": row.external_path,
                "observed_at": row.observed_at.isoformat(),
            }
            for (tenant, _), row in self._occurrences.items()
            if tenant == tenant_id and row.asset_id == asset_id
        ]
        embeddings = [
            _embedding_public(row)
            for (tenant, subject_id), row in self._embeddings.items()
            if tenant == tenant_id and subject_id in segment_ids
        ]
        return {"occurrences": occurrences, "embeddings": embeddings}

    async def original_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[str, str, str] | None:
        asset = await self.get_asset(tenant_id, asset_id, scopes)
        if asset is None:
            return None
        revision = self._revisions.get((tenant_id, asset.current_revision_id))
        digest = getattr(revision, "blob_digest", None)
        blob = self._blobs.get((tenant_id, digest)) if digest else None
        if blob is None:
            return None
        return blob.object_key, blob.media_type, asset.filename

    async def search(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        query: str,
        embedding: list[float],
        limit: int,
    ) -> list[SearchHit]:
        tokens = set(re.findall(r"[\w]+", query.lower()))
        rows: list[SearchHit] = []
        for (tenant, _), segment in self._segments.items():
            asset = self._assets.get((tenant_id, segment.asset_id))
            if tenant != tenant_id or asset is None:
                continue
            if workspace_id is not None and asset.workspace_id != workspace_id:
                continue
            if not self._allowed(tenant_id, asset.id, scopes):
                continue
            stored = self._embeddings.get((tenant_id, segment.id))
            score = self._score(asset, segment, stored, query, tokens, embedding)
            if query and score <= 0:
                continue
            rows.append(self._hit(asset, segment, score))
        rows.sort(key=lambda hit: (hit.score, hit.asset_id, hit.segment_id), reverse=True)
        return rows[:limit]

    @staticmethod
    def _score(
        asset: Asset,
        segment: Segment,
        stored: Embedding | None,
        query: str,
        tokens: set[str],
        embedding: list[float],
    ) -> float:
        title = asset.title.lower()
        text = segment.text.lower()
        lexical = sum(1.0 for token in tokens if token in text)
        title_match = 2.0 if query and query.lower() in title else 0.0
        vector = (
            max(0.0, cosine(embedding, list(stored.vector)))
            if query and stored is not None
            else 0.0
        )
        return round(title_match + lexical + (0.35 * vector), 6)

    @staticmethod
    def _hit(asset: Asset, segment: Segment, score: float) -> SearchHit:
        return SearchHit(
            asset_id=asset.id,
            revision_id=segment.revision_id,
            segment_id=segment.id,
            title=asset.title,
            filename=asset.filename,
            text=segment.text,
            locator=segment.locator,
            score=score,
            content_hash=segment.content_hash,
            source_kind=asset.source_kind,
            source_ref=asset.source_ref,
        )

    async def erase_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[list[str], list[str]]:
        async with self._lock:
            if not self._allowed(tenant_id, asset_id, scopes):
                return [], []
            asset = self._assets.pop((tenant_id, asset_id), None)
            if asset is None:
                return [], []
            segment_ids = [
                segment.id
                for (tenant, _), segment in self._segments.items()
                if tenant == tenant_id and segment.asset_id == asset_id
            ]
            for segment_id in segment_ids:
                self._segments.pop((tenant_id, segment_id), None)
                self._embeddings.pop((tenant_id, segment_id), None)
            revision = self._revisions.pop((tenant_id, asset.current_revision_id), None)
            for key, representation in list(self._representations.items()):
                if key[0] == tenant_id and getattr(representation, "revision_id", None) == asset.current_revision_id:
                    self._representations.pop(key, None)
            self._access.pop((tenant_id, asset_id), None)
            for key, occurrence in list(self._occurrences.items()):
                if key[0] == tenant_id and getattr(occurrence, "asset_id", None) == asset_id:
                    self._occurrences.pop(key, None)
            blob_keys: list[str] = []
            digest = getattr(revision, "blob_digest", None)
            still_used = any(
                getattr(row, "blob_digest", None) == digest
                for (tenant, _), row in self._revisions.items()
                if tenant == tenant_id
            )
            if digest and not still_used:
                blob = self._blobs.pop((tenant_id, digest), None)
                if blob is not None:
                    blob_keys.append(blob.object_key)
            return blob_keys, segment_ids

    async def ensure_providers(self, tenant_id: str, providers: list[Provider]) -> None:
        async with self._lock:
            for provider in providers:
                self._providers.setdefault((tenant_id, provider.id), provider)

    async def list_providers(self, tenant_id: str) -> list[Provider]:
        rows = [row for (tenant, _), row in self._providers.items() if tenant == tenant_id]
        return sorted(rows, key=lambda item: (not item.bundled, item.display_name))

    async def get_provider(self, tenant_id: str, provider_id: str) -> Provider | None:
        return self._providers.get((tenant_id, provider_id))

    async def save_provider(self, provider: Provider) -> None:
        self._providers[(provider.tenant_id, provider.id)] = provider

    async def save_projection(self, status: ProjectionStatus) -> None:
        key = (status.tenant_id, status.provider_id, status.subject_id, status.operation)
        self._projections[key] = status

    async def list_projections(
        self, tenant_id: str, subject_id: str | None = None
    ) -> list[ProjectionStatus]:
        rows = [
            row
            for (tenant, _, subject, _), row in self._projections.items()
            if tenant == tenant_id and (subject_id is None or subject == subject_id)
        ]
        return sorted(rows, key=lambda item: item.updated_at, reverse=True)


def _embedding_public(row: Embedding) -> dict:
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "model_provider": row.model_provider,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "dimensions": row.dimensions,
        "distance_metric": row.distance_metric,
        "created_at": row.created_at.isoformat(),
    }
