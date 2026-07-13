"""Hatchet task wiring for Boltrig v2 Ultracode runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

TASK_ULTRACODE_RUN = "boltrig-ultracode-run"
TASK_ULTRACODE_AGENT = "boltrig-ultracode-agent"


class UltracodeRunInput(BaseModel):
    """Pure-data input for a phased OpenCode/Ultracode workflow."""

    tenant: str
    workflow: dict[str, Any] = Field(default_factory=dict)
    mastra_plan: dict[str, Any] | None = None
    ctx_envelope: dict[str, Any]
    run_id: str | None = None
    goal: str | None = None


class UltracodeAgentInput(BaseModel):
    """Pure-data input for one Ultracode phase-agent child task."""

    tenant: str
    run_id: str
    goal: str = ""
    defaults: dict[str, Any] = Field(default_factory=dict)
    phase: dict[str, Any]
    agent: dict[str, Any]
    prior: list[dict[str, Any]] = Field(default_factory=list)
    ctx_envelope: dict[str, Any]


async def ultracode_run_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a Boltrig v2 phased agent workflow through the fleet spawner."""
    from boltrig.fleet.ultracode import run_ultracode_body

    return await run_ultracode_body(kernel, payload)


async def ultracode_agent_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one Ultracode phase-agent child body through the fleet spawner."""
    from boltrig.fleet.ultracode import run_ultracode_agent_body

    return await run_ultracode_agent_body(kernel, payload)


async def _hatchet_ultracode_agent_runner(
    workflow: Any,
    payload: dict[str, Any],
    inline_runner: Any,
) -> dict[str, Any]:
    """Run one Ultracode agent through Hatchet's public child-run API."""
    run = getattr(workflow, "aio_run", None)
    if not callable(run):
        return await inline_runner(payload)
    return await run(payload)


def register_local_ultracode_tasks(executor: Any, kernel: Any) -> None:
    """Register Ultracode parent/child bodies on the local executor seam."""
    register = getattr(executor, "register_task", None)
    if register is None:
        return

    async def _ultracode_agent(payload: dict[str, Any]) -> dict[str, Any]:
        return await ultracode_agent_body(kernel, payload)

    async def _ultracode_run(payload: dict[str, Any]) -> dict[str, Any]:
        from boltrig.fleet.ultracode import run_ultracode_body

        async def _agent_runner(agent_payload: dict[str, Any]) -> dict[str, Any]:
            phase = agent_payload["phase"]["id"]
            agent = agent_payload["agent"]["id"]
            return await executor.run_step(
                f"task:{TASK_ULTRACODE_AGENT}:{phase}:{agent}",
                _ultracode_agent,
                agent_payload,
                run_id=agent_payload.get("run_id"),
            )

        return await run_ultracode_body(kernel, payload, agent_runner=_agent_runner)

    register(TASK_ULTRACODE_RUN, _ultracode_run)
    register(TASK_ULTRACODE_AGENT, _ultracode_agent)


def register_hatchet_ultracode_tasks(
    hatchet: Any,
    resources: Any,
) -> dict[str, Any]:
    """Register Ultracode parent/child workflows on a live Hatchet client."""

    @hatchet.task(name=TASK_ULTRACODE_AGENT, input_validator=UltracodeAgentInput)
    async def ultracode_agent(inp: UltracodeAgentInput, ctx) -> dict:
        res = await resources()
        return await ultracode_agent_body(res["kernel"], inp.model_dump())

    @hatchet.durable_task(
        name=TASK_ULTRACODE_RUN,
        input_validator=UltracodeRunInput,
        execution_timeout=timedelta(hours=24),
        schedule_timeout=timedelta(hours=24),
    )
    async def ultracode_run(inp: UltracodeRunInput, ctx) -> dict:
        res = await resources()

        async def _agent_runner(agent_payload: dict[str, Any]) -> dict[str, Any]:
            async def _inline(payload: dict[str, Any]) -> dict[str, Any]:
                return await ultracode_agent_body(res["kernel"], payload)

            return await _hatchet_ultracode_agent_runner(
                ultracode_agent, agent_payload, _inline
            )

        from boltrig.fleet.ultracode import run_ultracode_body

        return await run_ultracode_body(
            res["kernel"], inp.model_dump(), agent_runner=_agent_runner
        )

    return {
        TASK_ULTRACODE_RUN: ultracode_run,
        TASK_ULTRACODE_AGENT: ultracode_agent,
    }
