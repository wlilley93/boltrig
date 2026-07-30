from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft7Validator

from boltrig.fleet.domain import (
    CanonicalJSON,
    JSONValue,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_runtime_events import (
    CodexEventTranslator,
    CodexRuntimeProtocolError,
)
from boltrig.fleet.infrastructure.codex_runtime_actor import (
    CodexRuntimeActor,
    CodexRuntimeTerminal,
)

from .codex_app_server_fakes import thread_payload
from .codex_runtime_fakes import FakeCodexClient, admission

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"


def _notification(method: str, params: dict[str, object]) -> wire.NotificationMessage:
    return wire.NotificationMessage(
        method,
        CanonicalJSON.from_mapping(cast(dict[str, JSONValue], params)),
    )


def _translator(
    *,
    limits: tuple[int, int, int] = (1, 3, 2),
) -> tuple[CodexEventTranslator, RuntimeThreadRef, RuntimeTurnRef]:
    exact = admission()
    thread = RuntimeThreadRef(exact.assignment, "codex_app_server", "thread-1")
    turn = RuntimeTurnRef(thread, "turn-1")
    translator = CodexEventTranslator(
        assignment=exact.assignment,
        thread=thread,
        cwd=exact.layout.workspace.as_posix(),
        max_native_concurrent=limits[0],
        max_native_total=limits[1],
        max_native_depth=limits[2],
        model_id="gpt-5.2-codex",
        reasoning_effort="high",
    )
    translator.translate(
        _notification(
            "thread/started",
            {"thread": thread_payload("thread-1", cwd=exact.layout.workspace.as_posix())},
        )
    )
    translator.bind_turn(turn)
    return translator, thread, turn


def _stable_fixtures() -> list[dict[str, object]]:
    cwd = "/srv/boltrig/cells/cell-1/workspace"
    thread = thread_payload("thread-1", cwd=cwd)
    turn = {"id": "turn-1", "items": [], "status": "inProgress"}
    item = {"id": "item-1", "text": "sensitive content", "type": "agentMessage"}
    return [
        {"method": "thread/started", "params": {"thread": thread}},
        {"method": "turn/started", "params": {"threadId": "thread-1", "turn": turn}},
        {
            "method": "item/started",
            "params": {
                "item": item,
                "startedAtMs": 1,
                "threadId": "thread-1",
                "turnId": "turn-1",
            },
        },
        {
            "method": "item/completed",
            "params": {
                "completedAtMs": 2,
                "item": item,
                "threadId": "thread-1",
                "turnId": "turn-1",
            },
        },
        {
            "method": "error",
            "params": {
                "error": {"message": "sensitive error"},
                "threadId": "thread-1",
                "turnId": "turn-1",
                "willRetry": False,
            },
        },
        {"method": "warning", "params": {"message": "sensitive warning"}},
        {"method": "thread/closed", "params": {"threadId": "native-1"}},
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "items": [], "status": "completed"},
            },
        },
        {
            "method": "item/started",
            "params": {
                "item": {
                    "agentsStates": {"native-1": {"status": "running"}},
                    "id": "collab-1", "receiverThreadIds": ["native-1"],
                    "senderThreadId": "thread-1", "status": "inProgress",
                    "tool": "spawnAgent", "type": "collabAgentToolCall",
                },
                "startedAtMs": 3, "threadId": "thread-1", "turnId": "turn-1",
            },
        },
        {
            "method": "item/started",
            "params": {
                "item": {
                    "agentPath": "agents/researcher", "agentThreadId": "native-1",
                    "id": "activity-1", "kind": "started", "type": "subAgentActivity",
                },
                "startedAtMs": 4, "threadId": "thread-1", "turnId": "turn-1",
            },
        },
    ]


def test_translated_lifecycle_fixtures_are_exact_checked_01443_notifications() -> None:
    bundle = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = bundle["definitions"]
    schema = {**definitions["ServerNotification"], "definitions": definitions}
    validator = Draft7Validator(schema)

    for fixture in _stable_fixtures():
        validator.validate(fixture)


def test_known_notifications_retain_only_bounded_lifecycle_metadata() -> None:
    translator, _thread, _turn = _translator()
    events = [
        translator.translate(_notification(fixture["method"], fixture["params"]))  # type: ignore[arg-type]
        for fixture in _stable_fixtures()[1:6]
    ]

    assert [event.kind for event in events] == [
        RuntimeEventKind.TURN_STARTED,
        RuntimeEventKind.ITEM_STARTED,
        RuntimeEventKind.ITEM_COMPLETED,
        RuntimeEventKind.ERROR,
        RuntimeEventKind.WARNING,
    ]
    retained = repr([(event.item_id, event.payload.to_mapping()) for event in events])
    assert "sensitive" not in retained


