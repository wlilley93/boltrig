"""Exact memory detail links retain the kernel's owner-scope boundary."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import MemoryFact
from boltrig.store import InMemoryStore


TENANT = "memory-detail-tenant"


def _headers(subject: str, *, tenant: str = TENANT) -> dict[str, str]:
    return {
        "x-boltrig-tenant": tenant,
        "x-boltrig-subject": subject,
        "x-boltrig-role": "member",
        "x-boltrig-grants": "*",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-23")
def test_memory_fact_detail_reauthorizes_tenant_and_owner_scope() -> None:
    store = InMemoryStore()

    async def seed() -> None:
        for tenant, fact_id, owner_scope, content in (
            (TENANT, "fact-alice", "user:alice", "Alice visible"),
            (TENANT, "fact-bob", "user:bob", "Bob private"),
            ("other-tenant", "fact-foreign", "user:alice", "Foreign private"),
        ):
            await store.add_memory_fact(
                MemoryFact(
                    id=fact_id,
                    tenant_id=tenant,
                    owner_scope=owner_scope,
                    engine_ref=f"engine:{fact_id}",
                    kind="decision",
                    source_kind="conversation",
                    source_ref=f"conversation:{fact_id}",
                    content=content,
                )
            )

    asyncio.run(seed())
    client = TestClient(create_app(Kernel(store), platform={}))

    visible = client.get(
        "/v1/memory/facts/fact-alice",
        headers=_headers("alice"),
    )
    assert visible.status_code == 200
    assert visible.json()["fact"]["content"] == "Alice visible"

    hidden = client.get(
        "/v1/memory/facts/fact-bob",
        headers=_headers("alice"),
    )
    foreign = client.get(
        "/v1/memory/facts/fact-foreign",
        headers=_headers("alice"),
    )
    missing = client.get(
        "/v1/memory/facts/does-not-exist",
        headers=_headers("alice"),
    )
    assert hidden.status_code == foreign.status_code == missing.status_code == 404
    assert hidden.json() == foreign.json() == missing.json() == {
        "error": "not_found"
    }
