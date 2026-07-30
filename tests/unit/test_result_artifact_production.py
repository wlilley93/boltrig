from __future__ import annotations

import base64

import pytest

from boltrig.fleet.artifact_production import (
    MAX_RESULT_ARTIFACTS,
    produce_spawn_artifacts,
    record_result_artifacts,
)
from boltrig.fleet.result import AgentResult
from boltrig.kernel import Kernel
from boltrig.models import Conversation, InvocationContext
from boltrig.store import InMemoryStore


async def _store() -> InMemoryStore:
    store = InMemoryStore()
    await store.create_conversation(
        Conversation(id="conversation-1", tenant_id="tenant-1", user_id="alice")
    )
    return store


@pytest.mark.invariant("SEC-WRK-08")
async def test_structured_agent_artifact_is_recorded_with_server_provenance():
    store = await _store()
    content = b"# Finished brief\n"

    production = await record_result_artifacts(
        store,
        {
            "agent_type": "codex-worker",
            "output": {
                "artifacts": [
                    {
                        "name": "brief.md",
                        "media_type": "text/markdown",
                        "data": base64.b64encode(content).decode(),
                        "owner_id": "mallory",
                        "run_id": "foreign",
                    }
                ]
            },
        },
        tenant_id="tenant-1",
        owner_id="alice",
        workspace_id=None,
        conversation_id="conversation-1",
        run_id="run-1",
        work_item_id="run-1",
    )

    assert production.declared == 1
    assert production.rejected == 0
    artifact = production.recorded[0]
    assert artifact.owner_id == "alice"
    assert artifact.run_id == "run-1"
    assert artifact.provenance.actor_ref == "codex-worker"
    assert artifact.provenance.source_ref == "run-1"
    stored = await store.get_artifact_download_scoped(
        "tenant-1", artifact.id, "alice", workspace_id=None
    )
    assert stored is not None
    assert stored[1] == content


async def test_result_artifacts_are_idempotent_and_malformed_values_are_rejected():
    store = await _store()
    result = {
        "agent_type": "codex-worker",
        "output": {
            "artifacts": [
                {
                    "name": "brief.md",
                    "media_type": "text/markdown",
                    "data": base64.b64encode(b"brief").decode(),
                },
                {
                    "name": "../escape",
                    "media_type": "text/plain",
                    "data": "not-base64",
                },
            ]
        },
    }
    kwargs = {
        "tenant_id": "tenant-1",
        "owner_id": "alice",
        "workspace_id": None,
        "conversation_id": "conversation-1",
        "run_id": "run-1",
        "work_item_id": "run-1",
    }

    first = await record_result_artifacts(store, result, **kwargs)
    second = await record_result_artifacts(store, result, **kwargs)

    assert first.declared == 2
    assert first.rejected == 1
    assert len(first.recorded) == 1
    assert second.recorded[0].id == first.recorded[0].id
    assert second.rejected == 1


async def test_result_artifact_count_is_bounded():
    store = await _store()
    declaration = {
        "name": "brief.md",
        "media_type": "text/markdown",
        "data": base64.b64encode(b"brief").decode(),
    }

    production = await record_result_artifacts(
        store,
        {"output": {"artifacts": [declaration] * (MAX_RESULT_ARTIFACTS + 1)}},
        tenant_id="tenant-1",
        owner_id="alice",
        workspace_id=None,
        conversation_id="conversation-1",
        run_id="run-1",
        work_item_id="run-1",
    )

    assert production.declared == MAX_RESULT_ARTIFACTS + 1
    assert production.rejected >= 1
    assert len(production.recorded) == 1


async def test_governed_spawn_seam_records_and_projects_safe_metadata():
    store = await _store()
    kernel = Kernel(store)
    context = InvocationContext(
        tenant_id="tenant-1",
        actor="chief-of-staff",
        on_behalf_of="alice",
        run_id="root-run",
        extra={"conversation_id": "conversation-1"},
    )
    result = AgentResult.succeeded(
        {
            "text": "Done",
            "artifacts": [
                {
                    "name": "brief.md",
                    "media_type": "text/markdown",
                    "data": base64.b64encode(b"brief").decode(),
                }
            ],
        }
    )

    production = await produce_spawn_artifacts(
        kernel,
        result,
        capability_name="codex-worker",
        context=context,
        run_id="child-run",
    )

    assert len(production.recorded) == 1
    event = kernel.events.snapshot("tenant-1", "root-run")[-1]
    assert event == {
        "type": "artifact",
        "artifact_id": production.recorded[0].id,
        "name": "brief.md",
        "media_type": "text/markdown",
        "size": 5,
    }
    assert "data" not in repr(event)
