from __future__ import annotations

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

from .codex_app_server_fakes import thread_payload
from .codex_runtime_fakes import admission

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"


def _notification(method: str, params: dict[str, object]) -> wire.NotificationMessage:
    return wire.NotificationMessage(
        method,
        CanonicalJSON.from_mapping(cast(dict[str, JSONValue], params)),
    )


def _translator() -> tuple[CodexEventTranslator, RuntimeThreadRef, RuntimeTurnRef]:
    exact = admission()
    thread = RuntimeThreadRef(exact.assignment, "codex_app_server", "thread-1")
    turn = RuntimeTurnRef(thread, "turn-1")
    translator = CodexEventTranslator(
        assignment=exact.assignment,
        thread=thread,
        cwd=exact.layout.workspace.as_posix(),
        max_native_concurrent=1,
        max_native_total=3,
        max_native_depth=2,
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

    assert started.payload.to_mapping()["observation"] == "native_thread_started"
    assert closed.payload.to_mapping()["observation"] == "native_thread_closed"
    assert restarted.kind is RuntimeEventKind.UNKNOWN


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
