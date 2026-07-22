"""The sole-author four-eyes bootstrap exemption (SEC-182).

On a tenant with exactly ONE active author-tier user, the independent-approver
rule is unsatisfiable: every high-consequence control verb - including the
invitation flow that would add a second human - deadlocks at four-eyes. The
exemption lifts self-approval only while that condition holds, always with an
audit flag; it lapses automatically the moment a second active author exists.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app
from boltrig.models import HITLStatus, HITLType, User
from tests.conftest import TENANT, _build_kernel


def _seat(k, subject: str, role: str, status: str = "active") -> None:
    asyncio.run(
        k.store.upsert_user(
            User(
                id=subject, tenant_id=TENANT, email=f"{subject}@example.com",
                role=role, status=status,
            )
        )
    )


def _request(k, requested_by: str):
    return asyncio.run(
        k.hitl.create(
            tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL,
            question="Approve ticket.create ?", verb="ticket.create",
            requested_by=requested_by, request_fingerprint="create-fp",
        )
    )


def _approve(client: TestClient, req_id: str, subject: str, grants: str = "ticket.create"):
    return client.post(
        f"/v1/hitl/{req_id}/respond",
        json={"decision": "approve"},
        headers={
            "x-boltrig-tenant": TENANT, "x-boltrig-subject": subject,
            "x-boltrig-tier": "human", "x-boltrig-grants": grants,
        },
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-182")
def test_sole_author_may_self_approve_with_an_audit_flag():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    _seat(k, "will", "superadmin")
    req = _request(k, "will")
    c = TestClient(create_app(k, platform={}))

    res = _approve(c, req.id, "will")

    assert res.status_code == 200
    assert res.json().get("sole_author_exemption") is True
    assert asyncio.run(k.hitl.get(TENANT, req.id)).status == HITLStatus.ANSWERED
    events = asyncio.run(k.store.audit_query(TENANT))
    flagged = [e for e in events if e.verb == "hitl.sole_author_approval"]
    assert len(flagged) == 1
    assert flagged[0].actor == "will"
    assert flagged[0].detail.get("hitl_request_id") == req.id


@pytest.mark.security
@pytest.mark.invariant("SEC-182")
def test_exemption_lapses_the_moment_a_second_author_exists():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    _seat(k, "will", "superadmin")
    _seat(k, "tom", "admin")
    req = _request(k, "will")
    c = TestClient(create_app(k, platform={}))

    assert _approve(c, req.id, "will").status_code == 403
    assert asyncio.run(k.hitl.get(TENANT, req.id)).status == HITLStatus.PENDING
    # The independent second author can still approve, as before.
    assert _approve(c, req.id, "tom").status_code == 200


@pytest.mark.security
@pytest.mark.invariant("SEC-182")
def test_exemption_counts_only_active_author_tier_users():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    c = TestClient(create_app(k, platform={}))

    # A sole MEMBER is not an author: no exemption.
    _seat(k, "member-only", "member")
    req = _request(k, "member-only")
    assert _approve(c, req.id, "member-only").status_code == 403

    # A DEACTIVATED author does not count against the exemption: will is
    # effectively the sole active author and may self-approve.
    _seat(k, "will", "superadmin")
    _seat(k, "ghost", "admin", status="deactivated")
    req2 = _request(k, "will")
    assert _approve(c, req2.id, "will").status_code == 200


@pytest.mark.security
@pytest.mark.invariant("SEC-182")
def test_exemption_never_lifts_the_live_grant_requirement():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    _seat(k, "will", "superadmin")
    req = _request(k, "will")
    c = TestClient(create_app(k, platform={}))

    # Sole author, but without the gated verb's grant: still fail-closed.
    assert _approve(c, req.id, "will", grants="ticket.read").status_code == 403
    assert asyncio.run(k.hitl.get(TENANT, req.id)).status == HITLStatus.PENDING
