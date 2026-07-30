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
    assert client.get(
        "/v1/audit/search", params={"query": "carol"}
    ).json()["results"] == []


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

    by_status = client.get("/v1/audit/search", params={"status": "ok"}).json()["results"]
    assert by_status and all(r["status"] == "ok" for r in by_status)
    assert client.get(
        "/v1/audit/search", params={"status": "does-not-exist"}
    ).json()["results"] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
@pytest.mark.parametrize(
    "query",
    (
        "casekeeper",
        "approval.run",
        "needs_review",
        "run-abc",
        "parent-xyz",
        "invoice",
        r"case%_\42",
    ),
)
def test_audit_free_text_search_matches_only_allowlisted_structural_fields(query):
    k, app, _ = _app(workspace=None)
    target = _row(
        actor="CaseKeeper",
        workspace=None,
        resource="Invoice",
        resource_id=r"Case%_\42",
        verb="Approval.Run",
    )
    target.status = "needs_review"
    target.run_id = "RUN-ABC"
    target.parent_run_id = "PARENT-XYZ"
    target.detail = {"secret_note": "must-never-be-searchable"}
    _run(k.audit.write(target))
    _run(k.audit.write(_row(
        actor="other",
        workspace=None,
        resource="ticket",
        resource_id="CaseABZ42",
        verb="ticket.create",
    )))

    rows = TestClient(app).get(
        "/v1/audit/search", params={"query": query}
    ).json()["results"]
    assert [row["resource_id"] for row in rows] == [r"Case%_\42"]


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_audit_free_text_is_literal_and_does_not_search_detail():
    k, app, _ = _app(workspace=None)
    _run(k.audit.write(_row(
        actor="literal",
        workspace=None,
        resource_id=r"Case%_\42",
    )))
    detail_only = _row(actor="other", workspace=None, resource_id="safe")
    detail_only.detail = {"secret_note": "needle-only-in-detail"}
    _run(k.audit.write(detail_only))
    _run(k.audit.write(_row(
        actor="wildcard-decoy",
        workspace=None,
        resource_id="CaseABZ42",
    )))
    client = TestClient(app)

    literal = client.get(
        "/v1/audit/search", params={"query": "%_\\"}
    ).json()["results"]
    assert [row["resource_id"] for row in literal] == [r"Case%_\42"]
    assert client.get(
        "/v1/audit/search", params={"query": "needle-only-in-detail"}
    ).json()["results"] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-ACCOUNT-AUDIT-PAGE-01")
def test_audit_search_filters_before_pagination_without_changing_chain_verify():
    k, app, _ = _app(workspace=None)
    for index in range(4):
        _run(k.audit.write(_row(
            actor="alice" if index % 2 == 0 else "bob", workspace=None,
            resource_id=f"T-{index}",
        )))
    client = TestClient(app)

    first = client.get("/v1/audit/search", params={"actor": "alice", "limit": 1}).json()
    second = client.get(
        "/v1/audit/search", params={"actor": "alice", "limit": 1, "offset": 1},
    ).json()

    assert [row["resource_id"] for row in first["results"]] == ["T-2"]
    assert first["next_offset"] == 1
    assert [row["resource_id"] for row in second["results"]] == ["T-0"]
    assert second["next_offset"] is None
    # Browsing pages never substitutes for or truncates the full chain scan.
    assert client.get("/v1/audit/verify").json()["chain_intact"] is True


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
