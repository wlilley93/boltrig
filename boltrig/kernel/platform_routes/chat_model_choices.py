"""Tenant-scoped, browser-safe model choices for text chat."""

from __future__ import annotations

from fastapi import Request

from boltrig.model_choice_policy import opaque_model_choice_id
from boltrig.models.model_id_policy import exact_model_id

from ._shared import platform_state

_CATALOGUE_FAILURE = {
    "status": "unavailable",
    "models": [],
    "reason": "not_configured",
}
_CATALOGUE_REASONS = frozenset(
    {
        "not_configured",
        "invalid_gateway_configuration",
        "gateway_timeout",
        "gateway_unavailable",
        "gateway_redirect_rejected",
        "gateway_response_rejected",
        "response_too_large",
        "schema_invalid",
        "catalogue_too_large",
        "pagination_limit",
    }
)


def _default_model_name(request: Request) -> str | None:
    value = platform_state(request).get("codex_model_id")
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        return None
    return value


async def _scoped_ai_default(kernel, principal, platform: dict):
    """Return the caller's configured default without projecting credential metadata."""

    from boltrig.identity import resolve_ai_key
    from boltrig.identity.bifrost_user_binding import (
        BifrostUserBindingUnavailable,
        BifrostUserGateway,
    )

    try:
        resolution = await resolve_ai_key(
            kernel.store,
            principal.tenant_id,
            workspace_id=principal.active_workspace_id,
            user_id=principal.subject,
            modality="text",
        )
    except Exception:
        return None
    if resolution.is_default:
        return None
    try:
        model = exact_model_id(resolution.model)
    except ValueError:
        raw_model = resolution.model
        return (
            raw_model if isinstance(raw_model, str) else None,
            False,
            "model_id_unsupported",
        )
    if not platform.get("codex_trusted_provider_configured"):
        return model, False, "trusted_codex_unavailable"
    if not platform.get("model_gateway_configured"):
        return model, False, "model_gateway_unavailable"
    try:
        gateway = BifrostUserGateway()
        binding = await gateway.load(kernel.store, principal.tenant_id, resolution)
        if binding is None:
            return model, False, "provider_not_connected"
        if not await gateway.is_usable(binding):
            return model, False, "model_not_advertised"
    except BifrostUserBindingUnavailable:
        return model, False, "model_gateway_unavailable"
    return model, True, None


def _declared_for(endpoints, model: str | None) -> tuple[str, ...] | None:
    """The declaration of the store endpoint naming exactly this model, if any."""

    return next(
        (endpoint.modalities for endpoint in endpoints if endpoint.model == model),
        None,
    )


def _advertised_modalities(
    advertised: dict, declared_modalities: tuple[str, ...] | None
) -> list[str] | None:
    """Resolve a row's modalities, letting a store declaration stand in.

    Plain OpenAI-compatible gateways list provider-derived models as bare
    {id, name} rows: absence of the key means "not described", never
    "describes nothing". Only that absence may be answered by the store
    endpoint's own declaration - the same declaration the kernel already
    trusts to route to the model at all. A row carrying the key malformed
    stays refused.
    """

    modalities = advertised.get("input_modalities")
    if isinstance(modalities, list):
        return modalities
    if "input_modalities" not in advertised and declared_modalities:
        return [
            "image" if modality == "vision" else modality
            for modality in declared_modalities
        ]
    return None


def _choice_availability(
    model: str,
    platform: dict,
    catalogue_by_id: dict[str, dict],
    declared_modalities: tuple[str, ...] | None = None,
) -> tuple[bool, str | None]:
    try:
        exact_model_id(model)
    except ValueError:
        return False, "model_id_unsupported"
    if not platform.get("codex_trusted_provider_configured"):
        return False, "trusted_codex_unavailable"
    if not platform.get("model_gateway_configured"):
        return False, "model_gateway_unavailable"
    advertised = catalogue_by_id.get(model)
    if advertised is None:
        return False, "model_not_advertised"
    modalities = _advertised_modalities(advertised, declared_modalities)
    if modalities is None:
        return False, "text_capability_not_advertised"
    if "text" not in modalities:
        return False, "text_not_supported"
    return True, None


def _model_availability(
    model: str | None,
    platform: dict,
    catalogue_by_id: dict[str, dict],
    declared_modalities: tuple[str, ...] | None = None,
) -> tuple[bool, str | None]:
    if model is None:
        return False, "default_model_unconfigured"
    return _choice_availability(model, platform, catalogue_by_id, declared_modalities)


