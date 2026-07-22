"""Thin HTTP projections over the shared HITL object-authorization policy."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from boltrig.models import HITLType

from .hitl_response_auth import (
    authorize_hitl_response,
    authorize_hitl_scope,
    hitl_request_visible,
)


def _request_row(request: Any) -> dict[str, Any]:
    inputs = None
    if request.type == HITLType.APPROVAL and isinstance(request.context, str):
        try:
            display_context = json.loads(request.context)
        except (TypeError, ValueError):
            display_context = None
        if isinstance(display_context, dict):
            inputs = display_context.get("inputs")
    return {
        "id": request.id,
        "type": request.type.value,
        "urgency": request.urgency.value,
        "question": request.question,
        "context": request.context,
        "options": request.options,
        "work_item_id": request.work_item_id,
        "status": request.status.value,
        "run_id": request.run_id,
        "verb": request.verb,
        "requested_by": request.requested_by,
        "requested_on_behalf_of": request.requested_on_behalf_of,
        "inputs": inputs,
        # SEC-181 marker: consumers may render a secure-input affordance for a
        # secure QUESTION (additive; existing consumers ignore it).
        "secure": bool(getattr(request, "secure", False)),
        "secure_purpose": getattr(request, "secure_purpose", None),
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
        from boltrig.text_envelope import wrap_untrusted

        decision = wrap_untrusted("hitl_response", principal.subject, decision)
    response = await kernel.hitl.answer(
        principal.tenant_id, request_id, decision, principal.subject, notes
    )
    return {"status": "answered", "response_id": response.id}


async def answer_hitl_question(
    kernel: Any,
    principal: Any,
    request_id: str,
    answer: Any,
) -> dict[str, Any]:
    """Owner-only, fail-closed answer to a QUESTION request (US-CHAT-12).

    The ONE question-answer path: the HTTP route and channel-native intake
    replies both call here, so eligibility (visible scope, QUESTION type, run
    ownership) and the untrusted-envelope wrap can never drift apart. Raises
    HTTPException with the same status the API returns; never answers an
    approval (those stay on the respond path, SEC-14). A SECURE question's
    answer is sealed as a run+purpose-scoped credential and only its reference
    is recorded (SEC-181 - see kernel/credentials.py)."""
    from boltrig.text_envelope import wrap_untrusted

    req, item = await visible_hitl_request(kernel, principal, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="unknown request")
    if req.type != HITLType.QUESTION:
        raise HTTPException(status_code=409, detail="not a question")
    # Owner = the run's owning work item's on_behalf_of; fail closed with NO
    # write when ownership cannot be confirmed.
    if item is None or item.on_behalf_of != principal.subject:
        raise HTTPException(status_code=403, detail="not your run")
    text = answer.strip() if isinstance(answer, str) else ""
    if not text:
        raise HTTPException(status_code=400, detail="answer is required")
    if getattr(req, "secure", False):
        # SEC-181 secure input: the value is sealed INSIDE the kernel as a
        # run+purpose-scoped credential (envelope-sealed at rest by the store
        # seam, SEC-04) and ONLY the reference is enveloped + recorded as the
        # decision, so the resume wiring replays the reference and the value
        # transits no code path that logs, audits, or echoes it. answer_len is
        # None here: even the LENGTH of a secure value is a leak.
        reference = await kernel.credentials.seal_run_scoped_value(
            principal.tenant_id, req.run_id, req.secure_purpose, text
        )
        wrapped = wrap_untrusted("user_answer", principal.subject, reference)
        answer_len: int | None = None
    else:
        # The answer is user-supplied, so it is enveloped as DATA before it is
        # recorded and replayed into the run (M1 / SEC-72).
        wrapped = wrap_untrusted("user_answer", principal.subject, text)
        answer_len = len(text)
    resp = await kernel.hitl.answer(
        principal.tenant_id, request_id, wrapped, principal.subject
    )
    return {
        "question_id": request_id,
        "response_id": resp.id,
        "run_id": req.run_id,
        "secure": bool(getattr(req, "secure", False)),
        "answer_len": answer_len,
    }
