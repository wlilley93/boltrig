"""Round Ten - the event backbone (FR-EVT-01/02, SEC-55).

Make real agent activity flow to the run-event relay so the chat renderer and the
run canvas (which already render tool/subagent/hitl events) light up.

FR-EVT-01  a verb invoked under a run publishes a paired tool_call + tool_result
           to that run's stream (tool_result carries status; failure leaks nothing).
FR-EVT-02  run events are a pure side-channel - a relay failure never breaks a
           call, and a call with no run_id publishes nothing.
SEC-55     run events are run-keyed and credential-free: a verb's events publish
           ONLY to its own run's stream, and never carry credential material.
"""

from __future__ import annotations

import pytest

from nankle.kernel.events import EventRelay
from nankle.models import GrantSet, InvocationContext
from tests.conftest import _build_kernel  # ticket adapter + gated variant

T = "acme"


def _drain(relay: EventRelay, run_id: str) -> list[dict]:
    """Snapshot the relay backlog for a run (publish records it synchronously)."""
    return list(relay._backlog.get(run_id, []))


def _ctx(run_id: str | None, grants=("ticket.*",)) -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(list(grants)),
                            actor="u", run_id=run_id)


# --------------------------------------------------------------------------- #
# FR-EVT-01  paired tool_call + tool_result on the run stream
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-EVT-01")
async def test_verb_publishes_paired_tool_events():
    k, _ = await _build_kernel()
    await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx("run-A"))
    events = _drain(k.events, "run-A")
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result"]
    call, result = events
    assert call["verb"] == "ticket.create" and call["input"] == {"title": "x"}
    assert result["verb"] == "ticket.create" and result["status"] == "ok"
    assert result["output"] is not None  # success carries the output


@pytest.mark.invariant("FR-EVT-01")
async def test_failed_verb_emits_error_result_without_leaking():
    k, _ = await _build_kernel()
    # missing required param -> schema_invalid; the result event reports failure
    # with no output payload.
    try:
        await k.invoke("ticket", "ticket.create", {}, _ctx("run-B"))
    except Exception:
        pass
    events = _drain(k.events, "run-B")
    assert events[0]["type"] == "tool_call"
    result = events[-1]
    assert result["type"] == "tool_result"
    assert result["status"] != "ok" and result["output"] is None


# --------------------------------------------------------------------------- #
# FR-EVT-02  events are a fail-safe side-channel
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-EVT-02")
async def test_no_run_id_publishes_nothing_and_call_still_works():
    k, _ = await _build_kernel()
    out = await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx(None))
    assert out["status"] == "open"  # the call works
    assert k.events._backlog == {}  # nothing published without a run


@pytest.mark.invariant("FR-EVT-02")
async def test_relay_failure_never_breaks_dispatch():
    k, _ = await _build_kernel()

    class _BrokenRelay:
        def publish(self, *a, **k):
            raise RuntimeError("relay down")

    k.dispatcher._events = _BrokenRelay()  # a relay that always throws
    # the verb still dispatches and returns normally despite the broken relay.
    out = await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx("run-C"))
    assert out["status"] == "open"


@pytest.mark.invariant("FR-EVT-02")
async def test_pending_human_emits_hitl_event():
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    from nankle.models import PendingHuman

    with pytest.raises(PendingHuman):
        await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx("run-D"))
    events = _drain(k.events, "run-D")
    kinds = [e["type"] for e in events]
    assert "hitl" in kinds  # the pause surfaces on the run stream
    assert "tool_result" not in kinds  # a paused call has no result yet


# --------------------------------------------------------------------------- #
# SEC-55  run-keyed isolation + credential-free events
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-55")
async def test_events_are_run_keyed_and_credential_free():
    k, _ = await _build_kernel()
    await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx("run-X"))
    try:  # ticket.read of a missing id raises, but still emits its run events
        await k.invoke("ticket", "ticket.read", {"id": "nope"}, _ctx("run-Y"))
    except Exception:
        pass

    # a run's events publish ONLY to its own stream - never cross-pollute.
    x_verbs = {e.get("verb") for e in _drain(k.events, "run-X")}
    y_verbs = {e.get("verb") for e in _drain(k.events, "run-Y")}
    assert x_verbs == {"ticket.create"} and y_verbs == {"ticket.read"}

    # no event anywhere carries credential material (credentials resolve inside
    # the kernel and never reach params/output, so never reach the stream).
    import json

    blob = json.dumps(k.events._backlog).lower()
    for marker in ("credential", "api_key", "secret", "password", "material", "token"):
        assert marker not in blob
