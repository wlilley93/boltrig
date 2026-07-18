from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import pickle
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from boltrig.fleet.application import model_proxy_grants as broker_module
from boltrig.fleet.application import model_proxy_deadline as deadline_module
from boltrig.fleet.application.model_proxy_grants import (
    ModelProxyBearerCacheCapacityExceeded,
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.domain.model_proxy_grant import (
    ActiveModelProxyGenerationConflict,
    IssuedModelProxyGrant,
    ModelProxyBearer,
    ModelProxyClockRollback,
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    ModelProxyGrantStatus,
    StaleModelProxyGeneration,
    StoredModelProxyGrant,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyBudgetBinding,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyModelBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    TrustedModelProxyRequestObservation,
)
from boltrig.fleet.infrastructure import memory_model_proxy_grants as memory_module
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
    MemoryModelProxyGrantStore,
    ModelProxyGrantStoreCapacityExceeded,
)
from boltrig.fleet.ports.model_proxy_grants import ModelProxyGrantStore

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
POLICY_DIGEST = "sha256:" + "a" * 64
CGROUP_DIGEST = "sha256:" + "c" * 64


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _binding(
    *,
    tenant: str = "tenant-1",
    workspace: str = "workspace-1",
    root: str = "root-1",
    phase: str = "phase-1",
    assignment: str = "assignment-1",
    cell: str = "cell-1",
    pid: int = 4321,
    pid_start_ticks: int = 998_001,
    boot_id: str = "018f4d4c-1111-7222-8333-123456789abc",
    pid_namespace_inode: int = 40_200,
    cgroup_digest: str = CGROUP_DIGEST,
    model: str = "gpt-5.2-codex",
    model_digest: str = POLICY_DIGEST,
    budget: str = "budget-1",
    max_input_tokens: int = 6_000,
    max_output_tokens: int = 4_000,
    max_total_tokens: int = 8_192,
    max_cost_micros: int = 125_000,
    budget_digest: str = POLICY_DIGEST,
) -> ModelProxyGrantBinding:
    root_scope = ModelProxyRootScope(tenant, workspace, root)
    phase_scope = ModelProxyPhaseScope(root_scope, phase)
    assignment_scope = ModelProxyAssignmentScope(phase_scope, assignment)
    cell_scope = ModelProxyCellScope(
        assignment_scope,
        cell,
        pid,
        pid_start_ticks,
        boot_id,
        pid_namespace_inode,
        cgroup_digest,
    )
    return ModelProxyGrantBinding(
        cell_scope,
        ModelProxyModelBinding(model, model_digest),
        ModelProxyBudgetBinding(
            budget,
            max_input_tokens,
            max_output_tokens,
            max_total_tokens,
            max_cost_micros,
            budget_digest,
        ),
    )


def _observation(binding: ModelProxyGrantBinding) -> TrustedModelProxyRequestObservation:
    return TrustedModelProxyRequestObservation(binding.cell, binding.model, binding.budget)


def _draft(
    name: str,
    *,
    binding: ModelProxyGrantBinding | None = None,
    generation: int = 1,
    ttl_seconds: int = 60,
) -> ModelProxyGrantDraft:
    return ModelProxyGrantDraft(
        grant_id=f"mpg_{name}",
        binding=binding or _binding(),
        bearer_digest=hashlib.sha256(f"bearer-{name}".encode()).hexdigest(),
        startup_request_digest=hashlib.sha256(f"request-{name}".encode()).hexdigest(),
        ttl_seconds=ttl_seconds,
        generation=generation,
    )


def _broker(
    *,
    store: MemoryModelProxyGrantStore | None = None,
    clock: _Clock | None = None,
    max_cached_bearers: int = 16,
) -> tuple[PhaseScopedModelProxyGrantBroker, MemoryModelProxyGrantStore, _Clock]:
    actual_clock = clock or _Clock()
    actual_store = store or MemoryModelProxyGrantStore(clock=actual_clock)
    broker = PhaseScopedModelProxyGrantBroker(
        actual_store,
        max_ttl_seconds=120,
        max_cached_bearers=max_cached_bearers,
    )
    protocol: ModelProxyGrantStore = actual_store
    assert protocol is actual_store
    return broker, actual_store, actual_clock


