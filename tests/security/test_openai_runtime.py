"""OpenAiRuntime: native OpenAI-compatible runtime, offline-safe (Epic RUN).

Pins the first-class sensitive-local lane runtime (US-RUN-01): a 'openai'
capability resolves to it, it degrades without an endpoint (P9), it reads real
usage and carries no tool/verb credential (SEC-27), and it allows a keyless
local endpoint (vLLM/Ollama).
"""

import pytest

from boltrig.fleet.runtime import OpenAiRuntime, build_runtime
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
)

T = "acme"


def _cap(model_endpoint: str | None = None) -> AgentCapability:
    return AgentCapability(
        "openai-worker", T, "openai", ["*"], 2, True, "standard",
        model_endpoint=model_endpoint,
    )


def _ctx(grants=("*",)):
    return InvocationContext(tenant_id=T, grants=GrantSet.of(list(grants)), actor="openai-worker")


def _endpoint(base_url: str | None = "http://local-vllm:8000/v1") -> ModelEndpoint:
    return ModelEndpoint(id="local-vllm", tenant_id=T, kind="vllm", model="glm-4", base_url=base_url)


class _FakeResponse:
    def __init__(self, payload: dict, seen: dict):
        self._payload = payload
        self._seen = seen

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """A stub httpx.AsyncClient capturing the POST body/headers."""

    def __init__(self, payload: dict, seen: dict):
        self._payload = payload
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, *, json, headers):
        self._seen["url"] = url
        self._seen["json"] = json
        self._seen["headers"] = headers
        return _FakeResponse(self._payload, self._seen)


def _install_fake_httpx(monkeypatch, payload: dict, seen: dict):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload, seen))


@pytest.mark.invariant("FR-RUN-06")
def test_build_runtime_resolves_openai():
    rt = build_runtime(_cap())
    assert isinstance(rt, OpenAiRuntime) and rt.runtime == "openai"


@pytest.mark.invariant("FR-RUN-07")
async def test_openai_runtime_degrades_without_endpoint():
    rt = OpenAiRuntime(endpoint=None)
    res = await rt.run("hello", _ctx(), tools=[])
    assert res.ok and res.degraded
    assert res.output.get("_degraded", {}) == {"runtime": "openai", "reason": "no_endpoint"}


@pytest.mark.invariant("FR-RUN-08")
@pytest.mark.invariant("SEC-27")
async def test_openai_runtime_reads_usage_and_carries_no_credential(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "done"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    seen: dict = {}
    _install_fake_httpx(monkeypatch, payload, seen)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    rt = OpenAiRuntime(endpoint=_endpoint())
    res = await rt.run("prompt", _ctx(), tools=["ticket.read"])
    # real usage is read from the OpenAI usage block, not the char estimate
    assert res.tokens_used == 18
    # the body carries the model + messages + tool names, never a tool/verb credential
    assert set(seen["json"]) == {"model", "messages", "tools"}
    assert "credential" not in repr(seen["json"]).lower()
    assert "sk-real" not in repr(seen["json"])  # the key is a header, never in the body
    assert seen["headers"]["Authorization"] == "Bearer sk-real"


@pytest.mark.invariant("FR-RUN-09")
async def test_openai_runtime_allows_keyless_local_endpoint(monkeypatch):
    payload = {"choices": [{"message": {"content": "local"}}], "usage": {"total_tokens": 5}}
    seen: dict = {}
    _install_fake_httpx(monkeypatch, payload, seen)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BOLTRIG_OPENAI_API_KEY", raising=False)
    rt = OpenAiRuntime(endpoint=_endpoint())
    res = await rt.run("prompt", _ctx(), tools=[])
    # a keyless local server is attempted, not hard-degraded, and no bearer is sent
    assert res.ok and not res.degraded
    assert res.tokens_used == 5
    assert "Authorization" not in seen["headers"]
    assert seen["url"] == "http://local-vllm:8000/v1/chat/completions"
