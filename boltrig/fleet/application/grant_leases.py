"""Application service for short-lived, exact-scope MCP grant leases."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from boltrig.fleet.domain.execution import PhaseAssignmentRef
from boltrig.fleet.domain.grant_lease import (
    GrantLeaseCandidate,
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRequestObservation,
    GrantRootBinding,
    MAX_GRANT_TTL_SECONDS,
    StoredGrantLease,
    validate_revocation_reason,
)
from boltrig.fleet.ports.credentials import EphemeralBearer, GrantLease, IssuedGrant
from boltrig.fleet.ports.grant_authority import GrantAuthoritySnapshotResolver
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from boltrig.models import RunId, TenantId, WorkspaceId, utcnow

from .grant_lease_cleanup import (
    cleanup_committed_issue,
    finish_issue_cleanup,
    reconcile_issue_receipt,
)

HARD_MAX_TTL_SECONDS = MAX_GRANT_TTL_SECONDS
DEFAULT_MAX_TTL_SECONDS = 300


class GrantAuthenticationRejected(PermissionError):
    """A bearer, binding, authority generation, or concrete verb did not authenticate."""


class GrantAuthorityUnavailable(PermissionError):
    """No trusted current authority snapshot permits grant issuance."""


def _aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DurableRunScopedGrantBroker:
    """Mint opaque credentials from trusted immutable authority snapshots only.

    A durable operation receipt reconciles an ambiguous commit while this issue call
    still owns the process-local bearer. A process crash cannot recover that bearer,
    so replaying the operation must never mint a replacement credential. Production
    wiring remains blocked until the resolver and store share durable transactional
    assignment, approval, lifecycle, and current-authority state.
    """

    def __init__(
        self,
        store: GrantLeaseStore,
        authority_resolver: GrantAuthoritySnapshotResolver,
        *,
        clock: Callable[[], datetime] = utcnow,
        max_ttl_seconds: int = DEFAULT_MAX_TTL_SECONDS,
    ) -> None:
        if type(max_ttl_seconds) is not int or not 1 <= max_ttl_seconds <= HARD_MAX_TTL_SECONDS:
            raise ValueError(f"max_ttl_seconds must be between 1 and {HARD_MAX_TTL_SECONDS}")
        self._store = store
        self._authority_resolver = authority_resolver
        self._clock = clock
        self._max_ttl_seconds = max_ttl_seconds

    def _now(self) -> datetime:
        return _aware("server clock", self._clock())

    async def issue(
        self,
        assignment: PhaseAssignmentRef,
        *,
        expires_at: datetime,
        issue_operation_id: str,
        expected_current_lease_generation: int | None,
    ) -> IssuedGrant:
        """Issue once from concrete verbs already evaluated by Boltrig policy."""

        binding = GrantLeaseBinding.from_assignment(assignment)
        authority_observed_at = self._now()
        authority = await self._resolve_current_authority(
            assignment,
            now=authority_observed_at,
        )
        now = max(authority_observed_at, self._now())
        expiry = _aware("expires_at", expires_at)
        if expiry <= now or expiry - now > timedelta(seconds=self._max_ttl_seconds):
            raise ValueError("requested lease expiry is outside the server TTL window")
        candidate, bearer = self._new_candidate(
            binding,
            authority,
            issued_at=now,
            expires_at=expiry,
            issue_operation_id=issue_operation_id,
            expected_current_lease_generation=expected_current_lease_generation,
        )
        store_task = asyncio.create_task(
            self._store.insert_active(
                candidate,
                expected_authority=authority,
                now=now,
            )
        )
        try:
            try:
                stored = await asyncio.shield(store_task)
            except Exception:
                reconciled = await reconcile_issue_receipt(self._store, candidate)
                if reconciled is None:
                    raise
                stored = reconciled
            await self._verify_active_projection(
                candidate,
                stored,
                authority,
                now=max(now, self._now()),
            )
            return self._issued_grant(stored, assignment, bearer)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(
                cleanup_committed_issue(
                    self._store,
                    store_task,
                    candidate,
                    now=max(now, self._now()),
                    reason="issue_cancelled",
                )
            )
            await finish_issue_cleanup(cleanup)
            raise
        except Exception as issue_error:
            cleanup = asyncio.create_task(
                cleanup_committed_issue(
                    self._store,
                    store_task,
                    candidate,
                    now=max(now, self._now()),
                    reason="issue_failed",
                )
            )
            try:
                await finish_issue_cleanup(cleanup)
            except Exception:
                issue_error.add_note("exact issue cleanup also failed")
            raise

    def _new_candidate(
        self,
        binding: GrantLeaseBinding,
        authority: GrantAuthoritySnapshot,
        *,
        issued_at: datetime,
        expires_at: datetime,
        issue_operation_id: str,
        expected_current_lease_generation: int | None,
    ) -> tuple[GrantLeaseCandidate, EphemeralBearer]:
        bearer = EphemeralBearer(secrets.token_urlsafe(32))
        candidate = GrantLeaseCandidate(
            lease_id=secrets.token_urlsafe(18),
            issue_operation_id=issue_operation_id,
            binding=binding,
            token_digest=_digest(bearer.reveal()),
            authority_snapshot=authority,
            issued_at=issued_at,
            expires_at=expires_at,
            max_ttl_seconds=self._max_ttl_seconds,
            expected_current_lease_generation=expected_current_lease_generation,
        )
        return candidate, bearer

    @staticmethod
    def _issued_grant(
        stored: StoredGrantLease,
        assignment: PhaseAssignmentRef,
        bearer: EphemeralBearer,
    ) -> IssuedGrant:
        return IssuedGrant(
            lease=GrantLease(
                lease_id=stored.lease_id,
                issue_operation_id=stored.issue_operation_id,
                assignment=assignment,
                expires_at=stored.expires_at,
                authority_policy_generation=stored.authority_policy_generation,
                lease_generation=stored.lease_generation,
            ),
            bearer_token=bearer,
        )

    async def authenticate(
        self,
        bearer: EphemeralBearer,
        observation: GrantRequestObservation,
    ) -> StoredGrantLease:
        """Authenticate one exact concrete verb without accepting prompt-derived policy."""

        if type(bearer) is not EphemeralBearer:
            raise TypeError("bearer must be an EphemeralBearer")
        if type(observation) is not GrantRequestObservation:
            raise TypeError("observation must be an exact GrantRequestObservation")
        binding = observation.binding
        authority_observed_at = self._now()
        authority = await self._resolve_current_authority(
            observation.assignment,
            now=authority_observed_at,
            reject_for_authentication=True,
        )
        now = max(authority_observed_at, self._now())
        lease = await self._store.find_active_by_digest(
            _digest(bearer.reveal()),
            binding,
            now=now,
            expected_authority=authority,
        )
        verified_at = max(now, self._now())
        if lease is None or not lease.authorizes_request(
            binding,
            authority,
            at=verified_at,
            verb_id=observation.verb_id,
        ):
            raise GrantAuthenticationRejected("run-scoped grant rejected")
        return lease

    async def _resolve_current_authority(
        self,
        assignment: PhaseAssignmentRef,
        *,
        now: datetime,
        reject_for_authentication: bool = False,
    ) -> GrantAuthoritySnapshot:
        try:
            authority = await self._authority_resolver.resolve_current_grant_authority(
                assignment,
                at=now,
            )
        except Exception as exc:
            if reject_for_authentication:
                raise GrantAuthenticationRejected("run-scoped grant rejected") from exc
            raise GrantAuthorityUnavailable(
                "trusted current grant authority is unavailable"
            ) from exc
        binding = GrantLeaseBinding.from_assignment(assignment)
        if type(authority) is not GrantAuthoritySnapshot or authority.binding != binding:
            if reject_for_authentication:
                raise GrantAuthenticationRejected("run-scoped grant rejected")
            raise GrantAuthorityUnavailable("trusted current grant authority is unavailable")
        return authority

    async def _verify_active_projection(
        self,
        candidate: GrantLeaseCandidate,
        stored: StoredGrantLease,
        authority: GrantAuthoritySnapshot,
        *,
        now: datetime,
    ) -> None:
        expected_generation = (
            1
            if candidate.expected_current_lease_generation is None
            else candidate.expected_current_lease_generation + 1
        )
        valid_projection = (
            type(stored) is StoredGrantLease
            and stored.is_projection_of(candidate)
            and stored.lease_generation == expected_generation
            and stored.status is GrantLeaseStatus.ACTIVE
            and stored.authority_snapshot == authority
            and stored.is_active_at(
                now,
                authority_policy_generation=authority.authority_policy_generation,
            )
        )
        if valid_projection:
            active = await self._store.find_active_by_id(
                stored.lease_id,
                stored.binding,
                now=now,
                expected_authority=authority,
            )
            verified_at = max(now, self._now())
            valid_projection = active == stored and stored.is_active_at(
                verified_at,
                authority_policy_generation=authority.authority_policy_generation,
            )
            now = verified_at
        if valid_projection:
            return
        await self._store.revoke_exact(
            candidate.lease_id,
            candidate.binding,
            now=now,
            reason="invalid_issue_projection",
        )
        raise GrantLeaseConflict("grant store returned an invalid issue projection")

    async def is_active(
        self,
        lease_id: str,
        assignment: PhaseAssignmentRef,
    ) -> bool:
        """Return metadata health using the server clock; this never authenticates a caller."""

        binding = GrantLeaseBinding.from_assignment(assignment)
        authority_observed_at = self._now()
        authority = await self._authority_resolver.resolve_current_grant_authority(
            assignment,
            at=authority_observed_at,
        )
        if type(authority) is not GrantAuthoritySnapshot or authority.binding != binding:
            return False
        now = max(authority_observed_at, self._now())
        lease = await self._store.find_active_by_id(
            lease_id,
            binding,
            now=now,
            expected_authority=authority,
        )
        verified_at = max(now, self._now())
        return bool(
            lease is not None
            and lease.binding == binding
            and lease.authority_snapshot == authority
            and lease.is_active_at(
                verified_at,
                authority_policy_generation=authority.authority_policy_generation,
            )
        )

    async def revoke(self, lease_id: str, assignment: PhaseAssignmentRef, *, reason: str) -> None:
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
    "GrantAuthorityUnavailable",
    "HARD_MAX_TTL_SECONDS",
]