async def _issue(
    broker: PhaseScopedModelProxyGrantBroker,
    request: str = "startup-1",
    *,
    binding: ModelProxyGrantBinding | None = None,
    generation: int = 1,
    ttl_seconds: int = 60,
) -> IssuedModelProxyGrant:
    return await broker.issue(
        request,
        binding or _binding(),
        ttl_seconds=ttl_seconds,
        generation=generation,
    )


async def _internal_auth(
    store: MemoryModelProxyGrantStore,
    issued: IssuedModelProxyGrant,
    binding: ModelProxyGrantBinding,
    *,
    generation: int = 1,
) -> StoredModelProxyGrant | None:
    digest = hashlib.sha256(issued.bearer.reveal().encode("ascii")).hexdigest()
    return await store.find_active_for_trusted_observation(
        digest,
        _observation(binding),
        generation=generation,
    )


async def test_issue_is_digest_only_redacted_nonserializable_and_wrapper_isolated() -> None:
    broker, store, _clock = _broker()
    first = await _issue(broker)
    second = await _issue(broker)
    secret = first.bearer.reveal()
    record = store.snapshot()[0]
    persisted = json.dumps(asdict(record), default=str, sort_keys=True)

    assert len(base64.urlsafe_b64decode(secret + "=")) == 32
    assert secret == second.bearer.reveal()
    assert first is not second and first.bearer is not second.bearer
    with pytest.raises(AttributeError, match="immutable"):
        first.bearer._value = "A" * 43  # type: ignore[misc]
    assert (await _issue(broker)).bearer.reveal() == secret
    assert secret not in persisted + repr(record) + repr(first) + repr(broker)
    assert record.bearer_digest not in repr(record)
    assert not hasattr(record, "permitted_verbs")
    assert not hasattr(broker, "authenticate")
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(first)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(broker)


@pytest.mark.parametrize(
    "foreign",
    [
        _binding(tenant="tenant-2"),
        _binding(workspace="workspace-2"),
        _binding(root="root-2"),
        _binding(phase="phase-2"),
        _binding(assignment="assignment-2"),
        _binding(cell="cell-2"),
        _binding(pid=4322),
        _binding(pid_start_ticks=998_002),
        _binding(boot_id="018f4d4c-1111-7222-8333-123456789abd"),
        _binding(pid_namespace_inode=40_201),
        _binding(cgroup_digest="sha256:" + "d" * 64),
        _binding(model="gpt-5.3-codex"),
        _binding(model_digest="sha256:" + "b" * 64),
        _binding(budget="budget-2"),
        _binding(max_input_tokens=5_999),
        _binding(max_output_tokens=3_999),
        _binding(max_total_tokens=8_191),
        _binding(max_cost_micros=124_999),
        _binding(budget_digest="sha256:" + "b" * 64),
    ],
)
async def test_internal_lookup_requires_every_trusted_peer_model_and_budget_field(
    foreign: ModelProxyGrantBinding,
) -> None:
    broker, store, _clock = _broker()
    issued = await _issue(broker)

    assert await _internal_auth(store, issued, foreign) is None
    assert await _internal_auth(store, issued, _binding(), generation=2) is None
    assert await _internal_auth(store, issued, _binding()) is not None


async def test_stolen_bearer_cannot_cross_pid_reuse_boot_or_namespace_observation() -> None:
    broker, store, _clock = _broker()
    issued = await _issue(broker)
    for foreign in (
        _binding(pid=9999, pid_start_ticks=998_001),
        _binding(pid=4321, pid_start_ticks=998_002),
        _binding(boot_id="018f4d4c-1111-7222-8333-123456789abd"),
        _binding(pid_namespace_inode=99_999),
    ):
        assert await _internal_auth(store, issued, foreign) is None


def test_scope_and_bearer_values_reject_subclasses_unicode_and_invalid_process_ids() -> None:
    class RootSubclass(ModelProxyRootScope):
        pass

    class StringSubclass(str):
        pass

    with pytest.raises(TypeError, match="exact ModelProxyRootScope"):
        ModelProxyPhaseScope(RootSubclass("tenant-1", "workspace-1", "root-1"), "phase-1")
    with pytest.raises(TypeError, match="exact string"):
        ModelProxyRootScope(StringSubclass("tenant-1"), "workspace-1", "root-1")
    for unsafe in ("tenant space", "tenant\nforged", "tenant\u200bforged", "ｔenant"):
        with pytest.raises(ValueError, match="safe ASCII"):
            ModelProxyRootScope(unsafe, "workspace-1", "root-1")
    for invalid in (True, 0, 2**63):
        with pytest.raises((TypeError, ValueError)):
            replace(_binding().cell, pid=invalid)
    with pytest.raises(ValueError, match="256 random bits"):
        ModelProxyBearer("_" * 43)


