"""Purpose-built seal-before-approval lifecycle for AI provider keys."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boltrig.identity.bifrost_user_binding import (
    BifrostUserBinding,
    BifrostUserGateway,
    binding_credential_ref,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.hitl_expiry import expire_tenant_once
from boltrig.models import (
    AiConfig,
    GrantSet,
    Organisation,
    TenantPermissions,
    utcnow,
)
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed

T = "ai-proposal-tenant"
SECRET = "sk-proposal-secret-material-0123456789"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _bounded_bifrost(monkeypatch):
    """Proposal tests exercise governance, with a runnable gateway boundary."""

    monkeypatch.setenv("BOLTRIG_MODEL_GATEWAY_URL", "http://bifrost:8080/v1")

    async def ensure(self, store, tenant_id, resolution, provider_key):
        assert provider_key
        ref = binding_credential_ref(tenant_id, resolution)
        provider = str(resolution.provider)
        model = str(resolution.model)
        model_id = model if "/" in model else f"{provider}/{model}"
        binding = BifrostUserBinding(
            provider=provider,
            model_id=model_id,
            provider_key_id="provider-key",
            virtual_key_id="virtual-key",
            virtual_key="vk-test-only",
            credential_ref=ref,
        )
        await store.set_credential_ref(
            tenant_id,
            ref,
            {
                "secret": binding.virtual_key,
                "provider": binding.provider,
                "model_id": binding.model_id,
                "source_credential_ref": resolution.credential_ref,
                "provider_key_id": binding.provider_key_id,
                "virtual_key_id": binding.virtual_key_id,
            },
        )
        return binding

    monkeypatch.setattr(BifrostUserGateway, "ensure", ensure)


def _run(coro):
    return asyncio.run(coro)


def _headers(subject="admin", role="org-admin"):
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


def _app():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    _run(
        store.create_org(
            Organisation(
                id=T,
                name="AI proposals",
                slug="ai-proposals",
                allow_own_ai_keys=True,
            )
        )
    )
    kernel = Kernel(store)
    return store, kernel, TestClient(create_app(kernel, platform={}))


def _stage(client, *, secret=SECRET, headers=None, modality=None):
    body = {
        "level": "org",
        "provider": "openai",
        "model": "gpt-5",
        "base_url": "https://api.openai.example/v1",
        "api_key": secret,
    }
    if modality is not None:
        body["modality"] = modality
    response = client.put(
        "/v1/ai-keys",
        headers=headers or _headers(),
        json=body,
    )
    assert response.status_code == 202, response.text
    return response


@pytest.mark.security
def test_vision_key_proposal_is_sealed_and_stored_as_a_separate_route() -> None:
    store, kernel, client = _app()
    staged = _stage(client, modality="vision")
    proposal_id = staged.json()["proposal"]["id"]
    assert staged.json()["proposal"]["modality"] == "vision"
    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    _run(kernel.hitl.answer(T, proposal.approval_id, "approve", "reviewer"))
    applied = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_headers()
    )
    assert applied.status_code == 200
    config = _run(store.get_ai_config(T, "org", T, "vision"))
    assert config is not None and config.modality == "vision"
    assert _run(store.get_ai_config(T, "org", T)) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
def test_secret_is_sealed_before_approval_and_exactly_once_consumed() -> None:
    store, kernel, client = _app()
    injected = client.put(
        "/v1/ai-keys",
        headers=_headers(),
        json={
            "level": "org",
            "provider": "openai",
            "model": "gpt-5",
            "api_key": SECRET,
            "approval_id": "caller-controlled",
        },
    )
    assert injected.status_code == 400
    assert _run(
        store.list_ai_key_secret_proposals(T, "admin", None)
    ) == []
    staged = _stage(client)
    body = staged.json()
    proposal_id = body["proposal"]["id"]
    assert "hitl_request_id" not in body
    assert SECRET not in staged.text

    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert proposal is not None and proposal.approval_id
    request = _run(store.get_hitl_request(T, proposal.approval_id))
    audit = _run(store.audit_query(T, limit=100))
    raw_stage = store._creds[(T, f"staged_ai_key:{proposal_id}")]
    assert is_sealed(raw_stage)
    for representation in (
        repr(proposal),
        repr(request),
        repr([row.detail for row in audit]),
        json.dumps(raw_stage),
    ):
        assert SECRET not in representation

    _run(kernel.hitl.answer(T, proposal.approval_id, "approve", "reviewer"))
    state = client.get(
        f"/v1/ai-keys/proposals/{proposal_id}", headers=_headers()
    )
    assert state.json()["status"] == "approved"

    applied = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_headers()
    )
    assert applied.status_code == 200 and applied.json()["status"] == "ok"
    assert SECRET not in applied.text
    config = _run(store.get_ai_config(T, "org", T))
    assert config is not None
    assert _run(store.get_credential_ref(T, config.credential_ref))["secret"] == SECRET
    consumed = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert consumed.status == "consumed" and consumed.secret_ref is None

    replay = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_headers()
    )
    assert replay.status_code == 409 and replay.json()["status"] == "consumed"
    assert _run(store.get_ai_config(T, "org", T)).credential_ref == config.credential_ref


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
def test_reject_expiry_and_edit_invalidation_remove_staged_material() -> None:
    for terminal in ("rejected", "expired", "invalidated"):
        store, kernel, client = _app()
        staged = _stage(client, secret=f"{SECRET}-{terminal}")
        proposal_id = staged.json()["proposal"]["id"]
        proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
        secret_ref = proposal.secret_ref
        if terminal == "rejected":
            _run(kernel.hitl.answer(T, proposal.approval_id, "reject", "reviewer"))
            assert _run(
                store.get_ai_key_secret_proposal(T, proposal_id)
            ).status == "rejected"
            response = client.get(
                f"/v1/ai-keys/proposals/{proposal_id}", headers=_headers()
            )
        elif terminal == "expired":
            store._ai_key_proposals[(T, proposal_id)] = replace(
                proposal, expires_at=utcnow() - timedelta(seconds=1)
            )
            assert _run(expire_tenant_once(store, T)) == 0
            response = client.get(
                f"/v1/ai-keys/proposals/{proposal_id}", headers=_headers()
            )
        else:
            response = client.delete(
                f"/v1/ai-keys/proposals/{proposal_id}", headers=_headers()
            )
        assert response.json()["status"] == terminal
        ended = _run(store.get_ai_key_secret_proposal(T, proposal_id))
        assert ended.status == terminal and ended.secret_ref is None
        assert _run(store.has_credential_ref(T, secret_ref)) is False
        assert _run(store.get_ai_config(T, "org", T)) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
def test_status_and_finalization_are_requester_only_and_restart_recoverable() -> None:
    store, kernel, client = _app()
    staged = _stage(client)
    proposal_id = staged.json()["proposal"]["id"]
    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))

    assert client.get(
        f"/v1/ai-keys/proposals/{proposal_id}",
        headers=_headers(subject="other"),
    ).status_code == 404
    assert client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize",
        headers=_headers(subject="other"),
    ).status_code == 404

    # A fresh app/kernel over the same durable store recovers the requester-only
    # proposal without a browser-held approval id or secret.
    restarted_kernel = Kernel(store)
    restarted = TestClient(create_app(restarted_kernel, platform={}))
    recovered = restarted.get("/v1/ai-keys/proposals", headers=_headers())
    assert recovered.json()["proposals"][0]["id"] == proposal_id
    assert recovered.json()["proposals"][0]["status"] == "pending"
    _run(restarted_kernel.hitl.answer(T, proposal.approval_id, "approve", "reviewer"))
    assert restarted.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_headers()
    ).json()["status"] == "ok"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
def test_policy_or_current_config_drift_refuses_and_clears_staging() -> None:
    # Current org policy is re-authorized after approval.
    store, kernel, client = _app()
    staged = client.put(
        "/v1/ai-keys",
        headers=_headers(subject="alice", role="member"),
        json={
            "level": "user",
            "provider": "openai",
            "model": "gpt-5",
            "api_key": SECRET,
        },
    )
    proposal_id = staged.json()["proposal"]["id"]
    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    _run(kernel.hitl.answer(T, proposal.approval_id, "approve", "reviewer"))
    org = _run(store.get_org(T))
    org.allow_own_ai_keys = False
    _run(store.update_org(org))
    denied = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize",
        headers=_headers(subject="alice", role="member"),
    )
    assert denied.status_code == 403
    invalidated = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert invalidated.status == "invalidated" and invalidated.secret_ref is None

    # The approved current-config snapshot is authoritative as well.
    store, kernel, client = _app()
    staged = _stage(client)
    proposal_id = staged.json()["proposal"]["id"]
    proposal = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    _run(kernel.hitl.answer(T, proposal.approval_id, "approve", "reviewer"))
    _run(store.set_credential_ref(T, "outside", {"secret": "other"}))
    _run(
        store.set_ai_config(
            AiConfig(
                tenant_id=T,
                level="org",
                scope_id=T,
                provider="other",
                model="other",
                credential_ref="outside",
            )
        )
    )
    drifted = client.post(
        f"/v1/ai-keys/proposals/{proposal_id}/finalize", headers=_headers()
    )
    assert drifted.status_code == 409
    assert drifted.json()["status"] == "invalidated"
    assert _run(store.get_ai_config(T, "org", T)).credential_ref == "outside"
    invalidated = _run(store.get_ai_key_secret_proposal(T, proposal_id))
    assert invalidated.status == "invalidated" and invalidated.secret_ref is None


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-33")
def test_worker_retains_only_the_opaque_proposal_after_secret_intake() -> None:
    worker = (
        ROOT / "apps/worker/src/components/AiKeyManagement.tsx"
    ).read_text(encoding="utf-8")
    assert "const [apiKey" not in worker
    assert "ref={apiKeyInput}" in worker
    assert worker.index('input.value = "";') < worker.index("await submission")
    assert "client.finalizeAiKeyProposal(proposal.id)" in worker
    assert "hitl_request_id" not in worker

    onboarding_form = (
        ROOT / "apps/worker/src/components/onboarding/ProviderStep.tsx"
    ).read_text(encoding="utf-8")
    onboarding_state = (
        ROOT / "apps/worker/src/components/onboarding/useProviderSetup.ts"
    ).read_text(encoding="utf-8")
    intake = (ROOT / "apps/worker/src/aiKeyIntake.ts").read_text(encoding="utf-8")
    assert 'ref={setup.apiKeyInput}' in onboarding_form
    assert "submitWriteOnlyAiKey(input" in onboarding_state
    assert "const [apiKey" not in onboarding_state
    assert intake.index('input.value = "";') < intake.index("return submission")

    spec = (
        ROOT / "boltrig/config/control_compat_specs.py"
    ).read_text(encoding="utf-8")
    start = spec.index('"control.ai_key.set"')
    end = spec.index('"control.ai_key.delete"', start)
    assert '"api_key": _STRING' not in spec[start:end]
    assert '"proposal_id": _STRING' in spec[start:end]
    assert '"secret_digest": _STRING' in spec[start:end]
