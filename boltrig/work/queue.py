"""Source queue adapters and the confidence scorer (S7.7, US-WRK-02).

A source queue (Jira, Monday, an internal inbox, ...) is an input/output channel
only; the fleet's view of work is always the normalised :class:`WorkItem` (P10).
:class:`QueueAdapter` is the contract every source implements; it both polls raw
work IN and writes discovered work BACK. :func:`score_confidence` and
:func:`decide_mode` decide how well-specified an item is and therefore whether it
runs as a convergent (known-steps) or divergent (may-expand) job (FR-WRK-02).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from boltrig.models import WorkItem

# --- confidence scoring (FR-WRK-02, US-WRK-02) --------------------------------
# A payload is "well specified" to the extent it names what, why, done-when, who
# and by-when. Weights sum to 1.0 so the score lands in [0, 1].
_CONFIDENCE_WEIGHTS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (0.30, ("title", "summary", "name", "subject")),
    (0.25, ("description", "body", "details")),
    (0.20, ("acceptance_criteria", "acceptance", "done_criteria", "definition_of_done")),
    (0.15, ("assignee", "owner", "assigned_to")),
    (0.10, ("deadline", "due_date", "due", "due_at")),
)

CONVERGENT_THRESHOLD = 0.7


def _present(raw: dict[str, Any], keys: tuple[str, ...]) -> bool:
    """True iff ``raw`` carries any of ``keys`` with a non-empty value."""
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict, tuple)) and not value:
            continue
        return True
    return False


def score_confidence(raw: dict[str, Any]) -> float:
    """How well-specified ``raw`` is, in ``[0, 1]`` (FR-WRK-02).

    Heuristic and deterministic: each well-known facet present (a title, a
    description, acceptance criteria, an assignee, a deadline) adds its weight.
    """
    if not isinstance(raw, dict):
        return 0.0
    total = sum(weight for weight, keys in _CONFIDENCE_WEIGHTS if _present(raw, keys))
    return round(min(1.0, max(0.0, total)), 3)


def decide_mode(confidence: float, threshold: float = CONVERGENT_THRESHOLD) -> bool:
    """Return ``convergent`` for a confidence score (US-WRK-02).

    A well-specified item (``confidence >= threshold``) runs convergent: known,
    shrinking steps. An under-specified one runs divergent (may expand) so the
    fleet explores before it commits.
    """
    return confidence >= threshold


# --- the source-queue contract (S7.7) -----------------------------------------
@runtime_checkable
class QueueAdapter(Protocol):
    """A source of work items and a sink for discovered ones (S7.7, P10)."""

    async def poll(self) -> list[WorkItem]: ...
    async def write_back(self, parent_id: str, items: list[WorkItem]) -> None: ...
    def score_confidence(self, raw: dict[str, Any]) -> float: ...


class InternalQueueAdapter:
    """A reference in-memory :class:`QueueAdapter` (offline-safe, no I/O).

    Raw payloads pushed via :meth:`push` are normalised to work items on
    :meth:`poll` (draining the inbox, standard queue semantics). Items written
    back are kept per parent for inspection. Real adapters (Jira, Monday) follow
    the same shape over a network client.
    """

    def __init__(self, tenant_id: str, source: str = "internal") -> None:
        self.tenant_id = tenant_id
        self.source = source
        self._inbox: list[dict[str, Any]] = []
        self.written_back: dict[str, list[WorkItem]] = {}

    def push(self, raw: dict[str, Any]) -> None:
        """Enqueue a raw source payload for the next :meth:`poll`."""
        self._inbox.append(dict(raw))

    async def poll(self) -> list[WorkItem]:
        """Drain the inbox into normalised work items (P10)."""
        from .normalise import normalise  # lazy: avoids a queue<->normalise cycle

        drained, self._inbox = self._inbox, []
        return [normalise(raw, self.source, self.tenant_id) for raw in drained]

    async def write_back(self, parent_id: str, items: list[WorkItem]) -> None:
        """Record discovered child items against their parent (US-WRK-04)."""
        self.written_back.setdefault(parent_id, []).extend(items)

    def score_confidence(self, raw: dict[str, Any]) -> float:
        """Delegate to the module-level heuristic (FR-WRK-02)."""
        return score_confidence(raw)
