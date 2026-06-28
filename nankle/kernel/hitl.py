"""Human-in-the-loop management (Epic K).

Creates and resolves approval / clarification / escalation requests. The kernel
gate (in ``dispatch``) creates an approval before a high-consequence verb runs
and refuses to proceed until it is answered with an approving decision
(SEC-14). The web Approvals panel is the canonical record (US-HIL-05); chat
adapters mirror it. Durable resume of paused runs is provided by Hatchet in the
fleet workers; this manager owns the request/response records and the gate.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from nankle.models import (
    HITLRequest,
    HITLResponse,
    HITLStatus,
    HITLType,
    Urgency,
    utcnow,
)
from nankle.store import Store

# Decisions that count as approval for a gated verb.
_APPROVING = {"approve", "approved", "yes", "ok", "allow"}


class HITLManager:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def create(
        self,
        tenant_id: str,
        run_id: str,
        type: HITLType,
        question: str,
        context: str = "",
        urgency: Urgency = Urgency.BLOCKING,
        options: list[str] | None = None,
        assignee: str | None = None,
        timeout_seconds: int | None = None,
        work_item_id: str | None = None,
    ) -> HITLRequest:
        req = HITLRequest(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            run_id=run_id,
            type=type,
            urgency=urgency,
            context=context,
            question=question,
            options=options or [],
            assignee=assignee,
            work_item_id=work_item_id,
            timeout_at=(
                utcnow() + timedelta(seconds=timeout_seconds) if timeout_seconds else None
            ),
        )
        await self._store.create_hitl_request(req)
        return req

    async def get(self, tenant_id: str, req_id: str) -> HITLRequest | None:
        return await self._store.get_hitl_request(tenant_id, req_id)

    async def list_pending(self, tenant_id: str) -> list[HITLRequest]:
        return await self._store.list_pending_hitl(tenant_id)

    async def answer(
        self, tenant_id: str, request_id: str, decision: str, respondent: str, notes: str = ""
    ) -> HITLResponse:
        resp = HITLResponse(
            id=uuid.uuid4().hex,
            request_id=request_id,
            tenant_id=tenant_id,
            decision=decision,
            respondent=respondent,
            responded_at=utcnow(),
            notes=notes,
        )
        await self._store.answer_hitl(resp)
        return resp

    async def is_approved(self, tenant_id: str, request_id: str) -> bool:
        """True iff the request was answered with an approving decision."""
        req = await self._store.get_hitl_request(tenant_id, request_id)
        if req is None or req.status != HITLStatus.ANSWERED:
            return False
        # The decision lives on the response; look it up via the store.
        resp = await self._store.get_hitl_response(tenant_id, request_id)
        return bool(resp and resp.decision.strip().lower() in _APPROVING)