def test_unknown_notification_hashes_method_and_drops_all_params() -> None:
    translator, _thread, _turn = _translator()

    event = translator.translate(
        _notification("item/agentMessage/delta", {"delta": "TOP-SECRET"})
    )

    assert event.kind is RuntimeEventKind.UNKNOWN
    assert set(event.payload.to_mapping()) == {"method_digest"}
    assert "TOP-SECRET" not in repr(event)


def test_native_observation_tripwire_tracks_active_parent_ordering() -> None:
    translator, thread, _turn = _translator()
    first = thread_payload("native-1", cwd="/srv/boltrig/cells/cell-1/workspace")
    first["parentThreadId"] = thread.thread_id
    second = thread_payload("native-2", cwd="/srv/boltrig/cells/cell-1/workspace")
    second["parentThreadId"] = thread.thread_id

    started = translator.translate(_notification("thread/started", {"thread": first}))
    with pytest.raises(CodexRuntimeProtocolError, match="observation tripwire"):
        translator.translate(_notification("thread/started", {"thread": second}))
    closed = translator.translate(
        _notification("thread/closed", {"threadId": "native-1"})
    )
    restarted = translator.translate(_notification("thread/started", {"thread": second}))

    assert started.kind is RuntimeEventKind.NATIVE_SUBAGENT_STARTED
    assert closed.kind is RuntimeEventKind.NATIVE_SUBAGENT_COMPLETED
    assert restarted.kind is RuntimeEventKind.NATIVE_SUBAGENT_STARTED
    assert started.payload.to_mapping()["native_thread_ref"] != "native-1"
    assert closed.payload.to_mapping()["native_thread_ref"] == (
        started.payload.to_mapping()["native_thread_ref"]
    )


@pytest.mark.invariant("SEC-159")
def test_root_completion_requires_the_observed_native_tree_to_be_drained() -> None:
    translator, thread, turn = _translator()
    translator.translate(
        _notification(
            "turn/started",
            {"threadId": thread.thread_id, "turn": _turn_value(turn, "inProgress")},
        )
    )
    child = thread_payload("native-1", cwd="/srv/boltrig/cells/cell-1/workspace")
    child["parentThreadId"] = thread.thread_id
    translator.translate(_notification("thread/started", {"thread": child}))

    with pytest.raises(CodexRuntimeProtocolError, match="tree was not drained"):
        translator.translate(
            _notification(
                "turn/completed",
                {"threadId": thread.thread_id, "turn": _turn_value(turn, "completed")},
            )
        )

    translator.translate(
        _notification("thread/closed", {"threadId": "native-1"})
    )
    completed = translator.translate(
        _notification(
            "turn/completed",
            {"threadId": thread.thread_id, "turn": _turn_value(turn, "completed")},
        )
    )

    assert completed.kind is RuntimeEventKind.TURN_COMPLETED


@pytest.mark.asyncio
@pytest.mark.invariant("SEC-159")
async def test_native_lifetime_expiry_terminates_the_phase_before_completion() -> None:
    translator, thread, _turn = _translator()
    client = FakeCodexClient()
    terminals: list[CodexRuntimeTerminal] = []
    terminal_seen = asyncio.Event()

    async def on_terminal(
        _actor: CodexRuntimeActor, terminal: CodexRuntimeTerminal
    ) -> None:
        terminals.append(terminal)
        terminal_seen.set()
        await client.notify("warning", {"message": "terminal wake"})

    actor = CodexRuntimeActor(
        client=cast(object, client),  # type: ignore[arg-type]
        translator=translator,
        on_terminal=on_terminal,
        max_buffered_events=8,
        native_subagent_lifetime_seconds=0.01,
    )
    actor.start()
    child = thread_payload("native-1", cwd="/srv/boltrig/cells/cell-1/workspace")
    child["parentThreadId"] = thread.thread_id
    await client.notify("thread/started", {"thread": child})

    await asyncio.wait_for(terminal_seen.wait(), timeout=1)
    assert terminals == [
        CodexRuntimeTerminal("limit", "Codex native subagent lifetime exceeded")
    ]
    assert actor.terminal == terminals[0]
    assert actor.pump_task is not None
    await asyncio.wait_for(actor.pump_task, timeout=1)


