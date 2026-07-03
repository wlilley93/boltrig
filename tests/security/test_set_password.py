"""`boltrig set-password` - the SSO/CF-Access -> session-auth password bridge.

An existing identity (provisioned by an edge IdP, no first-party password) gets a
password so it can log in under BOLTRIG_AUTH_MODE=session. It is NOT a signup: it
refuses an unknown email and never creates an identity or a grant. Box-level +
audited. This is the seeding path the prod cutover needs for an existing owner.
"""
from __future__ import annotations

import pytest

from boltrig.api import initiate as I
from boltrig.identity.passwords import verify_password
from boltrig.models import User, utcnow
from boltrig.store.memory import InMemoryStore

T = "default"


@pytest.fixture()
def _patched_store(monkeypatch):
    store = InMemoryStore()

    async def _build():
        return store

    monkeypatch.setattr("boltrig.api.bootstrap.build_store", _build)
    return store


@pytest.mark.security
async def test_set_password_sets_an_existing_users_credential(_patched_store):
    store = _patched_store
    now = utcnow()
    await store.upsert_user(User(
        id="owner@example.com", tenant_id=T, email="owner@example.com",
        role="superadmin", scope={"all": True}, status="active", source="idp",
        last_seen_at=now, created_at=now,
    ))
    rc = await I._run_set_password("owner@example.com", "a-strong-password-1", T)
    assert rc == 0
    cred = await store.get_password_credential(T, "owner@example.com")
    assert cred is not None
    assert verify_password(cred, "a-strong-password-1") is True


@pytest.mark.security
async def test_set_password_refuses_an_unknown_user(_patched_store):
    # Not a signup: an unknown email is refused, no identity created.
    rc = await I._run_set_password("ghost@example.com", "a-strong-password-1", T)
    assert rc == 3
    assert await _patched_store.get_user(T, "ghost@example.com") is None


@pytest.mark.security
async def test_set_password_rejects_a_weak_password(_patched_store):
    store = _patched_store
    now = utcnow()
    await store.upsert_user(User(
        id="owner@example.com", tenant_id=T, email="owner@example.com",
        role="superadmin", scope={}, status="active", source="idp",
        last_seen_at=now, created_at=now,
    ))
    rc = await I._run_set_password("owner@example.com", "short", T)
    assert rc == 2  # below the min length floor
    assert await store.get_password_credential(T, "owner@example.com") is None
