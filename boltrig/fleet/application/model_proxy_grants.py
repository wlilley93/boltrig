"""Issue and cancel model-only credentials; bearer authentication stays off here."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from typing import NoReturn, TypeVar

from boltrig.fleet.application.model_proxy_cache import (
    CachedModelProxyBearer as _CachedBearer,
    ModelProxyCacheKey as _CacheKey,
    ModelProxyStartupFingerprint as _StartupFingerprint,
)
from boltrig.fleet.application.model_proxy_cancellations import (
    CancelToken,
    ModelProxyCancellationScope,
    ModelProxyCancellationTracker,
)
from boltrig.fleet.application.model_proxy_deadline import (
    ModelProxyDeadlineElapsed,
    ModelProxyIssuanceDeadline,
)
from boltrig.fleet.application.model_proxy_store_projection import (
    require_active_projection,
    require_insert_projection,
)
from boltrig.fleet.domain.model_proxy_grant import (
    IssuedModelProxyGrant,
    MAX_MODEL_PROXY_GRANT_TTL_SECONDS,
    ModelProxyBearer,
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    ModelProxyGrantReceipt,
    validate_model_proxy_generation,
    validate_model_proxy_identifier,
    validate_model_proxy_ttl_seconds,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    model_proxy_startup_digest,
)
from boltrig.fleet.ports.model_proxy_grants import ModelProxyGrantStore

DEFAULT_MODEL_PROXY_TTL_SECONDS = 60
DEFAULT_MAX_EPHEMERAL_BEARERS = 1_024
HARD_MAX_EPHEMERAL_BEARERS = 10_000
_STRIPE_COUNT = 64
_T = TypeVar("_T")


class ModelProxyBearerCacheCapacityExceeded(ModelProxyGrantConflict):
    """The bounded idempotent-startup cache cannot retain another bearer."""


class PhaseScopedModelProxyGrantBroker:
    """Mint bounded model-only credentials without MCP or Opbox authority."""

    __slots__ = (
        "_cache",
        "_cache_lock",
        "_cancellations",
        "_max_cache",
        "_max_ttl",
        "_reservations",
        "_store",
        "_stripes",
    )

    def __init__(
        self,
        store: ModelProxyGrantStore,
        *,
        max_ttl_seconds: int = DEFAULT_MODEL_PROXY_TTL_SECONDS,
        max_cached_bearers: int = DEFAULT_MAX_EPHEMERAL_BEARERS,
    ) -> None:
        if type(max_ttl_seconds) is not int or not (
            1 <= max_ttl_seconds <= MAX_MODEL_PROXY_GRANT_TTL_SECONDS
        ):
            raise ValueError("max_ttl_seconds must be between 1 and 120")
        if type(max_cached_bearers) is not int or not (
            1 <= max_cached_bearers <= HARD_MAX_EPHEMERAL_BEARERS
        ):
            raise ValueError(
                f"max_cached_bearers must be between 1 and {HARD_MAX_EPHEMERAL_BEARERS}"
            )
        self._store = store
        self._max_ttl = max_ttl_seconds
        self._max_cache = max_cached_bearers
        self._cache: dict[_CacheKey, _CachedBearer] = {}
        self._cache_lock = asyncio.Lock()
        self._cancellations = ModelProxyCancellationTracker()
        self._reservations: set[ModelProxyCellScope] = set()
        self._stripes = tuple(asyncio.Lock() for _ in range(_STRIPE_COUNT))

    async def issue(
        self,
        startup_request_id: str,
        binding: ModelProxyGrantBinding,
        *,
        ttl_seconds: int = DEFAULT_MODEL_PROXY_TTL_SECONDS,
        generation: int,
    ) -> IssuedModelProxyGrant:
        request_id = validate_model_proxy_identifier("startup_request_id", startup_request_id)
        if type(binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        ttl = validate_model_proxy_ttl_seconds(ttl_seconds)
        if ttl > self._max_ttl:
            raise ValueError("requested model-proxy TTL exceeds the broker maximum")
        fingerprint = _StartupFingerprint(ttl, validate_model_proxy_generation(generation))
        key = _CacheKey(binding, request_id)
        async with self._stripe(binding.cell):
            cached = await self._current_cached(key, fingerprint)
            if cached is not None:
                return _issued(cached)
            task = asyncio.create_task(self._mint(key, fingerprint), name="model-proxy-grant-issue")
            return await _cancellation_safe(task)

    async def cancel_root(self, scope: ModelProxyRootScope) -> int:
        if type(scope) is not ModelProxyRootScope:
            raise TypeError("scope must be an exact ModelProxyRootScope")
        return await self._cancel(
            scope,
            lambda key: key.binding.cell.assignment.phase.root == scope,
            lambda: self._store.revoke_root(scope, reason="root_run_cancelled"),
        )

    async def cancel_phase(self, scope: ModelProxyPhaseScope) -> int:
        if type(scope) is not ModelProxyPhaseScope:
            raise TypeError("scope must be an exact ModelProxyPhaseScope")
        return await self._cancel(
            scope,
            lambda key: key.binding.cell.assignment.phase == scope,
            lambda: self._store.revoke_phase(scope, reason="phase_cancelled"),
        )

    async def cancel_assignment(self, scope: ModelProxyAssignmentScope) -> int:
        if type(scope) is not ModelProxyAssignmentScope:
            raise TypeError("scope must be an exact ModelProxyAssignmentScope")
        return await self._cancel(
            scope,
            lambda key: key.binding.cell.assignment == scope,
            lambda: self._store.revoke_assignment(scope, reason="assignment_cancelled"),
        )

    async def cancel_cell(self, scope: ModelProxyCellScope) -> int:
        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        return await self._cancel(
            scope,
            lambda key: key.binding.cell == scope,
            lambda: self._store.revoke_cell(scope, reason="cell_cancelled"),
        )

    async def _mint(
        self, key: _CacheKey, fingerprint: _StartupFingerprint
    ) -> IssuedModelProxyGrant:
        deadline = ModelProxyIssuanceDeadline.start(fingerprint.ttl_seconds)
        await self._reserve_cache_slot(key.binding.cell)
        try:
            if deadline.elapsed:
                raise _deadline_conflict()
            secret = secrets.token_urlsafe(32)
            draft = ModelProxyGrantDraft(
                grant_id=f"mpg_{secrets.token_urlsafe(18)}",
                binding=key.binding,
                bearer_digest=_digest(secret),
                startup_request_digest=model_proxy_startup_digest(key.binding, key.request_id),
                ttl_seconds=fingerprint.ttl_seconds,
                generation=fingerprint.generation,
            )
            returned = await self._store.insert_active(draft)
            try:
                stored = require_insert_projection(returned, draft)
            except ModelProxyGrantConflict as conflict:
                await self._reject_committed_insert(
                    key.binding.cell, "malformed_store_projection", conflict
                )
            if deadline.elapsed:
                await self._reject_committed_insert(
                    key.binding.cell, "issuance_deadline_elapsed", _deadline_conflict()
                )
            receipt = ModelProxyGrantReceipt(
                stored.grant_id,
                stored.binding,
                stored.issued_at,
                stored.expires_at,
                stored.generation,
            )
            cached = _CachedBearer(fingerprint, receipt, deadline, secret)
            async with self._cache_lock:
                late = deadline.elapsed
                if not late:
                    self._cache = {
                        old_key: value
                        for old_key, value in self._cache.items()
                        if old_key.binding.cell != key.binding.cell
                    }
                    self._cache[key] = cached
            if late:
                await self._reject_committed_insert(
                    key.binding.cell, "issuance_deadline_elapsed", _deadline_conflict()
                )
            try:
                deadline.schedule(self._expire_cached, key, stored.grant_id)
            except ModelProxyDeadlineElapsed:
                await self._drop_cached(key, stored.grant_id)
                await self._reject_committed_insert(
                    key.binding.cell, "issuance_deadline_elapsed", _deadline_conflict()
                )
            await self._require_still_active(key, cached)
            return _issued(cached)
        finally:
            await self._release_cache_slot(key.binding.cell)

    async def _require_still_active(self, key: _CacheKey, cached: _CachedBearer) -> None:
        if await self._is_stably_active(key, cached) and not cached.deadline.elapsed:
            return
        await self._drop_cached(key, cached.receipt.grant_id)
        if cached.deadline.elapsed:
            await self._reject_committed_insert(
                key.binding.cell, "issuance_deadline_elapsed", _deadline_conflict()
            )
        raise ModelProxyGrantConflict("model-proxy grant was revoked during issuance")

    async def _is_stably_active(self, key: _CacheKey, cached: _CachedBearer) -> bool:
        while True:
            observed = self._cancellations.sequence
            active = await self._lookup_active(key, cached)
            if not await self._cancellations.must_retry(observed, key.binding.cell):
                break
        return active

    async def _current_cached(
        self, key: _CacheKey, fingerprint: _StartupFingerprint
    ) -> _CachedBearer | None:
        async with self._cache_lock:
            cached = self._cache.get(key)
        if cached is None:
            return None
        if cached.fingerprint != fingerprint:
            raise ModelProxyGrantConflict("startup request was already used in this scope")
        if not cached.deadline.elapsed and await self._is_stably_active(key, cached):
            if cached.deadline.elapsed:
                await self._drop_cached(key, cached.receipt.grant_id)
                return None
            return cached
        await self._drop_cached(key, cached.receipt.grant_id)
        return None

    async def _reserve_cache_slot(self, cell: ModelProxyCellScope) -> None:
        while True:
            async with self._cache_lock:
                occupied = {key.binding.cell for key in self._cache} | self._reservations
                if cell in occupied or len(occupied) < self._max_cache:
                    self._reservations.add(cell)
                    return
                candidates = tuple(self._cache.items())
            removed = False
            for key, cached in candidates:
                if cached.deadline.elapsed or not await self._lookup_active(key, cached):
                    removed = await self._drop_cached(key, cached.receipt.grant_id) or removed
            if not removed:
                raise ModelProxyBearerCacheCapacityExceeded(
                    "model-proxy bearer cache capacity exceeded"
                )

    async def _release_cache_slot(self, cell: ModelProxyCellScope) -> None:
        async with self._cache_lock:
            self._reservations.discard(cell)

    async def _lookup_active(self, key: _CacheKey, cached: _CachedBearer) -> bool:
        value = await self._store.find_active_by_id(
            cached.receipt.grant_id,
            key.binding,
            generation=cached.fingerprint.generation,
        )
        try:
            return require_active_projection(
                value,
                receipt=cached.receipt,
                binding=key.binding,
                bearer_digest=_digest(cached.secret),
                startup_request_digest=model_proxy_startup_digest(key.binding, key.request_id),
            )
        except ModelProxyGrantConflict:
            await self._drop_cached(key, cached.receipt.grant_id)
            raise

    async def _reject_committed_insert(
        self, cell: ModelProxyCellScope, reason: str, conflict: ModelProxyGrantConflict
    ) -> NoReturn:
        try:
            await self._cancel(
                cell,
                lambda key: key.binding.cell == cell,
                lambda: self._store.revoke_cell(cell, reason=reason),
            )
        except BaseException:
            conflict.add_note("model-proxy committed-insert cleanup did not confirm")
        raise conflict from None

    async def _cancel(
        self,
        scope: ModelProxyCancellationScope,
        predicate: Callable[[_CacheKey], bool],
        revoke: Callable[[], Awaitable[int]],
    ) -> int:
        token = self._cancellations.begin(scope)
        task = asyncio.create_task(
            self._cancel_and_purge(scope, token, predicate, revoke),
            name="model-proxy-grant-cancel",
        )
        return await _cancellation_safe(task)

    async def _cancel_and_purge(
        self,
        scope: ModelProxyCancellationScope,
        token: CancelToken,
        predicate: Callable[[_CacheKey], bool],
        revoke: Callable[[], Awaitable[int]],
    ) -> int:
        try:
            count = await revoke()
            async with self._cache_lock:
                self._cache = {
                    key: value for key, value in self._cache.items() if not predicate(key)
                }
            if type(count) is not int or count < 0:
                raise TypeError("model-proxy store revoke count must be a non-negative integer")
            return count
        finally:
            self._cancellations.finish(scope, token)

    async def _drop_cached(self, key: _CacheKey, grant_id: str) -> bool:
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None and cached.receipt.grant_id == grant_id:
                self._cache.pop(key, None)
                return True
            return False

    def _expire_cached(self, key: _CacheKey, grant_id: str) -> None:
        cached = self._cache.get(key)
        if cached is not None and cached.receipt.grant_id == grant_id:
            self._cache.pop(key, None)

    def _stripe(self, cell: ModelProxyCellScope) -> asyncio.Lock:
        return self._stripes[hash(cell) % len(self._stripes)]

    def __repr__(self) -> str:
        return "PhaseScopedModelProxyGrantBroker(<redacted>)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("model-proxy grant brokers cannot be serialized")


async def _cancellation_safe(task: asyncio.Task[_T]) -> _T:
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise


def _issued(cached: _CachedBearer) -> IssuedModelProxyGrant:
    return IssuedModelProxyGrant(cached.receipt, ModelProxyBearer(cached.secret))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _deadline_conflict() -> ModelProxyGrantConflict:
    return ModelProxyGrantConflict("model-proxy issuance deadline elapsed")


__all__ = [
    "DEFAULT_MAX_EPHEMERAL_BEARERS",
    "DEFAULT_MODEL_PROXY_TTL_SECONDS",
    "HARD_MAX_EPHEMERAL_BEARERS",
    "ModelProxyBearerCacheCapacityExceeded",
    "PhaseScopedModelProxyGrantBroker",
]
