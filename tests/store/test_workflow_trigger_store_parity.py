"""Memory/Postgres parity for workflow trigger bindings and replay receipts."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import pytest

from boltrig.models import (
    Channel,
    GrantSet,
    WorkflowTrigger,
    WorkflowTriggerDelivery,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "workflow-trigger-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE workflow_trigger_deliveries,workflow_triggers,channels "
        "RESTART IDENTITY CASCADE"
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
async def trigger_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
@pytest.mark.invariant("SEC-08")
async def test_trigger_binding_and_receipt_semantics_match_on_both_stores(
    trigger_store,
):
    store = trigger_store
    webhook = WorkflowTrigger(
        id="hook",
        tenant_id=T,
        workflow_id="release",
        name="release-hook",
        source="webhook",
        owner_id="author",
        grant_ceiling=GrantSet.of(
            ["control.workflow.trigger"], ["control.workflow.delete"]
        ),
        secret_hash="a" * 64,
    )
    assert await store.create_workflow_trigger(webhook)
    assert not await store.create_workflow_trigger(webhook)

    got = await store.get_workflow_trigger(T, webhook.id)
    assert got is not None
    assert got.secret_hash == "a" * 64
    assert got.grant_ceiling == webhook.grant_ceiling
    assert await store.get_workflow_trigger("other-tenant", webhook.id) is None
    assert [item.id for item in await store.list_workflow_triggers(T, "release")] == [
        "hook"
    ]

    disabled = await store.set_workflow_trigger_enabled(T, webhook.id, False)
    assert disabled is not None and not disabled.enabled
    rotated = await store.rotate_workflow_trigger_secret(T, webhook.id, "b" * 64)
    assert rotated is not None and rotated.secret_hash == "b" * 64

    delivery = WorkflowTriggerDelivery(
        trigger_id=webhook.id,
        tenant_id=T,
        source_event_digest="d" * 64,
        status="queued",
        authority_subject="author",
        run_id="run-1",
    )
    attempts = await asyncio.gather(
        store.record_workflow_trigger_delivery(delivery),
        store.record_workflow_trigger_delivery(
            replace(delivery, status="denied", reason="must-not-overwrite")
        ),
    )
    assert sum(1 for _, inserted in attempts if inserted) == 1
    immutable = await store.get_workflow_trigger_delivery(
        T, webhook.id, delivery.source_event_digest
    )
    assert immutable is not None
    assert immutable.status == "queued"
    assert immutable.reason is None
    listed = await store.list_workflow_trigger_deliveries(T, webhook.id)
    assert listed == [immutable]
    assert (
        await store.get_workflow_trigger_delivery(
            "other-tenant", webhook.id, delivery.source_event_digest
        )
        is None
    )

    await store.upsert_channel(
        Channel(
            id="events",
            tenant_id=T,
            platform="webhook",
            name="Events",
            transport="webhook",
            credential_ref="events-secret",
        )
    )
    channel = WorkflowTrigger(
        id="channel",
        tenant_id=T,
        workflow_id="release",
        name="channel-events",
        source="channel",
        owner_id="author",
        grant_ceiling=GrantSet.of(["*"]),
        channel_id="events",
    )
    assert await store.create_workflow_trigger(channel)
    assert [
        item.id
        for item in await store.list_channel_workflow_triggers(T, "events")
    ] == ["channel"]
    await store.set_workflow_trigger_enabled(T, channel.id, False)
    assert await store.list_channel_workflow_triggers(T, "events") == []
    assert (
        await store.rotate_workflow_trigger_secret(T, channel.id, "c" * 64)
        is None
    )
