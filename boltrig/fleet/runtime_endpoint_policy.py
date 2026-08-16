"""Model-route helpers for the Codex-owned ``RuntimeResolver``."""

from __future__ import annotations

from boltrig.models import AgentCapability, ModelEndpoint

from .model_gateway import ModelGateway, apply_gateway


def served_model_route(endpoint: ModelEndpoint | None) -> dict[str, str] | None:
    """Project model/provider audit truth without topology or credentials."""

    if endpoint is None or not endpoint.model:
        return None
    route = {"model": str(endpoint.model)}
    if endpoint.kind:
        route["provider"] = str(endpoint.kind)
    return route


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
    """Bind a Codex conversation to the composed Bifrost route."""

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


__all__ = ["apply_conversation_gateway", "served_model_route"]
