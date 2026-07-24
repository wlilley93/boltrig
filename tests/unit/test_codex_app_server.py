from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet.domain import CanonicalJSON
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient

from .codex_app_server_fakes import (
    ClientFactory,
    FakeLineTransport,
    client_factory,
    initialize,
    sent,
    thread_result,
)

_CLIENT_FACTORY_FIXTURE = client_factory


def test_jsonl_codec_omits_jsonrpc_and_preserves_unknown_notifications() -> None:
    params = CanonicalJSON.from_mapping({"nested": {"ok": True}})
    line = wire.encode_request(wire.RequestMessage(7, "thread/read", params))

    assert "jsonrpc" not in line
    assert "\n" not in line
    assert wire.decode_message(line) == wire.RequestMessage(7, "thread/read", params)
    unknown = wire.decode_message('{"method":"future/event","params":{"version":2}}')
    assert isinstance(unknown, wire.NotificationMessage)
    assert unknown.method == "future/event"
    assert unknown.params.to_mapping() == {"version": 2}


def test_encode_response_answers_a_server_request_and_round_trips() -> None:
    """A client->server RESPONSE keyed to the inbound id: the exact envelope Codex
    expects when we answer item/tool/requestUserInput (id + result, no jsonrpc)."""
    result = CanonicalJSON.from_mapping({"answers": {"q1": {"answers": ["Approve"]}}})
    line = wire.encode_response(wire.ResponseMessage(request_id=0, result=result))

    assert line == '{"id":0,"result":{"answers":{"q1":{"answers":["Approve"]}}}}'
    assert "jsonrpc" not in line and "\n" not in line
    decoded = wire.decode_message(line)
    assert isinstance(decoded, wire.ResponseMessage)
    assert decoded.request_id == 0
    assert decoded.result is not None
    assert decoded.result.to_value() == {"answers": {"q1": {"answers": ["Approve"]}}}


def test_encode_response_carries_an_error_envelope() -> None:
    """The error arm: refuse a server request with {id, error}, jsonrpc omitted."""
    msg = wire.ResponseMessage(request_id=3, error=wire.RemoteErrorData(code=-32601, message="no"))
    line = wire.encode_response(msg)

    assert line == '{"error":{"code":-32601,"message":"no"},"id":3}'
    decoded = wire.decode_message(line)
    assert isinstance(decoded, wire.ResponseMessage) and decoded.error is not None
    assert decoded.error.code == -32601


@pytest.mark.parametrize(
    "line",
    [
        "",
        "[]",
        '{"jsonrpc":"2.0","id":1,"result":{}}',
        '{"id":1,"result":{},"error":{"code":1,"message":"bad"}}',
        '{"id":1,"id":2,"result":{}}',
        '{"id":true,"result":{}}',
        '{"id":1,"method":"thread/read"}',
        '{"method":"turn/started","params":[]}',
        '{"id":1,"result":NaN}',
        '{"id":1,"result":{},"extra":true}',
        '{"id":1,"result":{}}\n{"id":2,"result":{}}',
    ],
)
def test_jsonl_codec_rejects_ambiguous_or_malformed_messages(line: str) -> None:
    with pytest.raises(wire.MalformedMessageError, match="malformed"):
        wire.decode_message(line)


def test_codec_rechecks_line_bound_and_requires_valid_bound_types() -> None:
    line = '{"method":"event","params":{"value":"' + ("x" * 64) + '"}}'

    with pytest.raises(wire.MalformedMessageError):
        wire.decode_message(line, max_bytes=32)
    with pytest.raises(ValueError, match="positive integer"):
        wire.decode_message("{}", max_bytes=True)  # type: ignore[arg-type]


