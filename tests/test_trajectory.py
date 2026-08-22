"""The trajectory: verbatim turn records, opt-in, expiring (Decision TRJ-01).

The point of these tests is the DIFFERENCE from the audit log. Audit is bounded
and scrubbed by design -- a digest and a 256-character preview -- which cannot
answer "why did it say that". The trajectory answers it, and everything below
either proves it carries the call as made, or proves the safeguards that let it
do so without becoming a liability.
"""

import json
from datetime import timedelta

import pytest

from boltrig.kernel.trajectory import (
    MAX_PAYLOAD_CHARS,
    NullTrajectoryRecorder,
    TrajectoryRecorder,
    bound_payload,
)
from boltrig.models import InvocationContext, TrajectoryEvent, TrajectoryKind, utcnow
from boltrig.store.trajectory import InMemoryTrajectoryStore

TENANT = "t-traj"


def _ctx(run_id: str = "run-1", **kw) -> InvocationContext:
    return InvocationContext(tenant_id=TENANT, run_id=run_id, actor="agent-1", **kw)


class TestBounds:
    """What the recorder refuses to write, and why each refusal costs information."""

    def test_secret_looking_keys_are_redacted(self):
        out = bound_payload({"api_key": "sk-live-abc", "Authorization": "Bearer x", "title": "ok"})
        assert out["api_key"] == "[redacted]"
        assert out["Authorization"] == "[redacted]"
        assert out["title"] == "ok", "redaction must not eat ordinary fields"

    def test_nested_secrets_are_redacted(self):
        out = bound_payload({"outer": {"password": "hunter2"}})
        assert out["outer"]["password"] == "[redacted]"

    def test_long_values_are_truncated_with_a_marker_not_dropped(self):
        """Silently discarding the big result is worse than saying it was big."""
        out = bound_payload({"body": "x" * (MAX_PAYLOAD_CHARS + 500)})["body"]
        assert len(out) < MAX_PAYLOAD_CHARS + 100
        assert "truncated 500 chars" in out

    def test_deep_nesting_terminates(self):
        deep = current = {}
        for _ in range(40):
            current["next"] = {}
            current = current["next"]
        assert "[too deeply nested]" in json.dumps(bound_payload(deep))

    def test_unserialisable_values_do_not_raise(self):
        assert isinstance(bound_payload({"obj": object()})["obj"], str)


@pytest.mark.asyncio
class TestRecorder:
    async def test_a_disabled_recorder_writes_nothing(self):
        """OFF BY DEFAULT, because the stream is verbatim. The recorder is a
        live object rather than None so no call site carries a check."""
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store, enabled=False)
        await recorder.record(_ctx(), TrajectoryKind.PROMPT, {"text": "hello"})
        assert await store.read_trajectory(TENANT, "run-1") == []
        assert NullTrajectoryRecorder().enabled is False

    async def test_a_run_without_an_id_is_not_filed_under_a_placeholder(self):
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store, enabled=True)
        await recorder.record(
            InvocationContext(tenant_id=TENANT, run_id=None), TrajectoryKind.PROMPT, {"t": 1}
        )
        assert await store.list_trajectory_runs(TENANT) == []

    async def test_a_store_failure_never_reaches_the_caller(self):
        """A trajectory that could break a turn is worse than no trajectory."""

        class Exploding:
            async def append_trajectory(self, *a, **kw):
                raise RuntimeError("disk on fire")

        recorder = TrajectoryRecorder(Exploding(), enabled=True)
        await recorder.record(_ctx(), TrajectoryKind.PROMPT, {"text": "hello"})


