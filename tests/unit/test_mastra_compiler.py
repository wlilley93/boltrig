from __future__ import annotations

import pytest

from boltrig.fleet.mastra import MastraPlanError, compile_mastra_plan
from boltrig.fleet.ultracode import validate_workflow


def test_mastra_steps_compile_to_valid_phased_workflow():
    spec = compile_mastra_plan({
        "name": "auth-refactor",
        "goal": "Refactor auth safely.",
        "defaults": {"capability": "codex-worker", "max_total_agents": 4},
        "steps": [
            {
                "id": "discovery",
                "concurrency": 2,
                "parallel": [
                    {"id": "map", "role": "auditor", "instructions": "Map auth files."},
                    {"id": "risk", "agent": "reviewer", "task": "Find migration risks."},
                ],
            },
            {
                "id": "plan",
                "after": ["discovery"],
                "agents": [{"id": "synth", "objective": "Synthesize the plan."}],
            },
        ],
    })

    assert validate_workflow(spec)["source"] == "mastra"
    assert spec["workflow_name"] == "auth-refactor"
    assert spec["defaults"]["capability"] == "codex-worker"
    assert [phase["id"] for phase in spec["phases"]] == ["discovery", "plan"]
    assert spec["phases"][0]["agents"][0]["prompt"] == "Map auth files."
    assert spec["phases"][1]["depends_on"] == ["discovery"]


def test_mastra_graph_edges_compile_to_phase_dependencies():
    spec = compile_mastra_plan({
        "id": "graph-run",
        "goal": "Use graph-shaped orchestration.",
        "graph": {
            "nodes": [
                {"id": "implement", "type": "phase", "agents": [
                    {"id": "build", "instructions": "Implement scoped change."}
                ]},
                {"id": "discover", "type": "phase", "agents": [
                    {"id": "map", "instructions": "Map current code."}
                ]},
                {"id": "verify", "type": "agent", "phase": "implement",
                 "instructions": "Verify the patch."},
            ],
            "edges": [
                {"from": "discover", "to": "implement"},
                {"from": "map", "to": "verify"},
            ],
        },
    })

    assert [phase["id"] for phase in spec["phases"]] == ["discover", "implement"]
    assert spec["phases"][1]["depends_on"] == ["discover"]
    assert [agent["id"] for agent in spec["phases"][1]["agents"]] == ["build", "verify"]


def test_mastra_compiler_rejects_cycles_and_missing_instructions():
    with pytest.raises(MastraPlanError, match="dependency cycle"):
        compile_mastra_plan({
            "steps": [
                {"id": "a", "after": ["b"], "agents": [{"id": "aa", "task": "A"}]},
                {"id": "b", "after": ["a"], "agents": [{"id": "bb", "task": "B"}]},
            ]
        })

    with pytest.raises(MastraPlanError, match="missing instructions"):
        compile_mastra_plan({"steps": [{"id": "a", "agents": [{"id": "aa"}]}]})
