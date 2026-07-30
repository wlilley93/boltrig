"""Mutable control resources remain exact across approval and execution."""

from __future__ import annotations

import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    HITLStatus,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

TENANT = "control-approval"


def _workflow(action: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="mutable-workflow",
        tenant_id=TENANT,
        version="1",
        source=WorkflowSource.PRECREATED,
        definition={"steps": [{"id": "step", "action": action, "params": {}}]},
    )


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id="run-control-approval",
        extra={"principal_role": "superadmin", "principal_scope": {"all": True}},
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    kernel = Kernel(store)
    control = build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry)
    control.set_workflows(WorkflowLibrary(store, kernel=kernel))
    await kernel.register_adapter(TENANT, control)
    return kernel


@pytest.mark.security
@pytest.mark.invariant("SEC-138")
async def test_missing_mutable_resource_fails_before_creating_approval() -> None:
    kernel = await _kernel()

    with pytest.raises(AdapterFailure) as caught:
        await kernel.invoke(
            "control",
            "control.workflow.trigger",
            {"workflow_id": "missing", "inputs": {}},
            _context(),
        )

    assert caught.value.status_code == 404
    assert await kernel.hitl.list_pending(TENANT) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-138")
@pytest.mark.invariant("SEC-193")
@pytest.mark.parametrize(
    ("verb", "params"),
    [
        (
            "control.workflow.trigger",
            {"workflow_id": "mutable-workflow", "inputs": {}},
        ),
        (
            "control.workflow.archive",
            {"workflow_id": "mutable-workflow"},
        ),
    ],
)
async def test_resource_change_between_gate_and_adapter_execute_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    params: dict,
) -> None:
    kernel = await _kernel()
    original = _workflow("first.action")
    changed = _workflow("changed.action")
    await kernel.store.upsert_workflow(original)
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context())
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(TENANT, request_id, "approve", "independent-reviewer")

    calls = 0

    async def drifting_workflows(tenant_id: str) -> list[WorkflowDefinition]:
        nonlocal calls
        assert tenant_id == TENANT
        calls += 1
        return [original] if calls == 1 else [changed]

    monkeypatch.setattr(kernel.store, "list_workflows", drifting_workflows)
    with pytest.raises(AdapterFailure) as caught:
        await kernel.invoke(
            "control",
            verb,
            params,
            _context(),
            approval_id=request_id,
        )

    assert caught.value.status_code == 403
    assert calls == 2
    assert (await kernel.hitl.get(TENANT, request_id)).status == HITLStatus.CONSUMED
