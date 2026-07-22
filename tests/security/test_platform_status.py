"""Platform runtime status snapshots for the future Boltrig v2 console."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.identity.auth import build_principal_resolver
from boltrig.fleet.model_gateway_status import ModelGatewayStatusProvider
from boltrig.fleet.stack_tool_status import StackToolStatusProvider
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    RoleMapping,
    TenantPermissions,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


class _Verifier:
    async def verify(self, token: str) -> dict:
        if token != "good":
            raise ValueError("bad token")
        return {"sub": "alice", "groups": ["Admins"]}


class _StatusProvider:
    async def snapshot(self, *, tenant_id: str, workspace_id: str | None) -> dict:
        return {
            "components": [
                {
                    "id": "runpod",
                    "kind": "gpu",
                    "status": "ok",
                    "message": "warm",
                    "metadata": {
                        "session_cost": "1.23",
                        "base_url": "https://api.runpod.io/v2/secret",
                        "api_key": "rpa_secret",
                        "safe_count": 3,
                    },
                },
                {"id": "bad", "status": "surprising"},
            ],
            "runtimes": {
                "opencode": {
                    "status": "degraded",
                    "metadata": {"model": "ornith", "token": "secret"},
                }
            },
        }


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


def _client(platform=None) -> TestClient:
    mappings = [RoleMapping(T, "Admins", "org-admin", {"all": True})]
    resolver = build_principal_resolver(
        verifier=_Verifier(), mappings=mappings, tenant_id=T
    )
    return TestClient(
        create_app(asyncio.run(_kernel()), principal_resolver=resolver, platform=platform or {})
    )


def _client_for(kernel: Kernel, *, workspace_id: str | None = None) -> TestClient:
    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer good":
            raise HTTPException(status_code=401, detail="bad token")
        return Principal(
            tenant_id=T,
            subject="alice",
            grants=GrantSet.of(["*"]),
            role="org-admin",
            actor_tier="human",
            scope={"all": True},
            active_workspace_id=workspace_id,
        )

    return TestClient(create_app(kernel, principal_resolver=resolver))


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-08")
def test_platform_status_requires_authentication():
    assert _client({"status": _StatusProvider()}).get("/v1/platform/status").status_code == 401


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-09")
def test_platform_status_is_bounded_and_redacted():
    resp = _client({"status": _StatusProvider()}).get(
        "/v1/platform/status", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == T
    assert body["components"][0]["status"] == "ok"
    assert body["components"][1]["status"] == "unknown"
    assert body["runtimes"][0]["id"] == "opencode"

    rendered = repr(body).lower()
    assert "rpa_secret" not in rendered
    assert "api_key" not in rendered
    assert "base_url" not in rendered
    assert "https://api.runpod.io" not in rendered
    assert "token" not in rendered
    assert body["components"][0]["metadata"] == {"session_cost": "1.23", "safe_count": 3}


@pytest.mark.security
@pytest.mark.invariant("FR-GW-03")
def test_model_gateway_status_is_bounded_and_redacted(monkeypatch):
    monkeypatch.setenv("BOLTRIG_MODEL_GATEWAY_URL", "http://bifrost:8080/v1")
    monkeypatch.setenv("BOLTRIG_MODEL_GATEWAY_TTL", "120")
    # Live-health polling stays OFF regardless of test order: apply_manifest's
    # runtime-env export (pinned by tests/security/test_model_routing.py) leaks
    # BOLTRIG_MODEL_GATEWAY_* into os.environ process-wide, and a HEALTH=1 leak
    # would have this snapshot poll a dead health URL.
    monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_HEALTH", raising=False)
    monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_HEALTH_URL", raising=False)
    monkeypatch.setenv("BOLTRIG_MODEL_PROFILES", json.dumps({
        "code": {
            "provider": "bifrost",
            "model": "kimi-k2.7",
            "base_url": "http://bifrost:8080/v1",
        },
        "broken": {"provider": "bifrost"},
    }))
    resp = _client({"status": ModelGatewayStatusProvider(_StatusProvider())}).get(
        "/v1/platform/status", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    body = resp.json()
    components = {item["id"]: item for item in body["components"]}
    runtimes = {item["id"]: item for item in body["runtimes"]}

    assert components["bifrost"]["status"] == "ok"
    assert components["bifrost"]["metadata"] == {
        "configured": True,
        "routing": "gateway",
        "internal_route": True,
        "v1_base": True,
        "live_health": "not_polled",
        "cache_ttl_seconds": 120,
        "profile_count": 1,
    }
    assert runtimes["model-gateway"]["metadata"] == {
        "provider": "bifrost",
        "cache": "conversation_binding",
        "live_health": "not_polled",
    }
    rendered = repr(body).lower()
    assert "http://bifrost" not in rendered
    assert "base_url" not in rendered
    assert "api_key" not in rendered


@pytest.mark.security
@pytest.mark.invariant("FR-GW-03")
def test_model_gateway_status_reports_inert_when_unconfigured(monkeypatch):
    monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("BOLTRIG_MODEL_PROFILES", raising=False)
    resp = _client({"status": ModelGatewayStatusProvider()}).get(
        "/v1/platform/status", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    components = {item["id"]: item for item in resp.json()["components"]}
    assert components["bifrost"]["status"] == "unknown"
    assert components["bifrost"]["metadata"]["configured"] is False
    assert components["bifrost"]["metadata"]["profile_count"] == 0


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-12")
def test_stack_tool_status_reports_shipped_tools_without_user_paths():
    env = {
        "BOLTRIG_HERDR_HOME": "/var/lib/boltrig/herdr",
        "BOLTRIG_OPENCODE_HOME": "/var/lib/boltrig/opencode",
        "BOLTRIG_BROWSER_CLI_HOME": "/var/lib/boltrig/browser-cli",
        "HERDR_BIN": "/usr/local/bin/herdr",
        "BOLTRIG_OPENCODE_BIN": "/usr/local/bin/opencode",
        "BOLTRIG_BROWSER_CLI_BIN": "/usr/local/bin/browser-use",
        "BOLTRIG_BROWSER_ALLOWED_DOMAINS": "example.com,app.example.com",
        "BOLTRIG_BROWSER_CLOUD_POLICY": "stack",
        "BOLTRIG_BROWSER_CLOUD_API_KEY": "stack-key",
        "BOLTRIG_BROWSER_CLOUD_PROFILE_ID": "stack-profile",
    }
    resp = _client({"status": StackToolStatusProvider(_StatusProvider(), env=env)}).get(
        "/v1/platform/status", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    body = resp.json()
    components = {item["id"]: item for item in body["components"]}
    runtimes = {item["id"]: item for item in body["runtimes"]}

    for tool in ("herdr", "opencode", "browser-cli"):
        assert components[tool]["status"] == "ok"
        assert components[tool]["metadata"]["install_mode"] == "first_party_image"
        assert components[tool]["metadata"]["state_root_stack_owned"] is True
        assert components[tool]["metadata"]["binary_stack_owned"] is True
        assert runtimes[f"{tool}-cli"]["metadata"]["profile_state"] == "stack_owned"
    assert components["browser-cli"]["metadata"]["allowed_domain_count"] == 2
    assert components["browser-cli"]["metadata"]["cloud_profile_policy"] == "stack_owned"
    assert components["browser-cli"]["metadata"]["cloud_profile_configured"] is True

    rendered = repr(body).lower()
    assert "/var/lib/boltrig" not in rendered
    assert "/usr/local/bin" not in rendered
    assert ".config" not in rendered
    assert ".opencode" not in rendered
    assert "stack-key" not in rendered
    assert "stack-profile" not in rendered


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-12")
def test_stack_tool_status_degrades_personal_state_without_leaking_it():
    env = {
        "BOLTRIG_HERDR_HOME": "/home/will/.config/herdr",
        "BOLTRIG_OPENCODE_HOME": "/Users/will/.opencode",
        "BOLTRIG_BROWSER_CLI_HOME": "$HOME/.local/share/browser-use",
        "HERDR_BIN": "/home/will/.local/bin/herdr",
        "BOLTRIG_OPENCODE_BIN": "/Users/will/.opencode/bin/opencode",
        "BOLTRIG_BROWSER_CLI_BIN": "/home/will/.local/bin/browser-use",
    }
    resp = _client({"status": StackToolStatusProvider(env=env)}).get(
        "/v1/platform/status", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    components = {item["id"]: item for item in resp.json()["components"]}

    for tool in ("herdr", "opencode", "browser-cli"):
        assert components[tool]["status"] == "degraded"
        assert components[tool]["metadata"]["profile_state"] == "rejected"
        assert components[tool]["metadata"]["state_root_stack_owned"] is False
        assert components[tool]["metadata"]["binary_stack_owned"] is False

    rendered = repr(resp.json()).lower()
    assert "/home/will" not in rendered
    assert "/users/will" not in rendered
    assert "$home" not in rendered
    assert ".opencode/bin" not in rendered
    assert ".local/share/browser-use" not in rendered


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-10")
def test_platform_status_does_not_publish_run_events():
    kernel = asyncio.run(_kernel())

    async def resolver(_request):
        from boltrig.kernel.app import Principal

        return Principal(tenant_id=T, subject="alice", grants=GrantSet.of(["*"]))

    client = TestClient(
        create_app(kernel, principal_resolver=resolver, platform={"status": _StatusProvider()})
    )
    resp = client.get("/v1/platform/status")
    assert resp.status_code == 200
    assert kernel.events.snapshot(T, "anything") == []


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-11")
def test_model_telemetry_requires_authentication():
    kernel = asyncio.run(_kernel())
    assert _client_for(kernel).get("/v1/model/telemetry").status_code == 401


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-11")
def test_model_telemetry_is_aggregated_scoped_and_redacted():
    kernel = asyncio.run(_kernel())

    async def seed() -> None:
        for run_id, workspace, status, tokens, cost, latency in (
            ("r1", "ws-1", "ok", 100, 200, 40),
            ("r2", "ws-1", "degraded", 25, 50, 80),
            ("r3", "ws-2", "ok", 999, 999, 1),
        ):
            await kernel.audit.write(
                AuditEvent(
                    tenant_id=T,
                    ts=utcnow(),
                    run_id=run_id,
                    workspace_id=workspace,
                    actor="opencode-worker",
                    actor_tier="ephemeral",
                    action_type=ActionType.AGENT_SPAWN,
                    status=status,
                    tokens_used=tokens,
                    cost_micros=cost,
                    latency_ms=latency,
                    detail={
                        "model_route": {
                            "profile": "deep",
                            "provider": "cerebras",
                            "model": "qwen-3-coder",
                            "runtime": "opencode",
                            "base_url": "https://secret.example/v1",
                            "api_key": "never",
                        }
                    },
                )
            )

    asyncio.run(seed())
    resp = _client_for(kernel, workspace_id="ws-1").get(
        "/v1/model/telemetry", headers={"authorization": "Bearer good"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == "ws-1"
    assert body["models"] == [
        {
            "provider": "cerebras",
            "model": "qwen-3-coder",
            "runtime": "opencode",
            "calls": 2,
            "tokens": 125,
            "cost_micros": 250,
            "avg_latency_ms": 60.0,
            "last_seen": body["models"][0]["last_seen"],
            "statuses": {"degraded": 1, "ok": 1},
            "profile": "deep",
        }
    ]
    rendered = repr(body).lower()
    assert "secret.example" not in rendered
    assert "base_url" not in rendered
    assert "api_key" not in rendered
    assert "never" not in rendered
