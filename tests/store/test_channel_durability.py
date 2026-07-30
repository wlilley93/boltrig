"""Channel durability store parity (decision 0003, Phase 2): the durable
replay-dedup markers, the socket-class outbound hand-off and the sender's
binding row behave IDENTICALLY on the in-memory and Postgres stores.

Same parametrized-backend idiom as test_store_parity.py: the memory backend
runs everywhere; the postgres backend runs when BOLTRIG_TEST_DATABASE_URL is
set (CI) and skips cleanly offline.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.models import Channel, ChannelBinding, ChannelOutboxMessage

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


def _binding(
    bid: str, channel_id: str, sender: str, subject: str, role: str, *, tenant: str = T
) -> ChannelBinding:
    return ChannelBinding(
        id=bid, tenant_id=tenant, channel_id=channel_id, platform="slack",
        external_user_id=sender, subject=subject, role=role,
    )


# --- durable replay dedup (M3/SEC-66) ----------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-175")
async def test_record_channel_delivery_is_atomic_and_tenant_scoped(store):
    await _channel(store, "ch-1")
    # ch-2 must EXIST: channel_deliveries.channel_id REFERENCES channels(id), so
    # a marker for an unregistered channel is rejected by Postgres and is not a
    # state the product can reach either (channel_inbound resolves the channel
    # and 404s before any dedup write). The in-memory store enforces no FK, which
    # is why an unseeded ch-2 passed there and failed only on [postgres].
    await _channel(store, "ch-2")
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
@pytest.mark.invariant("SEC-177")
async def test_gateway_owner_lease_is_single_winner_expiring_and_tenant_scoped(
    store,
):
    await _channel(store, "ch-owner")
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    owner = await store.claim_channel_gateway_lease(
        T,
        "ch-owner",
        "gateway-a",
        "private-token-lease-a",
        45,
        now=now,
    )
    assert owner is not None
    assert owner.gateway_id == "gateway-a"
    assert await store.channel_gateway_lease_owned(
        T,
        "ch-owner",
        "private-token-lease-a",
        minimum_remaining_seconds=30,
        now=now,
    )
    assert not await store.channel_gateway_lease_owned(
        T,
        "ch-owner",
        "private-token-lease-a",
        minimum_remaining_seconds=60,
        now=now,
    )
    assert await store.claim_channel_gateway_lease(
        T,
        "ch-owner",
        "gateway-b",
        "private-token-lease-b",
        45,
        now=now,
    ) is None
    assert await store.list_channel_gateway_leases("other") == []

    takeover = await store.claim_channel_gateway_lease(
        T,
        "ch-owner",
        "gateway-b",
        "private-token-lease-b",
        45,
        now=now + timedelta(seconds=46),
    )
    assert takeover is not None
    assert takeover.gateway_id == "gateway-b"
    assert not await store.channel_gateway_lease_owned(
        T,
        "ch-owner",
        "private-token-lease-a",
        now=now + timedelta(seconds=46),
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-11")
async def test_notification_receipts_are_subject_scoped_on_both_stores(store):
    await _channel(store, "ch-1")
    for message_id, subject in (
        ("n-1", "alice"),
        ("n-2", "bob"),
    ):
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(
                id=message_id,
                tenant_id=T,
                channel_id="ch-1",
                payload={
                    "text": "test",
                    "target": "U-1",
                    "subject": subject,
                    "event": "approval",
                },
            )
        )
    alice = await store.list_notification_outbox(T, "alice")
    assert [(item.id, item.status) for item in alice] == [("n-1", "pending")]
    assert await store.list_notification_outbox(T, "mallory") == []
    assert await store.list_notification_outbox("other", "alice") == []


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


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-29")
async def test_delivery_receipts_are_safe_scoped_and_exactly_retry_terminal_failure(store):
    """Both stores expose metadata, not the gateway's payload or lease row.

    Manual recovery is intentionally one narrow transition: the caller must
    name a terminal row and its exact observed revision. Automatic retryable
    rows, delivered rows and stale snapshots cannot be requeued.
    """
    for channel_id in ("queued", "flight", "retryable", "delivered", "failed"):
        await _channel(store, channel_id)
        await store.enqueue_channel_outbox(_msg(f"m-{channel_id}", channel_id))

    in_flight = await store.claim_channel_outbox(T, ["flight"], "gateway", 60, 1)
    assert [row.id for row in in_flight] == ["m-flight"]

    retrying = await store.claim_channel_outbox(T, ["retryable"], "gateway", 60, 1)
    assert [row.id for row in retrying] == ["m-retryable"]
    assert await store.fail_channel_outbox(
        T, "m-retryable", "gateway", "provider said: private detail",
        max_attempts=3, backoff_seconds=600,
    )

    delivered = await store.claim_channel_outbox(T, ["delivered"], "gateway", 60, 1)
    assert [row.id for row in delivered] == ["m-delivered"]
    assert await store.ack_channel_outbox(T, "m-delivered", "gateway")

    failed = await store.claim_channel_outbox(T, ["failed"], "gateway", 60, 1)
    assert [row.id for row in failed] == ["m-failed"]
    assert await store.fail_channel_outbox(
        T, "m-failed", "gateway", "credential and destination must stay private",
        max_attempts=1, backoff_seconds=1,
    )

    expected = {
        "queued": ("queued", 0, None),
        "flight": ("in_flight", 1, None),
        "retryable": ("retryable", 1, "delivery_failed"),
        "delivered": ("delivered", 1, None),
        "failed": ("terminal_failed", 1, "delivery_failed"),
    }
    for channel_id, (status, attempts, safe_reason) in expected.items():
        receipt = await store.get_channel_delivery_receipt(
            T, channel_id, f"m-{channel_id}"
        )
        assert receipt is not None
        assert (receipt.status, receipt.attempts, receipt.safe_reason) == (
            status, attempts, safe_reason
        )
        assert set(vars(receipt)) == {
            "id", "tenant_id", "channel_id", "status", "attempts",
            "safe_reason", "created_at", "updated_at", "next_attempt_at",
        }
        assert await store.get_channel_delivery_receipt(
            "other", channel_id, receipt.id
        ) is None
        assert await store.get_channel_delivery_receipt(
            T, "different-channel", receipt.id
        ) is None

    retryable = await store.get_channel_delivery_receipt(
        T, "retryable", "m-retryable"
    )
    assert retryable is not None and retryable.next_attempt_at is not None
    assert await store.retry_terminal_channel_delivery(
        T, "retryable", "m-retryable", retryable.updated_at
    ) is None

    terminal = await store.get_channel_delivery_receipt(T, "failed", "m-failed")
    assert terminal is not None and terminal.updated_at is not None
    stale = terminal.updated_at - timedelta(microseconds=1)
    assert await store.retry_terminal_channel_delivery(
        T, "failed", "m-failed", stale
    ) is None
    queued = await store.retry_terminal_channel_delivery(
        T, "failed", "m-failed", terminal.updated_at
    )
    assert queued is not None
    assert (queued.status, queued.attempts, queued.safe_reason) == ("queued", 0, None)
    assert await store.retry_terminal_channel_delivery(
        T, "failed", "m-failed", terminal.updated_at
    ) is None


# --- the sender's binding row -------------------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-187")
async def test_rebinding_a_sender_replaces_that_senders_one_row(store):
    await _channel(store, "ch-1")
    await store.upsert_channel_binding(_binding("cb-1", "ch-1", "U-1", "alice", "member"))
    # Every writer mints a FRESH cb_ id, so the re-bind must key on the SENDER:
    # id-keyed, Postgres never reaches its conflict arm and raises against
    # channel_bindings_sender_idx (500, one-time pairing code already burned)
    # while memory stacks a second row the reader never returns.
    await store.upsert_channel_binding(_binding("cb-2", "ch-1", "U-1", "bob", "admin"))

    rows = await store.list_channel_bindings(T, "ch-1")
    assert [(r.id, r.subject, r.role) for r in rows] == [("cb-2", "bob", "admin")], (
        "a re-bind must REPLACE the sender's one binding row, not stack a duplicate "
        "beside it"
    )
    resolved = await store.get_channel_binding(T, "ch-1", "U-1")
    assert (resolved.id, resolved.subject, resolved.role) == ("cb-2", "bob", "admin"), (
        "the resolver still reads the STALE binding after a re-bind: the sender keeps "
        "the old subject/role, so a demotion or re-subject is silently discarded"
    )
    # ...and the sender key is scoped: another sender, or the same sender on
    # another channel, is a DIFFERENT row, never collapsed into the one above.
    await _channel(store, "ch-2")
    await store.upsert_channel_binding(_binding("cb-3", "ch-1", "U-2", "carol", "member"))
    await store.upsert_channel_binding(_binding("cb-4", "ch-2", "U-1", "dave", "member"))
    assert len(await store.list_channel_bindings(T, "ch-1")) == 2
    assert len(await store.list_channel_bindings(T, "ch-2")) == 1
    # tenant_id leads both the sender index and the primary key, and the whole
    # arbiter change hangs on that column, so pin it rather than assume it.
    await _channel(store, "ch-1", tenant="other")
    await store.upsert_channel_binding(
        _binding("cb-5", "ch-1", "U-1", "erin", "member", tenant="other")
    )
    assert len(await store.list_channel_bindings("other", "ch-1")) == 1
    assert len(await store.list_channel_bindings(T, "ch-1")) == 2


@pytest.mark.store
@pytest.mark.invariant("SEC-187")
async def test_a_binding_id_held_by_another_sender_is_refused_on_both_stores(store):
    """The fix's OWN failure mode, pinned in the twin as well as in Postgres.

    Re-using an id that another sender holds violates the primary key. Postgres
    raises and changes nothing; the memory store used to accept it AND delete the
    other sender's row on the way, silently unbinding a third party. That is the
    same memory-cannot-reproduce-Postgres trap this whole defect was made of.
    """
    await _channel(store, "ch-1")
    await store.upsert_channel_binding(_binding("cb-1", "ch-1", "U-1", "alice", "member"))
    await store.upsert_channel_binding(_binding("cb-2", "ch-1", "U-2", "bob", "member"))

    with pytest.raises(Exception):
        await store.upsert_channel_binding(
            _binding("cb-2", "ch-1", "U-1", "mallory", "admin")
        )
    rows = {r.id: r.external_user_id for r in await store.list_channel_bindings(T, "ch-1")}
    assert rows == {"cb-1": "U-1", "cb-2": "U-2"}, (
        "a rejected id-steal still mutated the table: another sender's binding was "
        "deleted or overwritten"
    )
