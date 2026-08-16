"""Round Five memory models: the governance + provenance control plane.

The swappable Memory Engine owns the graph/vector store internally; Boltrig
persists the metadata it must control *independently* of the engine: which scope
owns a fact, where it came from (provenance), whether it is sensitive, the
ingestion runs, and the erasure ledger. ``owner_scope`` is the RBAC boundary the
kernel - never the engine alone - enforces at both ingestion and retrieval
(SEC-40). Frozen-style dataclasses (domain state), tenant-isolated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, utcnow


# --- a governed memory fact (mirrors/links an engine node) -------------------
@dataclass
class MemoryFact:
    id: str  # Boltrig id, mapped to the engine node id
    tenant_id: TenantId
    owner_scope: str  # user:<id> | department:<name> | org  (the RBAC boundary)
    engine_ref: str  # the engine's node/record identifier
    kind: str  # semantic | episodic | procedural | entity | relationship | summary | document_chunk
    source_kind: str  # conversation | document | verb_result | feedback
    source_ref: str | None = None  # conversation id / document id / run id
    data_class: str = "standard"  # standard | sensitive (sensitive -> local only)
    content: str = ""  # a short human-readable label (the engine holds the rest)
    created_at: datetime = field(default_factory=utcnow)
    redacted: bool = False
    # --- typed memory planes (decision 0029): slots, versions, write-gate state
    # ``memory_key`` is the stable logical slot for semantic/procedural memory
    # (``{subject_type}::{subject_id}::{predicate}::{owner_scope}`` for facts,
    # ``procedure::{procedure_key}::{owner_scope}`` for procedures); episodes
    # are append-only and carry no key. ``status`` is the write-gate state
    # machine; exactly one ``active`` row per (tenant, memory_key) may exist for
    # semantic/procedural kinds - enforced by partial unique indexes (0076).
    memory_key: str | None = None
    status: str = "active"  # candidate | active | superseded | rejected
    version: int = 1
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    supersedes_id: str | None = None


# --- the typed-memory write-gate event trail (`add_memory_event`) -----------
@dataclass
class MemoryEvent:
    """One machine-readable write-gate decision, for tuning and inspection.

    Events record WHAT the gate decided and under which policy version - never
    the memory content itself (the fact row already owns that, scope-fenced).
    """

    id: str
    tenant_id: TenantId
    event: str  # candidate_created | candidate_rejected | memory_approved | memory_activated | memory_superseded | memory_confirmed
    memory_id: str | None = None
    memory_key: str | None = None
    decision: str | None = None  # the gate's decision code, when the event is one
    policy_version: str = "typed-write-v1"
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


# --- a cognify ingestion run (the durable pipeline record) -------------------
@dataclass
class MemoryIngestion:
    id: str
    tenant_id: TenantId
    source_kind: str
    source_ref: str
    owner_scope: str
    status: str = "pending"  # pending | screening | cognifying | done | failed | rejected
    hatchet_run_id: str | None = None
    facts_added: int = 0
    screened: bool = False  # injection/malware screen passed
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


# --- the right-to-be-forgotten ledger (verifiable completeness) --------------
@dataclass
class MemoryErasure:
    id: str
    tenant_id: TenantId
    requested_by: str
    target: str  # a fact id, a source_ref, a subject, or a scope
    scope: str
    engine_confirmed: bool = False  # engine reported deletion of node + derived edges
    transcript_handled: bool = False  # linked transcripts handled per policy
    facts_removed: int = 0
    created_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None


@dataclass
class MemoryProjectionStatus:
    """Per-backend projection state for kernel-led memory fanout.

    The canonical memory fact/erasure is owned by Boltrig. Cognee or any other
    backend is a projection with its own write/delete state and external
    reference. This row is the operator-visible answer to "did the projection
    catch up?" without making the projection authoritative.
    """

    id: str
    tenant_id: TenantId
    projection_id: str
    operation: str  # remember | forget
    status: str  # pending | written | failed | deleted | delete_failed
    fact_id: str | None = None
    target: str | None = None
    projection_ref: str | None = None
    error: str | None = None
    enqueue_attempts: int = 0
    operation_attempts: int = 0
    max_operation_attempts: int = 1
    first_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_code: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