@pytest.mark.asyncio
class TestStore:
    async def test_sequence_is_assigned_by_the_store_and_is_monotonic(self):
        store = InMemoryTrajectoryStore()
        for i in range(5):
            await store.append_trajectory(TENANT, "run-1", TrajectoryKind.MESSAGE, {"i": i})
        rows = await store.read_trajectory(TENANT, "run-1")
        assert [r.seq for r in rows] == [1, 2, 3, 4, 5]

    async def test_reads_are_tenant_scoped(self):
        store = InMemoryTrajectoryStore()
        await store.append_trajectory(TENANT, "run-1", TrajectoryKind.PROMPT, {"secret": "mine"})
        assert await store.read_trajectory("someone-else", "run-1") == []

    async def test_after_seq_supports_resuming_a_read(self):
        store = InMemoryTrajectoryStore()
        for i in range(4):
            await store.append_trajectory(TENANT, "run-1", TrajectoryKind.MESSAGE, {"i": i})
        assert [r.seq for r in await store.read_trajectory(TENANT, "run-1", after_seq=2)] == [3, 4]

    async def test_purge_removes_one_run_and_leaves_the_others(self):
        store = InMemoryTrajectoryStore()
        await store.append_trajectory(TENANT, "run-1", TrajectoryKind.PROMPT, {})
        await store.append_trajectory(TENANT, "run-2", TrajectoryKind.PROMPT, {})
        assert await store.purge_trajectory(TENANT, "run-1") == 1
        assert await store.read_trajectory(TENANT, "run-1") == []
        assert len(await store.read_trajectory(TENANT, "run-2")) == 1

    async def test_rows_expire(self):
        """SHORT RETENTION IS THE POINT: a verbatim record of what a user typed
        is not something to keep indefinitely just because it is useful."""
        store = InMemoryTrajectoryStore()
        await store.append_trajectory(TENANT, "run-1", TrajectoryKind.PROMPT, {}, ttl_days=1)
        assert await store.expire_trajectories(now=utcnow()) == 0
        assert await store.expire_trajectories(now=utcnow() + timedelta(days=2)) == 1
        assert await store.read_trajectory(TENANT, "run-1") == []


class TestExportShape:
    def test_a_row_exports_as_a_self_describing_jsonl_line(self):
        """An export is read by scripts that do not have our classes."""
        event = TrajectoryEvent(
            tenant_id=TENANT, run_id="run-1", seq=1,
            kind=TrajectoryKind.TOOL_CALL, payload={"verb": "ticket.create"},
            actor="agent-1", parent_run_id="root", depth=2,
        )
        row = event.to_jsonl_row()
        assert json.loads(json.dumps(row))["kind"] == "tool_call"
        assert row["parent_run_id"] == "root" and row["depth"] == 2
        # The tenant is NOT in the export: it is the scope you exported FROM,
        # and repeating it on every line invites treating a file as portable
        # between tenants.
        assert "tenant_id" not in row


@pytest.mark.asyncio
class TestThroughTheChokepoint:
    """The claim that actually matters: a real dispatch produces a real record."""

    async def test_an_invoke_records_the_call_and_its_result(self, kernel_and_adapter):
        from tests.conftest import TENANT as KERNEL_TENANT, make_ctx

        kernel, _ = kernel_and_adapter
        kernel.trajectory._enabled = True  # the tenant opting in

        ctx = make_ctx(["ticket.create"], run_id="run-traj")
        await kernel.dispatcher.invoke("ticket", "ticket.create", {"title": "hello"}, ctx)

        rows = await kernel.trajectory_store.read_trajectory(KERNEL_TENANT, "run-traj")
        kinds = [r.kind for r in rows]
        assert TrajectoryKind.TOOL_CALL in kinds
        assert TrajectoryKind.TOOL_RESULT in kinds

        call = next(r for r in rows if r.kind is TrajectoryKind.TOOL_CALL)
        # VERBATIM: the run event beside this one carries a redacted projection;
        # the trajectory carries the parameters as they were actually passed.
        assert call.payload["params"] == {"title": "hello"}
        assert call.payload["verb"] == "ticket.create"

        result = next(r for r in rows if r.kind is TrajectoryKind.TOOL_RESULT)
        assert result.payload["call_id"] == call.payload["call_id"], "the pair must correlate"
        assert result.seq > call.seq, "a result cannot precede its call"

    async def test_recording_is_off_unless_asked(self, kernel_and_adapter):
        from tests.conftest import TENANT as KERNEL_TENANT, make_ctx

        kernel, _ = kernel_and_adapter
        ctx = make_ctx(["ticket.create"], run_id="run-quiet")
        await kernel.dispatcher.invoke("ticket", "ticket.create", {"title": "hi"}, ctx)
        assert await kernel.trajectory_store.read_trajectory(KERNEL_TENANT, "run-quiet") == []