@pytest.mark.parametrize("prefix", ["-leading", "_leading"])
async def test_generated_grant_id_is_valid_for_every_token_urlsafe_prefix(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    secret = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    values = iter((secret, prefix))
    monkeypatch.setattr(broker_module.secrets, "token_urlsafe", lambda _size: next(values))
    issued = await _issue(_broker()[0])
    assert issued.receipt.grant_id == f"mpg_{prefix}"


async def test_duplicate_startup_is_process_local_and_scope_namespaced() -> None:
    broker, store, _clock = _broker()
    first, second = await asyncio.gather(_issue(broker), _issue(broker))
    assert first.bearer.reveal() == second.bearer.reveal()
    with pytest.raises(ModelProxyGrantConflict, match="already used"):
        await _issue(broker, ttl_seconds=59)

    tenant_two = await _issue(broker, binding=_binding(tenant="tenant-2"))
    assert tenant_two.bearer.reveal() != first.bearer.reveal()
    restarted = PhaseScopedModelProxyGrantBroker(store, max_ttl_seconds=120)
    with pytest.raises(ModelProxyGrantConflict):
        await _issue(restarted)


async def test_generation_supersession_revokes_old_bearer_and_retry_cache() -> None:
    broker, store, _clock = _broker()
    first = await _issue(broker, "startup-1")
    second = await _issue(broker, "startup-2", generation=2)
    assert await _internal_auth(store, first, _binding(), generation=1) is None
    assert await _internal_auth(store, second, _binding(), generation=2) is not None
    original = await store.get_by_id(first.receipt.grant_id, _binding())
    assert original is not None
    assert (original.status, original.revocation_reason) == (
        ModelProxyGrantStatus.REVOKED,
        "superseded_generation",
    )
    with pytest.raises(ModelProxyGrantConflict):
        await _issue(broker, "startup-1")


async def test_clock_rollback_terminally_revokes_and_never_reactivates() -> None:
    broker, store, clock = _broker()
    issued = await _issue(broker)
    clock.value = NOW + timedelta(seconds=50)
    assert await _internal_auth(store, issued, _binding()) is not None
    clock.value = NOW + timedelta(seconds=10)
    assert await _internal_auth(store, issued, _binding()) is None
    clock.value = NOW + timedelta(seconds=60)
    assert await _internal_auth(store, issued, _binding()) is None
    stored = await store.get_by_id(issued.receipt.grant_id, _binding())
    assert stored is not None
    assert (stored.status, stored.revocation_reason) == (
        ModelProxyGrantStatus.REVOKED,
        "clock_rollback",
    )
    with pytest.raises(ModelProxyClockRollback):
        await _issue(broker, "after-rollback", generation=2)


class _DelayedLookupStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def find_active_for_trusted_observation(
        self,
        bearer_digest: str,
        observation: TrustedModelProxyRequestObservation,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        self.entered.set()
        await self.release.wait()
        return await super().find_active_for_trusted_observation(
            bearer_digest, observation, generation=generation
        )


async def test_authoritative_store_time_rejects_lookup_delayed_across_expiry() -> None:
    clock = _Clock()
    store = _DelayedLookupStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issued = await _issue(broker, ttl_seconds=1)
    task = asyncio.create_task(_internal_auth(store, issued, _binding()))
    await store.entered.wait()
    clock.value = NOW + timedelta(seconds=1)
    store.release.set()
    assert await task is None


async def test_expiry_retains_generation_and_idle_timer_drops_raw_cache() -> None:
    broker, store, clock = _broker()
    issued = await _issue(broker, ttl_seconds=1)
    clock.value = NOW + timedelta(seconds=1)
    assert await _internal_auth(store, issued, _binding()) is None
    with pytest.raises(StaleModelProxyGeneration):
        await store.insert_active(_draft("expiry-replay"))
    await asyncio.sleep(1.05)
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]


@pytest.mark.parametrize("ttl", [121, 1_000])
def test_draft_rejects_grants_longer_than_two_minutes(ttl: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 120"):
        _draft("too-long", ttl_seconds=ttl)


@pytest.mark.parametrize("level", ["root", "phase", "assignment", "cell"])
async def test_hierarchical_cancellation_is_immediate_scoped_and_terminal(level: str) -> None:
    broker, store, _clock = _broker()
    target_binding = _binding()
    foreign_binding = {
        "root": _binding(root="root-2"),
        "phase": _binding(phase="phase-2"),
        "assignment": _binding(assignment="assignment-2"),
        "cell": _binding(cell="cell-2", pid=4330),
    }[level]
    target = await _issue(broker, "target", binding=target_binding)
    foreign = await _issue(broker, "foreign", binding=foreign_binding)
    scope = {
        "root": target_binding.cell.assignment.phase.root,
        "phase": target_binding.cell.assignment.phase,
        "assignment": target_binding.cell.assignment,
        "cell": target_binding.cell,
    }[level]
    assert await getattr(broker, f"cancel_{level}")(scope) == 1
    assert await _internal_auth(store, target, target_binding) is None
    assert await _internal_auth(store, foreign, foreign_binding) is not None
    with pytest.raises(StaleModelProxyGeneration):
        await _issue(broker, "target-next", binding=target_binding, generation=2)


async def test_cancel_vs_higher_generation_issue_race_fails_closed() -> None:
    clock = _Clock()
    store = MemoryModelProxyGrantStore(clock=clock)
    original = await store.insert_active(_draft("original"))

    async def attempt() -> Exception | None:
        try:
            await store.insert_active(_draft("replacement", generation=2))
        except Exception as exc:
            return exc
        return None

    inserted, revoked = await asyncio.gather(
        attempt(), store.revoke_cell(original.binding.cell, reason="cell_cancelled")
    )
    assert inserted is None or isinstance(inserted, StaleModelProxyGeneration)
    assert revoked == 1
    assert await store.find_active_by_id("mpg_replacement", _binding(), generation=2) is None


class _DelayedInsertStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        self.entered.set()
        await self.release.wait()
        return await super().insert_active(draft)


class _PostInsertDelayedStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.inserted = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        stored = await super().insert_active(draft)
        self.inserted.set()
        await self.release.wait()
        return stored


class _Monotonic:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _fake_deadline_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Monotonic, list[tuple[float, Callable[..., None], tuple[object, ...]]]]:
    monotonic = _Monotonic()
    scheduled: list[tuple[float, Callable[..., None], tuple[object, ...]]] = []

    def schedule(delay: float, callback: Callable[..., None], *args: object) -> None:
        scheduled.append((delay, callback, args))

    monkeypatch.setattr(deadline_module, "_event_loop_time", monotonic)
    monkeypatch.setattr(deadline_module, "_schedule_after", schedule)
    return monotonic, scheduled


async def test_delayed_insert_at_deadline_is_fenced_without_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic, scheduled = _fake_deadline_runtime(monkeypatch)
    clock = _Clock()
    store = _PostInsertDelayedStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issuance = asyncio.create_task(_issue(broker, ttl_seconds=1))
    await store.inserted.wait()
    monotonic.value = 101.0
    store.release.set()
    with pytest.raises(ModelProxyGrantConflict, match="issuance deadline elapsed"):
        await issuance
    assert not scheduled
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]
    assert store.snapshot()[0].status is ModelProxyGrantStatus.REVOKED
    assert store.snapshot()[0].revocation_reason == "issuance_deadline_elapsed"


