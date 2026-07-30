"""Durable PostgreSQL KnowledgeRepository with tenant and access predicates."""

from __future__ import annotations

from .models import (
    Asset,
    IngestionBundle,
    ProjectionStatus,
    Provider,
    SearchHit,
    Segment,
    UploadSession,
)
from .ports import StagedObject
from .postgres_rows import (
    asset as _asset,
    asset_public as _asset_public,
    hit as _hit,
    projection as _projection,
    provider as _provider,
    segment as _segment,
    upload as _upload,
    vector as _vector,
)
from boltrig.store.tenant_scope import bind_tenant_on_store_methods

from .postgres_writes import insert_bundle


# The SECOND holder of an _RlsPool. PostgresStore's mixins are all covered by the
# same decorator applied there, but this repository sits outside that MRO, so it
# was missed: with BOLTRIG_RLS=1 the kernel got past model_endpoints and then died
# on `new row violates row-level security policy for table "knowledge_providers"`.
# Checked the whole tree for others - every other _RlsPool user IS a PostgresStore
# mixin, so these two decorations are the complete set.
@bind_tenant_on_store_methods
class PostgresKnowledgeRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create_upload(self, upload: UploadSession) -> None:
        await self._pool.execute(
            """
            INSERT INTO knowledge_uploads
              (tenant_id,id,workspace_id,title,filename,media_type,owner_scope,
               source_kind,source_ref,status,created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            upload.tenant_id, upload.id, upload.workspace_id, upload.title,
            upload.filename, upload.media_type, upload.owner_scope, upload.source_kind,
            upload.source_ref, upload.status, upload.created_at,
        )

    async def get_upload(self, tenant_id: str, upload_id: str) -> UploadSession | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM knowledge_uploads WHERE tenant_id=$1 AND id=$2",
            tenant_id, upload_id,
        )
        return _upload(row) if row else None

    async def set_upload_staged(
        self, tenant_id: str, upload_id: str, staged: StagedObject
    ) -> UploadSession:
        row = await self._pool.fetchrow(
            """
            UPDATE knowledge_uploads
            SET staged_key=$3,digest=$4,byte_size=$5,status='staged',updated_at=now()
            WHERE tenant_id=$1 AND id=$2 AND status IN ('begun','staged')
            RETURNING *
            """,
            tenant_id, upload_id, staged.key, staged.digest, staged.byte_size,
        )
        if row is None:
            raise LookupError("upload not found or cannot be staged")
        return _upload(row)

    async def save_ingestion(
        self, tenant_id: str, upload_id: str, bundle: IngestionBundle
    ) -> None:
        pool = getattr(self._pool, "_pool", self._pool)
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id',$1,true)", tenant_id)
                status = await connection.fetchval(
                    "SELECT status FROM knowledge_uploads WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    tenant_id, upload_id,
                )
                if status != "staged":
                    raise ValueError("upload is not ready to commit")
                await insert_bundle(connection, bundle)
                await connection.execute(
                    """
                    UPDATE knowledge_uploads SET status='committed',asset_id=$3,updated_at=now()
                    WHERE tenant_id=$1 AND id=$2
                    """,
                    tenant_id, upload_id, bundle.asset.id,
                )

    async def get_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> Asset | None:
        row = await self._pool.fetchrow(
            """
            SELECT a.* FROM knowledge_assets a
            WHERE a.tenant_id=$1 AND a.id=$2 AND a.deleted_at IS NULL
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=a.tenant_id AND x.asset_id=a.id
                            AND x.scope=ANY($3::text[]))
            """,
            tenant_id, asset_id, scopes,
        )
        return _asset(row) if row else None

    async def list_assets(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        limit: int,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT a.*,count(s.id)::int AS segment_count
            FROM knowledge_assets a
            LEFT JOIN knowledge_segments s
              ON s.tenant_id=a.tenant_id AND s.asset_id=a.id
            WHERE a.tenant_id=$1 AND a.deleted_at IS NULL
              AND ($2::text IS NULL OR a.workspace_id=$2)
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=a.tenant_id AND x.asset_id=a.id
                            AND x.scope=ANY($3::text[]))
            GROUP BY a.tenant_id,a.id ORDER BY a.created_at DESC LIMIT $4 OFFSET $5
            """,
            tenant_id, workspace_id, scopes, limit, offset,
        )
        return [_asset_public(row) for row in rows]

    async def segments_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> list[Segment]:
        rows = await self._pool.fetch(
            """
            SELECT s.* FROM knowledge_segments s
            WHERE s.tenant_id=$1 AND s.asset_id=$2
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=s.tenant_id AND x.asset_id=s.asset_id
                            AND x.scope=ANY($3::text[]))
            ORDER BY s.sequence
            """,
            tenant_id, asset_id, scopes,
        )
        return [_segment(row) for row in rows]

    async def provenance_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> dict:
        occurrences = await self._pool.fetch(
            """
            SELECT o.id,o.source_kind,o.external_id,o.external_path,o.observed_at
            FROM knowledge_source_occurrences o
            WHERE o.tenant_id=$1 AND o.asset_id=$2
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=o.tenant_id AND x.asset_id=o.asset_id
                            AND x.scope=ANY($3::text[]))
            ORDER BY o.observed_at
            """,
            tenant_id, asset_id, scopes,
        )
        embeddings = await self._pool.fetch(
            """
            SELECT e.id,e.subject_type,e.subject_id,e.model_provider,e.model_name,
                   e.model_version,e.dimensions,e.distance_metric,e.created_at
            FROM knowledge_embeddings e
            JOIN knowledge_segments s
              ON s.tenant_id=e.tenant_id AND s.id=e.subject_id
            WHERE e.tenant_id=$1 AND s.asset_id=$2
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=s.tenant_id AND x.asset_id=s.asset_id
                            AND x.scope=ANY($3::text[]))
            ORDER BY e.created_at,e.id
            """,
            tenant_id, asset_id, scopes,
        )
        return {
            "occurrences": [_provenance_row(row) for row in occurrences],
            "embeddings": [_provenance_row(row) for row in embeddings],
        }

    async def original_for_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[str, str, str] | None:
        row = await self._pool.fetchrow(
            """
            SELECT b.object_key,b.media_type,a.filename
            FROM knowledge_assets a
            JOIN knowledge_revisions r
              ON r.tenant_id=a.tenant_id AND r.id=a.current_revision_id
            JOIN knowledge_blobs b
              ON b.tenant_id=r.tenant_id AND b.digest=r.blob_digest
            WHERE a.tenant_id=$1 AND a.id=$2 AND a.deleted_at IS NULL
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=a.tenant_id AND x.asset_id=a.id
                            AND x.scope=ANY($3::text[]))
            """,
            tenant_id, asset_id, scopes,
        )
        return (row["object_key"], row["media_type"], row["filename"]) if row else None

    async def search(
        self,
        tenant_id: str,
        workspace_id: str | None,
        scopes: list[str],
        query: str,
        embedding: list[float],
        limit: int,
    ) -> list[SearchHit]:
        rows = await self._pool.fetch(
            """
            SELECT a.id AS asset_id,a.current_revision_id,a.title,a.filename,
                   a.source_kind,a.source_ref,s.id AS segment_id,s.text,s.locator,
                   s.content_hash,
                   (CASE WHEN $4='' THEN 0
                         WHEN lower(a.title)=lower($4) THEN 3
                         WHEN a.title ILIKE '%' || $4 || '%' THEN 2 ELSE 0 END
                    + CASE WHEN $4='' THEN 0 ELSE
                        ts_rank_cd(s.search_vector,plainto_tsquery('simple',$4)) END
                    + CASE WHEN $4='' THEN 0 ELSE
                        GREATEST(0,1-(e.vector <=> $5::vector))*0.35 END) AS score
            FROM knowledge_segments s
            JOIN knowledge_assets a ON a.tenant_id=s.tenant_id AND a.id=s.asset_id
            JOIN LATERAL (
              SELECT vector FROM knowledge_embeddings e0
              WHERE e0.tenant_id=s.tenant_id AND e0.subject_type='segment'
                AND e0.subject_id=s.id ORDER BY e0.created_at DESC LIMIT 1
            ) e ON true
            WHERE s.tenant_id=$1 AND a.deleted_at IS NULL
              AND ($2::text IS NULL OR a.workspace_id=$2)
              AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                          WHERE x.tenant_id=a.tenant_id AND x.asset_id=a.id
                            AND x.scope=ANY($3::text[]))
            ORDER BY score DESC,a.created_at DESC,s.sequence LIMIT $6
            """,
            tenant_id, workspace_id, scopes, query, _vector(embedding), limit,
        )
        return [_hit(row) for row in rows]

    async def erase_asset(
        self, tenant_id: str, asset_id: str, scopes: list[str]
    ) -> tuple[list[str], list[str]]:
        pool = getattr(self._pool, "_pool", self._pool)
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.tenant_id',$1,true)", tenant_id)
                row = await connection.fetchrow(
                    """
                    SELECT r.blob_digest FROM knowledge_assets a
                    JOIN knowledge_revisions r
                      ON r.tenant_id=a.tenant_id AND r.id=a.current_revision_id
                    WHERE a.tenant_id=$1 AND a.id=$2
                      AND EXISTS (SELECT 1 FROM knowledge_asset_access x
                                  WHERE x.tenant_id=a.tenant_id AND x.asset_id=a.id
                                    AND x.scope=ANY($3::text[])) FOR UPDATE OF a
                    """,
                    tenant_id, asset_id, scopes,
                )
                if row is None:
                    return [], []
                segment_rows = await connection.fetch(
                    "SELECT id FROM knowledge_segments WHERE tenant_id=$1 AND asset_id=$2",
                    tenant_id, asset_id,
                )
                await connection.execute(
                    "DELETE FROM knowledge_assets WHERE tenant_id=$1 AND id=$2",
                    tenant_id, asset_id,
                )
                blob = await connection.fetchrow(
                    """
                    DELETE FROM knowledge_blobs b WHERE b.tenant_id=$1 AND b.digest=$2
                      AND NOT EXISTS (SELECT 1 FROM knowledge_revisions r
                                      WHERE r.tenant_id=b.tenant_id
                                        AND r.blob_digest=b.digest)
                    RETURNING object_key
                    """,
                    tenant_id, row["blob_digest"],
                )
                keys = [blob["object_key"]] if blob else []
                return keys, [item["id"] for item in segment_rows]

    async def ensure_providers(self, tenant_id: str, providers: list[Provider]) -> None:
        for row in providers:
            await self._pool.execute(
                """
                INSERT INTO knowledge_providers
                  (tenant_id,id,display_name,role,enabled,bundled,health,status,
                   last_error,config,updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (tenant_id,id) DO NOTHING
                """,
                tenant_id, row.id, row.display_name, row.role, row.enabled,
                row.bundled, row.health, row.status, row.last_error, row.config,
                row.updated_at,
            )

    async def list_providers(self, tenant_id: str) -> list[Provider]:
        rows = await self._pool.fetch(
            """SELECT * FROM knowledge_providers WHERE tenant_id=$1
               ORDER BY bundled DESC,display_name""",
            tenant_id,
        )
        return [_provider(row) for row in rows]

    async def get_provider(self, tenant_id: str, provider_id: str) -> Provider | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM knowledge_providers WHERE tenant_id=$1 AND id=$2",
            tenant_id, provider_id,
        )
        return _provider(row) if row else None

    async def save_provider(self, provider: Provider) -> None:
        await self._pool.execute(
            """
            UPDATE knowledge_providers
            SET enabled=$3,health=$4,status=$5,last_error=$6,config=$7,updated_at=$8
            WHERE tenant_id=$1 AND id=$2
            """,
            provider.tenant_id, provider.id, provider.enabled, provider.health,
            provider.status, provider.last_error, provider.config, provider.updated_at,
        )

    async def save_projection(self, status: ProjectionStatus) -> None:
        await self._pool.execute(
            """
            INSERT INTO knowledge_projection_statuses
              (tenant_id,provider_id,subject_type,subject_id,operation,status,
               projection_ref,error,updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (tenant_id,provider_id,subject_id,operation) DO UPDATE SET
              subject_type=EXCLUDED.subject_type,status=EXCLUDED.status,
              projection_ref=EXCLUDED.projection_ref,error=EXCLUDED.error,
              updated_at=EXCLUDED.updated_at
            """,
            status.tenant_id, status.provider_id, status.subject_type, status.subject_id,
            status.operation, status.status, status.projection_ref, status.error,
            status.updated_at,
        )

    async def list_projections(
        self, tenant_id: str, subject_id: str | None = None
    ) -> list[ProjectionStatus]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM knowledge_projection_statuses
            WHERE tenant_id=$1 AND ($2::text IS NULL OR subject_id=$2)
            ORDER BY updated_at DESC
            """,
            tenant_id, subject_id,
        )
        return [_projection(row) for row in rows]


def _provenance_row(row) -> dict:
    return {
        key: value.isoformat() if key in {"observed_at", "created_at"} else value
        for key, value in dict(row).items()
    }
