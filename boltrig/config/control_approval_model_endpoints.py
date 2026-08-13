"""Approval snapshots for revisioned model endpoint mutations."""

from __future__ import annotations

from typing import Any

from boltrig.model_choice_policy import opaque_model_choice_id
from boltrig.models import AdapterFailure, InvocationContext


def model_endpoint_view(endpoint: Any) -> dict[str, Any] | None:
    if endpoint is None:
        return None
    return {
        "id": endpoint.id,
        "kind": endpoint.kind,
        "model": endpoint.model,
        "base_url": endpoint.base_url,
        "fallback": endpoint.fallback,
        "data_class": endpoint.data_class,
        "is_active": endpoint.is_active,
        "modalities": list(endpoint.modalities),
        "revision": endpoint.revision,
    }


def _endpoint_id(params: dict[str, Any]) -> str:
    try:
        return opaque_model_choice_id(params["id"])
    except ValueError as error:
        raise AdapterFailure(
            str(error), status_code=409, reason="model_endpoint_choice_id_invalid"
        ) from None


async def _references(store: Any, endpoint_id: str, context: InvocationContext) -> dict:
    snapshot = await store.model_endpoint_references(
        context.tenant_id, endpoint_id
    )
    return snapshot.approval_context()


async def model_endpoint_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    endpoint_id = _endpoint_id(params)
    endpoint = await store.get_model_endpoint(context.tenant_id, endpoint_id)
    if endpoint is None:
        raise AdapterFailure(
            "model endpoint not found", status_code=404,
            reason="control_resource_not_found",
        )
    fallback = (
        await store.get_model_endpoint(context.tenant_id, endpoint.fallback)
        if endpoint.fallback else None
    )
    return {
        "model_endpoint": model_endpoint_view(endpoint),
        "fallback_target": model_endpoint_view(fallback),
        "references": await _references(store, endpoint_id, context),
    }


async def model_endpoint_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    endpoint_id = _endpoint_id(params)
    fallback_id = str(params.get("fallback") or "").strip() or None
    if fallback_id == endpoint_id:
        raise AdapterFailure(
            "a model endpoint cannot fall back to itself", status_code=409,
            reason="model_endpoint_fallback_invalid",
        )
    if fallback_id is not None:
        try:
            fallback_id = opaque_model_choice_id(fallback_id)
        except ValueError as error:
            raise AdapterFailure(
                str(error), status_code=409,
                reason="model_endpoint_choice_id_invalid",
            ) from None
    fallback = (
        await store.get_model_endpoint(context.tenant_id, fallback_id)
        if fallback_id else None
    )
    if fallback_id and (fallback is None or not fallback.is_active):
        raise AdapterFailure(
            "fallback model endpoint is missing or retired", status_code=409,
            reason="model_endpoint_fallback_unavailable",
        )
    return {
        "model_endpoint": model_endpoint_view(
            await store.get_model_endpoint(context.tenant_id, endpoint_id)
        ),
        "fallback_target": model_endpoint_view(fallback),
        "references": await _references(store, endpoint_id, context),
    }


__all__ = [
    "model_endpoint_context",
    "model_endpoint_upsert_context",
    "model_endpoint_view",
]
