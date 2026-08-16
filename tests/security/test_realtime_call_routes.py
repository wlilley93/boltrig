"""Decision-0021 browser call session and media-token security contracts."""

import asyncio
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.api.bootstrap import wire_hitl_resume
from boltrig.fleet.chat import ChatService
from boltrig.kernel import Kernel
from boltrig.kernel import call_gateway_routes
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    Channel,
    GrantSet,
    ModelEndpoint,
    RealtimeCallEvent,
    TenantPermissions,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "call-tenant"


async def _kernel(*, voice: bool = True) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    if voice:
        await store.upsert_channel(
            Channel(
                id="ch-voice",
                tenant_id=T,
                platform="voice",
                name="Realtime voice",
                transport="socket",
                enabled=True,
            )
        )
    return kernel, store


async def _gated_kernel() -> tuple[Kernel, InMemoryStore, object]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs={"ticket.create"})
    tickets = build_tickets()
    await kernel.register_adapter(T, tickets)
    await store.upsert_channel(
        Channel(
            id="ch-voice",
            tenant_id=T,
            platform="voice",
            name="Realtime voice",
            transport="socket",
            enabled=True,
        )
    )
    chat = ChatService(kernel.store, kernel.events, kernel=kernel)
    wire_hitl_resume(kernel, resume_held_write=chat.resume_held_write)
    return kernel, store, tickets


def _headers(subject: str = "alice", grants: str = "ticket.create") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": "member",
        "x-boltrig-grants": grants,
    }


def _gateway(kernel: Kernel, channels: list[str]) -> dict[str, str]:
    token = kernel.mcp.issue_run_token(
        T,
        GrantSet(),
        actor="channel-gateway",
        extra={"channel_gateway": True, "channels": channels},
    )
    record = kernel.mcp.lookup_run_token(token)
    assert record is not None
    for channel_id in channels:
        asyncio.run(
            kernel.store.claim_channel_gateway_lease(
                T,
                channel_id,
                "channel-gateway",
                record.lease_id,
                45,
            )
        )
    return {"x-boltrig-mcp-token": token}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
def test_media_bearer_is_single_use_channel_bounded_and_mints_only_caller_tools():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))

    created = client.post("/v1/calls", json={}, headers=_headers())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["call"]["participants"] == [
        {"id": "alice", "label": "You", "kind": "user"}
    ]
    call_id = body["call"]["id"]
    media_token = body["media_token"]
    assert body["websocket_url"] == f"/voice/v1/calls/{call_id}/media"
    assert "tool_token" not in body
    assert media_token not in json.dumps(body["call"])

    stored = asyncio.run(store.get_realtime_call(T, call_id))
    assert stored is not None
    assert stored.tool_context["allow"] == ["ticket.create"]
    assert "*" not in stored.tool_context["allow"]
    assert stored.media_token_hash and stored.media_token_hash != media_token
    assert media_token not in repr(stored)

    # A live gateway token for a DIFFERENT channel cannot spend the bearer.
    refused = client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": media_token},
        headers=_gateway(kernel, ["ch-other"]),
    )
    assert refused.status_code == 401

    claimed = client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": media_token},
        headers=_gateway(kernel, ["ch-voice"]),
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["call"]["status"] == "active"
    tool_token = claimed.json()["tool_token"]

    # The provider-facing session learns only the caller's explicit grant.
    tools = client.post(
        "/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"x-boltrig-mcp-token": tool_token},
    )
    assert [tool["name"] for tool in tools.json()["result"]["tools"]] == ["ticket.create"]

    # The same media bearer is atomically spent.
    replay = client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": media_token},
        headers=_gateway(kernel, ["ch-voice"]),
    )
    assert replay.status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-10")
