"""Memory/Postgres parity for atomic password recovery."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from boltrig.models import TwoFactorChallenge, User, UserSession, utcnow
from boltrig.models.access import PasswordResetToken

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "password-reset-store-tenant"
EMAIL = "owner@example.io"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE password_reset_tokens,two_factor_challenges,user_sessions,"
        "user_credentials,users RESTART IDENTITY CASCADE"
    )
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def password_reset_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


@pytest.mark.store
@pytest.mark.invariant("SEC-AUTH-RECOVERY-01")
@pytest.mark.invariant("SEC-08")
async def test_password_reset_lifecycle_matches_on_both_stores(password_reset_store):
    store = password_reset_store
    now = utcnow()
    await store.upsert_user(
        User(
            id=EMAIL,
            tenant_id=T,
            email=EMAIL,
            status="active",
            must_change_password=True,
        )
    )
    await store.set_password_credential(T, EMAIL, "old-password-hash")
    for session_id in ("session-a", "session-b"):
        await store.add_session(
            UserSession(
                id=session_id,
                tenant_id=T,
                user_id=EMAIL,
                token_hash=(session_id[-1] * 64),
                expires_at=now + timedelta(hours=1),
            )
        )
    await store.add_two_factor_challenge(
        TwoFactorChallenge(
            tenant_id=T,
            token_hash="c" * 64,
            user_id=EMAIL,
            expires_at=now + timedelta(minutes=5),
        )
    )

    assert not await store.replace_password_reset_token(
        PasswordResetToken(
            tenant_id=T,
            user_id="absent@example.io",
            token_hash="0" * 64,
            expires_at=now + timedelta(minutes=30),
        )
    )
    first = PasswordResetToken(
        tenant_id=T,
        user_id=EMAIL,
        token_hash="1" * 64,
        expires_at=now + timedelta(minutes=30),
    )
    second = PasswordResetToken(
        tenant_id=T,
        user_id=EMAIL,
        token_hash="2" * 64,
        expires_at=now + timedelta(minutes=30),
    )
    assert await store.replace_password_reset_token(first)
    assert await store.replace_password_reset_token(second)
    assert await store.reset_password_with_token(T, first.token_hash, "wrong-new-hash", now) is None

    attempts = await asyncio.gather(
        store.reset_password_with_token(T, second.token_hash, "new-password-hash", now),
        store.reset_password_with_token(T, second.token_hash, "new-password-hash", now),
    )
    winners = [result for result in attempts if result is not None]
    assert len(winners) == 1
    assert winners[0].user_id == EMAIL
    assert winners[0].revoked_sessions == 2
    assert await store.get_password_credential(T, EMAIL) == "new-password-hash"
    assert (await store.get_user(T, EMAIL)).must_change_password is False
    assert all(session.revoked for session in await store.list_sessions(T, EMAIL))
    assert await store.get_two_factor_challenge(T, "c" * 64) is None

    expired = PasswordResetToken(
        tenant_id=T,
        user_id=EMAIL,
        token_hash="3" * 64,
        expires_at=now - timedelta(seconds=1),
    )
    assert await store.replace_password_reset_token(expired)
    assert (
        await store.reset_password_with_token(T, expired.token_hash, "must-not-land", now) is None
    )
    assert await store.get_password_credential(T, EMAIL) == "new-password-hash"
