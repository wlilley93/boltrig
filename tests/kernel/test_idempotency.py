"""Idempotency replay: a repeated key returns the stored result, no re-execution
(NFR-REL-02 / SEC-15). A side-effecting verb must not fire twice on retry."""

import asyncio

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantSet,
    IdempotencyConflict,
    InvocationContext,
    PendingHuman,
    RateLimited,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


class CountingAdapter:
    """Counts execute() calls and returns the running count, so a re-execution is
    observable both as a higher count and a different result."""

    id = "counter"
    version = "1.0.0"
    runtime = "script"

    def __init__(
        self,
        *,
        consequence: str = "low",
        rate_limit: dict | None = None,
    ) -> None:
        self.calls = 0
        self.consequence = consequence
        self.rate_limit = rate_limit

    def describe(self):
        return [
            VerbSpec(
                verb_id="counter.do",
                noun_id="counter",
                input_schema={"type": "object"},
                output_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
                consequence=self.consequence,
                rate_limit=self.rate_limit,
            )
        ]

    async def execute(self, verb, params, credential, context):
        self.calls += 1
        return Result.success({"n": self.calls})

    async def health(self):
        return "ok"


def _ctx(*, actor: str = "t", on_behalf_of: str | None = None):
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["counter.*"]),
        actor=actor,
        on_behalf_of=on_behalf_of,
    )


async def _kernel(
    *,
    consequence: str = "low",
    rate_limit: dict | None = None,
):
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = CountingAdapter(consequence=consequence, rate_limit=rate_limit)
    await k.register_adapter(T, adapter)
    return k, adapter


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_repeated_key_replays_without_reexecuting():
    k, adapter = await _kernel()
    out1 = await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k1")
    out2 = await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k1")
    assert out1 == out2 == {"n": 1}
    assert adapter.calls == 1  # the second call was replayed, not re-executed


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_distinct_key_executes_again():
    k, adapter = await _kernel()
    await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k1")
    await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k2")
    assert adapter.calls == 2  # a different key is a different action


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_key_is_bound_to_canonical_request_and_authenticated_identity():
    k, adapter = await _kernel()
    first = await k.invoke(
        "counter", "counter.do", {"b": 2, "a": 1}, _ctx(), idempotency_key="bound"
    )
    replay = await k.invoke(
        "counter", "counter.do", {"a": 1, "b": 2}, _ctx(), idempotency_key="bound"
    )
    assert first == replay == {"n": 1}

    for params, context in [
        ({"a": 2, "b": 2}, _ctx()),
        ({"a": 1, "b": 2}, _ctx(actor="other")),
        ({"a": 1, "b": 2}, _ctx(on_behalf_of="alice")),
    ]:
        with pytest.raises(IdempotencyConflict):
            await k.invoke("counter", "counter.do", params, context, idempotency_key="bound")
    assert adapter.calls == 1


class BlockingAdapter(CountingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, verb, params, credential, context):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return Result.success({"n": self.calls})


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_concurrent_same_key_has_one_execution_owner():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = BlockingAdapter()
    await k.register_adapter(T, adapter)

    first = asyncio.create_task(
        k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="concurrent")
    )
    await adapter.started.wait()
    with pytest.raises(IdempotencyConflict):
        await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="concurrent")
    adapter.release.set()
    assert await first == {"n": 1}
    assert adapter.calls == 1


class SecretResultAdapter(CountingAdapter):
    async def execute(self, verb, params, credential, context):
        self.calls += 1
        return Result.success({"nested": {"accessToken": "sk-super-secret"}})


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_secret_shaped_success_is_completed_uncacheable_not_persisted():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = SecretResultAdapter()
    await k.register_adapter(T, adapter)

    output = await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="secret-result")
    assert output["nested"]["accessToken"] == "sk-super-secret"
    record = store._idem[(T, "secret-result")]
    assert record["status"] == "uncacheable" and record["result"] is None
    assert "sk-super-secret" not in repr(record)
    with pytest.raises(IdempotencyConflict):
        await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="secret-result")
    assert adapter.calls == 1


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_replay_precedes_spent_approval_gate():
    k, adapter = await _kernel(consequence="high")

    with pytest.raises(PendingHuman) as exc:
        await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-high")

    req_id = exc.value.hitl_request_id
    await k.hitl.answer(T, req_id, "approve", "human")
    out = await k.invoke(
        "counter",
        "counter.do",
        {},
        _ctx(),
        idempotency_key="k-high",
        approval_id=req_id,
    )

    retry = await k.invoke(
        "counter",
        "counter.do",
        {},
        _ctx(),
        idempotency_key="k-high",
        approval_id=req_id,
    )
    assert out == retry == {"n": 1}
    assert adapter.calls == 1


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_replay_precedes_rate_limit():
    k, adapter = await _kernel(rate_limit={"per": "minute", "max": 1, "scope": "tenant"})

    out = await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-rate")
    for _ in range(3):
        assert (
            await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-rate")
        ) == out

    with pytest.raises(RateLimited):
        await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-new")
    assert adapter.calls == 1


class ResettableCounter:
    """A rate-limit counter the test can rewind to simulate a new window."""

    def __init__(self) -> None:
        self.count = 0

    async def incr(self, key: str, window_seconds: int) -> int:
        self.count += 1
        return self.count


@pytest.mark.kernel
@pytest.mark.invariant("SEC-15")
async def test_rate_limited_key_is_released_and_retryable():
    # A key whose call died at the rate-limit gate is RELEASED, not parked
    # IN_PROGRESS: once the window passes, the same key retries cleanly instead
    # of conflicting on the orphaned claim. (The HITL-pending twin of this is
    # pinned by test_replay_precedes_spent_approval_gate above.)
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    counter = ResettableCounter()
    k = Kernel(store, counter=counter)
    adapter = CountingAdapter(rate_limit={"per": "minute", "max": 1, "scope": "tenant"})
    await k.register_adapter(T, adapter)

    await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-first")
    with pytest.raises(RateLimited):
        await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-tripped")

    counter.count = 0  # the rate window has passed
    out = await k.invoke("counter", "counter.do", {}, _ctx(), idempotency_key="k-tripped")
    assert out == {"n": 2}  # retried and executed, not IdempotencyConflict
    assert adapter.calls == 2
