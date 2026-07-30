"""Governed authoring operations for workflow event-source bindings."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from boltrig.models import InvocationContext, WorkflowTrigger

MAX_TRIGGERS_PER_WORKFLOW = 32
WEBHOOK_SECRET_PREFIX = "wft_"


def workflow_trigger_secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def mint_workflow_trigger_secret() -> tuple[str, str]:
    secret = WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(32)
    return secret, workflow_trigger_secret_digest(secret)


def _visible(workflow, workspace_id: str | None) -> bool:
    return workflow.workspace_id is None or workflow.workspace_id == workspace_id


def _archived(workflow) -> bool:
    lifecycle = workflow.definition.get("_boltrig_lifecycle")
    return bool(
        isinstance(lifecycle, dict) and lifecycle.get("status") == "archived"
    )


async def _workflow(store, tenant_id: str, workflow_id: str, workspace_id):
    return next(
        (
            item
            for item in await store.list_workflows(tenant_id)
            if item.id == workflow_id and _visible(item, workspace_id)
        ),
        None,
    )


async def create_workflow_trigger_record(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> tuple[WorkflowTrigger, str | None]:
    workflow = await _workflow(
        store, tenant_id, params["workflow_id"], context.workspace_id
    )
    if workflow is None:
        raise LookupError("workflow not found")
    if _archived(workflow):
        raise PermissionError("workflow_archived")
    source = str(params.get("source") or "")
    if source not in {"webhook", "channel"}:
        raise ValueError("source must be webhook or channel")
    name = str(params.get("name") or "").strip()
    if not name or len(name) > 80:
        raise ValueError("trigger name must be 1-80 characters")
    existing = await store.list_workflow_triggers(tenant_id, workflow.id)
    if len(existing) >= MAX_TRIGGERS_PER_WORKFLOW:
        raise ValueError("workflow trigger limit reached")
    if any(item.name == name for item in existing):
        raise ValueError("trigger name already exists")

    channel_id = None
    secret = None
    secret_hash = None
    if source == "channel":
        channel_id = str(params.get("channel_id") or "").strip()
        channel = (
            await store.get_channel(tenant_id, channel_id) if channel_id else None
        )
        if channel is None or not channel.enabled:
            raise LookupError("enabled channel not found")
    else:
        # A webhook is an ongoing delegation by a real, revocable human identity.
        # It cannot be authored by a synthetic agent context with no User record.
        owner = await store.get_user(tenant_id, context.actor)
        if owner is None or owner.status != "active":
            raise PermissionError("active delegator identity required")
        if not context.grants.permits("control.workflow.trigger"):
            raise PermissionError("delegator cannot trigger this workflow")
        secret, secret_hash = mint_workflow_trigger_secret()

    trigger = WorkflowTrigger(
        id=f"wft_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        workspace_id=workflow.workspace_id,
        name=name,
        source=source,
        owner_id=context.actor,
        grant_ceiling=context.grants,
        channel_id=channel_id,
        secret_hash=secret_hash,
    )
    if not await store.create_workflow_trigger(trigger):
        raise ValueError("trigger id conflict")
    saved = await store.get_workflow_trigger(tenant_id, trigger.id)
    return saved or trigger, secret


async def change_workflow_trigger_record(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    context: InvocationContext,
    action: str,
) -> tuple[WorkflowTrigger, str | None]:
    workflow = await _workflow(
        store, tenant_id, params["workflow_id"], context.workspace_id
    )
    trigger = await store.get_workflow_trigger(
        tenant_id, str(params["trigger_id"])
    )
    if (
        workflow is None
        or trigger is None
        or trigger.workflow_id != workflow.id
        or trigger.workspace_id != workflow.workspace_id
    ):
        raise LookupError("workflow trigger not found")
    if action == "enable":
        if _archived(workflow):
            raise PermissionError("workflow_archived")
        updated = await store.set_workflow_trigger_enabled(
            tenant_id, trigger.id, True
        )
        return updated or trigger, None
    if action == "disable":
        updated = await store.set_workflow_trigger_enabled(
            tenant_id, trigger.id, False
        )
        return updated or trigger, None
    if action == "rotate":
        if trigger.source != "webhook":
            raise ValueError("only webhook triggers have a secret")
        secret, secret_hash = mint_workflow_trigger_secret()
        updated = await store.rotate_workflow_trigger_secret(
            tenant_id, trigger.id, secret_hash
        )
        if updated is None:
            raise LookupError("workflow trigger not found")
        return updated, secret
    raise ValueError("unsupported workflow trigger action")
