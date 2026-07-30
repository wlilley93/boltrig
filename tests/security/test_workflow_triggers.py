"""External workflow triggers preserve current identity and kernel authority."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import (
    canonical_body,
    expected_signature,
    signed_content,
)
from boltrig.api.bootstrap import wire_hitl_resume
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.fleet.held_write_resume import resume_held_write
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import (
    Channel,
    ChannelBinding,
    GrantSet,
    HITLStatus,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
    User,
    WorkflowDefinition,
    WorkflowSource,
    Workspace,
    WorkspaceMember,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

T = "workflow-trigger-tests"
CHANNEL_SECRET = "channel-trigger-signing-secret"


class _CaptureExecutor:
    durable = True

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict]] = []

    def new_run_id(self) -> str:
        return f"run-{uuid.uuid4().hex}"

    async def enqueue(self, task_name: str, payload: dict) -> str:
        self.enqueued.append((task_name, payload))
        return f"engine-{len(self.enqueued)}"


def _context(actor: str, verb: str, *, workspace_id: str | None = None):
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor=actor,
        actor_tier="human",
        run_id=f"author-{verb.rsplit('.', 1)[-1]}-{uuid.uuid4().hex}",
        workspace_id=workspace_id,
        extra={"principal_role": "superadmin", "principal_scope": {"all": True}},
    )


async def _approved(
    kernel: Kernel,
    actor: str,
    verb: str,
    params: dict,
    *,
    workspace_id: str | None = None,
) -> dict:
    context = _context(actor, verb, workspace_id=workspace_id)
    with pytest.raises(PendingHuman) as pending:
        await kernel.invoke("control", verb, params, context)
    await kernel.hitl.answer(
        T, pending.value.hitl_request_id, "approve", "independent-reviewer"
    )
    return await kernel.invoke(
        "control",
        verb,
        params,
        context,
        approval_id=pending.value.hitl_request_id,
    )


async def _setup() -> tuple[Kernel, InMemoryStore, _CaptureExecutor]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_user(
        User(
            id="author",
            tenant_id=T,
            email="author@example.com",
            role="superadmin",
            scope={"all": True},
            status="active",
        )
    )
    await store.upsert_user(
        User(
            id="sender",
            tenant_id=T,
            email="sender@example.com",
            role="superadmin",
            scope={"all": True},
            status="active",
        )
    )
    await store.upsert_workflow(
        WorkflowDefinition(
            id="release",
            tenant_id=T,
            version="1",
            source=WorkflowSource.PRECREATED,
            definition={"steps": []},
        )
    )
    executor = _CaptureExecutor()
    kernel = Kernel(store)
    control = build_control_plane_adapter(
        store,
        loader=kernel.loader,
        registry=kernel.registry,
        workflows=WorkflowLibrary(store, executor=executor, kernel=kernel),
    )
    await kernel.register_adapter(T, control)
    return kernel, store, executor


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_webhook_secret_is_show_once_and_delivery_reauthorizes_current_owner():
    kernel, store, executor = await _setup()
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {"workflow_id": "release", "name": "release-hook", "source": "webhook"},
    )
    trigger = await store.get_workflow_trigger(T, created["trigger_id"])
    assert trigger is not None
    assert created["secret"].startswith("wft_")
    assert trigger.secret_hash != created["secret"]
    assert created["secret"] not in repr(trigger)

    client = TestClient(create_app(kernel))
    listed = client.get(
        "/v1/workflows/release/triggers",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "author",
            "x-boltrig-role": "org-admin",
        },
    )
    assert listed.status_code == 200
    assert "secret_hash" not in listed.json()["triggers"][0]
    assert "secret" not in listed.json()["triggers"][0]

    event = {
        "workflow_id": "attacker-choice",
        "grants": ["*"],
        "on_behalf_of": "attacker",
        "payload": "untrusted",
    }
    headers = {
        "x-boltrig-trigger-secret": created["secret"],
        "x-boltrig-delivery-id": "provider-event-1",
    }
    first = client.post(created["webhook_path"], json=event, headers=headers)
    replay = client.post(created["webhook_path"], json=event, headers=headers)
    assert first.status_code == 202
    assert first.json()["status"] == "pending_human"
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"
    assert executor.enqueued == []
    pending = await kernel.hitl.get(
        T, first.json()["receipt"]["hitl_request_id"]
    )
    assert pending.requested_by == "author"
    assert pending.requested_on_behalf_of == "author"
    from boltrig.kernel.held_call import read_held_call

    held = await read_held_call(store, T, pending.run_id, pending.id)
    assert held.verb == "control.workflow.trigger"
    assert held.params["workflow_id"] == "release"
    assert held.params["inputs"]["event"] == event
    assert held.context.actor == held.context.on_behalf_of == "author"

    # Approval resumes the sealed canonical call, and only that call, into the
    # durable workflow executor. The untrusted event remains nested input data.
    await kernel.hitl.answer(T, pending.id, "approve", "independent-reviewer")
    resumed = await resume_held_write(
        kernel, store, kernel.events, T, pending.run_id, pending.id
    )
    assert resumed == {"status": "ok"}
    assert len(executor.enqueued) == 1
    task_name, envelope = executor.enqueued[0]
    assert task_name == "boltrig-workflow-run"
    assert envelope["workflow_id"] == "release"
    assert envelope["inputs"]["event"] == event
    assert envelope["ctx_envelope"]["actor"] == "author"
    assert envelope["ctx_envelope"]["on_behalf_of"] == "author"

    # Current user state wins over the captured ceiling: deactivation kills the
    # next distinct event immediately and nothing reaches the executor.
    owner = await store.get_user(T, "author")
    owner.status = "deactivated"
    await store.upsert_user(owner)
    denied = client.post(
        created["webhook_path"],
        json={"payload": "later"},
        headers={**headers, "x-boltrig-delivery-id": "provider-event-2"},
    )
    assert denied.status_code == 403
    assert denied.json()["receipt"]["reason"] == "authority_revoked"
    assert len(executor.enqueued) == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_workspace_trigger_rechecks_current_membership_before_dispatch():
    kernel, store, executor = await _setup()
    await store.create_workspace(
        Workspace(
            id="ws-release",
            tenant_id=T,
            name="Release",
            slug="release",
        )
    )
    await store.add_workspace_member(
        WorkspaceMember(
            user_id="author",
            workspace_id="ws-release",
            tenant_id=T,
            role="owner",
        )
    )
    await store.upsert_workflow(
        WorkflowDefinition(
            id="workspace-release",
            tenant_id=T,
            workspace_id="ws-release",
            version="1",
            source=WorkflowSource.PRECREATED,
            definition={"steps": []},
        )
    )
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {
            "workflow_id": "workspace-release",
            "name": "workspace-hook",
            "source": "webhook",
        },
        workspace_id="ws-release",
    )

    await store.remove_workspace_member(T, "ws-release", "author")
    denied = TestClient(create_app(kernel)).post(
        created["webhook_path"],
        json={"event": "after-removal"},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "membership-revoked",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["receipt"]["reason"] == "authority_revoked"
    assert executor.enqueued == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_trigger_lifecycle_is_governed_and_rotation_revokes_old_secret():
    kernel, store, executor = await _setup()
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {"workflow_id": "release", "name": "lifecycle-hook", "source": "webhook"},
    )
    params = {
        "workflow_id": "release",
        "trigger_id": created["trigger_id"],
    }
    disabled = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.disable",
        params,
    )
    assert disabled["enabled"] is False
    enabled = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.enable",
        params,
    )
    assert enabled["enabled"] is True

    before = await store.get_workflow_trigger(T, created["trigger_id"])
    rotated = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.rotate",
        params,
    )
    after = await store.get_workflow_trigger(T, created["trigger_id"])
    assert before is not None and after is not None
    assert rotated["secret"].startswith("wft_")
    assert rotated["secret"] != created["secret"]
    assert after.secret_hash != before.secret_hash

    client = TestClient(create_app(kernel))
    old = client.post(
        created["webhook_path"],
        json={"event": "old-secret"},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "old-secret-event",
        },
    )
    current = client.post(
        created["webhook_path"],
        json={"event": "new-secret"},
        headers={
            "x-boltrig-trigger-secret": rotated["secret"],
            "x-boltrig-delivery-id": "new-secret-event",
        },
    )
    assert old.status_code == 401
    assert current.status_code == 202
    assert current.json()["status"] == "pending_human"
    assert executor.enqueued == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_secret_bearing_approval_requires_origin_surface_finalization():
    kernel, store, _ = await _setup()
    automatic_resumes: list[tuple[str, str, str]] = []

    async def resume(tenant_id: str, run_id: str, request_id: str):
        automatic_resumes.append((tenant_id, run_id, request_id))

    wire_hitl_resume(kernel, resume_held_write=resume)
    principal = Principal(
        tenant_id=T,
        subject="author",
        grants=GrantSet.of(["*"]),
        role="superadmin",
        actor_tier="human",
        scope={"all": True},
    )
    create_params = {
        "workflow_id": "release",
        "name": "handoff-hook",
        "source": "webhook",
    }
    _, create_pending = await dispatch_control_route(
        kernel,
        principal,
        "control.workflow.trigger_binding.create",
        create_params,
        run_id="origin-finalize-create",
    )
    assert create_pending is not None
    create_request = json.loads(bytes(create_pending.body))["hitl_request_id"]
    await kernel.hitl.answer(
        T, create_request, "approve", "independent-reviewer"
    )
    assert automatic_resumes == []
    assert (await kernel.hitl.get(T, create_request)).status == HITLStatus.ANSWERED
    from boltrig.kernel.held_call import read_held_call

    held = await read_held_call(
        store, T, "origin-finalize-create", create_request
    )
    assert held is not None
    assert "secret" not in repr(held.params)
    created, pending = await dispatch_control_route(
        kernel,
        principal,
        "control.workflow.trigger_binding.create",
        {**create_params, "approval_id": create_request},
        run_id="origin-finalize-create",
    )
    assert pending is None and created is not None
    assert created["secret"].startswith("wft_")
    assert (await kernel.hitl.get(T, create_request)).status == HITLStatus.CONSUMED
    assert (
        await read_held_call(
            store, T, "origin-finalize-create", create_request
        )
        is None
    )

    rotate_params = {
        "workflow_id": "release",
        "trigger_id": created["trigger_id"],
    }
    _, rotate_pending = await dispatch_control_route(
        kernel,
        principal,
        "control.workflow.trigger_binding.rotate",
        rotate_params,
        run_id="origin-finalize-rotate",
    )
    assert rotate_pending is not None
    rotate_request = json.loads(bytes(rotate_pending.body))["hitl_request_id"]
    await kernel.hitl.answer(
        T, rotate_request, "approve", "independent-reviewer"
    )
    assert automatic_resumes == []
    assert (await kernel.hitl.get(T, rotate_request)).status == HITLStatus.ANSWERED
    rotated, pending = await dispatch_control_route(
        kernel,
        principal,
        "control.workflow.trigger_binding.rotate",
        {**rotate_params, "approval_id": rotate_request},
        run_id="origin-finalize-rotate",
    )
    assert pending is None and rotated is not None
    assert rotated["secret"].startswith("wft_")
    assert rotated["secret"] != created["secret"]
    assert (
        await kernel.hitl.get(T, rotate_request)
    ).status == HITLStatus.CONSUMED
    assert (
        await read_held_call(
            store, T, "origin-finalize-rotate", rotate_request
        )
        is None
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_origin_finalization_is_discoverable_after_navigation_without_secret_storage():
    kernel, _, _ = await _setup()
    client = TestClient(create_app(kernel))
    author_headers = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }
    body = {
        "name": "reload-hook",
        "source": "webhook",
    }
    held = client.post(
        "/v1/workflows/release/triggers",
        json=body,
        headers=author_headers,
    )
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    await kernel.hitl.answer(
        T, request_id, "approve", "independent-reviewer"
    )

    other = client.get(
        "/v1/workflows/release/trigger-finalizations",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "sender",
            "x-boltrig-role": "org-admin",
        },
    )
    assert other.status_code == 200
    assert other.json()["finalizations"] == []
    discovered = client.get(
        "/v1/workflows/release/trigger-finalizations",
        headers=author_headers,
    )
    assert discovered.status_code == 200
    assert discovered.json()["finalizations"] == [
        {
            "request_id": request_id,
            "action": "create",
            "state": "ready",
            "name": "reload-hook",
            "source": "webhook",
        }
    ]
    assert "secret" not in repr(discovered.json())

    finalized = client.post(
        "/v1/workflows/release/triggers",
        json={**body, "approval_id": request_id},
        headers=author_headers,
    )
    assert finalized.status_code == 200
    assert finalized.json()["secret"].startswith("wft_")
    assert client.get(
        "/v1/workflows/release/trigger-finalizations",
        headers=author_headers,
    ).json()["finalizations"] == []

    trigger_id = finalized.json()["trigger_id"]
    rotate = client.post(
        f"/v1/workflows/release/triggers/{trigger_id}/rotate",
        json={},
        headers=author_headers,
    )
    assert rotate.status_code == 202
    rotate_request_id = rotate.json()["hitl_request_id"]
    await kernel.hitl.answer(
        T, rotate_request_id, "approve", "independent-reviewer"
    )
    assert client.get(
        "/v1/workflows/release/trigger-finalizations",
        headers=author_headers,
    ).json()["finalizations"] == [
        {
            "request_id": rotate_request_id,
            "action": "rotate",
            "state": "ready",
            "trigger_id": trigger_id,
        }
    ]
    rotated = client.post(
        f"/v1/workflows/release/triggers/{trigger_id}/rotate",
        json={"approval_id": rotate_request_id},
        headers=author_headers,
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret"].startswith("wft_")
    assert rotated.json()["secret"] != finalized.json()["secret"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_channel_trigger_uses_verified_current_sender_not_binding_author():
    kernel, store, executor = await _setup()
    await store.upsert_channel(
        Channel(
            id="ch-trigger",
            tenant_id=T,
            platform="webhook",
            name="Provider",
            transport="webhook",
            credential_ref="ch-secret",
            config={"sender_field": "sender"},
        )
    )
    await store.set_credential_ref(T, "ch-secret", {"secret": CHANNEL_SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(
            id="binding",
            tenant_id=T,
            channel_id="ch-trigger",
            platform="webhook",
            external_user_id="external-sender",
            subject="sender",
            role="superadmin",
        )
    )
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {
            "workflow_id": "release",
            "name": "provider-events",
            "source": "channel",
            "channel_id": "ch-trigger",
        },
    )
    assert "secret" not in created

    event = {
        "sender": "external-sender",
        "id": "channel-event-1",
        "workflow_id": "cannot-override",
        "text": "deploy",
    }
    timestamp = int(time.time())
    signature = expected_signature(
        CHANNEL_SECRET, signed_content(timestamp, canonical_body(event))
    )
    response = TestClient(create_app(kernel)).post(
        "/v1/channels/ch-trigger/inbound",
        json=event,
        headers={"x-boltrig-signature": f"t={timestamp},v1={signature}"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "workflow_trigger"
    outcome = response.json()["triggers"][0]
    assert outcome["status"] == "pending_human"
    pending = await kernel.hitl.get(
        T, outcome["receipt"]["hitl_request_id"]
    )
    assert pending.requested_by == "sender"
    assert pending.requested_on_behalf_of == "sender"
    assert pending.requested_by != "author"
    assert executor.enqueued == []
    assert await store.list_work_items(T) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_archived_workflow_fails_closed_before_external_dispatch():
    kernel, store, executor = await _setup()
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {"workflow_id": "release", "name": "archive-hook", "source": "webhook"},
    )
    workflow = (await store.list_workflows(T))[0]
    workflow.definition["_boltrig_lifecycle"] = {
        "status": "archived", "schedule": None
    }
    await store.upsert_workflow(workflow)

    response = TestClient(create_app(kernel)).post(
        created["webhook_path"],
        json={"event": "after archive"},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "archived-event",
        },
    )
    assert response.status_code == 409
    assert response.json()["receipt"]["reason"] == "workflow_archived"
    assert executor.enqueued == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-20")
async def test_webhook_trigger_rate_limit_bounds_unique_event_spend(monkeypatch):
    from boltrig.kernel import workflow_trigger_public_routes
    from boltrig.models import RateLimit

    monkeypatch.setattr(
        workflow_trigger_public_routes,
        "WEBHOOK_TRIGGER_RL",
        RateLimit(per="minute", max=1, scope="verb"),
    )
    kernel, _, executor = await _setup()
    created = await _approved(
        kernel,
        "author",
        "control.workflow.trigger_binding.create",
        {"workflow_id": "release", "name": "rate-hook", "source": "webhook"},
    )
    client = TestClient(create_app(kernel))
    first = client.post(
        created["webhook_path"],
        json={"event": 1},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "rate-1",
        },
    )
    limited = client.post(
        created["webhook_path"],
        json={"event": 2},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "rate-2",
        },
    )
    retry = client.post(
        created["webhook_path"],
        json={"event": 1},
        headers={
            "x-boltrig-trigger-secret": created["secret"],
            "x-boltrig-delivery-id": "rate-1",
        },
    )
    assert first.status_code == 202
    assert limited.status_code == 429
    assert limited.json() == {
        "status": "throttled", "reason": "trigger intake rate limit"
    }
    assert int(limited.headers["retry-after"]) >= 0
    assert retry.status_code == 200
    assert retry.json()["status"] == "duplicate"
    assert (
        retry.json()["receipt"]["event_digest"]
        == first.json()["receipt"]["event_digest"]
    )
    assert executor.enqueued == []
