"""Short-lived, run-scoped domain-authority grant broker port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, Protocol

from boltrig.fleet.domain import PhaseAssignmentRef
from boltrig.models import VerbId


class EphemeralBearer:
    """Non-serializable secret wrapper for a one-time runtime handoff."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("ephemeral bearer cannot be empty")
        self.__value = value

    def reveal(self) -> str:
        """Reveal only at the transport boundary that consumes the credential."""
        return self.__value

    def __repr__(self) -> str:
        return "EphemeralBearer(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("ephemeral bearers cannot be serialized")


@dataclass(frozen=True)
class GrantLease:
    """Persistable metadata for an expiring, immediately revocable grant."""

    lease_id: str
    assignment: PhaseAssignmentRef
    expires_at: datetime
    policy_generation: int


@dataclass(frozen=True)
class IssuedGrant:
    """One-time credential handoff; secret material is excluded from repr."""

    lease: GrantLease
    bearer_token: EphemeralBearer

    def __repr__(self) -> str:
        return f"IssuedGrant(lease={self.lease!r}, bearer_token=<redacted>)"


class RunScopedGrantBroker(Protocol):
    """Issue and revoke Opbox/MCP authority without durable parent credentials."""

    async def issue(
        self,
        assignment: PhaseAssignmentRef,
        *,
        expires_at: datetime,
        policy_generation: int,
        permitted_verbs: tuple[VerbId, ...],
        authority_evaluation_id: str,
        authority_evaluation_digest: str,
    ) -> IssuedGrant: ...

    async def revoke(
        self, lease_id: str, assignment: PhaseAssignmentRef, *, reason: str
    ) -> None: ...

    async def is_active(
        self,
        lease_id: str,
        assignment: PhaseAssignmentRef,
        *,
        at: datetime,
        policy_generation: int,
    ) -> bool: ...
