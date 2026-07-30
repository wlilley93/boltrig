"""Memory/Postgres persistence for immutable, owner-scoped artifacts."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from boltrig.models.artifacts import (
    MAX_ARTIFACT_PAGE,
    Artifact,
    ArtifactProvenance,
)

_META_COLUMNS = """
id,tenant_id,owner_id,workspace_id,conversation_id,run_id,work_item_id,
name,digest,media_type,size,revision,previous_revision_id,provenance,created_at
"""


def _validate_content(artifact: Artifact, content: bytes) -> None:
    if type(content) is not bytes:
        raise TypeError("artifact content must be exact immutable bytes")
    if len(content) != artifact.size:
        raise ValueError("artifact_content_size_mismatch")
    observed = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(observed, artifact.digest):
        raise ValueError("artifact_content_digest_mismatch")


def _workspace_visible(artifact: Artifact, workspace_id: str | None) -> bool:
    return artifact.workspace_id is None or artifact.workspace_id == workspace_id


def _artifact_row(row: Any) -> Artifact:
    provenance = row["provenance"]
    return Artifact(
        id=row["id"],
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        workspace_id=row["workspace_id"],
        conversation_id=row["conversation_id"],
        run_id=row["run_id"],
        work_item_id=row["work_item_id"],
        name=row["name"],
        digest=row["digest"],
        media_type=row["media_type"],
        size=row["size"],
        revision=row["revision"],
        previous_revision_id=row["previous_revision_id"],
        provenance=ArtifactProvenance(
            kind=provenance["kind"],
            actor_ref=provenance.get("actor_ref"),
            source_ref=provenance.get("source_ref"),
            tool_call_id=provenance.get("tool_call_id"),
        ),
        created_at=row["created_at"],
    )


def _provenance_json(provenance: ArtifactProvenance) -> dict[str, str | None]:
    return {
        "kind": provenance.kind,
        "actor_ref": provenance.actor_ref,
        "source_ref": provenance.source_ref,
        "tool_call_id": provenance.tool_call_id,
    }


class ArtifactStoreMem:
    async def record_artifact(self, artifact: Artifact, content: bytes) -> bool:
        _validate_content(artifact, content)
        records, blobs = _memory_tables(self)
        key = (artifact.tenant_id, artifact.id)
        if key in records:
            return False
        if artifact.workspace_id is not None and (
            artifact.tenant_id, artifact.workspace_id
        ) not in getattr(self, "_workspaces", {}):
            return False
        if artifact.conversation_id is not None:
            conversation = getattr(self, "_convs", {}).get(
                (artifact.tenant_id, artifact.conversation_id)
            )
            if conversation is None or conversation.user_id != artifact.owner_id:
                return False
        if artifact.previous_revision_id is not None:
            previous = records.get(
                (artifact.tenant_id, artifact.previous_revision_id)
            )
            if not _valid_previous(artifact, previous):
                return False
            if any(
                row.tenant_id == artifact.tenant_id
                and row.previous_revision_id == artifact.previous_revision_id
                for row in records.values()
            ):
                return False
        if any(
            row.tenant_id == artifact.tenant_id
            and row.owner_id == artifact.owner_id
            and row.workspace_id == artifact.workspace_id
            and row.conversation_id == artifact.conversation_id
            and row.name == artifact.name
            and row.revision == artifact.revision
            for row in records.values()
        ):
            return False
        records[key] = artifact
        blobs[key] = bytes(content)
        return True

    async def get_artifact_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> Artifact | None:
        records, _ = _memory_tables(self)
        artifact = records.get((tenant_id, artifact_id))
        if (
            artifact is None
            or artifact.owner_id != owner_id
            or not _workspace_visible(artifact, workspace_id)
        ):
            return None
        return artifact

    async def list_artifacts_scoped(
        self,
        tenant_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
        conversation_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> list[Artifact]:
        records, _ = _memory_tables(self)
        rows = [
            row
            for row in records.values()
            if row.tenant_id == tenant_id
            and row.owner_id == owner_id
            and _workspace_visible(row, workspace_id)
            and (
                conversation_id is None
                or row.conversation_id == conversation_id
            )
        ]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        if cursor is not None:
            positions = [
                index for index, row in enumerate(rows) if row.id == cursor
            ]
            if not positions:
                return []
            rows = rows[positions[0] + 1 :]
        return rows[: max(1, min(int(limit), MAX_ARTIFACT_PAGE + 1))]

    async def get_artifact_download_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> tuple[Artifact, bytes] | None:
        artifact = await self.get_artifact_scoped(
            tenant_id,
            artifact_id,
            owner_id,
            workspace_id=workspace_id,
        )
        if artifact is None:
            return None
        _, blobs = _memory_tables(self)
        content = blobs.get((tenant_id, artifact_id))
        return (artifact, bytes(content)) if content is not None else None


class ArtifactStorePG:
    _pool: Any

    async def record_artifact(self, artifact: Artifact, content: bytes) -> bool:
        _validate_content(artifact, content)
        row = await self._pool.fetchrow(
            f"""INSERT INTO artifacts ({_META_COLUMNS},content)
                SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16
                 WHERE ($4::text IS NULL OR EXISTS (
                         SELECT 1 FROM workspaces
                          WHERE tenant_id=$2 AND id=$4
                       ))
                   AND ($5::text IS NULL OR EXISTS (
                         SELECT 1 FROM conversations
                          WHERE tenant_id=$2 AND id=$5 AND user_id=$3
                       ))
                   AND (
                         ($12=1 AND $13::text IS NULL)
                         OR EXISTS (
                           SELECT 1 FROM artifacts previous
                            WHERE previous.tenant_id=$2 AND previous.id=$13
                              AND previous.owner_id=$3
                              AND previous.workspace_id IS NOT DISTINCT FROM $4
                              AND previous.conversation_id IS NOT DISTINCT FROM $5
                              AND previous.name=$8
                              AND previous.revision=$12-1
                         )
                       )
                ON CONFLICT DO NOTHING RETURNING id""",
            artifact.id,
            artifact.tenant_id,
            artifact.owner_id,
            artifact.workspace_id,
            artifact.conversation_id,
            artifact.run_id,
            artifact.work_item_id,
            artifact.name,
            artifact.digest,
            artifact.media_type,
            artifact.size,
            artifact.revision,
            artifact.previous_revision_id,
            _provenance_json(artifact.provenance),
            artifact.created_at,
            content,
        )
        return row is not None

    async def get_artifact_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> Artifact | None:
        row = await self._pool.fetchrow(
            f"""SELECT {_META_COLUMNS} FROM artifacts
                 WHERE tenant_id=$1 AND id=$2 AND owner_id=$3
                   AND (
                     workspace_id IS NULL OR workspace_id=$4
                   )""",
            tenant_id, artifact_id, owner_id, workspace_id,
        )
        return _artifact_row(row) if row is not None else None

    async def list_artifacts_scoped(
        self,
        tenant_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
        conversation_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> list[Artifact]:
        bounded = max(1, min(int(limit), MAX_ARTIFACT_PAGE + 1))
        rows = await self._pool.fetch(
            f"""SELECT {_META_COLUMNS} FROM artifacts artifact
                 WHERE tenant_id=$1 AND owner_id=$2
                   AND (
                     workspace_id IS NULL OR workspace_id=$3
                   )
                   AND ($4::text IS NULL OR conversation_id=$4)
                   AND (
                     $5::text IS NULL OR (created_at,id) < (
                       SELECT created_at,id FROM artifacts cursor_row
                        WHERE cursor_row.tenant_id=$1
                          AND cursor_row.id=$5
                          AND cursor_row.owner_id=$2
                          AND (
                            $4::text IS NULL
                            OR cursor_row.conversation_id=$4
                          )
                          AND (
                            cursor_row.workspace_id IS NULL
                            OR cursor_row.workspace_id=$3
                          )
                     )
                   )
                 ORDER BY created_at DESC,id DESC LIMIT $6""",
            tenant_id,
            owner_id,
            workspace_id,
            conversation_id,
            cursor,
            bounded,
        )
        return [_artifact_row(row) for row in rows]

    async def get_artifact_download_scoped(
        self,
        tenant_id: str,
        artifact_id: str,
        owner_id: str,
        *,
        workspace_id: str | None,
    ) -> tuple[Artifact, bytes] | None:
        row = await self._pool.fetchrow(
            f"""SELECT {_META_COLUMNS},content FROM artifacts
                 WHERE tenant_id=$1 AND id=$2 AND owner_id=$3
                   AND (
                     workspace_id IS NULL OR workspace_id=$4
                   )""",
            tenant_id, artifact_id, owner_id, workspace_id,
        )
        if row is None:
            return None
        artifact = _artifact_row(row)
        return artifact, bytes(row["content"])


def _valid_previous(artifact: Artifact, previous: Artifact | None) -> bool:
    return bool(
        previous is not None
        and previous.owner_id == artifact.owner_id
        and previous.workspace_id == artifact.workspace_id
        and previous.conversation_id == artifact.conversation_id
        and previous.name == artifact.name
        and previous.revision == artifact.revision - 1
    )


def _memory_tables(
    store: Any,
) -> tuple[
    dict[tuple[str, str], Artifact],
    dict[tuple[str, str], bytes],
]:
    records = getattr(store, "_artifacts", None)
    if records is None:
        records = {}
        setattr(store, "_artifacts", records)
    blobs = getattr(store, "_artifact_blobs", None)
    if blobs is None:
        blobs = {}
        setattr(store, "_artifact_blobs", blobs)
    return records, blobs
