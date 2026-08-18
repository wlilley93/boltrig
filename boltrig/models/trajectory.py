"""The trajectory: everything the model actually saw, in order (Decision TRJ-01).

WHY THIS IS NOT THE AUDIT LOG, and must never be folded into it.

``kernel/audit.py`` is the compliance source of truth and is deliberately
*bounded*: it scrubs ``detail``, refuses to persist raw secrets or identity
verbatim, and stores a digest plus a 256-character preview instead. That is
exactly right for a tamper-evident chain somebody may have to keep for years.

It is also exactly wrong for answering "why did it say that". Debugging a turn
needs the opposite: the whole prompt, the whole tool payload, the whole result,
unscrubbed and in order. Extending audit to carry that would either destroy its
retention posture or produce a second, quietly-unscrubbed column inside the
compliance record. So this is a separate stream with a separate posture:

    audit        bounded, scrubbed, tamper-evident, long retention, compliance
    trajectory   verbatim, unscrubbed, ordinary rows, SHORT retention, debugging

BECAUSE IT IS VERBATIM IT IS OPT-IN AND IT EXPIRES. Recording is off unless a
tenant turns it on, every row carries an expiry, and there is a purge. A store
of raw prompts is a store of whatever the user typed, which may include things
they would not put in an audit log on purpose.

REPLAY AND FORK COME FROM THE RUN GRAPH, not from a new concept. A run already
has ``run_id``, ``parent_run_id`` and ``depth`` (models/context.py), so a fork
is a run whose parent is the run it forked from, and replay is reading a run's
events in sequence. Nothing here invents a session identity that the kernel
does not already have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import utcnow


class TrajectoryKind(str, Enum):
    """What a row is. Deliberately small: a kind nobody can define precisely is
    a kind nobody can filter on."""

    PROMPT = "prompt"
    """What was sent to the model, verbatim."""

    CONTEXT = "context"
    """Something injected into the prompt -- a skill, a memory, an attachment.

    Separate from PROMPT because the interesting question is almost always
    "what got injected and by whom", and a single blob cannot answer it."""

    REASONING = "reasoning"
    """The model's thinking, where the runtime exposes it."""

    MESSAGE = "message"
    """Assistant output text."""

    TOOL_CALL = "tool_call"
    """A verb invocation with its parameters, recorded at the dispatch chokepoint."""

    TOOL_RESULT = "tool_result"
    """That call's outcome, success or failure."""

    ERROR = "error"
    """Something the turn could not do. Recorded rather than raised."""


@dataclass(frozen=True)
class TrajectoryEvent:
    """One append-only row.

    ``seq`` is per (tenant, run) and monotonic. It is assigned by the STORE
    rather than the caller: two concurrent tool calls in one run would otherwise
    race for a number, and a trajectory whose order is a guess is not a
    trajectory.
    """

    tenant_id: str
    run_id: str
    seq: int
    kind: TrajectoryKind
    payload: dict[str, Any]
    at: datetime = field(default_factory=utcnow)
    actor: str = "unknown"
    parent_run_id: str | None = None
    depth: int = 0
    expires_at: datetime | None = None

    def to_jsonl_row(self) -> dict[str, Any]:
        """One line of an exported session log.

        Flat and self-describing: an export is read by people and by scripts
        that do not have this class, so it carries its own field names rather
        than a positional shape.
        """
        return {
            "seq": self.seq,
            "at": self.at.isoformat(),
            "kind": self.kind.value,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "depth": self.depth,
            "actor": self.actor,
            "payload": self.payload,
        }
