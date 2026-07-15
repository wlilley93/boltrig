"""Operator console overview is authenticated, scoped, bounded, and redacted."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    Budget,
    GrantSet,
    HITLRequest,
    HITLType,
    TenantPermissions,
    Urgency,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


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
                        "alive_seconds": 120,
                        "api_key": "rpa_secret",
                        "base_url": "https://secret.example/v1",
                    },
                }
            ],
            "runtimes": {
                "opencode": {
                    "status": "degraded",
                    "metadata": {"model": "ornith", "token": "never"},
                }
            },
        }


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    store.set_budget(
        Budget(
            id="tenant",
            tenant_id=T,
            scope_type="tenant",
            token_limit=1000,
            cost_limit_micros=1000,
            spent_tokens=125,
            spent_micros=250,
        )
    )
    return Kernel(store)


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

    return TestClient(
        create_app(
            kernel,
            principal_resolver=resolver,
            platform={"status": _StatusProvider()},
        )
    )


async def _seed(kernel: Kernel) -> None:
    for run_id, workspace, status, tokens, cost, latency in (
        ("r1", "ws-1", "ok", 100, 200, 40),
        ("r1", "ws-1", "degraded", 25, 50, 80),
        ("r2", "ws-2", "ok", 999, 999, 1),
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
                        "api_key": "secret",
                        "base_url": "https://secret.example/v1",
                    }
                },
            )
        )
    await kernel.store.create_hitl_request(
        HITLRequest(
            id="hitl-1",
            tenant_id=T,
            run_id="r1",
            type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING,
            question="Approve the next deploy step?",
            context="deployment",
            options=["approve", "deny"],
            requested_by="opencode-worker",
            workspace_id="ws-1",
        ),
    )
    await kernel.store.create_hitl_request(
        HITLRequest(
            id="hitl-2",
            tenant_id=T,
            run_id="r2",
            type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING,
            question="Other workspace approval",
            context="deployment",
            options=["approve", "deny"],
            requested_by="opencode-worker",
            workspace_id="ws-2",
        ),
    )


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-12")
def test_console_overview_requires_authentication():
    kernel = asyncio.run(_kernel())
    assert _client_for(kernel).get("/v1/console/overview").status_code == 401


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-12")
def test_console_overview_is_scoped_bounded_and_redacted():
    kernel = asyncio.run(_kernel())
    asyncio.run(_seed(kernel))

    resp = _client_for(kernel, workspace_id="ws-1").get(
        "/v1/console/overview?limit=1",
        headers={"authorization": "Bearer good"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == T
    assert body["workspace_id"] == "ws-1"
    assert body["platform"]["components"][0]["metadata"] == {"alive_seconds": 120}
    assert body["platform"]["runtimes"][0]["id"] == "opencode"
    assert body["cost"]["total_cost_micros"] == 250
    assert body["cost"]["by_actor"] == {"opencode-worker": 250}
    assert body["budgets"][0]["spent_micros"] == 250
    assert len(body["recent_runs"]) == 1
    assert body["recent_runs"][0]["run_id"] == "r1"
    assert body["approvals"] == [
        {
            "id": "hitl-1",
            "run_id": "r1",
            "work_item_id": None,
            "type": "approval",
            "urgency": "blocking",
            "status": "pending",
            "question": "Approve the next deploy step?",
            "options": ["approve", "deny"],
            "assignee": None,
            "timeout_at": None,
        }
    ]
    assert body["models"][0]["calls"] == 2
    assert body["models"][0]["cost_micros"] == 250

    scoped_rendered = repr({
        "platform": body["platform"],
        "models": body["models"],
        "cost": body["cost"],
        "budgets": body["budgets"],
        "recent_runs": body["recent_runs"],
        "approvals": body["approvals"],
    }).lower()
    rendered = repr(body).lower()
    assert "r2" not in rendered
    assert "999" not in scoped_rendered
    assert "rpa_secret" not in rendered
    assert "secret.example" not in rendered
    assert "base_url" not in rendered
    assert "api_key" not in rendered
    assert "never" not in rendered