async def test_cache_expiry_uses_only_remaining_monotonic_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic, scheduled = _fake_deadline_runtime(monkeypatch)
    clock = _Clock()
    store = _PostInsertDelayedStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issuance = asyncio.create_task(_issue(broker, ttl_seconds=1))
    await store.inserted.wait()
    monotonic.value = 100.25
    store.release.set()
    assert await issuance
    assert len(scheduled) == 1
    delay, callback, args = scheduled[0]
    assert delay == pytest.approx(0.75)
    assert cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]
    monotonic.value = 101.0
    callback(*args)
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]


async def test_cancelled_late_insert_finishes_fence_without_secret_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic, scheduled = _fake_deadline_runtime(monkeypatch)
    clock = _Clock()
    store = _PostInsertDelayedStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issuance = asyncio.create_task(_issue(broker, ttl_seconds=1))
    await store.inserted.wait()
    issuance.cancel()
    monotonic.value = 101.0
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await issuance
    assert not scheduled
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]
    assert store.snapshot()[0].status is ModelProxyGrantStatus.REVOKED
    assert store.snapshot()[0].revocation_reason == "issuance_deadline_elapsed"


class _BlockingInsertStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return await super().insert_active(draft)


class _CancelDuringLookupStore(_PostInsertDelayedStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock)
        self.allow_cancel = asyncio.Event()
        self.cancel_entered = asyncio.Event()
        self.lookup_count = 0

    async def revoke_cell(self, scope: ModelProxyCellScope, *, reason: str) -> int:
        self.cancel_entered.set()
        await self.allow_cancel.wait()
        return await super().revoke_cell(scope, reason=reason)

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        captured = await super().find_active_by_id(grant_id, binding, generation=generation)
        self.lookup_count += 1
        if self.lookup_count > 100:
            raise RuntimeError("issuance busy-spun while cancellation needed the event loop")
        asyncio.get_running_loop().call_soon(self.allow_cancel.set)
        return captured


