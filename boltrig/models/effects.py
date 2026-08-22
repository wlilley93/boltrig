"""A recorded run effect: one governed change, and how to undo it - or the
honest admission that nothing can.

The DURABLE sibling of ``kernel/revertible.py``. That module's ``EffectLog``
compensates one in-process operation (MCP activation) and dies with the
process, by design. A chat or development run outlives its process and its
user asks a different question - "undo what that conversation did" - so its
effects are ROWS: appended by the dispatch chokepoint when a consequential
verb succeeds, reverted later through the same chokepoint (governed, audited,
HITL-gated like any other call).

``inverse_verb`` None is a FIRST-CLASS answer, not a gap: a sent email has no
inverse, and the ledger's job is to say so (``not_undoable``) rather than
pretend. Inverses come from ``kernel/effect_inverses.py``; a verb that
registry does not know fails closed to not-undoable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import RunId, TenantId, utcnow

#: recorded      - the effect happened; its inverse (if any) has not run.
#: not_undoable  - the effect happened and no inverse exists. Terminal.
#: reverted      - the inverse ran through dispatch and succeeded. Terminal.
#: revert_failed - the inverse ran and failed; the effect may persist. Terminal.
RUN_EFFECT_STATUSES: frozenset[str] = frozenset(
    {"recorded", "not_undoable", "reverted", "revert_failed"}
)


@dataclass
class RunEffect:
    """One effect row. ``seq`` orders the run's effects; revert walks it LIFO
    (the same load-bearing ordering ``kernel/revertible.py`` documents: later
    effects may depend on earlier ones still being in place)."""

    tenant_id: TenantId
    run_id: RunId
    seq: int
    verb_id: str
    status: str = "recorded"
    inverse_verb: str | None = None
    inverse_params: dict[str, Any] = field(default_factory=dict)
    #: Bounded human label for the undo surface ("ticket PROJ-1 created"),
    #: derived from the summarised params - never the raw payload (K-20).
    summary: str = ""
    created_at: datetime = field(default_factory=utcnow)
