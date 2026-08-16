"""Governed model-endpoint mutations."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.model_catalogue_policy import catalogue_model_reason
from boltrig.model_choice_policy import opaque_model_choice_id
from boltrig.models import AdapterFailure, InvocationContext, ModelEndpoint
from boltrig.models.model_id_policy import exact_model_id
from boltrig.store.model_endpoint_contract import ModelEndpointReferenceSnapshot

from .control_approval import require_unchanged_approval_context
from .control_safety import ControlConflict


def _active_status(endpoint) -> str:
    return "active" if endpoint is None or endpoint.is_active else "retired"


async def _validated_fallback(store, tenant_id, endpoint_id, params):
    fallback_id = str(params.get("fallback") or "").strip() or None
    if fallback_id == endpoint_id:
        raise ControlConflict("a model endpoint cannot fall back to itself")
    if fallback_id is None:
        return None
    try:
        fallback_id = opaque_model_choice_id(fallback_id)
    except ValueError as error:
        raise ControlConflict(str(error)) from None
    fallback = await store.get_model_endpoint(tenant_id, fallback_id)
    if fallback is None:
        raise LookupError("fallback model endpoint not found")
    if not fallback.is_active:
        raise ControlConflict("fallback model endpoint is retired")
    return fallback_id


async def _require_catalogue_model(
    catalogue: Any, model_id: str, modalities: tuple[str, ...]
) -> None:
    if catalogue is None:
        raise AdapterFailure(
            "the Bifrost model catalogue is unavailable",
            status_code=503,
            reason="model_catalogue_unavailable",
        )
    try:
        result = await catalogue.list_models()
    except Exception:
        raise AdapterFailure(
            "the Bifrost model catalogue is unavailable",
            status_code=503,
            reason="model_catalogue_unavailable",
        ) from None
    reason = catalogue_model_reason(result, model_id, modalities)
    if reason == "catalogue_unavailable":
        raise AdapterFailure(
            "the Bifrost model catalogue is unavailable",
            status_code=503,
            reason="model_catalogue_unavailable",
        )
    if reason is not None:
        raise AdapterFailure(
            "the exact model is not advertised as text-capable by Bifrost",
            status_code=409,
            reason="model_endpoint_not_advertised",
        )


async def preflight_model_endpoint_catalogue(
    verb: str, params: dict[str, Any], model_catalogue: Any
) -> None:
    """Reject an unprovable governed Bifrost row before consuming approval."""

    if verb != "control.model_endpoint.upsert":
        return
    try:
        endpoint_id = opaque_model_choice_id(params.get("id"))
        fallback_id = str(params.get("fallback") or "").strip() or None
        if fallback_id is not None:
            opaque_model_choice_id(fallback_id)
    except ValueError as error:
        raise AdapterFailure(
            str(error),
            status_code=409,
            reason="model_endpoint_choice_id_invalid",
        ) from None
    if fallback_id == endpoint_id:
        raise AdapterFailure(
            "a model endpoint cannot fall back to itself",
            status_code=409,
            reason="model_endpoint_fallback_invalid",
        )
    kind = str(params.get("kind") or "").strip().lower()
    data_class = str(params.get("data_class", "standard")).strip().lower()
    if data_class != "standard" or kind not in {"bifrost", "xai", "x.ai", "grok"}:
        return
    try:
        model = exact_model_id(params.get("model"))
        endpoint = ModelEndpoint(
            id="preflight",
            tenant_id="preflight",
            kind=kind,
            model=model,
            modalities=tuple(params.get("modalities") or ("text",)),
        )
    except (TypeError, ValueError) as error:
        raise AdapterFailure(
            str(error), status_code=409, reason="adapter_conflict"
        ) from None
    if kind != "bifrost":
        return
    await _require_catalogue_model(
        model_catalogue, model, endpoint.modalities
    )


def _endpoint_snapshot(value: Any, tenant_id: str) -> ModelEndpoint | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PermissionError("approved model endpoint state is invalid")
    try:
        return ModelEndpoint(
            id=value["id"], tenant_id=tenant_id, kind=value["kind"],
            model=value["model"], base_url=value.get("base_url"),
            fallback=value.get("fallback"), data_class=value["data_class"],
            is_active=value["is_active"], modalities=tuple(value["modalities"]),
            revision=value["revision"],
        )
    except (KeyError, TypeError, ValueError):
        raise PermissionError("approved model endpoint state is invalid") from None


def _approved_endpoints(
    context: InvocationContext, endpoint_id: str
) -> tuple[
    ModelEndpoint | None,
    ModelEndpoint | None,
    ModelEndpointReferenceSnapshot,
]:
    resource = context.extra.get("approval_resource_context")
    if (
        not isinstance(resource, dict)
        or "model_endpoint" not in resource
        or "fallback_target" not in resource
        or "references" not in resource
    ):
        raise PermissionError("approved model endpoint state is missing")
    current = _endpoint_snapshot(resource["model_endpoint"], context.tenant_id)
    fallback = _endpoint_snapshot(resource["fallback_target"], context.tenant_id)
    try:
        references = ModelEndpointReferenceSnapshot.parse_approval_context(
            resource["references"]
        )
    except (TypeError, ValueError):
        raise PermissionError("approved model endpoint state is invalid") from None
    if current is not None and current.id != endpoint_id:
        raise PermissionError("approved model endpoint state is invalid")
    return current, fallback, references


async def _execute_model_endpoint_upsert(
    store: Any,
    endpoint_id: str,
    params: dict[str, Any],
    context: InvocationContext,
    model_catalogue: Any,
) -> Result:
    fallback_id = await _validated_fallback(
        store, context.tenant_id, endpoint_id, params
    )
    kind = str(params["kind"]).strip().lower()
    data_class = str(params.get("data_class", "standard")).strip().lower()
    model = str(params["model"])
    if data_class == "sensitive" and kind != "local":
        raise ControlConflict("sensitive model endpoints must use the local kind")
    if data_class == "standard" and kind in {"bifrost", "xai", "x.ai", "grok"}:
        try:
            model = exact_model_id(model)
        except ValueError as error:
            raise ControlConflict(str(error)) from None
    endpoint = ModelEndpoint(
        id=endpoint_id,
        tenant_id=context.tenant_id,
        kind=kind,
        model=model,
        base_url=params.get("base_url"),
        fallback=fallback_id,
        data_class=data_class,
        modalities=tuple(params.get("modalities") or ("text",)),
    )
    if data_class == "standard" and kind == "bifrost":
        await _require_catalogue_model(
            model_catalogue, model, endpoint.modalities
        )
    expected, expected_fallback, expected_references = _approved_endpoints(
        context, endpoint_id
    )
    if not await store.compare_and_upsert_model_endpoint(
        endpoint,
        expected,
        expected_fallback=expected_fallback,
        expected_references=expected_references,
    ):
        raise ControlConflict("model endpoint changed after approval")
    current = await store.get_model_endpoint(context.tenant_id, endpoint.id)
    return Result.success(
        {
            "upserted": "model_endpoint",
            "id": endpoint.id,
            "model_endpoint_status": _active_status(current),
        }
    )


async def execute_model_endpoint_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    *,
    model_catalogue: Any = None,
) -> Result | None:
    if not verb.startswith("control.model_endpoint."):
        return None
    try:
        endpoint_id = opaque_model_choice_id(params.get("id"))
    except ValueError as error:
        raise ControlConflict(str(error)) from None
    await require_unchanged_approval_context(store, loader, verb, params, context)
    if verb in {
        "control.model_endpoint.retire",
        "control.model_endpoint.restore",
    }:
        expected, _expected_fallback, _expected_references = _approved_endpoints(
            context, endpoint_id
        )
        if expected is None:
            raise LookupError("model endpoint not found")
        endpoint = await store.compare_and_set_model_endpoint_active(
            context.tenant_id,
            endpoint_id,
            verb.endswith(".restore"),
            expected,
        )
        if endpoint is None:
            raise ControlConflict("model endpoint changed after approval")
        return Result.success(
            {
                "id": endpoint.id,
                "model_endpoint_status": _active_status(endpoint),
            }
        )
    if verb != "control.model_endpoint.upsert":
        return None
    return await _execute_model_endpoint_upsert(
        store, endpoint_id, params, context, model_catalogue
    )