class _DelayedActiveLookupStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.armed = False
        self.captured = asyncio.Event()
        self.release = asyncio.Event()

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        captured = await super().find_active_by_id(grant_id, binding, generation=generation)
        if self.armed:
            self.armed = False
            self.captured.set()
            await self.release.wait()
        return captured


class _DelayedRootCancelStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__(clock=clock)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def revoke_root(self, scope: ModelProxyRootScope, *, reason: str) -> int:
        self.entered.set()
        await self.release.wait()
        return await super().revoke_root(scope, reason=reason)


class _StoredSubclass(StoredModelProxyGrant):
    pass


def _as_subclass(record: StoredModelProxyGrant) -> StoredModelProxyGrant:
    return _StoredSubclass(
        grant_id=record.grant_id,
        binding=record.binding,
        bearer_digest=record.bearer_digest,
        startup_request_digest=record.startup_request_digest,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
        generation=record.generation,
        status=record.status,
        revoked_at=record.revoked_at,
        revocation_reason=record.revocation_reason,
    )


def _with_bool_generation(record: StoredModelProxyGrant) -> StoredModelProxyGrant:
    drifted = replace(record)
    object.__setattr__(drifted, "generation", True)
    return drifted


ProjectionDrift = Callable[[StoredModelProxyGrant], object]
PROJECTION_DRIFTS: tuple[tuple[str, ProjectionDrift], ...] = (
    ("grant_id", lambda record: replace(record, grant_id="mpg_drifted")),
    ("binding", lambda record: replace(record, binding=_binding(cell="cell-drift", pid=7777))),
    ("bearer_digest", lambda record: replace(record, bearer_digest="d" * 64)),
    ("startup_digest", lambda record: replace(record, startup_request_digest="e" * 64)),
    ("generation", lambda record: replace(record, generation=record.generation + 1)),
    (
        "issued_at",
        lambda record: replace(record, issued_at=record.issued_at + timedelta(seconds=1)),
    ),
    (
        "expires_at",
        lambda record: replace(record, expires_at=record.expires_at - timedelta(seconds=1)),
    ),
    ("status", lambda record: record.expire()),
    ("subclass", _as_subclass),
    ("bool_field", _with_bool_generation),
    ("bool_response", lambda _record: True),
)


class _MalformedInsertStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock, drift: ProjectionDrift) -> None:
        super().__init__(clock=clock)
        self.drift = drift

    async def insert_active(self, draft: ModelProxyGrantDraft) -> StoredModelProxyGrant:
        stored = await super().insert_active(draft)
        return cast(StoredModelProxyGrant, self.drift(stored))


class _MalformedLookupStore(MemoryModelProxyGrantStore):
    def __init__(self, clock: _Clock, drift: ProjectionDrift) -> None:
        super().__init__(clock=clock)
        self.drift = drift

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
    ) -> StoredModelProxyGrant | None:
        stored = await super().find_active_by_id(grant_id, binding, generation=generation)
        return stored if stored is None else cast(StoredModelProxyGrant, self.drift(stored))