def test_voice_call_cannot_invent_an_agent_identity_from_a_profile_label():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    response = client.post(
        "/v1/calls",
        json={"agent_profile_id": "caller-invented-familiar"},
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json() == {
        "status": "error",
        "reason": "agent_profile_not_found",
    }
    assert getattr(store, "_realtime_calls", {}) == {}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-10")
def test_voice_profiles_are_tenant_resolved_and_reach_the_gateway(monkeypatch):
    kernel, store = asyncio.run(_kernel())
    asyncio.run(store.upsert_model_endpoint(
        ModelEndpoint("voice-ep", T, "xai", "grok-voice-agent")
    ))
    asyncio.run(store.upsert_capability(
        AgentCapability(
            "research-familiar", T, "codex", ["*"], 2, True, "standard",
            model_endpoint="voice-ep",
        )
    ))
    monkeypatch.setenv("BOLTRIG_MODEL_PROFILES", json.dumps({
        "voice-fast": {"provider": "xai", "model": "grok-voice-fast"}
    }))
    client = TestClient(create_app(kernel))
    created = client.post(
        "/v1/calls",
        json={
            "agent_profile_id": "research-familiar",
            "model_profile_id": "voice-fast",
        },
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["call"]["agent_profile_id"] == "research-familiar"
    assert body["call"]["model_profile_id"] == "voice-fast"
    claimed = client.post(
        "/v1/calls/gateway/claim",
        json={
            "call_id": body["call"]["id"],
            "media_token": body["media_token"],
        },
        headers=_gateway(kernel, ["ch-voice"]),
    )
    assert claimed.json()["session_profile"] == {
        "id": "voice-fast",
        "provider": "xai",
        "model": "grok-voice-fast",
        "agent_profile_id": "research-familiar",
        "agent_runtime": "codex",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
def test_call_metadata_and_normalized_events_are_owner_scoped_and_never_store_audio():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    created = client.post("/v1/calls", json={}, headers=_headers()).json()
    call_id = created["call"]["id"]
    gateway = _gateway(kernel, ["ch-voice"])
    assert client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": created["media_token"]},
        headers=gateway,
    ).status_code == 200

    sentinel = "RAW-PCM-MUST-NEVER-PERSIST"
    event = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "id": "provider-transcript-one",
            "type": "transcript",
            "participant_id": "user",
            "payload": {
                "text": "hello",
                "final": True,
                "kind": "input",
                "audio": sentinel,
                "data": sentinel,
            },
        },
        headers=gateway,
    )
    assert event.status_code == 200, event.text
    assert event.json()["event"]["payload"] == {
        "text": "hello",
        "final": True,
        "kind": "input",
    }
    rows = asyncio.run(store.list_realtime_call_events(T, call_id))
    assert sentinel not in repr(rows)
    replay = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "id": "provider-transcript-one",
            "type": "transcript",
            "participant_id": "user",
            "payload": {"text": "hello", "final": True, "kind": "input"},
        },
        headers=gateway,
    )
    assert replay.status_code == 200
    messages = asyncio.run(
        store.list_messages(T, created["call"]["conversation_id"])
    )
    assert [(message.role.value, message.content) for message in messages] == [
        ("user", "hello")
    ]

    # Call reads deliberately conceal existence from another user.
    assert client.get(f"/v1/calls/{call_id}", headers=_headers("mallory")).status_code == 404
    assert client.get(
        f"/v1/calls/{call_id}/events", headers=_headers("mallory")
    ).status_code == 404

    ended = client.post(f"/v1/calls/{call_id}/end", headers=_headers())
    assert ended.status_code == 200
    assert ended.json()["call"]["status"] == "ended"
    assert client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={"type": "transcript", "payload": {"text": "too late"}},
        headers=gateway,
    ).status_code == 409


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
def test_typed_call_text_limits_are_durable_reconnect_stable_and_call_isolated():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    gateway = _gateway(kernel, ["ch-voice"])

    def claimed_call() -> str:
        created = client.post("/v1/calls", json={}, headers=_headers()).json()
        call_id = created["call"]["id"]
        claimed = client.post(
            "/v1/calls/gateway/claim",
            json={"call_id": call_id, "media_token": created["media_token"]},
            headers=gateway,
        )
        assert claimed.status_code == 200, claimed.text
        return call_id

    def typed(call_id: str, text: str):
        return client.post(
            f"/v1/calls/gateway/{call_id}/events",
            json={
                "type": "transcript",
                "payload": {
                    "text": text,
                    "final": True,
                    "kind": "input",
                    "via": "text",
                },
            },
            headers=gateway,
        )

    rate_call = claimed_call()
    for index in range(call_gateway_routes._TYPED_TEXT_RATE_LIMIT):
        assert typed(rate_call, f"rate {index}").status_code == 200
    refused = typed(rate_call, "rate overflow")
    assert refused.status_code == 429
    assert refused.json() == {
        "status": "error",
        "reason": "typed_text_limit_reached",
    }

    # Another canonical call has an independent budget.
    isolated_call = claimed_call()
    assert typed(isolated_call, "independent").status_code == 200

    old = utcnow() - timedelta(minutes=1)

    count_call = claimed_call()
    for index in range(call_gateway_routes._TYPED_TEXT_CALL_MESSAGE_LIMIT):
        asyncio.run(store.append_realtime_call_event(RealtimeCallEvent(
            id=f"typed-count-{index}",
            tenant_id=T,
            call_id=count_call,
            type="transcript",
            payload={
                "text": "x",
                "final": True,
                "kind": "input",
                "via": "text",
            },
            created_at=old,
        )))
    assert typed(count_call, "count overflow").status_code == 429

    char_call = claimed_call()
    full_frames = call_gateway_routes._TYPED_TEXT_CALL_CHAR_LIMIT // 8_000
    for index in range(full_frames):
        asyncio.run(store.append_realtime_call_event(RealtimeCallEvent(
            id=f"typed-chars-{index}",
            tenant_id=T,
            call_id=char_call,
            type="transcript",
            payload={
                "text": "x" * 8_000,
                "final": True,
                "kind": "input",
                "via": "text",
            },
            created_at=old,
        )))
    assert typed(char_call, "x").status_code == 429

    # Reopening rotates transport authority but cannot reset durable history.
    refreshed = client.post(
        f"/v1/calls/{count_call}/media-token", headers=_headers()
    )
    assert refreshed.status_code == 200
    assert client.post(
        "/v1/calls/gateway/claim",
        json={
            "call_id": count_call,
            "media_token": refreshed.json()["media_token"],
        },
        headers=gateway,
    ).status_code == 200
    assert typed(count_call, "still over count").status_code == 429


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
def test_unavailable_voice_is_typed_and_keeps_the_text_conversation():
    kernel, store = asyncio.run(_kernel(voice=False))
    client = TestClient(create_app(kernel))
    response = client.post("/v1/calls", json={}, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["call"]["status"] == "realtime_unavailable"
    assert body["call"]["unavailable_reason"] == "no_enabled_realtime_voice_channel"
    assert body["text_continuation_conversation_id"] == body["call"]["conversation_id"]
    assert "media_token" not in body
    conversation = asyncio.run(
        store.get_conversation(T, body["call"]["conversation_id"])
    )
    assert conversation is not None and conversation.user_id == "alice"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-03")
def test_reconnect_rotates_the_spent_media_bearer():
    kernel, _ = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    created = client.post("/v1/calls", json={}, headers=_headers()).json()
    call_id = created["call"]["id"]
    assert client.get(
        "/v1/calls/current",
        params={"conversation_id": created["call"]["conversation_id"]},
        headers=_headers(),
    ).json()["call"]["id"] == call_id
    listed_calls = client.get(
        "/v1/calls", headers=_headers()
    ).json()["calls"]
    assert [row["id"] for row in listed_calls] == [call_id]
    listed_call = listed_calls[0]
    assert listed_call["created_at"]
    assert listed_call["updated_at"]
    gateway = _gateway(kernel, ["ch-voice"])
    assert client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": created["media_token"]},
        headers=gateway,
    ).status_code == 200
    reopened = client.post(f"/v1/calls/{call_id}/reopen", headers=_headers())
    assert reopened.status_code == 200
    assert reopened.json()["call"]["status"] == "reconnecting"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-04")
