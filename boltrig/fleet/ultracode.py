"""Boltrig v2 phased OpenCode workflow runner.

This is the durable workflow spine for dynamic phase/agent plans. It validates a
pure-data workflow spec, runs phases in dependency order, and executes each agent
through ``Spawner.spawn`` so budget, audit, degraded honesty, and runtime routing
stay on the existing fleet path.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from boltrig.models import GrantSet, InvocationContext, TenantIsolation

from .prompt_stack import wrap_untrusted
from .spawn import build_spawner
from .ultracode_memory import memory_prompt, recall_memory, remember_run_summary

_MAX_PHASES = 20
_MAX_AGENTS = 100
_MAX_CONCURRENCY = 8
_FINAL_CHECKPOINTS = {"completed", "degraded", "failed"}

AgentRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class UltracodeSpecError(ValueError):
    """The workflow spec is not executable as a bounded Ultracode run."""


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


def _require_id(item: dict[str, Any], kind: str) -> str:
    value = item.get("id")
    if not isinstance(value, str) or not value.strip():
        raise UltracodeSpecError(f"{kind} missing id")
    return value


def validate_workflow(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a bounded phased workflow spec and return a shallow copy."""
    if not isinstance(spec, dict):
        raise UltracodeSpecError("workflow must be an object")
    defaults = spec.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise UltracodeSpecError("workflow.defaults must be an object")
    try:
        max_agents = min(int(defaults.get("max_total_agents") or _MAX_AGENTS), _MAX_AGENTS)
        max_concurrency = min(
            int(defaults.get("max_phase_concurrency") or _MAX_CONCURRENCY),
            _MAX_CONCURRENCY,
        )
    except (TypeError, ValueError) as exc:
        raise UltracodeSpecError("workflow limits must be integers") from exc
    if max_agents < 1 or max_concurrency < 1:
        raise UltracodeSpecError("workflow limits must be positive")
    phases = spec.get("phases")
    if not isinstance(phases, list) or not phases:
        raise UltracodeSpecError("workflow.phases must be a non-empty list")
    if len(phases) > _MAX_PHASES:
        raise UltracodeSpecError("workflow has too many phases")

    seen_phases: set[str] = set()
    seen_agents: set[str] = set()
    agent_count = 0
    for phase in phases:
        if not isinstance(phase, dict):
            raise UltracodeSpecError("phase must be an object")
        phase_id = _require_id(phase, "phase")
        if phase_id in seen_phases:
            raise UltracodeSpecError(f"duplicate phase id '{phase_id}'")
        deps = phase.get("depends_on") or []
        if not isinstance(deps, list):
            raise UltracodeSpecError(f"phase '{phase_id}' depends_on must be a list")
        try:
            phase_concurrency = int(phase.get("concurrency") or 1)
        except (TypeError, ValueError) as exc:
            raise UltracodeSpecError(f"phase '{phase_id}' concurrency must be an integer") from exc
        if phase_concurrency < 1 or phase_concurrency > max_concurrency:
            raise UltracodeSpecError(
                f"phase '{phase_id}' concurrency exceeds max_phase_concurrency"
            )
        missing = [dep for dep in deps if dep not in seen_phases]
        if missing:
            raise UltracodeSpecError(
                f"phase '{phase_id}' depends on missing/later phases: {missing}"
            )
        seen_phases.add(phase_id)

        agents = phase.get("agents")
        if not isinstance(agents, list) or not agents:
            raise UltracodeSpecError(f"phase '{phase_id}' must contain agents")
        agent_count += len(agents)
        if agent_count > max_agents:
            raise UltracodeSpecError("workflow has too many agents")
        for agent in agents:
            if not isinstance(agent, dict):
                raise UltracodeSpecError("agent must be an object")
            agent_id = f"{phase_id}.{_require_id(agent, 'agent')}"
            if agent_id in seen_agents:
                raise UltracodeSpecError(f"duplicate agent id '{agent_id}'")
            seen_agents.add(agent_id)
            if not (agent.get("prompt") or agent.get("objective")):
                raise UltracodeSpecError(f"agent '{agent_id}' missing prompt/objective")
    return dict(spec)


def _emit(kernel: Any, tenant_id: str, run_id: str, event: dict[str, Any]) -> None:
    relay = getattr(kernel, "events", None)
    if relay is None:
        return
    try:
        relay.publish(tenant_id, run_id, {"type": "ultracode", **event})
    except Exception:
        pass


def _phase_step(phase_id: str) -> str:
    return f"ultracode:{phase_id}"


def _agent_step(phase_id: str, agent_id: str) -> str:
    return f"ultracode:{phase_id}:{agent_id}"


async def _checkpoints(kernel: Any, tenant: str, run_id: str) -> dict[str, Any]:
    if not hasattr(kernel.store, "list_checkpoints"):
        return {}
    return {c.step: c for c in await kernel.store.list_checkpoints(tenant, run_id)}


