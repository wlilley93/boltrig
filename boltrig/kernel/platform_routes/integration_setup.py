"""Certified, provider-declared integration authentication setup."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.config.control_integrations import (
    integration_setup_refusal,
    validate_integration_secret_fields,
)
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models.integration_auth import IntegrationSecretContract

from ._shared import require_author


def public_secret_contract(contract: IntegrationSecretContract | None) -> dict | None:
    """Project field metadata only; credential kind and values stay kernel-side."""

    if contract is None:
        return None
    return {
        "kind": "manual_secret",
        "version": contract.version,
        "fields": [
            {
                "name": field.name,
                "label": field.label,
                "input_kind": field.input_kind,
                "secret": field.secret,
                "required": field.required,
                "min_length": field.min_length,
                "max_length": field.max_length,
            }
            for field in contract.fields
        ],
    }


def _error(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"status": "error", "reason": reason}, status_code=status_code)


def _validate_fields(
    contract: IntegrationSecretContract, body: object
) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(body, dict) or set(body) - {"fields", "label"}:
        return None, "invalid_setup_shape"
    submitted = body.get("fields")
    return validate_integration_secret_fields(contract, submitted)


def _connection_label(item, body: dict) -> str | None:
    value = body.get("label", item.label)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 200 else None


async def _setup_ready(kernel, tenant_id: str, item) -> str | None:
    return await integration_setup_refusal(
        kernel.store,
        kernel.loader,
        kernel.credentials,
        tenant_id,
        item,
    )


async def _submit_manual_secret(
    integration_id: str,
    body: dict,
    kernel,
    principal,
    connection_view,
    request: Request,
) -> JSONResponse:
    item = await kernel.store.get_integration_catalogue(principal.tenant_id, integration_id)
    if item is None:
        return _error("not_found", 404)
    refusal = await _setup_ready(kernel, principal.tenant_id, item)
    if refusal is not None:
        return JSONResponse(
            {
                "status": "unsupported",
                "reason": refusal,
                "integration_id": integration_id,
            },
            status_code=409,
        )
    contract = item.secret_contract
    assert contract is not None and item.adapter_id is not None
    fields, reason = _validate_fields(contract, body)
    if reason is not None or fields is None:
        return _error(reason or "invalid_setup_fields")
    label = _connection_label(item, body)
    if label is None:
        return _error("invalid_connection_label")

    output, pending = await dispatch_control_route(
        kernel,
        principal,
        "control.integration.connect",
        {
            "integration_id": item.id,
            "label": label,
            "secret": fields,
        },
        request=request,
    )
    if pending is not None:
        return pending
    connection_id = str((output or {}).get("connection_id") or "")
    connection = await kernel.store.get_integration_connection(principal.tenant_id, connection_id)
    if connection is None:
        return _error("connection_projection_unavailable", 503)
    return JSONResponse(
        {
            "status": "connected",
            "connection": await connection_view(kernel, principal.tenant_id, connection),
        },
        status_code=201,
    )


def register_integration_setup(app, P, K, *, connection_view) -> None:
    @app.post("/v1/integrations/{integration_id}/oauth/start")
    async def oauth_start(integration_id: str, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        item = await k.store.get_integration_catalogue(p.tenant_id, integration_id)
        if item is None:
            return _error("not_found", 404)
        reason = (
            "oauth_not_declared" if "oauth2" not in item.auth else "oauth_provider_not_configured"
        )
        return JSONResponse(
            {
                "status": "unsupported",
                "reason": reason,
                "integration_id": integration_id,
            },
            status_code=409,
        )

    @app.post("/v1/integrations/{integration_id}/secrets")
    async def submit_secret(
        integration_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        return await _submit_manual_secret(integration_id, body, k, p, connection_view, request)


__all__ = ["public_secret_contract", "register_integration_setup"]
