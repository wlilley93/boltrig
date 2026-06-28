"""The noun / verb / binding registry models (S6.1).

Agents reason in stable nouns and verbs. The kernel resolves each verb to a
concrete implementation via a binding. The agent never learns which concrete
system sits behind a verb (P4, K-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .base import AdapterId, NounId, TenantId, VerbId


class Consequence(str, Enum):
    """How impactful a verb is. ``high`` may require human approval (US-HIL-01)."""

    LOW = "low"
    HIGH = "high"


class TargetType(str, Enum):
    """What a verb binds to: a deterministic adapter or a reasoning agent (P3)."""

    ADAPTER = "adapter"
    AGENT = "agent"


@dataclass(frozen=True)
class Noun:
    """A stable concept agents reason about (e.g. ``ticket``)."""

    id: NounId
    tenant_id: TenantId
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verb:
    """A capability available on a noun (e.g. ``ticket.create``)."""

    id: VerbId
    tenant_id: TenantId
    noun_id: NounId
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    description: str = ""
    consequence: Consequence = Consequence.LOW
    # Optional: behaviour to synthesise when the binding is unavailable (P9).
    degraded_mode: dict[str, Any] | None = None
    # service-principal | delegated (US-IAM-03). delegated => OAuth on-behalf-of.
    identity_mode: str = "service-principal"


@dataclass(frozen=True)
class RateLimit:
    """A per-verb / per-tenant rate-limit policy (FR-KER-05)."""

    per: str  # 'minute' | 'hour'
    max: int
    scope: str = "tenant"  # 'tenant' | 'verb'


@dataclass(frozen=True)
class VerbBinding:
    """Resolves a verb to its implementation for a tenant."""

    verb_id: VerbId
    tenant_id: TenantId
    target_type: TargetType
    target_ref: AdapterId | str  # adapter id or agent-capability name
    rate_limit: RateLimit | None = None
