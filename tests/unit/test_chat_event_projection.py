"""The ordinary chat stream is a closed, redacted public event contract."""

from __future__ import annotations

import pytest

from boltrig.fleet.chat_event_projection import project_chat_event


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_degraded_text_receipt_preserves_only_the_typed_honesty_flag() -> None:
    projected = project_chat_event(
        {
            "type": "text_delta",
            "delta": "degraded (codex: unavailable)",
            "degraded": True,
            "provider_error": "must-not-cross",
        }
    )

    assert projected == {
        "type": "text_delta",
        "delta": "degraded (codex: unavailable)",
        "degraded": True,
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_unknown_internal_frame_collapses_without_reflecting_type_or_payload() -> None:
    projected = project_chat_event(
        {
            "type": "ultracode",
            "provider": "secret-provider",
            "output": {"token": "must-not-cross"},
        }
    )

    assert projected == {
        "type": "event_unavailable",
        "reason": "unsupported_event",
    }
    assert "ultracode" not in repr(projected)
    assert "must-not-cross" not in repr(projected)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_tool_frames_keep_only_reviewed_summary_fields() -> None:
    call = project_chat_event(
        {
            "type": "tool_call",
            "run_id": "run-1",
            "verb": "mail.send",
            "call_id": "call-1",
            "input": {"api_key": "secret", "body": "private"},
            "args_summary": {
                "keys": ["body", "to"],
                "count": 2,
                "sample": "private",
            },
            "unreviewed": "private",
        }
    )
    result = project_chat_event(
        {
            "type": "tool_result",
            "call_id": "call-1",
            "status": "ok",
            "output": {"recipient": "private"},
            "result_summary": {
                "keys": ["message_id"],
                "status": "ok",
                "sample": "private",
            },
        }
    )

    assert call == {
        "type": "tool_call",
        "run_id": "run-1",
        "tool": "mail.send",
        "call_id": "call-1",
        "args_summary": {"keys": ["body", "to"], "count": 2},
    }
    assert result == {
        "type": "tool_result",
        "run_id": None,
        "call_id": "call-1",
        "status": "ok",
        "result_summary": {"keys": ["message_id"], "status": "ok"},
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_artifact_frames_are_typed_receipts_without_content_bytes() -> None:
    projected = project_chat_event(
        {
            "type": "artifact",
            "artifact_id": "artifact-1",
            "name": "answer.txt",
            "media_type": "text/plain",
            "size": 42,
            "content": "must be fetched through the authorized route",
        }
    )

    assert projected == {
        "type": "artifact",
        "artifact_id": "artifact-1",
        "name": "answer.txt",
        "media_type": "text/plain",
        "size": 42,
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_malformed_reviewed_frame_fails_to_a_content_free_notice() -> None:
    assert project_chat_event(
        {"type": "workflow_step", "step_id": "one", "status": "invented"}
    ) == {
        "type": "event_unavailable",
        "reason": "malformed_event",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_nested_subagent_receipts_drop_unreviewed_fields() -> None:
    projected = project_chat_event(
        {
            "type": "subagent",
            "child_run_id": "child-1",
            "task": "Research the topic",
            "skills": ["research"],
            "spawn_rule": {
                "id": "research",
                "priority": 5,
                "matched_intent_tags": ["research"],
                "capability": "codex",
                "skills_added": ["research"],
                "max_depth": 2,
                "credential": "must-not-cross",
            },
            "familiar_genotype": {
                "source": "agent_capability.name.v1",
                "seed": 7,
                "palette": ["violet"],
                "private_state": "must-not-cross",
            },
        }
    )

    assert "credential" not in repr(projected)
    assert "private_state" not in repr(projected)
    assert projected["spawn_rule"]["id"] == "research"
    assert projected["familiar_genotype"]["seed"] == 7
