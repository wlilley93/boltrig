"""DH-1: desktop control goes through the chokepoint, with no side door.

``desktop.*`` verbs give the familiar governed hands on the host desktop. The kernel cannot reach the
compositor, so a granted dispatch lands in the shared HandsRegistry and a host executor pulls it over
the authenticated ``/v1/hands`` surface. These tests pin the whole loop: an ungranted caller is denied
and audited and NOTHING is queued (no side door), bad params are rejected by the binding before the
handler runs, a granted call is dispatched + audited + queued, a claimed command cannot be claimed
twice, a receipt resolves the waiting dispatch, and an absent executor reports executor_offline while
the governed act still stands.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.desktop import build as build_desktop
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.hands_registry import HandsRegistry
from boltrig.models import (
    GrantMissing,
    GrantSet,
    InvocationContext,
    SchemaValidationError,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

TENANT = "acme"


def _ctx(grants: list[str]) -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(grants),
        actor="ephemeral-1",
        actor_tier="ephemeral",
        run_id="run-dh1",
    )


async def _desktop_kernel(wait_seconds: float = 8.0) -> tuple[Kernel, HandsRegistry]:
    store = InMemoryStore()
    # the tenant ceiling must also permit the verb (intersection with the caller's grants)
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["desktop.*"])))
    kernel = Kernel(store, blocking_verbs=set())
    registry = HandsRegistry()
    kernel.hands_registry = registry  # the bootstrap wiring: one registry, shared
    await kernel.register_adapter(TENANT, build_desktop(registry, wait_seconds=wait_seconds))
    return kernel, registry


async def _queued(registry: HandsRegistry) -> dict:
    """Wait for the dispatched task to reach the handler and enqueue its command."""
    for _ in range(200):
        pending = registry.pending()
        if pending:
            return pending[0]
        await asyncio.sleep(0.005)
    raise AssertionError("no command was queued")


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_granted_focus_dispatches_audits_and_queues():
    kernel, registry = await _desktop_kernel()
    task = asyncio.create_task(
        kernel.invoke(
            "desktop", "desktop.window.focus", {"address": "0xabc"}, _ctx(["desktop.window.focus"])
        )
    )
    cmd = await _queued(registry)
    # the dispatched command carries exactly what the governed call authorised
    assert cmd["verb"] == "desktop.window.focus"
    assert cmd["args"] == {"address": "0xabc"}
    assert cmd["run_id"] == "run-dh1"
    assert cmd["claimed"] is False and cmd["queued_at"]
    registry.complete(cmd["id"], {"status": "ok"})
    out = await task
    assert out["delivered"] is True and out["status"] == "ok"
    events = await kernel.store.audit_query(TENANT)
    row = events[-1]
    assert row.verb == "desktop.window.focus"
    assert row.status == "ok"
    assert row.target_adapter == "desktop"


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_ungranted_desktop_call_is_denied_audited_and_queues_nothing():
    kernel, registry = await _desktop_kernel()
    with pytest.raises(GrantMissing):
        await kernel.invoke(
            "desktop", "desktop.window.focus", {"address": "0xabc"}, _ctx([])
        )
    # denied is still audited (SEC-16), and NO command reached the host (no side door)
    events = await kernel.store.audit_query(TENANT)
    assert events[-1].verb == "desktop.window.focus"
    assert events[-1].status == "grant_missing"
    assert registry.pending() == []


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_schema_bad_args_are_rejected_by_the_binding_and_queue_nothing():
    kernel, registry = await _desktop_kernel()
    # a negative width fails schema validation BEFORE the handler runs (SEC-21)
    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "desktop",
            "desktop.window.move",
            {"address": "0xabc", "x": 0, "y": 0, "width": -10, "height": 100},
            _ctx(["desktop.window.move"]),
        )
    assert registry.pending() == []


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_full_round_trip_receipt_resolves_the_waiting_dispatch():
    kernel, registry = await _desktop_kernel()
    task = asyncio.create_task(
        kernel.invoke(
            "desktop", "desktop.window.list", {}, _ctx(["desktop.window.list"])
        )
    )
    cmd = await _queued(registry)
    # the executor claims it (mark-on-read): a second poll must NOT see it again
    assert registry.claim(cmd["id"]) is not None
    assert registry.pending() == []
    assert registry.claim(cmd["id"]) is None
    receipt = {
        "status": "ok",
        "result": {"windows": [{"address": "0xabc", "title": "term"}]},
        "side_effects": [],
    }
    assert registry.complete(cmd["id"], receipt) is True
    out = await task
    assert out["delivered"] is True
    assert out["status"] == "ok"
    assert out["result"] == {"windows": [{"address": "0xabc", "title": "term"}]}
    assert out["side_effects"] == []


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_executor_offline_still_dispatches_and_audits():
    # a short injected wait keeps the suite fast; production uses the 8 s default
    kernel, registry = await _desktop_kernel(wait_seconds=0.05)
    out = await kernel.invoke(
        "desktop", "desktop.window.focus", {"address": "0xabc"}, _ctx(["desktop.window.focus"])
    )
    # the governed act happened and is audited; delivery is best-effort (decision 0014 doctrine)
    assert out == {"status": "executor_offline", "delivered": False}
    # the timed-out command was expired + removed: a late receipt is refused
    assert registry.pending() == []
    assert registry.complete("anything", {"status": "ok"}) is False
    events = await kernel.store.audit_query(TENANT)
    assert events[-1].verb == "desktop.window.focus"
    assert events[-1].status == "ok"


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_hands_routes_require_the_principal():
    # both routes are behind the normal authenticated principal (SEC-01)
    from fastapi import HTTPException

    async def deny_all(request):  # noqa: ARG001
        raise HTTPException(status_code=401, detail="denied")

    kernel, _ = await _desktop_kernel()
    client = TestClient(create_app(kernel, principal_resolver=deny_all))
    assert client.get("/v1/hands/commands").status_code == 401
    assert client.post("/v1/hands/commands/x/receipt", json={"status": "ok"}).status_code == 401


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_hands_routes_claim_once_and_record_the_receipt():
    kernel, registry = await _desktop_kernel()
    client = TestClient(create_app(kernel))
    headers = {"x-boltrig-tenant": TENANT, "x-boltrig-subject": "hands-exec-1"}
    task = asyncio.create_task(
        kernel.invoke(
            "desktop", "desktop.window.focus", {"address": "0xabc"}, _ctx(["desktop.window.focus"])
        )
    )
    cmd = await _queued(registry)
    # the executor's poll claims the command; a second poll gets nothing (no double-execute)
    r1 = client.get("/v1/hands/commands", headers=headers)
    assert r1.status_code == 200
    commands = r1.json()["commands"]
    assert [c["id"] for c in commands] == [cmd["id"]]
    assert commands[0]["claimed"] is True
    assert commands[0]["verb"] == "desktop.window.focus"
    assert commands[0]["args"] == {"address": "0xabc"}
    r2 = client.get("/v1/hands/commands", headers=headers)
    assert r2.status_code == 200 and r2.json()["commands"] == []
    # resolving the waiting dispatch from THIS loop (TestClient serves on a
    # portal thread; an asyncio.Event with a waiter must be set on its own loop)
    registry.complete(cmd["id"], {"status": "ok"})
    out = await task
    assert out["delivered"] is True
    # the receipt POST records the execution kernel-side (SEC-16)
    r3 = client.post(
        f"/v1/hands/commands/{cmd['id']}/receipt", json={"status": "ok"}, headers=headers
    )
    assert r3.status_code == 404  # already resolved above: the id is gone
    cmd2 = registry.create("desktop.window.focus", {"address": "0xdef"}, "run-dh1")
    r4 = client.post(
        f"/v1/hands/commands/{cmd2['id']}/receipt", json={"status": "ok"}, headers=headers
    )
    assert r4.status_code == 200 and r4.json() == {"status": "ok"}
    # an unknown command id is refused
    r5 = client.post(
        "/v1/hands/commands/nope/receipt", json={"status": "ok"}, headers=headers
    )
    assert r5.status_code == 404
    # a malformed receipt is refused
    r6 = client.post(
        f"/v1/hands/commands/{cmd2['id']}/receipt", json={"status": "maybe"}, headers=headers
    )
    assert r6.status_code == 400
    events = await kernel.store.audit_query(TENANT)
    receipts = [e for e in events if e.verb == "desktop.hands.receipt"]
    assert len(receipts) == 1
    assert receipts[0].status == "ok"
    assert receipts[0].detail["command"] == cmd2["id"]


@pytest.mark.security
@pytest.mark.invariant("DH-1")
async def test_desktop_verbs_only_exist_when_the_addon_is_enabled(monkeypatch):
    """DH-1: the add-on is opt-in (BOLTRIG_DESKTOP_HANDS=1). A boot without the flag must not
    even register the capability: no desktop adapter, no verbs, nothing to grant. The kernel
    that does not drive a desktop never advertises one."""
    from boltrig.api.bootstrap import _seed_default
    from boltrig.kernel.hands_registry import HandsRegistry as _HR

    # flag OFF: no registry attached, no adapter registered
    monkeypatch.delenv("BOLTRIG_DESKTOP_HANDS", raising=False)
    kernel = Kernel(InMemoryStore(), blocking_verbs=set())
    await _seed_default(kernel)
    assert kernel.loader.peek("default", "desktop") is None
    assert getattr(kernel, "hands_registry", None) is None

    # flag ON: the add-on registers the adapter against the shared registry
    monkeypatch.setenv("BOLTRIG_DESKTOP_HANDS", "1")
    kernel2 = Kernel(InMemoryStore(), blocking_verbs=set())
    kernel2.hands_registry = _HR()
    await _seed_default(kernel2)
    assert kernel2.loader.peek("default", "desktop") is not None
