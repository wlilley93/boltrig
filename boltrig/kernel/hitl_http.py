"""Thin HTTP projections over the shared HITL object-authorization policy."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import HITLType

from .hitl_response_auth import (
    authorize_hitl_response,
    authorize_hitl_scope,
    hitl_request_visible,
)


def _request_row(request: Any) -> dict[str, Any]:
    return {
        "id": request.id,
        "type": request.type.value,
        "urgency": request.urgency.value,
        "question": request.question,
        "context": request.context,
        "options": request.options,
        "work_item_id": request.work_item_id,
        "status": request.status.value,
    }


async def list_visible_hitl(kernel: Any, principal: Any) -> list[dict[str, Any]]:
    pending = await kernel.hitl.list_pending(principal.tenant_id)
    return [
        _request_row(request)
        for request in pending
        if await hitl_request_visible(kernel, principal, request)
    ]


async def visible_hitl_request(
    kernel: Any, principal: Any, request_id: str
) -> tuple[Any | None, Any | None]:
    """Return a request and linked item only when the request is visible."""
    request = await kernel.hitl.get(principal.tenant_id, request_id)
    if request is None:
        return None, None
    try:
        item = await authorize_hitl_scope(kernel, principal, request)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None, None
        raise
    owner = getattr(item, "on_behalf_of", None)
    if request.type == HITLType.QUESTION and owner != principal.subject:
        return None, None
    return request, item


async def respond_to_hitl(
    kernel: Any,
    principal: Any,
    request_id: str,
    decision: str,
    notes: str,
) -> dict[str, str]:
    request = await kernel.hitl.get(principal.tenant_id, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="unknown request")
    await authorize_hitl_response(kernel, principal, request)
    if request.type != HITLType.APPROVAL:
        from boltrig.fleet.prompt_stack import wrap_untrusted

        decision = wrap_untrusted("hitl_response", principal.subject, decision)
    response = await kernel.hitl.answer(
        principal.tenant_id, request_id, decision, principal.subject, notes
    )
    return {"status": "answered", "response_id": response.id}
