"""The live Hatchet workflows: a plain run and the durable HITL backbone (P1-1).

Two workflows are registered:

  * ``ping`` - a plain task, the deterministic proof that the live engine
    executes Nankle workflows end to end (worker registration -> step run ->
    result).
  * ``hitl_demo`` - the durable task that is the production durability backbone:
    it pauses on a HITL wait and resumes when the approval event arrives. The
    engine holds the durable wait, so the run survives a worker restart. (The
    durability *property* is also proven offline-of-Hatchet by the Postgres-backed
    NFR-REL-01 test; the live event-resume depends on the engine's durable-event
    wiring.)

``hatchet_sdk`` is imported defensively so importing this module is safe without
the optional [durable] extra (offline import stays clean). The model + context
types are module-level so the SDK can resolve task annotations. This module is in
the fleet layer; the kernel and models import nothing from it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel


# The HITL approval event key. Correlation to a specific run is by SCOPE
# (the run key), not by baking the key into the event name - that is how Hatchet
# routes a user event to one durable wait.
APPROVAL_EVENT_KEY = "nankle:approval"


class HitlInput(BaseModel):
    run_key: str


class PingInput(BaseModel):
    value: int = 1


try:  # module-level so durable_task's get_type_hints can resolve the annotation
    from hatchet_sdk import Context, DurableContext
except Exception:  # offline / no [durable] extra: keep the module import-safe
    Context = Any  # type: ignore[assignment,misc]
    DurableContext = Any  # type: ignore[assignment,misc]


def build_hatchet_app() -> tuple[Any, dict[str, Any]]:
    """Build the Hatchet client + the Nankle workflows.

    The client reads HATCHET_CLIENT_TOKEN / HATCHET_CLIENT_TLS_STRATEGY /
    HATCHET_CLIENT_HOST_PORT from the environment. Returns
    ``(hatchet, {"ping": ..., "hitl": ...})``.
    """
    from hatchet_sdk import Hatchet, UserEventCondition

    hatchet = Hatchet()

    @hatchet.task(name="nankle-ping", input_validator=PingInput)
    def ping(inp: PingInput, ctx: Context) -> dict:
        return {"pong": True, "doubled": inp.value * 2}

    @hatchet.durable_task(
        name="nankle-hitl-demo",
        input_validator=HitlInput,
        # a HITL pause can last arbitrarily long; the durable wait must not be
        # killed by the default 60s execution timeout (NFR-REL-01).
        execution_timeout=timedelta(hours=24),
        schedule_timeout=timedelta(hours=24),
    )
    async def hitl_demo(inp: HitlInput, ctx: DurableContext) -> dict:
        # Durable pause: block until the approval event for this run arrives. The
        # event is correlated to THIS run by scope (a fixed key + per-run scope),
        # which is how Hatchet routes a user event to a specific durable wait. The
        # engine persists this wait, so a worker restart resumes the same run.
        await ctx.aio_wait_for(
            f"approval-{inp.run_key}",
            UserEventCondition(
                event_key=APPROVAL_EVENT_KEY,
                scope=inp.run_key,
                expression="true",
                consider_events_since=datetime.now(timezone.utc) - timedelta(minutes=10),
            ),
        )
        return {"resumed": True, "key": inp.run_key}

    return hatchet, {"ping": ping, "hitl": hitl_demo}


async def approve(hatchet: Any, run_key: str, decision: str = "approve") -> None:
    """Push the approval event that resumes a paused durable HITL run, correlated
    to the run by scope. This is what a kernel HITL approval triggers in
    production to resume the Hatchet run."""
    from hatchet_sdk import PushEventOptions

    await hatchet.event.aio_push(
        APPROVAL_EVENT_KEY,
        {"decision": decision, "run_key": run_key},
        options=PushEventOptions(scope=run_key),
    )
