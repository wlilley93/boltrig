"""Memory/Postgres parity for immutable Worker artifact storage."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace

import pytest

from boltrig.models import Conversation, Workspace, utcnow
from boltrig.models.artifacts import Artifact, ArtifactProvenance

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "artifact-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE artifacts,conversations,workspaces RESTART IDENTITY CASCADE"
    )
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def artifact_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _artifact(
    artifact_id: str,
    content: bytes,
    *,
    owner: str = "alice",
    workspace: str | None = "workspace-a",
    conversation: str | None = "conversation-1",
) -> Artifact:
    return Artifact(
        id=artifact_id,
        tenant_id=T,
        owner_id=owner,
        workspace_id=workspace,
        conversation_id=conversation,
        name="report.txt",
        digest=hashlib.sha256(content).hexdigest(),
        media_type="text/plain",
        size=len(content),
        revision=1,
        provenance=ArtifactProvenance(
            kind="workflow", source_ref="workflow-1"
        ),
        created_at=utcnow(),
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-08")
@pytest.mark.invariant("SEC-08")
async def test_artifact_lifecycle_and_scope_match_on_both_stores(artifact_store):
    for workspace in ("workspace-a", "workspace-b"):
        await artifact_store.create_workspace(
            Workspace(
                id=workspace,
                tenant_id=T,
                name=workspace,
                slug=workspace,
            )
        )
    await artifact_store.create_conversation(
        Conversation(id="conversation-1", tenant_id=T, user_id="alice")
    )
    await artifact_store.create_conversation(
        Conversation(id="conversation-bob", tenant_id=T, user_id="bob")
    )
    await artifact_store.create_conversation(
        Conversation(id="conversation-2", tenant_id=T, user_id="alice")
    )

    first_bytes = b"first revision"
    first = _artifact("artifact-1", first_bytes)
    assert await artifact_store.record_artifact(first, first_bytes)
    assert not await artifact_store.record_artifact(first, first_bytes)

    second_bytes = b"second revision"
    second = replace(
        _artifact("artifact-2", second_bytes),
        revision=2,
        previous_revision_id=first.id,
    )
    assert await artifact_store.record_artifact(second, second_bytes)
    same_name_other_conversation = _artifact(
        "artifact-other-conversation",
        b"independent report",
        conversation="conversation-2",
    )
    assert await artifact_store.record_artifact(
        same_name_other_conversation, b"independent report"
    )
    assert not await artifact_store.record_artifact(
        replace(second, id="artifact-branch"), second_bytes
    )
    assert not await artifact_store.record_artifact(
        _artifact(
            "artifact-wrong-owner-conversation",
            b"no",
            conversation="conversation-bob",
        ),
        b"no",
    )
    assert not await artifact_store.record_artifact(
        _artifact(
            "artifact-missing-workspace",
            b"no",
            workspace="workspace-missing",
            conversation=None,
        ),
        b"no",
    )

    visible = await artifact_store.list_artifacts_scoped(
        T,
        "alice",
        workspace_id="workspace-a",
        conversation_id="conversation-1",
        limit=3,
    )
    assert [row.id for row in visible] == ["artifact-2", "artifact-1"]
    page = await artifact_store.list_artifacts_scoped(
        T,
        "alice",
        workspace_id="workspace-a",
        conversation_id="conversation-1",
        limit=3,
        cursor="artifact-2",
    )
    assert [row.id for row in page] == ["artifact-1"]
    assert await artifact_store.list_artifacts_scoped(
        T,
        "alice",
        workspace_id="workspace-a",
        conversation_id="conversation-1",
        cursor="unknown",
    ) == []
    assert await artifact_store.get_artifact_scoped(
        "rival",
        first.id,
        "alice",
        workspace_id="workspace-a",
    ) is None
    assert await artifact_store.get_artifact_scoped(
        T,
        first.id,
        "bob",
        workspace_id="workspace-a",
    ) is None
    assert await artifact_store.get_artifact_scoped(
        T,
        first.id,
        "alice",
        workspace_id="workspace-b",
    ) is None
    downloaded = await artifact_store.get_artifact_download_scoped(
        T,
        second.id,
        "alice",
        workspace_id="workspace-a",
    )
    assert downloaded is not None
    assert downloaded[0] == second and downloaded[1] == second_bytes

    with pytest.raises(ValueError, match="artifact_content_size_mismatch"):
        await artifact_store.record_artifact(
            _artifact("artifact-invalid-bytes", b"correct"),
            b"short",
        )
