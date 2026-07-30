"""Replacement-safe model endpoint author projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import platform_state, require_author


async def _references(store: Any, tenant_id: str, endpoint_id: str) -> dict:
    return {
        "capabilities": sorted(
            item.name
            for item in await store.list_all_capabilities(tenant_id)
            if item.model_endpoint == endpoint_id
        ),
        "fallbacks": sorted(
            item.id
            for item in await store.list_model_endpoints(tenant_id)
            if item.id != endpoint_id and item.fallback == endpoint_id
        ),
    }


def _role_projection(endpoint_id: str | None, endpoints: dict[str, Any]) -> dict[str, Any]:
    if endpoint_id is None:
        return {"endpoint_id": None, "state": "not_configured"}
    endpoint = endpoints.get(endpoint_id)
    if endpoint is None:
        return {"endpoint_id": endpoint_id, "state": "missing"}
    return {
        "endpoint_id": endpoint_id,
        "state": "active" if endpoint.is_active else "retired",
    }


def _price_projection(prices: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model, raw_rate in sorted(dict(prices or {}).items()):
        if isinstance(raw_rate, dict):
            input_rate = float(raw_rate.get("input", 0))
            output_rate = float(raw_rate.get("output", input_rate))
        else:
            input_rate = output_rate = float(raw_rate)
        rows.append(
            {
                "model": str(model),
                "input_micros_per_token": input_rate,
                "output_micros_per_token": output_rate,
            }
        )
    return rows


def _unconfigured_policy() -> dict[str, Any]:
    return {
        "policy": {
            "state": "unconfigured",
            "source": "no_process_manifest",
            "generation": None,
            "default": {
                "endpoint_id": None,
                "state": "not_configured",
                "serving_state": "inactive_no_consumer",
            },
            "sensitive": {
                "endpoint_id": None,
                "state": "not_configured",
                "serving_state": "not_configured",
                "eligible": False,
            },
            "prices": [],
            "price_serving_state": "not_configured",
            "changes_apply_at": "process_restart",
        }
    }


def _configured_policy(policy: Any, current: dict[str, Any]) -> dict[str, Any]:
    default = {
        **_role_projection(policy.default, current),
        "serving_state": "inactive_no_consumer",
    }
    sensitive = _role_projection(policy.sensitive_endpoint, current)
    endpoint = current.get(policy.sensitive_endpoint)
    eligible = bool(
        endpoint is not None
        and endpoint.is_active
        and endpoint.kind == "local"
        and endpoint.data_class == "sensitive"
    )
    sensitive["serving_state"] = (
        "active_process_policy"
        if eligible
        else (
            "not_configured" if policy.sensitive_endpoint is None else "refuses_sensitive_routing"
        )
    )
    sensitive["eligible"] = eligible
    prices = _price_projection(policy.prices)
    generation = hashlib.sha256(
        json.dumps(
            {
                "default": policy.default,
                "sensitive": policy.sensitive_endpoint,
                "prices": prices,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "policy": {
            "state": (
                "degraded"
                if policy.sensitive_endpoint is not None and not eligible
                else "configured"
            ),
            "source": "process_start_manifest",
            "generation": generation,
            "default": default,
            "sensitive": sensitive,
            "prices": prices,
            "price_serving_state": (
                "active_process_cost_accountant" if prices else "not_configured"
            ),
            "changes_apply_at": "process_restart",
        }
    }


def _register_inventory_routes(app, P, K) -> None:
    @app.get("/v1/model-endpoints")
    async def list_model_endpoints(k=K, p=P) -> dict:
        endpoints = await k.store.list_model_endpoints(p.tenant_id)
        return {
            "endpoints": [
                {
                    "id": endpoint.id,
                    "kind": endpoint.kind,
                    "model": endpoint.model,
                    "data_class": endpoint.data_class,
                    "is_active": endpoint.is_active,
                    "status": "active" if endpoint.is_active else "retired",
                }
                for endpoint in sorted(endpoints, key=lambda item: item.id)
            ]
        }

    @app.get("/v1/model-endpoints/{endpoint_id}")
    async def get_model_endpoint(endpoint_id: str, k=K, p=P) -> JSONResponse:
        # The general picker omits topology details. Only an author may hydrate
        # them before replacing an existing row; credential material is not part
        # of this record and is never returned.
        require_author(p)
        endpoint = await k.store.get_model_endpoint(p.tenant_id, endpoint_id)
        if endpoint is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"},
                status_code=404,
            )
        return JSONResponse(
            {
                "endpoint": {
                    "id": endpoint.id,
                    "kind": endpoint.kind,
                    "model": endpoint.model,
                    "base_url": endpoint.base_url,
                    "fallback": endpoint.fallback,
                    "data_class": endpoint.data_class,
                    "is_active": endpoint.is_active,
                    "status": "active" if endpoint.is_active else "retired",
                    "references": await _references(k.store, p.tenant_id, endpoint.id),
                }
            }
        )


def _register_policy_route(app, P, K) -> None:
    @app.get("/v1/model-policy")
    async def get_model_policy(request: Request, k=K, p=P) -> dict[str, Any]:
        """Project process-start model policy without provider topology or secrets.

        The default role is deliberately labelled inactive: it is parsed today
        but has no serving consumer. The sensitive role and price table name
        their real process consumers, so Worker cannot mistake stored endpoint
        inventory for effective routing or billing policy.
        """
        require_author(p)
        policy = platform_state(request).get("model_policy")
        if policy is None:
            return _unconfigured_policy()

        current = {
            endpoint.id: endpoint for endpoint in await k.store.list_model_endpoints(p.tenant_id)
        }
        return _configured_policy(policy, current)


def _register_lifecycle_routes(app, P, K) -> None:
    async def lifecycle(
        endpoint_id: str,
        action: str,
        request: Request,
        body: dict[str, Any] | None,
        k: Any,
        p: Any,
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            f"control.model_endpoint.{action}",
            {
                "id": endpoint_id,
                "approval_id": (body or {}).get("approval_id"),
            },
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/model-endpoints/{endpoint_id}/retire")
    async def retire_model_endpoint(
        endpoint_id: str,
        request: Request,
        body: dict[str, Any] | None = None,
        k=K,
        p=P,
    ) -> JSONResponse:
        return await lifecycle(endpoint_id, "retire", request, body, k, p)

    @app.post("/v1/model-endpoints/{endpoint_id}/restore")
    async def restore_model_endpoint(
        endpoint_id: str,
        request: Request,
        body: dict[str, Any] | None = None,
        k=K,
        p=P,
    ) -> JSONResponse:
        return await lifecycle(endpoint_id, "restore", request, body, k, p)


def register(app, P, K) -> None:
    _register_inventory_routes(app, P, K)
    _register_policy_route(app, P, K)
    _register_lifecycle_routes(app, P, K)
