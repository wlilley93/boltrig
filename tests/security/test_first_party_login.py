"""First-party invite-only login invariants ([2026] VJS-COUNTY 7): SEC-97..SEC-101.

Invite-only, no self-signup (SEC-97); passwords hashed argon2id + non-reversible +
never logged (SEC-98); login rate-limited + non-enumerating (SEC-99); the session
cookie is httpOnly + Secure + SameSite + bounded + revocable (SEC-100); the session
resolver is fail-closed and CSRF-protected on mutating cookie requests (SEC-101).

These exercise the real HTTP surface through the session principal resolver so the
gate is tested exactly as it faces the internet.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password, verify_password
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions, User, utcnow
from boltrig.store import InMemoryStore

# The console is single-tenant; _console_tenant() defaults to 'default' with no env.
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


def _login(client, email, password):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def _set_cookies_insecure(monkeypatch):
    # TestClient talks http; a Secure cookie would not be sent back. Drop Secure for
    # the round-trip tests (the Secure flag itself is asserted separately in SEC-100).
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")


# --- SEC-97: invite-only, no open self-signup, single-use tokens --------------
@pytest.mark.security
@pytest.mark.invariant("SEC-97")
def test_invite_only_no_self_signup_and_single_use(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    owner_c = TestClient(app)
    invitee_c = TestClient(app)

    # There is NO open self-signup route.
    assert owner_c.post("/v1/auth/signup", json={"email": "x@y.io", "password": "z" * 12}
                        ).status_code in (404, 405)
    # An account cannot be created without a valid invite token.
    bogus = invitee_c.post("/v1/auth/accept-invite",
                           json={"token": "boltrig_invite_bogus", "password": "n" * 12})
    assert bogus.status_code == 400

    # The owner logs in and mints an invitation (the only way an account is made).
    lo = _login(owner_c, OWNER, OWNER_PW)
    assert lo.status_code == 200
    csrf = lo.json()["csrf_token"]
    inv = owner_c.post("/v1/admin/invitations",
                       json={"email": "newbie@example.io", "role": "member"},
                       headers={"x-boltrig-csrf": csrf})
    assert inv.status_code == 200
    token = inv.json()["invite_token"]
    assert token and token.startswith("boltrig_invite_")

    # The invitee accepts (single-use) and can then log in.
    ac = invitee_c.post("/v1/auth/accept-invite",
                        json={"token": token, "password": "newbie-password-123"})
    assert ac.status_code == 200
    assert _login(invitee_c, "newbie@example.io", "newbie-password-123").status_code == 200

    # The SAME token cannot be reused (single-use consume).
    replay = invitee_c.post("/v1/auth/accept-invite",
                            json={"token": token, "password": "different-password-1"})
    assert replay.status_code == 400


# --- SEC-98: passwords hashed argon2id, non-reversible, never logged ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-98")
def test_password_is_hashed_non_reversible_and_never_logged(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    owner_c = TestClient(app)
    csrf = _login(owner_c, OWNER, OWNER_PW).json()["csrf_token"]
    token = owner_c.post("/v1/admin/invitations",
                         json={"email": "u@example.io", "role": "member"},
                         headers={"x-boltrig-csrf": csrf}).json()["invite_token"]
    secret = "s3cret-user-password-xyz"
    TestClient(app).post("/v1/auth/accept-invite",
                         json={"token": token, "password": secret})

    stored = _run(store.get_password_credential(T, "u@example.io"))
    # Stored form is an argon2id PHC string, not the plaintext, and is one-way.
    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert secret not in stored
    assert verify_password(stored, secret) is True
    assert verify_password(stored, "wrong-password") is False

    # The plaintext never appears in the User identity row nor the audit chain.
    user = _run(store.get_user(T, "u@example.io"))
    assert secret not in json.dumps(user.__dict__, default=str)
    events = _run(store.audit_query(T, limit=1000))
    blob = json.dumps([e.detail for e in events], default=str)
    assert secret not in blob


# --- SEC-99: login rate-limited + non-enumerating -----------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-99")
def test_login_is_rate_limited_and_non_enumerating(monkeypatch):
    _set_cookies_insecure(monkeypatch)

    # Non-enumeration: an unknown email and a known-but-wrong password return the
    # byte-identical body and status - no oracle for which emails exist.
    _, app_a, store_a = _app()
    _run(_seat_owner(store_a))
    ca = TestClient(app_a)
    unknown = _login(ca, "nobody@example.io", "whatever-123456")
    wrong = _login(ca, OWNER, "wrong-password-123")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()

    # Rate limit: the per-identity bound (5/min) trips on the 6th attempt with 429.
    _, app_b, store_b = _app()
    _run(_seat_owner(store_b))
    cb = TestClient(app_b)
    codes = [_login(cb, OWNER, "bad-password-000").status_code for _ in range(6)]
    assert codes[:5] == [401, 401, 401, 401, 401]
    assert codes[5] == 429


# --- SEC-100: session cookie httpOnly + Secure + SameSite + bounded + revocable
@pytest.mark.security
@pytest.mark.invariant("SEC-100")
def test_session_cookie_is_httponly_secure_bounded_and_revocable(monkeypatch):
    # Assert the cookie flags with Secure ON (the production default).
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "1")
    _, app, store = _app()
    _run(_seat_owner(store))
    resp = _login(TestClient(app), OWNER, OWNER_PW)
    set_cookies = [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]
    session_cookie = next(c for c in set_cookies if c.startswith("boltrig_session="))
    low = session_cookie.lower()
    assert "httponly" in low
    assert "secure" in low
    assert "samesite=strict" in low
    assert "max-age=" in low  # bounded lifetime

    # The stored session is bounded (expires_at in the future) and revocable.
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    _, app2, store2 = _app()
    _run(_seat_owner(store2))
    c = TestClient(app2)
    assert _login(c, OWNER, OWNER_PW).status_code == 200
    sessions = _run(store2.list_sessions(T, OWNER))
    assert len(sessions) == 1 and sessions[0].expires_at is not None
    assert sessions[0].expires_at > utcnow()
    # Authenticated before logout, denied after (the session is revoked in-store).
    assert c.get("/v1/me/sessions").status_code == 200
    csrf = _login(c, OWNER, OWNER_PW).json()["csrf_token"]
    assert c.post("/v1/auth/logout", headers={"x-boltrig-csrf": csrf}).status_code == 200
    assert c.get("/v1/me/sessions").status_code == 401


# --- SEC-101: resolver fail-closed + CSRF on mutating cookie requests ----------
@pytest.mark.security
@pytest.mark.invariant("SEC-101")
def test_resolver_fail_closed_and_csrf_protected(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    _, app, store = _app()
    _run(_seat_owner(store))

    # Fail-closed: no session cookie -> 401 on an authenticated route.
    assert TestClient(app).get("/v1/me/sessions").status_code == 401

    c = TestClient(app)
    csrf = _login(c, OWNER, OWNER_PW).json()["csrf_token"]
    # A GET is exempt from CSRF; a mutating POST without the header is refused 403.
    assert c.get("/v1/me/sessions").status_code == 200
    no_csrf = c.post("/v1/admin/invitations", json={"email": "a@b.io", "role": "member"})
    assert no_csrf.status_code == 403
    with_csrf = c.post("/v1/admin/invitations", json={"email": "a@b.io", "role": "member"},
                       headers={"x-boltrig-csrf": csrf})
    assert with_csrf.status_code == 200

    # Fail-closed on deactivation: the live session stops resolving at once.
    c2 = TestClient(app)
    _login(c2, OWNER, OWNER_PW)
    assert c2.get("/v1/me/sessions").status_code == 200
    owner = _run(store.get_user(T, OWNER))
    owner.status = "deactivated"
    _run(store.upsert_user(owner))
    assert c2.get("/v1/me/sessions").status_code == 401


# --- D7: `boltrig initiate` seats one owner and refuses to run twice ----------
@pytest.mark.security
def test_initiate_is_idempotent_and_refuses_twice(monkeypatch):
    from boltrig.api import initiate as initiate_mod

    shared = InMemoryStore()

    async def _fake_store():
        return shared

    monkeypatch.setattr(initiate_mod, "build_store", _fake_store, raising=False)
    # build_store is imported inside _run; patch the source too.
    monkeypatch.setattr("boltrig.api.bootstrap.build_store", _fake_store, raising=False)

    rc1 = _run(initiate_mod._run("founder@example.io", "founder-password-123", T))
    assert rc1 == 0
    seated = _run(shared.get_user(T, "founder@example.io"))
    assert seated is not None and seated.role == "superadmin"
    # A second run against the same store refuses (an owner already exists).
    rc2 = _run(initiate_mod._run("founder@example.io", "founder-password-123", T))
    assert rc2 != 0
    rc3 = _run(initiate_mod._run("someone-else@example.io", "another-password-123", T))
    assert rc3 != 0
