"""`memory.ingest.on_session_end` must actually select threads, and only the right ones.

The manifest shipped this flag and the admin console offered it as a toggle while
nothing read either - a switch for behaviour that did not exist. These pin the two
properties that make it safe to switch on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from boltrig.memory.session_distillation import (
    DistillationPolicy,
    already_distilled,
    policy_from_manifest,
    select_conversations_to_distil,
)
from boltrig.models.conversation import Conversation, ConversationStatus
from boltrig.models.memory import MemoryIngestion
from boltrig.store import InMemoryStore

T = "t-distil"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


def _manifest(**ingest):
    return {"memory": {"enabled": True, "ingest": {**ingest}}}


async def _conv(store, conv_id, *, minutes_idle, status=ConversationStatus.ACTIVE):
    conv = Conversation(
        id=conv_id,
        tenant_id=T,
        user_id="u1",
        title=conv_id,
        status=status,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(minutes=minutes_idle),
    )
    store._convs[(T, conv_id)] = conv
    return conv


def test_off_unless_the_manifest_says_otherwise():
    """A retention feature must never switch itself on by accident."""
    assert policy_from_manifest(None).enabled is False
    assert policy_from_manifest({}).enabled is False
    assert policy_from_manifest({"memory": {}}).enabled is False
    assert policy_from_manifest(_manifest()).enabled is False
    # present but not exactly True - a string "true" must not enable it
    assert policy_from_manifest(_manifest(on_session_end="true")).enabled is False
    assert policy_from_manifest(
        {"memory": {"enabled": False, "ingest": {"on_session_end": True}}}
    ).enabled is False


def test_enabled_reads_the_idle_window_and_defaults_to_an_hour():
    p = policy_from_manifest(_manifest(on_session_end=True))
    assert p.enabled is True
    assert p.idle_minutes == 60, "the Principal chose ~1 hour"

    p2 = policy_from_manifest(_manifest(on_session_end=True, session_idle_minutes=15))
    assert p2.idle_minutes == 15

    # a nonsense window falls back rather than distilling everything instantly
    p3 = policy_from_manifest(_manifest(on_session_end=True, session_idle_minutes=0))
    assert p3.idle_minutes == 60
    p4 = policy_from_manifest(_manifest(on_session_end=True, session_idle_minutes="soon"))
    assert p4.idle_minutes == 60


async def test_only_idle_threads_are_selected():
    store = InMemoryStore()
    await _conv(store, "quiet", minutes_idle=90)
    await _conv(store, "busy", minutes_idle=5)

    policy = policy_from_manifest(_manifest(on_session_end=True))
    picked = await select_conversations_to_distil(store, T, NOW, policy)

    assert [c.id for c in picked] == ["quiet"], "a live thread must not be distilled"


async def test_a_deleted_thread_is_never_distilled():
    """retention.py soft-closes a deleted thread. It must not then be copied into
    365-day memory - that would resurrect content the user asked to remove."""
    store = InMemoryStore()
    await _conv(store, "deleted", minutes_idle=90, status=ConversationStatus.CLOSED)
    await _conv(store, "kept", minutes_idle=90)

    policy = policy_from_manifest(_manifest(on_session_end=True))
    picked = await select_conversations_to_distil(store, T, NOW, policy)

    assert [c.id for c in picked] == ["kept"]


async def test_distilling_is_idempotent_across_sweeps():
    """The sweep runs repeatedly over the same threads. Without the receipt check
    it would write the same content into memory on every pass."""
    store = InMemoryStore()
    await _conv(store, "once", minutes_idle=90)
    policy = policy_from_manifest(_manifest(on_session_end=True))

    first = await select_conversations_to_distil(store, T, NOW, policy)
    assert [c.id for c in first] == ["once"]
    assert await already_distilled(store, T, "once") is False

    await store.add_memory_ingestion(
        MemoryIngestion(
            id="ing-1",
            tenant_id=T,
            source_kind="conversation",
            source_ref="once",
            owner_scope="user:u1",
            status="done",
        )
    )

    assert await already_distilled(store, T, "once") is True
    second = await select_conversations_to_distil(store, T, NOW, policy)
    assert second == [], "a distilled thread must not be picked up again"


async def test_disabled_policy_selects_nothing_even_with_idle_threads():
    store = InMemoryStore()
    await _conv(store, "quiet", minutes_idle=999)
    picked = await select_conversations_to_distil(store, T, NOW, DistillationPolicy())
    assert picked == []


def test_the_seat_acts_on_behalf_of_the_thread_owner():
    """A generic seat cannot write memory, and only a deployment showed that.

    Memory RBAC derives the permitted owner scopes from ``context.on_behalf_of``
    (ultracode_memory.owner_scopes -> adapter_writes._refuse_unsafe_content). A
    context with no principal has NO scopes, so the write is refused for every
    user. Measured on the beelink 2026-07-30: the sweep raised
    ``GrantMissing: cannot write memory to scope user:...`` on every thread while
    the unit tests were green, because they exercised SELECTION and never the
    governed write.

    So the seat must be per-owner. This also bounds it: a distillation can write
    into that one owner's scope and nowhere else.
    """
    from boltrig.memory.session_distillation import distillation_context as _distillation_context

    ctx = _distillation_context("t1", "alice@example.com")
    assert ctx.on_behalf_of == "alice@example.com", (
        "without on_behalf_of the memory write is refused for every scope"
    )
    assert ctx.grants.permits("memory.remember")
    assert not ctx.grants.permits("memory.forget"), "the seat must stay bounded"

    other = _distillation_context("t1", "bob@example.com")
    assert other.on_behalf_of == "bob@example.com", "each thread gets its own seat"


async def test_the_sweep_drains_a_backlog_LARGER_than_one_batch():
    """A batch-sized limit must not wedge the sweep after the first pass.

    THE DEFECT THIS PINS, measured live on the beelink 2026-07-30: the SQL applied
    `LIMIT batch` ordered by updated_at, and already-distilled threads were filtered
    out afterwards in Python. So the second sweep fetched the same oldest 20,
    discarded all 20, and returned nothing - 20 of 89 written, then permanently
    stuck, with zero errors and a healthy worker.

    The existing idempotency test could not see it: with ONE conversation there is
    no difference between "skips a distilled thread" and "is wedged by it". A
    backlog test needs MORE items than the batch, which is the whole point.
    """
    store = InMemoryStore()
    policy = policy_from_manifest(_manifest(on_session_end=True))
    total = policy.batch * 2 + 3  # deliberately not a multiple of the batch
    for i in range(total):
        await _conv(store, f"c{i:03d}", minutes_idle=90 + i)

    seen: list[str] = []
    for sweep in range(6):
        due = await select_conversations_to_distil(store, T, NOW, policy)
        if not due:
            break
        assert len(due) <= policy.batch
        for conv in due:
            assert conv.id not in seen, f"{conv.id} handed out twice"
            seen.append(conv.id)
            await store.add_memory_ingestion(
                MemoryIngestion(
                    id=f"ing-{conv.id}",
                    tenant_id=T,
                    source_kind="conversation",
                    source_ref=conv.id,
                    owner_scope="user:u1",
                    status="done",
                )
            )

    assert len(seen) == total, (
        f"the sweep drained only {len(seen)} of {total} - it wedged after the "
        f"first batch instead of advancing"
    )
    assert await select_conversations_to_distil(store, T, NOW, policy) == []


async def test_pending_is_visible_even_when_selection_returns_nothing():
    """The 2026-07-30 wedge made selection return NOTHING - seen=0 acted=0, which
    reads as idle. ``count_pending_distillation`` is computed from two plain
    counts sharing no logic with selection, so a selection bug cannot zero it.

    Here selection is HEALTHY and empty because every idle thread is distilled -
    and pending agrees at 0. The point is the next test: the numbers are derived
    independently, so a regression in one cannot silently agree with the other.
    """
    store = InMemoryStore()
    policy = policy_from_manifest(_manifest(on_session_end=True))
    await _conv(store, "a", minutes_idle=90)
    await _conv(store, "b", minutes_idle=120)
    await _conv(store, "busy", minutes_idle=2)

    idle_before = NOW - policy.idle_after
    assert await store.count_pending_distillation(T, idle_before) == 2

    for cid in ("a", "b"):
        await store.add_memory_ingestion(
            MemoryIngestion(
                id=f"ing-{cid}",
                tenant_id=T,
                source_kind="conversation",
                source_ref=cid,
                owner_scope="user:u1",
                status="done",
            )
        )
    assert await select_conversations_to_distil(store, T, NOW, policy) == []
    assert await store.count_pending_distillation(T, idle_before) == 0


async def test_pending_counts_do_not_share_selections_logic():
    """If the pending number were derived from selection's own row set, a bug in
    selection (filtering every candidate away, as on 2026-07-30) would zero it
    too, and a wedged sweep would report "idle". These counts deliberately go
    straight to the conversation and receipt tables."""
    store = InMemoryStore()
    await _conv(store, "wedged-1", minutes_idle=90)
    await _conv(store, "wedged-2", minutes_idle=90)
    idle_before = NOW - timedelta(minutes=60)

    # Simulate selection's blind spot WITHOUT touching the underlying data: even
    # if selection somehow returned nothing, the pending count must not move.
    pending_before = await store.count_pending_distillation(T, idle_before)
    assert pending_before == 2

    # a receipt for a DIFFERENT source kind must not reduce the count either
    await store.add_memory_ingestion(
        MemoryIngestion(
            id="ing-other",
            tenant_id=T,
            source_kind="reflection",
            source_ref="wedged-1",
            owner_scope="user:u1",
            status="done",
        )
    )
    assert await store.count_pending_distillation(T, idle_before) == 2


async def test_the_pg_count_uses_only_what_the_rls_pool_exposes():
    """The beelink deploy 2026-07-30: count_pending_distillation called
    ``_pool.fetchval``, and _RlsPool exposes only fetch/fetchrow/execute - the
    sweep errored on every cycle while the in-memory tests were green, because
    InMemoryStore never touches a pool. This drives the PG implementation
    through a pool double with exactly the _RlsPool surface."""
    from boltrig.store.distillation_reads import DistillationReadsPG

    class _RlsSurfacePool:
        """Only the three methods _RlsPool actually has. No fetchval."""

        async def fetch(self, query, *args):
            raise AssertionError("unexpected call")

        async def fetchrow(self, query, *args):
            if "FROM conversations" in query:
                return {"n": 5}
            if "FROM memory_ingestions" in query:
                return {"n": 2}
            raise AssertionError(f"unexpected query: {query}")

        async def execute(self, query, *args):
            raise AssertionError("unexpected call")

    class _Store(DistillationReadsPG):
        def __init__(self):
            self._pool = _RlsSurfacePool()

    pending = await _Store().count_pending_distillation("t1", NOW)
    assert pending == 3
