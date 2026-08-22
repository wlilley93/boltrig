"""Where ``_summarise_params``, ``_summarise_output`` and ``_event_safe`` live.

Lifted out of ``boltrig.kernel.dispatch``: they are pure shaping functions holding no
dispatch state, so the chokepoint was the wrong home for them. Each one's own
docstring states what it guarantees; the mechanisms they rest on are
``schema_diagnosis.MAX_PARAM_KEYS`` (the key cap) and ``idempotency.sensitive_key``
(the redaction predicate), both imported below.
"""

from __future__ import annotations

from typing import Any

from .idempotency import sensitive_key
from .schema_diagnosis import MAX_PARAM_KEYS


def _summarise_params(params: Any) -> dict[str, Any]:
    """A bounded, VALUE-FREE description of a verb's params for the chat stream
    (K-20 bounded observability): the sorted top-level KEY NAMES and their count,
    never the values (which can carry secrets or untrusted content).

    Since the schema-validation ledger order (D1) this rides on the AUDIT ROW as well as the
    stream. It had fed only the stream since K-20, so a regulator-facing row was strictly
    shallower than the chat stream beside it, and it is what makes a `schema_invalid` row
    answerable at all: the recorded keys, against the registered schema's `required`, are a
    diff rather than a guess."""
    if isinstance(params, dict):
        keys = sorted(str(k) for k in params)
        # Capped, because this now reaches the append-only audit row and not only the
        # ephemeral stream. A key NAME is instance-chosen, so no mechanical check can
        # guarantee it is never itself sensitive; it is admitted because it is a name and not
        # a value, bounded here, and still passed through the write-time scrub as a second
        # line. That is a recorded LIMIT of the schema-validation ledger order (L1), not a
        # safety proof, and no test should pretend otherwise.
        return {"keys": keys[:MAX_PARAM_KEYS], "count": len(keys)}
    return {"keys": [], "count": 0}


def _summarise_output(output: Any) -> dict[str, Any]:
    """A bounded, VALUE-FREE description of a verb's output (K-20): the output's
    top-level key names only, never the values."""
    if isinstance(output, dict):
        return {"keys": sorted(str(k) for k in output)}
    return {"keys": []}


def _event_safe(value: Any) -> Any:
    """Redact secret-shaped values before the internal run-event relay.

    The caller still receives the real adapter result. Durable/run-canvas event
    records do not need bearer material and must never become a second secret
    store (notably for one-time invitation tokens).
    """
    if isinstance(value, dict):
        media_type = value.get("media_type")
        media_payload = (
            isinstance(media_type, str)
            and (media_type.startswith("image/") or media_type.startswith("audio/") or media_type.startswith("video/"))
        )
        safe: dict[str, Any] = {}
        for key, item in value.items():
            redact_media = media_payload and str(key) in {"data", "blob", "bytes"}
            safe[str(key)] = (
                "[redacted]" if sensitive_key(key) or redact_media else _event_safe(item)
            )
        return safe
    if isinstance(value, list):
        return [_event_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_event_safe(item) for item in value]
    return value


def result_frames(
    *, verb: str, status: str, output: Any, run_id: Any, call_id: Any
) -> list[dict[str, Any]]:
    """The run-event frames one completed verb produces. Usually one, sometimes two.

    A LIST rather than a single frame, because ``voice.listen`` is the first verb
    whose outcome carries something the emotion relay needs to see separately from
    the tool result. The relay matches rules on an event's TOP-LEVEL fields -- the
    table is ``where: {verb: ...}`` and nothing walks into a nested payload -- so a
    tone buried inside a ``tool_result`` output is unreachable to it. It needs to be
    its own event type or it may as well not be measured.

    Kept here rather than in the dispatcher for the reason this module exists: these
    are pure shaping functions holding no dispatch state, and the chokepoint is the
    wrong home for them. The dispatcher decides WHEN a verb has finished; what that
    finish looks like on the wire is this module's business.

    The tone frame deliberately carries NO transcript. The point of measuring
    delivery rather than words is that the words do not have to travel, and putting
    them on a second stream to save a lookup would give that away for nothing.
    """
    frames: list[dict[str, Any]] = [
        {
            "type": "tool_result", "verb": verb, "status": status,
            "output": _event_safe(output) if status == "ok" else None,
            "run_id": run_id, "call_id": call_id,
            "result_summary": (
                _summarise_output(output) if status == "ok" else {"status": status}
            ),
        }
    ]
    tone = _tone_frame(status, output, run_id)
    if tone is not None:
        frames.append(tone)
    return frames


def _tone_frame(status: str, output: Any, run_id: Any) -> dict[str, Any] | None:
    """A ``voice_tone`` event, when the verb reported one and only then.

    Every gate here is a refusal: a failed verb, an output that is not a mapping, a
    missing or malformed tone block. The tone is a garnish on a transcript and must
    never be the reason an event is malformed -- so anything unexpected produces no
    event rather than a partial one.
    """
    if status != "ok" or not isinstance(output, dict):
        return None
    block = output.get("tone")
    if not isinstance(block, dict):
        return None
    label = block.get("tone")
    if not isinstance(label, str) or not label:
        return None
    intensity = block.get("intensity")
    return {
        "type": "voice_tone",
        "tone": label,
        "intensity": float(intensity) if isinstance(intensity, (int, float)) else 0.5,
        # How many utterances the baseline behind this had heard. On the event so
        # that a tone can be discounted after the fact if the calibration turns out
        # to have been thin -- a bare label cannot be second-guessed.
        "calibrated_on": block.get("calibrated_on"),
        "run_id": run_id,
    }
