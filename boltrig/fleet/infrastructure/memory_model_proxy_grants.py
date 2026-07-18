"""Bounded atomic in-memory model-proxy grant storage."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypeAlias

from boltrig.fleet.domain.model_proxy_grant import (
    ActiveModelProxyGenerationConflict,
    ModelProxyClockRollback,
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    ModelProxyGrantStatus,
    StaleModelProxyGeneration,
    StoredModelProxyGrant,
    _aware,
    validate_model_proxy_revocation_reason,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    TrustedModelProxyRequestObservation,
)
from boltrig.models import utcnow

DEFAULT_MAX_MODEL_PROXY_RECORDS = 4_096
DEFAULT_MAX_MODEL_PROXY_FENCES = 2_048
HARD_MAX_MODEL_PROXY_STATE = 100_000

FenceState: TypeAlias = tuple[
    dict[ModelProxyCellScope, int],
    set[ModelProxyRootScope],
    set[ModelProxyPhaseScope],
    set[ModelProxyAssignmentScope],
    set[ModelProxyCellScope],
]


class ModelProxyGrantStoreCapacityExceeded(ModelProxyGrantConflict):
    """Security state cannot grow without exceeding its configured hard bound."""


class MemoryModelProxyGrantStore:
    """Digest-only store retaining generation and cancellation tombstones."""

    __slots__ = (
        "_cancelled_assignments",
        "_cancelled_cells",
        "_cancelled_phases",
        "_cancelled_roots",
        "_clock",
        "_clock_high_water",
        "_clock_rollback",
        "_highest_generation",
        "_lock",
        "_max_fences",
        "_max_records",
        "_records",
    )

    def __init__(
        self,
        *,
        max_records: int = DEFAULT_MAX_MODEL_PROXY_RECORDS,
        max_fences: int = DEFAULT_MAX_MODEL_PROXY_FENCES,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._max_records = _capacity("max_records", max_records)
        self._max_fences = _capacity("max_fences", max_fences)
        self._records: dict[str, StoredModelProxyGrant] = {}
        self._highest_generation: dict[ModelProxyCellScope, int] = {}
        self._cancelled_roots: set[ModelProxyRootScope] = set()
        self._cancelled_phases: set[ModelProxyPhaseScope] = set()
        self._cancelled_assignments: set[ModelProxyAssignmentScope] = set()
        self._cancelled_cells: set[ModelProxyCellScope] = set()
        self._clock = clock
        self._clock_high_water: datetime | None = None
        self._clock_rollback = False
        self._lock = asyncio.Lock()

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        if type(draft) is not ModelProxyGrantDraft:
            raise TypeError("draft must be an exact ModelProxyGrantDraft")
        async with self._lock:
            current = self._authoritative_now()
            if self._clock_rollback:
                raise ModelProxyClockRollback("model-proxy clock moved backwards")
            grant = StoredModelProxyGrant(
                grant_id=draft.grant_id,
                binding=draft.binding,
                bearer_digest=draft.bearer_digest,
                startup_request_digest=draft.startup_request_digest,
                issued_at=current,
                expires_at=current + timedelta(seconds=draft.ttl_seconds),
                generation=draft.generation,
            )
            if self._is_cancelled(grant.binding.cell):
                raise StaleModelProxyGeneration("model-proxy scope is terminally cancelled")
            if self._collides(grant):
                raise ModelProxyGrantConflict("model-proxy credential was already inserted")
            highest = self._highest_generation.get(grant.binding.cell)
            active = self._active_for_cell(grant.binding.cell, current)
            if any(item.generation == grant.generation for item in active):
                raise ActiveModelProxyGenerationConflict("model-proxy generation is already active")
            if highest is not None and grant.generation <= highest:
                raise StaleModelProxyGeneration("model-proxy generation is stale")
            if len(self._records) >= self._max_records:
                raise ModelProxyGrantStoreCapacityExceeded("model-proxy store capacity exceeded")
            if highest is None and self._fence_count() >= self._max_fences:
                raise ModelProxyGrantStoreCapacityExceeded("model-proxy store capacity exceeded")
            replacements = self._expiry_plan(current)
            for record in active:
                replacements[record.grant_id] = record.revoke(
                    now=current, reason="superseded_generation"
                )
            self._records.update(replacements)
            self._records[grant.grant_id] = grant
            self._highest_generation[grant.binding.cell] = grant.generation
            return grant

    async def find_active_for_trusted_observation(
        self,
        bearer_digest: str,
        observation: TrustedModelProxyRequestObservation,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        if type(observation) is not TrustedModelProxyRequestObservation:
            raise TypeError("observation must be an exact TrustedModelProxyRequestObservation")
        if not _digest_candidate(bearer_digest):
            return None
        async with self._lock:
            current = self._authoritative_now()
            if self._clock_rollback:
                return None
            self._records.update(self._expiry_plan(current))
            matched: StoredModelProxyGrant | None = None
            for record in self._records.values():
                if hmac.compare_digest(record.bearer_digest, bearer_digest):
                    matched = record
            if (
                matched is not None
                and matched.binding == observation.binding
                and matched.active_at(current, generation=generation)
            ):
                return matched
            return None

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        if type(binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        if type(grant_id) is not str:
            return None
        async with self._lock:
            current = self._authoritative_now()
            if self._clock_rollback:
                return None
            self._records.update(self._expiry_plan(current))
            record = self._records.get(grant_id)
            if (
                record is not None
                and record.binding == binding
                and record.active_at(current, generation=generation)
            ):
                return record
            return None

    async def find_active_by_bearer_digest(
        self, bearer_digest: str, *, generation: int
    ) -> StoredModelProxyGrant | None:
        """Find an active grant by its bearer digest alone, without a binding.

        The bearer-authenticated loopback channel authorised by [2026] VJS-CC-VJS 1:
        issuance is SO_PEERCRED-gated over the unix socket, so possession of the
        issued bearer secret IS the capability and the model-call proxy verifies a
        presented bearer by digest alone (it holds no peer-attested observation).
        Constant-time digest comparison; expiry is applied before the match.
        """
        if not _digest_candidate(bearer_digest):
            return None
        async with self._lock:
            current = self._authoritative_now()
            if self._clock_rollback:
                return None
            self._records.update(self._expiry_plan(current))
            for record in self._records.values():
                if hmac.compare_digest(
                    record.bearer_digest, bearer_digest
                ) and record.active_at(current, generation=generation):
                    return record
            return None

    async def get_by_id(
        self, grant_id: str, binding: ModelProxyGrantBinding
    ) -> StoredModelProxyGrant | None:
        if type(binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        if type(grant_id) is not str:
            return None
        async with self._lock:
            record = self._records.get(grant_id)
            return record if record is not None and record.binding == binding else None

    async def revoke_root(self, scope: ModelProxyRootScope, *, reason: str) -> int:
        if type(scope) is not ModelProxyRootScope:
            raise TypeError("scope must be an exact ModelProxyRootScope")
        return await self._revoke(
            lambda cell: _root(cell) == scope,
            lambda: self._plan_root(scope),
            reason=reason,
        )

    async def revoke_phase(self, scope: ModelProxyPhaseScope, *, reason: str) -> int:
        if type(scope) is not ModelProxyPhaseScope:
            raise TypeError("scope must be an exact ModelProxyPhaseScope")
        return await self._revoke(
            lambda cell: cell.assignment.phase == scope,
            lambda: self._plan_phase(scope),
            reason=reason,
        )

    async def revoke_assignment(self, scope: ModelProxyAssignmentScope, *, reason: str) -> int:
        if type(scope) is not ModelProxyAssignmentScope:
            raise TypeError("scope must be an exact ModelProxyAssignmentScope")
        return await self._revoke(
            lambda cell: cell.assignment == scope,
            lambda: self._plan_assignment(scope),
            reason=reason,
        )

    async def revoke_cell(self, scope: ModelProxyCellScope, *, reason: str) -> int:
        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        return await self._revoke(
            lambda cell: cell == scope,
            lambda: self._plan_cell(scope),
            reason=reason,
        )

    async def _revoke(
        self,
        predicate: Callable[[ModelProxyCellScope], bool],
        plan_fences: Callable[[], FenceState],
        *,
        reason: str,
    ) -> int:
        safe_reason = validate_model_proxy_revocation_reason(reason)
        async with self._lock:
            current = self._authoritative_now()
            plan = plan_fences()
            self._require_fence_capacity(plan)
            replacements = self._expiry_plan(current)
            count = 0
            for grant_id, record in self._records.items():
                if (
                    record.status is ModelProxyGrantStatus.ACTIVE
                    and record.expires_at > current
                    and predicate(record.binding.cell)
                ):
                    replacements[grant_id] = record.revoke(now=current, reason=safe_reason)
                    count += 1
            self._install_fences(plan)
            self._records.update(replacements)
            return count

    def _authoritative_now(self) -> datetime:
        current = _aware("store clock", self._clock())
        high_water = self._clock_high_water
        if self._clock_rollback:
            return high_water or current
        if high_water is not None and current < high_water:
            self._clock_rollback = True
            self._records.update(
                {
                    grant_id: record.revoke(now=high_water, reason="clock_rollback")
                    for grant_id, record in self._records.items()
                    if record.status is ModelProxyGrantStatus.ACTIVE
                }
            )
            return high_water
        self._clock_high_water = current
        return current

    def _plan_root(self, scope: ModelProxyRootScope) -> FenceState:
        generations, roots, phases, assignments, cells = self._copy_fences()
        roots.add(scope)
        generations = {cell: value for cell, value in generations.items() if _root(cell) != scope}
        phases = {item for item in phases if item.root != scope}
        assignments = {item for item in assignments if item.phase.root != scope}
        cells = {item for item in cells if _root(item) != scope}
        return generations, roots, phases, assignments, cells

    def _plan_phase(self, scope: ModelProxyPhaseScope) -> FenceState:
        generations, roots, phases, assignments, cells = self._copy_fences()
        if scope.root not in roots:
            phases.add(scope)
        generations = {
            cell: value for cell, value in generations.items() if cell.assignment.phase != scope
        }
        assignments = {item for item in assignments if item.phase != scope}
        cells = {item for item in cells if item.assignment.phase != scope}
        return generations, roots, phases, assignments, cells

    def _plan_assignment(self, scope: ModelProxyAssignmentScope) -> FenceState:
        generations, roots, phases, assignments, cells = self._copy_fences()
        if scope.phase.root not in roots and scope.phase not in phases:
            assignments.add(scope)
        generations = {
            cell: value for cell, value in generations.items() if cell.assignment != scope
        }
        cells = {item for item in cells if item.assignment != scope}
        return generations, roots, phases, assignments, cells

    def _plan_cell(self, scope: ModelProxyCellScope) -> FenceState:
        generations, roots, phases, assignments, cells = self._copy_fences()
        parent_cancelled = (
            _root(scope) in roots
            or scope.assignment.phase in phases
            or scope.assignment in assignments
        )
        if not parent_cancelled:
            cells.add(scope)
        generations.pop(scope, None)
        return generations, roots, phases, assignments, cells

    def _copy_fences(self) -> FenceState:
        return (
            dict(self._highest_generation),
            set(self._cancelled_roots),
            set(self._cancelled_phases),
            set(self._cancelled_assignments),
            set(self._cancelled_cells),
        )

    def _install_fences(self, state: FenceState) -> None:
        (
            self._highest_generation,
            self._cancelled_roots,
            self._cancelled_phases,
            self._cancelled_assignments,
            self._cancelled_cells,
        ) = state

    def _require_fence_capacity(self, state: FenceState) -> None:
        if sum(len(items) for items in state) > self._max_fences:
            raise ModelProxyGrantStoreCapacityExceeded("model-proxy store capacity exceeded")

    def _fence_count(self) -> int:
        return sum(len(items) for items in self._copy_fences())

    def _is_cancelled(self, cell: ModelProxyCellScope) -> bool:
        return (
            _root(cell) in self._cancelled_roots
            or cell.assignment.phase in self._cancelled_phases
            or cell.assignment in self._cancelled_assignments
            or cell in self._cancelled_cells
        )

    def _active_for_cell(
        self, cell: ModelProxyCellScope, now: datetime
    ) -> tuple[StoredModelProxyGrant, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.binding.cell == cell
            and record.status is ModelProxyGrantStatus.ACTIVE
            and record.expires_at > now
        )

    def _collides(self, grant: StoredModelProxyGrant) -> bool:
        digest_collision = False
        request_collision = False
        for record in self._records.values():
            digest_collision = (
                hmac.compare_digest(record.bearer_digest, grant.bearer_digest) or digest_collision
            )
            request_collision = (
                hmac.compare_digest(record.startup_request_digest, grant.startup_request_digest)
                or request_collision
            )
        return grant.grant_id in self._records or digest_collision or request_collision

    def _expiry_plan(self, now: datetime) -> dict[str, StoredModelProxyGrant]:
        return {
            grant_id: record.expire()
            for grant_id, record in self._records.items()
            if record.status is ModelProxyGrantStatus.ACTIVE and record.expires_at <= now
        }

    def snapshot(self) -> tuple[StoredModelProxyGrant, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


def _capacity(label: str, value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_MODEL_PROXY_STATE:
        raise ValueError(f"{label} must be between 1 and {HARD_MAX_MODEL_PROXY_STATE}")
    return value


def _digest_candidate(value: object) -> bool:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _root(cell: ModelProxyCellScope) -> ModelProxyRootScope:
    return cell.assignment.phase.root
