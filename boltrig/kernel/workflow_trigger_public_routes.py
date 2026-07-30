"""Secret-authenticated public webhook route for workflow triggers."""

from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.config.control_workflow_triggers import workflow_trigger_secret_digest
from boltrig.models import RateLimit, RateLimited

from .workflow_trigger_delivery import (
    bounded_event,
    deliver_trigger,
    delivery_view,
    event_digest,
    webhook_principal,
)

WEBHOOK_TRIGGER_RL = RateLimit(per="minute", max=30, scope="verb")


def _authenticated(trigger, supplied: str) -> bool:
    stored = (
        trigger.secret_hash
        if trigger is not None and trigger.source == "webhook"
        else "0" * 64
    )
    return secrets.compare_digest(
        workflow_trigger_secret_digest(supplied), stored or "0" * 64
    )


async def _enforce_rate_limit(kernel, tenant_id: str, trigger_id: str):
    try:
        await kernel.rate_limiter.enforce(
            tenant_id,
            f"workflow.webhook:{trigger_id}",
            WEBHOOK_TRIGGER_RL,
        )
    except RateLimited as exc:
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(int(exc.retry_after_seconds))
        return JSONResponse(
            {"status": "throttled", "reason": "trigger intake rate limit"},
            status_code=429,
            headers=headers,
        )
    return None


def register_public_workflow_trigger_routes(app, K) -> None:
    @app.post("/v1/automation-hooks/{tenant_id}/{trigger_id}")
    async def workflow_webhook(
        tenant_id: str,
        trigger_id: str,
        body: dict,
        request: Request,
        k=K,
    ) -> JSONResponse:
        from boltrig.store.postgres import set_current_tenant

        set_current_tenant(tenant_id)
        trigger = await k.store.get_workflow_trigger(tenant_id, trigger_id)
        supplied = request.headers.get("x-boltrig-trigger-secret") or ""
        valid = _authenticated(trigger, supplied)
        if trigger is None or not valid:
            return JSONResponse(
                {"status": "denied", "reason": "webhook_authentication"},
                status_code=401,
            )
        source_event_id = str(
            request.headers.get("x-boltrig-delivery-id") or ""
        ).strip()
        if not source_event_id or len(source_event_id) > 200:
            return JSONResponse(
                {"status": "error", "reason": "delivery_id_required"},
                status_code=400,
            )
        if not bounded_event(body):
            return JSONResponse(
                {"status": "error", "reason": "event_too_large"},
                status_code=413,
            )
        digest = event_digest(f"webhook:{trigger.id}", source_event_id)
        existing = await k.store.get_workflow_trigger_delivery(
            tenant_id, trigger.id, digest
        )
        if existing is not None:
            return JSONResponse(
                {"status": "duplicate", "receipt": delivery_view(existing)}
            )
        throttled = await _enforce_rate_limit(k, tenant_id, trigger.id)
        if throttled is not None:
            return throttled
        principal = await webhook_principal(k.store, trigger)
        payload, status_code = await deliver_trigger(
            k, trigger, principal, body, digest, request
        )
        return JSONResponse(payload, status_code=status_code)
