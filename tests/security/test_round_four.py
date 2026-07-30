"""Round Four security/governance invariants: SEC-34..39.

Personal access tokens never escalate and die with the user (SEC-34); invitations
do not bypass the IdP (SEC-35); settings writes are RBAC-checked server-side and
audited (SEC-36); headless REST/MCP runs the same chokepoint scoped to the user
(SEC-37); there is no relaxed unauthenticated path for tokens/connections
(SEC-38); authored verbs are safe-by-default high-consequence (SEC-39).
"""

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.identity.auth import build_principal_resolver
from boltrig.identity.provisioning import provision_user
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    Noun,
    RoleMapping,
    TenantPermissions,
    UserInvitation,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _client(k: Kernel) -> TestClient:
    return TestClient(create_app(k, platform={}))


def _hdr(role="org-admin", grants="*", subject="alice", departments=""):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject, "x-boltrig-role": role,
            "x-boltrig-grants": grants, "x-boltrig-departments": departments}


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}", "x-boltrig-tenant": T}


# --- SEC-34: a personal access token never escalates and dies with the user ---
@pytest.mark.security
@pytest.mark.invariant("SEC-34")
def test_pat_never_escalates_and_dies_with_user():
    k = asyncio.run(_kernel())
    c = _client(k)
    # a read-only user mints a PAT asking for MORE than they hold: it is capped.
    readonly = _hdr(role="agent", grants="ticket.read", subject="alice")
    over = c.post("/v1/me/tokens", json={"name": "x", "scope": ["ticket.create"]}, headers=readonly)
    assert over.status_code == 200
    assert over.json()["scope"] == []  # ticket.create not permitted -> dropped at mint

    minted = c.post("/v1/me/tokens", json={"name": "cc", "scope": ["ticket.read"]}, headers=readonly)
    secret = minted.json()["secret"]
    # the PAT sees only ticket.read, never ticket.create (capped to the user, SEC-34)
    caps = c.get("/v1/capabilities", headers=_bearer(secret)).json()
    verbs = {v["id"] for v in caps["verbs"]}
    assert "ticket.read" in verbs and "ticket.create" not in verbs
    # the secret is shown once and never leaks back in the listing (PAT-02)
    listed = c.get("/v1/me/tokens", headers=readonly).json()["tokens"]
    assert listed and all("secret" not in t for t in listed)

    # Deactivation is a governed, high-consequence control mutation. Once a
    # different human approves and the caller reapplies it, the PAT dies at once.
    held = c.patch(
        "/v1/admin/users/alice", json={"status": "deactivated"}, headers=_hdr()
    )
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    asyncio.run(k.hitl.answer(T, request_id, "approve", "security-admin"))
    applied = c.patch(
        "/v1/admin/users/alice",
        json={"status": "deactivated", "approval_id": request_id},
        headers=_hdr(),
    )
    assert applied.status_code == 200
    assert c.get("/v1/capabilities", headers=_bearer(secret)).status_code == 401


# --- SEC-35: invitations do not bypass the IdP -------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-35")
def test_invitations_do_not_bypass_idp():
    store = InMemoryStore()
    mappings = [RoleMapping(T, "eng-grp", "engineer", {"departments": ["engineering"]})]

    async def scenario():
        # an unmapped, un-invited identity is denied (fail-closed, US-USR-01)
        denied = await provision_user(store, tenant_id=T, subject="u1",
                                      email="u1@acme", groups=[], mappings=mappings)
        assert denied is None
        assert await store.get_user(T, "u1") is None

        # an invitation alone grants no access until the invitee authenticates
        # (a LIVE invitation - provisioning correctly refuses an expired one)
        await store.add_invitation(UserInvitation(
            id="i1", tenant_id=T, email="u2@acme", intended_role="agent",
            intended_scope={"verbs": ["ticket.read"]}, invited_by="admin",
            expires_at=utcnow() + timedelta(days=7)))
        # (still no user row before they log in)
        assert await store.get_user(T, "u2") is None

        # on first SSO login the invited identity is provisioned with that role/scope
        invited = await provision_user(store, tenant_id=T, subject="u2",
                                       email="u2@acme", groups=[], mappings=mappings)
        assert invited is not None and invited.role == "agent" and invited.source == "invitation"
        inv = await store.get_invitation(T, "i1")
        assert inv.status == "accepted"  # consumed, not reusable

        # a mapped identity is provisioned from its group, with the source recorded
        mapped = await provision_user(store, tenant_id=T, subject="u3",
                                      email="u3@acme", groups=["eng-grp"], mappings=mappings)
        assert mapped.role == "engineer" and mapped.source_group == "eng-grp"

    asyncio.run(scenario())


