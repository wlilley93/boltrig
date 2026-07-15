"""Resource-bounding on the list reads (M7 / M9-memory / SEC-009).

/v1/work and /v1/work/{id} must never return an unbounded slice: the work list
is keyset-paginated and the page size is server-clamped (SEC-69), and the detail
endpoint queries a work item's children DIRECTLY by parent_id (US-IAM-02 scope
preserved) instead of loading the whole department-visible set into memory. The
structured-memory list reads clamp the caller-supplied page size and a batch
ingest is capped by item count (M9-memory / SEC-009).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets  # noqa: F401
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import GrantSet, TenantPermissions, WorkItem, WorkStatus
from boltrig.store import InMemoryStore
from boltrig.store.base import MAX_INGEST_ITEMS, MAX_MEMORY_LIST, MAX_WORK_PAGE

T = "acme"


class _SpyStore(InMemoryStore):
    """Records the arguments the HTTP surface passes to the bounded reads, so a
    test can prove the query path (child-by-parent, clamped limits) without
    reaching into the endpoint internals."""

    def __init__(self) -> None:
        super().__init__()
        self.work_list_calls: list[dict] = []
        self.fact_list_limits: list[int] = []
        self.ingestion_list_limits: list[int] = []

    async def list_work_items(
        self, tenant_id, status=None, parent_id=None, departments=None,
        limit=None, cursor=None, workspace_id=None, enforce_workspace=False,
    ):
        self.work_list_calls.append({"parent_id": parent_id, "limit": limit, "cursor": cursor})
        return await super().list_work_items(
            tenant_id,
            status,
            parent_id,
            departments,
            limit,
            cursor,
            workspace_id,
            enforce_workspace,
        )

    async def list_memory_facts(self, tenant_id, owner_scopes, kind=None, limit=50):
        self.fact_list_limits.append(limit)
        return await super().list_memory_facts(tenant_id, owner_scopes, kind=kind, limit=limit)

    async def list_memory_ingestions(self, tenant_id, limit=50):
        self.ingestion_list_limits.append(limit)
        return await super().list_memory_ingestions(tenant_id, limit=limit)


def _hdr(role: str, departments: str = ""):
    return {
        "x-boltrig-tenant": T, "x-boltrig-subject": "u",
        "x-boltrig-role": role, "x-boltrig-departments": departments,
    }


# --- M7 / SEC-69: /v1/work is keyset-paginated and the page is clamped --------
def _work_client(store: InMemoryStore, n: int) -> TestClient:
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))

    async def _seed():
        for i in range(n):
            await store.create_work_item(
                WorkItem(id=f"w-{i:03d}", tenant_id=T, source="internal",
                         intent=f"task {i}", confidence=0.9, convergent=True,
                         status=WorkStatus.PENDING, owner_member="engineering")
            )

    asyncio.run(_seed())
    return TestClient(create_app(Kernel(store)))


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
def test_list_work_is_paginated_and_clamped():
    c = _work_client(InMemoryStore(), n=12)

    # a limit over the ceiling is clamped to MAX_WORK_PAGE (never honoured raw).
    over = c.get("/v1/work?limit=9999", headers=_hdr("engineer", "engineering"))
    assert over.status_code == 200
    assert over.json()["limit"] == MAX_WORK_PAGE

    # two pages cover the whole set with no overlap, via the returned cursor.
    p1 = c.get("/v1/work?limit=5", headers=_hdr("engineer", "engineering")).json()
    assert len(p1["items"]) == 5
    assert p1["next_cursor"] is not None
    p2 = c.get(f"/v1/work?limit=5&cursor={p1['next_cursor']}",
               headers=_hdr("engineer", "engineering")).json()
    assert len(p2["items"]) == 5
    p3 = c.get(f"/v1/work?limit=5&cursor={p2['next_cursor']}",
               headers=_hdr("engineer", "engineering")).json()
    assert len(p3["items"]) == 2  # remainder
    assert p3["next_cursor"] is None  # short page => end of the slice

    ids1 = [w["id"] for w in p1["items"]]
    ids2 = [w["id"] for w in p2["items"]]
    ids3 = [w["id"] for w in p3["items"]]
    seen = ids1 + ids2 + ids3
    assert len(seen) == len(set(seen)) == 12  # full coverage, no overlap


# --- M7 / US-IAM-02: work-detail children are queried by parent_id ------------
def _detail_client(store: _SpyStore) -> TestClient:
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))

    async def _seed():
        await store.create_work_item(
            WorkItem(id="epic-1", tenant_id=T, source="slack", intent="matter",
                     confidence=0.9, convergent=False, status=WorkStatus.IN_FLIGHT,
                     owner_member="engineering")
        )
        await store.create_work_item(
            WorkItem(id="story-1", tenant_id=T, source="internal", intent="draft",
                     confidence=0.8, convergent=True, status=WorkStatus.PENDING,
                     owner_member="engineering", parent_id="epic-1")
        )
        await store.create_work_item(
            WorkItem(id="mkt-1", tenant_id=T, source="internal", intent="campaign",
                     confidence=0.9, convergent=True, status=WorkStatus.PENDING,
                     owner_member="marketing")
        )

    asyncio.run(_seed())
    return TestClient(create_app(Kernel(store)))


@pytest.mark.security
@pytest.mark.invariant("US-IAM-02")
def test_work_detail_children_query_is_bounded():
    store = _SpyStore()
    c = _detail_client(store)

    r = c.get("/v1/work/epic-1", headers=_hdr("engineer", "engineering"))
    assert r.status_code == 200
    assert {ch["id"] for ch in r.json()["children"]} == {"story-1"}  # right children

    # US-IAM-02 preserved: a marketing item is out of the engineer's scope -> 404.
    assert c.get("/v1/work/mkt-1", headers=_hdr("engineer", "engineering")).status_code == 404

    # the detail path queried children DIRECTLY by parent_id and NEVER loaded the
    # whole department-visible set (a parent_id=None list scan).
    assert any(call["parent_id"] == "epic-1" for call in store.work_list_calls)
    assert all(call["parent_id"] is not None for call in store.work_list_calls)


# --- M9-memory / SEC-009 / SEC-69: memory list clamp + ingest cap -------------
async def _memory_kernel(store: _SpyStore):
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = build_memory_adapter(
        LocalMemoryEngine(), store, audit=k.audit,
        config={"embedding_endpoint": "local", "local_endpoints": ["local"]},
    )
    await k.register_adapter(T, adapter)
    return k


def _mem_hdr(sub="alice", role="employee", grants="*"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": sub,
            "x-boltrig-role": role, "x-boltrig-grants": grants}


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
def test_memory_list_limits_clamped_and_ingest_capped():
    store = _SpyStore()
    k = asyncio.run(_memory_kernel(store))
    c = TestClient(create_app(k, platform={}))

    # a caller limit over the ceiling is clamped before it reaches the store.
    assert c.get("/v1/memory/facts?limit=9999", headers=_mem_hdr()).status_code == 200
    assert store.fact_list_limits[-1] == MAX_MEMORY_LIST
    assert c.get("/v1/memory/ingestions?limit=9999", headers=_mem_hdr()).status_code == 200
    assert store.ingestion_list_limits[-1] == MAX_MEMORY_LIST

    # a batch ingest over the item cap is refused before any screening work.
    over = c.post(
        "/v1/memory/ingest",
        json={"source_kind": "document", "source_ref": "d",
              "items": [f"note {i}" for i in range(MAX_INGEST_ITEMS + 1)]},
        headers=_mem_hdr(),
    )
    assert over.status_code == 413
    # a within-cap ingest is accepted (the cap does not break the normal path).
    ok = c.post(
        "/v1/memory/ingest",
        json={"source_kind": "document", "source_ref": "d",
              "items": ["clean onboarding note"]},
        headers=_mem_hdr(),
    )
    assert ok.status_code == 200
