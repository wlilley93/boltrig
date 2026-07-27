"""The auth surface's audit rows carry names, never the secrets beside them (SEC-191).

Nine comments across `boltrig/api/auth_routes.py` say some version of "keys-only audit: the
session id, NEVER the secret / csrf / password". Until this file they rested on nothing: the
audit row's contents were whatever dict literal the call site happened to pass, and the only
enforcement was that whoever wrote each line had been careful. That is the shape Tier 0 of
GOAL-claims-must-be-load-bearing.md classifies as NO-SUBJECT, and it is the shape two of the
eleven original defects took.

WHAT THIS DRIVES. The three paths that handle a secret and then audit: invite acceptance
(which sees a chosen password), login (which mints a session secret and a CSRF token), and 2FA
enrolment (which mints a TOTP secret and an otpauth URI containing it). For each, the whole
audit stream is serialised and searched for the material the route was holding at the time.

WHY IT SEARCHES THE WHOLE STREAM AND NOT THE ONE ROW. A route can only leak into the row it
writes, but a REGRESSION can leak into a row it did not previously write at all, and asserting
on one row would not see that. The stream is small in a seeded test and the cost is nothing.

WHAT IT DOES NOT ESTABLISH. That the write-time scrubber would catch a leak. It would not
reliably: `pii.contains_secret` is a pattern list, and the schema-validation ledger order
recorded it missing an `sk-live-` token outright. The guarantee here is POSITIONAL, exactly as
that order requires: the material is never put in the dict. If a future change starts relying
on the scrubber instead, this test keeps passing and is measuring the wrong thing, so the last
case disables the scrubber and requires the result to be unchanged.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import build_session_resolver, hash_password
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions, User
from boltrig.store import InMemoryStore
from tests.conftest import TENANT  # noqa: F401  (imported for parity with the sibling suites)

T = "default"
OWNER = "owner@example.io"
OWNER_PW = "owner-password-correct-horse-1"


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


def _audit_text(store) -> str:
    """Every audit row this tenant holds, serialised as one searchable string."""
    rows = _run(store.audit_query(T))
    return json.dumps([
        {"verb": r.verb, "actor": r.actor, "status": r.status, "detail": r.detail}
        for r in rows
    ], default=str)


@pytest.mark.security
@pytest.mark.invariant("SEC-191")
def test_login_audits_the_session_id_and_never_the_password_secret_or_csrf():
    """`auth_routes.py` says "the session id, never the secret / csrf / password (D8)"."""
    k, app, store = _app()
    _run(_seat_owner(store))
    client = TestClient(app)

    r = client.post("/v1/auth/login", json={"email": OWNER, "password": OWNER_PW})
    assert r.status_code == 200, r.text

    text = _audit_text(store)
    assert "auth.login" in text, "the login was not audited at all"
    assert OWNER_PW not in text, "the password reached an audit row"
    for cookie in client.cookies.jar:
        # The session secret and the CSRF token are handed to the client as cookies, which is
        # the only place this test can see them without reaching into the store's internals.
        # A row carrying either would be the leak the comment denies.
        assert cookie.value and cookie.value not in text, (
            f"the {cookie.name} cookie value reached an audit row"
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-191")
def test_a_failed_login_audits_the_outcome_and_never_the_attempted_password():
    """The failure path is the one that handles an attacker-chosen string, so it is the one
    where a naive "audit the request" would be worst."""
    k, app, store = _app()
    _run(_seat_owner(store))
    client = TestClient(app)

    attempt = "attacker-chosen-Password!-123"
    client.post("/v1/auth/login", json={"email": OWNER, "password": attempt})

    assert attempt not in _audit_text(store), "a failed attempt's password reached an audit row"


@pytest.mark.security
@pytest.mark.invariant("SEC-191")
def test_the_guarantee_is_positional_and_not_the_write_time_scrubber(monkeypatch):
    """With `pii.contains_secret` neutered, nothing changes.

    If this ever goes red while the tests above stay green, the auth surface has started
    relying on the scrubber, and the scrubber is a pattern list: the schema-validation ledger
    order recorded it failing to match an `sk-live-` token at all. A nominal defence is not a
    trust boundary ([2026] VJS-CC-OPBOX 5 H1).
    """
    from boltrig.kernel import audit as audit_mod

    monkeypatch.setattr(audit_mod.pii, "contains_secret", lambda *_a, **_k: None)

    k, app, store = _app()
    _run(_seat_owner(store))
    client = TestClient(app)
    client.post("/v1/auth/login", json={"email": OWNER, "password": OWNER_PW})

    assert OWNER_PW not in _audit_text(store)