def _is_replayable(checkpoint: Any | None) -> bool:
    return bool(
        checkpoint
        and checkpoint.status in _FINAL_CHECKPOINTS
        and isinstance(checkpoint.output, dict)
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
        "repo_root", "opencode_auto", "opencode_agent", "conversation_id",
        "model_profile", "ai_profile", "model_profiles",
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
    return {"id": agent["id"], "status": result["status"], "degraded": result["degraded"],
            "result": result}


async def run_ultracode_agent_body(kernel: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run one phase-agent from pure task data and checkpoint its output."""
    ctx = _context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    if tenant != ctx.tenant_id:
        raise TenantIsolation(f"task payload tenant '{tenant}' != envelope tenant '{ctx.tenant_id}'")
    run_id = payload["run_id"]
    phase = dict(payload["phase"])
    agent = dict(payload["agent"])
    step = _agent_step(phase["id"], agent["id"])
    prior = await _checkpoints(kernel, tenant, run_id)
    if _is_replayable(prior.get(step)):
        return dict(prior[step].output)
    if hasattr(kernel.store, "upsert_checkpoint"):
        await kernel.store.upsert_checkpoint(
            tenant, run_id, step, "started",
            output={"phase_id": phase["id"], "agent_id": agent["id"]},
        )
    spawner = build_spawner(kernel)
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
    agent_runner: AgentRunner | None = None,
) -> dict[str, Any]:
    """Run a phased Ultracode workflow from pure queue data."""
    ctx = _context_from_envelope(payload["ctx_envelope"])
    tenant = payload["tenant"]
    if tenant != ctx.tenant_id:
        raise TenantIsolation(f"task payload tenant '{tenant}' != envelope tenant '{ctx.tenant_id}'")
    run_id = payload.get("run_id") or ctx.run_id or uuid.uuid4().hex
    workflow = payload.get("workflow")
    if payload.get("mastra_plan"):
        from .mastra import compile_mastra_plan

        workflow = compile_mastra_plan(payload["mastra_plan"])
    spec = validate_workflow(workflow)
    defaults = dict(spec.get("defaults") or {})
    goal = str(spec.get("goal") or payload.get("goal") or "")
    prior: list[dict[str, Any]] = []
    phase_records: list[dict[str, Any]] = []
    replay = await _checkpoints(kernel, tenant, run_id)

    async def inline_agent_runner(agent_payload: dict[str, Any]) -> dict[str, Any]:
        return await run_ultracode_agent_body(kernel, agent_payload)

    for phase in spec["phases"]:
        phase_step = _phase_step(phase["id"])
        if _is_replayable(replay.get(phase_step)):
            phase_record = dict(replay[phase_step].output)
            phase_records.append(phase_record)
            prior.append(phase_record)
            _emit(kernel, tenant, run_id, {"status": "phase_replayed", "phase_id": phase["id"]})
            if phase_record.get("status") == "failed":
                break
            continue
        _emit(kernel, tenant, run_id, {"status": "phase_started", "phase_id": phase["id"]})
        concurrency = max(1, min(int(phase.get("concurrency") or 1), _MAX_CONCURRENCY))
        semaphore = asyncio.Semaphore(concurrency)

        async def guarded(agent: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                step = _agent_step(phase["id"], agent["id"])
                if _is_replayable(replay.get(step)):
                    _emit(kernel, tenant, run_id, {"status": "agent_replayed", "phase_id": phase["id"],
                                          "agent_id": agent["id"]})
                    return dict(replay[step].output)
                _emit(kernel, tenant, run_id, {"status": "agent_started", "phase_id": phase["id"],
                                      "agent_id": agent["id"]})
                agent_payload = {
                    "tenant": tenant,
                    "run_id": run_id,
                    "goal": goal,
                    "defaults": defaults,
                    "phase": phase,
                    "agent": agent,
                    "prior": list(prior),
                    "ctx_envelope": payload["ctx_envelope"],
                }
                run_agent = agent_runner
                if run_agent is None:
                    run_agent = inline_agent_runner
                record = await run_agent(agent_payload)
                _emit(kernel, tenant, run_id, {"status": "agent_finished", "phase_id": phase["id"],
                                      "agent_id": agent["id"], "degraded": record["degraded"]})
                return record

        agents = await asyncio.gather(*(guarded(agent) for agent in phase["agents"]))
        phase_status = "completed"
        if any(agent["status"] != "ok" for agent in agents):
            phase_status = "failed"
        elif any(agent["degraded"] for agent in agents):
            phase_status = "degraded"
        phase_record = {"id": phase["id"], "status": phase_status, "agents": agents}
        phase_records.append(phase_record)
        prior.append(phase_record)
        if hasattr(kernel.store, "upsert_checkpoint"):
            await kernel.store.upsert_checkpoint(
                tenant, run_id, phase_step, phase_status, output=phase_record
            )
        replay[phase_step] = type("_Checkpoint", (), {"status": phase_status, "output": phase_record})()
        _emit(kernel, tenant, run_id, {"status": "phase_finished", "phase_id": phase["id"],
                              "phase_status": phase_status})
        if phase_status == "failed":
            break

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
