"""The invocation context that travels with every kernel call (S7.1).

Identity in the context is authenticated-by-construction (K-3): the kernel
stamps ``tenant_id`` / ``on_behalf_of`` from the verified bearer at the door;
they are never read from untrusted request fields by handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import RunId, TenantId, UserId
from .grants import EMPTY_GRANTS, GrantSet


@dataclass(frozen=True)
class InvocationContext:
    tenant_id: TenantId
    run_id: RunId | None = None
    parent_run_id: RunId | None = None
    depth: int = 0
    on_behalf_of: UserId | None = None  # delegated human identity (US-IAM-03)
    grants: GrantSet = field(default_factory=lambda: EMPTY_GRANTS)
    actor: str = "unknown"  # agent capability name or user id
    actor_tier: str = "ephemeral"  # tier1 | tier2 | ephemeral | human
    skills_loaded: tuple[str, ...] = ()
    # Arbitrary task context a skill may require (S7.5, e.g. epic_id, team_context).
    # The kernel dispatch never reads this; it carries skill-context for spawn-time
    # validation against a skill's context_requirements (US-SKL-01).
    extra: dict[str, Any] = field(default_factory=dict)
