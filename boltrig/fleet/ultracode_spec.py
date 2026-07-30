"""Validation for bounded Ultracode phase plans."""

from __future__ import annotations

from typing import Any

MAX_PHASES = 20
MAX_AGENTS = 100
MAX_CONCURRENCY = 8


class UltracodeSpecError(ValueError):
    """The workflow spec is not executable as a bounded Ultracode run."""


def _require_id(item: dict[str, Any], kind: str) -> str:
    value = item.get("id")
    if not isinstance(value, str) or not value.strip():
        raise UltracodeSpecError(f"{kind} missing id")
    return value


def _workflow_limits(defaults: dict[str, Any]) -> tuple[int, int]:
    try:
        max_agents = min(
            int(defaults.get("max_total_agents") or MAX_AGENTS),
            MAX_AGENTS,
        )
        max_concurrency = min(
            int(defaults.get("max_phase_concurrency") or MAX_CONCURRENCY),
            MAX_CONCURRENCY,
        )
    except (TypeError, ValueError) as exc:
        raise UltracodeSpecError("workflow limits must be integers") from exc
    if max_agents < 1 or max_concurrency < 1:
        raise UltracodeSpecError("workflow limits must be positive")
    return max_agents, max_concurrency


def _validate_phase(
    phase: Any,
    *,
    seen_phases: set[str],
    seen_agents: set[str],
    max_concurrency: int,
) -> int:
    if not isinstance(phase, dict):
        raise UltracodeSpecError("phase must be an object")
    phase_id = _require_id(phase, "phase")
    if phase_id in seen_phases:
        raise UltracodeSpecError(f"duplicate phase id '{phase_id}'")
    deps = phase.get("depends_on") or []
    if not isinstance(deps, list):
        raise UltracodeSpecError(f"phase '{phase_id}' depends_on must be a list")
    try:
        concurrency = int(phase.get("concurrency") or 1)
    except (TypeError, ValueError) as exc:
        raise UltracodeSpecError(f"phase '{phase_id}' concurrency must be an integer") from exc
    if concurrency < 1 or concurrency > max_concurrency:
        raise UltracodeSpecError(
            f"phase '{phase_id}' concurrency exceeds max_phase_concurrency"
        )
    missing = [dependency for dependency in deps if dependency not in seen_phases]
    if missing:
        raise UltracodeSpecError(
            f"phase '{phase_id}' depends on missing/later phases: {missing}"
        )
    seen_phases.add(phase_id)
    agents = phase.get("agents")
    if not isinstance(agents, list) or not agents:
        raise UltracodeSpecError(f"phase '{phase_id}' must contain agents")
    for agent in agents:
        if not isinstance(agent, dict):
            raise UltracodeSpecError("agent must be an object")
        agent_id = f"{phase_id}.{_require_id(agent, 'agent')}"
        if agent_id in seen_agents:
            raise UltracodeSpecError(f"duplicate agent id '{agent_id}'")
        seen_agents.add(agent_id)
        if not (agent.get("prompt") or agent.get("objective")):
            raise UltracodeSpecError(f"agent '{agent_id}' missing prompt/objective")
    return len(agents)


def validate_workflow(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a bounded phased workflow spec and return a shallow copy."""
    if not isinstance(spec, dict):
        raise UltracodeSpecError("workflow must be an object")
    defaults = spec.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise UltracodeSpecError("workflow.defaults must be an object")
    max_agents, max_concurrency = _workflow_limits(defaults)
    phases = spec.get("phases")
    if not isinstance(phases, list) or not phases:
        raise UltracodeSpecError("workflow.phases must be a non-empty list")
    if len(phases) > MAX_PHASES:
        raise UltracodeSpecError("workflow has too many phases")
    seen_phases: set[str] = set()
    seen_agents: set[str] = set()
    agent_count = 0
    for phase in phases:
        agent_count += _validate_phase(
            phase,
            seen_phases=seen_phases,
            seen_agents=seen_agents,
            max_concurrency=max_concurrency,
        )
        if agent_count > max_agents:
            raise UltracodeSpecError("workflow has too many agents")
    return dict(spec)
