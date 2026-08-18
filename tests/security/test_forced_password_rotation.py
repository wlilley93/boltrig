"""A provisioning credential cannot stay the live prod gate.

[2026] VJS-COUNTY 8 D7 ordered the founding superadmin seeded into a default org
plus workspace AND "a password rotation forced before prod exposure, so a weak
seed admin is never the live prod gate". The first half shipped. The second was
never built, and nothing noticed for months - it surfaced only when the
order-binding gate tried to bind D7 and could not.

The hazard is not weakness. `boltrig initiate` already refuses a weak password
through validate_password_strength. It is that the credential typed at
PROVISIONING time survives as the live credential: it has been in a shell
history, usually in a runbook, and often in more than one person's hands.
Strength does not touch any of that.

So the flag is set by `initiate` and by nothing else, the resolver clamps a
flagged account to the change-password surface on EVERY request, and rotating -
by the operator CLI or by the account itself - discharges it.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions, User
from boltrig.store import InMemoryStore

pytestmark = pytest.mark.security

T = "default"
SEEDED = "founder@example.io"
SEED_PW = "provisioning-password-123"
NEW_PW = "a-properly-rotated-password-456"


def _run(coro):
    return asyncio.run(coro)


def _app():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    app = create_app(k, principal_resolver=build_session_resolver(T), platform={})
    return k, app, store


async def _seat(store, *, must_change: bool) -> None:
    await store.upsert_user(User(
        id=SEEDED, tenant_id=T, email=SEEDED, role="superadmin",
        scope={"all": True}, status="active", source="initiate",
        must_change_password=must_change,
    ))
    await store.set_password_credential(T, SEEDED, hash_password(SEED_PW))


def _logged_in(monkeypatch, *, must_change: bool):
    monkeypatch.setenv("BOLTRIG_SESSION_COOKIE_SECURE", "0")
    k, app, store = _app()
    _run(_seat(store, must_change=must_change))
    client = TestClient(app)
    login = client.post(
        "/v1/auth/login", json={"email": SEEDED, "password": SEED_PW}
    )
    assert login.status_code == 200, login.text
    # Every call below is mutating, so it carries the CSRF token the session issued
    # - the resolver enforces it on this route exactly as on every other one.
    return k, client, store, login.json()["csrf_token"]


# --- [2026] VJS-COUNTY 8 D7: the clamp ------------------------------------------
def test_a_seeded_account_reaches_nothing_but_the_rotation_surface(monkeypatch):
    """The directive's substance. A session issues - the password IS correct - but
    it buys nothing until the provisioning credential is retired."""
    _, client, _, csrf = _logged_in(monkeypatch, must_change=True)

    blocked = client.get("/v1/me/sessions")
    assert blocked.status_code == 403, blocked.text
    assert "password_change_required" in blocked.text


def test_an_ordinary_account_is_completely_unaffected(monkeypatch):
    """The flag defaults FALSE and is set by `initiate` alone, so this is a property
    of the SEEDING flow and not a retroactive policy. Getting this wrong would have
    locked live operators out of two production consoles for a hazard their
    accounts do not have."""
    _, client, _, csrf = _logged_in(monkeypatch, must_change=False)
    assert client.get("/v1/me/sessions").status_code == 200


def test_rotating_lifts_the_clamp_and_the_old_password_stops_working(monkeypatch):
    """The way out, and proof the rotation is real rather than a flag flip."""
    _, client, store, csrf = _logged_in(monkeypatch, must_change=True)

    done = client.post(
        "/v1/auth/change-password",
        headers={"x-boltrig-csrf": csrf},
        json={"current_password": SEED_PW, "new_password": NEW_PW},
    )
    assert done.status_code == 200, done.text
    assert client.get("/v1/me/sessions").status_code == 200

    user = _run(store.get_user(T, SEEDED))
    assert user is not None and user.must_change_password is False

    fresh = TestClient(client.app)
    assert fresh.post(
        "/v1/auth/login", json={"email": SEEDED, "password": SEED_PW}
    ).status_code == 401
    assert fresh.post(
        "/v1/auth/login", json={"email": SEEDED, "password": NEW_PW}
    ).status_code == 200


def test_the_rotation_route_demands_the_current_password(monkeypatch):
    """A session is a bearer of identity, not proof of the credential - and this
    route's whole job is to retire a credential. A stolen session must not be able
    to set a new password and lock the owner out of their own account."""
    _, client, store, csrf = _logged_in(monkeypatch, must_change=True)

    refused = client.post(
        "/v1/auth/change-password",
        headers={"x-boltrig-csrf": csrf},
        json={"current_password": "not-the-password", "new_password": NEW_PW},
    )
    assert refused.status_code == 401, refused.text
    user = _run(store.get_user(T, SEEDED))
    assert user is not None and user.must_change_password is True, (
        "a refused rotation cleared the clamp"
    )


def test_the_new_password_must_be_strong_and_must_actually_differ(monkeypatch):
    """Re-setting the SAME password is not a rotation. Accepting it would clear the
    clamp while retiring nothing, which is the only way this whole mechanism can be
    satisfied without doing its job."""
    _, client, store, csrf = _logged_in(monkeypatch, must_change=True)

    weak = client.post(
        "/v1/auth/change-password",
        headers={"x-boltrig-csrf": csrf},
        json={"current_password": SEED_PW, "new_password": "x"},
    )
    assert weak.status_code == 400, weak.text

    same = client.post(
        "/v1/auth/change-password",
        headers={"x-boltrig-csrf": csrf},
        json={"current_password": SEED_PW, "new_password": SEED_PW},
    )
    assert same.status_code == 400, same.text
    assert "differ" in same.text

    user = _run(store.get_user(T, SEEDED))
    assert user is not None and user.must_change_password is True


def test_the_clamp_is_checked_every_request_not_just_at_login(monkeypatch):
    """Same property the 2FA enrollment clamp has: an account flagged while a
    session is already live is clamped on its very next call, not at some future
    login it may never make."""
    _, client, store, csrf = _logged_in(monkeypatch, must_change=False)
    assert client.get("/v1/me/sessions").status_code == 200

    user = _run(store.get_user(T, SEEDED))
    assert user is not None
    _run(store.upsert_user(
        User(
            id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role,
            scope=user.scope, status=user.status, source=user.source,
            created_at=user.created_at, must_change_password=True,
        )
    ))
    after = client.get("/v1/me/sessions")
    assert after.status_code == 403 and "password_change_required" in after.text


def test_initiate_flags_the_account_it_seeds() -> None:
    """The flag has exactly one producer. If `initiate` stopped setting it the whole
    mechanism would be inert while every test above still passed on a hand-built
    user, so this reads the seeding path itself."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "boltrig" / "api" / "initiate.py"
    ).read_text(encoding="utf-8")
    assert "must_change_password=True" in source, (
        "boltrig initiate no longer flags the account it seeds; COUNTY 8 D7's "
        "forced rotation is inert"
    )


def test_rotating_kills_every_other_session_but_keeps_the_callers(monkeypatch):
    """The rotation retires the OLD credential, so sessions minted against it must
    die with it: an attacker's session from a phished password otherwise survived
    the victim's own rotation for the full session lifetime. The reset path
    already revoked everything; this is the authenticated twin, keeping only the
    session that just proved knowledge of the old password."""
    _, client, store, csrf = _logged_in(monkeypatch, must_change=False)

    # A second, independent session for the same identity (the "attacker").
    other = TestClient(client.app)
    assert other.post(
        "/v1/auth/login", json={"email": SEEDED, "password": SEED_PW}
    ).status_code == 200
    assert other.get("/v1/me/sessions").status_code == 200

    done = client.post(
        "/v1/auth/change-password",
        headers={"x-boltrig-csrf": csrf},
        json={"current_password": SEED_PW, "new_password": NEW_PW},
    )
    assert done.status_code == 200, done.text

    # The caller keeps working; the other session is revoked.
    assert client.get("/v1/me/sessions").status_code == 200
    assert other.get("/v1/me/sessions").status_code == 401
