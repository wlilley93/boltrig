"""A HITL pause must reach the person who asked for the thing being paused.

A chat turn never calls a verb itself: it spawns a worker whose cell reaches back
through the kernel MCP face, so every verb a chat turn causes is dispatched under
the CHILD run id. The chat client follows the ROOT run's stream. Publishing the
pause only to `context.run_id` therefore put it on a stream nobody follows - the
turn ended, and the user was told in prose that something was "pending human
approval" with nothing to approve. Verified live before the fix: a write turn's
frames were message_start / subagent / subagent_end / text_delta / message_end,
with no `hitl` frame at all.
"""

import asyncio

import pytest

from boltrig.models import InvocationContext, GrantSet


class _Relay:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def publish(self, tenant_id: str, run_id: str, event: dict) -> None:
        self.published.append((run_id, event))


class _Hitl:
    async def pending_event(self, context, request_id, verb, call_id):
        return {"type": "hitl", "verb": verb, "hitl_request_id": request_id}


def _dispatcher_with_relay(relay):
    """A Dispatcher with only the collaborators _emit_pause touches."""
    from boltrig.kernel.dispatch import Dispatcher

    d = Dispatcher.__new__(Dispatcher)
    d._events = relay
    d._hitl = _Hitl()
    return d


@pytest.mark.security
def test_pause_reaches_both_the_child_and_the_parent_stream():
    relay = _Relay()
    d = _dispatcher_with_relay(relay)
    ctx = InvocationContext(
        tenant_id="t", grants=GrantSet.of(["*"]), run_id="child", parent_run_id="root"
    )
    asyncio.run(d._emit_pause(ctx, "hitl-1", "opbox.add_comment", "call-1"))

    streams = [run_id for run_id, _ in relay.published]
    assert streams == ["child", "root"], "the pause must reach the stream the client follows"


@pytest.mark.security
def test_a_root_run_publishes_once_not_twice():
    """A run with no parent - or one that is its own parent - must not double-emit."""
    relay = _Relay()
    d = _dispatcher_with_relay(relay)
    for parent in (None, "root"):
        relay.published.clear()
        ctx = InvocationContext(
            tenant_id="t", grants=GrantSet.of(["*"]), run_id="root", parent_run_id=parent
        )
        asyncio.run(d._emit_pause(ctx, "hitl-1", "opbox.add_comment", "call-1"))
        assert [r for r, _ in relay.published] == ["root"]


@pytest.mark.security
def test_the_run_token_carries_the_parent_so_a_cell_can_reach_it():
    """The cell's context is built from its run token, so the token must carry the
    parent - otherwise dispatch has nothing to publish the pause to."""
    from boltrig.kernel.mcp import McpFace

    face = McpFace(kernel=None)
    token = face.issue_run_token("t", GrantSet.of(["*"]), run_id="child", parent_run_id="root")
    stored = face._tokens[McpFace._token_key(token)]
    assert stored.run_id == "child"
    assert stored.parent_run_id == "root"
    # And it reaches the InvocationContext the verb is dispatched under.
    ctx = face._context(stored)
    assert ctx.run_id == "child" and ctx.parent_run_id == "root"


@pytest.mark.security
def test_a_token_without_a_parent_is_unchanged():
    """Every existing caller omits it; that run must behave exactly as before."""
    from boltrig.kernel.mcp import McpFace

    face = McpFace(kernel=None)
    token = face.issue_run_token("t", GrantSet.of(["*"]), run_id="solo")
    assert face._tokens[McpFace._token_key(token)].parent_run_id is None
