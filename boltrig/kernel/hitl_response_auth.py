"""Authorization policy for responding to human approval requests."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import GrantMissing, HITLRequest, HITLType


async def authorize_approval_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> None:
    """Require an independent, assigned human with the live action grant."""
    if request.type != HITLType.APPROVAL:
        return
    if principal.actor_tier != "human":
        raise HTTPException(status_code=403, detail="only a human may approve")
    if not request.verb or not request.request_fingerprint:
        raise HTTPException(status_code=409, detail="approval is not request-bound")
    if request.assignee and request.assignee != principal.subject:
        raise HTTPException(status_code=403, detail="approval is assigned to another user")
    initiators = {
        value
        for value in (request.requested_by, request.requested_on_behalf_of)
        if value
    }
    respondents = {
        value for value in (principal.subject, principal.on_behalf_of) if value
    }
    if initiators & respondents:
        raise HTTPException(status_code=403, detail="cannot approve your own request")
    permissions = await kernel.store.get_tenant_permissions(principal.tenant_id)
    try:
        kernel.grants.check(principal.context(), request.verb, permissions)
    except GrantMissing as exc:
        raise HTTPException(
            status_code=403, detail="not authorised to approve this action"
        ) from exc
