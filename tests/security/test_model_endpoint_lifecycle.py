"""Recoverable, governed model-endpoint withdrawal contracts."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.config.manifest import ModelsConfig
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.model_router import select_model_endpoint
from boltrig.fleet.model_router import endpoint_id_for_modality
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.call_profiles import resolve_call_profiles
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


class _Catalogue:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def list_models(self) -> dict:
        return self.result


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

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "generic-split-agent",
            "runtime": "codex",
            "model_endpoint": "text-only",
            "model_routes": {"vision": "vision-only"},
        },
    )
    generic_split = next(
        item
        for item in await kernel.store.list_all_capabilities(T)
        if item.name == "generic-split-agent"
    )
    assert generic_split.endpoint_for("text") == "text-only"
    assert generic_split.endpoint_for("vision") == "vision-only"
    with pytest.raises(ModelEndpointUnavailable):
        await select_model_endpoint(
            kernel.store,
            T,
            "text-only",
            sensitive=False,
            modality="vision",
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-37")
async def test_agent_model_routes_keep_voice_directions_separate_and_credential_free() -> None:
    kernel = await _kernel()
    for endpoint_id, modality in (
        ("local-whisper", "stt"),
        ("fish-audio", "tts"),
        ("omnivoice", "realtime"),
    ):
        await kernel.store.upsert_model_endpoint(
            ModelEndpoint(
                id=endpoint_id,
                tenant_id=T,
                kind="local" if endpoint_id == "local-whisper" else "bifrost",
                model=endpoint_id,
                modalities=(modality,),
            )
        )

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "voice-agent",
            "runtime": "codex",
            "model_routes": {
                "stt": "local-whisper",
                "tts": "fish-audio",
                "realtime": "omnivoice",
            },
        },
    )
    stored = next(
        item for item in await kernel.store.list_all_capabilities(T)
        if item.name == "voice-agent"
    )
    assert stored.endpoint_for("stt") == "local-whisper"
    assert stored.endpoint_for("tts") == "fish-audio"
    assert stored.endpoint_for("realtime") == "omnivoice"
    assert "api_key" not in repr(stored.model_routes)

    with pytest.raises(ValueError, match="unsupported model route modalities"):
        AgentCapability(
            name="invalid-voice-agent",
            tenant_id=T,
            runtime="codex",
            supported_skills=["*"],
            max_depth=1,
            is_ephemeral=True,
            cost_tier="standard",
            model_routes={"voice": "omnivoice"},
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-37")
async def test_capability_authoring_rejects_conflicting_legacy_and_generic_routes() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="reviewed-safe",
            tenant_id=T,
            kind="bifrost",
            model="reviewed-model",
            modalities=("text", "vision"),
        )
    )

    with pytest.raises(AdapterFailure) as conflict:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            {
                "name": "conflicting-agent",
                "runtime": "codex",
                "model_endpoint": "unreviewed-missing",
                "model_routes": {"text": "reviewed-safe"},
            },
            _context("conflicting-agent"),
        )
    assert conflict.value.reason == "model_endpoint_binding_conflict"
    assert await kernel.store.list_all_capabilities(T) == []

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "matching-agent",
            "runtime": "codex",
            "model_endpoint": "reviewed-safe",
            "model_routes": {"text": "reviewed-safe"},
        },
    )
    matching = (await kernel.store.list_all_capabilities(T))[0]
    assert matching.endpoint_for("text") == "reviewed-safe"

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "generic-only-agent",
            "runtime": "codex",
            "model_routes": {"text": "reviewed-safe"},
        },
    )
    generic_only = next(
        item
        for item in await kernel.store.list_all_capabilities(T)
        if item.name == "generic-only-agent"
    )
    assert generic_only.model_endpoint == "reviewed-safe"
    assert generic_only.endpoint_for("text") == "reviewed-safe"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-37")
async def test_capability_approval_rebinds_when_a_voice_route_changes() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="voice-route",
            tenant_id=T,
            kind="xai",
            model="voice-a",
            modalities=("realtime",),
        )
    )
    params = {
        "name": "voice-agent",
        "runtime": "codex",
        "model_routes": {"realtime": "voice-route"},
    }
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            params,
            _context("voice-route-a"),
        )
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")

    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="voice-route",
            tenant_id=T,
            kind="xai",
            model="voice-b",
            modalities=("realtime",),
        )
    )
    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.capability.upsert",
            params,
            _context("voice-route-a"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    assert await kernel.store.list_all_capabilities(T) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-37")
async def test_realtime_call_profile_requires_an_active_realtime_endpoint() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="wrong-modality",
            tenant_id=T,
            kind="xai",
            model="voice-model",
            modalities=("text",),
        )
    )
    await kernel.store.upsert_capability(
        AgentCapability(
            name="voice-agent",
            tenant_id=T,
            runtime="codex",
            supported_skills=["*"],
            max_depth=1,
            is_ephemeral=True,
            cost_tier="standard",
            model_routes={"realtime": "wrong-modality"},
        )
    )

    profile, reason = await resolve_call_profiles(
        kernel,
        Principal(tenant_id=T, subject="owner"),
        {"agent_profile_id": "voice-agent"},
    )
    assert profile is None
    assert reason == "agent_model_endpoint_unavailable"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-37")
async def test_governed_xai_route_requires_an_exact_immutable_model_id() -> None:
    kernel = await _kernel()
    with pytest.raises(AdapterFailure) as invalid:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            {
                "id": "voice-route",
                "kind": "xai",
                "model": "grok-voice-latest",
                "modalities": ["realtime"],
            },
            _context("mutable-voice-model"),
        )
    assert invalid.value.reason == "adapter_conflict"
    assert await kernel.store.get_model_endpoint(T, "voice-route") is None


async def _kernel(*, model_catalogue=None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
            model_catalogue=model_catalogue,
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


async def _held_approval(kernel: Kernel, verb: str, params: dict) -> str:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(f"hold-{verb}"))
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    return held.value.hitl_request_id


def _two_party_barrier():
    arrived = 0
    release = asyncio.Event()

    async def wait() -> None:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            release.set()
        await release.wait()

    return wait


def _success_count(results: list[object]) -> int:
    return sum(not isinstance(result, BaseException) for result in results)


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_endpoint_authoring_enforces_local_sensitive_and_exact_bifrost_ids() -> None:
    kernel = await _kernel()

    with pytest.raises(AdapterFailure) as hosted_sensitive:
        await _approved(
            kernel,
            "control.model_endpoint.upsert",
            {
                "id": "sensitive-hosted",
                "kind": "bifrost",
                "model": "provider/model-a",
                "data_class": "sensitive",
            },
        )
    assert hosted_sensitive.value.reason == "adapter_conflict"
    assert await kernel.store.get_model_endpoint(T, "sensitive-hosted") is None

    with pytest.raises(AdapterFailure) as mutable_bifrost:
        await _approved(
            kernel,
            "control.model_endpoint.upsert",
            {
                "id": "mutable-bifrost",
                "kind": "bifrost",
                "model": "provider/latest",
                "data_class": "standard",
            },
        )
    assert mutable_bifrost.value.reason == "adapter_conflict"
    assert await kernel.store.get_model_endpoint(T, "mutable-bifrost") is None

    created = await _approved(
        kernel,
        "control.model_endpoint.upsert",
        {
            "id": "local-sensitive",
            "kind": "local",
            "model": "local-model",
            "data_class": "sensitive",
        },
    )
    assert created["id"] == "local-sensitive"


@pytest.mark.security
@pytest.mark.invariant("SEC-12")
async def test_bifrost_authoring_requires_live_exact_catalogue_modalities() -> None:
    advertised = _Catalogue(
        {
            "status": "ok",
            "reason": None,
            "models": [
                {
                    "id": "cloudflare/@cf/meta/llama-3.1-8b-instruct",
                    "name": "ignored display name",
                    "input_modalities": ["text", "image"],
                }
            ],
        }
    )
    kernel = await _kernel(model_catalogue=advertised)
    created = await _approved(
        kernel,
        "control.model_endpoint.upsert",
        {
            "id": "catalogued",
            "kind": "bifrost",
            "model": "cloudflare/@cf/meta/llama-3.1-8b-instruct",
            "modalities": ["text", "vision"],
        },
    )
    assert created["id"] == "catalogued"

    for model, modalities in (
        ("provider/not-advertised", ["text"]),
        ("cloudflare/@cf/meta/llama-3.1-8b-instruct", ["text", "vision"]),
    ):
        catalogue = (
            advertised
            if model.startswith("cloudflare")
            else _Catalogue({"status": "ok", "reason": None, "models": []})
        )
        if model.startswith("cloudflare"):
            catalogue = _Catalogue(
                {
                    "status": "ok",
                    "reason": None,
                    "models": [{"id": model, "name": model, "input_modalities": ["text"]}],
                }
            )
        rejected_kernel = await _kernel(model_catalogue=catalogue)
        with pytest.raises(AdapterFailure) as rejected:
            await rejected_kernel.invoke(
                "control",
                "control.model_endpoint.upsert",
                {
                    "id": "rejected",
                    "kind": "bifrost",
                    "model": model,
                    "modalities": modalities,
                },
                _context("catalogue-rejected"),
            )
        assert rejected.value.reason in {
            "model_endpoint_not_advertised",
            "adapter_conflict",
        }

    unavailable = await _kernel(
        model_catalogue=_Catalogue(
            {"status": "unavailable", "reason": "gateway_timeout", "models": []}
        )
    )
    with pytest.raises(AdapterFailure) as failed_closed:
        await unavailable.invoke(
            "control",
            "control.model_endpoint.upsert",
            {"id": "unavailable", "kind": "bifrost", "model": "provider/model-a"},
            _context("catalogue-unavailable"),
        )
    assert failed_closed.value.reason == "model_catalogue_unavailable"


@pytest.mark.security
async def test_endpoint_authoring_refuses_unsafe_opaque_choice_id() -> None:
    kernel = await _kernel()
    with pytest.raises(AdapterFailure) as invalid:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            {
                "id": "unsafe id",
                "kind": "bifrost",
                "model": "provider/model-a",
            },
            _context("unsafe-id"),
        )
    assert invalid.value.reason == "model_endpoint_choice_id_invalid"


@pytest.mark.security
@pytest.mark.parametrize(
    "endpoint_id",
    ["with/slash", "%2F", "%252F", "query?", "fragment#", "back\\slash", ".", "..", "café", "x" * 161],
)
async def test_endpoint_authoring_refuses_non_path_segment_ids(endpoint_id: str) -> None:
    kernel = await _kernel()
    with pytest.raises(AdapterFailure) as invalid:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            {"id": endpoint_id, "kind": "local", "model": "local-model"},
            _context("unsafe-path-segment"),
        )
    assert invalid.value.reason == "model_endpoint_choice_id_invalid"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_maximum_safe_endpoint_id_roundtrips_through_detail_and_retire() -> None:
    kernel = await _kernel()
    endpoint_id = "x" * 160
    await _approved(
        kernel,
        "control.model_endpoint.upsert",
        {"id": endpoint_id, "kind": "local", "model": "local-model"},
    )
    client = TestClient(create_app(kernel))
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }
    detail = client.get(f"/v1/model-endpoints/{endpoint_id}", headers=author)
    assert detail.status_code == 200
    assert detail.json()["endpoint"]["id"] == endpoint_id
    await _approved(kernel, "control.model_endpoint.retire", {"id": endpoint_id})
    stored = await kernel.store.get_model_endpoint(T, endpoint_id)
    assert stored is not None and stored.is_active is False


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_two_approved_endpoint_edits_compare_and_swap_once(monkeypatch) -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("contended"))
    first = {"id": "contended", "kind": "local", "model": "model-one"}
    second = {"id": "contended", "kind": "local", "model": "model-two"}
    approval_a = await _held_approval(kernel, "control.model_endpoint.upsert", first)
    approval_b = await _held_approval(kernel, "control.model_endpoint.upsert", second)
    original = kernel.store.compare_and_upsert_model_endpoint
    barrier = _two_party_barrier()

    async def contested(*args, **kwargs):
        await barrier()
        return await original(*args, **kwargs)

    monkeypatch.setattr(kernel.store, "compare_and_upsert_model_endpoint", contested)
    results = await asyncio.gather(
        kernel.invoke(
            "control", "control.model_endpoint.upsert", first,
            _context("hold-control.model_endpoint.upsert"), approval_id=approval_a,
        ),
        kernel.invoke(
            "control", "control.model_endpoint.upsert", second,
            _context("hold-control.model_endpoint.upsert"), approval_id=approval_b,
        ),
        return_exceptions=True,
    )
    assert _success_count(results) == 1
    rejected = next(result for result in results if isinstance(result, AdapterFailure))
    assert rejected.reason == "adapter_conflict"
    stored = await kernel.store.get_model_endpoint(T, "contended")
    assert stored is not None and stored.revision == 2
    assert stored.model in {"model-one", "model-two"}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_approved_edit_and_lifecycle_change_compare_and_swap_once(monkeypatch) -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("lifecycle-race"))
    edit = {"id": "lifecycle-race", "kind": "local", "model": "edited"}
    retire = {"id": "lifecycle-race"}
    edit_approval = await _held_approval(kernel, "control.model_endpoint.upsert", edit)
    retire_approval = await _held_approval(kernel, "control.model_endpoint.retire", retire)
    upsert = kernel.store.compare_and_upsert_model_endpoint
    lifecycle = kernel.store.compare_and_set_model_endpoint_active
    barrier = _two_party_barrier()

    async def contested_upsert(*args, **kwargs):
        await barrier()
        return await upsert(*args, **kwargs)

    async def contested_lifecycle(*args, **kwargs):
        await barrier()
        return await lifecycle(*args, **kwargs)

    monkeypatch.setattr(kernel.store, "compare_and_upsert_model_endpoint", contested_upsert)
    monkeypatch.setattr(
        kernel.store, "compare_and_set_model_endpoint_active", contested_lifecycle
    )
    results = await asyncio.gather(
        kernel.invoke(
            "control", "control.model_endpoint.upsert", edit,
            _context("hold-control.model_endpoint.upsert"), approval_id=edit_approval,
        ),
        kernel.invoke(
            "control", "control.model_endpoint.retire", retire,
            _context("hold-control.model_endpoint.retire"), approval_id=retire_approval,
        ),
        return_exceptions=True,
    )
    assert _success_count(results) == 1
    stored = await kernel.store.get_model_endpoint(T, "lifecycle-race")
    assert stored is not None and stored.revision == 2


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_approved_fallback_use_and_retirement_compare_and_swap_once(monkeypatch) -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(_endpoint("fallback-race"))
    create = {
        "id": "new-primary",
        "kind": "local",
        "model": "local-model",
        "fallback": "fallback-race",
    }
    retire = {"id": "fallback-race"}
    create_approval = await _held_approval(
        kernel, "control.model_endpoint.upsert", create
    )
    retire_approval = await _held_approval(
        kernel, "control.model_endpoint.retire", retire
    )
    upsert = kernel.store.compare_and_upsert_model_endpoint
    lifecycle = kernel.store.compare_and_set_model_endpoint_active
    barrier = _two_party_barrier()

    async def contested_upsert(*args, **kwargs):
        await barrier()
        return await upsert(*args, **kwargs)

    async def contested_lifecycle(*args, **kwargs):
        await barrier()
        return await lifecycle(*args, **kwargs)

    monkeypatch.setattr(kernel.store, "compare_and_upsert_model_endpoint", contested_upsert)
    monkeypatch.setattr(
        kernel.store, "compare_and_set_model_endpoint_active", contested_lifecycle
    )
    results = await asyncio.gather(
        kernel.invoke(
            "control", "control.model_endpoint.upsert", create,
            _context("hold-control.model_endpoint.upsert"), approval_id=create_approval,
        ),
        kernel.invoke(
            "control", "control.model_endpoint.retire", retire,
            _context("hold-control.model_endpoint.retire"), approval_id=retire_approval,
        ),
        return_exceptions=True,
    )
    assert _success_count(results) == 1


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


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-14")
async def test_endpoint_upsert_approval_rebinds_when_a_capability_reference_is_added() -> None:
    kernel = await _kernel()
    await kernel.store.upsert_model_endpoint(
        ModelEndpoint(
            id="reference-drift",
            tenant_id=T,
            kind="local",
            model="model-before-review",
            modalities=("text", "vision"),
        )
    )
    params = {
        "id": "reference-drift",
        "kind": "local",
        "model": "model-after-review",
        "modalities": ["text", "vision"],
    }
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            params,
            _context("reference-drift"),
        )
    await kernel.hitl.answer(
        T, held.value.hitl_request_id, "approve", "endpoint-reviewer"
    )

    await _approved(
        kernel,
        "control.capability.upsert",
        {
            "name": "new-reference",
            "runtime": "codex",
            "model_endpoint": "reference-drift",
        },
    )

    with pytest.raises(PendingHuman) as rebound:
        await kernel.invoke(
            "control",
            "control.model_endpoint.upsert",
            params,
            _context("reference-drift"),
            approval_id=held.value.hitl_request_id,
        )
    assert rebound.value.hitl_request_id != held.value.hitl_request_id
    current = await kernel.store.get_model_endpoint(T, "reference-drift")
    assert current is not None and current.model == "model-before-review"
