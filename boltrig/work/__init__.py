"""The work-item library: normalise sources, score confidence, persist (P10).

The fleet operates only on normalised work items. This package owns the source
translation (:func:`normalise`), the source-queue contract
(:class:`QueueAdapter`), the confidence heuristic, and source-agnostic
persistence (:class:`WorkItemStore`).
"""

from __future__ import annotations

from .normalise import normalise
from .queue import (
    CONVERGENT_THRESHOLD,
    InternalQueueAdapter,
    QueueAdapter,
    decide_mode,
    score_confidence,
)
from .store import WorkItemStore

__all__ = [
    "CONVERGENT_THRESHOLD",
    "InternalQueueAdapter",
    "QueueAdapter",
    "WorkItemStore",
    "decide_mode",
    "normalise",
    "score_confidence",
]
