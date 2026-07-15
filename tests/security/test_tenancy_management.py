"""Org/workspace MANAGEMENT routes + invite provisioning ([2026] VJS-COUNTY 8, D6).

FR-ORG-04 : the workspace + org management surface is role-scoped + audited - a
            caller lists their own workspaces, an org-admin/owner creates one (and is
            seated as its owner), a manager renames it + adds/removes members, and the
            org routes expose + update the org's handle and policy flags.
SEC-117   : workspace management is membership/role fail-closed - PATCH a workspace,
            add + remove a member all refuse a caller who is neither an org-admin nor
            an owner/admin of THAT workspace (403, NO write); an unknown workspace is
            404, an out-of-set role 400, an unknown target user 404.
SEC-118   : an org/workspace-scoped invite seats the invitee into exactly that
            workspace on accept with the invited role (bounded by the ceiling);
            provision creates the workspace + seats the invitee as owner; org
            provisioning is superadmin-only, and a workspace-targeted invite requires
            the inviter to manage that workspace.
SEC-119   : org management is org-admin fail-closed - PATCH /v1/orgs/current refuses a
            non-admin (403, NO write) and lets an org-admin rename + toggle
            allow_own_ai_keys / require_two_factor; GET exposes the flags, never a key.

These drive the REAL HTTP surface through the header principal resolver (the same
resolver the kernel uses off-session), plus the public accept-invite gate.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    User,
    Workspace,
    WorkspaceMember,
)
from boltrig.store import InMemoryStore
from tests.approval import approved_request

# The console tenant is 'default' (accept-invite operates within it), so the
# management writes and the accept flow share one tenant.
T = "default"


def _run(coro):
    return asyncio.run(coro)


def _app():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, platform={})
    return k, app, store


def _hdr(role="org-admin", subject="admin"):
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject,
            "x-boltrig-role": role, "x-boltrig-grants": "*"}


def _approved(c, k, method, path, *, headers=None, json=None):
    return approved_request(
        c, k, T, method, path, headers=headers or _hdr(), json=json
    )


async def _seat_user(store, user_id, *, role="member"):
    await store.upsert_user(User(
        id=user_id, tenant_id=T, email=user_id, role=role, scope={}, status="active",
        source="test",
    ))


async def _make_ws(store, ws_id, *, owner=None):
    await store.create_workspace(Workspace(id=ws_id, tenant_id=T, name=ws_id, slug=ws_id))
    if owner is not None:
        await store.add_workspace_member(
            WorkspaceMember(user_id=owner, workspace_id=ws_id, tenant_id=T, role="owner")
        )


# --- FR-ORG-04: the management surface (role-scoped + audited) ----------------
@pytest.mark.security
@pytest.mark.invariant("FR-ORG-04")
def test_workspace_and_org_management_surface():
    k, app, store = _app()
    c = TestClient(app)

    # An org-admin creates a workspace and is seated as its owner.
    r = _approved(c, k, "POST", "/v1/workspaces", json={"name": "Acme Team"})
    assert r.status_code == 200
    ws = r.json()["workspace"]
    assert ws["name"] == "Acme Team" and ws["slug"].startswith("acme-team-")
    # The creator (admin) is now a member and can list it as their own.
    mine = c.get("/v1/workspaces", headers=_hdr()).json()["workspaces"]
    assert [w["id"] for w in mine] == [ws["id"]]

    # Rename + settings via PATCH (the creator manages it as owner).
    p = _approved(
        c, k, "PATCH", f"/v1/workspaces/{ws['id']}",
        json={"name": "Renamed", "status": "archived"},
    )
    assert p.status_code == 200
    assert p.json()["workspace"]["name"] == "Renamed"
    assert p.json()["workspace"]["status"] == "archived"

    # Add an existing org user as a member, then list + remove.
    _run(_seat_user(store, "bob@x.io"))
    add = _approved(
        c, k, "POST", f"/v1/workspaces/{ws['id']}/members",
        json={"user_id": "bob@x.io", "role": "viewer"},
    )
    assert add.status_code == 200 and add.json()["member"]["role"] == "viewer"
    roster = c.get(f"/v1/workspaces/{ws['id']}/members", headers=_hdr()).json()["members"]
    assert {m["user_id"] for m in roster} == {"admin", "bob@x.io"}
    rm = _approved(c, k, "DELETE", f"/v1/workspaces/{ws['id']}/members/bob@x.io")
    assert rm.status_code == 200
    roster2 = c.get(f"/v1/workspaces/{ws['id']}/members", headers=_hdr()).json()["members"]
    assert {m["user_id"] for m in roster2} == {"admin"}

    # Org routes: read the org, then update its handle + flags.
    org = c.get("/v1/orgs/current", headers=_hdr()).json()["organisation"]
    assert org["id"] == T and org["allow_own_ai_keys"] is False
    up = _approved(
        c, k, "PATCH", "/v1/orgs/current",
        json={"name": "Acme Inc", "allow_own_ai_keys": True},
    )
    assert up.status_code == 200
    assert up.json()["organisation"]["name"] == "Acme Inc"
    assert up.json()["organisation"]["allow_own_ai_keys"] is True
    members = c.get("/v1/orgs/current/members", headers=_hdr()).json()["members"]
    assert isinstance(members, list)

    # Every management write is audited keys-only.
    events = _run(store.audit_query(T, limit=1000))
    verbs = {e.verb for e in events}
    assert {"workspace.create", "workspace.update", "workspace.member.add",
            "workspace.member.remove", "org.update"} <= verbs


# --- SEC-117: workspace management is membership/role fail-closed --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-117")
def test_workspace_management_is_membership_role_fail_closed():
    k, app, store = _app()
    c = TestClient(app)
    # ws-a exists; carol is a plain (non-manager) member of it; dave is not a member.
    _run(_make_ws(store, "ws-a", owner="alice@x.io"))
    _run(store.add_workspace_member(
        WorkspaceMember(user_id="carol@x.io", workspace_id="ws-a", tenant_id=T, role="member")
    ))
    _run(_seat_user(store, "target@x.io"))

    member_hdr = _hdr(role="member", subject="carol@x.io")   # a member, not a manager
    stranger_hdr = _hdr(role="member", subject="dave@x.io")   # not a member at all

    def _members():
        return {m.user_id for m in _run(store.list_workspace_members(T, "ws-a"))}

    baseline = _members()

    # A plain member cannot rename the workspace.
    assert c.patch("/v1/workspaces/ws-a", headers=member_hdr,
                   json={"name": "hijack"}).status_code == 403
    assert _run(store.get_workspace(T, "ws-a")).name == "ws-a"  # NO write

    # A plain member cannot add a member (403, NO write).
    assert c.post("/v1/workspaces/ws-a/members", headers=member_hdr,
                  json={"user_id": "target@x.io", "role": "admin"}).status_code == 403
    assert _members() == baseline

    # A non-member is likewise refused, and cannot even read the roster.
    assert c.post("/v1/workspaces/ws-a/members", headers=stranger_hdr,
                  json={"user_id": "target@x.io", "role": "member"}).status_code == 403
    assert c.get("/v1/workspaces/ws-a/members", headers=stranger_hdr).status_code == 403
    assert _members() == baseline

    # An unknown workspace is 404 (not a 403 leak of existence to a manager path).
    assert c.patch("/v1/workspaces/ws-nope", headers=_hdr(),
                   json={"name": "x"}).status_code == 404

    # The workspace owner (via org-admin here) validates the add inputs: an out-of-set
    # role is 400, an unknown target user is 404, both with NO write.
    assert c.post("/v1/workspaces/ws-a/members", headers=_hdr(),
                  json={"user_id": "target@x.io", "role": "superadmin"}).status_code == 400
    assert c.post("/v1/workspaces/ws-a/members", headers=_hdr(),
                  json={"user_id": "ghost@x.io", "role": "member"}).status_code == 404
    assert _members() == baseline

    # ...but the workspace OWNER themselves may manage it (positive control).
    owner_hdr = _hdr(role="member", subject="alice@x.io")
    assert _approved(
        c, k, "POST", "/v1/workspaces/ws-a/members", headers=owner_hdr,
        json={"user_id": "target@x.io", "role": "member"},
    ).status_code == 200
    assert "target@x.io" in _members()


# --- SEC-118: org/workspace-scoped invite seating + provisioning --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-118")
def test_scoped_invite_seats_and_provisions(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    k, app, store = _app()
    c = TestClient(app)
    _run(_make_ws(store, "ws-target", owner="admin"))  # admin (org-admin) manages it

    # 1) A workspace-targeted invite seats the invitee into THAT workspace on accept
    #    with the invited role.
    inv = _approved(
        c, k, "POST", "/v1/admin/invitations",
        json={"email": "seat@x.io", "role": "viewer", "workspace_id": "ws-target"},
    )
    assert inv.status_code == 200
    tok = inv.json()["invite_token"]
    ac = c.post("/v1/auth/accept-invite",
                json={"token": tok, "password": "seat-password-123"})
    assert ac.status_code == 200
    m = _run(store.get_workspace_member(T, "ws-target", "seat@x.io"))
    assert m is not None and m.role == "viewer"  # exactly the invited role

    # 2) A provisioning invite CREATES a workspace on accept and seats the invitee as
    #    its OWNER.
    inv2 = _approved(
        c, k, "POST", "/v1/admin/invitations",
        json={"email": "founder@x.io", "role": "member",
              "provision_workspace_name": "Founder Space"},
    )
    tok2 = inv2.json()["invite_token"]
    assert c.post("/v1/auth/accept-invite",
                  json={"token": tok2, "password": "founder-password-1"}).status_code == 200
    owned = _run(store.list_workspaces_for_user(T, "founder@x.io"))
    assert len(owned) == 1 and owned[0].name == "Founder Space"
    om = _run(store.get_workspace_member(T, owned[0].id, "founder@x.io"))
    assert om.role == "owner"

    # 3) Org provisioning is SUPERADMIN-ONLY: an org-admin is refused 403 with NO
    #    invitation written; a superadmin may set it.
    before = len(_run(store.list_invitations(T)))
    denied = c.post("/v1/admin/invitations", headers=_hdr(role="org-admin"),
                    json={"email": "neworg@x.io", "role": "member",
                          "provision_org_name": "NewCo"})
    assert denied.status_code == 403
    assert len(_run(store.list_invitations(T))) == before  # NO write

    okorg = _approved(
        c, k, "POST", "/v1/admin/invitations", headers=_hdr(role="superadmin"),
        json={"email": "neworg@x.io", "role": "member",
              "provision_org_name": "NewCo"},
    )
    assert okorg.status_code == 200
    tok3 = okorg.json()["invite_token"]
    assert c.post("/v1/auth/accept-invite",
                  json={"token": tok3, "password": "neworg-password-1"}).status_code == 200
    # A brand-new org (a fresh tenant) now exists, owned by the invitee.
    new_orgs = [o for o in _run(store.list_orgs()) if o.name == "NewCo"]
    assert len(new_orgs) == 1
    assert _run(store.list_org_members(new_orgs[0].id))[0].user_id == "neworg@x.io"

    # 4) A workspace-targeted invite is authorised against the workspace BEFORE the
    #    invitation is written: an unknown workspace is refused 404 with NO invitation
    #    left behind, so an invite can never be scoped into a phantom workspace.
    before4 = len(_run(store.list_invitations(T)))
    bad = c.post("/v1/admin/invitations", headers=_hdr(),
                 json={"email": "x@x.io", "role": "member", "workspace_id": "ws-nope"})
    assert bad.status_code == 404
    assert len(_run(store.list_invitations(T))) == before4  # NO write


# --- SEC-119: org management is org-admin fail-closed --------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-119")
def test_org_management_is_admin_fail_closed():
    k, app, store = _app()
    c = TestClient(app)

    # A non-admin cannot mutate the org (403), and nothing is written.
    r = c.patch("/v1/orgs/current", headers=_hdr(role="member", subject="bob@x.io"),
                json={"allow_own_ai_keys": True, "name": "hijack"})
    assert r.status_code == 403
    org = c.get("/v1/orgs/current", headers=_hdr()).json()["organisation"]
    assert org["allow_own_ai_keys"] is False and org["name"] != "hijack"

    # An org-admin may rename + toggle both policy flags.
    up = _approved(
        c, k, "PATCH", "/v1/orgs/current",
        json={"name": "Acme", "allow_own_ai_keys": True,
              "require_two_factor": True},
    )
    assert up.status_code == 200
    body = up.json()["organisation"]
    assert body["allow_own_ai_keys"] is True and body["require_two_factor"] is True
    assert body["name"] == "Acme"

    # The GET view exposes the flags + handle but carries no secret material.
    got = c.get("/v1/orgs/current", headers=_hdr(role="member", subject="bob@x.io")).json()
    assert set(got["organisation"]) >= {"id", "name", "slug", "settings",
                                        "allow_own_ai_keys", "require_two_factor"}
    assert "credential" not in repr(got).lower() and "secret" not in repr(got).lower()
