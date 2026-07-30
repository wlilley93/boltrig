"""Round Three platform models (authoring, eval, customisation, memory).

All carry ``tenant_id`` and are tenant-isolated. Authoring/admin edits are
versioned (``ConfigRevision``) so every in-app change round-trips to manifest/YAML
and is reversible (C1, C2, NFR-REL-01). Frozen dataclasses (domain state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, utcnow


# --- versioned configuration & library edits (C1/C2/C3) ----------------------
@dataclass
class ConfigRevision:
    tenant_id: TenantId
    kind: str  # manifest_section | skill | workflow | noun | verb | binding | adapter
    ref: str  # which entity (skill id, section name, ...)
    version: str
    payload: dict[str, Any]
    actor: str
    id: int | None = None  # assigned by the store (monotonic / BIGSERIAL)
    created_at: datetime = field(default_factory=utcnow)
    rolled_back: bool = False


# --- evaluation harness (Epic EVAL) ------------------------------------------
EVAL_TARGET_KINDS: tuple[str, ...] = ("skill", "workflow")


@dataclass
class EvalCase:
    id: str
    tenant_id: TenantId
    target_kind: str  # one of EVAL_TARGET_KINDS
    target_ref: str
    input: dict[str, Any]
    assertions: dict[str, Any]  # expected output / must-call / must-not / rubric
    labels: list[str] = field(default_factory=list)
    # Archival is recoverable: fixture content and historical runs stay intact.
    is_active: bool = True


@dataclass
class EvalRun:
    id: str
    tenant_id: TenantId
    case_id: str
    passed: bool
    score: float
    detail: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None  # the fleet run produced
    created_at: datetime = field(default_factory=utcnow)


# --- notification preferences (Epic NOT, completes US-CUS-02) -----------------
@dataclass
class NotificationPref:
    id: str
    tenant_id: TenantId
    scope_kind: str  # user | team
    scope_ref: str
    event_type: str  # server-declared producer event (notification_catalogue)
    channel: str  # exact enabled socket channel id; legacy rows may name a platform
    target: str | None = None
    enabled: bool = True


# --- personal agents (Epic PA, completes US-CUS-03) --------------------------
@dataclass
class PersonalAgent:
    id: str
    tenant_id: TenantId
    user_id: UserId  # the owner; acts ONLY under the owner's delegated permissions
    runtime: str  # a capability name (e.g. pi-worker)
    skills: list[str] = field(default_factory=list)
    enabled: bool = True


# --- memory & knowledge (Epic MEM, optional) ---------------------------------
@dataclass
class MemoryItem:
    id: str
    tenant_id: TenantId
    owner_scope: str  # user:<id> | department:<name> | org  (the RBAC boundary)
    kind: str  # fact | summary | document_chunk
    content: str
    embedding: list[float] | None = None
    source_ref: str | None = None
    data_class: str = "standard"  # standard | sensitive (sensitive -> local only, SEC-31)
    created_at: datetime = field(default_factory=utcnow)
