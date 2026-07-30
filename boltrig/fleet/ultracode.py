"""Boltrig v2 phased OpenCode workflow runner.

This is the durable workflow spine for dynamic phase/agent plans. It validates a
pure-data workflow spec, runs phases in dependency order, and executes each agent
through ``Spawner.spawn`` so budget, audit, degraded honesty, and runtime routing
stay on the existing fleet path.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from boltrig.models import GrantSet, InvocationContext, TenantIsolation

from .prompt_stack import wrap_untrusted
from .ultracode_memory import memory_prompt, recall_memory, remember_run_summary
from .ultracode_phases import agent_step as _agent_step
from .ultracode_phases import checkpoints as _checkpoints
from .ultracode_phases import replayable as _is_replayable
from .ultracode_phases import run_phases
from .ultracode_spec import UltracodeSpecError as UltracodeSpecError
from .ultracode_spec import validate_workflow as validate_workflow

AgentRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _context_from_envelope(env: dict[str, Any]) -> InvocationContext:
    grants = env.get("grants") or {}
    return InvocationContext(
        tenant_id=env["tenant_id"],
        run_id=env.get("run_id"),
        parent_run_id=env.get("parent_run_id"),
        depth=int(env.get("depth", 0)),
        on_behalf_of=env.get("on_behalf_of"),
        workspace_id=env.get("workspace_id"),
        ip_address=env.get("ip_address"),
        user_agent=env.get("user_agent"),
        grants=GrantSet.of(list(grants.get("allow") or []), list(grants.get("deny") or [])),
        actor=env.get("actor", "unknown"),
        actor_tier=env.get("actor_tier", "ephemeral"),
        skills_loaded=tuple(env.get("skills_loaded") or ()),
        extra=dict(env.get("extra") or {}),
    )


def _prompt(
    goal: str,
    phase: dict[str, Any],
    agent: dict[str, Any],
    prior: list[dict],
    memory: str = "",
) -> str:
    parts = [
        f"Goal:\n{goal}",
        f"Phase:\n{phase.get('name') or phase['id']}",
        f"Agent:\n{agent.get('role') or agent['id']}",
        f"Objective:\n{agent.get('prompt') or agent.get('objective')}",
    ]
    if memory:
        parts.append(f"Scoped memory:\n{memory}")
    if prior:
        # Prior phase outputs are model-generated, hence untrusted: they reach the
        # next phase's model only inside the M1 envelope, exactly like memory recall
        # (ultracode_memory.memory_prompt), never as bare prompt text (SEC-72).
        wrapped = "\n".join(
            wrap_untrusted(
                "ultracode.prior_output",
                str(entry.get("id") or "agent"),
                str(entry.get("result") or entry),
            )
            for entry in prior
        )
        parts.append(f"Prior phase outputs:\n{wrapped}")
    return "\n\n".join(parts)


def _ctx_for(base: InvocationContext, run_id: str, phase: dict, agent: dict) -> InvocationContext:
    extra = dict(base.extra)
    extra.update(
        {
            "ultracode_run_id": run_id,
            "ultracode_phase_id": phase["id"],
            "ultracode_agent_id": agent["id"],
            "opencode_title": f"{phase['id']}:{agent['id']}",
        }
    )
    for key in (
        "repo_root",
        "opencode_auto",
        "opencode_agent",
        "conversation_id",
        "model_profile",
        "ai_profile",
        "model_profiles",
    ):
        if key in agent:
            extra[key] = agent[key]
    return replace(base, run_id=run_id, extra=extra)


async def _run_agent(
    spawner: Any,
    tenant: str,
    run_id: str,
    goal: str,
    defaults: dict[str, Any],
    phase: dict[str, Any],
    agent: dict[str, Any],
    context: InvocationContext,
    prior: list[dict[str, Any]],
    memory: str = "",
) -> dict[str, Any]:
    prefer = dict(agent.get("prefer") or {})
    capability = agent.get("capability") or defaults.get("capability")
    if capability:
        prefer["capability"] = capability
    if defaults.get("cost_tier") and "cost_tier" not in prefer:
        prefer["cost_tier"] = defaults["cost_tier"]
    agent_context = dict(agent)
    for key in ("model_profile", "ai_profile", "model_profiles"):
        if key in defaults and key not in agent_context:
            agent_context[key] = defaults[key]
    result = await spawner.spawn(
        tenant,
        _prompt(goal, phase, agent, prior, memory),
        list(agent.get("skills") or []),
        prefer,
        _ctx_for(context, run_id, phase, agent_context),
        partial_on_budget=False,
        grant_ceiling=context.grants if isinstance(context.grants, GrantSet) else None,
    )
    return {
        "id": agent["id"],
        "status": result["status"],
        "degraded": result["degraded"],
        "result": result,
    }


async def run_ultracode_agent_body(
    kernel: Any,
    payload: dict[str, Any],
    *,
    spawner: Any | None,
) -> dict[str, Any]:
    """Run one phase-agent through its composition-owned spawner."""
    ctx = _context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    if tenant != ctx.tenant_id:
        raise TenantIsolation(
            f"task payload tenant '{tenant}' != envelope tenant '{ctx.tenant_id}'"
        )
    run_id = payload["run_id"]
    phase = dict(payload["phase"])
    agent = dict(payload["agent"])
    step = _agent_step(phase["id"], agent["id"])
    prior = await _checkpoints(kernel, tenant, run_id)
    if _is_replayable(prior.get(step)):
        return dict(prior[step].output)
    if hasattr(kernel.store, "upsert_checkpoint"):
        await kernel.store.upsert_checkpoint(
            tenant,
            run_id,
            step,
            "started",
            output={"phase_id": phase["id"], "agent_id": agent["id"]},
        )
    if spawner is None:
        raise RuntimeError("no composition-owned spawner wired for Ultracode agent")
    memory = await recall_memory(
        kernel,
        tenant,
        ctx,
        dict(payload.get("defaults") or {}),
        agent,
    )
    record = await _run_agent(
        spawner,
        tenant,
        run_id,
        str(payload.get("goal") or ""),
        dict(payload.get("defaults") or {}),
        phase,
        agent,
        ctx,
        list(payload.get("prior") or []),
        memory_prompt(memory),
    )
    status = "failed"
    if record["status"] == "ok":
        status = "degraded" if record["degraded"] else "completed"
    if hasattr(kernel.store, "upsert_checkpoint"):
        await kernel.store.upsert_checkpoint(tenant, run_id, step, status, output=record)
    return record


async def run_ultracode_body(
    kernel: Any,
    payload: dict[str, Any],
    *,
    spawner: Any | None = None,
    agent_runner: AgentRunner | None = None,
) -> dict[str, Any]:
    """Run a phased Ultracode workflow from pure queue data.

    Inline execution requires the composition-owned ``spawner``. Durable
    callers may instead supply ``agent_runner``; its registered child body must
    carry that same spawner. Neither path constructs runtime authority here.
    """
    ctx = _context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    if tenant != ctx.tenant_id:
        raise TenantIsolation(
            f"task payload tenant '{tenant}' != envelope tenant '{ctx.tenant_id}'"
        )
    run_id = payload.get("run_id") or ctx.run_id or uuid.uuid4().hex
    workflow = payload.get("workflow")
    if payload.get("mastra_plan"):
        from .mastra import compile_mastra_plan

        workflow = compile_mastra_plan(payload["mastra_plan"])
    spec = validate_workflow(workflow)
    defaults = dict(spec.get("defaults") or {})
    goal = str(spec.get("goal") or payload.get("goal") or "")
    async def inline_agent_runner(agent_payload: dict[str, Any]) -> dict[str, Any]:
        return await run_ultracode_agent_body(
            kernel,
            agent_payload,
            spawner=spawner,
        )
    phase_records = await run_phases(
        kernel,
        tenant=tenant,
        run_id=run_id,
        goal=goal,
        defaults=defaults,
        phases=spec["phases"],
        context_envelope=payload["ctx_envelope"],
        agent_runner=agent_runner or inline_agent_runner,
    )

    overall = "completed"
    if any(phase["status"] == "failed" for phase in phase_records):
        overall = "failed"
    elif any(phase["status"] == "degraded" for phase in phase_records):
        overall = "degraded"
    record = {
        "run_id": run_id,
        "workflow_name": spec.get("workflow_name") or "ultracode",
        "tenant_id": tenant,
        "status": overall,
        "phases": phase_records,
    }
    await remember_run_summary(kernel, tenant, ctx, record, defaults)
    return record