@pytest.mark.parametrize(
    ("_name", "drift"), PROJECTION_DRIFTS, ids=[x[0] for x in PROJECTION_DRIFTS]
)
async def test_malformed_insert_projection_never_returns_or_caches_bearer(
    _name: str, drift: ProjectionDrift
) -> None:
    clock = _Clock()
    store = _MalformedInsertStore(clock, drift)
    broker, _store, _clock = _broker(store=store, clock=clock)
    with pytest.raises(ModelProxyGrantConflict, match="malformed projection"):
        await _issue(broker)
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]
    assert store.snapshot()[0].status is ModelProxyGrantStatus.REVOKED
    assert store.snapshot()[0].revocation_reason == "malformed_store_projection"


@pytest.mark.parametrize(
    ("_name", "drift"), PROJECTION_DRIFTS, ids=[x[0] for x in PROJECTION_DRIFTS]
)
async def test_malformed_active_lookup_never_returns_and_purges_cached_bearer(
    _name: str, drift: ProjectionDrift
) -> None:
    clock = _Clock()
    store = _MalformedLookupStore(clock, drift)
    broker, _store, _clock = _broker(store=store, clock=clock)
    with pytest.raises(ModelProxyGrantConflict, match="malformed projection"):
        await _issue(broker)
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]


async def test_cancel_committed_during_cache_insert_cannot_leave_or_return_secret() -> None:
    clock = _Clock()
    store = _PostInsertDelayedStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issuance = asyncio.create_task(_issue(broker))
    await store.inserted.wait()
    assert await broker.cancel_cell(_binding().cell) == 1
    store.release.set()
    with pytest.raises(ModelProxyGrantConflict, match="revoked during issuance"):
        await issuance
    assert not cast(dict[object, object], broker._cache)  # type: ignore[attr-defined]


async def test_concurrent_cells_cannot_oversubscribe_bearer_capacity() -> None:
    clock = _Clock()
    store = _BlockingInsertStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock, max_cached_bearers=1)
    first_binding = _binding(cell="cell-a")
    second_binding = next(
        candidate
        for index in range(256)
        if broker._stripe(  # type: ignore[attr-defined]
            (candidate := _binding(cell=f"cell-b-{index}")).cell
        )
        is not broker._stripe(first_binding.cell)  # type: ignore[attr-defined]
    )
    first = asyncio.create_task(_issue(broker, "first", binding=first_binding))
    await store.entered.wait()
    second = asyncio.create_task(_issue(broker, "second", binding=second_binding))
    done, _pending = await asyncio.wait({second}, timeout=0.2)
    try:
        assert second in done
        with pytest.raises(ModelProxyBearerCacheCapacityExceeded):
            await second
        assert store.calls == 1
    finally:
        store.release.set()
        await first
        if not second.done():
            await second


async def test_cancel_completion_during_stale_active_lookup_is_observed() -> None:
    clock = _Clock()
    store = _CancelDuringLookupStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    issuance = asyncio.create_task(_issue(broker))
    await store.inserted.wait()
    cancellation = asyncio.create_task(broker.cancel_cell(_binding().cell))
    await store.cancel_entered.wait()
    store.release.set()
    assert await cancellation == 1
    with pytest.raises(ModelProxyGrantConflict, match="revoked during issuance"):
        await issuance
    assert store.lookup_count < 100


async def test_cached_retry_rechecks_cancel_completion_after_stale_lookup() -> None:
    clock = _Clock()
    store = _DelayedActiveLookupStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    await _issue(broker)
    store.armed = True
    retry = asyncio.create_task(_issue(broker))
    await store.captured.wait()
    assert await broker.cancel_cell(_binding().cell) == 1
    store.release.set()
    with pytest.raises(StaleModelProxyGeneration):
        await retry


async def test_stalled_unrelated_root_cancel_does_not_block_issuance() -> None:
    clock = _Clock()
    store = _DelayedRootCancelStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    root_one = _binding(root="root-1").cell.assignment.phase.root
    cancellation = asyncio.create_task(broker.cancel_root(root_one))
    await store.entered.wait()
    issuance = asyncio.create_task(_issue(broker, binding=_binding(root="root-2")))
    done, _pending = await asyncio.wait({issuance}, timeout=0.2)
    try:
        assert issuance in done
        assert await issuance
    finally:
        store.release.set()
        assert await cancellation == 0
        if not issuance.done():
            await issuance


