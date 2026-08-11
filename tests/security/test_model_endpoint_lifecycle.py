"""Recoverable, governed model-endpoint withdrawal contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.manifest import ModelsConfig
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.model_router import select_model_endpoint
from boltrig.fleet.model_router import endpoint_id_for_modality
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AdapterFailure,
    AgentCapability,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    ModelEndpointUnavailable,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "model-endpoint-lifecycle"


def _endpoint(
    endpoint_id: str,
    *,
    model: str = "served-model",
    fallback: str | None = None,
) -> ModelEndpoint:
    return ModelEndpoint(
        id=endpoint_id,
        tenant_id=T,
        kind="openai",
        model=model,
        base_url=f"https://{endpoint_id}.example.test/v1",
        fallback=fallback,
        data_class="standard",
    )


def _context(label: str) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{label}",
        extra={"principal_role": "org-admin", "principal_scope": {"all": True}},
    )


@pytest.mark.security
async def test_agent_accepts_multimodal_or_explicit_text_and_vision_routes() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="multimodal",
            tenant_id=T,
            kind="bifrost",
            model="vision-model",
            modalities=("text", "vision"),
        )
    )
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="text-only",
            tenant_id=T,
            kind="bifrost",
            model="text-model",
            modalities=("text",),
        )
    )
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="vision-only",
            tenant_id=T,
            kind="bifrost",
            model="vision-model-2",
            modalities=("vision",),
        )
    )

    with pytest.raises(AdapterFailure) as invalid:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            {
                "name": "invalid-single",
                "runtime": "codex",
                "model_endpoint": "text-only",
            },
            _context("invalid-single"),
        )
    assert invalid.value.reason == "multimodal_model_required"

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "multimodal-agent",
            "runtime": "codex",
            "model_endpoint": "multimodal",
        },
    )
    split = await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "split-agent",
            "runtime": "codex",
            "model_endpoint": "text-only",
            "vision_model_endpoint": "vision-only",
        },
    )
    assert split["capability_status"] == "active"
    stored = next(
        item
        for item in await kernel.store.list_all_capabilities(T)
        if item.name == "split-agent"
    )
    assert stored.model_endpoint == "text-only"
    assert stored.vision_model_endpoint == "vision-only"
    assert endpoint_id_for_modality(stored, "text") == "text-only"
    assert endpoint_id_for_modality(stored, "vision") == "vision-only"
    with pytest.raises(ModelEndpointUnavailable):
        await select_model_endpoint(
            kernel.store,
            T,
            "text-only",
            sensitive=False,
            modality="vision",
        )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store, loader=kernel.loader, registry=kernel.registry
        ),
    )
    return kernel


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "reviewer"
    )
    return await kernel.invoke(
        "control",
        verb,
        params,
        _context(verb),
        approval_id=held.value.hitl_request_id,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_author_inventory_keeps_both_states_and_exposes_retained_references() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("active"))
    await kernel.store.upsert_model_endpoint(_endpoint("retired"))
    await kernel.store.upsert_model_endpoint(
        _endpoint("secondary", fallback="retired")
    )
    await kernel.store.set_model_endpoint_active(T, "retired", False)
    await kernel.store.upsert_capability(
        AgentCapability(
            name="archivist",
            tenant_id=T,
            runtime="codex",
            supported_skills=["records/*"],
            max_depth=1,
            is_ephemeral=False,
            cost_tier="standard",
            model_endpoint="retired",
        )
    )
    client = TestClient(create_app(kernel))
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    inventory = client.get("/v1/model-endpoints", headers=author)
    assert inventory.status_code == 200
    assert [(row["id"], row["status"]) for row in inventory.json()["endpoints"]] == [
        ("active", "active"),
        ("retired", "retired"),
        ("secondary", "active"),
    ]
    detail = client.get("/v1/model-endpoints/retired", headers=author)
    assert detail.status_code == 200
    assert detail.json()["endpoint"]["status"] == "retired"
    assert detail.json()["endpoint"]["references"] == {
        "capabilities": ["archivist"],
        "fallbacks": ["secondary"],
    }
    assert detail.json()["endpoint"]["base_url"].startswith("https://retired.")

    pending = client.post("/v1/model-endpoints/active/retire", headers=author)
    assert pending.status_code == 202
    assert pending.json()["status"] == "pending_human"
    member = {**author, "x-boltrig-role": "member"}
    assert client.get("/v1/model-endpoints/retired", headers=member).status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_process_model_policy_projection_names_real_consumers_without_topology() -> None:
    kernel = await _kernel()
    sensitive = ModelEndpoint(
        id="private-local",
        tenant_id=T,
        kind="local",
        model="private-model",
        base_url="https://private-model.example.test/secret-path",
        fallback=None,
        data_class="sensitive",
    )
    default = _endpoint("stored-default", model="default-model")
    await kernel.store.upsert_model_endpoint(sensitive)
    await kernel.store.upsert_model_endpoint(default)
    client = TestClient(
        create_app(
            kernel,
            platform={
                "model_policy": ModelsConfig(
                    endpoints=(sensitive, default),
                    default=default.id,
                    sensitive_endpoint=sensitive.id,
                    prices={
                        "private-model": {"input": 0.25, "output": 1.5},
                    },
                )
            },
        )
    )
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    response = client.get("/v1/model-policy", headers=author)
    assert response.status_code == 200
    policy = response.json()["policy"]
    assert policy["state"] == "configured"
    assert policy["default"] == {
        "endpoint_id": "stored-default",
        "state": "active",
        "serving_state": "inactive_no_consumer",
    }
    assert policy["sensitive"] == {
        "endpoint_id": "private-local",
        "state": "active",
        "serving_state": "active_process_policy",
        "eligible": True,
    }
    assert policy["prices"] == [
        {
            "model": "private-model",
            "input_micros_per_token": 0.25,
            "output_micros_per_token": 1.5,
        }
    ]
    assert len(policy["generation"]) == 64
    assert "private-model.example.test" not in response.text
    assert "secret-path" not in response.text
    assert "base_url" not in response.text
    assert client.get(
        "/v1/model-policy",
        headers={**author, "x-boltrig-role": "member"},
    ).status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_direct_endpoint_route_finalizes_with_caller_held_approval() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("approved-endpoint"))
    client = TestClient(create_app(kernel))
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }

    pending = client.post(
        "/v1/model-endpoints/approved-endpoint/retire",
        headers=author,
    )
    assert pending.status_code == 202
    approval_id = pending.json()["hitl_request_id"]
    await kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")

    completed = client.post(
        "/v1/model-endpoints/approved-endpoint/retire",
        headers={**author, "x-boltrig-approval-id": approval_id},
        json={},
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "status": "ok",
        "id": "approved-endpoint",
        "model_endpoint_status": "retired",
    }
    stored = await kernel.store.get_model_endpoint(T, "approved-endpoint")
    assert stored is not None and stored.is_active is False


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_retirement_preserves_configuration_and_every_reference_fails_closed() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("fallback"))
    await kernel.store.upsert_model_endpoint(
        _endpoint("primary", fallback="fallback")
    )
    await kernel.store.upsert_capability(
        AgentCapability(
            name="researcher",
            tenant_id=T,
            runtime="codex",
            supported_skills=["research/*"],
            max_depth=2,
            is_ephemeral=True,
            cost_tier="standard",
            model_endpoint="primary",
        )
    )

    retired = await _approved(
        kernel, "control.model_endpoint.retire", {"id": "primary"}
    )
    assert retired == {
        "id": "primary",
        "model_endpoint_status": "retired",
    }
    stored = await kernel.store.get_model_endpoint(T, "primary")
    assert stored is not None
    assert stored.model == "served-model"
    assert stored.base_url == "https://primary.example.test/v1"
    assert stored.fallback == "fallback"
    assert stored.is_active is False

    # A retired primary is a hard stop. Its stored fallback is not a side door.
    with pytest.raises(ModelEndpointUnavailable):
        await select_model_endpoint(
            kernel.store, T, "primary", sensitive=False
        )

    with pytest.raises(AdapterFailure) as binding:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            {
                "name": "new-worker",
                "runtime": "codex",
                "model_endpoint": "primary",
            },
            _context("bind-retired"),
        )
    assert binding.value.reason == "model_endpoint_binding_unavailable"

    with pytest.raises(AdapterFailure) as fallback:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            {
                "id": "new-endpoint",
                "kind": "openai",
                "model": "new-model",
                "fallback": "primary",
            },
            _context("fallback-retired"),
        )
    assert fallback.value.reason == "model_endpoint_fallback_unavailable"

    # An ordinary replacement may update configuration but cannot smuggle the
    # endpoint back into service.
    await kernel.store.upsert_model_endpoint(
        _endpoint("primary", model="edited-model", fallback="fallback")
    )
    assert (await kernel.store.get_model_endpoint(T, "primary")).is_active is False

    restored = await _approved(
        kernel, "control.model_endpoint.restore", {"id": "primary"}
    )
    assert restored == {
        "id": "primary",
        "model_endpoint_status": "active",
    }
    routed = await select_model_endpoint(
        kernel.store, T, "primary", sensitive=False
    )
    assert routed is not None and routed.model == "edited-model"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_endpoint_lifecycle_approval_is_bound_to_the_exact_mutable_state() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("mutable"))
    params = {"id": "mutable"}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control",
            "control.model_endpoint.retire",
            params,
            _context("retire"),
        )
    await kernel.store.upsert_model_endpoint(
        _endpoint("mutable", model="changed-after-review")
    )
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "reviewer"
    )

    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.model_endpoint.retire",
            params,
            _context("retire"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    current = await kernel.store.get_model_endpoint(T, "mutable")
    assert current is not None and current.is_active is True
    assert current.model == "changed-after-review"
