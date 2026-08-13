"""Canonical validation for governed per-capability model routes."""

from __future__ import annotations

from typing import Any

from boltrig.models import MODEL_MODALITIES, ModelEndpoint


class CapabilityRouteValidationError(ValueError):
    def __init__(self, message: str, *, reason: str, missing: bool = False) -> None:
        super().__init__(message)
        self.reason = reason
        self.missing = missing


async def validated_capability_routes(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, str], dict[str, ModelEndpoint]]:
    endpoint_id = str(params.get("model_endpoint") or "").strip() or None
    vision_endpoint_id = (
        str(params.get("vision_model_endpoint") or "").strip() or None
    )
    raw_routes = params.get("model_routes") or {}
    if not isinstance(raw_routes, dict):
        raise CapabilityRouteValidationError(
            "model_routes must be an object",
            reason="model_endpoint_binding_invalid",
        )
    routes = {
        str(modality).strip().lower(): str(endpoint).strip()
        for modality, endpoint in raw_routes.items()
        if str(modality).strip() and str(endpoint).strip()
    }
    invalid = set(routes) - set(MODEL_MODALITIES)
    if invalid:
        raise CapabilityRouteValidationError(
            f"unsupported model route modalities: {sorted(invalid)}",
            reason="model_endpoint_modality_invalid",
        )
    for modality, legacy_id in (
        ("text", endpoint_id),
        ("vision", vision_endpoint_id),
    ):
        explicit_id = routes.get(modality)
        if explicit_id and legacy_id and explicit_id != legacy_id:
            raise CapabilityRouteValidationError(
                f"{modality} model route conflicts with its legacy binding",
                reason="model_endpoint_binding_conflict",
            )
        if legacy_id:
            routes[modality] = legacy_id

    # The generic map is authoritative, while the old text/vision columns are
    # still the compatibility projection consumed by older runtime, pricing
    # and inventory paths. Populate that projection from a generic-only write
    # so every reader observes the same reviewed route.
    endpoint_id = routes.get("text")
    vision_endpoint_id = routes.get("vision")

    selected: dict[str, ModelEndpoint] = {}
    for modality, selected_id in routes.items():
        endpoint = await store.get_model_endpoint(tenant_id, selected_id)
        if endpoint is None:
            raise CapabilityRouteValidationError(
                "model endpoint not found",
                reason="model_endpoint_binding_unavailable",
                missing=True,
            )
        if not endpoint.is_active:
            raise CapabilityRouteValidationError(
                "model endpoint is retired",
                reason="model_endpoint_binding_unavailable",
            )
        if not endpoint.supports(modality):
            raise CapabilityRouteValidationError(
                f"{modality} model endpoint does not advertise {modality} modality",
                reason="model_endpoint_modality_unavailable",
            )
        selected[modality] = endpoint

    text_endpoint = selected.get("text")
    if endpoint_id and "vision" not in routes:
        if text_endpoint is None or not text_endpoint.supports("vision"):
            raise CapabilityRouteValidationError(
                "a single agent model must advertise both text and vision modalities",
                reason="multimodal_model_required",
            )
    return endpoint_id, vision_endpoint_id, routes, selected
