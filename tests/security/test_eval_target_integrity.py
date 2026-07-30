"""Evaluation target dispatch and durable-history integrity."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.eval import EvalRunner
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    EvalCase,
    GrantSet,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

T = "eval-target-integrity"


def _headers(*, role: str = "org-admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


class _UnexpectedSpawner:
    def __init__(self) -> None:
        self.calls = 0

    async def spawn(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("workflow or invalid targets must not enter the skill spawner")


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    return kernel


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-24")
async def test_target_kind_is_closed_at_authoring_and_forged_rows_fail_closed() -> None:
    kernel = await _kernel()
    spawner = _UnexpectedSpawner()
    runner = EvalRunner(kernel, spawner)
    client = TestClient(create_app(kernel, platform={"eval": runner}))

    invalid = client.post(
        "/v1/eval/cases",
        headers=_headers(),
        json={
            "id": "invalid",
            "target_kind": "agent",
            "target_ref": "anything",
            "input": {},
            "assertions": {},
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["reason"] == "schema_invalid"
    assert await kernel.store.get_eval_case(T, "invalid") is None

    accepted = client.post(
        "/v1/eval/cases",
        headers=_headers(),
        json={
            "id": "workflow-case",
            "target_kind": "workflow",
            "target_ref": "workflow-under-test",
            "input": {},
            "assertions": {},
        },
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "pending_human"

    forged = EvalCase(
        id="legacy-forged",
        tenant_id=T,
        target_kind="conversation",
        target_ref="could-have-been-a-skill",
        input={"task": "must not run"},
        assertions={},
    )
    await kernel.store.upsert_eval_case(forged)
    result = await runner.run_case(forged, grants=GrantSet.of(["*"]), actor="author")
    assert result.passed is False
    assert result.score == 0.0
    assert result.detail["target"] == {
        "kind": "conversation",
        "ref": "could-have-been-a-skill",
    }
    assert result.detail["target_error"] == "unsupported_target_kind"
    assert spawner.calls == 0


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-24")
async def test_workflow_target_uses_governed_interpreter_and_history_keeps_snapshot() -> None:
    kernel = await _kernel()
    workflow = WorkflowDefinition(
        id="ticket-workflow",
        tenant_id=T,
        version="1.0.0",
        source=WorkflowSource.PRECREATED,
        definition={
            "steps": [
                {
                    "id": "create",
                    "parents": [],
                    "action": "ticket.create",
                    "params": {"title": "Evaluated through the workflow path"},
                }
            ]
        },
        workspace_id="workspace-a",
    )
    workflows = WorkflowLibrary(kernel.store, kernel=kernel)
    await workflows.register(workflow)
    spawner = _UnexpectedSpawner()
    runner = EvalRunner(kernel, spawner, workflows=workflows)
    case = EvalCase(
        id="workflow-eval",
        tenant_id=T,
        target_kind="workflow",
        target_ref=workflow.id,
        input={"fixture": "value"},
        assertions={
            "must_call": ["ticket.create"],
            "must_not_call": ["ticket.read"],
            "forbidden_grants": ["ticket.delete"],
            "expect_output": {"status": "completed"},
        },
    )
    await kernel.store.upsert_eval_case(case)

    client = TestClient(create_app(kernel, platform={"eval": runner}))
    response = client.post(
        "/v1/eval/run",
        headers={
            **_headers(),
            "x-boltrig-grants": "ticket.create",
            "x-boltrig-workspace": "workspace-a",
        },
        json={"case_id": case.id},
    )
    assert response.status_code == 200, response.text
    [result] = await kernel.store.list_eval_runs(T, case.id)

    assert result.passed is True, result.detail
    assert result.score == 1.0
    assert result.detail["target"] == {
        "kind": "workflow",
        "ref": workflow.id,
    }
    assert result.detail["workflow_status"] == "completed"
    assert result.detail["effective_grants"] == ["ticket.create"]
    assert result.detail["checks"] == {
        "must_call:ticket.create": True,
        "must_not_call:ticket.read": True,
        "forbidden_grant:ticket.delete": True,
        "expect_output": True,
    }
    assert spawner.calls == 0

    # Editing the case after the run cannot rewrite what historical execution
    # actually targeted: the run carries its own immutable target snapshot.
    await kernel.store.upsert_eval_case(replace(case, target_ref="replacement-workflow"))
    history = client.get(f"/v1/eval/runs?case_id={case.id}", headers=_headers())
    assert history.status_code == 200
    [row] = history.json()["runs"]
    assert row["target_kind"] == "workflow"
    assert row["target_ref"] == workflow.id
    assert row["detail"] == result.detail
    assert isinstance(row["created_at"], str)
    assert (
        client.get(
            f"/v1/eval/runs?case_id={case.id}",
            headers=_headers(role="member"),
        ).status_code
        == 403
    )
