"""Safe caller-held finalization for generic Worker capability invocation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app
from tests.conftest import _build_kernel


ROOT = Path(__file__).resolve().parents[2]
HEADERS = {
    "x-boltrig-tenant": "acme",
    "x-boltrig-subject": "u1",
    "x-boltrig-grants": "ticket.create",
}


def _request(title: str, key: str) -> dict:
    return {
        "noun": "ticket",
        "verb": "ticket.create",
        "params": {"title": title},
        "idempotency_key": key,
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-28")
def test_caller_owned_approval_state_finalizes_the_exact_invocation_once():
    kernel, _ = asyncio.run(
        _build_kernel(blocking_verbs={"ticket.create"})
    )
    client = TestClient(create_app(kernel))
    body = _request("Exact approved ticket", "worker-invoke-exact")

    pending = client.post("/v1/invoke", json=body, headers=HEADERS)
    assert pending.status_code == 202
    request_id = pending.json()["hitl_request_id"]
    assert client.get(
        f"/v1/invoke/approvals/{request_id}", headers=HEADERS
    ).json() == {"status": "pending"}
    assert client.get(
        f"/v1/invoke/approvals/{request_id}",
        headers={**HEADERS, "x-boltrig-subject": "somebody-else"},
    ).status_code == 404

    asyncio.run(kernel.hitl.answer("acme", request_id, "approve", "reviewer"))
    assert client.get(
        f"/v1/invoke/approvals/{request_id}", headers=HEADERS
    ).json() == {"status": "approved"}

    completed = client.post(
        "/v1/invoke",
        json={**body, "approval_id": request_id},
        headers=HEADERS,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "ok"
    assert client.get(
        f"/v1/invoke/approvals/{request_id}", headers=HEADERS
    ).json() == {"status": "consumed"}

    replay = client.post(
        "/v1/invoke",
        json={**body, "approval_id": request_id},
        headers=HEADERS,
    )
    assert replay.status_code == 200
    assert replay.json() == completed.json()


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-28")
def test_caller_approval_state_projects_rejection_and_expiry_without_params():
    kernel, _ = asyncio.run(
        _build_kernel(blocking_verbs={"ticket.create"})
    )
    client = TestClient(create_app(kernel))

    rejected = client.post(
        "/v1/invoke",
        json=_request("Rejected ticket", "worker-invoke-reject"),
        headers=HEADERS,
    ).json()["hitl_request_id"]
    asyncio.run(kernel.hitl.answer("acme", rejected, "reject", "reviewer"))
    rejection = client.get(
        f"/v1/invoke/approvals/{rejected}", headers=HEADERS
    )
    assert rejection.json() == {"status": "rejected"}
    assert set(rejection.json()) == {"status"}

    expired = client.post(
        "/v1/invoke",
        json=_request("Expired ticket", "worker-invoke-expired"),
        headers=HEADERS,
    ).json()["hitl_request_id"]
    assert asyncio.run(kernel.store.expire_hitl("acme", expired))
    expiry = client.get(
        f"/v1/invoke/approvals/{expired}", headers=HEADERS
    )
    assert expiry.json() == {"status": "expired"}
    assert set(expiry.json()) == {"status"}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-28")
def test_worker_runner_has_no_raw_authority_or_changed_request_replay_surface():
    runner = (
        ROOT / "apps/worker/src/components/build/CapabilityRunner.tsx"
    ).read_text(encoding="utf-8")
    compiler = (
        ROOT / "sdks/web/src/capabilityInvocation.ts"
    ).read_text(encoding="utf-8")

    invoke_body = runner.split("const request: InvokeRequest = {", 1)[1].split(
        "};", 1
    )[0]
    assert "noun: selected.noun" in invoke_body
    assert "verb: selected.id" in invoke_body
    assert "params: built.params" in invoke_body
    assert "context:" not in invoke_body
    assert "approval_id:" not in invoke_body
    assert "raw" not in invoke_body.lower()
    assert "current === null ? null : { ...current, invalidated: true }" in runner
    assert "Check approval and continue" in runner
    assert "client.invokeApprovalState" in runner
    assert "secret-shaped fields require a purpose-built secure-input surface" in compiler
    assert "open-ended additional properties require a purpose-built surface" in compiler
