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
