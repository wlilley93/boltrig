"""Pure-data contracts carried across the Hatchet queue boundary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InvokeInput(BaseModel):
    """One governed verb invocation."""

    tenant: str
    noun: str
    verb: str
    params: dict[str, Any] = Field(default_factory=dict)
    ctx_envelope: dict[str, Any]
    run_id: str | None = None
    step: str | None = None


class WorkItemInput(BaseModel):
    """The pump's claimed-item body."""

    tenant_id: str
    item_id: str


class WorkflowRunInput(BaseModel):
    """One interpreted workflow occurrence."""

    tenant: str
    workflow_id: str
    workflow_snapshot: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    ctx_envelope: dict[str, Any]
    run_id: str
    conversation_id: str | None = None


__all__ = ["InvokeInput", "WorkItemInput", "WorkflowRunInput"]
