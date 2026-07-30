"""Recoverable governed workflow lifecycle contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.control_workflows import upsert_workflow_record
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    InvocationContext,
    PendingHuman,
    SchemaValidationError,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary
from boltrig.workflows.generator import generate_workflow, learn_from_success

T = "workflow-lifecycle"


def _context(verb: str) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id=f"run-{verb.rsplit('.', 1)[-1]}",
        extra={"principal_role": "superadmin", "principal_scope": {"all": True}},
    )


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _context(verb))
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    return await kernel.invoke("control", verb, params, _context(verb), approval_id=request_id)


async def _rejected_without_approval(kernel: Kernel, verb: str, params: dict) -> AdapterFailure:
    with pytest.raises(AdapterFailure) as failed:
        await kernel.invoke("control", verb, params, _context(verb))
    return failed.value


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    control = build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry)
    control.set_workflows(WorkflowLibrary(store, kernel=kernel))
    await kernel.register_adapter(T, control)
    await store.upsert_workflow(
        WorkflowDefinition(
            id="renewals",
            tenant_id=T,
            version="1",
            source=WorkflowSource.PRECREATED,
            definition={"steps": []},
        )
    )
    return kernel


@pytest.mark.security
@pytest.mark.invariant("SEC-193")
async def test_archive_is_recoverable_and_blocks_every_execution_seam() -> None:
    kernel = await _kernel()
    await _approved(
        kernel,
        "control.workflow.schedule",
        {"workflow_id": "renewals", "cron": "0 9 * * 1", "timezone": "UTC"},
    )
    archived = await _approved(kernel, "control.workflow.archive", {"workflow_id": "renewals"})
    assert archived == {
        "id": "renewals",
        "workflow_status": "archived",
        "schedule": None,
    }
    workflow = (await kernel.store.list_workflows(T))[0]
    assert workflow.definition["_boltrig_lifecycle"]["status"] == "archived"
    assert "schedule" not in workflow.definition

    library = WorkflowLibrary(kernel.store, kernel=kernel)
    with pytest.raises(PermissionError, match="workflow_archived"):
        await library.trigger(T, "renewals", {})
    with pytest.raises(PermissionError, match="workflow_archived"):
        await library.execute(T, "renewals", {}, _context("execute"))

    pending_before = await kernel.hitl.list_pending(T)
    denied = await _rejected_without_approval(
        kernel,
        "control.workflow.schedule",
        {"workflow_id": "renewals", "cron": "0 10 * * 1"},
    )
    assert str(denied) == "workflow_archived"
    for verb in ("control.workflow.trigger", "control.workflow.execute"):
        denied = await _rejected_without_approval(
            kernel, verb, {"workflow_id": "renewals", "inputs": {}}
        )
        assert str(denied) == "workflow_archived"
    assert await kernel.hitl.list_pending(T) == pending_before

    # An ordinary definition save cannot smuggle an archived workflow active.
    await upsert_workflow_record(
        kernel.store,
        T,
        {"id": "renewals", "version": "2", "definition": {"steps": []}},
        workspace_id=None,
    )
    latest = (await kernel.store.list_workflows(T))[0]
    assert latest.definition["_boltrig_lifecycle"]["status"] == "archived"

    restored = await _approved(kernel, "control.workflow.restore", {"workflow_id": "renewals"})
    assert restored["workflow_status"] == "active"
    assert (await library.trigger(T, "renewals", {}))["status"] == "queued"


@pytest.mark.security
@pytest.mark.invariant("SEC-193")
async def test_list_and_detail_surface_lifecycle_without_deleting_archive() -> None:
    kernel = await _kernel()
    await _approved(kernel, "control.workflow.archive", {"workflow_id": "renewals"})
    client = TestClient(create_app(kernel))
    headers = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }
    summary = client.get("/v1/workflows", headers=headers).json()["workflows"][0]
    detail = client.get("/v1/workflows/renewals", headers=headers).json()
    assert summary["status"] == detail["status"] == "archived"
    assert summary["schedule"] is detail["schedule"] is None
    assert detail["id"] == "renewals"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-25")
async def test_authored_upsert_cannot_forge_internal_workflow_provenance() -> None:
    kernel = await _kernel()

    # Provenance is not an authored input, including the otherwise harmless
    # precreated value. Refusal occurs at schema validation before approval or
    # persistence, so a client cannot use a forged HITL request as a side door.
    pending_before = await kernel.hitl.list_pending(T)
    for source in WorkflowSource:
        with pytest.raises(SchemaValidationError):
            await kernel.invoke(
                "control",
                "control.workflow.upsert",
                {
                    "id": f"forged-{source.value}",
                    "source": source.value,
                    "definition": {"steps": []},
                },
                _context("control.workflow.upsert"),
            )
    assert await kernel.hitl.list_pending(T) == pending_before
    assert not any(
        workflow.id.startswith("forged-") for workflow in await kernel.store.list_workflows(T)
    )

    # Defense in depth for direct callers of the shared authoring helper.
    with pytest.raises(ValueError, match="kernel-owned"):
        await upsert_workflow_record(
            kernel.store,
            T,
            {
                "id": "direct-forgery",
                "source": "learned",
                "definition": {"steps": []},
            },
            workspace_id=None,
        )

    # Internal synthesis and learning retain their typed provenance path.
    generated = generate_workflow("prepare renewal", ["renewal"], T)
    await kernel.store.upsert_workflow(generated)
    edited_generated = await upsert_workflow_record(
        kernel.store,
        T,
        {
            "id": generated.id,
            "version": "2.0.0",
            "definition": {"steps": [], "edited": True},
        },
        workspace_id=None,
    )
    assert edited_generated.source is WorkflowSource.GENERATED
    assert edited_generated.origin_task == "prepare renewal"

    learned = await learn_from_success(kernel.store, edited_generated, "successful renewal")
    edited_learned = await upsert_workflow_record(
        kernel.store,
        T,
        {
            "id": learned.id,
            "version": "2.0.1",
            "definition": {"steps": [], "edited_again": True},
        },
        workspace_id=None,
    )
    assert edited_learned.source is WorkflowSource.LEARNED
    assert edited_learned.origin_task == "successful renewal"

    authored = await upsert_workflow_record(
        kernel.store,
        T,
        {"id": "authored", "definition": {"steps": []}},
        workspace_id=None,
    )
    assert authored.source is WorkflowSource.PRECREATED


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-19")
async def test_authored_loop_contract_rejects_invalid_bindings_before_save() -> None:
    kernel = await _kernel()
    invalid_source = {
        "id": "bad-loop-source",
        "definition": {
            "steps": [
                {
                    "id": "loop",
                    "action": "flow.loop",
                    "params": {"items": [1]},
                },
                {
                    "id": "body",
                    "action": "ticket.create",
                    "parents": ["loop"],
                    "params": {"title": None},
                    "loop_bindings": {"title": "expression"},
                },
            ],
        },
    }
    pending_before = await kernel.hitl.list_pending(T)

    with pytest.raises(SchemaValidationError):
        await kernel.invoke(
            "control",
            "control.workflow.upsert",
            invalid_source,
            _context("control.workflow.upsert"),
        )

    assert await kernel.hitl.list_pending(T) == pending_before
    with pytest.raises(ValueError, match="loop_binding_target_missing"):
        await upsert_workflow_record(
            kernel.store,
            T,
            {
                "id": "bad-loop-target",
                "definition": {
                    "steps": [
                        {
                            "id": "loop",
                            "action": "flow.loop",
                            "params": {"items": [1]},
                        },
                        {
                            "id": "body",
                            "action": "ticket.create",
                            "parents": ["loop"],
                            "params": {"title": None},
                            "loop_bindings": {"missing": "item"},
                        },
                    ],
                },
            },
            workspace_id=None,
        )
    assert not any(
        workflow.id.startswith("bad-loop") for workflow in await kernel.store.list_workflows(T)
    )
