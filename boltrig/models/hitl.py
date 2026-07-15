"""Human-in-the-loop request/response contracts (S6.4, S7.6).

HITL adapters (Slack/Teams/email/web) translate these to a channel's native
format and back. The web Approvals panel is always the canonical record
regardless of notification channel (US-HIL-05).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import HITLId, RunId, TenantId, UserId, WorkItemId, WorkspaceId


class HITLType(str, Enum):
    APPROVAL = "approval"
    CLARIFICATION = "clarification"
    ESCALATION = "escalation"
    # A turn's agent asking the USER a clarifying question via the governed
    # ``chat.ask_user`` verb (US-CHAT-12). It is answered by the owner through the
    # fail-closed ``/v1/hitl/{id}/answer`` route, never by the approvals gate: an
    # approval clears a HIGH-consequence verb, a QUESTION only feeds an answer back
    # into a paused run, so the two must never be interchangeable (H1 / SEC-14).
    QUESTION = "question"


class Urgency(str, Enum):
    BLOCKING = "blocking"
    ASYNC = "async"


class HITLStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    CONSUMED = "consumed"  # an approving answer that has been spent by the gate (single-use)
    TIMED_OUT = "timed_out"
    ESCALATED = "escalated"


@dataclass
class HITLRequest:
    id: HITLId
    tenant_id: TenantId
    run_id: RunId  # the (Hatchet) run that is paused
    type: HITLType
    urgency: Urgency
    context: str
    question: str
    status: HITLStatus = HITLStatus.PENDING
    work_item_id: WorkItemId | None = None
    options: list[str] = field(default_factory=list)  # for approvals
    assignee: str | None = None  # user or group
    timeout_at: datetime | None = None
    # SEC-14: an approval is bound to the verb it gates and to who asked, so an
    # approval for one verb cannot authorise another, and the requester cannot
    # approve their own request.
    verb: str | None = None
    requested_by: UserId | None = None
    requested_on_behalf_of: UserId | None = None
    # SHA-256 over the canonical action, validated params, authenticated caller
    # context and optional mutable-resource state.  A response is useful only for
    # an invocation that recomputes this exact fingerprint.
    request_fingerprint: str | None = None
    # Object-level visibility is bound when the request is created. ``None`` is
    # org-wide/backward-compatible; a list (including empty) is the originating
    # principal's department scope and must never be widened by a reader.
    workspace_id: WorkspaceId | None = None
    department_scope: list[str] | None = None


@dataclass
class HITLResponse:
    id: HITLId
    request_id: HITLId
    tenant_id: TenantId
    decision: str
    respondent: UserId
    responded_at: datetime
    notes: str = ""
