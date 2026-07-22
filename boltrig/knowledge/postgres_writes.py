"""Transactional inserts for one canonical Knowledge ingestion bundle."""

from __future__ import annotations

from .postgres_rows import vector


async def insert_bundle(connection, bundle) -> None:
    await _insert_core(connection, bundle)
    await _insert_segments(connection, bundle)
    await _insert_access_and_job(connection, bundle)


async def _insert_core(connection, bundle) -> None:
    blob, asset, revision, representation, occurrence = (
        bundle.blob,
        bundle.asset,
        bundle.revision,
        bundle.representation,
        bundle.occurrence,
    )
    await connection.execute(
        """
        INSERT INTO knowledge_blobs
          (tenant_id,digest,object_key,byte_size,media_type,created_at)
        VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (tenant_id,digest) DO NOTHING
        """,
        blob.tenant_id, blob.digest, blob.object_key, blob.byte_size,
        blob.media_type, blob.created_at,
    )
    await connection.execute(
        """
        INSERT INTO knowledge_assets
          (tenant_id,id,workspace_id,title,filename,asset_type,owner_scope,
           current_revision_id,source_kind,source_ref,created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
        asset.tenant_id, asset.id, asset.workspace_id, asset.title, asset.filename,
        asset.asset_type, asset.owner_scope, asset.current_revision_id,
        asset.source_kind, asset.source_ref, asset.created_at,
    )
    await connection.execute(
        """
        INSERT INTO knowledge_revisions
          (tenant_id,id,asset_id,blob_digest,version,media_type,byte_size,created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        revision.tenant_id, revision.id, revision.asset_id, revision.blob_digest,
        revision.version, revision.media_type, revision.byte_size, revision.created_at,
    )
    await connection.execute(
        """
        INSERT INTO knowledge_representations
          (tenant_id,id,revision_id,kind,format,generator,generator_version,
           content_hash,created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        representation.tenant_id, representation.id, representation.revision_id,
        representation.kind, representation.format, representation.generator,
        representation.generator_version, representation.content_hash,
        representation.created_at,
    )
    await connection.execute(
        """
        INSERT INTO knowledge_source_occurrences
          (tenant_id,id,asset_id,source_kind,external_id,external_path,observed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
        occurrence.tenant_id, occurrence.id, occurrence.asset_id,
        occurrence.source_kind, occurrence.external_id, occurrence.external_path,
        occurrence.observed_at,
    )


async def _insert_segments(connection, bundle) -> None:
    await connection.executemany(
        """
        INSERT INTO knowledge_segments
          (tenant_id,id,asset_id,revision_id,representation_id,sequence,text,
           locator,content_hash,created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
        [
            (
                row.tenant_id, row.id, row.asset_id, row.revision_id,
                row.representation_id, row.sequence, row.text, row.locator,
                row.content_hash, row.created_at,
            )
            for row in bundle.segments
        ],
    )
    await connection.executemany(
        """
        INSERT INTO knowledge_embeddings
          (tenant_id,id,subject_type,subject_id,model_provider,model_name,
           model_version,dimensions,distance_metric,vector,created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::vector,$11)
        """,
        [
            (
                row.tenant_id, row.id, row.subject_type, row.subject_id,
                row.model_provider, row.model_name, row.model_version,
                row.dimensions, row.distance_metric, vector(row.vector), row.created_at,
            )
            for row in bundle.embeddings
        ],
    )


async def _insert_access_and_job(connection, bundle) -> None:
    asset, revision = bundle.asset, bundle.revision
    await connection.executemany(
        """
        INSERT INTO knowledge_asset_access (tenant_id,asset_id,scope)
        VALUES ($1,$2,$3) ON CONFLICT DO NOTHING
        """,
        [(asset.tenant_id, asset.id, scope) for scope in bundle.access_scopes],
    )
    await connection.execute(
        """
        INSERT INTO knowledge_jobs (tenant_id,id,kind,subject_id,status,detail)
        VALUES ($1,$2,'ingest',$3,'completed',$4)
        """,
        asset.tenant_id, f"ingest:{asset.id}", asset.id,
        {"segment_count": len(bundle.segments), "revision_id": revision.id},
    )
