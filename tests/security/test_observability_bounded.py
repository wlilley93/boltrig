"""Observability reads are bounded in the store, never load-then-filter (SEC-69).

The console/cost/telemetry/audit-search routes used to load the tenant's whole
work table (twice, via dept_run_ids) plus a 10_000-row audit slice per request
and filter in Python. The run-scope predicate (department + workspace) now runs
INSIDE the store query under a clamped page, and the console's HITL visibility
checks are batched into ONE work-item ref lookup instead of an N+1.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    HITLRequest,
    HITLType,
    TenantPermissions,
    Urgency,
    WorkItem,
    utcnow,
)
from boltrig.store import InMemoryStore
from boltrig.store.base import DEFAULT_WORK_PAGE, MAX_OBSERVABILITY_PAGE, MAX_WORK_PAGE

T = "acme"


class _SpyStore(InMemoryStore):
    """Counts the reads the observability routes must NOT fall back to."""

    def __init__(self) -> None:
        super().__init__()
        self.work_list_calls = 0
        self.legacy_audit_query_calls = 0
        self.scoped_calls: list[dict] = []
        self.scoped_result_sizes: list[int] = []
        self.run_scoped_calls: list[dict] = []
        self.run_scoped_result_sizes: list[int] = []
        self.ref_lookups: list[list[str]] = []
        self.work_item_gets = 0
        self.run_id_gets = 0
        self.permission_reads = 0
        self.member_reads = 0

    async def list_work_items(self, *args, **kwargs):
        self.work_list_calls += 1
        return await super().list_work_items(*args, **kwargs)

    async def audit_query(self, *args, **kwargs):
        self.legacy_audit_query_calls += 1
        return await super().audit_query(*args, **kwargs)

    async def audit_query_scoped(self, tenant_id, **kwargs):
        self.scoped_calls.append(kwargs)
        rows = await super().audit_query_scoped(tenant_id, **kwargs)
        self.scoped_result_sizes.append(len(rows))
        return rows

    async def list_run_items_scoped(self, tenant_id, **kwargs):
        self.run_scoped_calls.append(kwargs)
        rows = await super().list_run_items_scoped(tenant_id, **kwargs)
        self.run_scoped_result_sizes.append(len(rows))
        return rows

    async def list_work_items_by_refs(self, tenant_id, refs):
        self.ref_lookups.append(list(refs))
        return await super().list_work_items_by_refs(tenant_id, refs)

    async def get_work_item(self, *args, **kwargs):
        self.work_item_gets += 1
        return await super().get_work_item(*args, **kwargs)

    async def get_work_item_by_run_id(self, *args, **kwargs):
        self.run_id_gets += 1
        return await super().get_work_item_by_run_id(*args, **kwargs)

    async def get_tenant_permissions(self, *args, **kwargs):
        self.permission_reads += 1
        return await super().get_tenant_permissions(*args, **kwargs)

    async def get_workspace_member(self, *args, **kwargs):
        self.member_reads += 1
        return await super().get_workspace_member(*args, **kwargs)


def _client(kernel: Kernel, store: _SpyStore, *, role="org-admin", scope=None) -> TestClient:
    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer good":
            raise HTTPException(status_code=401, detail="bad token")
        return Principal(
            tenant_id=T,
            subject="alice",
            grants=GrantSet.of(["*"]),
            role=role,
            actor_tier="human",
            scope=scope if scope is not None else {"all": True},
        )

    return TestClient(create_app(kernel, principal_resolver=resolver, platform={}))


def _kernel() -> tuple[Kernel, _SpyStore]:
    store = _SpyStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store), store


def _event(cost: int = 1, *, run_id=None, actor="worker") -> AuditEvent:
    return AuditEvent(
        tenant_id=T,
        ts=utcnow(),
        run_id=run_id,
        actor=actor,
        actor_tier="ephemeral",
        action_type=ActionType.MODEL_CALL,
        status="ok",
        cost_micros=cost,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
def test_observability_reads_do_not_load_full_tables():
    kernel, store = _kernel()
    # A tenant well past the page ceiling: the routes must read a clamped page,
    # never the whole table (and never the legacy 10k slice / work-table scan).
    overhang = 500

    async def seed() -> None:
        for _ in range(MAX_OBSERVABILITY_PAGE + overhang):
            await store.audit_append(_event())

    asyncio.run(seed())
    client = _client(kernel, store)

    cost = client.get("/v1/cost", headers={"authorization": "Bearer good"})
    assert cost.status_code == 200
    # every seeded row costs 1 micro; only the clamped tail page is summed
    assert cost.json()["total_cost_micros"] == MAX_OBSERVABILITY_PAGE

    for path in ("/v1/model/telemetry", "/v1/audit/search", "/v1/console/overview"):
        resp = client.get(path, headers={"authorization": "Bearer good"})
        assert resp.status_code == 200, path

    assert store.work_list_calls == 0
    assert store.legacy_audit_query_calls == 0
    assert store.scoped_calls  # every read went through the scoped query
    assert all(
        call["limit"] == MAX_OBSERVABILITY_PAGE for call in store.scoped_calls
    )
    assert all(size <= MAX_OBSERVABILITY_PAGE for size in store.scoped_result_sizes)


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
def test_audit_search_stays_department_scoped_via_the_store():
    kernel, store = _kernel()

    async def seed() -> None:
        await store.create_work_item(
            WorkItem(
                id="w-eng",
                tenant_id=T,
                source="internal",
                intent="eng task",
                confidence=1.0,
                convergent=True,
                owner_member="engineering",
            )
        )
        await store.audit_append(_event(run_id="w-eng", actor="eng-run"))
        await store.audit_append(_event(run_id=None, actor="audit-only"))

    asyncio.run(seed())
    client = _client(
        kernel, store, role="engineer", scope={"departments": ["engineering"]}
    )
    headers = {"authorization": "Bearer good"}
    actors = {
        row["actor"]
        for row in client.get("/v1/audit/search", headers=headers).json()["results"]
    }
    # the department's own run is visible; an audit-only event (no owning work
    # item) is not - exactly the old RunScope semantics, now enforced in SQL.
    assert actors == {"eng-run"}
    cost = client.get("/v1/cost", headers=headers).json()
    assert cost["by_actor"] == {"eng-run": 1}
    assert cost["scope"] == ["engineering"]


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-12")
def test_console_overview_batches_hitl_visibility_checks():
    kernel, store = _kernel()

    async def seed() -> None:
        for i in range(6):
            await store.create_work_item(
                WorkItem(
                    id=f"w-{i}",
                    tenant_id=T,
                    source="internal",
                    intent=f"task {i}",
                    confidence=1.0,
                    convergent=True,
                    owner_member="engineering",
                )
            )
            await store.create_hitl_request(
                HITLRequest(
                    id=f"hitl-{i}",
                    tenant_id=T,
                    run_id=f"w-{i}",
                    work_item_id=f"w-{i}",
                    type=HITLType.APPROVAL,
                    urgency=Urgency.BLOCKING,
                    question=f"Approve step {i}?",
                    context="deployment",
                    options=["approve", "deny"],
                    verb="ticket.create",
                    requested_by="worker",
                )
            )

    asyncio.run(seed())
    client = _client(kernel, store)
    resp = client.get("/v1/console/overview", headers={"authorization": "Bearer good"})

    assert resp.status_code == 200
    approvals = resp.json()["approvals"]
    assert [row["id"] for row in approvals] == [f"hitl-{i}" for i in range(6)]
    # ONE batched ref lookup covered every pending request; the per-request
    # work-item getters were never hit, and tenant permissions were read once.
    assert len(store.ref_lookups) == 1
    assert store.ref_lookups[0] == [f"w-{i}" for i in range(6)]
    assert store.work_item_gets == 0
    assert store.run_id_gets == 0
    assert store.permission_reads == 1
    assert store.member_reads == 0


@pytest.mark.security
@pytest.mark.invariant("SEC-69")
def test_runs_listing_is_keyset_paginated_and_bounded():
    kernel, store = _kernel()
    # A tenant past the default page: /v1/runs must return a clamped keyset
    # page, never the whole work table (the old dept_run_ids load).
    total = DEFAULT_WORK_PAGE + 25

    async def seed() -> None:
        for i in range(total):
            await store.create_work_item(
                WorkItem(
                    id=f"w-{i:04d}",
                    tenant_id=T,
                    source="internal",
                    intent=f"task {i}",
                    confidence=1.0,
                    convergent=True,
                    owner_member="engineering",
                )
            )

    asyncio.run(seed())
    client = _client(kernel, store)
    headers = {"authorization": "Bearer good"}

    first = client.get("/v1/runs", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert len(body["runs"]) == DEFAULT_WORK_PAGE
    assert body["limit"] == DEFAULT_WORK_PAGE
    cursor = body["next_cursor"]
    assert cursor == body["runs"][-1]["work_item"]

    # The cursor round-trips into the next page with no overlap, and a short
    # page ends the slice (same keyset idiom as /v1/work).
    second = client.get(f"/v1/runs?cursor={cursor}", headers=headers).json()
    assert len(second["runs"]) == 25
    assert second["next_cursor"] is None
    overlap = {row["work_item"] for row in body["runs"]} & {
        row["work_item"] for row in second["runs"]
    }
    assert not overlap

    # Even an absurd caller page size is clamped at the store ceiling.
    big = client.get("/v1/runs?limit=100000", headers=headers).json()
    assert big["limit"] == MAX_WORK_PAGE
    assert store.run_scoped_calls  # every read went through the scoped query
    assert all(call["limit"] <= MAX_WORK_PAGE for call in store.run_scoped_calls)
    assert all(size <= MAX_WORK_PAGE for size in store.run_scoped_result_sizes)
    # ... and the route never fell back to the legacy full-table reads.
    assert store.work_list_calls == 0
    assert store.legacy_audit_query_calls == 0
