from __future__ import annotations

import pytest

from boltrig.fleet.rivet_runtime import RivetAgentOSRuntime
from boltrig.fleet.runtime import build_runtime
from boltrig.models import AgentCapability, GrantSet, InvocationContext, ModelEndpoint

T = "acme"


def _cap() -> AgentCapability:
    return AgentCapability(
        "rivet-worker", T, "rivet_agentos", ["*"], 2, True, "standard",
        model_endpoint="standard",
    )


def _endpoint() -> ModelEndpoint:
    return ModelEndpoint(
        id="standard",
        tenant_id=T,
        kind="openai",
        model="glm-5.2",
        base_url="https://models.example/v1",
    )


def _ctx() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id="run-1",
        workspace_id="ws-1",
        grants=GrantSet.of(["ticket.read"]),
        actor="rivet-worker",
        skills_loaded=("analysis/decompose",),
    )


def test_build_runtime_resolves_rivet_agentos():
    rt = build_runtime(
        _cap(),
        lambda _id: _endpoint(),
        rivet_config={"agentos_url": "http://rivet-agentos:2468"},
    )

    assert isinstance(rt, RivetAgentOSRuntime)
    assert rt.runtime == "rivet_agentos"


async def test_rivet_degrades_without_agentos_url():
    rt = RivetAgentOSRuntime(agentos_url=None, issue_token=lambda *a, **k: "TOKEN")

    res = await rt.run("hello", _ctx(), tools=[])

    assert res.ok and res.degraded
    assert res.output["_degraded"] == {
        "runtime": "rivet_agentos",
        "reason": "no_agentos",
    }


@pytest.mark.invariant("SEC-27")
async def test_rivet_request_carries_scoped_mcp_not_tool_credentials():
    seen = {}

    async def transport(url, payload, headers):
        seen.update({"url": url, "payload": payload, "headers": headers})
        return 200, {
            "summary": "used TOKEN_SECRET",
            "output": {"text": "token TOKEN_SECRET redacted"},
            "tokens_used": 13,
            "cost_micros": 17,
        }

    revoked = []
    rt = RivetAgentOSRuntime(
        agentos_url="http://rivet-agentos:2468",
        mcp_url="http://kernel:8000/v1/mcp",
        issue_token=lambda *a, **k: "TOKEN_SECRET",
        revoke_token=revoked.append,
        endpoint=_endpoint(),
        agentos_token="AGENTOS_SECRET",
        transport=transport,
    )

    res = await rt.run("do work", _ctx(), tools=["ticket.read"])

    assert seen["url"] == "http://rivet-agentos:2468/runs"
    assert seen["headers"]["Authorization"] == "Bearer AGENTOS_SECRET"
    assert seen["payload"]["mcp"] == {
        "url": "http://kernel:8000/v1/mcp",
        "token": "TOKEN_SECRET",
    }
    assert seen["payload"]["context"]["workspace_id"] == "ws-1"
    assert seen["payload"]["model"]["name"] == "glm-5.2"
    assert "credential" not in repr(seen["payload"]).lower()
    assert revoked == ["TOKEN_SECRET"]
    assert res.tokens_used == 13
    assert res.cost_micros == 17
    assert "TOKEN_SECRET" not in repr(res.output)
    assert "TOKEN_SECRET" not in res.summary
    assert "[redacted]" in repr(res.output)


async def test_rivet_http_error_degrades_and_revokes():
    async def transport(url, payload, headers):
        return 503, {"error": "down"}

    revoked = []
    rt = RivetAgentOSRuntime(
        agentos_url="http://rivet-agentos:2468",
        issue_token=lambda *a, **k: "TOKEN_SECRET",
        revoke_token=revoked.append,
        transport=transport,
    )

    res = await rt.run("do work", _ctx(), tools=[])

    assert res.ok and res.degraded
    assert res.output["_degraded"]["reason"] == "http_503"
    assert revoked == ["TOKEN_SECRET"]
