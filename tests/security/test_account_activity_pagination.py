"""Own-account audit activity is identity-filtered before its bounded page."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import ActionType, AuditEvent, GrantSet, TenantPermissions, utcnow
from boltrig.store import InMemoryStore

T = "account-activity"


class _Store(InMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.legacy_reads = 0

    async def audit_query(self, *args, **kwargs):
        self.legacy_reads += 1
        return await super().audit_query(*args, **kwargs)


def _event(actor: str, verb: str, *, on_behalf_of: str | None = None) -> AuditEvent:
    return AuditEvent(
        tenant_id=T, ts=utcnow(), actor=actor, on_behalf_of=on_behalf_of,
        action_type=ActionType.TOOL_CALL, status="ok", verb=verb,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-ACCOUNT-AUDIT-PAGE-01")
def test_account_activity_filters_identity_before_limit_and_pages_newest_first():
    store = _Store()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)

    async def seed() -> None:
        await kernel.audit.write(_event("alice", "own.oldest"))
        await kernel.audit.write(_event("delegate", "delegated", on_behalf_of="alice"))
        await kernel.audit.write(_event("alice", "own.newest"))
        for index in range(25):
            await kernel.audit.write(_event("someone-else", f"other.{index}"))

    asyncio.run(seed())

    async def resolver(request):
        return Principal(
            tenant_id=T, subject="alice", grants=GrantSet.of(["*"]),
            role="member", actor_tier="human", scope={"all": True},
        )

    client = TestClient(create_app(kernel, principal_resolver=resolver, platform={}))
    first = client.get("/v1/me/activity", params={"limit": 2, "offset": 0})
    second = client.get("/v1/me/activity", params={"limit": 2, "offset": 2})

    assert first.status_code == second.status_code == 200
    assert [row["verb"] for row in first.json()["results"]] == [
        "own.newest", "delegated",
    ]
    assert first.json()["next_offset"] == 2
    assert [row["verb"] for row in second.json()["results"]] == ["own.oldest"]
    assert second.json()["next_offset"] is None
    assert store.legacy_reads == 0


@pytest.mark.security
@pytest.mark.invariant("SEC-ACCOUNT-AUDIT-PAGE-01")
def test_account_activity_rejects_unbounded_pages():
    store = _Store()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)

    async def resolver(request):
        return Principal(
            tenant_id=T, subject="alice", grants=GrantSet.of(["*"]),
            role="member", actor_tier="human", scope={"all": True},
        )

    client = TestClient(create_app(kernel, principal_resolver=resolver, platform={}))
    assert client.get("/v1/me/activity", params={"limit": 51}).status_code == 422
    assert client.get("/v1/me/activity", params={"offset": 10_001}).status_code == 422
