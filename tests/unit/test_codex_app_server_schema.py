from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator

from .codex_app_server_fakes import INITIALIZE_RESULT, thread_payload, thread_result

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json"


def _bundle() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(definition_name: str, instance: object) -> None:
    bundle = _bundle()
    definitions = bundle["definitions"]
    assert isinstance(definitions, dict)
    definition = definitions[definition_name]
    assert isinstance(definition, dict)
    schema = {**definition, "definitions": definitions}
    Draft7Validator(schema).validate(instance)


def test_initialize_fixtures_match_stable_01443_required_shape() -> None:
    params = {
        "clientInfo": {"name": "boltrig", "title": "Boltrig", "version": "0.1.0"},
        "capabilities": {"experimentalApi": False},
    }

    _validate("InitializeParams", params)
    assert set(INITIALIZE_RESULT) == {
        "codexHome",
        "platformFamily",
        "platformOs",
        "userAgent",
    }
    assert str(INITIALIZE_RESULT["codexHome"]).startswith("/")
    assert all(type(INITIALIZE_RESULT[key]) is str for key in INITIALIZE_RESULT)


def test_thread_start_fixtures_validate_against_checked_in_schema() -> None:
    params = {
        "approvalPolicy": "never",
        "cwd": "/workspace",
        "developerInstructions": "Bounded",
        "ephemeral": True,
        "model": "gpt-5.4",
        "sandbox": "read-only",
    }

    _validate("ThreadStartParams", params)
    _validate("ThreadStartResponse", thread_result())


def test_thread_resume_fixtures_reassert_read_only_policy_and_validate() -> None:
    params = {
        "approvalPolicy": "never",
        "cwd": "/workspace",
        "model": "gpt-5.4",
        "sandbox": "read-only",
        "threadId": "thr-1",
    }

    _validate("ThreadResumeParams", params)
    _validate("ThreadResumeResponse", thread_result())


def test_thread_read_fixtures_validate_requested_id_shape() -> None:
    _validate("ThreadReadParams", {"includeTurns": True, "threadId": "thr-1"})
    _validate("ThreadReadResponse", {"thread": thread_payload()})


def test_turn_start_fixtures_validate_against_checked_in_schema() -> None:
    params = {
        "clientUserMessageId": "msg-1",
        "input": [{"type": "text", "text": "Inspect"}],
        "outputSchema": {"type": "object"},
        "threadId": "thr-1",
    }
    response = {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}

    _validate("TurnStartParams", params)
    _validate("TurnStartResponse", response)


def test_turn_steer_fixtures_require_expected_turn_precondition() -> None:
    params = {
        "clientUserMessageId": "msg-2",
        "expectedTurnId": "turn-1",
        "input": [{"type": "text", "text": "More evidence"}],
        "threadId": "thr-1",
    }

    _validate("TurnSteerParams", params)
    _validate("TurnSteerResponse", {"turnId": "turn-1"})


def test_turn_interrupt_fixtures_bind_both_thread_and_turn() -> None:
    _validate("TurnInterruptParams", {"threadId": "thr-1", "turnId": "turn-1"})
    _validate("TurnInterruptResponse", {})
