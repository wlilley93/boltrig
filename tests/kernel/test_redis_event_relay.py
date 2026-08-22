"""Parity and cross-replica acceptance for the bounded Redis event relay."""

from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis
import pytest
from fakeredis import aioredis as fake_aioredis

from boltrig.fleet.chat import ChatService
from boltrig.fleet.chat_turn_flow import _next_turn, _stream_one
from boltrig.kernel.events import (
    EventRelay,
    build_event_relay,
)
from boltrig.kernel.redis_event_relay import RedisEventRelay
from boltrig.models import Conversation, ConversationMessage, MessageRole
from boltrig.store import InMemoryStore

pytestmark = pytest.mark.kernel


def _fake_pair(
    server: fakeredis.FakeServer,
    *,
    namespace: str,
    backlog: int = 2,
    max_closed: int = 2,
) -> RedisEventRelay:
    return RedisEventRelay(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        fake_aioredis.FakeRedis(server=server, decode_responses=True),
        backlog=backlog,
        max_closed=max_closed,
        namespace=namespace,
    )


@pytest.mark.invariant("NFR-CONV-03")
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_relay_backends_preserve_bounded_cursor_and_reopen_semantics(
    backend: str,
) -> None:
    relay = (
        EventRelay(backlog=2, max_closed=2)
        if backend == "memory"
        else _fake_pair(
            fakeredis.FakeServer(),
            namespace=f"parity-{uuid.uuid4().hex}",
        )
    )
    original = {"type": "text_delta", "delta": "one"}
    relay.publish("acme", "run-1", original)
    relay.publish("acme", "run-1", {"type": "text_delta", "delta": "two"})
    relay.publish("acme", "run-1", {"type": "text_delta", "delta": "three"})

    assert relay.seq_bounds("acme", "run-1") == (2, 3)
    assert [item["delta"] for item in relay.snapshot("acme", "run-1")] == [
        "two",
        "three",
    ]
    assert [item["delta"] for item in relay.snapshot("acme", "run-1", since=2)] == ["three"]
    assert original == {"type": "text_delta", "delta": "one"}

    relay.close("acme", "run-1")
    assert [seq async for seq, _event in relay.subscribe_with_seq("acme", "run-1", since=1)] == [
        2,
        3,
    ]
    relay.reopen("acme", "run-1")
    relay.publish("acme", "run-1", {"type": "text_delta", "delta": "four"})
    assert relay.seq_bounds("acme", "run-1") == (3, 4)


@pytest.mark.invariant("NFR-CONV-03")
async def test_two_redis_replicas_share_replay_live_close_and_active_run_truth() -> None:
    server = fakeredis.FakeServer()
    namespace = f"replicas-{uuid.uuid4().hex}"
    replica_a = _fake_pair(server, namespace=namespace)
    replica_b = _fake_pair(server, namespace=namespace)

    replica_a.publish("acme", "run-1", {"type": "text_delta", "delta": "replay"})
    follower = replica_b.subscribe_with_seq("acme", "run-1")
    first = await anext(follower)
    assert first == (1, {"type": "text_delta", "delta": "replay"})

    waiting = asyncio.create_task(anext(follower))
    await asyncio.sleep(0)
    replica_a.publish("acme", "run-1", {"type": "text_delta", "delta": "live"})
    assert await asyncio.wait_for(waiting, timeout=1) == (
        2,
        {"type": "text_delta", "delta": "live"},
    )
    replica_a.close("acme", "run-1")
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(follower), timeout=1)

    async with replica_a.conversation_lock("acme", "conversation-1"):
        assert replica_b.active_run("acme", "conversation-1") is None
        replica_a.set_active_run("acme", "conversation-1", "run-1")
    assert replica_b.active_run("acme", "conversation-1") == "run-1"
    assert not replica_b.clear_active_run("acme", "conversation-1", expected="another-run")
    assert replica_b.clear_active_run("acme", "conversation-1", expected="run-1")


@pytest.mark.invariant("NFR-CONV-03")
async def test_chat_projection_on_replica_b_follows_replica_a_canonical_run() -> None:
    server = fakeredis.FakeServer()
    namespace = f"chat-{uuid.uuid4().hex}"
    replica_a = _fake_pair(server, namespace=namespace)
    replica_b = _fake_pair(server, namespace=namespace)
    store = InMemoryStore()
    await store.create_conversation(
        Conversation(
            id="conversation-1",
            tenant_id="acme",
            user_id="alice",
            title="Shared",
        )
    )
    chat_a = ChatService(store, replica_a)
    chat_b = ChatService(store, replica_b)

    async with chat_a._lock_for("acme", "conversation-1"):  # noqa: SLF001
        chat_a._set_active_run(  # noqa: SLF001
            "acme", "conversation-1", "run-1"
        )
    replica_a.publish("acme", "run-1", {"type": "text_delta", "delta": "from replica A"})

    projection = chat_b.live_projection()
    assert await projection.active_run_for("acme", "alice", "engineer", "conversation-1") == "run-1"
    follower = projection.follow("acme", "conversation-1", "run-1")
    assert await anext(follower) == (
        1,
        {"type": "text_delta", "delta": "from replica A"},
    )
    replica_a.close("acme", "run-1")
    replica_a.clear_active_run("acme", "conversation-1", expected="run-1")
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(follower), timeout=1)