async def test_initialize_requires_complete_stable_object_exactly_once(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    with pytest.raises(wire.ProtocolStateError, match="initialize"):
        await client.thread_read("thr-1")

    receipt = await initialize(client, transport)

    assert receipt.payload.to_mapping()["platformOs"] == "linux"
    assert client.state is wire.ClientState.READY
    assert transport.read_limits and set(transport.read_limits) == {wire.MAX_LINE_BYTES}
    with pytest.raises(wire.ProtocolStateError, match="re-initialized"):
        await client.initialize()


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {
            "codexHome": "relative",
            "platformFamily": "unix",
            "platformOs": "linux",
            "userAgent": "x",
        },
        {
            "codexHome": "/srv/codex",
            "platformFamily": "unix",
            "platformOs": "linux",
            "userAgent": 1,
        },
    ],
)
async def test_incomplete_initialize_response_fails_and_closes_transport(
    client_factory: ClientFactory, result: object
) -> None:
    client, transport = client_factory()
    task = asyncio.create_task(client.initialize())
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    await transport.receive({"id": 1, "result": result})

    with pytest.raises(wire.MalformedMessageError):
        await task
    assert client.state is wire.ClientState.FAILED
    assert client.transport_closed


@pytest.mark.invariant("SEC-150")
async def test_read_only_lifecycle_uses_exact_monotonic_stable_shapes(
    client_factory: ClientFactory,
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)

    start_task = asyncio.create_task(
        client.thread_start(cwd="/workspace", model="gpt-5.4", developer_instructions="Bounded")
    )
    start = await sent(transport)
    assert isinstance(start, wire.RequestMessage)
    assert (start.request_id, start.method) == (2, "thread/start")
    assert start.params.to_mapping() == {
        "approvalPolicy": "never",
        "cwd": "/workspace",
        "developerInstructions": "Bounded",
        "ephemeral": True,
        "model": "gpt-5.4",
        "sandbox": "read-only",
    }
    await transport.receive({"id": 2, "result": thread_result()})
    assert (await start_task).thread_id == "thr-1"

    resume_task = asyncio.create_task(
        client.thread_resume("thr-1", cwd="/workspace", model="gpt-5.4")
    )
    resume = await sent(transport)
    assert isinstance(resume, wire.RequestMessage)
    assert (resume.request_id, resume.method) == (3, "thread/resume")
    assert resume.params.to_mapping() == {
        "approvalPolicy": "never",
        "cwd": "/workspace",
        "model": "gpt-5.4",
        "sandbox": "read-only",
        "threadId": "thr-1",
    }
    await transport.receive({"id": 3, "result": thread_result()})
    assert (await resume_task).request_id == 3

    read_task = asyncio.create_task(client.thread_read("thr-1", include_turns=True))
    read = await sent(transport)
    assert isinstance(read, wire.RequestMessage)
    assert (read.request_id, read.method) == (4, "thread/read")
    await transport.receive({"id": 4, "result": {"thread": thread_result()["thread"]}})
    assert (await read_task).thread_id == "thr-1"

    turn_task = asyncio.create_task(
        client.turn_start("thr-1", prompt="Inspect", client_user_message_id="msg-1")
    )
    turn = await sent(transport)
    assert isinstance(turn, wire.RequestMessage)
    assert (turn.request_id, turn.method) == (5, "turn/start")
    await transport.receive(
        {"id": 5, "result": {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}}
    )
    assert (await turn_task).turn_id == "turn-1"

    steer_task = asyncio.create_task(
        client.turn_steer(
            "thr-1",
            expected_turn_id="turn-1",
            prompt="More evidence",
            client_user_message_id="msg-2",
        )
    )
    steer = await sent(transport)
    assert isinstance(steer, wire.RequestMessage)
    assert steer.params.to_mapping()["expectedTurnId"] == "turn-1"
    await transport.receive({"id": 6, "result": {"turnId": "turn-1"}})
    assert (await steer_task).turn_id == "turn-1"

    interrupt_task = asyncio.create_task(client.turn_interrupt("thr-1", "turn-1"))
    interrupt = await sent(transport)
    assert isinstance(interrupt, wire.RequestMessage)
    assert interrupt.params.to_mapping() == {"threadId": "thr-1", "turnId": "turn-1"}
    await transport.receive({"id": 7, "result": {}})
    assert (await interrupt_task).request_id == 7


