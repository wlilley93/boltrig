"""Tenant-collision regressions for the live in-process run-event relay."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store import InMemoryStore

RUN_ID = "chosen-collision"
VICTIM = "victim"
EVIL = "evil"


async def _seed() -> Kernel:
    kernel = Kernel(InMemoryStore())
    for tenant in (VICTIM, EVIL):
        await kernel.store.create_work_item(
            WorkItem(
                id=RUN_ID,
                tenant_id=tenant,
                source="internal",
                intent=f"{tenant} run",
                confidence=1.0,
                convergent=True,
                status=WorkStatus.DONE,
                owner_member="engineering",
            )
        )
        await kernel.audit.write(
            AuditEvent(
                tenant_id=tenant,
                ts=utcnow(),
                run_id=RUN_ID,
                actor=f"{tenant}-agent",
                actor_tier="ephemeral",
                action_type=ActionType.TOOL_CALL,
                status="ok",
                verb="ticket.read",
            )
        )
    return kernel


def _client(kernel: Kernel) -> TestClient:
    async def resolver(request: Request) -> Principal:
        tenant = request.headers.get("x-test-tenant")
        if tenant not in {VICTIM, EVIL}:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return Principal(
            tenant_id=tenant,
            subject=f"{tenant}-user",
            grants=GrantSet.of(["*"]),
            role="org-admin",
            actor_tier="human",
            scope={"all": True},
        )

    return TestClient(create_app(kernel, principal_resolver=resolver, platform={}))


@pytest.mark.security
@pytest.mark.invariant("SEC-56")
def test_authorized_same_run_id_cannot_read_another_tenants_backlog() -> None:
    kernel = asyncio.run(_seed())
    client = _client(kernel)
    victim_event = {"type": "text_delta", "delta": "VICTIM_SECRET"}
    evil_event = {"type": "text_delta", "delta": "evil-owned"}
    kernel.events.publish(VICTIM, RUN_ID, victim_event)
    kernel.events.publish(EVIL, RUN_ID, evil_event)

    victim = client.get(f"/v1/runs/{RUN_ID}/events", headers={"x-test-tenant": VICTIM})
    evil = client.get(f"/v1/runs/{RUN_ID}/events", headers={"x-test-tenant": EVIL})

    assert victim.status_code == evil.status_code == 200
    assert "VICTIM_SECRET" in victim.text and "evil-owned" not in victim.text
    assert "evil-owned" in evil.text and "VICTIM_SECRET" not in evil.text


@pytest.mark.security
@pytest.mark.invariant("SEC-56")
async def test_same_run_id_live_publish_and_close_are_tenant_scoped() -> None:
    relay = EventRelay()
    victim = relay.for_tenant(VICTIM)
    evil = relay.for_tenant(EVIL)
    victim_received: list[dict] = []
    received: list[dict] = []

    async def consume_victim() -> None:
        async for event in victim.subscribe(RUN_ID, replay=False):
            victim_received.append(event)

    async def consume_evil() -> None:
        async for event in evil.subscribe(RUN_ID, replay=False):
            received.append(event)

    victim_consumer = asyncio.create_task(consume_victim())
    consumer = asyncio.create_task(consume_evil())
    await asyncio.sleep(0)
    victim.publish(RUN_ID, {"type": "text_delta", "delta": "VICTIM_LIVE_SECRET"})
    victim.close(RUN_ID)
    await asyncio.wait_for(victim_consumer, timeout=1)

    assert not consumer.done()
    assert received == []
    assert victim_received == [{"type": "text_delta", "delta": "VICTIM_LIVE_SECRET"}]
    evil.publish(RUN_ID, {"type": "text_delta", "delta": "evil-live"})
    evil.close(RUN_ID)
    await asyncio.wait_for(consumer, timeout=1)

    assert received == [{"type": "text_delta", "delta": "evil-live"}]
    assert victim.snapshot(RUN_ID) == [{"type": "text_delta", "delta": "VICTIM_LIVE_SECRET"}]
    assert evil.snapshot(RUN_ID) == [{"type": "text_delta", "delta": "evil-live"}]
