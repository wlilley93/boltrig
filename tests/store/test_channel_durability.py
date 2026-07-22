"""Channel durability store parity (decision 0003, Phase 2): the durable
replay-dedup markers and the socket-class outbound hand-off behave IDENTICALLY
on the in-memory and Postgres stores.

Same parametrized-backend idiom as test_store_parity.py: the memory backend
runs everywhere; the postgres backend runs when BOLTRIG_TEST_DATABASE_URL is
set (CI) and skips cleanly offline.
"""

from __future__ import annotations

import os

import pytest

from boltrig.models import Channel, ChannelOutboxMessage

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "channels,channel_deliveries,channel_outbox"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    s = await _make_store(request.param)
    yield s
    close = getattr(s, "close", None)
    if close is not None:
        await close()


async def _channel(s, cid: str, tenant: str = T) -> None:
    await s.upsert_channel(
        Channel(id=cid, tenant_id=tenant, platform="slack", name=cid, transport="socket")
    )


def _msg(mid: str, channel_id: str, *, tenant: str = T) -> ChannelOutboxMessage:
    return ChannelOutboxMessage(
        id=mid, tenant_id=tenant, channel_id=channel_id,
        payload={"text": f"body-{mid}", "target": "C1"},
    )


# --- durable replay dedup (M3/SEC-66) ----------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-175")
async def test_record_channel_delivery_is_atomic_and_tenant_scoped(store):
    await _channel(store, "ch-1")
    # first sighting records; a replay within the window is refused - on BOTH
    # stores, so dedup holds across processes, not just in one memory space
    assert await store.record_channel_delivery(T, "ch-1", "d-1", ttl_seconds=600) is True
    assert await store.record_channel_delivery(T, "ch-1", "d-1", ttl_seconds=600) is False
    # a different channel or tenant is a DIFFERENT marker (tenant isolation)
    assert await store.record_channel_delivery(T, "ch-2", "d-1", ttl_seconds=600) is True
    assert await store.record_channel_delivery("other", "ch-1", "d-1", ttl_seconds=600) is True


@pytest.mark.store
@pytest.mark.invariant("SEC-175")
async def test_record_channel_delivery_honours_the_ttl(store):
    await _channel(store, "ch-1")
    # an already-expired marker is evicted and the delivery counts as new
    assert await store.record_channel_delivery(T, "ch-1", "d-2", ttl_seconds=-1) is True
    assert await store.record_channel_delivery(T, "ch-1", "d-2", ttl_seconds=600) is True
    # ...and from then on the live marker dedups again
    assert await store.record_channel_delivery(T, "ch-1", "d-2", ttl_seconds=600) is False


# --- the durable outbound hand-off -------------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-176")
async def test_outbox_claim_is_single_winner_and_lease_scoped(store):
    await _channel(store, "ch-1")
    await store.enqueue_channel_outbox(_msg("m-1", "ch-1"))
    await store.enqueue_channel_outbox(_msg("m-2", "ch-1"))

    claimed = await store.claim_channel_outbox(T, ["ch-1"], "w1", 60, 10)
    assert [m.id for m in claimed] == ["m-1", "m-2"]  # oldest first
    assert all(m.status == "in_flight" and m.lease_owner == "w1" and m.attempts == 1
               for m in claimed)
    # a concurrent claimer wins nothing while the lease is live
    assert await store.claim_channel_outbox(T, ["ch-1"], "w2", 60, 10) == []
    # ack is CAS'd on the lease owner: a stranger cannot settle w1's claim
    assert await store.ack_channel_outbox(T, "m-1", "w2") is False
    assert await store.ack_channel_outbox(T, "m-1", "w1") is True
    assert await store.ack_channel_outbox(T, "m-1", "w1") is False  # terminal
    # tenant isolation: another tenant cannot see or settle the row
    assert await store.claim_channel_outbox("other", ["ch-1"], "w9", 60, 10) == []
    assert await store.ack_channel_outbox("other", "m-2", "w1") is False


@pytest.mark.store
@pytest.mark.invariant("SEC-176")
async def test_outbox_claim_honours_channel_set_and_lease_expiry(store):
    await _channel(store, "ch-1")
    await _channel(store, "ch-2")
    await store.enqueue_channel_outbox(_msg("m-1", "ch-1"))
    await store.enqueue_channel_outbox(_msg("m-2", "ch-2"))
    # the claim is bounded to the caller's channel set; a negative lease lapses
    # at once, so the next claimer reclaims the row (an expired lease is
    # reclaimable) and attempts increments per claim
    assert [m.id for m in await store.claim_channel_outbox(T, ["ch-1"], "w1", -1, 10)] == ["m-1"]
    reclaimed = await store.claim_channel_outbox(T, ["ch-1"], "w2", 60, 10)
    assert [m.id for m in reclaimed] == ["m-1"]
    assert reclaimed[0].attempts == 2


@pytest.mark.store
@pytest.mark.invariant("SEC-176")
async def test_outbox_fail_backs_off_then_terminates(store):
    await _channel(store, "ch-1")
    await store.enqueue_channel_outbox(_msg("m-1", "ch-1"))
    await store.enqueue_channel_outbox(_msg("m-2", "ch-1"))
    await store.claim_channel_outbox(T, ["ch-1"], "w1", 60, 10)

    # under the cap: back to pending behind a FUTURE backoff gate (not hot-loop)
    assert await store.fail_channel_outbox(
        T, "m-1", "w1", "boom", max_attempts=3, backoff_seconds=600
    ) is True
    assert await store.claim_channel_outbox(T, ["ch-1"], "w1", 60, 10) == []
    # at the cap: terminally failed, never claimable again
    assert await store.fail_channel_outbox(
        T, "m-2", "w1", "poison", max_attempts=1, backoff_seconds=1
    ) is True
    assert await store.claim_channel_outbox(T, ["ch-1"], "w1", 60, 10) == []
    # a stale claimer cannot fail a row it does not own
    assert await store.fail_channel_outbox(
        T, "m-1", "stranger", "x", max_attempts=3, backoff_seconds=1
    ) is False
