"""Display objects stay closed, bounded and tied to an interactive named turn."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from boltrig.adapters.builtin.chat_present import ChatPresentAdapter
from boltrig.fleet.chat_event_projection import project_chat_event
from boltrig.kernel.events import EventRelay
from boltrig.models import InvocationContext
from boltrig.models.display_objects import (
    DISPLAY_OBJECT_KINDS,
    DisplayObjectValidationError,
    build_display_object,
    validate_display_object,
)


def email_draft() -> dict:
    return {
        "kind": "email.draft",
        "title": "Draft reply to Dana",
        "data": {
            "to": ["dana@example.com"],
            "subject": "Launch plan",
            "body": "Here is the reviewed launch plan.",
        },
    }


def test_builder_stamps_truth_and_adds_reviewed_draft_actions() -> None:
    payload = email_draft()
    payload["provenance"] = {
        "run_id": "forged-run", "agent_address": "forged-agent", "provider": "forged-provider"
    }
    built = build_display_object(
        payload, run_id="run-1", agent_address="chief-of-staff"
    )

    assert built["schema"] == "boltrig.display.v1"
    assert built["id"].startswith("do_")
    assert built["status"] == "draft"
    assert built["revision"] == 1
    assert built["provenance"] == {
        "run_id": "run-1", "agent_address": "chief-of-staff"
    }
    assert [item["intent"] for item in built["actions"]] == [
        "edit", "change_recipient", "send", "discard"
    ]
    assert built["actions"][2]["requires_confirmation"] is True


def test_connection_bound_message_draft_receives_send_action() -> None:
    built = build_display_object(
        {
            "kind": "slack.message.draft",
            "title": "Draft update",
            "data": {
                "connection_id": "slack-primary",
                "recipient": "#launch",
                "body": "The release candidate is ready.",
            },
        },
        run_id="run-1",
        agent_address="chief-of-staff",
    )

    assert "send" in [item["intent"] for item in built["actions"]]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(kind="invented.widget"),
        lambda value: value["data"].update(url="javascript:alert(1)"),
        lambda value: value.update(extra="not in the envelope"),
        lambda value: value["data"].update(latitude=91),
        lambda value: value.update(blocks=[{"type": "table", "columns": ["Name"]}]),
    ],
)
def test_validator_rejects_unreviewed_or_unsafe_shapes(mutation) -> None:
    built = build_display_object(
        email_draft(), run_id="run-1", agent_address="chief-of-staff"
    )
    mutation(built)
    with pytest.raises(DisplayObjectValidationError):
        validate_display_object(built)


def test_kernel_and_browser_template_catalogues_cannot_drift() -> None:
    source = Path("sdks/web/src/displayObjects.ts").read_text(encoding="utf-8")
    browser_kinds = set(re.findall(r'\{ kind: "([^"]+)"', source))

    assert browser_kinds == DISPLAY_OBJECT_KINDS


def test_agent_tool_schema_advertises_templates_fields_and_composable_blocks() -> None:
    schema = ChatPresentAdapter().describe()[0].input_schema

    assert set(schema["properties"]["kind"]["enum"]) == DISPLAY_OBJECT_KINDS
    assert len(schema["properties"]["blocks"]["items"]["oneOf"]) == 16
    field_types = schema["properties"]["fields"]["items"]["properties"]["type"]["enum"]
    assert {"recipient", "agent", "connection", "multi_select"} <= set(field_types)
    assert "Never provide HTML" in schema["properties"]["data"]["description"]


@pytest.mark.asyncio
async def test_named_interactive_agent_can_publish_to_the_parent_chat_run() -> None:
    relay = EventRelay()
    adapter = ChatPresentAdapter(events=relay)
    context = InvocationContext(
        tenant_id="tenant-1",
        run_id="phase-1",
        parent_run_id="chat-run-1",
        actor="legal",
        actor_tier="tier1",
        extra={"conversation_id": "conversation-1"},
    )

    result = await adapter.execute("chat.present", email_draft(), None, context)

    assert result.ok
    frame = relay.snapshot("tenant-1", "chat-run-1")[0]
    assert frame["type"] == "display_object"
    assert frame["object"]["provenance"] == {
        "run_id": "chat-run-1", "agent_address": "legal"
    }
    assert "dana@example.com" not in repr(result.output)


@pytest.mark.asyncio
async def test_ephemeral_or_noninteractive_call_cannot_publish() -> None:
    relay = EventRelay()
    adapter = ChatPresentAdapter(events=relay)
    ephemeral = InvocationContext(
        tenant_id="tenant-1", run_id="run-1", actor="worker", actor_tier="ephemeral",
        extra={"conversation_id": "conversation-1"},
    )
    background = InvocationContext(
        tenant_id="tenant-1", run_id="run-2", actor="legal", actor_tier="tier1"
    )

    assert not (await adapter.execute("chat.present", email_draft(), None, ephemeral)).ok
    assert not (await adapter.execute("chat.present", email_draft(), None, background)).ok
    assert relay.snapshot("tenant-1", "run-1") == []
    assert relay.snapshot("tenant-1", "run-2") == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_public_projection_keeps_only_the_validated_object_contract() -> None:
    display_object = build_display_object(
        email_draft(), run_id="run-1", agent_address="legal"
    )
    projected = project_chat_event(
        {
            "type": "display_object",
            "run_id": "run-1",
            "object": display_object,
            "private_prompt": "must-not-cross",
        }
    )

    assert projected == {
        "type": "display_object", "run_id": "run-1", "object": display_object
    }
    assert "private_prompt" not in repr(projected)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-31")
def test_malformed_display_object_collapses_to_content_free_notice() -> None:
    projected = project_chat_event(
        {
            "type": "display_object",
            "object": {"kind": "raw.html", "html": "<script>secret</script>"},
        }
    )

    assert projected == {"type": "event_unavailable", "reason": "malformed_event"}
    assert "secret" not in repr(projected)