# --- SEC-36: settings changes are authorization-checked and audited ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-36")
def test_settings_changes_are_authz_checked_and_audited():
    k = asyncio.run(_kernel())
    c = _client(k)
    # a user's own setting write persists and is audited with the actor
    assert c.put("/v1/me/settings", json={"key": "theme", "value": "dark"},
                 headers=_hdr(role="agent", grants="", subject="alice")).status_code == 200
    events = asyncio.run(k.store.audit_query(T))
    assert any(e.verb == "settings.update" and e.actor == "alice" for e in events)
    # a non-admin cannot touch the org directory (RBAC enforced server-side)
    denied = c.patch("/v1/admin/users/alice", json={"role": "org-admin"},
                     headers=_hdr(role="agent", grants="", subject="mallory"))
    assert denied.status_code == 403


# --- SEC-37: headless parity - no weak REST/MCP path -------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-37")
def test_headless_parity_no_weak_path():
    k = asyncio.run(_kernel())
    c = _client(k)
    readonly = _hdr(role="agent", grants="ticket.read", subject="alice")
    secret = c.post("/v1/me/tokens", json={"name": "cc", "scope": ["ticket.read"]},
                    headers=readonly).json()["secret"]

    # user-authenticated MCP advertises only the user's permitted tools (US-HEAD-02)
    listed = c.post("/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers=_bearer(secret))
    tools = {t["name"] for t in listed.json()["result"]["tools"]}
    assert "ticket.read" in tools and "ticket.create" not in tools

    # the headless REST path runs the SAME chokepoint: with valid params (so the
    # grant check, not schema validation, is what bites) an out-of-scope verb is
    # denied exactly as on the site (identical grant enforcement, no weak path).
    invoke = c.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.create", "params": {"title": "x"}},
        headers=_bearer(secret),
    )
    assert invoke.status_code == 403


# --- SEC-38: no unauthenticated access to tokens / connections ---------------
@pytest.mark.security
@pytest.mark.invariant("SEC-38")
def test_no_unauthenticated_access_to_tokens():
    class _StubVerifier:
        async def verify(self, token):
            return {"sub": "u", "groups": []}

    k = asyncio.run(_kernel())
    resolver = build_principal_resolver(verifier=_StubVerifier(), mappings=[], tenant_id=T)
    c = TestClient(create_app(k, principal_resolver=resolver, platform={}))
    # no bearer -> 401; tokens and connection details are never exposed unauthenticated
    assert c.get("/v1/me/tokens").status_code == 401
    assert c.get("/v1/me/connections").status_code == 401


# --- SEC-39: authored verbs are safe-by-default high-consequence --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-39")
def test_authored_verbs_safe_by_default():
    k = asyncio.run(_kernel())
    asyncio.run(
        k.store.upsert_noun(
            Noun(id="widget", tenant_id=T, description="Authored verb fixture")
        )
    )
    c = _client(k)

    def author(body: dict) -> dict:
        held = c.post("/v1/verbs", json=body, headers=_hdr())
        assert held.status_code == 202
        request_id = held.json()["hitl_request_id"]
        asyncio.run(k.hitl.answer(T, request_id, "approve", "security-admin"))
        applied = c.post(
            "/v1/verbs",
            json={**body, "approval_id": request_id},
            headers=_hdr(),
        )
        assert applied.status_code == 200
        return applied.json()

    # a destructive verb authored with no explicit consequence defaults to high,
    # so the HITL gate engages (US-RTR-02/04).
    dele = author({"id": "widget.delete", "noun_id": "widget"})
    assert dele["consequence"] == "high"
    stored = asyncio.run(k.store.get_verb(T, "widget.delete"))
    assert stored.consequence.value == "high"
    # a read verb stays low; an explicit choice is still honoured
    fetch = author({"id": "widget.fetch", "noun_id": "widget"})
    assert fetch["consequence"] == "low"
    forced = author(
        {"id": "widget.purge", "noun_id": "widget", "consequence": "low"}
    )
    assert forced["consequence"] == "low"
