"""Caller-owned delegated-agent approval posture (SEC-197)."""

import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.approval_posture import (
    ApprovalPosture,
    persist_approval_posture,
)
from boltrig.models import (
    Consequence,
    GrantMissing,
    GrantSet,
    PendingHuman,
    RateLimit,
    RateLimited,
    UserSetting,
)
from tests.conftest import TENANT, _build_kernel, make_ctx


async def _make_ticket_high(kernel) -> None:
    verb = await kernel.store.get_verb(TENANT, "ticket.create")
    assert verb is not None
    await kernel.store.upsert_verb(replace(verb, consequence=Consequence.HIGH))


def _agent(owner: str = "alice"):
    return make_ctx(
        ["ticket.create"],
        actor="chief-of-staff",
        actor_tier="tier1",
        on_behalf_of=owner,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
def test_posture_http_contract_is_interactive_confirmed_scoped_and_audited() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))
    headers = {
        "x-boltrig-tenant": TENANT,
        "x-boltrig-subject": "alice",
        "x-boltrig-tier": "human",
    }

    default = client.get("/v1/me/approval-posture", headers=headers)
    assert default.status_code == 200
    assert default.json() == {
        "posture": "risk_based",
        "source": "safe_default",
        "enforcement": {
            "applies_to": "delegated_agent_adapter_calls",
            "workspace_blocking_verbs_remain": True,
            "control_plane_approvals_remain": True,
            "direct_human_consequence_gate_remains": True,
            "authority_is_never_widened": True,
        },
    }
    assert client.put(
        "/v1/me/approval-posture",
        headers=headers,
        json={"posture": "unlimited"},
    ).status_code == 400
    assert client.put(
        "/v1/me/approval-posture",
        headers=headers,
        json={"posture": "full_access"},
    ).status_code == 400
    assert client.put(
        "/v1/me/settings",
        headers=headers,
        json={"key": "agentic.approval_posture", "value": "full_access"},
    ).status_code == 400

    changed = client.put(
        "/v1/me/approval-posture",
        headers=headers,
        json={"posture": "full_access", "confirm": "full_access"},
    )
    assert changed.status_code == 200
    assert changed.json()["posture"] == "full_access"
    assert changed.json()["source"] == "user_override"
    assert client.get("/v1/me/approval-posture", headers=headers).json()["posture"] == "full_access"

    events = asyncio.run(kernel.store.audit_query(TENANT))
    event = next(event for event in events if event.verb == "approval_posture.update")
    assert event.actor == "alice"
    assert event.detail == {"posture": "full_access"}


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
def test_machine_bearer_cannot_change_the_owners_posture() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())

    async def pat_principal(_request):
        return Principal(
            tenant_id=TENANT,
            subject="alice",
            grants=GrantSet.of(["*"]),
            role="org-admin",
            actor_tier="human",
            credential_kind="pat",
        )

    client = TestClient(create_app(kernel, principal_resolver=pat_principal))
    denied = client.put(
        "/v1/me/approval-posture",
        json={"posture": "full_access", "confirm": "full_access"},
    )
    assert denied.status_code == 403
    assert denied.json()["reason"] == "an interactive human session is required"


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
async def test_ask_and_risk_based_postures_drive_only_delegated_adapter_prompts() -> None:
    ask_kernel, _adapter = await _build_kernel()
    await persist_approval_posture(
        ask_kernel.store, TENANT, "alice", ApprovalPosture.ALWAYS_ASK
    )
    with pytest.raises(PendingHuman):
        await ask_kernel.invoke(
            "ticket", "ticket.create", {"title": "ask"}, _agent()
        )

    risk_kernel, _adapter = await _build_kernel()
    result = await risk_kernel.invoke(
        "ticket", "ticket.create", {"title": "safe"}, _agent()
    )
    assert result["status"] == "open"


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
async def test_full_access_never_bypasses_blocks_control_gates_or_grants() -> None:
    blocked_kernel, _adapter = await _build_kernel(blocking_verbs={"ticket.create"})
    await persist_approval_posture(
        blocked_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    with pytest.raises(PendingHuman):
        await blocked_kernel.invoke(
            "ticket", "ticket.create", {"title": "blocked"}, _agent()
        )

    control_kernel, _adapter = await _build_kernel()
    await _make_ticket_high(control_kernel)
    binding = await control_kernel.store.get_binding(TENANT, "ticket.create")
    assert binding is not None
    await control_kernel.store.upsert_binding(replace(binding, target_ref="control"))
    await persist_approval_posture(
        control_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    with pytest.raises(PendingHuman):
        await control_kernel.invoke(
            "ticket", "ticket.create", {"title": "control"}, _agent()
        )

    grants_kernel, _adapter = await _build_kernel()
    await persist_approval_posture(
        grants_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    with pytest.raises(GrantMissing):
        await grants_kernel.invoke(
            "ticket",
            "ticket.create",
            {"title": "not granted"},
            make_ctx([], actor_tier="tier1", on_behalf_of="alice"),
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
async def test_full_access_is_owner_scoped_and_does_not_weaken_direct_human_calls() -> None:
    owner_kernel, _adapter = await _build_kernel()
    await _make_ticket_high(owner_kernel)
    binding = await owner_kernel.store.get_binding(TENANT, "ticket.create")
    assert binding is not None
    await owner_kernel.store.upsert_binding(replace(
        binding,
        rate_limit=RateLimit(per="minute", max=1, scope="tenant"),
    ))
    await persist_approval_posture(
        owner_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    result = await owner_kernel.invoke(
        "ticket", "ticket.create", {"title": "owner consent"}, _agent("alice")
    )
    assert result["status"] == "open"
    with pytest.raises(RateLimited):
        await owner_kernel.invoke(
            "ticket", "ticket.create", {"title": "still rate limited"}, _agent("alice")
        )
    events = await owner_kernel.store.audit_query(TENANT)
    assert any(event.verb == "ticket.create" and event.status == "ok" for event in events)

    other_kernel, _adapter = await _build_kernel()
    await _make_ticket_high(other_kernel)
    await persist_approval_posture(
        other_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    with pytest.raises(PendingHuman):
        await other_kernel.invoke(
            "ticket", "ticket.create", {"title": "other owner"}, _agent("bob")
        )

    direct_kernel, _adapter = await _build_kernel()
    await _make_ticket_high(direct_kernel)
    await persist_approval_posture(
        direct_kernel.store, TENANT, "alice", ApprovalPosture.FULL_ACCESS
    )
    with pytest.raises(PendingHuman):
        await direct_kernel.invoke(
            "ticket",
            "ticket.create",
            {"title": "direct"},
            make_ctx(
                ["ticket.create"],
                actor="alice",
                actor_tier="human",
                on_behalf_of="alice",
            ),
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-197")
async def test_malformed_stored_posture_falls_back_to_risk_based() -> None:
    kernel, _adapter = await _build_kernel()
    await _make_ticket_high(kernel)
    await kernel.store.upsert_user_setting(UserSetting(
        tenant_id=TENANT,
        user_id="alice",
        key="agentic.approval_posture",
        value="not-a-posture",
    ))
    with pytest.raises(PendingHuman):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "fail safe"}, _agent()
        )
