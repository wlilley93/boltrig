"""Worker artifact reads are scoped, content-addressed, and read-only."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import Conversation, Workspace, utcnow
from boltrig.models.artifacts import Artifact, ArtifactProvenance
from boltrig.store import InMemoryStore

T = "artifact-tenant"
ROOT = Path(__file__).resolve().parents[2]


def _headers(
    *,
    tenant: str = T,
    subject: str = "alice",
    workspace: str | None = None,
) -> dict[str, str]:
    headers = {
        "x-boltrig-tenant": tenant,
        "x-boltrig-subject": subject,
        "x-boltrig-role": "org-admin",
    }
    if workspace is not None:
        headers["x-boltrig-workspace"] = workspace
    return headers


def _artifact(
    artifact_id: str,
    content: bytes,
    *,
    tenant: str = T,
    owner: str = "alice",
    workspace: str | None = None,
    conversation: str | None = "conversation-1",
    name: str | None = None,
    offset: int = 0,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        tenant_id=tenant,
        owner_id=owner,
        workspace_id=workspace,
        conversation_id=conversation,
        run_id=f"run-{artifact_id}",
        work_item_id=f"work-{artifact_id}",
        name=name or f"{artifact_id}.txt",
        digest=hashlib.sha256(content).hexdigest(),
        media_type="text/plain",
        size=len(content),
        revision=1,
        provenance=ArtifactProvenance(
            kind="tool",
            actor_ref="codex",
            tool_call_id=f"call-{artifact_id}",
        ),
        created_at=utcnow() + timedelta(seconds=offset),
    )


async def _seed() -> tuple[InMemoryStore, dict[str, Artifact]]:
    store = InMemoryStore()
    for tenant, workspace in (
        (T, "workspace-a"),
        (T, "workspace-b"),
        ("rival", "workspace-a"),
    ):
        await store.create_workspace(
            Workspace(
                id=workspace,
                tenant_id=tenant,
                name=workspace,
                slug=workspace,
            )
        )
    await store.create_conversation(
        Conversation(id="conversation-1", tenant_id=T, user_id="alice")
    )
    await store.create_conversation(
        Conversation(id="conversation-2", tenant_id=T, user_id="alice")
    )
    await store.create_conversation(
        Conversation(id="conversation-1", tenant_id="rival", user_id="alice")
    )
    rows = {
        "org": _artifact("artifact-org", b"org", offset=1),
        "workspace_a": _artifact(
            "artifact-a", b"workspace-a", workspace="workspace-a", offset=2
        ),
        "workspace_b": _artifact(
            "artifact-b", b"workspace-b", workspace="workspace-b", offset=3
        ),
        "other_owner": _artifact(
            "artifact-bob",
            b"bob",
            owner="bob",
            workspace="workspace-a",
            conversation=None,
            offset=4,
        ),
        "other_conversation": _artifact(
            "artifact-other-conversation",
            b"other",
            workspace="workspace-a",
            conversation="conversation-2",
            offset=5,
        ),
        "other_tenant": _artifact(
            "artifact-rival",
            b"rival",
            tenant="rival",
            workspace="workspace-a",
            offset=6,
        ),
    }
    for row in rows.values():
        assert await store.record_artifact(
            row, {
                "artifact-org": b"org",
                "artifact-a": b"workspace-a",
                "artifact-b": b"workspace-b",
                "artifact-bob": b"bob",
                "artifact-other-conversation": b"other",
                "artifact-rival": b"rival",
            }[row.id]
        )
    return store, rows


def _client() -> tuple[TestClient, InMemoryStore, dict[str, Artifact]]:
    store, rows = asyncio.run(_seed())
    return TestClient(create_app(Kernel(store))), store, rows


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-08")
@pytest.mark.invariant("SEC-08")
def test_artifact_list_and_detail_are_owner_tenant_and_workspace_scoped():
    client, _, _ = _client()
    response = client.get(
        "/v1/artifacts",
        params={"conversation_id": "conversation-1"},
        headers=_headers(workspace="workspace-a"),
    )
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["artifacts"]] == [
        "artifact-a",
        "artifact-org",
    ]
    assert body["next_cursor"] is None
    projected = body["artifacts"][0]
    assert set(projected) == {
        "id",
        "owner_id",
        "workspace_id",
        "conversation_id",
        "run_id",
        "work_item_id",
        "name",
        "digest",
        "media_type",
        "size",
        "revision",
        "previous_revision_id",
        "provenance",
        "created_at",
    }
    assert "tenant_id" not in repr(projected)
    assert "content" not in repr(projected)
    assert "path" not in repr(projected)

    visible = client.get(
        "/v1/artifacts/artifact-a",
        headers=_headers(workspace="workspace-a"),
    )
    assert visible.status_code == 200
    assert visible.json()["provenance"] == {
        "kind": "tool",
        "actor_ref": "codex",
        "tool_call_id": "call-artifact-a",
    }
    assert client.get(
        "/v1/artifacts/artifact-b",
        headers=_headers(workspace="workspace-a"),
    ).status_code == 404
    assert client.get(
        "/v1/artifacts/artifact-bob",
        headers=_headers(workspace="workspace-a"),
    ).status_code == 404
    assert client.get(
        "/v1/artifacts/artifact-a",
        headers=_headers(tenant="rival", workspace="workspace-a"),
    ).status_code == 404


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-08")
def test_artifact_download_verifies_bytes_and_never_accepts_an_upload():
    client, store, _ = _client()
    headers = _headers(workspace="workspace-a")
    response = client.get(
        "/v1/artifacts/artifact-a/download", headers=headers
    )
    assert response.status_code == 200
    assert response.content == b"workspace-a"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].endswith(
        "artifact-a.txt"
    )
    assert response.headers["etag"].startswith('"sha256:')
    assert response.headers["x-content-type-options"] == "nosniff"

    assert client.post(
        "/v1/artifacts",
        content=b"caller bytes",
        headers=headers,
    ).status_code == 405
    assert "post" not in client.get("/openapi.json").json()["paths"][
        "/v1/artifacts"
    ]

    store._artifact_blobs[(T, "artifact-a")] = b"tampered"
    broken = client.get(
        "/v1/artifacts/artifact-a/download", headers=headers
    )
    assert broken.status_code == 503
    assert broken.json() == {
        "status": "error",
        "reason": "artifact_integrity_failed",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-08")
def test_artifact_contract_rejects_paths_and_non_content_addressed_bytes():
    content = b"bounded"
    with pytest.raises(ValueError, match="invalid_artifact_name"):
        _artifact("bad", content, name="../secret.txt")

    store = InMemoryStore()
    artifact = _artifact("wrong-digest", content, conversation=None)
    with pytest.raises(ValueError, match="artifact_content_digest_mismatch"):
        asyncio.run(store.record_artifact(artifact, b"changed"))


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-08")
def test_artifact_production_has_one_canonical_runtime_seam():
    producers = []
    for path in (ROOT / "boltrig").rglob("*.py"):
        if path.is_relative_to(ROOT / "boltrig" / "store"):
            continue
        if "record_artifact(" in path.read_text(encoding="utf-8"):
            producers.append(path.relative_to(ROOT).as_posix())
    assert producers == ["boltrig/fleet/artifact_production.py"], (
        "artifact production must remain behind the one bounded result seam: "
        f"{producers}"
    )
