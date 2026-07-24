"""``boltrig mint-token``: the box-level PAT mint capped at the user's grants.

Mirrors the ``POST /v1/me/tokens`` route (SEC-34): the token can never be minted
above the user, an explicit scope is narrowed to what the user holds, and a token
for a non-existent identity is refused (it is not a signup).
"""

from __future__ import annotations

import pytest

from boltrig.api.mint_token import _run_mint_token
from boltrig.identity.tokens import hash_secret
from boltrig.models import User, utcnow
from boltrig.store import InMemoryStore
from boltrig.store.postgres import set_current_tenant

TENANT = "default"


def _seed_user(role: str = "author", scope: dict | None = None) -> User:
    now = utcnow()
    return User(
        id="u1@acme.test", tenant_id=TENANT, email="u1@acme.test", role=role,
        scope=scope if scope is not None else {}, status="active", source="idp",
        last_seen_at=now, created_at=now,
    )


async def _mint(store, monkeypatch, **kw):
    """Run the command against a store, capturing the printed secret line."""
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    # mint_token imports build_store from bootstrap at call time; patch it there.
    import boltrig.api.bootstrap as bootstrap

    async def _fake_build_store():
        return store
    monkeypatch.setattr(bootstrap, "build_store", _fake_build_store)
    code = await _run_mint_token("u1@acme.test", TENANT, **kw)
    return code, printed


@pytest.mark.security
async def test_mints_a_pat_capped_at_the_users_grants(monkeypatch):
    store = InMemoryStore()
    set_current_tenant(TENANT)
    await store.upsert_user(_seed_user(role="org-admin", scope={"all": True}))
    code, printed = await _mint(store, monkeypatch, name="ci", scope=None, ttl_days=1)
    assert code == 0
    # The stored PAT resolves by the sha256 of the printed secret (shown once).
    secret = printed[-1].strip()
    pat = await store.get_pat_by_hash(hash_secret(secret))
    assert pat is not None and pat.name == "ci" and pat.user_id == "u1@acme.test"


@pytest.mark.security
async def test_explicit_scope_is_narrowed_to_the_users_grants(monkeypatch):
    store = InMemoryStore()
    set_current_tenant(TENANT)
    # A plain author: their derived grants do NOT include a made-up admin verb.
    await store.upsert_user(_seed_user(role="author"))
    code, printed = await _mint(
        store, monkeypatch, name="scoped", scope=["org.delete"], ttl_days=None
    )
    assert code == 0
    secret = printed[-1].strip()
    pat = await store.get_pat_by_hash(hash_secret(secret))
    assert "org.delete" not in pat.scope  # never minted above the user (SEC-34)


@pytest.mark.security
async def test_a_missing_user_is_refused_not_created(monkeypatch):
    store = InMemoryStore()
    set_current_tenant(TENANT)
    code, _ = await _mint(store, monkeypatch, name="ci", scope=None, ttl_days=1)
    assert code == 3  # no identity -> refuse; mint-token never creates a user


@pytest.mark.security
async def test_a_blank_name_is_refused(monkeypatch):
    store = InMemoryStore()
    set_current_tenant(TENANT)
    await store.upsert_user(_seed_user())
    code, _ = await _mint(store, monkeypatch, name="  ", scope=None, ttl_days=1)
    assert code == 2
