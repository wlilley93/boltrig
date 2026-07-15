"""Object-level authorization regressions for generic HITL HTTP routes."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.fleet.pump import WorkPump
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.questions import QUESTIONS_VERB, register_questions_verb
from boltrig.models import (
    GrantSet,
    HITLStatus,
    HITLType,
    PendingHuman,
    TenantPermissions,
    Urgency,
    WorkItem,
    WorkStatus,
    Workspace,
    WorkspaceMember,
)
from boltrig.store import InMemoryStore

T = "acme"


def _principal(
    subject: str,
    *,
    departments: list[str] | None = None,
    workspace: str | None = None,
    role: str = "engineer",
    grants: list[str] | None = None,
    actor_tier: str = "human",
    on_behalf_of: str | None = None,
) -> Principal:
    scope = {"all": True} if role == "org-admin" else {"departments": departments or []}
    return Principal(
        tenant_id=T,
        subject=subject,
        grants=GrantSet.of(grants if grants is not None else ["ticket.create"]),
        role=role,
        actor_tier=actor_tier,
        on_behalf_of=on_behalf_of,
        scope=scope,
        active_workspace_id=workspace,
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs={"ticket.create"})
    await kernel.register_adapter(T, build_tickets())
    return kernel


def _client(kernel: Kernel) -> TestClient:
    principals = {
        "requester": _principal(
            "requester", departments=["marketing"], workspace="ws-2"
        ),
        "marketing-reviewer": _principal(
            "marketing-reviewer", departments=["marketing"], workspace="ws-2"
        ),
        "marketing-wrong-workspace": _principal(
            "marketing-wrong-workspace", departments=["marketing"], workspace="ws-1"
        ),
        "engineering-same-workspace": _principal(
            "engineering-same-workspace", departments=["engineering"], workspace="ws-2"
        ),
        "engineering-reviewer": _principal(
            "engineering-reviewer", departments=["engineering"], workspace="ws-1"
        ),
        "floating-reviewer": _principal(
            "floating-reviewer", departments=["marketing"], workspace=None
        ),
        "independent-reviewer": _principal(
            "independent-reviewer", role="org-admin", grants=["*"]
        ),
        "alice": _principal("alice", role="org-admin", grants=["*"]),
        "bob": _principal("bob", role="org-admin", grants=["*"]),
        "agent": _principal(
            "agent:worker", role="org-admin", grants=["*"], actor_tier="ephemeral"
        ),
        "delegate": _principal(
            "delegate", role="org-admin", grants=["*"], on_behalf_of="alice"
        ),
    }

    async def resolver(request: Request) -> Principal:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        principal = principals.get(token)
        if principal is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return principal

    return TestClient(create_app(kernel, principal_resolver=resolver, platform={}))


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _create_scoped_approval(client: TestClient) -> str:
    response = client.post(
        "/v1/invoke",
        headers=_headers("requester"),
        json={
            "noun": "ticket",
            "verb": "ticket.create",
            "params": {"title": "marketing deploy"},
            "context": {"run_id": "run-marketing-ws2"},
        },
    )
    assert response.status_code == 202
    return response.json()["hitl_request_id"]


def _listed_ids(client: TestClient, token: str) -> set[str]:
    response = client.get("/v1/hitl", headers=_headers(token))
    assert response.status_code == 200
    return {request["id"] for request in response.json()["requests"]}


@pytest.mark.security
@pytest.mark.invariant("SEC-141")
def test_hitl_list_and_respond_enforce_department_and_workspace_scope():
    kernel = asyncio.run(_kernel())
    client = _client(kernel)
    request_id = _create_scoped_approval(client)
    fired: list[str] = []
    kernel.hitl.set_resume_notifier(lambda request: fired.append(request.id))

    hidden_from = (
        "engineering-reviewer",
        "marketing-wrong-workspace",
        "engineering-same-workspace",
        "floating-reviewer",
    )
    for token in hidden_from:
        assert request_id not in _listed_ids(client, token)
    assert request_id in _listed_ids(client, "marketing-reviewer")
    assert request_id in _listed_ids(client, "requester")
    assert request_id in _listed_ids(client, "bob")  # no active workspace, org-wide

    for token in hidden_from:
        denied = client.post(
            f"/v1/hitl/{request_id}/respond",
            headers=_headers(token),
            json={"decision": "approve"},
        )
        assert denied.status_code == 404
        assert denied.json()["detail"] == "unknown request"
    assert asyncio.run(kernel.hitl.get(T, request_id)).status == HITLStatus.PENDING
    assert fired == []

    asyncio.run(
        kernel.store.create_workspace(
            Workspace(id="ws-2", tenant_id=T, name="Marketing", slug="marketing")
        )
    )
    asyncio.run(
        kernel.store.add_workspace_member(
            WorkspaceMember(
                user_id="floating-reviewer",
                workspace_id="ws-2",
                tenant_id=T,
            )
        )
    )
    assert request_id in _listed_ids(client, "floating-reviewer")

    allowed = client.post(
        f"/v1/hitl/{request_id}/respond",
        headers=_headers("floating-reviewer"),
        json={"decision": "approve"},
    )
    assert allowed.status_code == 200
    assert asyncio.run(kernel.hitl.get(T, request_id)).status == HITLStatus.ANSWERED
    assert fired == [request_id]


@pytest.mark.security
@pytest.mark.invariant("SEC-141")
def test_hitl_list_hides_requests_outside_assignee_and_requester_relationships():
    kernel = asyncio.run(_kernel())
    client = _client(kernel)
    assigned = asyncio.run(
        kernel.hitl.create(
            tenant_id=T,
            run_id="assigned-run",
            type=HITLType.APPROVAL,
            question="Approve assigned action?",
            assignee="alice",
            verb="ticket.create",
            requested_by="requester",
            request_fingerprint="assigned-fingerprint",
        )
    )

    assert assigned.id in _listed_ids(client, "alice")
    assert assigned.id in _listed_ids(client, "requester")
    assert assigned.id not in _listed_ids(client, "bob")


@pytest.mark.security
@pytest.mark.invariant("SEC-141")
async def test_chat_question_persists_authenticated_workspace_and_department_scope():
    kernel = await _kernel()
    captured = []

    class CapturingSpawner:
        async def spawn(self, tenant_id, task, skills, prefer, context, **kwargs):
            captured.append(context)
            return {"summary": "done", "new_work_items": ["follow up"]}

    chat = ChatService(
        kernel.store,
        kernel.events,
        turn_executor=build_turn_executor(
            kernel, CapturingSpawner(), continuity=False
        ),
    )
    _ = [
        event
        async for event in chat.handle_turn(
            tenant_id=T,
            user_id="alice",
            role="engineer",
            grants=GrantSet.of(["chat.*"]),
            message="ask me before choosing a region",
            workspace_id="ws-2",
            scope={"departments": ["marketing"]},
        )
    ]
    assert len(captured) == 1
    items = await kernel.store.list_work_items(T)
    assert len(items) == 2
    assert {item.workspace_id for item in items} == {"ws-2"}

    await register_questions_verb(kernel.store, T)
    with pytest.raises(PendingHuman):
        await kernel.invoke(
            "chat",
            QUESTIONS_VERB,
            {"prompt": "Which region?", "choices": ["eu", "us"]},
            captured[0],
        )

    request = (await kernel.hitl.list_pending(T))[0]
    assert request.type == HITLType.QUESTION
    assert request.requested_on_behalf_of == "alice"
    assert request.workspace_id == "ws-2"
    assert request.department_scope == ["marketing"]


@pytest.mark.security
@pytest.mark.invariant("SEC-141")
async def test_pump_preserves_workspace_and_department_on_approval_and_park():
    kernel = await _kernel()

    class RoutingCoS:
        async def route(self, item, context):
            return "engineering"

    class BlockingHead:
        name = "engineering"

        async def handle(self, item, context, *, tree_id):
            return await kernel.invoke(
                "ticket", "ticket.create", {"title": "sensitive"}, context
            )

    item = WorkItem(
        id="pump-work",
        tenant_id=T,
        source="internal",
        intent="create a sensitive ticket",
        confidence=1.0,
        convergent=False,
        status=WorkStatus.IN_FLIGHT,
        hatchet_run_id="pump-run",
        on_behalf_of="alice",
        workspace_id="ws-2",
    )
    await kernel.store.create_work_item(item)
    pump = WorkPump(
        kernel, object(), RoutingCoS(), {"engineering": BlockingHead()}
    )

    with pytest.raises(PendingHuman):
        await pump.handle_claimed_item(item)

    request = (await kernel.hitl.list_pending(T))[0]
    assert request.type == HITLType.APPROVAL
    assert request.workspace_id == "ws-2"
    assert request.department_scope == ["engineering"]
    stored = await kernel.store.get_work_item(T, item.id)
    assert stored is not None and stored.owner_member == "engineering"

    await pump._park(item, "pump-run", reason="blocked", detail="needs review")
    pending = await kernel.hitl.list_pending(T)
    escalation = next(req for req in pending if req.type == HITLType.ESCALATION)
    assert escalation.workspace_id == "ws-2"
    assert escalation.department_scope == ["engineering"]


async def _seed_owner_request(kernel: Kernel, kind: HITLType, request_id: str):
    await kernel.store.create_work_item(
        WorkItem(
            id=f"work-{request_id}",
            tenant_id=T,
            source="chat",
            intent="needs owner input",
            confidence=1.0,
            convergent=False,
            status=WorkStatus.AWAITING_HUMAN,
            owner_member="engineering",
            hatchet_run_id=f"run-{request_id}",
            on_behalf_of="alice",
        )
    )
    return await kernel.hitl.create(
        tenant_id=T,
        run_id=f"run-{request_id}",
        type=kind,
        question="What should happen?",
        urgency=Urgency.BLOCKING,
        work_item_id=f"work-{request_id}",
        requested_by="agent:worker",
        requested_on_behalf_of="alice",
        assignee="independent-reviewer" if kind != HITLType.QUESTION else None,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-89")
@pytest.mark.invariant("SEC-141")
def test_generic_respond_cannot_bypass_owner_checked_question_answer_route():
    kernel = asyncio.run(_kernel())
    client = _client(kernel)
    question = asyncio.run(_seed_owner_request(kernel, HITLType.QUESTION, "question"))

    hidden = client.post(
        f"/v1/hitl/{question.id}/respond",
        headers=_headers("bob"),
        json={"decision": "probe another owner's question"},
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "unknown request"

    delegated = client.post(
        f"/v1/hitl/{question.id}/answer",
        headers=_headers("delegate"),
        json={"answer": "probe while delegated for owner"},
    )
    unknown = client.post(
        "/v1/hitl/unknown/answer",
        headers=_headers("delegate"),
        json={"answer": "probe unknown"},
    )
    assert delegated.status_code == unknown.status_code == 404
    assert delegated.json() == unknown.json() == {
        "status": "error",
        "reason": "not_found",
    }

    generic = client.post(
        f"/v1/hitl/{question.id}/respond",
        headers=_headers("alice"),
        json={"decision": "raw unwrapped answer"},
    )
    assert generic.status_code == 409
    assert generic.json()["detail"] == "use the question answer route"
    assert asyncio.run(kernel.hitl.get(T, question.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.store.get_hitl_response(T, question.id)) is None

    dedicated = client.post(
        f"/v1/hitl/{question.id}/answer",
        headers=_headers("alice"),
        json={"answer": "safe owner answer"},
    )
    assert dedicated.status_code == 200
    stored = asyncio.run(kernel.store.get_hitl_response(T, question.id))
    assert stored is not None
    assert stored.decision.startswith('<untrusted kind="user_answer"')
    assert "safe owner answer" in stored.decision


@pytest.mark.security
@pytest.mark.invariant("SEC-141")
@pytest.mark.parametrize("kind", [HITLType.CLARIFICATION, HITLType.ESCALATION])
def test_nonapproval_generic_respond_requires_independent_assigned_human(kind: HITLType):
    kernel = asyncio.run(_kernel())
    client = _client(kernel)
    fired: list[str] = []
    kernel.hitl.set_resume_notifier(lambda req: fired.append(req.id))
    request = asyncio.run(_seed_owner_request(kernel, kind, kind.value))

    nonhuman = client.post(
        f"/v1/hitl/{request.id}/respond",
        headers=_headers("agent"),
        json={"decision": "agent takeover"},
    )
    assert nonhuman.status_code == 403
    assert fired == []

    owner = client.post(
        f"/v1/hitl/{request.id}/respond",
        headers=_headers("alice"),
        json={"decision": "answer my own request"},
    )
    assert owner.status_code == 403
    assert owner.json()["detail"] == "cannot answer your own request"

    denied = client.post(
        f"/v1/hitl/{request.id}/respond",
        headers=_headers("bob"),
        json={"decision": "take over"},
    )
    assert denied.status_code == 403
    assert asyncio.run(kernel.hitl.get(T, request.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.store.get_hitl_response(T, request.id)) is None
    assert fired == []

    allowed = client.post(
        f"/v1/hitl/{request.id}/respond",
        headers=_headers("independent-reviewer"),
        json={"decision": "continue"},
    )
    assert allowed.status_code == 200
    assert asyncio.run(kernel.hitl.get(T, request.id)).status == HITLStatus.ANSWERED
    stored = asyncio.run(kernel.store.get_hitl_response(T, request.id))
    assert stored is not None
    assert stored.decision.startswith('<untrusted kind="hitl_response"')
    assert "continue" in stored.decision
    assert stored.respondent == "independent-reviewer"
    assert fired == [request.id]
