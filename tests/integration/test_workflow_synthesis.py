"""Workflow synthesis: reasoning path with a deterministic offline fallback (US-WFL-02)."""

import pytest

from nankle.fleet.result import AgentResult
from nankle.workflows.generator import generate_workflow_reasoned

T = "acme"
_LINEAR = ["understand", "plan", "execute", "verify", "report"]


class _StepRuntime:
    """A runtime that proposes structured steps (the reasoning path)."""

    async def run(self, prompt, context, *, tools):
        return AgentResult(
            ok=True,
            output={"steps": [
                {"name": "gather", "description": "collect inputs"},
                {"name": "decide", "description": "choose an action"},
            ]},
            summary="proposed",
        )


class _EmptyRuntime:
    """A runtime that proposes nothing usable (forces the fallback)."""

    async def run(self, prompt, context, *, tools):
        return AgentResult(ok=True, output={}, summary="no json here")


@pytest.mark.invariant("US-WFL-02")
async def test_reasoned_synthesis_uses_runtime_steps():
    wf = await generate_workflow_reasoned("triage", ["x"], T, runtime=_StepRuntime())
    assert [s["name"] for s in wf.definition["steps"]] == ["gather", "decide"]
    assert wf.definition.get("synthesis") == "reasoned"


@pytest.mark.invariant("US-WFL-02")
async def test_reasoned_falls_back_to_deterministic_offline():
    # an unusable proposal (or offline) -> the deterministic linear pipeline (P9)
    wf = await generate_workflow_reasoned("triage", ["x"], T, runtime=_EmptyRuntime())
    assert wf.definition.get("synthesis") is None
    assert [s["name"] for s in wf.definition["steps"]] == _LINEAR


async def test_no_runtime_is_deterministic():
    wf = await generate_workflow_reasoned("triage", ["x"], T)
    assert [s["name"] for s in wf.definition["steps"]] == _LINEAR