async def test_double_cancellation_finishes_issue_and_preserves_idempotent_secret() -> None:
    clock = _Clock()
    store = _DelayedInsertStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    task = asyncio.create_task(_issue(broker))
    await store.entered.wait()
    task.cancel()
    task.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(store.snapshot()) == 1
    assert (await _issue(broker)).receipt.grant_id == store.snapshot()[0].grant_id


async def test_unrelated_cancellation_is_not_blocked_by_stalled_issuance() -> None:
    clock = _Clock()
    store = _DelayedInsertStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock)
    stalled = asyncio.create_task(_issue(broker, binding=_binding(root="root-1")))
    await store.entered.wait()
    cancelled = await asyncio.wait_for(
        broker.cancel_root(_binding(root="root-2").cell.assignment.phase.root), timeout=0.2
    )
    assert cancelled == 0
    store.release.set()
    assert await stalled


async def test_capacity_reconciles_external_revocation_without_secret_eviction() -> None:
    broker, store, _clock = _broker(max_cached_bearers=1)
    first = await _issue(broker)
    with pytest.raises(ModelProxyBearerCacheCapacityExceeded):
        await _issue(broker, "foreign", binding=_binding(root="root-2"))
    assert await store.revoke_cell(_binding().cell, reason="external_cancel") == 1
    second = await _issue(broker, "foreign", binding=_binding(root="root-2"))
    assert second.bearer.reveal() != first.bearer.reveal()

    bounded = MemoryModelProxyGrantStore(max_records=1, max_fences=1, clock=_Clock())
    original = await bounded.insert_active(_draft("capacity"))
    with pytest.raises(ModelProxyGrantStoreCapacityExceeded):
        await bounded.insert_active(_draft("capacity-next", generation=2))
    assert await bounded.get_by_id(original.grant_id, original.binding) == original


async def test_constant_time_internal_digest_lookup_scans_every_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryModelProxyGrantStore(clock=_Clock())
    first = await store.insert_active(_draft("scan-first"))
    await store.insert_active(_draft("scan-second", binding=_binding(cell="cell-2")))
    real_compare = memory_module.hmac.compare_digest
    comparisons: list[tuple[str, str]] = []

    def tracked(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(memory_module.hmac, "compare_digest", tracked)
    assert (
        await store.find_active_for_trusted_observation(
            first.bearer_digest, _observation(first.binding), generation=1
        )
        == first
    )
    assert len(comparisons) == len(store.snapshot())


async def test_same_generation_has_one_winner_and_collisions_are_redacted() -> None:
    store = MemoryModelProxyGrantStore(clock=_Clock())

    async def attempt(draft: ModelProxyGrantDraft) -> Exception | None:
        try:
            await store.insert_active(draft)
        except Exception as exc:
            return exc
        return None

    outcomes = await asyncio.gather(attempt(_draft("race-a")), attempt(_draft("race-b")))
    assert sum(item is None for item in outcomes) == 1
    assert sum(isinstance(item, ActiveModelProxyGenerationConflict) for item in outcomes) == 1
    original = store.snapshot()[0]
    collision = replace(
        _draft("collision", binding=_binding(cell="cell-3")),
        bearer_digest=original.bearer_digest,
    )
    with pytest.raises(ModelProxyGrantConflict) as caught:
        await store.insert_active(collision)
    assert collision.grant_id not in str(caught.value)
    assert collision.bearer_digest not in str(caught.value)


async def test_store_rejects_pre_timestamped_future_record_instead_of_delayed_activation() -> None:
    store = MemoryModelProxyGrantStore(clock=_Clock())
    future = StoredModelProxyGrant(
        grant_id="mpg_future",
        binding=_binding(),
        bearer_digest="a" * 64,
        startup_request_digest="b" * 64,
        issued_at=NOW + timedelta(seconds=30),
        expires_at=NOW + timedelta(seconds=60),
        generation=1,
    )
    with pytest.raises(TypeError, match="exact ModelProxyGrantDraft"):
        await store.insert_active(future)  # type: ignore[arg-type]
