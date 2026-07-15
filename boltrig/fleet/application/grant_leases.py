"""Application service for short-lived, exact-scope MCP grant leases."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from boltrig.fleet.domain.execution import PhaseAssignmentRef
from boltrig.fleet.domain.grant_lease import (
    GrantLeaseBinding,
    GrantRootBinding,
    MAX_GRANT_TTL_SECONDS,
    MAX_PERMITTED_VERBS,
    StoredGrantLease,
    validate_revocation_reason,
)
from boltrig.fleet.ports.credentials import EphemeralBearer, GrantLease, IssuedGrant
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from boltrig.models import RunId, TenantId, VerbId, WorkspaceId, utcnow

HARD_MAX_TTL_SECONDS = MAX_GRANT_TTL_SECONDS
DEFAULT_MAX_TTL_SECONDS = 300


class GrantAuthenticationRejected(PermissionError):
    """A bearer, binding, generation, or concrete verb did not authenticate."""


def _aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generation(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("policy_generation must be a positive integer")
    return value


def _verb_snapshot(values: tuple[VerbId, ...]) -> tuple[VerbId, ...]:
    if type(values) is not tuple:
        raise TypeError("permitted_verbs must be an immutable tuple")
    snapshot: list[VerbId] = []
    for value in values:
        if len(snapshot) == MAX_PERMITTED_VERBS:
            raise ValueError(f"authority snapshots permit at most {MAX_PERMITTED_VERBS} verbs")
        snapshot.append(value)
    return tuple(snapshot)


class DurableRunScopedGrantBroker:
    """Mint opaque credentials from Boltrig-evaluated immutable verb snapshots only."""

    def __init__(
        self,
        store: GrantLeaseStore,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_ttl_seconds: int = DEFAULT_MAX_TTL_SECONDS,
    ) -> None:
        if type(max_ttl_seconds) is not int or not 1 <= max_ttl_seconds <= HARD_MAX_TTL_SECONDS:
            raise ValueError(f"max_ttl_seconds must be between 1 and {HARD_MAX_TTL_SECONDS}")
        self._store = store
        self._clock = clock
        self._max_ttl_seconds = max_ttl_seconds

    def _now(self) -> datetime:
        return _aware("server clock", self._clock())

    async def issue(
        self,
        assignment: PhaseAssignmentRef,
        *,
        expires_at: datetime,
        policy_generation: int,
        permitted_verbs: tuple[VerbId, ...],
        authority_evaluation_id: str,
        authority_evaluation_digest: str,
    ) -> IssuedGrant:
        """Issue once from concrete verbs already evaluated by Boltrig policy."""

        binding = GrantLeaseBinding.from_assignment(assignment)
        generation = _generation(policy_generation)
        now = self._now()
        expiry = _aware("expires_at", expires_at)
        if expiry <= now or expiry - now > timedelta(seconds=self._max_ttl_seconds):
            raise ValueError("requested lease expiry is outside the server TTL window")
        bearer = EphemeralBearer(secrets.token_urlsafe(32))
        lease_id = secrets.token_urlsafe(18)
        stored = StoredGrantLease(
            lease_id=lease_id,
            binding=binding,
            token_digest=_digest(bearer.reveal()),
            permitted_verbs=_verb_snapshot(permitted_verbs),
            authority_evaluation_id=authority_evaluation_id,
            authority_evaluation_digest=authority_evaluation_digest,
            issued_at=now,
            expires_at=expiry,
            max_ttl_seconds=self._max_ttl_seconds,
            policy_generation=generation,
        )
        await self._store.insert_active(stored, now=now)
        return IssuedGrant(
            lease=GrantLease(
                lease_id=lease_id,
                assignment=assignment,
                expires_at=expiry,
                policy_generation=generation,
            ),
            bearer_token=bearer,
        )

    async def authenticate(
        self,
        bearer: EphemeralBearer,
        assignment: PhaseAssignmentRef,
        *,
        verb_id: VerbId,
        policy_generation: int,
    ) -> StoredGrantLease:
        """Authenticate one exact concrete verb without accepting prompt-derived policy."""

        if not isinstance(bearer, EphemeralBearer):
            raise TypeError("bearer must be an EphemeralBearer")
        generation = _generation(policy_generation)
        binding = GrantLeaseBinding.from_assignment(assignment)
        now = self._now()
        lease = await self._store.find_active_by_digest(
            _digest(bearer.reveal()),
            binding,
            now=now,
            policy_generation=generation,
        )
        if not self._authorizes(lease, binding, now, generation, verb_id):
            raise GrantAuthenticationRejected("run-scoped grant rejected")
        if lease is None:  # pragma: no cover - narrowed by _authorizes
            raise GrantAuthenticationRejected("run-scoped grant rejected")
        return lease

    @staticmethod
    def _authorizes(
        lease: StoredGrantLease | None,
        binding: GrantLeaseBinding,
        now: datetime,
        policy_generation: int,
        verb_id: VerbId,
    ) -> bool:
        return bool(
            lease is not None
            and lease.binding == binding
            and lease.is_active_at(now, policy_generation=policy_generation)
            and isinstance(verb_id, str)
            and verb_id in lease.permitted_verbs
        )

    async def is_active(
        self,
        lease_id: str,
        assignment: PhaseAssignmentRef,
        *,
        at: datetime,
        policy_generation: int,
    ) -> bool:
        """Return metadata health using the server clock; this never authenticates a caller."""

        del at
        generation = _generation(policy_generation)
        binding = GrantLeaseBinding.from_assignment(assignment)
        now = self._now()
        lease = await self._store.find_active_by_id(
            lease_id,
            binding,
            now=now,
            policy_generation=generation,
        )
        return bool(
            lease is not None
            and lease.binding == binding
            and lease.is_active_at(now, policy_generation=generation)
        )

    async def revoke(
        self, lease_id: str, assignment: PhaseAssignmentRef, *, reason: str
    ) -> None:
        """Idempotently revoke only through an exact assignment binding."""

        binding = GrantLeaseBinding.from_assignment(assignment)
        await self._store.revoke_exact(
            lease_id,
            binding,
            now=self._now(),
            reason=validate_revocation_reason(reason),
        )

    async def revoke_bound(
        self, lease_id: str, assignment: PhaseAssignmentRef, *, reason: str
    ) -> None:
        """Revoke only when the caller supplies the lease's exact assignment binding."""

        await self.revoke(lease_id, assignment, reason=reason)

    async def cancel_assignment(self, assignment: PhaseAssignmentRef) -> int:
        """Immediately revoke every active bearer for a cancelled assignment."""

        return await self._store.revoke_assignment(
            GrantLeaseBinding.from_assignment(assignment),
            now=self._now(),
            reason="assignment_cancelled",
        )

    async def cancel_root(
        self, tenant_id: TenantId, workspace_id: WorkspaceId, root_run_id: RunId
    ) -> int:
        """Immediately revoke all root bearers without crossing tenant/workspace scope."""

        binding = GrantRootBinding(tenant_id, workspace_id, root_run_id)
        return await self._store.revoke_root(
            binding,
            now=self._now(),
            reason="root_run_cancelled",
        )


__all__ = [
    "DEFAULT_MAX_TTL_SECONDS",
    "DurableRunScopedGrantBroker",
    "GrantAuthenticationRejected",
    "HARD_MAX_TTL_SECONDS",
]
