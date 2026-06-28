"""Idempotency replay: a repeated key returns the stored result, no re-execution
(NFR-REL-02 / SEC-15). A side-effecting verb must not fire twice on retry."""

import pytest

from nankle.adapters.base import Result, VerbSpec
from nankle.kernel import Kernel
from nankle.models import GrantSet, InvocationContext, TenantPermissions
from nankle.store import InMemoryStore

T = "acme"


class CountingAdapter:
    """Counts execute() calls and returns the running count, so a re-execution is
    observable both as a higher count and a different result."""

    id = "counter"
    version = "1.0.0"
    runtime = "script"

    def __init__(self) -> None:
        self.calls = 0

    def describe(self):
        return [
            VerbSpec(
                verb_id="counter.do",
                noun_id="counter",
                input_schema={"type": "object"},
                output_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
                consequence="low",
            )
        ]

    async def execute(self, verb, params, credential, context):
        self.calls += 1
        return Result.success({"n": self.calls})

    async def health(self):
        return "ok"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["counter.*"]), actor="t")


async def _kernel():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    adapter = CountingAdapter()
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