@pytest.mark.asyncio
async def test_native_lifetime_timer_is_cancelled_when_the_tree_drains() -> None:
    translator, thread, _turn = _translator()
    client = FakeCodexClient()

    async def on_terminal(
        _actor: CodexRuntimeActor, _terminal: CodexRuntimeTerminal
    ) -> None:
        await client.notify("warning", {"message": "terminal wake"})

    actor = CodexRuntimeActor(
        client=cast(object, client),  # type: ignore[arg-type]
        translator=translator,
        on_terminal=on_terminal,
        max_buffered_events=8,
        native_subagent_lifetime_seconds=0.02,
    )
    actor.start()
    child = thread_payload("native-1", cwd="/srv/boltrig/cells/cell-1/workspace")
    child["parentThreadId"] = thread.thread_id
    await client.notify("thread/started", {"thread": child})
    await client.notify("thread/closed", {"threadId": "native-1"})
    await asyncio.sleep(0.05)

    assert actor.terminal is None
    await actor.fail(CodexRuntimeTerminal("closed", "Codex thread closed"))
    assert actor.pump_task is not None
    await asyncio.wait_for(actor.pump_task, timeout=1)


def test_collab_items_emit_bounded_structured_activity_without_content() -> None:
    translator, thread, turn = _translator()
    translator.translate(
        _notification(
            "turn/started",
            {"threadId": thread.thread_id, "turn": _turn_value(turn, "inProgress")},
        )
    )
    item: dict[str, object] = {
        "agentsStates": {
            "native-1": {"message": "SECRET CHILD OUTPUT", "status": "running"},
        },
        "id": "collab-1",
        "model": "gpt-5.2-codex",
        "prompt": "SECRET CHILD PROMPT",
        "reasoningEffort": "high",
        "receiverThreadIds": ["native-1"],
        "senderThreadId": thread.thread_id,
        "status": "inProgress",
        "tool": "spawnAgent",
        "type": "collabAgentToolCall",
    }
    started = translator.translate(
        _notification(
            "item/started",
            {
                "item": item,
                "startedAtMs": 1,
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
            },
        )
    )
    item["status"] = "completed"
    completed = translator.translate(
        _notification(
            "item/completed",
            {
                "completedAtMs": 2,
                "item": item,
                "threadId": thread.thread_id,
                "turnId": turn.turn_id,
            },
        )
    )

    assert started.kind is RuntimeEventKind.NATIVE_SUBAGENT_ACTIVITY
    assert completed.kind is RuntimeEventKind.NATIVE_SUBAGENT_ACTIVITY
    payload = completed.payload.to_mapping()
    assert payload["action"] == "spawnAgent"
    assert payload["lifecycle"] == "completed"
    assert payload["native_sender_ref"] == "root"
    assert payload["native_receiver_refs"] != ["native-1"]
    assert "SECRET" not in repr(payload)
    assert "gpt-5.2-codex" not in repr(payload)


def test_collab_items_fail_closed_when_native_agents_are_disabled_or_widen_model() -> None:
    for limits, model in (
        ((0, 0, 0), "gpt-5.2-codex"),
        ((1, 3, 2), "different/model"),
    ):
        translator, thread, turn = _translator(limits=limits)
        translator.translate(
            _notification(
                "turn/started",
                {"threadId": thread.thread_id, "turn": _turn_value(turn, "inProgress")},
            )
        )
        item = {
            "agentsStates": {},
            "id": "collab-1",
            "model": model,
            "prompt": "hidden",
            "reasoningEffort": "high",
            "receiverThreadIds": ["native-1"],
            "senderThreadId": thread.thread_id,
            "status": "inProgress",
            "tool": "spawnAgent",
            "type": "collabAgentToolCall",
        }
        expected = "not admitted" if limits == (0, 0, 0) else "model ceiling"
        with pytest.raises(CodexRuntimeProtocolError, match=expected):
            translator.translate(
                _notification(
                    "item/started",
                    {
                        "item": item,
                        "startedAtMs": 1,
                        "threadId": thread.thread_id,
                        "turnId": turn.turn_id,
                    },
                )
            )


@pytest.mark.parametrize(
    "params",
    [
        {"threadId": "other", "turn": {"id": "turn-1", "items": [], "status": "inProgress"}},
        {"threadId": "thread-1", "turn": {"id": "other", "items": [], "status": "inProgress"}},
    ],
)
def test_known_turn_notification_rejects_thread_or_turn_mismatch(
    params: dict[str, object],
) -> None:
    translator, _thread, _turn = _translator()

    with pytest.raises(CodexRuntimeProtocolError):
        translator.translate(_notification("turn/started", params))


