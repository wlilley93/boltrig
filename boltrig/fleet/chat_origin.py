"""Which surface a chat turn came from, without letting a caller steer routing.

THE REQUIREMENT. One conversation, two surfaces: a message typed into an Opbox
spotlight should appear in the boltrig UI as the same thread, attributed to the
channel it arrived through. Turns from different surfaces can share a
conversation, so attribution belongs on the TURN, not on the conversation.

THE TRAP, and why this is not simply ``source``. ``WorkItem.source`` looks like
the obvious home - opbox already stamps ``source='opbox', source_id=<matterId>``
at intake - but it is not a label. ``chief_of_staff._route_deterministic`` does::

    if work_item.source in dept.queue_sources: return dept.name

so ``source`` selects the DEPARTMENT. Accepting a caller-supplied ``source``
would let a client choose which department handles their work: routing authority
handed to the requester, through what reads like a display field. Anyone
implementing "attribute the channel" by the obvious route would have shipped it.

WHAT THIS DOES INSTEAD. ``source`` stays ``"chat"``, so routing is untouched and
every existing ``queue_sources`` rule keeps its meaning. The origin goes in
``source_id``, which is documented as the GENERIC OPAQUE EXTERNAL REFERENCE
(``platform_routes/observability``), is NULL on every chat turn today, and is
already filterable end to end: ``/v1/runs?external_ref=...`` reads it, and both
the Postgres and in-memory stores implement the filter. So a UI can list "runs
that came from the Opbox spotlight" with no new column and no new query path.

It is a LABEL and nothing else. It grants nothing, narrows nothing, and reaches
no authority decision - which is exactly why a caller may set it.
"""

from __future__ import annotations

import re

# ASCII, bounded, and no separators that would let a label impersonate a
# structured reference elsewhere. Caller-supplied and stored, so it is
# canonicalised rather than trusted: an unusable value is dropped, never a reason
# to refuse someone's message.
_ORIGIN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}\Z")

MAX_ORIGIN_LENGTH = 64


def normalised_origin(raw: object) -> str | None:
    """A bounded lower-case origin label, or ``None`` when absent or unusable.

    ``None`` leaves ``source_id`` NULL, which is exactly today's behaviour, so a
    client that sends nothing loses nothing.
    """

    if not isinstance(raw, str):
        return None
    label = raw.strip().lower()
    if not label or _ORIGIN.fullmatch(label) is None:
        return None
    return label


__all__ = ["MAX_ORIGIN_LENGTH", "normalised_origin"]
