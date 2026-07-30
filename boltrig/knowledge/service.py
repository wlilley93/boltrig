"""Canonical Knowledge lifecycle and permission-first retrieval orchestration."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
import json
from typing import Any

from boltrig.identity.rbac import knowledge_scopes
from boltrig.memory.embeddings import HashingEmbedder

from .extraction import extract
from .models import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_ITEMS,
    MAX_SEARCH_LIMIT,
    MAX_UPLOAD_BYTES,
    Asset,
    Blob,
    Embedding,
    IngestionBundle,
    Representation,
    Revision,
    Segment,
    SourceOccurrence,
    UploadSession,
    new_id,
    now,
)
from .ports import StagedObject
from .projections import UNAVAILABLE_PROVIDER_IDS, UNAVAILABLE_PROVIDER_REASON
from .service_public import asset_type, projection_public, segment_public, stable_id


def permitted_scopes(context) -> list[str]:
    """Scopes derived from the authenticated principal (SEC-KNO-01) - never from
    caller-supplied ``extra`` keys; missing principal fields fail closed."""
    extra = context.extra or {}
    principal_scope = extra.get("principal_scope")
    return knowledge_scopes(
        context.actor,
        context.on_behalf_of,
        context.workspace_id,
        str(extra.get("principal_role") or ""),
        principal_scope if isinstance(principal_scope, dict) else None,
    )


class KnowledgeService:
    def __init__(self, repository, vault, projections, *, embedder=None) -> None:
        self.repository = repository
        self.vault = vault
        self.projections = projections
        self.embedder = embedder or HashingEmbedder()
        self._commit_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def begin_upload(self, params: dict[str, Any], context) -> dict[str, Any]:
        title = str(params.get("title") or "").strip()
        filename = str(params.get("filename") or "").strip()
        media_type = str(params.get("media_type") or "application/octet-stream").strip()
        if not title or len(title) > 500:
            raise ValueError("title is required and must be at most 500 characters")
        if not filename or len(filename) > 240 or "/" in filename or "\\" in filename:
            raise ValueError("filename must be a plain name of at most 240 characters")
        scopes = permitted_scopes(context)
        owner_scope = str(
            params.get("owner_scope") or f"user:{context.on_behalf_of or context.actor}"
        )
        if owner_scope not in scopes:
            raise PermissionError(f"owner scope {owner_scope!r} is not permitted")
        upload = UploadSession(
            id=new_id("upl"),
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            title=title,
            filename=filename,
            media_type=media_type[:200],
            owner_scope=owner_scope,
            source_kind=str(params.get("source_kind") or "upload")[:100],
            source_ref=(str(params["source_ref"])[:2_000] if params.get("source_ref") else None),
        )
        await self.repository.create_upload(upload)
        return {"upload_id": upload.id, "status": upload.status, "max_bytes": MAX_UPLOAD_BYTES}

    async def stage_upload(self, upload_id: str, data: bytes, context) -> dict[str, Any]:
        if not data:
            raise ValueError("upload body is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
        upload = await self.repository.get_upload(context.tenant_id, upload_id)
        if upload is None or upload.owner_scope not in permitted_scopes(context):
            raise LookupError("upload not found")
        staged = await self.vault.stage(context.tenant_id, upload_id, data)
        updated = await self.repository.set_upload_staged(context.tenant_id, upload_id, staged)
        return {
            "upload_id": updated.id,
            "status": updated.status,
            "digest": updated.digest,
            "byte_size": updated.byte_size,
        }

    async def commit_upload(self, upload_id: str, context) -> dict[str, Any]:
        upload = await self.repository.get_upload(context.tenant_id, upload_id)
        if upload is None or upload.owner_scope not in permitted_scopes(context):
            raise LookupError("upload not found")
        # Serialise concurrent commits of ONE upload so the replay check is atomic
        # with the ingestion save (the in-memory repository has no row lock;
        # Postgres also holds FOR UPDATE inside save_ingestion). Locks are kept,
        # not popped: one tiny entry per upload id, and a waiter may hold one.
        lock = self._commit_locks.setdefault((context.tenant_id, upload_id), asyncio.Lock())
        async with lock:
            upload = await self.repository.get_upload(context.tenant_id, upload_id)
            if upload.status == "committed" and upload.asset_id:
                return {"asset_id": upload.asset_id, "status": "committed", "replayed": True}
            if not upload.staged_key or not upload.digest or upload.byte_size is None:
                raise ValueError("upload has not been staged")
            data = await self.vault.read(upload.staged_key)
            if hashlib.sha256(data).hexdigest() != upload.digest or len(data) != upload.byte_size:
                raise ValueError("staged upload integrity check failed")
            extraction = extract(data, media_type=upload.media_type, filename=upload.filename)
            staged = StagedObject(upload.staged_key, upload.digest, upload.byte_size)
            object_key = await self.vault.commit(context.tenant_id, staged)
            bundle = self._bundle(upload, extraction, object_key)
            try:
                await self.repository.save_ingestion(context.tenant_id, upload_id, bundle)
            except ValueError:
                # Lost a cross-instance commit race (Postgres FOR UPDATE):
                # answer with the idempotent replay, not an error.
                latest = await self.repository.get_upload(context.tenant_id, upload_id)
                if latest is not None and latest.status == "committed" and latest.asset_id:
                    return {"asset_id": latest.asset_id, "status": "committed", "replayed": True}
                raise
        projections = await self.projections.compile(
            context.tenant_id, bundle.asset, bundle.segments, context
        )
        return {
            "asset_id": bundle.asset.id,
            "revision_id": bundle.revision.id,
            "status": "committed",
            "segment_count": len(bundle.segments),
            "digest": bundle.blob.digest,
            "projections": projections,
        }

    def _bundle(self, upload: UploadSession, extraction, object_key: str) -> IngestionBundle:
        asset_id, revision_id = new_id("ast"), new_id("rev")
        representation_id = stable_id("rep", revision_id, "plain_text")
        asset = Asset(
            id=asset_id,
            tenant_id=upload.tenant_id,
            workspace_id=upload.workspace_id,
            title=upload.title,
            filename=upload.filename,
            asset_type=asset_type(upload.media_type),
            owner_scope=upload.owner_scope,
            current_revision_id=revision_id,
            source_kind=upload.source_kind,
            source_ref=upload.source_ref,
        )
        revision = Revision(
            id=revision_id,
            tenant_id=upload.tenant_id,
            asset_id=asset_id,
            blob_digest=str(upload.digest),
            version=1,
            media_type=upload.media_type,
            byte_size=int(upload.byte_size or 0),
        )
        representation = Representation(
            id=representation_id,
            tenant_id=upload.tenant_id,
            revision_id=revision_id,
            kind="plain_text",
            format=extraction.format,
            generator=extraction.generator,
            generator_version=extraction.generator_version,
            content_hash=extraction.content_hash,
        )
        segments = tuple(
            self._segment(asset, revision, representation, index, part)
            for index, part in enumerate(extraction.parts, start=1)
        )
        occurrence = SourceOccurrence(
            id=stable_id("src", asset_id, upload.source_kind, upload.source_ref or upload.id),
            tenant_id=upload.tenant_id,
            asset_id=asset_id,
            source_kind=upload.source_kind,
            external_id=upload.source_ref or upload.id,
            external_path=upload.filename,
        )
        embeddings = tuple(self._embedding(segment) for segment in segments)
        scopes = {upload.owner_scope}
        if upload.workspace_id:
            scopes.add(f"workspace:{upload.workspace_id}")
        blob = Blob(
            digest=str(upload.digest),
            tenant_id=upload.tenant_id,
            object_key=object_key,
            byte_size=int(upload.byte_size or 0),
            media_type=upload.media_type,
        )
        return IngestionBundle(
            blob,
            asset,
            revision,
            representation,
            occurrence,
            segments,
            embeddings,
            tuple(scopes),
        )

    def _segment(self, asset, revision, representation, sequence, part) -> Segment:
        content_hash = hashlib.sha256(part.text.encode("utf-8")).hexdigest()
        return Segment(
            id=stable_id("seg", revision.id, str(sequence), content_hash),
            tenant_id=asset.tenant_id,
            asset_id=asset.id,
            revision_id=revision.id,
            representation_id=representation.id,
            sequence=sequence,
            text=part.text,
            locator=dict(part.locator),
            content_hash=content_hash,
        )

    def _embedding(self, segment: Segment) -> Embedding:
        model_name = str(getattr(self.embedder, "model", type(self.embedder).__name__))
        provider = "openai-compatible" if hasattr(self.embedder, "base_url") else "boltrig"
        vector = tuple(self.embedder.embed(segment.text))
        return Embedding(
            id=stable_id("emb", segment.id, provider, model_name, "1"),
            tenant_id=segment.tenant_id,
            subject_type="segment",
            subject_id=segment.id,
            model_provider=provider,
            model_name=model_name,
            model_version="1",
            dimensions=len(vector),
            distance_metric="cosine",
            vector=vector,
        )

    async def list_assets(self, params: dict[str, Any], context) -> dict[str, Any]:
        limit = min(max(int(params.get("limit", 50)), 1), 100)
        offset = min(max(int(params.get("offset", 0)), 0), 1_000_000)
        rows = await self.repository.list_assets(
            context.tenant_id, context.workspace_id, permitted_scopes(context), limit + 1, offset
        )
        return {
            "assets": rows[:limit],
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    async def get_asset(self, asset_id: str, context) -> dict[str, Any]:
        scopes = permitted_scopes(context)
        asset = await self.repository.get_asset(context.tenant_id, asset_id, scopes)
        if asset is None:
            raise LookupError("asset not found")
        segments = await self.repository.segments_for_asset(context.tenant_id, asset_id, scopes)
        provenance = await self.repository.provenance_for_asset(context.tenant_id, asset_id, scopes)
        projections = await self.repository.list_projections(context.tenant_id, asset_id)
        return {
            "asset": {
                "id": asset.id,
                "title": asset.title,
                "filename": asset.filename,
                "asset_type": asset.asset_type,
                "revision_id": asset.current_revision_id,
                "source_kind": asset.source_kind,
                "source_ref": asset.source_ref,
                "created_at": asset.created_at.isoformat(),
            },
            "segments": [segment_public(segment) for segment in segments],
            "provenance": provenance,
            "projections": [projection_public(row) for row in projections],
        }

    async def original(self, asset_id: str, context) -> dict[str, Any]:
        result = await self.repository.original_for_asset(
            context.tenant_id, asset_id, permitted_scopes(context)
        )
        if result is None:
            raise LookupError("asset not found")
        key, media_type, filename = result
        data = await self.vault.read(key)
        return {
            "filename": filename,
            "media_type": media_type,
            "byte_size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }

    async def search(self, params: dict[str, Any], context) -> dict[str, Any]:
        query = str(params.get("query") or "").strip()[:2_000]
        limit = min(max(int(params.get("limit", 10)), 1), MAX_SEARCH_LIMIT)
        vector = self.embedder.embed(query)
        hits = await self.repository.search(
            context.tenant_id, context.workspace_id, permitted_scopes(context), query, vector, limit
        )
        return {"query": query, "hits": [hit.public() for hit in hits]}

    async def build_context(self, params: dict[str, Any], context) -> dict[str, Any]:
        limit = min(int(params.get("limit", 8)), MAX_CONTEXT_ITEMS)
        search = await self.search({"query": params.get("query", ""), "limit": limit}, context)
        items, chars = [], 0
        for hit in search["hits"]:
            text = str(hit["text"])
            if chars + len(text) > MAX_CONTEXT_CHARS:
                break
            items.append(
                {
                    "content": text,
                    "citation": hit["citation"],
                    "authority": "original_revision",
                    "trust": "untrusted_source_content",
                    "score": hit["score"],
                }
            )
            chars += len(text)
        envelope = {
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "query": search["query"],
            "items": items,
            "omissions": {"context_limit": len(search["hits"]) - len(items)},
        }
        envelope["context_hash"] = hashlib.sha256(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return envelope

    async def erase_asset(self, asset_id: str, context) -> dict[str, Any]:
        scopes = permitted_scopes(context)
        asset = await self.repository.get_asset(context.tenant_id, asset_id, scopes)
        if asset is None:
            raise LookupError("asset not found")
        segments = await self.repository.segments_for_asset(context.tenant_id, asset_id, scopes)
        blob_keys, segment_ids = await self.repository.erase_asset(
            context.tenant_id, asset_id, scopes
        )
        for key in blob_keys:
            await self.vault.erase(key)
        projections = await self.projections.erase(context.tenant_id, asset_id, segment_ids)
        return {
            "asset_id": asset_id,
            "status": "erased",
            "segments_erased": len(segments),
            "objects_erased": len(blob_keys),
            "projections": projections,
        }

    async def list_providers(self, context) -> dict[str, Any]:
        await self.projections.refresh_health(context.tenant_id)
        providers = await self.repository.list_providers(context.tenant_id)
        return {"providers": [provider.public() for provider in providers]}

    async def set_provider(self, provider_id: str, enabled: bool, context) -> dict[str, Any]:
        provider = await self.repository.get_provider(context.tenant_id, provider_id)
        if provider is None:
            raise LookupError("provider not found")
        if provider_id in UNAVAILABLE_PROVIDER_IDS:
            if enabled:
                raise ValueError(
                    f"{provider.display_name} is unavailable: {UNAVAILABLE_PROVIDER_REASON}"
                )
            updated = replace(
                provider,
                enabled=False,
                health="unavailable",
                status="unavailable",
                last_error=UNAVAILABLE_PROVIDER_REASON,
                updated_at=now(),
            )
            await self.repository.save_provider(updated)
            return {"provider": updated.public()}
        updated = replace(
            provider,
            enabled=enabled,
            status="enabled" if enabled else "disabled",
            last_error=None if not enabled else provider.last_error,
            updated_at=now(),
        )
        await self.repository.save_provider(updated)
        if provider_id == "cognee" and enabled:
            await self.projections.refresh_health(context.tenant_id)
            updated = await self.repository.get_provider(context.tenant_id, provider_id) or updated
        return {"provider": updated.public()}
