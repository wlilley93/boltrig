"""Exact caller-lane continuation for fixed Memory mutations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "memory-approval-finalization"
AUTHOR = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "memory-author",
    "x-boltrig-role": "employee",
    "x-boltrig-grants": "*",
}


async def _client(*, blocking_verbs: set[str]) -> tuple[Kernel, TestClient]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs=blocking_verbs)
    await kernel.register_adapter(
        T,
        build_memory_adapter(LocalMemoryEngine(), store, audit=kernel.audit),
    )
    return kernel, TestClient(create_app(kernel))


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_batch_ingestion_replays_as_one_exact_governed_operation() -> None:
    kernel, client = await _client(blocking_verbs={"memory.ingest"})
    exact = {
        "source_kind": "document",
        "source_ref": "source-a",
        "items": ["the exact approved fact"],
    }

    pending = client.post("/v1/memory/ingest", json=exact, headers=AUTHOR)
    assert pending.status_code == 202
    request_id = pending.json()["hitl_request_id"]
    assert await kernel.store.list_memory_ingestions(T) == []

    await kernel.hitl.answer(T, request_id, "approve", "independent-reviewer")
    changed = client.post(
        "/v1/memory/ingest",
        json={**exact, "items": ["a different unapproved fact"]},
        headers={**AUTHOR, "x-boltrig-approval-id": request_id},
    )
    assert changed.status_code == 202
    assert changed.json()["hitl_request_id"] != request_id
    assert await kernel.store.list_memory_ingestions(T) == []

    completed = client.post(
        "/v1/memory/ingest",
        json=exact,
        headers={**AUTHOR, "x-boltrig-approval-id": request_id},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "ok"
    assert completed.json()["facts_added"] == 1
    facts = await kernel.store.list_memory_facts(T, ["user:memory-author"])
    assert [fact.content for fact in facts] == ["the exact approved fact"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_source_erasure_exposes_and_consumes_its_approval_handle() -> None:
    kernel, client = await _client(blocking_verbs={"memory.forget"})
    remembered = client.post(
        "/v1/memory/remember",
        json={
            "content": "erasable fact",
            "source_kind": "document",
            "source_ref": "source-a",
        },
        headers=AUTHOR,
    )
    assert remembered.status_code == 200

    pending = client.post(
        "/v1/memory/forget",
        json={"source_ref": "source-a"},
        headers=AUTHOR,
    )
    assert pending.status_code == 202
    request_id = pending.json()["hitl_request_id"]

    await kernel.hitl.answer(T, request_id, "approve", "independent-reviewer")
    completed = client.post(
        "/v1/memory/forget",
        json={"source_ref": "source-a"},
        headers={**AUTHOR, "x-boltrig-approval-id": request_id},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "ok"
    assert completed.json()["facts_removed"] == 1
    assert await kernel.store.list_memory_facts(T, ["user:memory-author"]) == []
