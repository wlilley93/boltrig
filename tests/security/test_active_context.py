"""Session active-workspace context + switching invariants ([2026] VJS-COUNTY 8,
D4): FR-ORG-03, SEC-106, SEC-107.

The active WORKSPACE lives on the session and is RE-AUTHORIZED against membership
every request, never trusted from the client:

  - FR-ORG-03: login seeds a deterministic default active workspace from
    membership (or None), and the session resolver surfaces it onto the principal
    so principal.context().workspace_id carries it (the plumbing half of D11).
  - SEC-106: POST /v1/me/active-context is membership-re-authorized + fail-closed -
    an unknown workspace is 404, a non-member workspace is 403, both with NO write;
    a valid member switch persists.
  - SEC-107: a revoked-membership session drops to no active workspace - the
    resolver re-authorizes every request, so once membership is revoked the
    resolved active workspace becomes None (never the stale value).

These exercise the REAL session resolver: SEC-106 through the HTTP surface, and the
context-carrying / re-auth paths by driving build_session_resolver directly (with a
seeded session) so the principal + InvocationContext are observed exactly as the
kernel receives them.
"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import (
    build_session_resolver,
    hash_password,
    new_session,
    pick_default_workspace,
)
from boltrig.identity.sessions import SESSION_COOKIE
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    User,
    Workspace,
    WorkspaceMember,
    utcnow,
)
from boltrig.store import InMemoryStore

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


async def _make_workspace(store, ws_id: str, *, member: str | None = OWNER):
    await store.create_workspace(
        Workspace(id=ws_id, tenant_id=T, name=ws_id, slug=ws_id)
    )
    if member is not None:
        await store.add_workspace_member(
            WorkspaceMember(user_id=member, workspace_id=ws_id, tenant_id=T, role="member")
        )


def _login(client):
    return client.post("/v1/auth/login", json={"email": OWNER, "password": OWNER_PW})


def _set_cookies_insecure(monkeypatch):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")


class _FakeRequest:
    """A minimal Request the session resolver can read (cookie + app + method +
    headers) and stash the live session onto. Lets a test observe the Principal +
    InvocationContext the resolver builds without an HTTP round-trip."""

    def __init__(self, app, secret: str, *, method: str = "GET"):
        self.app = app
        self.cookies = {SESSION_COOKIE: secret}
        self.method = method
        self.headers = {}
        self.state = SimpleNamespace()


# --- FR-ORG-03: pick_default_workspace is deterministic / None ----------------
@pytest.mark.security
@pytest.mark.invariant("FR-ORG-03")
def test_pick_default_workspace_is_deterministic_or_none():
    # No memberships -> no default.
    assert pick_default_workspace([]) is None

    now = utcnow()
    older = Workspace(id="w-z", tenant_id=T, name="z", slug="z",
                      created_at=now - timedelta(hours=1))
    newer = Workspace(id="w-a", tenant_id=T, name="a", slug="a", created_at=now)
    # Ordered by (created_at, id): the OLDER workspace wins regardless of input order.
    assert pick_default_workspace([newer, older]) == "w-z"
    assert pick_default_workspace([older, newer]) == "w-z"

    # Same created_at -> deterministic id tie-break (lexicographically smallest).
    a = Workspace(id="w-a", tenant_id=T, name="a", slug="a", created_at=now)
    b = Workspace(id="w-b", tenant_id=T, name="b", slug="b", created_at=now)
    assert pick_default_workspace([b, a]) == "w-a"
    assert pick_default_workspace([a, b]) == "w-a"


# --- FR-ORG-03: login seeds a default + the context carries the workspace ------
@pytest.mark.security
@pytest.mark.invariant("FR-ORG-03")
def test_login_seeds_deterministic_default_and_context_carries_workspace(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    # The owner is a member of ONE workspace; login must seed it as the default.
    _run(_make_workspace(store, "ws-1"))

    c = TestClient(app)
    assert _login(c).status_code == 200
    sessions = _run(store.list_sessions(T, OWNER))
    assert len(sessions) == 1
    assert sessions[0].active_workspace_id == "ws-1"

    # The resolver surfaces the active workspace onto the principal, and every
    # InvocationContext the principal builds carries it (the D11 plumbing).
    session, secret, _csrf = new_session(T, OWNER, client="web")
    session.active_workspace_id = "ws-1"
    _run(store.add_session(session))
    resolver = build_session_resolver(T)
    principal = _run(resolver(_FakeRequest(app, secret)))
    assert principal.active_workspace_id == "ws-1"
    assert principal.context().workspace_id == "ws-1"
    # A user who is a member of no workspace yet gets None (not an orphan default).
    assert pick_default_workspace(_run(store.list_workspaces_for_user(T, "nobody"))) is None


# --- SEC-106: switching is membership-re-authorized + fail-closed --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-106")
def test_switch_is_membership_reauthorized_and_fail_closed(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    # ws-mine: the owner is a member. ws-theirs: EXISTS but the owner is NOT a member.
    _run(_make_workspace(store, "ws-mine"))
    _run(_make_workspace(store, "ws-theirs", member=None))

    c = TestClient(app)
    csrf = _login(c).json()["csrf_token"]
    hdr = {"x-boltrig-csrf": csrf}

    def _active():
        return _run(store.list_sessions(T, OWNER))[0].active_workspace_id

    baseline = _active()  # the login-seeded default (ws-mine)

    # Unknown workspace -> 404, NO write.
    r404 = c.post("/v1/me/active-context", json={"workspace_id": "ws-nope"}, headers=hdr)
    assert r404.status_code == 404
    assert _active() == baseline

    # Exists but the caller is NOT a member -> 403, NO write. A client can never set
    # an active workspace it is not a member of.
    r403 = c.post("/v1/me/active-context", json={"workspace_id": "ws-theirs"}, headers=hdr)
    assert r403.status_code == 403
    assert _active() == baseline

    # Missing workspace_id -> 400, NO write.
    r400 = c.post("/v1/me/active-context", json={}, headers=hdr)
    assert r400.status_code == 400
    assert _active() == baseline

    # A member switch persists the new active workspace on the session.
    ok = c.post("/v1/me/active-context", json={"workspace_id": "ws-mine"}, headers=hdr)
    assert ok.status_code == 200
    assert ok.json()["workspace_id"] == "ws-mine"
    assert _active() == "ws-mine"

    # Keys-only audit records the switch (the workspace id, nothing sensitive).
    events = _run(store.audit_query(T, limit=1000))
    switch = [e for e in events if e.verb == "session.active_context.switch"]
    assert switch and switch[-1].detail.get("workspace_id") == "ws-mine"


# --- SEC-107: a revoked-membership session drops to no active workspace --------
@pytest.mark.security
@pytest.mark.invariant("SEC-107")
def test_revoked_membership_session_drops_to_no_active_workspace(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    _run(_make_workspace(store, "ws-1"))

    # A live session with ws-1 as its active workspace resolves to ws-1 while the
    # membership stands.
    session, secret, _csrf = new_session(T, OWNER, client="web")
    session.active_workspace_id = "ws-1"
    _run(store.add_session(session))
    resolver = build_session_resolver(T)
    before = _run(resolver(_FakeRequest(app, secret)))
    assert before.active_workspace_id == "ws-1"
    assert before.context().workspace_id == "ws-1"

    # Revoke the membership. The SAME session (its stored active_workspace_id is
    # still ws-1) must now resolve to NO active workspace - the re-auth runs every
    # request, so the stale value is never trusted.
    _run(store.remove_workspace_member(T, "ws-1", OWNER))
    after = _run(resolver(_FakeRequest(app, secret)))
    assert after.active_workspace_id is None
    assert after.context().workspace_id is None
