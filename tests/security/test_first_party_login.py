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
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password, verify_password
from boltrig.identity.invites import hash_invite_token
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    User,
    UserInvitation,
    utcnow,
)
from boltrig.store import InMemoryStore
from tests.approval import approved_request

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


# --- SEC-97 / [2026] VJS-COUNTY 7 D1: invite-only, no self-signup, single-use -------
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
    inv = approved_request(
        owner_c, k, T, "POST", "/v1/admin/invitations",
        json={"email": "newbie@example.io", "role": "member"},
        headers={"x-boltrig-csrf": csrf},
    )
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


@pytest.mark.security
@pytest.mark.invariant("SEC-97")
async def test_concurrent_invite_redemption_cannot_apply_the_rejected_password(
    monkeypatch,
):
    """The single-use claim linearises acceptance before any account write.

    Delaying the legacy id-based consume makes this test deterministically expose
    the old ordering: both requests wrote their password, then the first CAS
    winner returned 200 while the rejected request's password remained stored.
    The current route never reaches that late consume seam; only the exact token
    claimant can write.
    """
    monkeypatch.delenv("BOLTRIG_SESSION_TENANT", raising=False)
    _, app, store = _app()
    token = "boltrig_invite_concurrent-redemption"
    email = "concurrent@example.io"
    await store.add_invitation(
        UserInvitation(
            id="concurrent-invite",
            tenant_id=T,
            email=email,
            intended_role="member",
            intended_scope={},
            invited_by=OWNER,
            expires_at=utcnow() + timedelta(hours=1),
            token_hash=hash_invite_token(token),
        )
    )

    original_consume = store.consume_invitation
    both_at_legacy_consume = asyncio.Event()
    first_finished = asyncio.Event()
    arrivals = 0

    async def delayed_legacy_consume(tenant_id, invitation_id):
        nonlocal arrivals
        order = arrivals
        arrivals += 1
        if order == 1:
            both_at_legacy_consume.set()
        await asyncio.wait_for(both_at_legacy_consume.wait(), timeout=5)
        if order == 0:
            won = await original_consume(tenant_id, invitation_id)
            first_finished.set()
            return won
        await asyncio.wait_for(first_finished.wait(), timeout=5)
        return await original_consume(tenant_id, invitation_id)

    # This hook is intentionally unused by the fixed route. It makes the same
    # regression fail deterministically if the old mutate-then-consume ordering
    # is restored.
    store.consume_invitation = delayed_legacy_consume
    passwords = ("first-winner-password-123", "second-loser-password-456")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/v1/auth/accept-invite",
                    json={"token": token, "password": password},
                )
                for password in passwords
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 400]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    rejected = 1 - winner
    credential = await store.get_password_credential(T, email)
    assert credential is not None
    assert verify_password(credential, passwords[winner])
    assert not verify_password(credential, passwords[rejected])
    assert arrivals == 0


# --- SEC-98 / [2026] VJS-COUNTY 7 D4: argon2id, non-reversible, never logged --------
@pytest.mark.security
@pytest.mark.invariant("SEC-98")
def test_password_is_hashed_non_reversible_and_never_logged(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))
    owner_c = TestClient(app)
    csrf = _login(owner_c, OWNER, OWNER_PW).json()["csrf_token"]
    token = approved_request(
        owner_c, k, T, "POST", "/v1/admin/invitations",
        json={"email": "u@example.io", "role": "member"},
        headers={"x-boltrig-csrf": csrf},
    ).json()["invite_token"]
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


