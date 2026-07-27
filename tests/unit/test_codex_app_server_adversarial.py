from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet.infrastructure import codex_protocol as wire

from .codex_app_server_fakes import (
    ClientFactory,
    client_factory,
    initialize,
    relax_request_timeout,
    sent,
    thread_result,
)

_CLIENT_FACTORY_FIXTURE = client_factory


async def test_out_of_order_live_responses_remain_correlated(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    first_task = asyncio.create_task(client.thread_read("thr-first"))
    second_task = asyncio.create_task(client.thread_read("thr-second"))
    first = await sent(transport)
    second = await sent(transport)
    assert isinstance(first, wire.RequestMessage)
    assert isinstance(second, wire.RequestMessage)

    await transport.receive(
        {"id": second.request_id, "result": {"thread": thread_result("thr-second")["thread"]}}
    )
    await transport.receive(
        {"id": first.request_id, "result": {"thread": thread_result("thr-first")["thread"]}}
    )

    assert (await first_task).thread_id == "thr-first"
    assert (await second_task).thread_id == "thr-second"


async def test_pending_request_count_is_bounded(client_factory: ClientFactory) -> None:
    client, transport = client_factory(max_pending=1)
    await initialize(client, transport)
    first_task = asyncio.create_task(client.thread_read("thr-first"))
    first = await sent(transport)
    assert isinstance(first, wire.RequestMessage)

    with pytest.raises(wire.PendingRequestsFullError):
        await client.thread_read("thr-second")
    await transport.receive(
        {"id": first.request_id, "result": {"thread": thread_result("thr-first")["thread"]}}
    )
    assert (await first_task).thread_id == "thr-first"


async def test_oversized_unsent_request_releases_its_pending_slot(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(max_pending=1)
    await initialize(client, transport)

    with pytest.raises(wire.MalformedMessageError, match="line limit"):
        await client.turn_start(
            "thr-1",
            prompt="x" * wire.MAX_LINE_BYTES,
            client_user_message_id="msg-oversized",
        )

    live_task = asyncio.create_task(client.thread_read("thr-live"))
    live = await sent(transport)
    assert isinstance(live, wire.RequestMessage)
    await transport.receive(
        {"id": live.request_id, "result": {"thread": thread_result("thr-live")["thread"]}}
    )
    assert (await live_task).thread_id == "thr-live"
    assert client.state is wire.ClientState.READY


async def test_first_late_timeout_response_is_discarded_but_duplicate_fails(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(request_timeout=0.015)
    await initialize(client, transport)
    slow_task = asyncio.create_task(client.thread_read("thr-slow"))
    slow = await sent(transport)
    assert isinstance(slow, wire.RequestMessage)
    with pytest.raises(wire.RequestTimeoutError):
        await slow_task

    # The 15ms budget has now done its only job, which was to expire `slow_task`.
    # Leaving it in place would make the SUCCESS leg below race the event loop:
    # under a full-suite run `live_task` would time out too, and the test would
    # fail claiming the client had dropped a live response it had actually
    # delivered. Observed once in five `make python-quality` runs on 2026-07-27.
    relax_request_timeout(client)

    live_task = asyncio.create_task(client.thread_read("thr-live"))
    live = await sent(transport)
    assert isinstance(live, wire.RequestMessage)
    late = {"id": slow.request_id, "result": {"thread": thread_result("thr-slow")["thread"]}}
    await transport.receive(late)
    await transport.receive(
        {"id": live.request_id, "result": {"thread": thread_result("thr-live")["thread"]}}
    )

    assert (await live_task).thread_id == "thr-live"
    assert client.state is wire.ClientState.READY
    await transport.receive(late)
    with pytest.raises(wire.DuplicateResponseIdError):
        await client.next_notification(timeout=0.2)


async def test_first_late_cancelled_response_does_not_harm_other_live_request(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    cancelled_task = asyncio.create_task(client.thread_read("thr-cancelled"))
    cancelled = await sent(transport)
    assert isinstance(cancelled, wire.RequestMessage)
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task

    live_task = asyncio.create_task(client.thread_read("thr-live"))
    live = await sent(transport)
    assert isinstance(live, wire.RequestMessage)
    await transport.receive(
        {
            "id": cancelled.request_id,
            "result": {"thread": thread_result("thr-cancelled")["thread"]},
        }
    )
    await transport.receive(
        {"id": live.request_id, "result": {"thread": thread_result("thr-live")["thread"]}}
    )

    assert (await live_task).thread_id == "thr-live"
    assert client.state is wire.ClientState.READY


async def test_tombstone_memory_is_bounded_and_evicted_late_id_fails_closed(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(request_timeout=0.01, max_tombstones=1)
    await initialize(client, transport)
    requests: list[wire.RequestMessage] = []
    for name in ("thr-one", "thr-two"):
        task = asyncio.create_task(client.thread_read(name))
        request = await sent(transport)
        assert isinstance(request, wire.RequestMessage)
        requests.append(request)
        with pytest.raises(wire.RequestTimeoutError):
            await task

    await transport.receive(
        {"id": requests[0].request_id, "result": {"thread": thread_result("thr-one")["thread"]}}
    )
    with pytest.raises(wire.UnknownResponseIdError):
        await client.next_notification(timeout=0.2)


async def test_initialize_cancellation_fails_joins_reader_and_closes_transport(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    task = asyncio.create_task(client.initialize())
    assert isinstance(await sent(transport), wire.RequestMessage)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.state is wire.ClientState.FAILED
    assert client.transport_closed
    assert transport.closed


async def test_initialize_cancellation_during_write_never_sticks_initializing(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    transport.write_gate = asyncio.Event()
    task = asyncio.create_task(client.initialize())
    await asyncio.wait_for(transport.write_started.wait(), timeout=0.2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.state is wire.ClientState.FAILED
    assert client.transport_closed


async def test_notification_byte_budget_decrements_when_drained(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(max_notification_bytes=256)
    await initialize(client, transport)
    await transport.receive({"method": "event/one", "params": {"text": "x" * 32}})
    for _ in range(10):
        if client.queued_notification_bytes:
            break
        await asyncio.sleep(0)

    assert 0 < client.queued_notification_bytes <= 256
    assert (await client.next_notification()).method == "event/one"
    assert client.queued_notification_bytes == 0


async def test_notification_total_byte_budget_fails_closed(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(max_notifications=8, max_notification_bytes=80)
    await initialize(client, transport)
    await transport.receive({"method": "event/one", "params": {"text": "x" * 40}})

    with pytest.raises(wire.NotificationQueueFullError):
        await client.next_notification(timeout=0.2)
    assert client.state is wire.ClientState.FAILED


async def test_notification_count_budget_fails_after_buffer_is_drained(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(max_notifications=1)
    await initialize(client, transport)
    await transport.receive({"method": "event/one", "params": {}})
    await transport.receive({"method": "event/two", "params": {}})
    for _ in range(10):
        if client.state is wire.ClientState.FAILED:
            break
        await asyncio.sleep(0)

    assert (await client.next_notification()).method == "event/one"
    with pytest.raises(wire.NotificationQueueFullError):
        await client.next_notification(timeout=0.2)


async def test_write_duration_and_write_lock_acquisition_are_bounded(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory(request_timeout=0.015)
    await initialize(client, transport)
    transport.write_started.clear()
    transport.write_gate = asyncio.Event()
    first = asyncio.create_task(client.thread_read("thr-first"))
    await asyncio.wait_for(transport.write_started.wait(), timeout=0.2)
    second = asyncio.create_task(client.thread_read("thr-second"))

    with pytest.raises(wire.RequestTimeoutError):
        await first
    with pytest.raises(wire.RequestTimeoutError):
        await second
    assert client.state is wire.ClientState.READY


async def test_transport_read_bound_is_passed_before_every_frame(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(client.thread_read("thr-1"))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    await transport.receive(
        {"id": request.request_id, "result": {"thread": thread_result()["thread"]}}
    )
    await task

    assert transport.read_limits
    assert set(transport.read_limits) == {wire.MAX_LINE_BYTES}


async def test_close_failure_is_observable_and_retriable(client_factory: ClientFactory) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    transport.close_failures = 1

    with pytest.raises(wire.CodexTransportError) as caught:
        await client.aclose()
    assert "SECRET" not in str(caught.value)
    assert client.state is wire.ClientState.CLOSED
    assert not client.transport_closed

    await client.aclose()
    assert client.transport_closed
    assert transport.close_calls == 2


async def test_transport_exit_fails_pending_request_without_leaking_detail(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(client.thread_read("thr-1"))
    assert isinstance(await sent(transport), wire.RequestMessage)

    await transport.receive(RuntimeError("SECRET process stderr"))

    with pytest.raises(wire.CodexTransportError) as caught:
        await task
    assert "SECRET" not in str(caught.value)
    assert client.state is wire.ClientState.FAILED
