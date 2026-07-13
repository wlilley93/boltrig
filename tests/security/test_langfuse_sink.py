"""Langfuse observability stays metadata-only and fail-safe."""

import asyncio
import json

import pytest

from boltrig.models import AgentCapability, GrantSet, InvocationContext
from boltrig.observability.langfuse_sink import (
    LangfuseObservabilitySink,
    NoopObservabilitySink,
    build_observability_sink,
    spawn_trace_payload,
)


pytestmark = pytest.mark.security

T = "acme"


def _capability() -> AgentCapability:
    return AgentCapability("opencode-worker", T, "opencode", ["*"], 2, True, "cheap")


def _parent() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id="parent-run",
        workspace_id="ws-1",
        ip_address="203.0.113.77",
        user_agent="secret-browser",
        on_behalf_of="person@example.test",
        grants=GrantSet.of(["*"]),
        actor="chief-of-staff",
    )


@pytest.mark.invariant("FR-OBS-13")
def test_langfuse_payload_is_bounded_and_redacts_route_connection_data():
    payload = spawn_trace_payload(
        tenant_id=T,
        parent=_parent(),
        capability=_capability(),
        skills=[f"analysis/decompose-{idx}" for idx in range(30)],
        run_id="child-run",
        status="x" * 200,
        tokens=123,
        cost_micros=456,
        latency_ms=789,
        model_route={
            "provider": "bifrost",
            "model": "ornith",
            "runtime": "openai",
            "profile": "code",
            "base_url": "https://models.internal/v1",
            "api_key": "sk-secret",
            "token": "bearer-secret",
        },
    )

    assert payload["metadata"]["model_route"] == {
        "provider": "bifrost",
        "model": "ornith",
        "runtime": "openai",
        "profile": "code",
    }
    assert payload["usage_details"] == {"total_tokens": 123, "cost_micros": 456}
    assert len(payload["metadata"]["skills"]) == 20
    assert len(payload["metadata"]["status"]) == 60
    blob = json.dumps(payload, sort_keys=True)
    assert "models.internal" not in blob
    assert "sk-secret" not in blob
    assert "bearer-secret" not in blob
    assert "203.0.113.77" not in blob
    assert "person@example.test" not in blob
    assert "secret-browser" not in blob
    assert "task" not in blob
    assert "prompt" not in blob
    assert "output" not in blob
    assert "raw_detail" not in blob


@pytest.mark.invariant("FR-OBS-13")
async def test_langfuse_sink_emits_event_and_flushes():
    class _Client:
        def __init__(self):
            self.events: list[dict] = []
            self.flushed = False

        def event(self, **payload):
            self.events.append(payload)

        def flush(self):
            self.flushed = True

    client = _Client()
    sink = LangfuseObservabilitySink(client)
    await sink.record_spawn(
        tenant_id=T,
        parent=_parent(),
        capability=_capability(),
        skills=["analysis/decompose"],
        run_id="child-run",
        status="ok",
        tokens=1,
        cost_micros=2,
    )

    assert client.events[0]["name"] == "boltrig.agent.spawn"
    assert client.events[0]["metadata"]["capability"] == "opencode-worker"
    assert client.flushed is True


@pytest.mark.invariant("FR-OBS-13")
async def test_langfuse_sink_failure_is_swallowed():
    class _Client:
        def event(self, **payload):
            raise RuntimeError("langfuse unavailable")

    sink = LangfuseObservabilitySink(_Client())
    await sink.record_spawn(
        tenant_id=T,
        parent=_parent(),
        capability=_capability(),
        skills=["analysis/decompose"],
        run_id="child-run",
        status="ok",
        tokens=1,
        cost_micros=2,
    )


@pytest.mark.invariant("FR-OBS-13")
async def test_langfuse_sink_timeout_is_swallowed():
    class _Client:
        async def event(self, **payload):
            await asyncio.sleep(1)

    sink = LangfuseObservabilitySink(_Client(), timeout_s=0.001)
    await sink.record_spawn(
        tenant_id=T,
        parent=_parent(),
        capability=_capability(),
        skills=["analysis/decompose"],
        run_id="child-run",
        status="ok",
        tokens=1,
        cost_micros=2,
    )


@pytest.mark.invariant("FR-OBS-13")
def test_langfuse_builder_defaults_to_noop_without_keys():
    assert isinstance(build_observability_sink({}), NoopObservabilitySink)
