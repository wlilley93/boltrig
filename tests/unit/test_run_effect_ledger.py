"""The recording policy: what enters the durable run-effect ledger (FR-REV-01)."""

from __future__ import annotations

import pytest

from boltrig.kernel.effect_inverses import inverse_for, register_inverse
from boltrig.kernel.run_effect_recorder import record_run_effect
from boltrig.models import GrantSet, InvocationContext
from boltrig.store import InMemoryStore

T = "acme"


@pytest.fixture()
def slack_inverse(monkeypatch):
    # A scratch copy of the registry, so registrations cannot leak between tests.
    import boltrig.kernel.effect_inverses as module

    monkeypatch.setattr(module, "_BUILDERS", {})
    register_inverse(
        "slack.message.send",
        lambda params, output: (
            ("slack.message.delete", {"ts": output["ts"], "channel": params["channel"]})
            if output.get("ts")
            else None
        ),
    )


def _context(run_id: str = "run-1", *, revert: bool = False) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id=run_id,
        grants=GrantSet.of(["*"]),
        extra={"effect_revert": "orig"} if revert else {},
    )


async def _record(store, verb, params, output, context, *, gated):
    await record_run_effect(
        store, verb, params, output, context, {"gated": gated},
        summarise=lambda p: str(sorted(p)),
    )


@pytest.mark.invariant("FR-REV-01")
async def test_gated_success_records_with_its_inverse(slack_inverse):
    store = InMemoryStore()
    await _record(
        store, "slack.message.send", {"channel": "C1", "text": "hi"},
        {"ts": "171.5"}, _context(), gated=True,
    )

    rows = await store.list_run_effects(T, "run-1")
    assert [(r.seq, r.status, r.inverse_verb) for r in rows] == [
        (1, "recorded", "slack.message.delete")
    ]
    # The inverse params were built AT RECORD TIME from the success output -
    # the identifier a later revert needs, captured while it is still known.
    assert rows[0].inverse_params == {"ts": "171.5", "channel": "C1"}


@pytest.mark.invariant("FR-REV-01")
async def test_unknown_verbs_fail_closed_to_not_undoable(slack_inverse):
    store = InMemoryStore()
    await _record(store, "email.send", {"to": "a@b"}, {}, _context(), gated=True)

    rows = await store.list_run_effects(T, "run-1")
    assert [(r.status, r.inverse_verb) for r in rows] == [("not_undoable", None)]
    # And the registry itself answers None for the unknown verb.
    assert inverse_for("email.send", {}, {}) is None


@pytest.mark.invariant("FR-REV-01")
async def test_a_revert_run_records_nothing(slack_inverse):
    store = InMemoryStore()
    await _record(
        store, "slack.message.send", {"channel": "C1"}, {"ts": "1"},
        _context(revert=True), gated=True,
    )

    assert await store.list_run_effects(T, "run-1") == []


async def test_ungated_unannotated_calls_stay_off_the_ledger(slack_inverse):
    # A read-only search is neither gated nor invertible: no row, no noise.
    store = InMemoryStore()
    await _record(store, "knowledge.search", {"q": "x"}, {}, _context(), gated=False)

    assert await store.list_run_effects(T, "run-1") == []


async def test_a_raising_builder_is_not_undoable_never_a_failed_call(slack_inverse):
    register_inverse("jira.ticket.create", lambda p, o: o["missing-key"])
    store = InMemoryStore()
    await _record(store, "jira.ticket.create", {}, {}, _context(), gated=True)

    rows = await store.list_run_effects(T, "run-1")
    assert [(r.status, r.inverse_verb) for r in rows] == [("not_undoable", None)]


async def test_settle_cas_lets_exactly_one_caller_win(slack_inverse):
    store = InMemoryStore()
    await _record(
        store, "slack.message.send", {"channel": "C1"}, {"ts": "1"},
        _context(), gated=True,
    )

    first = await store.settle_run_effect(
        T, "run-1", 1, expected="recorded", status="reverted"
    )
    second = await store.settle_run_effect(
        T, "run-1", 1, expected="recorded", status="reverted"
    )
    assert (first, second) == (True, False)
