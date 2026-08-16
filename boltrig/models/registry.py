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


class IdempotencyMode(str, Enum):
    """Whether successful output may be persisted and replayed by the kernel."""

    CACHEABLE = "cacheable"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Noun:
    """A stable concept agents reason about (e.g. ``ticket``)."""

    id: NounId
    tenant_id: TenantId
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    # Recoverable author withdrawal; archived nouns remain stored but are not
    # discoverable, bindable, or invocable.
    is_active: bool = True


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
    idempotency_mode: IdempotencyMode = IdempotencyMode.CACHEABLE
    # The binding is retained on archival so restore is lossless.
    is_active: bool = True


@dataclass(frozen=True)
class RateLimit:
    """A per-verb / per-tenant rate-limit policy (FR-KER-05).

    ``max`` is per FIXED CALENDAR window, not per sliding one. A configured 5/min
    therefore admits up to 10 within an arbitrarily short span that straddles a
    minute boundary, while the SUSTAINED rate stays at the configured value. That
    is a deliberate trade rather than an oversight
    ([2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001), and it is written here, at the
    point of configuration, so nobody has to read the counter to know what the
    number they are choosing actually delivers.

    Do not configure against this as if it were a hard instantaneous ceiling. If a
    surface ever needs one (an external quota with a penalty for overshoot, a
    lockout threshold, an irreversible spend where 2x is material), that is the
    evidence the judgment names for renewing the application for a sliding window.
    """

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

    def owned_by(self, adapter_id: str) -> bool:
        """Is this binding the named adapter's to change or remove?

        THE ACTIVATION OWNERSHIP CONVENTION, stated once so the two sides cannot
        drift. Deactivation has always used it -- `_unpublish_owned_verbs` only
        removes bindings whose target_ref is the adapter's own id, so retiring
        one adapter cannot delete another's work. Registration did not, and
        upserted over anything in its way, which is why a verb deliberately
        re-pointed at a reasoning agent reverted to the adapter on the next
        startup.

        A binding pointing at an AGENT is never an adapter's, whatever the
        agent-capability name happens to be: the target_type settles it before
        the ref is even compared.
        """
        return self.target_type is TargetType.ADAPTER and self.target_ref == adapter_id