@pytest.mark.parametrize(
    ("sandbox", "approval"),
    [
        ("danger-full-access", "never"),
        ("workspace-write", "never"),
        ("read-only", "on-request"),
        ("read-only", "untrusted"),
        (True, "never"),
        ("read-only", None),
    ],
)
async def test_thread_start_runtime_rejects_non_read_only_policy(
    client_factory: ClientFactory, sandbox: object, approval: object
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)

    with pytest.raises(ValueError, match="first Codex client"):
        await client.thread_start(
            cwd="/workspace",
            sandbox=sandbox,  # type: ignore[arg-type]
            approval_policy=approval,  # type: ignore[arg-type]
        )
    assert transport.sent.empty()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_timeout": True},
        {"max_pending": True},
        {"max_notifications": 0},
        {"max_notification_bytes": -1},
        {"response_history": 1.5},
        {"max_tombstones": "1"},
        {"client_name": 1},
    ],
)
def test_client_configuration_types_and_bounds_are_exact(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        CodexAppServerClient(FakeLineTransport(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        {"approvalPolicy": "on-request"},
        {"cwd": "/other"},
        {"model": "other"},
        {"sandbox": {"type": "workspaceWrite"}},
        {"sandbox": {"type": "readOnly", "networkAccess": True}},
        {"thread": {"cwd": "/other"}},
        {"thread": {"ephemeral": False}},
    ],
)
async def test_thread_start_rejects_mismatched_effective_policy(
    client_factory: ClientFactory, mutation: dict[str, object]
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(client.thread_start(cwd="/workspace", model="gpt-5.4"))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    response = thread_result()
    for key, value in mutation.items():
        if key == "thread" and isinstance(value, dict):
            response["thread"].update(value)  # type: ignore[union-attr]
        else:
            response[key] = value
    await transport.receive({"id": request.request_id, "result": response})

    with pytest.raises(wire.MalformedMessageError):
        await task
    assert client.state is wire.ClientState.FAILED


async def test_resume_read_and_steer_reject_wrong_correlated_entity_ids(
    client_factory: ClientFactory,
) -> None:
    cases = (
        (
            lambda client: client.thread_resume("thr-1", cwd="/workspace", model="gpt-5.4"),
            thread_result("thr-other"),
        ),
        (
            lambda client: client.thread_read("thr-1"),
            {"thread": thread_result("thr-other")["thread"]},
        ),
        (
            lambda client: client.turn_steer(
                "thr-1", expected_turn_id="turn-1", prompt="x", client_user_message_id="msg"
            ),
            {"turnId": "turn-other"},
        ),
    )
    for call, response in cases:
        client, transport = client_factory()
        await initialize(client, transport)
        task = asyncio.create_task(call(client))
        request = await sent(transport)
        assert isinstance(request, wire.RequestMessage)
        await transport.receive({"id": request.request_id, "result": response})
        with pytest.raises(wire.MalformedMessageError):
            await task


@pytest.mark.invariant("SEC-150")
@pytest.mark.invariant("CODEX-APPROVAL-1")
@pytest.mark.invariant("CODEX-APPROVAL-3")
async def test_a_tool_approval_is_answered_explicitly_and_the_pump_survives(
    client_factory: ClientFactory,
) -> None:
    """[2026] VJS-COUNTY 12: codex's item/tool/requestUserInput is ANSWERED
    explicitly (an approve response written to the wire, never left to codex's
    autoResolutionMs timer), and the single-reader pump keeps running."""
    from boltrig.fleet.infrastructure.codex_server_request_handler import (
        answer_server_request,
    )

    client, transport = client_factory(server_request_handler=answer_server_request)
    await initialize(client, transport)
    await transport.receive({
        "id": 7, "method": "item/tool/requestUserInput",
        "params": {
            "threadId": "t", "turnId": "u", "itemId": "call_9",
            "questions": [{
                "id": "mcp_tool_call_approval_call_9", "header": "Approve app tool call?",
                "question": 'Allow the boltrig MCP server to run tool "opbox.matter.list"?',
                "isOther": False, "isSecret": False,
                "options": [{"label": "Approve", "description": "run"},
                            {"label": "Decline", "description": "no"}],
            }],
            "autoResolutionMs": None,
        },
    })

    # The pump survives (no crash, no notification), and an explicit approve
    # response for id 7 was written back to codex.
    with pytest.raises(TimeoutError):
        await client.next_notification(timeout=0.2)
    assert client.state is not wire.ClientState.FAILED
    written: list[str] = []
    while not transport.sent.empty():
        written.append(transport.sent.get_nowait())
    approve = [line for line in written if '"id":7' in line and '"result"' in line]
    assert approve, "an explicit approve response must be written for the tool approval"
    assert '"Approve"' in approve[0]


@pytest.mark.invariant("CODEX-APPROVAL-1")
async def test_an_unhandled_server_request_is_refused_typed_and_never_crashes_the_pump(
    client_factory: ClientFactory,
) -> None:
    """[2026] VJS-COUNTY 12 + AGENTS.md graceful degradation: a server-initiated
    request must be ANSWERED with a typed error (absent a handler), not raise
    UnexpectedServerRequestError and crash the single-reader pump. Neither the
    peer method nor its params may leak into the response."""
    client, transport = client_factory()
    await initialize(client, transport)
    peer_method = "approval/request/SECRET"
    await transport.receive({"id": 50, "method": peer_method, "params": {"token": "SECRET"}})

    # The pump SURVIVES: no notification arrives, and it does NOT raise the old
    # UnexpectedServerRequestError - it simply times out with nothing to deliver.
    with pytest.raises(TimeoutError):
        await client.next_notification(timeout=0.2)
    assert client.state is not wire.ClientState.FAILED

    # A typed error response was written back, keyed to the same id, leaking
    # neither the peer method nor its params.
    written: list[str] = []
    while not transport.sent.empty():
        written.append(transport.sent.get_nowait())
    assert any('"id":50' in line and '"error"' in line for line in written)
    assert all("SECRET" not in line and peer_method not in line for line in written)


@pytest.mark.parametrize(
    "call",
    [
        lambda client: client.thread_start(cwd="relative"),
        lambda client: client.thread_start(cwd=1),
        lambda client: client.thread_start(cwd="/workspace/"),
        lambda client: client.thread_start(cwd="/workspace/../other"),
        lambda client: client.thread_read(1),
        lambda client: client.thread_read("thr-1", include_turns=1),
        lambda client: client.turn_start("thr-1", prompt=1, client_user_message_id="m"),
        lambda client: client.turn_start(
            "thr-1", prompt="x", client_user_message_id="m", output_schema={}
        ),
    ],
)
async def test_runtime_arguments_are_validated_exactly(
    client_factory: ClientFactory, call: object
) -> None:
    client, transport = client_factory()
    await initialize(client, transport)

    with pytest.raises((TypeError, ValueError)):
        await call(client)  # type: ignore[operator]
    assert transport.sent.empty()


async def test_remote_error_does_not_echo_peer_payload(client_factory: ClientFactory) -> None:
    client, transport = client_factory()
    await initialize(client, transport)
    task = asyncio.create_task(client.thread_read("thr-1"))
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    await transport.receive(
        {
            "id": request.request_id,
            "error": {"code": -32001, "message": "SECRET", "data": {"token": "SECRET"}},
        }
    )

    with pytest.raises(wire.CodexRemoteError) as caught:
        await task
    assert "SECRET" not in str(caught.value)
    assert client.state is wire.ClientState.READY
