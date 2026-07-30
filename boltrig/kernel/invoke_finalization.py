"""Caller-owned status projection for synchronous invoke approvals."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import HITLStatus, HITLType, utcnow


async def invoke_approval_state(
    kernel: Any,
    principal: Any,
    request_id: str,
) -> dict[str, str]:
    """Return only the state needed to resume an exact caller-held invocation.

    Direct ``POST /v1/invoke`` calls have no run id, so their caller is the only
    resume lane. The request body remains component-held; this projection never
    returns params, fingerprints, decisions, respondents or approval authority.
    """
    request = await kernel.hitl.get(principal.tenant_id, request_id)
    if (
        request is None
        or request.type != HITLType.APPROVAL
        or request.run_id
        or request.requested_by != principal.subject
        or request.requested_on_behalf_of != principal.on_behalf_of
    ):
        raise HTTPException(status_code=404, detail="unknown invocation approval")

    if request.status == HITLStatus.CONSUMED:
        return {"status": "consumed"}
    if (
        request.timeout_at is not None
        and request.timeout_at <= utcnow()
        and request.status in {HITLStatus.PENDING, HITLStatus.ANSWERED}
    ):
        return {"status": "expired"}
    if request.status == HITLStatus.PENDING:
        return {"status": "pending"}
    if request.status == HITLStatus.ANSWERED:
        return {
            "status": (
                "approved"
                if await kernel.hitl.is_approved(principal.tenant_id, request_id)
                else "rejected"
            )
        }
    if request.status in {HITLStatus.TIMED_OUT, HITLStatus.ESCALATED}:
        return {"status": "expired"}
    raise HTTPException(status_code=409, detail="invocation approval state is unavailable")
