"""Durable external bindings and receipts for governed workflow triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .grants import EMPTY_GRANTS, GrantSet

WORKFLOW_TRIGGER_SOURCES = ("webhook", "channel")


@dataclass
class WorkflowTrigger:
    """One approved event source bound to one stored workflow.

    ``secret_hash`` is the SHA-256 digest of a high-entropy webhook bearer and is
    never projected. ``grant_ceiling`` is used only by webhook delivery: channel
    delivery derives its authority from the currently verified sender instead.
    """

    id: str
    tenant_id: str
    workflow_id: str
    name: str
    source: str
    owner_id: str
    workspace_id: str | None = None
    grant_ceiling: GrantSet = field(default_factory=lambda: EMPTY_GRANTS)
    channel_id: str | None = None
    secret_hash: str | None = None
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class WorkflowTriggerDelivery:
    """A keys-only replay receipt for one trigger plus one source event."""

    trigger_id: str
    tenant_id: str
    source_event_digest: str
    status: str
    authority_subject: str | None = None
    run_id: str | None = None
    hitl_request_id: str | None = None
    reason: str | None = None
    created_at: datetime | None = None
