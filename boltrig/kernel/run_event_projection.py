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