async def _catalogue(platform: dict) -> dict:
    provider = platform.get("bifrost_models")
    if provider is None:
        return dict(_CATALOGUE_FAILURE)
    try:
        result = await provider.list_models()
    except Exception:
        return {
            "status": "unavailable",
            "models": [],
            "reason": "gateway_unavailable",
        }
    if not isinstance(result, dict):
        return {
            "status": "unavailable",
            "models": [],
            "reason": "gateway_response_rejected",
        }
    status = result.get("status")
    models = result.get("models")
    reason = result.get("reason")
    if (
        status not in {"ok", "unavailable"}
        or type(models) is not list
        or (status == "ok" and reason is not None)
        or (status == "unavailable" and reason not in _CATALOGUE_REASONS)
    ):
        return {
            "status": "unavailable",
            "models": [],
            "reason": "gateway_response_rejected",
        }
    return {"status": status, "models": models, "reason": reason}


def _catalogue_index(catalogue: dict) -> tuple[bool, dict[str, dict]]:
    if catalogue.get("status") != "ok":
        return False, {}
    index: dict[str, dict] = {}
    for row in catalogue["models"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            return False, {}
        if row["id"] in index:
            return False, {}
        index[row["id"]] = row
    return True, index


def _project_choices(endpoints, platform, catalogue_available, catalogue_by_id):
    projected = []
    for endpoint in endpoints:
        if (
            not isinstance(endpoint.model, str)
            or not endpoint.model
            or len(endpoint.model) > 160
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in endpoint.model
            )
        ):
            continue
        try:
            opaque_model_choice_id(endpoint.id)
        except ValueError:
            continue
        available, reason = (
            _choice_availability(
                endpoint.model, platform, catalogue_by_id, endpoint.modalities
            )
            if catalogue_available
            else (False, "catalogue_unavailable")
        )
        projected.append((endpoint, available, reason))
    return projected


def register(app, P, K) -> None:
    @app.get("/v1/chat/model-choices")
    async def list_chat_model_choices(request: Request, k=K, p=P) -> dict:
        """Project exact model names, never endpoint topology or credentials."""

        platform = platform_state(request)
        scoped_default = await _scoped_ai_default(k, p, platform)
        default_model = (
            scoped_default[0]
            if scoped_default is not None
            else _default_model_name(request)
        )
        endpoints = sorted(
            (
                endpoint
                for endpoint in await k.store.list_model_endpoints(p.tenant_id)
                if endpoint.is_active
                and endpoint.data_class == "standard"
                and endpoint.supports("text")
            ),
            key=lambda endpoint: endpoint.id,
        )
        catalogue = await _catalogue(platform)
        catalogue_available, catalogue_by_id = _catalogue_index(catalogue)
        if catalogue.get("status") == "ok" and not catalogue_available:
            catalogue["reason"] = "gateway_response_rejected"
        projected = _project_choices(
            endpoints,
            platform,
            catalogue_available,
            catalogue_by_id,
        )

        default_choice_id = next(
            (
                endpoint.id
                for endpoint, _available, _reason in projected
                if default_model is not None and endpoint.model == default_model
            ),
            None,
        )
        if scoped_default is not None:
            default_available = scoped_default[1]
            default_unavailable_reason = scoped_default[2]
        elif catalogue_available:
            default_available, default_unavailable_reason = _model_availability(
                default_model,
                platform,
                catalogue_by_id,
                _declared_for(endpoints, default_model),
            )
        else:
            default_available = False
            default_unavailable_reason = "catalogue_unavailable"
        return {
            "status": "ok"
            if catalogue_available or default_available
            else "unavailable",
            "reason": None
            if catalogue_available or default_available
            else catalogue.get("reason"),
            "choices": [
                {
                    "id": endpoint.id,
                    "model_name": endpoint.model,
                    "available": available,
                    "is_default": endpoint.id == default_choice_id,
                    "modalities": list(endpoint.modalities),
                    "unavailable_reason": reason,
                }
                for endpoint, available, reason in projected
            ],
            "default_model_name": default_model,
            "default_source": "personal" if scoped_default is not None else "platform",
            "default_choice_id": default_choice_id,
            "default_available": default_available,
            "default_unavailable_reason": default_unavailable_reason,
        }


__all__ = ["register"]
