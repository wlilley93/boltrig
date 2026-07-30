"""Owner/workspace-scoped metadata and download routes for immutable artifacts."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from boltrig.models.artifacts import MAX_ARTIFACT_PAGE, Artifact


def _view(artifact: Artifact) -> dict[str, Any]:
    provenance = {
        "kind": artifact.provenance.kind,
        "actor_ref": artifact.provenance.actor_ref,
        "source_ref": artifact.provenance.source_ref,
        "tool_call_id": artifact.provenance.tool_call_id,
    }
    return {
        "id": artifact.id,
        "owner_id": artifact.owner_id,
        "workspace_id": artifact.workspace_id,
        "conversation_id": artifact.conversation_id,
        "run_id": artifact.run_id,
        "work_item_id": artifact.work_item_id,
        "name": artifact.name,
        "digest": artifact.digest,
        "media_type": artifact.media_type,
        "size": artifact.size,
        "revision": artifact.revision,
        "previous_revision_id": artifact.previous_revision_id,
        "provenance": {
            key: value for key, value in provenance.items() if value is not None
        },
        "created_at": artifact.created_at.isoformat(),
    }


def _owner(principal: Any) -> str:
    return str(principal.on_behalf_of or principal.subject)


def _bounded_query(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value or len(value.encode("utf-8")) > 256:
        raise HTTPException(status_code=400, detail=f"invalid {label}")
    return value


async def _artifact_or_404(
    kernel: Any, principal: Any, artifact_id: str
) -> Artifact:
    bounded_id = _bounded_query("artifact id", artifact_id)
    assert bounded_id is not None
    artifact: Artifact | None = await kernel.store.get_artifact_scoped(
        principal.tenant_id,
        bounded_id,
        _owner(principal),
        workspace_id=principal.active_workspace_id,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact


def register(app: Any, P: Any, K: Any) -> None:
    @app.get("/v1/artifacts")  # type: ignore[untyped-decorator]
    async def list_artifacts(
        conversation_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        k: Any = K,
        p: Any = P,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), MAX_ARTIFACT_PAGE))
        rows = await k.store.list_artifacts_scoped(
            p.tenant_id,
            _owner(p),
            workspace_id=p.active_workspace_id,
            conversation_id=_bounded_query("conversation id", conversation_id),
            limit=bounded_limit + 1,
            cursor=_bounded_query("cursor", cursor),
        )
        visible = rows[:bounded_limit]
        return {
            "artifacts": [_view(artifact) for artifact in visible],
            "next_cursor": visible[-1].id if len(rows) > bounded_limit else None,
        }

    @app.get("/v1/artifacts/{artifact_id}")  # type: ignore[untyped-decorator]
    async def artifact_detail(
        artifact_id: str, k: Any = K, p: Any = P
    ) -> dict[str, Any]:
        return _view(await _artifact_or_404(k, p, artifact_id))

    @app.get(  # type: ignore[untyped-decorator]
        "/v1/artifacts/{artifact_id}/download"
    )
    async def download_artifact(
        artifact_id: str, k: Any = K, p: Any = P
    ) -> Response:
        bounded_id = _bounded_query("artifact id", artifact_id)
        assert bounded_id is not None
        result = await k.store.get_artifact_download_scoped(
            p.tenant_id,
            bounded_id,
            _owner(p),
            workspace_id=p.active_workspace_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        artifact, content = result
        observed = hashlib.sha256(content).hexdigest()
        if (
            len(content) != artifact.size
            or not hmac.compare_digest(observed, artifact.digest)
        ):
            return JSONResponse(
                {"status": "error", "reason": "artifact_integrity_failed"},
                status_code=503,
            )
        filename = quote(artifact.name, safe="")
        return Response(
            content,
            media_type=artifact.media_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "ETag": f'"sha256:{artifact.digest}"',
                "X-Artifact-Digest": artifact.digest,
                "X-Content-Type-Options": "nosniff",
            },
        )


__all__ = ["register"]
