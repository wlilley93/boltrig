"""Deterministic workflow generation and learning (US-WFL-02/03/05).

When no precreated workflow matches an intent, the fleet synthesises one. The
synthesis is DETERMINISTIC and offline: no LLM is called (mirrors the adapter
generator's contract). A generated workflow is a fixed, linear Hatchet-style
pipeline (understand -> plan -> execute -> verify -> report). When such a run
succeeds, :func:`learn_from_success` re-saves it as ``source='learned'`` so the
library can reuse it next time (US-WFL-03).

NONE OF THAT RUNS. `select_or_generate_workflow` has no production caller and
`learn_from_success` is gated on ``GENERATED_WORKFLOW_KEY``, which nothing under
``boltrig/`` writes, so neither the retrieval half nor the learning half has ever
fired. This module survives under
[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001, waived against the Principal
question at ``docs/decisions/0019-route-by-intent-is-the-principals.md``: should
the pump route an unaddressed item by intent at all? On expiry without an answer,
retire. Do not describe this loop as live: a court was told it was, because the
code existed and had callers, and no gate could contradict it.

:func:`schedule_spec` builds a timezone-aware cron trigger spec (US-WFL-05).
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from zoneinfo import ZoneInfo

from boltrig.models import WorkflowDefinition, WorkflowSource

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
    task: str, intent_tags: list[str], tenant_id: str,
    *, workspace_id: str | None = None,
) -> WorkflowDefinition:
    """Build a deterministic linear workflow for ``task`` (US-WFL-02).

    The ``definition`` is a Hatchet-style spec dict: a named workflow whose steps
    form a single dependency line. ``source`` is ``generated`` and no LLM is
    involved, so the same task always yields the same spec.

    ``workspace_id`` stamps the caller's ACTIVE workspace ([2026] VJS-COUNTY 8, D2)
    so the synthesised workflow - and any workflow later learned from it - inherits
    the scope of the run that produced it. None (the default) means org-wide, so an
    existing caller with no active workspace synthesises exactly as before.
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
        workspace_id=workspace_id,
    )


async def learn_from_success(
    store: Any, wf: WorkflowDefinition, origin_task: str
) -> WorkflowDefinition:
    """Re-save a succeeded workflow as reusable, ``source='learned'`` (US-WFL-03).

    Builds a new record (the input is not mutated) tagged ``learned`` and stamped
    with the ``origin_task`` that proved it, then upserts it for future matching.
    Returns the learned definition. The learned workflow INHERITS the ``workspace_id``
    of the workflow that produced it ([2026] VJS-COUNTY 8, D2) - ``replace`` carries
    every unchanged field forward - so a workspace-scoped run learns a workspace-
    scoped workflow, and an org-wide (None) run learns an org-wide one. Learning
    never widens scope or authority (COUNTY 5): only provenance changes.

    Reserved for engine plan Phase 3 (wired into run completion to save learned
    workflows).
    """
    learned = replace(wf, source=WorkflowSource.LEARNED, origin_task=origin_task)
    await store.upsert_workflow(learned)
    return learned


async def select_or_generate_workflow(
    store: Any,
    task: str,
    intent_tags: list[str],
    tenant_id: str,
    *,
    runtime: Any | None = None,
    workspace_id: str | None = None,
) -> WorkflowDefinition:
    """Prefer a matched (learned/precreated/generated) workflow, else synthesise.

    The flywheel's retrieval half (Phase 3, US-WFL-04): consult the library FIRST
    so a workflow whose intent overlaps the request - including one saved by
    :func:`learn_from_success` after a prior success - is reused instead of
    synthesised again. When nothing overlaps (an empty or non-matching library)
    ``match`` returns ``None`` and we fall back to synthesis.

    "Behaviour is unchanged today and improves as the library fills" is what this
    said until 2026-07-27, and behaviour is unchanged today for a reason that
    sentence did not give: this function has no production caller, so nothing here
    improves as anything fills.

    Workspace-scoped ([2026] VJS-COUNTY 8, D2): the caller's active ``workspace_id``
    both narrows the library lookup (match returns org-wide OR own-workspace
    workflows only, never another workspace's) and stamps a freshly synthesised
    workflow, so a run inside a workspace reuses/creates within that workspace while
    a run with no active workspace (None) sees + creates only org-wide workflows,
    exactly as before.
    """
    from .library import WorkflowLibrary  # local import: no package-load cycle

    library = WorkflowLibrary(store)
    matched = await library.match(
        tenant_id, list(intent_tags or []), active_workspace_id=workspace_id
    )
    if matched is not None:
        return matched
    return await generate_workflow_reasoned(
        task, intent_tags, tenant_id, runtime=runtime, workspace_id=workspace_id
    )


