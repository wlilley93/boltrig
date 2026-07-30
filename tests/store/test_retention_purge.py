"""Right-to-erasure: closed conversations are hard-purged past retention (M11 / SEC-74).

``DELETE /v1/me/conversations/{id}`` soft-closes a thread (status=CLOSED); the
durable hard-erasure is the retention worker's job
(:mod:`boltrig.fleet.retention`). This module proves the worker
(``run_retention_once``) hard-deletes a CLOSED conversation AND its messages once
it is older than the retention cutoff, leaves an open or recently-closed thread
alone, returns the right count, and is tenant-scoped - on BOTH stores (parity):
the in-memory store everywhere, and Postgres when BOLTRIG_TEST_DATABASE_URL is
set (skips cleanly offline, following the store-parity pattern).
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from boltrig.fleet.retention import run_retention_once
from boltrig.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    MessageRole,
    utcnow,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "conversations,conversation_messages"


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


async def _seed_conv(store, cid, *, status, updated_at, tenant=T, user="alice"):
    conv = Conversation(
        id=cid, tenant_id=tenant, user_id=user, title=cid, status=status,
        created_at=updated_at, updated_at=updated_at,
    )
    await store.create_conversation(conv)
    await store.add_message(
        ConversationMessage(
            id=f"{cid}-m1", conversation_id=cid, tenant_id=tenant,
            role=MessageRole.USER, content="secret body", created_at=updated_at,
        )
    )
    return conv


@pytest.mark.store
@pytest.mark.invariant("SEC-74")
async def test_closed_conversation_body_is_hard_purged_after_retention(store):
    now = utcnow()
    retention_days = 30
    old = now - timedelta(days=31)     # closed + past the cutoff -> purged
    recent = now - timedelta(days=1)   # closed but inside the window -> kept

    await _seed_conv(store, "closed-old", status=ConversationStatus.CLOSED, updated_at=old)
    await _seed_conv(store, "closed-recent", status=ConversationStatus.CLOSED, updated_at=recent)
    await _seed_conv(store, "open-old", status=ConversationStatus.ACTIVE, updated_at=old)

    purged = await run_retention_once(store, T, retention_days, now=now)
    assert purged == 1  # only the closed + old thread

    # the closed + old conversation AND its messages are gone (right-to-erasure).
    assert await store.get_conversation(T, "closed-old") is None
    assert await store.list_messages(T, "closed-old") == []

    # a recently-closed thread (still inside the window) and an open thread survive.
    assert await store.get_conversation(T, "closed-recent") is not None
    assert await store.list_messages(T, "closed-recent") != []
    assert await store.get_conversation(T, "open-old") is not None
    assert await store.list_messages(T, "open-old") != []


@pytest.mark.store
@pytest.mark.invariant("SEC-74")
async def test_retention_purge_is_tenant_scoped(store):
    now = utcnow()
    old = now - timedelta(days=40)
    await _seed_conv(store, "mine", status=ConversationStatus.CLOSED, updated_at=old)
    # a closed + old conversation in ANOTHER tenant must survive a purge of T.
    await _seed_conv(
        store, "theirs", status=ConversationStatus.CLOSED, updated_at=old,
        tenant="other", user="bob",
    )

    purged = await run_retention_once(store, T, 30, now=now)
    assert purged == 1
    assert await store.get_conversation(T, "mine") is None
    assert await store.get_conversation("other", "theirs") is not None
    assert await store.list_messages("other", "theirs") != []


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-13")
async def test_restore_transition_is_owner_scoped_and_idempotent_on_both_stores(store):
    now = utcnow()
    await _seed_conv(
        store,
        "restore-contract",
        status=ConversationStatus.CLOSED,
        updated_at=now - timedelta(days=1),
    )

    assert await store.restore_closed_conversation(
        T, "missing", "alice", now
    ) == (False, False, False)
    assert await store.restore_closed_conversation(
        T, "restore-contract", "bob", now
    ) == (True, False, False)
    assert await store.restore_closed_conversation(
        T, "restore-contract", "alice", now
    ) == (True, True, True)
    assert await store.restore_closed_conversation(
        T, "restore-contract", "alice", now
    ) == (True, True, False)
    restored = await store.get_conversation(T, "restore-contract")
    assert restored is not None
    assert restored.status == ConversationStatus.ACTIVE
    assert restored.updated_at == now


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-13")
async def test_restore_racing_retention_never_resurrects_a_purged_row(store):
    now = utcnow()
    cutoff = now - timedelta(days=30)
    await _seed_conv(
        store,
        "restore-race",
        status=ConversationStatus.CLOSED,
        updated_at=now - timedelta(days=31),
    )

    restored, purged = await asyncio.gather(
        store.restore_closed_conversation(T, "restore-race", "alice", now),
        store.purge_closed_conversations(T, cutoff),
    )
    surviving = await store.get_conversation(T, "restore-race")

    if restored == (True, True, True):
        assert purged == 0
        assert surviving is not None
        assert surviving.status == ConversationStatus.ACTIVE
    else:
        assert restored == (False, False, False)
        assert purged == 1
        assert surviving is None
        assert await store.list_messages(T, "restore-race") == []


@pytest.mark.invariant("SEC-74")
def test_purge_runs_select_and_deletes_in_one_transaction():
    # The hard-purge SELECT + three DELETEs must share ONE transaction, so a crash
    # mid-purge cannot strand a conversation whose messages are already erased.
    from boltrig.store.postgres import PostgresStore, set_current_tenant

    log: list = []

    class _Conn:
        def __init__(self) -> None:
            self._in_txn = False

        def transaction(self):
            conn = self

            class _T:
                async def __aenter__(self_inner):
                    conn._in_txn = True
                    return None

                async def __aexit__(self_inner, *a):
                    conn._in_txn = False
                    return False

            return _T()

        async def fetch(self, q, *a):
            log.append(("fetch", q, self._in_txn))
            return [{"id": "c1"}]

        async def execute(self, q, *a):
            log.append(("execute", q, self._in_txn))
            return "DELETE 1"

    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def __init__(self):
            self.conn = _Conn()

        def acquire(self):
            return _Acquire(self.conn)

    store = PostgresStore(_Pool())
    set_current_tenant("acme")
    try:
        n = asyncio.run(store.purge_closed_conversations("acme", "2020-01-01"))
    finally:
        set_current_tenant(None)
    assert n == 1
    # the GUC set is the first statement, then the SELECT + 3 DELETEs, and every
    # data statement executed inside the single transaction (in_txn is True).
    assert log[0][0] == "execute" and "set_config('app.tenant_id'" in log[0][1]
    data_ops = [entry for entry in log if "set_config" not in entry[1]]
    assert len(data_ops) == 4  # 1 select + 3 deletes
    assert all(in_txn for _, _, in_txn in data_ops)
