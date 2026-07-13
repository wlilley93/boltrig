"""Thin Mastra-plan compiler for Boltrig v2 workflows.

Mastra owns the orchestration shape; Hatchet owns durability. This module keeps
that boundary explicit by compiling a small graph/step plan into the existing
Ultracode phased workflow contract without running anything itself.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class MastraPlanError(ValueError):
    """The Mastra-style plan cannot be compiled into a bounded workflow."""


def compile_mastra_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Compile a Mastra-style plan into the existing Ultracode workflow spec.

    Supported inputs are intentionally small:
    - ``phases``: phase objects with ``agents``/``parallel``/``steps``.
    - ``steps``: top-level phase-like steps.
    - ``graph``: ``nodes`` plus ``edges`` where phase/agent edges imply phase
      dependencies. Agent nodes may name their containing phase with ``phase``.
    """
    if not isinstance(plan, dict):
        raise MastraPlanError("mastra plan must be an object")
    phases = _compile_phases(plan)
    if not phases:
        raise MastraPlanError("mastra plan must contain phases, steps, or graph nodes")
    defaults = dict(plan.get("defaults") or {})
    for key in ("capability", "cost_tier", "model_profile", "ai_profile"):
        if key in plan and key not in defaults:
            defaults[key] = plan[key]
    return {
        "workflow_name": _name(plan),
        "goal": str(plan.get("goal") or plan.get("objective") or ""),
        "defaults": defaults,
        "phases": phases,
        "source": "mastra",
    }


def _name(plan: dict[str, Any]) -> str:
    return str(plan.get("workflow_name") or plan.get("name") or plan.get("id") or "mastra")


def _compile_phases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(plan.get("phases"), list):
        return _ordered([_phase(item, i) for i, item in enumerate(plan["phases"], start=1)])
    if isinstance(plan.get("steps"), list):
        return _ordered([_phase(item, i) for i, item in enumerate(plan["steps"], start=1)])
    graph = plan.get("graph") if isinstance(plan.get("graph"), dict) else plan
    if isinstance(graph.get("nodes"), list):
        return _compile_graph(graph)
    return []


def _compile_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    by_id = {_required_id(node, "node"): node for node in nodes}
    phase_nodes = {
        node_id: node for node_id, node in by_id.items()
        if _kind(node) in {"phase", "step"} or any(key in node for key in ("agents", "parallel"))
    }
    agent_nodes = {
        node_id: node for node_id, node in by_id.items()
        if node_id not in phase_nodes
    }
    if not phase_nodes:
        phases = []
        for index, (node_id, node) in enumerate(agent_nodes.items(), start=1):
            phases.append(_phase({"id": f"phase-{index:02d}-{node_id}", "agents": [node]}, index))
        return _ordered(_add_graph_deps(phases, graph.get("edges") or [], by_id))

    phases_by_id = {
        phase_id: _phase(node, index)
        for index, (phase_id, node) in enumerate(phase_nodes.items(), start=1)
    }
    for node_id, node in agent_nodes.items():
        phase_id = str(node.get("phase") or node.get("phase_id") or "")
        if not phase_id:
            continue
        if phase_id not in phases_by_id:
            raise MastraPlanError(f"agent '{node_id}' references unknown phase '{phase_id}'")
        phases_by_id[phase_id]["agents"].append(_agent(node, len(phases_by_id[phase_id]["agents"]) + 1))
    return _ordered(_add_graph_deps(list(phases_by_id.values()), graph.get("edges") or [], by_id))


