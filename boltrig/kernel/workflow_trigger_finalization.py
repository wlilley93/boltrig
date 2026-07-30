"""Secret-safe discovery and resume policy for trigger finalization."""

from __future__ import annotations

import json

from boltrig.models import HITLStatus

SECRET_FINALIZATION_VERBS = frozenset(
    {
        "control.workflow.trigger_binding.create",
        "control.workflow.trigger_binding.rotate",
    }
)


async def approval_requires_origin_finalization(store, request) -> bool:
    """Whether answer-side resume would discard a one-time webhook secret."""
    if request.verb not in SECRET_FINALIZATION_VERBS:
        return False
    if request.verb.endswith(".rotate"):
        return True
    from boltrig.kernel.held_call import read_held_call

    held = await read_held_call(
        store, request.tenant_id, request.run_id, request.id
    )
    return bool(held is not None and held.params.get("source") == "webhook")


def _display_inputs(request) -> dict | None:
    try:
        display = json.loads(request.context)
    except (TypeError, ValueError):
        return None
    inputs = display.get("inputs") if isinstance(display, dict) else None
    return inputs if isinstance(inputs, dict) else None


async def _candidate(store, hitl, principal, workflow, request):
    if (
        request.verb not in SECRET_FINALIZATION_VERBS
        or request.workspace_id != workflow.workspace_id
    ):
        return None
    inputs = _display_inputs(request)
    if inputs is None or inputs.get("workflow_id") != workflow.id:
        return None
    if request.status == HITLStatus.ANSWERED:
        if not await hitl.is_approved(principal.tenant_id, request.id):
            return None
        state = "ready"
    else:
        state = "waiting"
    if request.verb.endswith(".create"):
        if inputs.get("source") != "webhook":
            return None
        return {
            "request_id": request.id,
            "action": "create",
            "state": state,
            "name": str(inputs.get("name") or ""),
            "source": "webhook",
        }
    trigger = await store.get_workflow_trigger(
        principal.tenant_id, str(inputs.get("trigger_id") or "")
    )
    if (
        trigger is None
        or trigger.workflow_id != workflow.id
        or trigger.workspace_id != workflow.workspace_id
        or trigger.source != "webhook"
    ):
        return None
    return {
        "request_id": request.id,
        "action": "rotate",
        "state": state,
        "trigger_id": trigger.id,
    }


async def discover_finalizations(store, hitl, principal, workflow) -> list[dict]:
    requests = await store.list_hitl_requests_for_requester(
        principal.tenant_id,
        principal.subject,
        [HITLStatus.PENDING.value, HITLStatus.ANSWERED.value],
        limit=20,
    )
    finalizations = []
    for request in requests:
        item = await _candidate(store, hitl, principal, workflow, request)
        if item is not None:
            finalizations.append(item)
    return finalizations
