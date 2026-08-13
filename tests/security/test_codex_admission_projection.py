"""Worker sees the effective Codex OFF wall without changing execution."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.observability import codex_admission as admission_module
from boltrig.observability.codex_admission import (
    codex_admission_projection,
    codex_release_posture,
)
from boltrig.store import InMemoryStore


def test_uncomposed_codex_projection_claims_no_runtime_evidence() -> None:
    projected = codex_admission_projection(
        None,
        trusted_provider_configured=False,
    )
    assert projected["rollout"] == {
        "policy_source": "scaffold_not_composed",
        "mode": "off",
        "generation": None,
        "shadow_root_decisions": "disabled",
        "root_execution": "legacy_only",
        "assignment_admission": "inactive_never_called",
        "canary_decision": "unavailable_rollout_off",
    }
    assert projected["runtime"]["trusted_provider"] == "off"
    assert projected["runtime"]["runtime_config_production_ready"] is False
    assert projected["runtime"]["runtime_class_production_ready"] is False
    assert (
        projected["runtime"]["production_activation"]
        == "refused_unresolved_isolation_controls"
    )
    assert (
        projected["runtime"]["preflight_evidence"]
        == "unavailable_no_durable_cell_receipts"
    )
    assert projected["runtime"]["cell_liveness"] == "unavailable"
    assert projected["execution_changed_by_projection"] is False
    assert projected["release_posture"] == codex_release_posture()
    assert projected["release_posture"]["status"] == "blocked"
    assert projected["release_posture"]["fresh_authority_required"] is True
    assert len(projected["release_posture"]["quarantined_preflight_blockers"]) == 7


def test_two_constant_flips_cannot_promote_a_quarantined_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admission_module.CodexAgentRuntime, "production_ready", True)
    monkeypatch.setattr(
        admission_module, "CODEX_RUNTIME_CONFIG_PRODUCTION_READY", True
    )

    posture = codex_release_posture()
    projected = codex_admission_projection(None, trusted_provider_configured=True)

    assert posture["runtime_class_production_ready"] is True
    assert posture["runtime_config_production_ready"] is True
    assert posture["status"] == "blocked"
    assert len(posture["quarantined_preflight_blockers"]) == 7
    assert (
        projected["runtime"]["production_activation"]
        == "refused_unresolved_isolation_controls"
    )


def test_composed_shadow_stack_is_still_off_and_execution_neutral() -> None:
    projected = codex_admission_projection(
        SimpleNamespace(policy_generation=7),
        trusted_provider_configured=True,
    )
    assert projected["rollout"]["policy_source"] == "immutable_off_scaffold"
    assert projected["rollout"]["generation"] == 7
    assert (
        projected["rollout"]["shadow_root_decisions"]
        == "active_execution_neutral"
    )
    assert projected["runtime"]["trusted_provider"] == (
        "configured_development_only"
    )


def test_platform_status_projects_only_redacted_codex_composition() -> None:
    async def resolver(request: Request) -> Principal:
        if request.headers.get("authorization") != "Bearer member-session":
            raise HTTPException(status_code=401, detail="invalid session")
        return Principal(tenant_id="acme", subject="alice", role="member")

    client = TestClient(
        create_app(
            Kernel(InMemoryStore()),
            principal_resolver=resolver,
            platform={
                "codex_execution": SimpleNamespace(
                    policy_generation=3,
                    upstream_key="NEVER-SERIALIZE",
                ),
                "codex_trusted_provider_configured": True,
            },
        )
    )
    response = client.get(
        "/v1/platform/status",
        headers={"authorization": "Bearer member-session"},
    )
    assert response.status_code == 200
    admission = response.json()["codex_admission"]
    assert admission["rollout"]["generation"] == 3
    assert admission["rollout"]["mode"] == "off"
    assert admission["runtime"]["trusted_provider"] == (
        "configured_development_only"
    )
    assert "NEVER-SERIALIZE" not in response.text
    assert "upstream_key" not in response.text
