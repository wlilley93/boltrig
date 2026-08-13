"""Memory/PostgreSQL parity for atomic first-party invitation claims."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from boltrig.models import UserInvitation, utcnow


DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "invitation-claim-store-tenant"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute("TRUNCATE user_invitations RESTART IDENTITY CASCADE")
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
async def invitation_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def _invite(invitation_id: str, token_hash: str, *, expired: bool = False):
    now = utcnow()
    return UserInvitation(
        id=invitation_id,
        tenant_id=T,
        email=f"{invitation_id}@example.io",
        intended_role="member",
        intended_scope={},
        invited_by="owner@example.io",
        expires_at=now + (-timedelta(seconds=1) if expired else timedelta(hours=1)),
        token_hash=token_hash,
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-97")
@pytest.mark.invariant("SEC-08")
async def test_exact_token_claim_is_single_winner_and_expiry_safe(invitation_store):
    store = invitation_store
    now = utcnow()
    live_hash = "a" * 64
    await store.add_invitation(_invite("live", live_hash))

    attempts = await asyncio.gather(
        store.claim_invitation_by_token_hash(T, live_hash, now),
        store.claim_invitation_by_token_hash(T, live_hash, now),
    )
    winners = [result for result in attempts if result is not None]
    assert len(winners) == 1
    assert winners[0].id == "live"
    assert winners[0].status == "accepted"
    assert (await store.get_invitation(T, "live")).status == "accepted"

    expired_hash = "b" * 64
    await store.add_invitation(_invite("expired", expired_hash, expired=True))
    assert await store.claim_invitation_by_token_hash(T, expired_hash, now) is None
    assert (await store.get_invitation(T, "expired")).status == "pending"
    assert await store.claim_invitation_by_token_hash(T, "c" * 64, now) is None