def _phase(raw: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MastraPlanError("phase/step must be an object")
    phase_id = str(raw.get("id") or raw.get("name") or f"phase-{index:02d}")
    phase = {
        "id": phase_id,
        "name": str(raw.get("name") or phase_id),
        "depends_on": [str(item) for item in raw.get("depends_on") or raw.get("after") or []],
        "concurrency": int(raw.get("concurrency") or raw.get("max_concurrency") or 1),
        "agents": [_agent(item, i) for i, item in enumerate(_agent_items(raw), start=1)],
    }
    if not phase["agents"] and _kind(raw) not in {"phase", "step"}:
        phase["agents"] = [_agent(raw, 1)]
    if not phase["agents"]:
        raise MastraPlanError(f"phase '{phase_id}' has no agents")
    return phase


def _agent_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("agents", "parallel", "steps"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _agent(raw: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MastraPlanError("agent must be an object")
    agent_id = str(raw.get("id") or raw.get("name") or f"agent-{index:02d}")
    prompt = raw.get("prompt") or raw.get("instructions") or raw.get("objective") or raw.get("task")
    if not prompt:
        raise MastraPlanError(f"agent '{agent_id}' missing instructions/objective")
    agent = {
        "id": agent_id,
        "role": raw.get("role") or raw.get("agent") or raw.get("type") or raw.get("kind"),
        "prompt": str(prompt),
    }
    for key in (
        "capability", "skills", "prefer", "model_profile", "ai_profile",
        "repo_root", "opencode_auto", "opencode_agent", "conversation_id",
        "memory", "run_type",
    ):
        if key in raw:
            agent[key] = raw[key]
    return {key: value for key, value in agent.items() if value not in (None, "")}


def _add_graph_deps(
    phases: list[dict[str, Any]],
    edges: list[Any],
    nodes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    phase_ids = {phase["id"] for phase in phases}
    agent_to_phase: dict[str, str] = {}
    for phase in phases:
        for agent in phase["agents"]:
            agent_to_phase[agent["id"]] = phase["id"]
    deps = {phase["id"]: set(phase.get("depends_on") or []) for phase in phases}
    for raw in edges:
        src, dst = _edge(raw)
        src_phase = src if src in phase_ids else _node_phase(src, nodes, agent_to_phase)
        dst_phase = dst if dst in phase_ids else _node_phase(dst, nodes, agent_to_phase)
        if src_phase and dst_phase and src_phase != dst_phase:
            deps[dst_phase].add(src_phase)
    for phase in phases:
        phase["depends_on"] = sorted(deps[phase["id"]])
    return phases


def _ordered(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {phase["id"]: phase for phase in phases}
    indegree = {phase_id: 0 for phase_id in by_id}
    children: dict[str, list[str]] = defaultdict(list)
    for phase in phases:
        for dep in phase.get("depends_on") or []:
            if dep not in by_id:
                raise MastraPlanError(f"phase '{phase['id']}' depends on unknown phase '{dep}'")
            indegree[phase["id"]] += 1
            children[dep].append(phase["id"])
    ready = deque([phase["id"] for phase in phases if indegree[phase["id"]] == 0])
    ordered: list[dict[str, Any]] = []
    while ready:
        phase_id = ready.popleft()
        phase = by_id[phase_id]
        phase["depends_on"] = [dep for dep in phase.get("depends_on") or []]
        ordered.append(phase)
        for child in children[phase_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(ordered) != len(phases):
        raise MastraPlanError("mastra plan contains a dependency cycle")
    return ordered


def _edge(raw: Any) -> tuple[str, str]:
    if isinstance(raw, dict):
        src = raw.get("from") or raw.get("source")
        dst = raw.get("to") or raw.get("target")
    elif isinstance(raw, (list, tuple)) and len(raw) == 2:
        src, dst = raw
    else:
        raise MastraPlanError("graph edge must name from/to")
    if not src or not dst:
        raise MastraPlanError("graph edge must name from/to")
    return str(src), str(dst)


def _node_phase(
    node_id: str,
    nodes: dict[str, dict[str, Any]],
    agent_to_phase: dict[str, str],
) -> str | None:
    node = nodes.get(node_id) or {}
    return str(node.get("phase") or node.get("phase_id") or agent_to_phase.get(node_id) or "")


def _kind(raw: dict[str, Any]) -> str:
    return str(raw.get("kind") or raw.get("type") or "").lower()


def _required_id(raw: dict[str, Any], kind: str) -> str:
    value = raw.get("id")
    if not isinstance(value, str) or not value.strip():
        raise MastraPlanError(f"{kind} missing id")
    return value
