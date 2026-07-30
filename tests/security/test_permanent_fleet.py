"""Permanent fleet desired/observed truth and safe-boundary projection."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.config.admin import AdminConfig
from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.config.manifest import FleetManifest, apply_manifest
from boltrig.config.permanent_fleet import (
    latest_permanent_fleet_revision,
    normalise_permanent_fleet,
    record_permanent_fleet_startup_observation,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    AgentCapability,
    Budget,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "permanent-fleet"


def _hierarchy(*, department_name: str = "research-head") -> dict:
    return {
        "chief": {
            "name": "chief-of-staff",
            "routing_id": "cos",
            "purpose": "Coordinate work across departments",
            "brief": "Stored chief brief",
            "runtime": "codex",
            "model_endpoint": None,
            "supported_skills": ["*"],
            "max_depth": 4,
            "cost_tier": "standard",
            "budget": {
                "token_limit": 50_000,
                "cost_limit_micros": 250_000,
                "hard_stop": True,
                "window": "monthly",
            },
        },
        "departments": [
            {
                "name": department_name,
                "routing_id": "research",
                "purpose": "Own research work",
                "brief": "Stored research brief",
                "runtime": "script",
                "model_endpoint": None,
                "supported_skills": ["research"],
                "max_depth": 3,
                "cost_tier": "cheap",
                "budget": {
                    "token_limit": 10_000,
                    "cost_limit_micros": 50_000,
                    "hard_stop": True,
                    "window": "monthly",
                },
            }
        ],
    }


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        actor="author",
        actor_tier="human",
        run_id="permanent-fleet-apply",
        grants=GrantSet.of(["*"]),
        extra={"principal_role": "org-admin", "principal_scope": {"all": True}},
    )


async def _kernel(store: InMemoryStore | None = None):
    store = store or InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    admin = AdminConfig(
        store,
        tenant_id=T,
        doc={"organisation": "Test", "tenant_id": T},
    )
    kernel = Kernel(store)
    await kernel.register_adapter(
        T,
        build_control_plane_adapter(
            store,
            loader=kernel.loader,
            registry=kernel.registry,
            admin=admin,
        ),
    )
    return kernel, admin


async def _approved_apply(kernel: Kernel, hierarchy: dict) -> dict:
    params = {"hierarchy": hierarchy}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control", "control.permanent_fleet.apply", params, _context()
        )
    request_id = held.value.hitl_request_id
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    return await kernel.invoke(
        "control",
        "control.permanent_fleet.apply",
        params,
        _context(),
        approval_id=request_id,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-27")
async def test_desired_write_is_single_revision_and_projects_only_on_manifest_apply():
    kernel, admin = await _kernel()
    await kernel.store.upsert_capability(
        AgentCapability(
            name="governed-profile",
            tenant_id=T,
            runtime="script",
            supported_skills=["*"],
            max_depth=1,
            is_ephemeral=True,
            cost_tier="cheap",
            source="control-plane",
        )
    )
    await kernel.store.upsert_budget_policy(
        Budget(
            id="research",
            tenant_id=T,
            scope_type="department",
            token_limit=1,
            spent_tokens=321,
            spent_micros=654,
            window="monthly",
        )
    )

    result = await _approved_apply(kernel, _hierarchy())
    assert result["apply_state"] == "restart_required"
    assert result["hot_applied"] is False
    assert result["profiles_reconciled"] is False
    assert result["reconcile_at"] == "next_manifest_apply_or_redeploy"
    assert {
        row.name for row in await kernel.store.list_all_capabilities(T)
    } == {"governed-profile"}
    before = await kernel.store.get_budget(T, "research")
    assert before is not None and before.token_limit == 1

    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }
    client = TestClient(create_app(kernel, platform={"admin": admin}))
    viewer = client.get(
        "/v1/permanent-fleet",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "viewer",
            "x-boltrig-role": "viewer",
        },
    )
    assert viewer.status_code == 403
    desired = client.get("/v1/permanent-fleet", headers=author)
    assert desired.status_code == 200
    assert desired.json()["apply_state"] == "restart_required"
    assert desired.json()["profiles_reconciled"] is False
    assert (
        desired.json()["projection_state"]["budget_policy"]
        == "desired_awaiting_manifest_apply"
    )
    exported = client.post("/v1/admin/config/export", headers=author)
    assert exported.status_code == 200
    assert (
        exported.json()["manifest"]["hierarchy"]["tier2"][0]["department"]
        == "research"
    )

    # The existing safe manifest boundary performs the declarative projection.
    await apply_manifest(
        kernel,
        FleetManifest(organisation="Test", tenant_id=T),
        load_builtin_adapters=False,
        confirm_bulk_deactivate=True,
    )
    projected = {
        row.name: row for row in await kernel.store.list_all_capabilities(T)
    }
    assert projected["governed-profile"].source == "control-plane"
    assert projected["chief-of-staff"].is_ephemeral is False
    assert projected["research-head"].runtime == "script"
    after = await kernel.store.get_budget(T, "research")
    assert after is not None
    assert after.token_limit == 10_000
    assert (after.spent_tokens, after.spent_micros) == (321, 654)
    view = client.get("/v1/permanent-fleet", headers=author).json()
    assert view["profiles_reconciled"] is True
    assert view["projection_state"]["budget_policy"] == "projected"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_direct_fleet_route_finalizes_with_caller_held_approval():
    kernel, admin = await _kernel()
    client = TestClient(create_app(kernel, platform={"admin": admin}))
    author = {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": "author",
        "x-boltrig-role": "org-admin",
    }
    body = {"hierarchy": _hierarchy()}

    pending = client.put("/v1/permanent-fleet", headers=author, json=body)
    assert pending.status_code == 202
    approval_id = pending.json()["hitl_request_id"]
    await kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")

    completed = client.put(
        "/v1/permanent-fleet",
        headers={**author, "x-boltrig-approval-id": approval_id},
        json=body,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "ok"
    assert completed.json()["apply_state"] == "restart_required"
    desired = client.get("/v1/permanent-fleet", headers=author).json()
    assert desired["generation"] == completed.json()["generation"]
    assert desired["hierarchy"] == body["hierarchy"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-27")
async def test_startup_snapshot_never_claims_current_worker_liveness_or_inactive_fields():
    kernel, admin = await _kernel()
    await _approved_apply(kernel, _hierarchy())
    generation = await record_permanent_fleet_startup_observation(
        kernel.store, T, "worker-1"
    )
    assert generation is not None

    client = TestClient(create_app(kernel, platform={"admin": admin}))
    response = client.get(
        "/v1/permanent-fleet",
        headers={
            "x-boltrig-tenant": T,
            "x-boltrig-subject": "author",
            "x-boltrig-role": "org-admin",
        },
    ).json()
    assert response["apply_state"] == "startup_applied_liveness_unknown"
    assert response["runtime_liveness"] == "unknown_not_probed_by_startup"
    assert response["field_state"]["purpose"] == (
        "startup_prompt_policy_consumed_runtime_liveness_unknown"
    )
    assert response["field_state"]["chief_routing_identity"] == (
        "startup_constructed_liveness_unknown"
    )
    assert response["field_state"]["runtime"] == (
        "startup_policy_consumed_runtime_liveness_unknown"
    )
    assert response["field_state"]["model_endpoint"] == (
        "startup_policy_consumed_runtime_liveness_unknown"
    )
    observation = response["observations"][0]
    assert observation["applied_fields"] == [
        "department_routing_identity",
        "department_supported_skills",
        "chief_routing_identity",
        "chief_supported_skills",
        "purpose",
        "brief",
        "runtime",
        "model_endpoint",
        "max_depth",
        "cost_tier",
    ]
    assert observation["inactive_fields"] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-27")
async def test_closed_hierarchy_and_revision_failure_leave_no_false_desired_state():
    invalid = _hierarchy()
    invalid["departments"][0]["routing_id"] = "cos"
    with pytest.raises(ValueError):
        normalise_permanent_fleet(invalid)

    class FailingRevisionStore(InMemoryStore):
        fail_permanent_revision = False

        async def add_config_revision(self, revision):
            if (
                self.fail_permanent_revision
                and revision.kind == "permanent_fleet"
            ):
                raise RuntimeError("revision store unavailable")
            return await super().add_config_revision(revision)

    store = FailingRevisionStore()
    kernel, admin = await _kernel(store)
    params = {"hierarchy": _hierarchy()}
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke(
            "control", "control.permanent_fleet.apply", params, _context()
        )
    await kernel.hitl.answer(T, held.value.hitl_request_id, "approve", "reviewer")
    store.fail_permanent_revision = True
    with pytest.raises(RuntimeError, match="revision store unavailable"):
        await kernel.invoke(
            "control",
            "control.permanent_fleet.apply",
            params,
            _context(),
            approval_id=held.value.hitl_request_id,
        )
    assert await latest_permanent_fleet_revision(store, T) is None
    assert admin.section("hierarchy") is None
    assert await store.list_all_capabilities(T) == []
