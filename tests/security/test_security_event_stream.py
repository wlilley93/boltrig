"""The distinct SecurityEvent stream ([2026] VJS-COUNTY 9, D3): SEC-121.

SEC-121  the SecurityEvent stream is its OWN tamper-evident (hash-chained),
         append-only, keys-only stream, wired at the security-relevant paths:
         login failure + login throttle trip (auth_routes), permission denial
         (GrantMissing at the chokepoint), and MCP auth failure (a bad run token).
         It is SEPARATE from the business audit log.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantMissing,
    GrantSet,
    SecurityEvent,
    SecurityEventType,
    TenantPermissions,
    User,
    utcnow,
)
from boltrig.store import InMemoryStore
from tests.conftest import TENANT, make_ctx

T = "default"
OWNER = "owner@example.io"
OWNER_PW = "owner-password-123"


def _run(coro):
    return asyncio.run(coro)


def _app():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, principal_resolver=build_session_resolver(T), platform={})
    return k, app, store


async def _seat_owner(store):
    await store.upsert_user(User(
        id=OWNER, tenant_id=T, email=OWNER, role="superadmin",
        scope={"all": True}, status="active", source="initiate",
    ))
    await store.set_password_credential(T, OWNER, hash_password(OWNER_PW))


# --------------------------------------------------------------------------- #
# hash-chained + keys-only
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-121")
async def test_security_stream_is_hash_chained_and_keys_only(kernel):
    # Two signals chain: seq 1 has no prev, seq 2 chains to seq 1's hash.
    await kernel.security.write(SecurityEvent(
        tenant_id=TENANT, ts=utcnow(), event_type=SecurityEventType.LOGIN_FAILURE,
        reason="invalid_email_or_password", actor="a@x.io", ip_address="1.2.3.4",
    ))
    # keys-only (K-20): a secret handed in detail is scrubbed, never stored verbatim.
    await kernel.security.write(SecurityEvent(
        tenant_id=TENANT, ts=utcnow(), event_type=SecurityEventType.MCP_AUTH_FAILURE,
        reason="bad_token", detail={"token": "sk-supersecretvalue1234567890"},
    ))
    rows = await kernel.store.security_query(TENANT)
    assert len(rows) == 2
    assert rows[0].seq == 1 and rows[0].prev_hash is None and rows[0].hash
    assert rows[1].seq == 2 and rows[1].prev_hash == rows[0].hash
    # the secret never rides verbatim - it is digested.
    stored = rows[1].detail.get("token")
    assert isinstance(stored, dict) and stored.get("_scrubbed") is True
    assert "supersecret" not in str(rows[1].detail)

    ok, bad = await kernel.security.verify(TENANT)
    assert ok and bad is None
    # tamper is detected on the security chain (same guarantee as the audit chain).
    rows[0].reason = "tampered"
    ok2, bad2 = await kernel.security.verify(TENANT)
    assert not ok2 and bad2 == rows[0].seq


# --------------------------------------------------------------------------- #
# whole-chain verification: no tail window, ever (SEC-168)
# --------------------------------------------------------------------------- #
async def _long_security_chain(n: int):
    """A REAL hash-chained security stream of n rows on a fresh in-memory store."""
    from boltrig.kernel.security_events import SecurityWriter

    store = InMemoryStore()
    writer = SecurityWriter(store)
    for i in range(n):
        await writer.write(SecurityEvent(
            tenant_id=TENANT, ts=utcnow(), event_type=SecurityEventType.LOGIN_FAILURE,
            reason=f"attempt-{i}", actor="eve@x.io",
        ))
    return store, writer


@pytest.mark.security
@pytest.mark.invariant("SEC-168")
async def test_a_long_security_chain_verifies_ok():
    # False-positive regression: the old verify read only the newest 10_000 rows
    # and seeded prev=None, failing an UNTAMPERED chain longer than the window.
    _store, writer = await _long_security_chain(10_050)
    assert await writer.verify(TENANT) == (True, None)


@pytest.mark.security
@pytest.mark.invariant("SEC-168")
async def test_security_tamper_below_the_old_window_is_caught():
    # False-negative regression: seq 5 sits below the old 10_000-row tail window,
    # so tampering it was never re-derived. It must be caught with the right seq.
    store, writer = await _long_security_chain(10_050)
    next(e for e in store._security[TENANT] if e.seq == 5).reason = "tampered"
    assert await writer.verify(TENANT) == (False, 5)


# --------------------------------------------------------------------------- #
# separate stream: a business action does NOT land in the security stream
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-121")
async def test_security_stream_is_separate_from_the_audit_log(kernel):
    await kernel.invoke("ticket", "ticket.create", {"title": "x"},
                        make_ctx(["ticket.create"]))
    assert len(await kernel.store.audit_query(TENANT)) == 1
    assert await kernel.store.security_query(TENANT) == []


# --------------------------------------------------------------------------- #
# wired: permission denial at the chokepoint (GrantMissing)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-121")
async def test_permission_denial_at_chokepoint_records_a_security_signal(kernel):
    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", "ticket.create", {"title": "x", "id": "T-2"},
                            make_ctx([], actor="mallory"))
    sec = await kernel.store.security_query(TENANT)
    assert len(sec) == 1
    e = sec[0]
    assert e.event_type == SecurityEventType.PERMISSION_DENIED
    assert e.actor == "mallory" and e.resource == "ticket" and e.resource_id == "T-2"
    # the denial is ALSO in the audit log (both streams, at the same depth).
    assert (await kernel.store.audit_query(TENANT))[-1].status == "grant_missing"


# --------------------------------------------------------------------------- #
# wired: MCP auth failure (a bad/expired run token)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-121")
async def test_bad_mcp_run_token_records_an_mcp_auth_failure(kernel):
    resp = await kernel.mcp.handle(
        "not-a-real-token", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        ip_address="9.9.9.9", user_agent="curl/8",
    )
    assert resp["error"]["code"] == -32001
    sec = await kernel.store.security_query("_unauthenticated")
    assert len(sec) == 1
    assert sec[0].event_type == SecurityEventType.MCP_AUTH_FAILURE
    assert sec[0].ip_address == "9.9.9.9"


# --------------------------------------------------------------------------- #
# wired: login failure + login throttle trip (auth_routes)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-121")
def test_login_failure_and_throttle_record_security_signals(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    k, app, store = _app()
    _run(_seat_owner(store))
    client = TestClient(app)

    # a wrong password is a LOGIN_FAILURE signal.
    r = client.post("/v1/auth/login", json={"email": OWNER, "password": "wrong-pw"})
    assert r.status_code == 401
    sec = _run(store.security_query(T))
    assert any(e.event_type == SecurityEventType.LOGIN_FAILURE for e in sec)

    # hammering login past the per-identity bound is a RATE_LIMIT_TRIP signal.
    for _ in range(10):
        client.post("/v1/auth/login", json={"email": OWNER, "password": "wrong-pw"})
    sec = _run(store.security_query(T))
    assert any(e.event_type == SecurityEventType.RATE_LIMIT_TRIP for e in sec)
    # keys-only: no signal row carries the password.
    assert all("wrong-pw" not in str(e.detail) for e in sec)
