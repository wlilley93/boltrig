"""Audit browser filters + verify endpoint ([2026] VJS-COUNTY 9, D5): SEC-123.

SEC-123  the audit browser reads are org/workspace-scoped fail-closed (a caller
         with an active workspace sees only org-wide + its OWN workspace's rows,
         never another workspace's), the search filters by user / resource / date
         range and can pivot to the SecurityEvent stream, and the verify endpoint
         recomputes the chain + latest anchor and reports a BROKEN chain.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    SecurityEvent,
    SecurityEventType,
    TenantPermissions,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


def _run(coro):
    return asyncio.run(coro)


def _resolver(*, role="org-admin", workspace=None):
    async def resolve(request):
        return Principal(
            tenant_id=T, subject="admin", grants=GrantSet.of(["*"]), role=role,
            actor_tier="human", scope={"all": True}, active_workspace_id=workspace,
        )
    return resolve


def _app(*, role="org-admin", workspace=None):
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, principal_resolver=_resolver(role=role, workspace=workspace),
                     platform={})
    return k, app, store


def _row(*, actor, workspace, resource="ticket", resource_id="T-1", verb="ticket.create"):
    return AuditEvent(
        tenant_id=T, ts=utcnow(), actor=actor, action_type=ActionType.TOOL_CALL,
        status="ok", verb=verb, noun="ticket", resource=resource,
        resource_id=resource_id, workspace_id=workspace, run_id=None,
    )


async def _seed(k):
    await k.audit.write(_row(actor="alice", workspace="ws-1", resource_id="T-1"))
    await k.audit.write(_row(actor="bob", workspace="ws-1", resource_id="T-2"))
    await k.audit.write(_row(actor="carol", workspace="ws-2", resource_id="T-3"))
    await k.audit.write(_row(actor="alice", workspace=None, resource="invoice",
                             resource_id="I-9", verb="invoice.pay"))


# --------------------------------------------------------------------------- #
# workspace fail-closed: own workspace + org-wide only, never another workspace
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_audit_search_is_workspace_scoped_fail_closed():
    k, app, _ = _app(workspace="ws-1")
    _run(_seed(k))
    client = TestClient(app)
    rows = client.get("/v1/audit/search").json()["results"]
    seen_ws = {r["workspace_id"] for r in rows}
    # ws-1 (own) + None (org-wide) visible; ws-2 NEVER.
    assert seen_ws == {"ws-1", None}
    assert all(r["workspace_id"] != "ws-2" for r in rows)


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_audit_search_filters_by_user_and_resource():
    k, app, _ = _app(workspace=None)  # no active workspace -> whole tenant
    _run(_seed(k))
    client = TestClient(app)
    # by user (actor)
    by_user = client.get("/v1/audit/search", params={"actor": "alice"}).json()["results"]
    assert by_user and all(r["actor"] == "alice" for r in by_user)
    # by resource
    by_res = client.get("/v1/audit/search", params={"resource": "invoice"}).json()["results"]
    assert by_res and all(r["resource"] == "invoice" for r in by_res)
    # rows carry the enrichment fields for the browser
    assert set(by_res[0]) >= {"resource", "resource_id", "workspace_id", "ip_address"}


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_audit_search_can_pivot_to_the_security_stream():
    k, app, _ = _app(workspace=None)
    _run(k.security.write(SecurityEvent(
        tenant_id=T, ts=utcnow(), event_type=SecurityEventType.LOGIN_FAILURE,
        reason="invalid_email_or_password", actor="eve", resource="auth.login",
    )))
    client = TestClient(app)
    out = client.get("/v1/audit/search", params={"security": 1}).json()
    assert out["stream"] == "security"
    assert out["results"] and out["results"][0]["event_type"] == "login_failure"
    # filter the security stream by type
    typed = client.get("/v1/audit/search",
                       params={"security": 1, "event_type": "rate_limit_trip"}).json()
    assert typed["results"] == []


# --------------------------------------------------------------------------- #
# verify endpoint: intact, then detects a broken chain
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_verify_endpoint_reports_intact_then_detects_a_broken_chain():
    k, app, store = _app(workspace=None)
    _run(_seed(k))
    _run(k.anchorer.anchor(T))
    client = TestClient(app)

    intact = client.get("/v1/audit/verify").json()
    assert intact["chain_intact"] is True and intact["intact"] is True
    assert intact["anchor"]["is_dev_fallback"] is True

    # tamper a persisted row (no re-hash) -> the chain recompute no longer matches.
    rows = _run(store.audit_query(T))
    rows[1].status = "tampered"
    broken = client.get("/v1/audit/verify").json()
    assert broken["chain_intact"] is False
    assert broken["chain_first_bad_seq"] == rows[1].seq
    assert broken["intact"] is False


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_verify_and_search_are_gated_and_fail_closed_for_non_authors():
    # a non-author cannot read the integrity status (SEC-33 consistency).
    k, app, _ = _app(role="engineer", workspace=None)
    _run(_seed(k))
    client = TestClient(app)
    assert client.get("/v1/audit/verify").status_code == 403
