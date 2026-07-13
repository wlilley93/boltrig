"""Compatibility helper for HTTP routes backed by governed ``control.*`` verbs."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.models import DegradedMode, PendingHuman


async def _ensure_control_plane(
    kernel: Any, principal: Any, request: Request | None
) -> None:
    """Late-wire the built-in adapter for in-process/test app construction.

    Production bootstrap registers it eagerly. ``create_app(Kernel(...))`` is a
    supported compatibility path, so direct routes must not fall back to raw
    writes merely because that composition root was not used.
    """
    tenant = principal.tenant_id
    platform = (
        (getattr(request.app.state, "platform", {}) or {})
        if request is not None
        else {}
    )
    adapter = kernel.loader.peek(tenant, "control")
    if adapter is None:
        from boltrig.config.control_plane import build_control_plane_adapter

        adapter = build_control_plane_adapter(
            kernel.store,
            loader=kernel.loader,
            registry=kernel.registry,
            admin=platform.get("admin"),
            workflows=platform.get("workflows"),
        )
        await kernel.register_adapter(tenant, adapter)
        return
    adapter.set_registry(kernel.registry)
    if platform.get("admin") is not None:
        adapter.set_admin(platform["admin"])
    if platform.get("workflows") is not None:
        adapter.set_workflows(platform["workflows"])
    if await kernel.store.get_verb(tenant, "control.workflow.upsert") is None:
        await kernel.registry.register_adapter_verbs(tenant, adapter)


async def dispatch_control_route(
    kernel: Any,
    principal: Any,
    verb: str,
    params: dict[str, Any],
    *,
    request: Request | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Invoke a control verb and translate only its control-flow responses.

    Ordinary kernel errors continue to the app's canonical error handler. The
    optional headers/body fields let legacy direct-route clients re-apply an
    approved request without introducing a second mutation implementation.
    """
    await _ensure_control_plane(kernel, principal, request)
    clean = dict(params)
    approval_id = clean.pop("approval_id", None)
    idempotency_key = clean.pop("idempotency_key", None)
    if request is not None:
        approval_id = request.headers.get("x-boltrig-approval-id") or approval_id
        idempotency_key = request.headers.get("idempotency-key") or idempotency_key
    try:
        output = await kernel.invoke(
            "control",
            verb,
            clean,
            principal.context(),
            approval_id=approval_id,
            idempotency_key=idempotency_key,
        )
        return output, None
    except PendingHuman as exc:
        return None, JSONResponse(
            {"status": "pending_human", "hitl_request_id": exc.hitl_request_id},
            status_code=202,
        )
    except DegradedMode as exc:
        return None, JSONResponse(
            {"status": "degraded", "output": exc.output}, status_code=503
        )