# --- SEC-99 / [2026] VJS-COUNTY 7 D5: rate-limited, constant-time, non-enumerating --
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
    #
    # The limiter uses a FIXED wall-clock window (int(time.time() // 60)), not a
    # sliding one, so six attempts that straddle a minute boundary land in two
    # buckets, the count resets, and the sixth returns 401. Each attempt does a
    # deliberately slow password hash, so on a loaded box that straddle is not
    # rare: this test failed exactly that way in a 113s suite run. Pinning the
    # clock removes the race without weakening the assertion, which is about the
    # limiter's behaviour WITHIN a window, not about wall time.
    monkeypatch.setattr("boltrig.kernel.ratelimit.time.time", lambda: 1_700_000_000.0)
    _, app_b, store_b = _app()
    _run(_seat_owner(store_b))
    cb = TestClient(app_b)
    codes = [_login(cb, OWNER, "bad-password-000").status_code for _ in range(6)]
    assert codes[:5] == [401, 401, 401, 401, 401]
    assert codes[5] == 429


# --- SEC-100 / [2026] VJS-COUNTY 7 D2+D6: session cookie httpOnly/Secure/SameSite,
#     bounded, revocable - D2's logout revocation and D6's cookie posture, one surface
@pytest.mark.security
@pytest.mark.invariant("SEC-100")
def test_session_cookie_is_httponly_secure_bounded_and_revocable(monkeypatch):
    # Assert the cookie flags with Secure ON (the production default).
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "1")
    k, app, store = _app()
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


# --- SEC-101 / [2026] VJS-COUNTY 7 D3+D8: resolver fail-closed, CSRF on mutating
#     cookie requests - the session resolver that replaced the CF Access one, and
#     the one chokepoint every auth action routes through
@pytest.mark.security
@pytest.mark.invariant("SEC-101")
def test_resolver_fail_closed_and_csrf_protected(monkeypatch):
    _set_cookies_insecure(monkeypatch)
    k, app, store = _app()
    _run(_seat_owner(store))

    # Fail-closed: no session cookie -> 401 on an authenticated route.
    assert TestClient(app).get("/v1/me/sessions").status_code == 401

    c = TestClient(app)
    csrf = _login(c, OWNER, OWNER_PW).json()["csrf_token"]
    # A GET is exempt from CSRF; a mutating POST without the header is refused 403.
    assert c.get("/v1/me/sessions").status_code == 200
    no_csrf = c.post("/v1/admin/invitations", json={"email": "a@b.io", "role": "member"})
    assert no_csrf.status_code == 403
    with_csrf = approved_request(
        c, k, T, "POST", "/v1/admin/invitations",
        json={"email": "a@b.io", "role": "member"},
        headers={"x-boltrig-csrf": csrf},
    )
    assert with_csrf.status_code == 200

    # Fail-closed on deactivation: the live session stops resolving at once.
    c2 = TestClient(app)
    _login(c2, OWNER, OWNER_PW)
    assert c2.get("/v1/me/sessions").status_code == 200
    owner = _run(store.get_user(T, OWNER))
    owner.status = "deactivated"
    _run(store.upsert_user(owner))
    assert c2.get("/v1/me/sessions").status_code == 401


# --- [2026] VJS-COUNTY 7 D7: `boltrig initiate` seats the founding OWNER and the
#     whole flow stays invite-only - it refuses to run twice, no open self-signup --
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


# --- [2026] VJS-COUNTY 7 D9: the directive that is about the RECORD ----------------
@pytest.mark.security
def test_every_first_party_auth_invariant_is_declared_in_the_catalogue():
    """D9 orders the five behaviours PINNED as invariants with debt staying zero.

    The invariant gate proves every DECLARED invariant is bound; nothing proved
    these five were declared at all. Deleting a declaration takes its enforcement
    with it and leaves every other check green - which is exactly how the
    catalogue once ate a whole invariant to a duplicate id and stayed passing.
    """
    import pathlib

    catalogue = (
        pathlib.Path(__file__).resolve().parents[2] / "tests" / "invariants.yaml"
    ).read_text(encoding="utf-8")
    missing = [
        inv
        for inv in ("SEC-97", "SEC-98", "SEC-99", "SEC-100", "SEC-101")
        if f"\n  {inv}:" not in catalogue
    ]
    assert not missing, f"first-party auth invariants absent from the catalogue: {missing}"