@pytest.mark.invariant("NFR-CONV-03")
async def test_two_chat_replicas_admit_one_turn_and_durably_queue_the_steer() -> None:
    server = fakeredis.FakeServer()
    namespace = f"steer-{uuid.uuid4().hex}"
    replica_a = _fake_pair(server, namespace=namespace)
    replica_b = _fake_pair(server, namespace=namespace)
    store = InMemoryStore()
    gate = asyncio.Event()
    entered = asyncio.Event()
    calls: list[str] = []

    async def executor(
        *,
        run_id,
        message,
        relay,
        **_kwargs,
    ) -> None:
        calls.append(message)
        entered.set()
        if len(calls) == 1:
            await gate.wait()
        relay.publish(run_id, {"type": "text_delta", "delta": f"reply:{message}"})

    chat_a = ChatService(store, replica_a, turn_executor=executor)
    chat_b = ChatService(store, replica_b, turn_executor=executor)
    first = asyncio.create_task(
        _collect_turn(
            chat_a.handle_turn(
                tenant_id="acme",
                user_id="alice",
                role="engineer",
                message="first",
            )
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    conversation = (await store.list_conversations("acme", "alice"))[0]

    queued = await _collect_turn(
        chat_b.handle_turn(
            tenant_id="acme",
            user_id="alice",
            role="engineer",
            message="second",
            conversation_id=conversation.id,
        )
    )
    assert [item["type"] for item in queued] == ["queued"]
    assert calls == ["first"]

    gate.set()
    frames = await asyncio.wait_for(first, timeout=2)
    assert calls == ["first", "second"]
    assert [item["type"] for item in frames].count("message_start") == 2
    assert [item["type"] for item in frames].count("message_end") == 2


@pytest.mark.invariant("NFR-CONV-03")
@pytest.mark.invariant("US-CHAT-15")
async def test_direct_input_is_durable_before_another_replica_can_append_a_steer() -> None:
    """Pin the ordering race: direct input must stay inside admission's lock."""

    class InterleavingStore(InMemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self.direct_started = asyncio.Event()
            self.release_direct = asyncio.Event()
            self._gated = False

        async def add_message(self, message):
            if not self._gated and message.role == MessageRole.USER and message.run_id is not None:
                self._gated = True
                self.direct_started.set()
                await self.release_direct.wait()
            return await super().add_message(message)

    server = fakeredis.FakeServer()
    namespace = f"ordering-{uuid.uuid4().hex}"
    store = InterleavingStore()
    calls: list[str] = []
    executor_entered = asyncio.Event()
    release_executor = asyncio.Event()

    async def executor(*, run_id, message, relay, **_kwargs) -> None:
        calls.append(message)
        executor_entered.set()
        if len(calls) == 1:
            await release_executor.wait()
        relay.publish(run_id, {"type": "text_delta", "delta": message})

    chat_a = ChatService(store, _fake_pair(server, namespace=namespace), turn_executor=executor)
    chat_b = ChatService(store, _fake_pair(server, namespace=namespace), turn_executor=executor)
    first = asyncio.create_task(
        _collect_turn(
            chat_a.handle_turn(
                tenant_id="acme",
                user_id="alice",
                role="engineer",
                message="first",
            )
        )
    )
    await asyncio.wait_for(store.direct_started.wait(), timeout=1)
    conversation = (await store.list_conversations("acme", "alice"))[0]
    second = asyncio.create_task(
        _collect_turn(
            chat_b.handle_turn(
                tenant_id="acme",
                user_id="alice",
                role="engineer",
                message="second",
                conversation_id=conversation.id,
            )
        )
    )

    await asyncio.sleep(0.05)
    assert not second.done()
    assert await store.list_messages("acme", conversation.id) == []

    store.release_direct.set()
    await asyncio.wait_for(executor_entered.wait(), timeout=1)
    queued = await asyncio.wait_for(second, timeout=1)
    assert [item["type"] for item in queued] == ["queued"]
    messages = await store.list_messages("acme", conversation.id)
    assert [(item.content, item.run_id) for item in messages] == [
        ("first", messages[0].run_id),
        ("second", messages[1].run_id),
    ]
    assert messages[0].run_id is not None
    assert messages[1].run_id is not None
    assert messages[1].run_id != messages[0].run_id

    release_executor.set()
    await asyncio.wait_for(first, timeout=2)
    assert calls == ["first", "second"]


@pytest.mark.invariant("NFR-CONV-03")
@pytest.mark.invariant("US-CHAT-15")
async def test_turn_admission_rolls_back_cleanly_at_each_storage_boundary() -> None:
    class FailingClaimRelay(EventRelay):
        def set_active_run(self, tenant_id: str, conversation_id: str, run_id: str) -> None:
            raise RuntimeError("redis unavailable")

    store_before_claim = InMemoryStore()
    chat = ChatService(store_before_claim, FailingClaimRelay())
    with pytest.raises(RuntimeError, match="redis unavailable"):
        await _collect_turn(
            chat.handle_turn(
                tenant_id="acme",
                user_id="alice",
                role="engineer",
                message="must not persist",
            )
        )
    conversation = (await store_before_claim.list_conversations("acme", "alice"))[0]
    assert await store_before_claim.list_messages("acme", conversation.id) == []

    class FailingMessageStore(InMemoryStore):
        async def add_message(self, _message):
            raise RuntimeError("message store unavailable")

    relay = EventRelay()
    failing_store = FailingMessageStore()
    chat = ChatService(failing_store, relay)
    with pytest.raises(RuntimeError, match="message store unavailable"):
        await _collect_turn(
            chat.handle_turn(
                tenant_id="acme",
                user_id="alice",
                role="engineer",
                message="must roll back active",
            )
        )
    conversation = (await failing_store.list_conversations("acme", "alice"))[0]
    assert relay.active_run("acme", conversation.id) is None
    assert await failing_store.list_messages("acme", conversation.id) == []


async def _collect_turn(iterator):
    return [item async for item in iterator]


@pytest.mark.invariant("NFR-CONV-02")
async def test_redis_closed_retention_is_bounded_and_tenant_scoped() -> None:
    relay = _fake_pair(
        fakeredis.FakeServer(),
        namespace=f"retention-{uuid.uuid4().hex}",
        max_closed=1,
    )
    relay.publish("tenant-a", "same-run", {"tenant": "a"})
    relay.publish("tenant-b", "same-run", {"tenant": "b"})
    relay.close("tenant-a", "same-run")
    relay.close("tenant-b", "same-run")

    assert relay.snapshot("tenant-a", "same-run") == []
    assert relay.max_seq("tenant-a", "same-run") == 0
    assert relay.snapshot("tenant-b", "same-run") == [{"tenant": "b"}]


@pytest.mark.invariant("NFR-CONV-03")
async def test_evicted_closed_stream_keeps_a_bounded_completion_tombstone() -> None:
    relay = _fake_pair(
        fakeredis.FakeServer(),
        namespace=f"tombstone-{uuid.uuid4().hex}",
        max_closed=1,
    )
    for run_id in ("run-1", "run-2"):
        relay.publish("acme", run_id, {"type": "text_delta", "delta": run_id})
        relay.close("acme", run_id)

    assert relay.snapshot("acme", "run-1") == []
    ended = [item async for item in relay.subscribe_with_seq("acme", "run-1")]
    assert ended == []


@pytest.mark.invariant("NFR-CONV-03")
async def test_live_subscriber_fails_loudly_when_it_falls_behind_the_trim_window() -> None:
    relay = _fake_pair(
        fakeredis.FakeServer(),
        namespace=f"live-gap-{uuid.uuid4().hex}",
        backlog=2,
    )
    relay.publish("acme", "run-1", {"n": 1})
    follower = relay.subscribe_with_seq("acme", "run-1")
    assert await anext(follower) == (1, {"n": 1})
    for value in (2, 3, 4):
        relay.publish("acme", "run-1", {"n": value})

    with pytest.raises(RuntimeError, match="event_relay_live_cursor_truncated"):
        await asyncio.wait_for(anext(follower), timeout=1)


@pytest.mark.invariant("NFR-CONV-03")
async def test_conversation_lock_renews_while_a_store_write_is_slow() -> None:
    server = fakeredis.FakeServer()
    namespace = f"renew-{uuid.uuid4().hex}"
    first = RedisEventRelay(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        fake_aioredis.FakeRedis(server=server, decode_responses=True),
        namespace=namespace,
        lock_timeout_s=2,
        lock_lease_s=0.2,
    )
    second = RedisEventRelay(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        fake_aioredis.FakeRedis(server=server, decode_responses=True),
        namespace=namespace,
        lock_timeout_s=2,
        lock_lease_s=0.2,
    )
    entered = asyncio.Event()

    async def contender() -> None:
        async with second.conversation_lock("acme", "conversation"):
            entered.set()

    async with first.conversation_lock("acme", "conversation"):
        task = asyncio.create_task(contender())
        await asyncio.sleep(1.2)
        assert not entered.is_set()
    await asyncio.wait_for(task, timeout=1)
    assert entered.is_set()


@pytest.mark.invariant("NFR-CONV-03")
async def test_next_turn_never_overwrites_a_successor_after_lease_loss() -> None:
    store = InMemoryStore()
    relay = EventRelay()
    conversation = Conversation(id="conversation", tenant_id="acme", user_id="alice")
    await store.create_conversation(conversation)
    await store.add_message(
        ConversationMessage(
            id="queued",
            conversation_id=conversation.id,
            tenant_id="acme",
            role=MessageRole.USER,
            content="queued steer",
        )
    )
    relay.set_active_run("acme", conversation.id, "run-2")
    chat = ChatService(store, relay)

    result = await _next_turn(
        chat,
        SimpleNamespace(tenant_id="acme"),
        conversation,
        "run-1",
    )
    assert result is None
    assert relay.active_run("acme", conversation.id) == "run-2"
    assert (await store.list_messages("acme", conversation.id))[0].run_id is None


@pytest.mark.invariant("NFR-CONV-03")
async def test_stale_run_stops_when_active_lease_refresh_loses_ownership() -> None:
    async def executor(*, run_id, relay, **_kwargs) -> None:
        relay.publish(run_id, {"type": "text_delta", "delta": "stale"})

    relay = EventRelay()
    relay.set_active_run("acme", "conversation", "run-2")
    chat = ChatService(InMemoryStore(), relay, turn_executor=executor)
    request = SimpleNamespace(
        tenant_id="acme",
        user_id="alice",
        role="engineer",
        grants=None,
        workspace_id=None,
        scope=None,
        on_behalf_bearer=None,
        origin=None,
        model_profile_id=None,
    )
    conversation = Conversation(id="conversation", tenant_id="acme", user_id="alice")
    stream = _stream_one(chat, request, conversation, "run-1", "stale", [], None, [], None)
    assert (await anext(stream))["type"] == "message_start"
    with pytest.raises(RuntimeError, match="conversation_run_ownership_lost"):
        await anext(stream)
    assert relay.active_run("acme", conversation.id) == "run-2"


@pytest.mark.invariant("NFR-CONV-03")
def test_production_factory_refuses_an_in_memory_fallback() -> None:
    with pytest.raises(RuntimeError, match="production_event_relay_requires_redis"):
        build_event_relay(production=True)
    assert isinstance(build_event_relay(production=False), EventRelay)
    assert not isinstance(build_event_relay(production=False), RedisEventRelay)


@pytest.mark.invariant("NFR-CONV-03")
async def test_redis_relay_closes_both_clients_on_shutdown() -> None:
    sync_client = Mock()
    async_client = Mock()
    async_client.aclose = AsyncMock()
    relay = RedisEventRelay(sync_client, async_client, namespace="shutdown")

    await relay.aclose()

    async_client.aclose.assert_awaited_once()
    sync_client.close.assert_called_once()


@pytest.mark.invariant("NFR-CONV-03")
@pytest.mark.skipif(
    not os.environ.get("BOLTRIG_TEST_REDIS_URL"),
    reason="BOLTRIG_TEST_REDIS_URL is not configured",
)
async def test_real_redis_two_client_continuity() -> None:
    """Service-gated proof against Redis itself, isolated by a unique namespace."""
    url = os.environ["BOLTRIG_TEST_REDIS_URL"]
    namespace = f"acceptance-{uuid.uuid4().hex}"
    replica_a = RedisEventRelay.from_url(url, namespace=namespace)
    replica_b = RedisEventRelay.from_url(url, namespace=namespace)
    try:
        follower = replica_b.subscribe_with_seq("acceptance", "run")
        waiting = asyncio.create_task(anext(follower))
        await asyncio.sleep(0.05)
        replica_a.publish("acceptance", "run", {"type": "text_delta", "delta": "cross-replica"})
        assert await asyncio.wait_for(waiting, timeout=3) == (
            1,
            {"type": "text_delta", "delta": "cross-replica"},
        )
        replica_a.close("acceptance", "run")
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(follower), timeout=3)
    finally:
        replica_a.forget("acceptance", "run")
        await replica_a._async.aclose()  # noqa: SLF001
        await replica_b._async.aclose()  # noqa: SLF001
        replica_a._sync.close()  # noqa: SLF001
        replica_b._sync.close()  # noqa: SLF001
