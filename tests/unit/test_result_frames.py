"""What a finished verb becomes on the wire, and when a tone gets its own event.

The tone frame exists because the emotion relay matches rules on an event's
TOP-LEVEL fields -- the table is ``where: {verb: ...}`` and nothing walks into a
nested payload -- so a tone buried inside a ``tool_result`` output is unreachable
to it. Everything below is either that, or a refusal: a malformed tone must
produce no event rather than a partial one, because the transcript is the product
and the tone is a garnish.
"""

from __future__ import annotations

from typing import Any

import pytest

from boltrig.kernel.run_event_projection import result_frames


def frames(**kwargs: Any) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "verb": "voice.listen",
        "status": "ok",
        "output": {"text": "hello"},
        "run_id": "run-1",
        "call_id": "call-1",
    }
    base.update(kwargs)
    return result_frames(**base)


def tone_output(**block: Any) -> dict[str, Any]:
    payload = {"tone": "cross", "intensity": 0.8, "calibrated_on": 9}
    payload.update(block)
    return {"text": "fine.", "tone": payload}


def test_an_ordinary_verb_produces_exactly_one_frame() -> None:
    out = frames(verb="opbox.add_comment", output={"id": 7})
    assert len(out) == 1
    assert out[0]["type"] == "tool_result"


def test_a_tone_gets_its_own_event_beside_the_result() -> None:
    out = frames(output=tone_output())
    assert [f["type"] for f in out] == ["tool_result", "voice_tone"]
    assert out[1]["tone"] == "cross"
    assert out[1]["intensity"] == pytest.approx(0.8)
    assert out[1]["calibrated_on"] == 9
    assert out[1]["run_id"] == "run-1"


def test_the_tone_frame_carries_no_transcript() -> None:
    # The point of measuring delivery rather than words is that the words do not
    # have to travel. Putting them on a second stream to save a lookup would give
    # that away for nothing.
    out = frames(output=tone_output())
    assert "text" not in out[1]
    assert "hello" not in str(out[1])
    assert "fine." not in str(out[1])


def test_the_result_frame_is_unchanged_by_a_tone_being_present() -> None:
    plain = frames(output={"text": "hello"})[0]
    toned = frames(output=tone_output())[0]
    assert plain["type"] == toned["type"] == "tool_result"
    assert toned["verb"] == "voice.listen"
    assert toned["status"] == "ok"
    assert toned["call_id"] == "call-1"


def test_a_failed_verb_emits_no_tone_and_no_output() -> None:
    out = frames(status="error", output=tone_output())
    assert len(out) == 1
    assert out[0]["output"] is None
    assert out[0]["result_summary"] == {"status": "error"}


@pytest.mark.parametrize(
    "output",
    [
        {"text": "hi"},
        {"text": "hi", "tone": None},
        {"text": "hi", "tone": "cross"},
        {"text": "hi", "tone": {}},
        {"text": "hi", "tone": {"tone": ""}},
        {"text": "hi", "tone": {"tone": 7}},
        "not a mapping at all",
        None,
    ],
    ids=[
        "no-tone", "null-tone", "tone-not-a-mapping", "empty-block",
        "empty-label", "label-not-a-string", "output-not-a-mapping", "no-output",
    ],
)
def test_a_malformed_tone_produces_no_event_rather_than_a_partial_one(
    output: Any,
) -> None:
    out = frames(output=output)
    assert [f["type"] for f in out] == ["tool_result"]


def test_a_missing_intensity_falls_back_rather_than_failing() -> None:
    # A tone with no intensity is still a tone worth appraising; the relay scales
    # by the RULE's intensity anyway, so this only has to be sane.
    out = frames(output=tone_output(intensity=None))
    assert out[1]["intensity"] == pytest.approx(0.5)


def test_a_pending_human_status_is_the_dispatcher_s_business_not_this_module_s() -> None:
    # The dispatcher does not call this at all for pending_human; if it ever did,
    # the frame should still be well-formed rather than half-built.
    out = frames(status="pending_human", output=tone_output())
    assert out[0]["type"] == "tool_result"
    assert out[0]["output"] is None
