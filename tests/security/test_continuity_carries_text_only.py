"""What cross-turn continuity carries, and what it drops, ASSERTED IN BOTH DIRECTIONS.

WHY THIS FILE EXISTS. `boltrig/fleet/continuity.py` renders a turn from
`message.content` alone. Every tool call and tool result the turn made is sitting one
attribute away on the same object, in `message.events`, and is never read. Before this
file, NO TEST IN THE REPOSITORY asserted that in either direction: not that the tool work
is dropped, and not that it stays dropped. `SEC-46` says continuity "composes only
persisted text", and that sentence lived in `docs/invariants.md` and in a module docstring
with nothing underneath it. The invariant's own named test
(`test_round_six.py::test_continuity_is_deterministic_and_append_only`) proves determinism,
prefix stability and the absence of the words "grant" and "token" - it never builds a
message that HAS events, so it could not have noticed either half moving.

THE TWO HALVES PULL IN OPPOSITE DIRECTIONS, which is the whole reason to pin both.

  (1) THE DEFECT. A turn that ran five tools and narrated nothing renders into the next
      turn as `Assistant: <untrusted ...></untrusted>` - an empty envelope. The model is
      told it spoke and told it said nothing, which is not what happened. `continuity.py`
      records this outcome in a comment as a rendering nicety ("Empty content (e.g. a turn
      that produced only tool/HITL events) still renders deterministically as an empty
      envelope"), which describes it accurately and enforces nothing.

  (2) THE SECURITY PROPERTY. Tool argument VALUES and result VALUES must never reach a
      later prompt. `test_chat_streaming_richness.py` proves they never reach the browser
      stream and never reach `message.events`, because
      `chat_event_projection.py` strips them BEFORE persistence. Nothing proved they never
      reach the composed prompt. That is a different boundary with a different reader, and
      the obvious "fix" for (1) - render `message.events` into the transcript - is exactly
      the change that would breach it if it reached past the bounded projection.

So this file pins (2) as a security floor and pins (1) as a RECORD OF A KNOWN GAP. Whoever
closes (1) must edit this file, and the diff will put the two halves side by side, which is
the point: the empty envelope is a defect and the value exclusion is not, and a single
careless change could "fix" the first by breaking the second.

NOT A DESIGN DECISION. Pinning what the system does today is not a ruling that it should.
Whether a bounded, value-free tool-work line belongs in the transcript changes SEC-46's own
wording, so it is filed to the court rather than decided here.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.continuity import compose_turn_task, render_transcript
from boltrig.models import ConversationMessage, MessageRole

T = "tenant-continuity"


def _msg(
    role: MessageRole,
    content: str | None,
    *,
    mid: str,
    events: list[dict] | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        id=mid,
        conversation_id="c",
        tenant_id=T,
        role=role,
        content=content,
        events=events or [],
    )


# The shape `chat_event_projection.py` actually persists: names and argument KEY names,
# never values. Reproduced here from `_tool_call` / `_tool_result` so this test fails if
# the projection widens, rather than silently agreeing with whatever it becomes.
def _tool_events(secret: str) -> list[dict]:
    return [
        {
            "type": "tool_call",
            "run_id": "r1",
            "tool": "ticket.create",
            "call_id": "call-1",
            "args_summary": {"keys": ["title", "api_key"], "count": 2},
        },
        {
            "type": "tool_result",
            "run_id": "r1",
            "call_id": "call-1",
            "status": "ok",
            "result_summary": {"keys": ["id"], "status": "ok"},
        },
        # A hostile-but-realistic case: a projection bug, or a future widening, that let a
        # value through onto the persisted row. Continuity must not be the thing that
        # carries it into the next prompt even then. Defence in depth, deliberately: the
        # projection is the primary guard and this is the second one.
        {"type": "tool_call", "tool": "vault.read", "leaked": secret},
    ]


@pytest.mark.security
@pytest.mark.invariant("SEC-46")
def test_tool_event_values_never_reach_a_later_prompt():
    """THE SECURITY HALF. Nothing from `message.events` enters the composed task.

    Asserted at the PROMPT boundary, which is a different reader from the browser stream
    that `test_chat_streaming_richness.py` guards. The leaked-value event is the negative
    control: without it this test would pass on a transcript that renders event dicts,
    because the tool NAMES alone read as harmless.
    """
    secret = "sk-live-do-not-echo-4a91"
    # `messages` is the FULL ordered transcript and already ends with the just-persisted
    # current user turn; `current_message` is only the empty-history fallback. Composed the
    # way `chat_turn_execution.py:113-120` composes it, because a test that calls a function
    # differently from its one production caller proves something about neither.
    history = [
        _msg(MessageRole.USER, "open a ticket", mid="m1"),
        _msg(MessageRole.ASSISTANT, "Done.", mid="m2", events=_tool_events(secret)),
        _msg(MessageRole.USER, "and now assign it", mid="m3"),
    ]

    task = compose_turn_task(history, "and now assign it")

    assert secret not in task, "a value on the persisted event row reached the next prompt"
    assert "vault.read" not in task
    assert "ticket.create" not in task, "tool NAMES are also not carried today"
    assert "args_summary" not in task and "call-1" not in task
    # The control: what IS carried is carried, so this is not passing because the
    # transcript is empty.
    assert "open a ticket" in task and "Done." in task and "and now assign it" in task


@pytest.mark.security
@pytest.mark.invariant("SEC-46")
def test_a_turn_that_only_ran_tools_renders_as_an_empty_envelope():
    """THE DEFECT HALF, pinned so that closing it is a deliberate, visible act.

    This asserts a behaviour that is WRONG on the merits: a turn that did real work and
    narrated none of it is presented to the next turn as a turn that said nothing. It is
    recorded rather than fixed because fixing it changes what SEC-46 permits into the
    prompt, and that is the court's call, not this file's.
    """
    worked_silently = _msg(
        MessageRole.ASSISTANT, "", mid="m2", events=_tool_events("unused")
    )
    said_nothing_at_all = _msg(MessageRole.ASSISTANT, "", mid="m3", events=[])

    # The two are INDISTINGUISHABLE in the transcript. That is the defect in one line:
    # five tool calls and total inactivity render identically.
    assert render_transcript([worked_silently]) == render_transcript([said_nothing_at_all])

    # And `None` content - the DB default when a row was written before any delta
    # arrived - must not render the string "None" into a prompt.
    never_wrote_content = _msg(MessageRole.ASSISTANT, None, mid="m4")
    rendered = render_transcript([never_wrote_content])
    assert "None" not in rendered
    assert rendered == render_transcript([said_nothing_at_all])


@pytest.mark.security
@pytest.mark.invariant("SEC-46")
def test_events_do_not_disturb_prefix_stability():
    """Prefix stability is what the gateway cache rests on, and it must not depend on
    whether a turn happened to use tools. If events ever DO get rendered, they must render
    append-only like everything else; this fails loudly if a change makes an earlier turn's
    text depend on a later turn's events."""
    turn1 = [_msg(MessageRole.USER, "hello", mid="m1")]
    turn2 = turn1 + [
        _msg(MessageRole.ASSISTANT, "hi", mid="m2", events=_tool_events("x")),
        _msg(MessageRole.USER, "again", mid="m3"),
    ]
    assert render_transcript(turn2).startswith(render_transcript(turn1))