def test_voice_hitl_answer_resumes_the_exact_sealed_call_and_projects_resolution():
    kernel, store, tickets = asyncio.run(_gated_kernel())
    client = TestClient(create_app(kernel))
    created = client.post("/v1/calls", json={}, headers=_headers()).json()
    call_id = created["call"]["id"]
    gateway = _gateway(kernel, ["ch-voice"])
    claimed = client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": created["media_token"]},
        headers=gateway,
    ).json()
    tool_token = claimed["tool_token"]
    held = client.post(
        "/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "ticket.create",
                "arguments": {"title": "the sealed voice action"},
            },
        },
        headers={"x-boltrig-mcp-token": tool_token},
    ).json()["result"]["_boltrig"]
    assert held["status"] == "pending_human"
    request_id = held["hitl_request_id"]
    assert tickets._tickets == {}

    pending = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "type": "hitl",
            "payload": {
                "request_id": request_id,
                "status": "pending",
                "verb": "ticket.create",
                "provider_call_id": "provider-call-7",
            },
        },
        headers=gateway,
    )
    assert pending.status_code == 200
    assert asyncio.run(store.get_realtime_call(T, call_id)).status == "held"

    asyncio.run(kernel.hitl.answer(T, request_id, "approve", "reviewer@acme"))

    request = asyncio.run(kernel.hitl.get(T, request_id))
    assert request is not None and request.status.value == "consumed"
    assert [row["title"] for row in tickets._tickets.values()] == [
        "the sealed voice action"
    ]
    resolution = client.get(
        f"/v1/calls/gateway/{call_id}/hitl/{request_id}", headers=gateway
    )
    assert resolution.status_code == 200
    assert resolution.json()["status"] == "ok"
    events = client.get(
        f"/v1/calls/{call_id}/events", headers=_headers()
    ).json()["events"]
    assert any(
        event["type"] == "hitl"
        and event["payload"] == {
            "request_id": request_id,
            "status": "ok",
            "verb": "ticket.create",
        }
        for event in events
    )
    assert asyncio.run(store.get_realtime_call(T, call_id)).status == "active"
    # A fast human may answer before the severed gateway finishes publishing
    # its pending observation. Terminal kernel truth must dominate that late
    # pending event, and the gateway may never forge a resolved outcome.
    late = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "type": "hitl",
            "payload": {"request_id": request_id, "status": "pending"},
        },
        headers=gateway,
    )
    assert late.status_code == 200
    assert client.get(
        f"/v1/calls/gateway/{call_id}/hitl/{request_id}", headers=gateway
    ).json()["status"] == "ok"
    assert asyncio.run(store.get_realtime_call(T, call_id)).status == "active"
    forged = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "type": "hitl",
            "payload": {"request_id": request_id, "status": "ok"},
        },
        headers=gateway,
    )
    assert forged.status_code == 400


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-04")
def test_voice_usage_is_content_free_owner_scoped_and_explicitly_priced():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    created = client.post("/v1/calls", json={}, headers=_headers()).json()
    call_id = created["call"]["id"]
    gateway = _gateway(kernel, ["ch-voice"])
    client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": created["media_token"]},
        headers=gateway,
    )
    payloads = [
        {
            "input_audio_bytes": 1200,
            "output_audio_bytes": 800,
            "tool_calls": 1,
            "provider_input_tokens": 12,
            "provider_output_tokens": 8,
            "estimated_cost_micros": 19,
            "pricing_revision": "xai-contract-2026-07",
            "cost_status": "estimated",
            "audio": "PCM MUST NOT PERSIST",
        },
        {
            "input_audio_bytes": 300,
            "output_audio_bytes": 200,
            "tool_calls": 0,
            "provider_input_tokens": 3,
            "provider_output_tokens": 2,
            "estimated_cost_micros": 4,
            "pricing_revision": "xai-contract-2026-07",
            "cost_status": "estimated",
        },
    ]
    for payload in payloads:
        response = client.post(
            f"/v1/calls/gateway/{call_id}/events",
            json={"type": "usage", "payload": payload},
            headers=gateway,
        )
        assert response.status_code == 200, response.text
    refused = client.post(
        f"/v1/calls/gateway/{call_id}/events",
        json={
            "type": "usage",
            "payload": {"input_audio_bytes": -1, "cost_status": "unpriced"},
        },
        headers=gateway,
    )
    assert refused.status_code == 400

    usage = client.get(f"/v1/calls/{call_id}/usage", headers=_headers())
    assert usage.status_code == 200
    assert usage.json()["usage"] == {
        "input_audio_bytes": 1500,
        "output_audio_bytes": 1000,
        "tool_calls": 1,
        "provider_input_tokens": 15,
        "provider_output_tokens": 10,
        "estimated_cost_micros": 23,
        "pricing_revision": "xai-contract-2026-07",
        "cost_status": "estimated",
    }
    assert client.get(
        f"/v1/calls/{call_id}/usage", headers=_headers("mallory")
    ).status_code == 404
    rows = asyncio.run(store.list_realtime_call_events(T, call_id))
    assert "PCM MUST NOT PERSIST" not in repr(rows)
    assert client.post(
        f"/v1/calls/gateway/{call_id}/state",
        json={"status": "reconnecting"},
        headers=gateway,
    ).status_code == 200

    refreshed = client.post(
        f"/v1/calls/{call_id}/media-token", headers=_headers()
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["media_token"] != created["media_token"]
    assert client.post(
        "/v1/calls/gateway/claim",
        json={"call_id": call_id, "media_token": refreshed.json()["media_token"]},
        headers=gateway,
    ).status_code == 200
