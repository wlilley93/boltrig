"""A caller may not assert somebody else's run id at a write door (SEC-186).

``POST /v1/invoke`` and ``POST /v1/spawn`` let the request body name the run the
work executes under. That string is not a label: the dispatcher publishes this
call's ``tool_call``/``tool_result`` frames against it, ``_ask_user`` binds a new
HITL to it, and - before this fence - it was the ONLY thing gating run-scoped
credentials, so a same-tenant bystander who quoted a stranger's run id was handed
that stranger's sealed material. The reference's run id and the "context" run id
it was checked against both came out of the same attacker-controlled request, so
they always agreed.

Every READ path already fenced this on the work item's ``on_behalf_of``
(``visible_run_events``, ``cancel_run``, ``answer_hitl_question``). These pin the
same predicate on the WRITE doors.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.spawn import Spawner, make_app_spawner
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, SpawnBody, create_app
from boltrig.models import GrantSet, TenantPermissions, WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "acme"
VICTIM_RUN = "run-victims-chat-turn"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(T, build_tickets())
    # A live chat turn belonging to victoria, exactly as fleet/chat.py writes it.
    await store.create_work_item(WorkItem(
        id=VICTIM_RUN, tenant_id=T, source="chat", intent="something private",
        confidence=1.0, convergent=False, status=WorkStatus.IN_FLIGHT,
        owner_member="chief-of-staff", hatchet_run_id=VICTIM_RUN,
        on_behalf_of="victoria",
    ))
    return kernel


def _hdr(subject: str) -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": "engineer",
        "x-boltrig-tier": "human",
        "x-boltrig-grants": "ticket.*",
        "x-boltrig-verbs": "ticket.read",
        "x-boltrig-departments": "engineering",
    }


def _principal(subject: str) -> Principal:
    return Principal(
        tenant_id=T, subject=subject, grants=GrantSet.of(["ticket.*"]),
        role="engineer", actor_tier="human",
        scope={"departments": ["engineering"], "verbs": ["ticket.read"]},
    )


def _invoke(client: TestClient, subject: str, context: dict):
    return client.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.read",
              "params": {"id": "missing"}, "context": context},
        headers=_hdr(subject),
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
def test_invoke_refuses_a_run_id_belonging_to_another_user():
    kernel = asyncio.run(_kernel())
    client = TestClient(create_app(kernel, platform={}))

    denied = _invoke(client, "mallory", {"run_id": VICTIM_RUN})
    assert denied.status_code == 403, "mallory joined victoria's run"
    assert denied.json()["reason"] == "not your run"

    # parent_run_id is the same claim one level up, and is fenced identically.
    denied_parent = _invoke(client, "mallory", {"parent_run_id": VICTIM_RUN})
    assert denied_parent.status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
def test_invoke_still_admits_the_runs_own_owner_and_an_unowned_run():
    kernel = asyncio.run(_kernel())
    client = TestClient(create_app(kernel, platform={}))

    # The owner reaching her own run is untouched (404 is the ticket adapter's
    # ordinary not-found, i.e. the call went through the fence and dispatched).
    assert _invoke(client, "victoria", {"run_id": VICTIM_RUN}).status_code == 404
    # A run id nobody owns impersonates nobody, and confers nothing: run-scoped
    # credentials are separately owner-bound. It stays usable as a correlation
    # label, which is what several callers have always used it for.
    assert _invoke(client, "mallory", {"run_id": "run-i-just-made-up"}).status_code == 404
    # No run id at all is the common case and must not regress.
    assert _invoke(client, "mallory", {}).status_code == 404


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
def test_spawn_refuses_a_parent_run_belonging_to_another_user(monkeypatch):
    """Worse here than at invoke: ``_inherit_adapter_bearer`` copies the PARENT
    run's sealed bearer onto the child, so an unchecked parent_run_id laundered a
    stranger's downstream credential into a run the caller owns outright.

    Driven through the REAL ``make_app_spawner`` seam, which is where the fence
    lives; a substituted spawner would route around the thing under test."""
    kernel = asyncio.run(_kernel())
    calls: list[str | None] = []

    async def fake_spawn(self, **kwargs):
        calls.append(kwargs["context"].parent_run_id)
        return {"run_id": "captured", "status": "ok"}

    monkeypatch.setattr(Spawner, "spawn", fake_spawn)
    app_spawner = make_app_spawner(kernel)
    body = SpawnBody(task="x", context={"parent_run_id": VICTIM_RUN})

    with pytest.raises(HTTPException) as denied:
        asyncio.run(app_spawner(_principal("mallory"), body))
    assert denied.value.status_code == 403
    assert calls == [], "the spawn ran before the fence could refuse it"

    asyncio.run(app_spawner(_principal("victoria"), body))
    assert calls == [VICTIM_RUN], "the run's own owner must still be able to spawn under it"


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
def test_the_fence_is_not_scoped_away_by_a_foreign_workspace():
    """Existence is checked without the workspace fence on purpose. Scoping the
    lookup would report a run in another workspace as "no such run", and the
    no-such-run branch is the permissive one - so the further the caller is from
    the run, the weaker the check would get."""
    kernel = asyncio.run(_kernel())
    client = TestClient(create_app(kernel, platform={}))
    headers = {**_hdr("mallory"), "x-boltrig-workspace": "ws-somewhere-else"}
    denied = client.post(
        "/v1/invoke",
        json={"noun": "ticket", "verb": "ticket.read", "params": {"id": "missing"},
              "context": {"run_id": VICTIM_RUN}},
        headers=headers,
    )
    assert denied.status_code == 403
