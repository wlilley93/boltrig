"""Requester-owned recovery metadata for one-time channel pairing codes."""

from __future__ import annotations

import json
from typing import Any

from boltrig.models import HITLStatus


def _display_inputs(request: Any) -> dict[str, Any] | None:
    try:
        display = json.loads(request.context)
    except (TypeError, ValueError):
        return None
    inputs = display.get("inputs") if isinstance(display, dict) else None
    return inputs if isinstance(inputs, dict) else None


async def _candidate(store, hitl, principal, channel, request):
    if (
        request.verb != "control.channel.pair"
        or request.run_id
        or request.requested_by != principal.subject
        or request.requested_on_behalf_of != principal.on_behalf_of
        or request.workspace_id != principal.active_workspace_id
    ):
        return None
    inputs = _display_inputs(request)
    if inputs is None or inputs.get("channel_id") != channel.id:
        return None
    if await store.get_channel(principal.tenant_id, channel.id) is None:
        return None
    if request.status == HITLStatus.ANSWERED:
        if not await hitl.is_approved(principal.tenant_id, request.id):
            return None
        state = "ready"
    elif request.status == HITLStatus.PENDING:
        state = "waiting"
    else:
        return None
    try:
        ttl_minutes = int(inputs.get("ttl_minutes") or 15)
    except (TypeError, ValueError):
        return None
    return {
        "request_id": request.id,
        "state": state,
        "external_user_id": str(inputs.get("external_user_id") or ""),
        "subject": str(inputs.get("subject") or ""),
        "role": str(inputs.get("role") or "member"),
        "ttl_minutes": max(1, min(ttl_minutes, 60)),
    }


async def discover_pair_finalizations(
    store,
    hitl,
    principal,
    channel,
) -> list[dict[str, Any]]:
    """List only the caller's safe pairing intent; never a generated code."""
    requests = await store.list_hitl_requests_for_requester(
        principal.tenant_id,
        principal.subject,
        [HITLStatus.PENDING.value, HITLStatus.ANSWERED.value],
        limit=20,
    )
    finalizations = []
    for request in requests:
        item = await _candidate(store, hitl, principal, channel, request)
        if item is not None:
            finalizations.append(item)
    return finalizations
