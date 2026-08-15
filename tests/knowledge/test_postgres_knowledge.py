from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest

from boltrig.knowledge.filesystem_vault import FilesystemObjectVault
from boltrig.knowledge.postgres_repository import PostgresKnowledgeRepository
from boltrig.knowledge.projections import provider_defaults
from boltrig.knowledge.service import KnowledgeService
from boltrig.models import GrantSet, InvocationContext
from boltrig.store import PostgresStore

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL")


class _NoopProjections:
    async def compile(self, tenant_id, asset, segments, context):
        return []

    async def erase(self, tenant_id, asset_id, segment_ids, context=None):
        return []


def _context(
    tenant_id: str, user: str = "postgres-user", workspace: str | None = "workspace-a"
) -> InvocationContext:
    return InvocationContext(
        tenant_id=tenant_id,
        workspace_id=workspace,
        actor=user,
        actor_tier="human",
        grants=GrantSet.of(["knowledge.*"]),
    )


@_pg
@pytest.mark.invariant("KNO-01")
@pytest.mark.invariant("KNO-03")
async def test_postgres_knowledge_round_trip_provenance_search_and_erase(
    tmp_path: Path,
) -> None:
    tenant = f"kno-pg-{uuid.uuid4().hex}"
    store = await PostgresStore.connect(str(DSN))
    repository = PostgresKnowledgeRepository(store._pool)
    await repository.ensure_providers(tenant, provider_defaults(tenant))
    service = KnowledgeService(
        repository,
        FilesystemObjectVault(tmp_path / "vault"),
        _NoopProjections(),
    )
    context = _context(tenant)
    try:
        begun = await service.begin_upload(
            {
                "title": "Postgres source",
                "filename": "source.md",
                "media_type": "text/markdown",
            },
            context,
        )
        await service.stage_upload(begun["upload_id"], b"Durable source occurrence", context)
        committed = await service.commit_upload(begun["upload_id"], context)

        found = await service.search({"query": "source occurrence"}, context)
        assert found["hits"][0]["asset_id"] == committed["asset_id"]
        asset = await service.get_asset(committed["asset_id"], context)
        assert asset["provenance"]["occurrences"][0]["external_path"] == "source.md"
        assert asset["provenance"]["embeddings"][0]["model_version"] == "1"
        erased = await service.erase_asset(committed["asset_id"], context)
        assert erased["objects_erased"] == 1
        assert (await service.search({"query": "source occurrence"}, context))["hits"] == []
    finally:
        for query in (
            "DELETE FROM knowledge_projection_outbox WHERE tenant_id=$1",
            "DELETE FROM knowledge_jobs WHERE tenant_id=$1",
            "DELETE FROM knowledge_projection_statuses WHERE tenant_id=$1",
            "DELETE FROM knowledge_asset_access WHERE tenant_id=$1",
            "DELETE FROM knowledge_embeddings WHERE tenant_id=$1",
            "DELETE FROM knowledge_segments WHERE tenant_id=$1",
            "DELETE FROM knowledge_representations WHERE tenant_id=$1",
            "DELETE FROM knowledge_source_occurrences WHERE tenant_id=$1",
            "DELETE FROM knowledge_revisions WHERE tenant_id=$1",
            "DELETE FROM knowledge_assets WHERE tenant_id=$1",
            "DELETE FROM knowledge_uploads WHERE tenant_id=$1",
            "DELETE FROM knowledge_blobs WHERE tenant_id=$1",
            "DELETE FROM knowledge_providers WHERE tenant_id=$1",
        ):
            await store._pool.execute(query, tenant)
        await store.close()


@_pg
@pytest.mark.invariant("SEC-KNO-01")
async def test_postgres_retrieval_filters_access_before_returning_any_candidate(
    tmp_path: Path,
) -> None:
    tenant = f"kno-pg-{uuid.uuid4().hex}"
    store = await PostgresStore.connect(str(DSN))
    repository = PostgresKnowledgeRepository(store._pool)
    await repository.ensure_providers(tenant, provider_defaults(tenant))
    service = KnowledgeService(
        repository,
        FilesystemObjectVault(tmp_path / "vault"),
        _NoopProjections(),
    )
    owner = _context(tenant, user="owner-user", workspace=None)
    stranger = _context(tenant, user="stranger-user", workspace=None)
    try:
        begun = await service.begin_upload(
            {"title": "Private", "filename": "private.md", "media_type": "text/markdown"},
            owner,
        )
        await service.stage_upload(begun["upload_id"], b"Private codename albatross", owner)
        committed = await service.commit_upload(begun["upload_id"], owner)

        assert (await service.search({"query": "albatross"}, stranger))["hits"] == []
        with pytest.raises(LookupError, match="asset not found"):
            await service.get_asset(committed["asset_id"], stranger)
        with pytest.raises(LookupError, match="asset not found"):
            await service.original(committed["asset_id"], stranger)
    finally:
        for query in (
            "DELETE FROM knowledge_projection_outbox WHERE tenant_id=$1",
            "DELETE FROM knowledge_jobs WHERE tenant_id=$1",
            "DELETE FROM knowledge_projection_statuses WHERE tenant_id=$1",
            "DELETE FROM knowledge_asset_access WHERE tenant_id=$1",
            "DELETE FROM knowledge_embeddings WHERE tenant_id=$1",
            "DELETE FROM knowledge_segments WHERE tenant_id=$1",
            "DELETE FROM knowledge_representations WHERE tenant_id=$1",
            "DELETE FROM knowledge_source_occurrences WHERE tenant_id=$1",
            "DELETE FROM knowledge_revisions WHERE tenant_id=$1",
            "DELETE FROM knowledge_assets WHERE tenant_id=$1",
            "DELETE FROM knowledge_uploads WHERE tenant_id=$1",
            "DELETE FROM knowledge_blobs WHERE tenant_id=$1",
            "DELETE FROM knowledge_providers WHERE tenant_id=$1",
        ):
            await store._pool.execute(query, tenant)
        await store.close()
