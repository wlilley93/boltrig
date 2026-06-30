"""Normalise a raw source payload into a :class:`WorkItem` (US-WRK-01, P10).

Every source (Jira, Monday, an email inbox, a webhook) speaks its own shape. The
fleet only ever operates on the normalised work item, so this is the single
translation point: it preserves the raw payload verbatim, extracts a human
intent and the structured constraints, and scores how well-specified the item is
to choose convergent vs divergent execution (FR-WRK-02).
"""

from __future__ import annotations

import uuid
from typing import Any

from boltrig.models import WorkItem, WorkStatus

from .queue import decide_mode, score_confidence

# Field aliases seen across the common trackers, in priority order.
_INTENT_KEYS = (
    "intent", "title", "summary", "name", "subject", "task", "description", "body",
)
_SOURCE_ID_KEYS = ("source_id", "id", "key", "ticket_id", "number")
_CONSTRAINT_KEYS: dict[str, tuple[str, ...]] = {
    "deadline": ("deadline", "due_date", "due", "due_at"),
    "assignee": ("assignee", "owner", "assigned_to"),
    "dependencies": ("dependencies", "deps", "depends_on", "blocked_by"),
    "priority": ("priority", "severity"),
    "acceptance_criteria": (
        "acceptance_criteria", "acceptance", "done_criteria", "definition_of_done",
    ),
    "labels": ("labels", "tags"),
}


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """First present, non-empty value among ``keys`` (else ``None``)."""
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _extract_constraints(raw: dict[str, Any]) -> dict[str, Any]:
    """Pull the structured constraints (deadlines, assignee, deps) out of ``raw``."""
    out: dict[str, Any] = {}
    for canonical, aliases in _CONSTRAINT_KEYS.items():
        value = _first(raw, aliases)
        if value is not None:
            out[canonical] = value
    return out


def normalise(raw: dict[str, Any], source: str, tenant_id: str) -> WorkItem:
    """Turn a raw source payload into a :class:`WorkItem` (US-WRK-01).

    The original ``raw`` is preserved verbatim (a shallow copy, so the caller's
    dict is never mutated). ``confidence`` comes from :func:`score_confidence`
    and ``convergent`` from :func:`decide_mode`, so a well-specified item runs
    with known steps and a vague one is allowed to expand (FR-WRK-02).
    """
    raw = dict(raw or {})
    intent_value = _first(raw, _INTENT_KEYS)
    intent = str(intent_value) if intent_value is not None else ""
    source_id_value = _first(raw, _SOURCE_ID_KEYS)
    source_id = str(source_id_value) if source_id_value is not None else None

    confidence = score_confidence(raw)
    return WorkItem(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        source=source,
        intent=intent,
        confidence=confidence,
        convergent=decide_mode(confidence),
        status=WorkStatus.PENDING,
        source_id=source_id,
        constraints=_extract_constraints(raw),
        raw=raw,
    )
