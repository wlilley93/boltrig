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
    kind: str  # entity | relationship | summary | document_chunk
    source_kind: str  # conversation | document | verb_result | feedback
    source_ref: str | None = None  # conversation id / document id / run id
    data_class: str = "standard"  # standard | sensitive (sensitive -> local only)
    content: str = ""  # a short human-readable label (the engine holds the rest)
    created_at: datetime = field(default_factory=utcnow)
    redacted: bool = False


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
