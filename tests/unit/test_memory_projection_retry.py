"""fanout.retry_failed is READ (task #40): retry is behaviour, not a label.

Until 2026-07-31 this manifest key was advertised and read by nothing, so a
failed inline projection was never reattempted whatever it said - a knob for
behaviour that did not exist, the exact defect class of on_session_end (#30).
These tests pin the knob to a mechanism in both execution modes and record the
budget on the status row, so a reader can tell fast-fail from retry from the
row alone.
"""

from __future__ import annotations

import pytest

from boltrig.memory.engine import EngineFact
from boltrig.memory.projection_adapters import build_memory_projection_fanout
from boltrig.memory.projections import MemoryProjectionFanout, ProjectionResult
from boltrig.models import InvocationContext
from boltrig.store import InMemoryStore

pytestmark = pytest.mark.unit

TENANT = "acme"


class _FlakyProjection:
    """Fails the first ``failures`` calls, then succeeds - the retry shape."""

    id = "cognee"

    def __init__(self, *, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def remember(self, tenant_id, fact, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("backend down")
        return ProjectionResult.written(f"ref:{fact.id}")

    async def forget(self, tenant_id, *, fact_id, projection_ref, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("backend down")
        return ProjectionResult.deleted(projection_ref)


def _fact() -> EngineFact:
    return EngineFact(id="fact-1", owner_scope="user:alice", kind="entity", content="x")


def _context() -> InvocationContext:
    return InvocationContext(tenant_id=TENANT, actor="alice")


async def test_retry_failed_true_reattempts_a_failed_inline_projection_once() -> None:
    """THE knob's meaning: one bounded reattempt on the inline path."""
    projection = _FlakyProjection(failures=1)
    fanout = MemoryProjectionFanout(
        InMemoryStore(), [projection], retry_failed=True
    )
    rows = await fanout.remember(TENANT, _fact(), _context())
    assert projection.calls == 2, "the failed call was not reattempted"
    assert rows[0]["status"] == "written"


async def test_retry_failed_false_fails_fast_and_says_so_on_the_row() -> None:
    """False is fail-fast, and the row must let a reader SEE that fast-fail was
    chosen: max_operation_attempts=1 is the difference between "we tried twice
    and it is down" and "we chose not to retry"."""
    projection = _FlakyProjection(failures=1)
    store = InMemoryStore()
    fanout = MemoryProjectionFanout(store, [projection], retry_failed=False)
    rows = await fanout.remember(TENANT, _fact(), _context())
    assert projection.calls == 1, "retry_failed=false must not reattempt"
    assert rows[0]["status"] == "failed"
    statuses = await store.list_memory_projection_statuses(TENANT, limit=10)
    assert statuses[0].max_operation_attempts == 1
    assert statuses[0].operation_attempts == 1


async def test_the_inline_retry_is_bounded_not_a_loop() -> None:
    """Inline execution runs on the caller's request path: two attempts, never
    more, or a down backend becomes a hung verb."""
    projection = _FlakyProjection(failures=10)
    fanout = MemoryProjectionFanout(
        InMemoryStore(), [projection], retry_failed=True
    )
    rows = await fanout.remember(TENANT, _fact(), _context())
    assert projection.calls == 2
    assert rows[0]["status"] == "failed"


async def test_forget_honours_the_same_budget() -> None:
    projection = _FlakyProjection(failures=1)
    store = InMemoryStore()
    fanout = MemoryProjectionFanout(store, [projection], retry_failed=True)
    rows = await fanout.forget(TENANT, ["fact-1"], _context())
    assert projection.calls == 2
    assert rows[0]["status"] == "deleted"


def test_the_builder_reads_the_knob_for_the_queued_mode() -> None:
    """retry_failed=false collapses the queued budget to a single attempt - the
    same fact the inline path records, expressed in the queued path's own
    mechanism (max_operation_attempts)."""
    cfg = {
        "projections": [{"id": "cognee", "enabled": True}],
        "fanout": {"execution": "queued", "retry_failed": False},
    }
    fanout = build_memory_projection_fanout(InMemoryStore(), cfg)
    assert fanout is not None
    assert fanout.projection_delivery_posture()["max_operation_attempts"] == 1


def test_the_builder_defaults_to_retry_in_both_modes() -> None:
    """Absent means TRUE: the field's name promises retry and the shipped
    example says true, so absence keeps the promise."""
    queued = build_memory_projection_fanout(
        InMemoryStore(),
        {"projections": [{"id": "cognee", "enabled": True}], "fanout": {"execution": "queued"}},
    )
    assert queued.projection_delivery_posture()["max_operation_attempts"] == 3
    inline = build_memory_projection_fanout(
        InMemoryStore(),
        {"projections": [{"id": "cognee", "enabled": True}], "fanout": {}},
    )
    assert inline is not None and inline._retry_failed is True
