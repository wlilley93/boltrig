"""Human-in-the-loop request/response contracts (S6.4, S7.6).

HITL adapters (Slack/Teams/email/web) translate these to a channel's native
format and back. The web Approvals panel is always the canonical record
regardless of notification channel (US-HIL-05).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import HITLId, RunId, TenantId, UserId, WorkItemId


class HITLType(str, Enum):
    APPROVAL = "approval"
    CLARIFICATION = "clarification"
    ESCALATION = "escalation"


class Urgency(str, Enum):
    BLOCKING = "blocking"
    ASYNC = "async"


class HITLStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
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


@dataclass
class HITLResponse:
    id: HITLId
    request_id: HITLId
    tenant_id: TenantId
    decision: str
    respondent: UserId
    responded_at: datetime
    notes: str = ""