def _extract_steps(result: Any) -> list[dict[str, Any]]:
    """Pull a proposed step list out of a runtime result (output or JSON summary)."""
    output = getattr(result, "output", None) or {}
    if isinstance(output, dict) and isinstance(output.get("steps"), list):
        return [s for s in output["steps"] if isinstance(s, dict)]
    summary = getattr(result, "summary", "") or ""
    try:
        import json

        parsed = json.loads(summary)
        if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
            return [s for s in parsed["steps"] if isinstance(s, dict)]
    except Exception:
        pass
    return []


async def generate_workflow_reasoned(
    task: str, intent_tags: list[str], tenant_id: str, *,
    runtime: Any | None = None, workspace_id: str | None = None,
) -> WorkflowDefinition:
    """Synthesise a workflow, optionally via a reasoning runtime (US-WFL-02).

    When a ``runtime`` is supplied it is asked to propose ordered steps; the
    proposal is validated and compiled into a Hatchet-style spec marked
    ``synthesis: reasoned``. With no runtime, an unusable proposal, or any failure
    (offline, no model), it falls back to the deterministic linear pipeline
    (:func:`generate_workflow`), so synthesis never crashes the fleet (P9).

    ``workspace_id`` (the caller's active workspace, [2026] VJS-COUNTY 8, D2) is
    stamped on the synthesised workflow on every path - reasoned and the
    deterministic fallbacks - so scope is inherited regardless of how synthesis
    resolves. None means org-wide (backward-compat).
    """
    if runtime is None:
        return generate_workflow(task, intent_tags, tenant_id, workspace_id=workspace_id)
    try:
        from boltrig.models import InvocationContext

        prompt = (
            f"Propose ordered workflow steps for this task: {task}\n"
            'Return JSON only: {"steps":[{"name":"...","description":"..."}]}'
        )
        result = await runtime.run(
            prompt,
            InvocationContext(tenant_id=tenant_id, workspace_id=workspace_id),
            tools=[],
        )
        proposed = _extract_steps(result)
        if not proposed:
            return generate_workflow(task, intent_tags, tenant_id, workspace_id=workspace_id)
    except Exception:
        return generate_workflow(task, intent_tags, tenant_id, workspace_id=workspace_id)

    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for index, item in enumerate(proposed, start=1):
        stage = _slug(str(item.get("name", f"step{index}")))
        step_id = f"step-{index}-{stage}"
        steps.append(
            {
                "id": step_id,
                "name": item.get("name", stage),
                "parents": [previous] if previous else [],
                "action": f"agent.{stage}",
                "description": str(item.get("description", "")),
            }
        )
        previous = step_id

    name = f"gen-{_slug(task)}"
    definition = {
        "name": name,
        "version": "1.0.0",
        "on": {"event": "work_item.dispatched"},
        "inputs": {"task": task},
        "steps": steps,
        "synthesis": "reasoned",
    }
    return WorkflowDefinition(
        id=name,
        tenant_id=tenant_id,
        version="1.0.0",
        source=WorkflowSource.GENERATED,
        definition=definition,
        intent_tags=list(intent_tags or []),
        origin_task=task,
        workspace_id=workspace_id,
    )


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