def test_duplicate_root_or_turn_lifecycle_is_rejected() -> None:
    translator, thread, turn = _translator()
    root = thread_payload(thread.thread_id, cwd="/srv/boltrig/cells/cell-1/workspace")
    started: dict[str, object] = {
        "threadId": thread.thread_id,
        "turn": _turn_value(turn, "inProgress"),
    }

    with pytest.raises(CodexRuntimeProtocolError, match="native parent"):
        translator.translate(_notification("thread/started", {"thread": root}))
    translator.translate(_notification("turn/started", started))
    with pytest.raises(CodexRuntimeProtocolError, match="started turn"):
        translator.translate(_notification("turn/started", started))


def test_turn_and_item_events_require_strict_start_completion_order() -> None:
    translator, thread, turn = _translator()
    completed: dict[str, object] = {
        "threadId": thread.thread_id,
        "turn": _turn_value(turn, "completed"),
    }
    item: dict[str, object] = {
        "completedAtMs": 1,
        "item": {"id": "item-1", "type": "agentMessage"},
        "threadId": thread.thread_id,
        "turnId": turn.turn_id,
    }

    with pytest.raises(CodexRuntimeProtocolError, match="still in progress"):
        translator.translate(_notification("turn/completed", completed))
    with pytest.raises(CodexRuntimeProtocolError, match="preceded its turn"):
        translator.translate(_notification("item/completed", item))


def test_items_are_unique_type_stable_and_closed_before_turn_completion() -> None:
    translator, thread, turn = _translator()
    translator.translate(
        _notification(
            "turn/started",
            {"threadId": thread.thread_id, "turn": _turn_value(turn, "inProgress")},
        )
    )
    started: dict[str, object] = {
        "item": {"id": "item-1", "type": "agentMessage"},
        "startedAtMs": 1,
        "threadId": thread.thread_id,
        "turnId": turn.turn_id,
    }
    translator.translate(_notification("item/started", started))

    with pytest.raises(CodexRuntimeProtocolError, match="duplicate"):
        translator.translate(_notification("item/started", started))
    with pytest.raises(CodexRuntimeProtocolError, match="still in progress"):
        translator.translate(
            _notification(
                "turn/completed",
                {"threadId": thread.thread_id, "turn": _turn_value(turn, "completed")},
            )
        )
    drifted = {
        "completedAtMs": 2,
        "item": {"id": "item-1", "type": "reasoning"},
        "threadId": thread.thread_id,
        "turnId": turn.turn_id,
    }
    with pytest.raises(CodexRuntimeProtocolError, match="matching active start"):
        translator.translate(_notification("item/completed", drifted))


def test_closed_native_parent_cannot_emit_or_parent_later_work() -> None:
    translator, thread, _turn = _translator()
    native = thread_payload("native-1", cwd="/srv/boltrig/cells/cell-1/workspace")
    native["parentThreadId"] = thread.thread_id
    child = thread_payload("native-child", cwd="/srv/boltrig/cells/cell-1/workspace")
    child["parentThreadId"] = "native-1"
    translator.translate(_notification("thread/started", {"thread": native}))
    translator.translate(_notification("thread/closed", {"threadId": "native-1"}))

    with pytest.raises(CodexRuntimeProtocolError, match="active phase tree"):
        translator.translate(_notification("thread/started", {"thread": child}))
    with pytest.raises(CodexRuntimeProtocolError, match="active phase tree"):
        translator.translate(
            _notification("warning", {"message": "hidden", "threadId": "native-1"})
        )


def _turn_value(turn: RuntimeTurnRef, status: str) -> dict[str, object]:
    return {"id": turn.turn_id, "items": [], "status": status}


def test_agent_message_text_is_captured_for_readback_but_never_in_the_event() -> None:
    # The read-back seam (read_turn_output) needs the answer, but events() must stay
    # a content-free ledger: the text is captured on the translator, never emitted.
    translator, _thread, _turn = _translator()
    translator.translate(
        _notification(
            "turn/started",
            {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "items": [], "status": "inProgress"},
            },
        )
    )
    item = {"id": "item-1", "text": "the answer is 4", "type": "agentMessage"}
    translator.translate(
        _notification(
            "item/started",
            {"item": item, "startedAtMs": 1, "threadId": "thread-1", "turnId": "turn-1"},
        )
    )
    event = translator.translate(
        _notification(
            "item/completed",
            {"completedAtMs": 2, "item": item, "threadId": "thread-1", "turnId": "turn-1"},
        )
    )
    assert translator.latest_agent_message_text == "the answer is 4"
    assert "the answer is 4" not in repr(event.payload.to_mapping())
