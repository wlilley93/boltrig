"""Authority, idempotency and receipts for workflow trigger delivery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from fastapi import Request

from boltrig.identity.provisioning import effective_grants_for_request
from boltrig.kernel.app import Principal
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import (
    BoltrigError,
    IdempotencyConflict,
    WorkflowTrigger,
    WorkflowTriggerDelivery,
)

MAX_TRIGGER_EVENT_BYTES = 256 * 1024


def trigger_view(trigger: WorkflowTrigger) -> dict[str, Any]:
    return {
        "id": trigger.id,
        "workflow_id": trigger.workflow_id,
        "workspace_id": trigger.workspace_id,
        "name": trigger.name,
        "source": trigger.source,
        "owner_id": trigger.owner_id,
        "channel_id": trigger.channel_id,
        "enabled": trigger.enabled,
        "secret_configured": bool(trigger.secret_hash),
        "created_at": trigger.created_at.isoformat() if trigger.created_at else None,
        "updated_at": trigger.updated_at.isoformat() if trigger.updated_at else None,
    }


def delivery_view(delivery: WorkflowTriggerDelivery) -> dict[str, Any]:
    return {
        "trigger_id": delivery.trigger_id,
        "event_digest": delivery.source_event_digest,
        "status": delivery.status,
        "authority_subject": delivery.authority_subject,
        "run_id": delivery.run_id,
        "hitl_request_id": delivery.hitl_request_id,
        "reason": delivery.reason,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
    }


def event_digest(source_scope: str, source_event_id: str) -> str:
    return hashlib.sha256(
        f"{source_scope}\0{source_event_id}".encode()
    ).hexdigest()


def bounded_event(body: dict[str, Any]) -> bool:
    try:
        raw = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except (TypeError, ValueError):
        return False
    return len(raw) <= MAX_TRIGGER_EVENT_BYTES


async def webhook_principal(store, trigger: WorkflowTrigger) -> Principal | None:
    user = await store.get_user(trigger.tenant_id, trigger.owner_id)
    if user is None or user.status != "active":
        return None
    if trigger.workspace_id is not None:
        member = await store.get_workspace_member(
            trigger.tenant_id, trigger.workspace_id, user.id
        )
        if member is None:
            return None
    current = await effective_grants_for_request(store, user, trigger.workspace_id)
    bounded = current.intersect(trigger.grant_ceiling)
    if not bounded.permits("control.workflow.trigger"):
        return None
    return Principal(
        tenant_id=trigger.tenant_id,
        subject=user.id,
        grants=bounded,
        role=user.role,
        actor_tier="human",
        on_behalf_of=user.id,
        scope=dict(user.scope or {}),
        active_workspace_id=trigger.workspace_id,
    )


async def channel_principal(
    store, trigger: WorkflowTrigger, principal: Principal
) -> Principal | None:
    bounded = principal.grants
    if trigger.workspace_id is not None:
        user = await store.get_user(trigger.tenant_id, principal.subject)
        if user is None or user.status != "active":
            return None
        member = await store.get_workspace_member(
            trigger.tenant_id, trigger.workspace_id, user.id
        )
        if member is None:
            return None
        current = await effective_grants_for_request(
            store, user, trigger.workspace_id
        )
        bounded = bounded.intersect(current)
    if not bounded.permits("control.workflow.trigger"):
        return None
    return replace(
        principal,
        grants=bounded,
        on_behalf_of=principal.subject,
        active_workspace_id=trigger.workspace_id,
    )


async def record_delivery(
    store,
    trigger: WorkflowTrigger,
    digest: str,
    status: str,
    **fields,
) -> tuple[WorkflowTriggerDelivery, bool]:
    return await store.record_workflow_trigger_delivery(
        WorkflowTriggerDelivery(
            trigger_id=trigger.id,
            tenant_id=trigger.tenant_id,
            source_event_digest=digest,
            status=status,
            **fields,
        )
    )


async def _preflight(kernel, trigger, principal, digest):
    existing = await kernel.store.get_workflow_trigger_delivery(
        trigger.tenant_id, trigger.id, digest
    )
    if existing is not None:
        return {"status": "duplicate", "receipt": delivery_view(existing)}, 200
    if not trigger.enabled:
        row, _ = await record_delivery(
            kernel.store, trigger, digest, "disabled", reason="trigger_disabled"
        )
        return {"status": "error", "receipt": delivery_view(row)}, 409
    workflow = next(
        (
            item
            for item in await kernel.store.list_workflows(trigger.tenant_id)
            if item.id == trigger.workflow_id
            and item.workspace_id == trigger.workspace_id
        ),
        None,
    )
    if workflow is None:
        row, _ = await record_delivery(
            kernel.store, trigger, digest, "denied", reason="workflow_unavailable"
        )
        return {"status": "denied", "receipt": delivery_view(row)}, 403
    lifecycle = workflow.definition.get("_boltrig_lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
        row, _ = await record_delivery(
            kernel.store, trigger, digest, "archived", reason="workflow_archived"
        )
        return {"status": "error", "receipt": delivery_view(row)}, 409
    if principal is None:
        row, _ = await record_delivery(
            kernel.store, trigger, digest, "denied", reason="authority_revoked"
        )
        return {"status": "denied", "receipt": delivery_view(row)}, 403
    return None


def _admission(trigger, body, digest):
    params = {
        "workflow_id": trigger.workflow_id,
        "inputs": {
            "trigger": {"id": trigger.id, "source": trigger.source},
            "event": dict(body),
        },
        "idempotency_key": f"workflow-trigger:{trigger.id}:{digest}",
    }
    run_id = "wft_" + hashlib.sha256(
        f"{trigger.id}\0{digest}".encode()
    ).hexdigest()
    return params, run_id


async def _record_dispatch_result(
    kernel, trigger, principal, digest, output, pending
):
    if pending is not None:
        body = json.loads(bytes(pending.body))
        row, _ = await record_delivery(
            kernel.store,
            trigger,
            digest,
            "pending_human",
            authority_subject=principal.subject,
            hitl_request_id=body.get("hitl_request_id"),
        )
        return {"status": "pending_human", "receipt": delivery_view(row)}, 202
    result = dict(output or {})
    row, inserted = await record_delivery(
        kernel.store,
        trigger,
        digest,
        str(result.get("status") or "queued"),
        authority_subject=principal.subject,
        run_id=result.get("run_id"),
    )
    return {
        "status": "accepted" if inserted else "duplicate",
        "receipt": delivery_view(row),
    }, 202 if inserted else 200


async def deliver_trigger(
    kernel,
    trigger: WorkflowTrigger,
    principal: Principal | None,
    body: dict[str, Any],
    digest: str,
    request: Request,
) -> tuple[dict[str, Any], int]:
    blocked = await _preflight(kernel, trigger, principal, digest)
    if blocked is not None:
        return blocked
    params, run_id = _admission(trigger, body, digest)
    try:
        output, pending = await dispatch_control_route(
            kernel,
            principal,
            "control.workflow.trigger",
            params,
            request=request,
            run_id=run_id,
        )
    except IdempotencyConflict:
        return {"status": "in_progress"}, 409
    except BoltrigError as exc:
        status = "denied" if exc.status_code == 403 else "error"
        row, _ = await record_delivery(
            kernel.store,
            trigger,
            digest,
            status,
            authority_subject=principal.subject,
            reason=exc.reason,
        )
        return {"status": status, "receipt": delivery_view(row)}, exc.status_code
    return await _record_dispatch_result(
        kernel, trigger, principal, digest, output, pending
    )


async def deliver_channel_workflow_triggers(
    kernel,
    channel,
    principal: Principal,
    source_event_id: str,
    body: dict[str, Any],
    request: Request,
) -> list[dict[str, Any]]:
    triggers = await kernel.store.list_channel_workflow_triggers(
        channel.tenant_id, channel.id, limit=32
    )
    if not triggers:
        return []
    if not bounded_event(body):
        return [{"status": "error", "reason": "event_too_large"}]
    outcomes = []
    digest = event_digest(f"channel:{channel.id}", source_event_id)
    for trigger in triggers:
        current = await channel_principal(kernel.store, trigger, principal)
        payload, status_code = await deliver_trigger(
            kernel, trigger, current, body, digest, request
        )
        outcomes.append(
            {"trigger_id": trigger.id, "http_status": status_code, **payload}
        )
    return outcomes
