"""Checkpointed phase execution for an Ultracode run."""

from __future__ import annotations

import asyncio
from typing import Any

from .ultracode_spec import MAX_CONCURRENCY

_FINAL_CHECKPOINTS = {"completed", "degraded", "failed"}


def agent_step(phase_id: str, agent_id: str) -> str:
    return f"ultracode:{phase_id}:{agent_id}"


async def checkpoints(kernel: Any, tenant: str, run_id: str) -> dict[str, Any]:
    if not hasattr(kernel.store, "list_checkpoints"):
        return {}
    return {
        checkpoint.step: checkpoint
        for checkpoint in await kernel.store.list_checkpoints(tenant, run_id)
    }


def replayable(checkpoint: Any | None) -> bool:
    return bool(
        checkpoint
        and checkpoint.status in _FINAL_CHECKPOINTS
        and isinstance(checkpoint.output, dict)
    )


def _emit(kernel: Any, tenant_id: str, run_id: str, event: dict[str, Any]) -> None:
    relay = getattr(kernel, "events", None)
    if relay is None:
        return
    try:
        relay.publish(tenant_id, run_id, {"type": "ultracode", **event})
    except Exception:
        pass


async def _run_one_agent(
    kernel: Any,
    *,
    tenant: str,
    run_id: str,
    goal: str,
    defaults: dict[str, Any],
    phase: dict[str, Any],
    agent: dict[str, Any],
    prior: list[dict[str, Any]],
    replay: dict[str, Any],
    context_envelope: dict[str, Any],
    agent_runner: Any,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        step = agent_step(phase["id"], agent["id"])
        if replayable(replay.get(step)):
            _emit(
                kernel,
                tenant,
                run_id,
                {
                    "status": "agent_replayed",
                    "phase_id": phase["id"],
                    "agent_id": agent["id"],
                },
            )
            return dict(replay[step].output)
        _emit(
            kernel,
            tenant,
            run_id,
            {
                "status": "agent_started",
                "phase_id": phase["id"],
                "agent_id": agent["id"],
            },
        )
        record = await agent_runner(
            {
                "tenant": tenant,
                "run_id": run_id,
                "goal": goal,
                "defaults": defaults,
                "phase": phase,
                "agent": agent,
                "prior": list(prior),
                "ctx_envelope": context_envelope,
            }
        )
        _emit(
            kernel,
            tenant,
            run_id,
            {
                "status": "agent_finished",
                "phase_id": phase["id"],
                "agent_id": agent["id"],
                "degraded": record["degraded"],
            },
        )
        return record


def _phase_status(agents: list[dict[str, Any]]) -> str:
    if any(agent["status"] != "ok" for agent in agents):
        return "failed"
    if any(agent["degraded"] for agent in agents):
        return "degraded"
    return "completed"


async def _run_phase(
    kernel: Any,
    *,
    tenant: str,
    run_id: str,
    goal: str,
    defaults: dict[str, Any],
    phase: dict[str, Any],
    prior: list[dict[str, Any]],
    replay: dict[str, Any],
    context_envelope: dict[str, Any],
    agent_runner: Any,
) -> dict[str, Any]:
    phase_step = f"ultracode:{phase['id']}"
    if replayable(replay.get(phase_step)):
        record = dict(replay[phase_step].output)
        _emit(
            kernel,
            tenant,
            run_id,
            {"status": "phase_replayed", "phase_id": phase["id"]},
        )
        return record
    _emit(
        kernel,
        tenant,
        run_id,
        {"status": "phase_started", "phase_id": phase["id"]},
    )
    concurrency = max(
        1,
        min(int(phase.get("concurrency") or 1), MAX_CONCURRENCY),
    )
    semaphore = asyncio.Semaphore(concurrency)
    agents = await asyncio.gather(
        *(
            _run_one_agent(
                kernel,
                tenant=tenant,
                run_id=run_id,
                goal=goal,
                defaults=defaults,
                phase=phase,
                agent=agent,
                prior=prior,
                replay=replay,
                context_envelope=context_envelope,
                agent_runner=agent_runner,
                semaphore=semaphore,
            )
            for agent in phase["agents"]
        )
    )
    status = _phase_status(agents)
    record = {"id": phase["id"], "status": status, "agents": agents}
    if hasattr(kernel.store, "upsert_checkpoint"):
        await kernel.store.upsert_checkpoint(
            tenant,
            run_id,
            phase_step,
            status,
            output=record,
        )
    _emit(
        kernel,
        tenant,
        run_id,
        {
            "status": "phase_finished",
            "phase_id": phase["id"],
            "phase_status": status,
        },
    )
    return record


async def run_phases(
    kernel: Any,
    *,
    tenant: str,
    run_id: str,
    goal: str,
    defaults: dict[str, Any],
    phases: list[dict[str, Any]],
    context_envelope: dict[str, Any],
    agent_runner: Any,
) -> list[dict[str, Any]]:
    """Run phases in order, replaying final checkpoints and stopping on failure."""
    prior: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    replay = await checkpoints(kernel, tenant, run_id)
    for phase in phases:
        record = await _run_phase(
            kernel,
            tenant=tenant,
            run_id=run_id,
            goal=goal,
            defaults=defaults,
            phase=phase,
            prior=prior,
            replay=replay,
            context_envelope=context_envelope,
            agent_runner=agent_runner,
        )
        records.append(record)
        prior.append(record)
        if record.get("status") == "failed":
            break
    return records
