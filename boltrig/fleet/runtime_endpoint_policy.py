"""Endpoint/profile/gateway policy helpers for ``RuntimeResolver``."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import AgentCapability, InvocationContext, ModelEndpoint

from .model_gateway import ModelGateway, apply_gateway
from .model_profiles import apply_model_profile, select_model_profile
from .runtime import runtime_for_provider

_PROVIDER_NATIVE_RUNTIMES = frozenset({"openai", "claude-api"})


def served_model_route(endpoint: ModelEndpoint | None) -> dict[str, str] | None:
    """Project model/provider audit truth without topology or credentials."""

    if endpoint is None or not endpoint.model:
        return None
    route = {"model": str(endpoint.model)}
    if endpoint.kind:
        route["provider"] = str(endpoint.kind)
    return route


def apply_legacy_provider_route(
    *,
    tenant_id: str,
    capability: AgentCapability,
    endpoint: ModelEndpoint | None,
    explicit_endpoint: bool,
    resolution: Any,
    modality: str,
    pinned_policy: bool,
    sensitive: bool,
) -> tuple[ModelEndpoint | None, str | None]:
    """Apply legacy provider-native or scoped-key routing when lawful."""

    runtime_override = None
    if pinned_policy or sensitive:
        return endpoint, runtime_override
    if (
        explicit_endpoint
        and endpoint is not None
        and capability.runtime in _PROVIDER_NATIVE_RUNTIMES
    ):
        runtime_override = runtime_for_provider(endpoint.kind)
        if runtime_override is None and endpoint.kind in {
            "local",
            "openai-compatible",
        }:
            runtime_override = "openai"
    elif resolution is not None and not resolution.is_default:
        runtime_override = runtime_for_provider(resolution.provider)
        if runtime_override is not None:
            endpoint = _routed_endpoint(tenant_id, endpoint, resolution, modality)
    return endpoint, runtime_override


def apply_requested_model_profile(
    *,
    tenant_id: str,
    capability: AgentCapability,
    endpoint: ModelEndpoint | None,
    runtime_override: str | None,
    context: InvocationContext | None,
    pinned_policy: bool,
    sensitive: bool,
) -> tuple[ModelEndpoint | None, str | None, dict[str, str] | None]:
    if (
        context is None
        or sensitive
        or pinned_policy
        or capability.runtime == "codex"
    ):
        return endpoint, runtime_override, None
    profile = select_model_profile(dict(context.extra or {}))
    endpoint, profile_runtime, profile_route = apply_model_profile(
        endpoint, profile, tenant_id=tenant_id
    )
    if profile_runtime is not None:
        runtime_override = profile_runtime
    route = profile_route.audit_detail() if profile_route is not None else None
    return endpoint, runtime_override, route


def apply_conversation_gateway(
    endpoint: ModelEndpoint | None,
    *,
    gateway_url: str | None,
    bindings: ModelGateway,
    tenant_id: str,
    conversation_id: str | None,
    sensitive: bool,
    capability: AgentCapability,
    choice_id: str | None,
    pinned_policy: bool,
) -> ModelEndpoint | None:
    return apply_gateway(
        endpoint,
        gateway_url=gateway_url,
        binding=bindings,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        sensitive=sensitive,
        explicit_rebind=(
            choice_id is not None
            or (
                capability.runtime == "codex"
                and not sensitive
                and not pinned_policy
            )
        ),
    )


def _routed_endpoint(
    tenant_id: str,
    base: ModelEndpoint | None,
    resolution: Any,
    modality: str = "text",
) -> ModelEndpoint:
    model = resolution.model or (base.model if base is not None else "")
    base_url = resolution.base_url or (base.base_url if base is not None else None)
    if base is not None:
        return replace(base, model=model, base_url=base_url)
    return ModelEndpoint(
        id="ai-config",
        tenant_id=tenant_id,
        kind=(resolution.provider or "openai"),
        model=model,
        base_url=base_url,
        data_class="standard",
        modalities=("vision",) if modality == "vision" else ("text",),
    )


__all__ = [
    "apply_conversation_gateway",
    "apply_legacy_provider_route",
    "apply_requested_model_profile",
    "served_model_route",
]
