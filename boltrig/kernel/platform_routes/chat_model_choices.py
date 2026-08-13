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


def _choice_availability(
    model: str,
    platform: dict,
    catalogue_by_id: dict[str, dict],
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
    modalities = advertised.get("input_modalities")
    if not isinstance(modalities, list):
        return False, "text_capability_not_advertised"
    if "text" not in modalities:
        return False, "text_not_supported"
    return True, None


def _model_availability(
    model: str | None,
    platform: dict,
    catalogue_by_id: dict[str, dict],
) -> tuple[bool, str | None]:
    if model is None:
        return False, "default_model_unconfigured"
    return _choice_availability(model, platform, catalogue_by_id)


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
            _choice_availability(endpoint.model, platform, catalogue_by_id)
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
        default_model = _default_model_name(request)
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
        if catalogue_available:
            default_available, default_unavailable_reason = _model_availability(
                default_model,
                platform,
                catalogue_by_id,
            )
        else:
            default_available = False
            default_unavailable_reason = "catalogue_unavailable"
        return {
            "status": "ok" if catalogue_available else "unavailable",
            "reason": None if catalogue_available else catalogue.get("reason"),
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
            "default_choice_id": default_choice_id,
            "default_available": default_available,
            "default_unavailable_reason": default_unavailable_reason,
        }


__all__ = ["register"]
