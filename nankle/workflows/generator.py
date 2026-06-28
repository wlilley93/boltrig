"""Deterministic workflow generation and learning (US-WFL-02/03/05).

When no precreated workflow matches an intent, the fleet synthesises one. The
synthesis is DETERMINISTIC and offline: no LLM is called (mirrors the adapter
generator's contract). A generated workflow is a fixed, linear Hatchet-style
pipeline (understand -> plan -> execute -> verify -> report). When such a run
succeeds, :func:`learn_from_success` re-saves it as ``source='learned'`` so the
library can reuse it next time (US-WFL-03).

:func:`schedule_spec` builds a timezone-aware cron trigger spec (US-WFL-05).
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from zoneinfo import ZoneInfo

from nankle.models import WorkflowDefinition, WorkflowSource

# The fixed linear pipeline a generated workflow runs (US-WFL-02). Each stage is
# one Hatchet step whose only parent is the stage before it (a strict line).
_PIPELINE: tuple[tuple[str, str], ...] = (
    ("understand", "Read the task and its inputs; restate the goal and constraints."),
    ("plan", "Decompose the goal into ordered, independently-verifiable steps."),
    ("execute", "Carry out the plan, invoking verbs through the kernel chokepoint."),
    ("verify", "Check each output against its acceptance criteria."),
    ("report", "Summarise outcomes and write back any discovered work items."),
)


def _slug(text: str) -> str:
    """A stable, filesystem-safe slug derived from free text (deterministic)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:48] or "task"


def generate_workflow(
    task: str, intent_tags: list[str], tenant_id: str
) -> WorkflowDefinition:
    """Build a deterministic linear workflow for ``task`` (US-WFL-02).

    The ``definition`` is a Hatchet-style spec dict: a named workflow whose steps
    form a single dependency line. ``source`` is ``generated`` and no LLM is
    involved, so the same task always yields the same spec.
    """
    name = f"gen-{_slug(task)}"
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for index, (stage, description) in enumerate(_PIPELINE, start=1):
        step_id = f"step-{index}-{stage}"
        steps.append(
            {
                "id": step_id,
                "name": stage,
                "parents": [previous] if previous else [],
                "action": f"agent.{stage}",
                "description": description,
            }
        )
        previous = step_id

    definition: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "on": {"event": "work_item.dispatched"},
        "inputs": {"task": task},
        "steps": steps,
    }
    return WorkflowDefinition(
        id=name,
        tenant_id=tenant_id,
        version="1.0.0",
        source=WorkflowSource.GENERATED,
        definition=definition,
        intent_tags=list(intent_tags or []),
        origin_task=task,
    )


async def learn_from_success(
    store: Any, wf: WorkflowDefinition, origin_task: str
) -> WorkflowDefinition:
    """Re-save a succeeded workflow as reusable, ``source='learned'`` (US-WFL-03).

    Builds a new record (the input is not mutated) tagged ``learned`` and stamped
    with the ``origin_task`` that proved it, then upserts it for future matching.
    Returns the learned definition.
    """
    learned = replace(wf, source=WorkflowSource.LEARNED, origin_task=origin_task)
    await store.upsert_workflow(learned)
    return learned


def schedule_spec(cron: str, timezone: str) -> dict[str, Any]:
    """Build a timezone-aware cron trigger spec for a workflow (US-WFL-05).

    Validates the cron field count (5 or 6 fields) and that ``timezone`` is a
    real IANA zone (via ``zoneinfo``, stdlib). Raises ``ValueError`` otherwise so
    a bad schedule fails loudly at definition time, not at the next tick.
    """
    fields = (cron or "").split()
    if len(fields) not in (5, 6):
        raise ValueError(
            f"cron expression must have 5 or 6 fields, got {len(fields)}: {cron!r}"
        )
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # unknown / unavailable zone
        raise ValueError(f"unknown timezone {timezone!r}: {exc}") from exc
    return {"type": "cron", "cron": cron, "timezone": timezone}
