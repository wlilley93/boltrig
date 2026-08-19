"""Server-owned exact model selection for standard Codex chat turns."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.model_catalogue_policy import catalogue_model_reason
from boltrig.model_choice_policy import opaque_model_choice_id
from boltrig.models import (
    AgentCapability,
    InvocationContext,
    ModelCatalogueUnavailable,
    ModelEndpoint,
    ModelEndpointUnavailable,
)
from boltrig.models.model_id_policy import exact_model_id

from .model_router import (
    endpoint_id_for_modality,
    outbound_text_classifies_sensitive,
    select_model_endpoint,
)


def requested_model_choice_id(context: InvocationContext | None) -> str | None:
    """Return one bounded opaque endpoint id, never a caller model string."""

    raw = (context.extra if context is not None else {}).get("model_endpoint_id")
    if raw is None:
        return None
    try:
        return opaque_model_choice_id(raw)
    except ValueError:
        raise ModelEndpointUnavailable("model choice id is invalid") from None


def validate_model_choice_scope(
    choice_id: str | None,
    capability: AgentCapability,
    *,
    sensitive: bool,
    pinned_policy: bool,
) -> None:
    if choice_id is not None and (capability.runtime != "codex" or sensitive or pinned_policy):
        raise ModelEndpointUnavailable(
            "model choices are available only for standard ephemeral Codex chat"
        )


async def resolve_base_model(
    *,
    kernel: Any,
    tenant_id: str,
    capability: AgentCapability,
    context: InvocationContext | None,
    pinned_policy: bool,
    sensitive_endpoint_id: str | None,
    outbound_text: str | None = None,
) -> tuple[bool, str, str | None, str | None, ModelEndpoint | None]:
    """Resolve request classification and the capability default endpoint.

    ``outbound_text`` is the egress payload text (the composed prompt handed to
    the runtime). The deterministic PII scanner runs over it at this seam, so a
    detection classifies the request sensitive BEFORE the routing decision
    (SEC-13) - classification only, the text is never mutated."""

    sensitive = bool(context is not None and context.extra.get("data_class") == "sensitive")
    # The caller-supplied classification is not trusted alone here (SEC-13):
    # scanner detection overrides a missing/false classification so existing
    # sensitive policy (local endpoint, or the audited misroute refusal when
    # none is configured - SEC-12) applies unchanged. Fail closed, never open.
    sensitive = sensitive or outbound_text_classifies_sensitive(outbound_text)
    modality = str((context.extra if context is not None else {}).get("input_modality") or "text")
    choice_id = requested_model_choice_id(context)
    validate_model_choice_scope(
        choice_id,
        capability,
        sensitive=sensitive,
        pinned_policy=pinned_policy,
    )
    capability_endpoint_id = endpoint_id_for_modality(capability, modality)
    endpoint = None
    if choice_id is None:
        endpoint = await select_model_endpoint(
            kernel.store,
            tenant_id,
            capability_endpoint_id,
            sensitive=sensitive,
            modality=modality,
            sensitive_endpoint_id=sensitive_endpoint_id,
            audit=kernel.audit,
            actor=capability.name,
        )
    return sensitive, modality, choice_id, capability_endpoint_id, endpoint


def trusted_codex_configured(config: dict[str, Any] | None) -> bool:
    return bool(
        config
        and config.get("trusted") is True
        and config.get("provider") is not None
        and config.get("stack_root") is not None
        and isinstance(config.get("model_id"), str)
        and config.get("model_id")
    )


async def require_catalogue_model(
    catalogue: Any,
    model_id: str,
    required_modalities: tuple[str, ...],
    declared_modalities: tuple[str, ...] | None = None,
) -> None:
    """Re-prove exact Bifrost support at the runtime admission boundary.

    ``declared_modalities`` is the store endpoint's own declaration for this
    exact model; the shared policy lets it stand in only when the gateway
    lists the model as a bare row with no ``input_modalities`` key at all.
    """

    if catalogue is None:
        raise ModelCatalogueUnavailable("the Bifrost model catalogue is unavailable")
    try:
        result = await catalogue.list_models()
    except Exception:
        raise ModelCatalogueUnavailable("the Bifrost model catalogue is unavailable") from None
    reason = catalogue_model_reason(result, model_id, required_modalities, declared_modalities)
    if reason == "catalogue_unavailable":
        raise ModelCatalogueUnavailable("the Bifrost model catalogue is unavailable")
    if reason is not None:
        raise ModelEndpointUnavailable(
            "the exact model is not advertised for the requested input by Bifrost"
        )


async def resolve_codex_model(
    *,
    kernel: Any,
    tenant_id: str,
    capability: AgentCapability,
    endpoint: ModelEndpoint | None,
    choice_id: str | None,
    modality: str,
    pinned_policy: bool,
    codex_config: dict[str, Any] | None,
    gateway_url: str | None,
    model_catalogue: Any,
) -> ModelEndpoint | None:
    """Resolve the selected endpoint or compose the exact Automatic model."""

    if choice_id is not None:
        if not trusted_codex_configured(codex_config) or not gateway_url:
            raise ModelEndpointUnavailable(
                "model choices require trusted Codex and the Bifrost gateway"
            )
        selected = await select_model_endpoint(
            kernel.store,
            tenant_id,
            choice_id,
            sensitive=False,
            modality=modality,
            audit=kernel.audit,
            actor=capability.name,
        )
        if selected is None or selected.data_class != "standard" or not selected.supports("text"):
            raise ModelEndpointUnavailable("model choice is not available for this chat input")
        try:
            exact_model_id(selected.model)
        except ValueError:
            raise ModelEndpointUnavailable(
                "model choice uses an unsupported immutable model id"
            ) from None
        required_modalities = tuple(dict.fromkeys(("text", modality)))
        await require_catalogue_model(
            model_catalogue,
            selected.model,
            required_modalities,
            declared_modalities=selected.modalities,
        )
        return replace(selected, kind="bifrost", base_url=gateway_url)
    if pinned_policy:
        return endpoint
    if not trusted_codex_configured(codex_config):
        return None
    if not gateway_url:
        raise ModelEndpointUnavailable("automatic Codex routing requires the Bifrost gateway")
    try:
        model_id = exact_model_id((codex_config or {}).get("model_id"))
    except ValueError:
        return None
    required_modalities = tuple(dict.fromkeys(("text", modality)))
    await require_catalogue_model(
        model_catalogue,
        model_id,
        required_modalities,
        declared_modalities=(
            endpoint.modalities
            if endpoint is not None and endpoint.model == model_id
            else None
        ),
    )
    if endpoint is None:
        return ModelEndpoint(
            id="codex-process-default",
            tenant_id=tenant_id,
            kind="bifrost",
            model=model_id,
            base_url=gateway_url,
            data_class="standard",
            modalities=("text", "vision"),
        )
    return replace(
        endpoint,
        kind="bifrost",
        model=model_id,
        base_url=gateway_url,
    )


def codex_model_route(
    endpoint: ModelEndpoint | None,
    choice_id: str | None,
) -> dict[str, str] | None:
    if endpoint is None:
        return None
    return {
        "model": endpoint.model,
        "provider": "bifrost",
        "runtime": "codex",
        **({"choice_id": choice_id} if choice_id is not None else {}),
    }


__all__ = [
    "codex_model_route",
    "requested_model_choice_id",
    "require_catalogue_model",
    "resolve_base_model",
    "resolve_codex_model",
    "trusted_codex_configured",
    "validate_model_choice_scope",
]
