"""Post-run reflection: one lesson per terminal work item, and its evidence.

Split from ``pump.py`` at the size ratchet, and the seam is real: the pump
decides WHEN a run is terminal; this module decides what reflection does about
it and how its outcomes are counted (#29 - the counters feed the `reflection`
receipt ``pump_progress`` publishes per window, which is what makes "never
written a row" decidable as idle / broken / off).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from boltrig.models import WorkItem

from .authority import reflection_context

log = logging.getLogger("boltrig.fleet.pump")


def reflection_lesson(item: WorkItem, terminal_status: str, outcome: dict) -> str:
    """A short, deterministic lesson distilled from an outcome (Phase 3, US-WFL-07).

    Deliberately a fixed template, not a model call, so reflection is cheap and
    reproducible. The content is bland by construction so it clears the memory
    adapter's secret / injection screen, and it is stored THROUGH the chokepoint,
    so that screen still runs on it (it is never bypassed)."""
    score = outcome.get("score")
    return (
        f"Lesson from work item {item.id} ({item.source}): the task "
        f"'{item.intent}' reached {terminal_status} with outcome score {score} "
        f"(degraded={bool(item.degraded)})."
    )


async def reflect_terminal_item(
    pump: Any, item: WorkItem, run_id: str, terminal_status: str
) -> None:
    """Distil one lesson and store it via the memory verb, best-effort (US-WFL-07).

    Governed: the write goes through ``kernel.invoke`` (the one chokepoint), so the
    memory adapter's scope + secret + injection screens all run on it. Provenance is the
    run id (``source_ref``) and work item id. OFF unless enabled, and any reflection
    failure is swallowed so it can never fail the run (P9). Carries the narrow reflection
    seat, NOT the item's execution context (``authority.REFLECTION_GRANTS``)."""
    if not pump._reflect_enabled or pump._kernel is None:
        return
    outcome = (item.result or {}).get("outcome") or {}
    lesson = reflection_lesson(item, terminal_status, outcome)
    pump.reflection_window["attempted"] += 1
    try:
        ctx = reflection_context(item, run_id)
        await pump._kernel.invoke(
            "memory", "memory.remember",
            {
                "content": lesson,
                "kind": "lesson",
                "source_kind": "reflection",
                "source_ref": run_id,
            },
            ctx,
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # reflection is best-effort; never fail the run (P9)
        pump.reflection_window["failed"] += 1
        # WARNING, not DEBUG (#29): the swallow is right - a reflection
        # failure must never fail the run - but a swallow at DEBUG made
        # "broken" indistinguishable from "idle" for a month. The receipt
        # carries the count; this line carries the WHY.
        log.warning("reflection failed for %s; continuing", item.id, exc_info=True)
    else:
        pump.reflection_window["written"] += 1
