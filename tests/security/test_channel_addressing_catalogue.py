"""Backend-owned channel addressing choices and honest stale projection."""

from __future__ import annotations

import asyncio
import json

import pytest

from boltrig.config.channel_addressing import (
    validate_channel_addressing_config,
    validate_channel_policy_config,
)
from boltrig.config.permanent_fleet import (
    PERMANENT_FLEET_KIND,
    PERMANENT_FLEET_REF,
    normalise_permanent_fleet,
    permanent_fleet_generation,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal
from boltrig.kernel.channel_inventory_routes import list_channels
from boltrig.models import (
    Channel,
    ConfigRevision,
    GrantSet,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore

T = "channel-addressing-catalogue"


def _hierarchy() -> dict:
    return normalise_permanent_fleet(
        {
            "chief": {
                "name": "chief-of-staff",
                "routing_id": "cos",
                "purpose": "Coordinate work",
                "runtime": "codex",
                "supported_skills": ["*"],
            },
            "departments": [
                {
                    "name": "research-head",
                    "routing_id": "research",
                    "purpose": "Own research",
                    "runtime": "codex",
                    "supported_skills": ["research"],
                },
                {
                    "name": "finance-head",
                    "routing_id": "finance",
                    "purpose": "Own finance",
                    "runtime": "codex",
                    "supported_skills": ["finance"],
                },
            ],
        }
    )


async def _seed() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    hierarchy = _hierarchy()
    await store.add_config_revision(
        ConfigRevision(
            tenant_id=T,
            kind=PERMANENT_FLEET_KIND,
            ref=PERMANENT_FLEET_REF,
            version=permanent_fleet_generation(hierarchy),
            payload={"hierarchy": hierarchy},
            actor="test",
        )
    )
    for workflow_id, workspace_id, status in (
        ("org-report", None, "active"),
        ("workspace-report", "ws-1", "active"),
        ("other-workspace", "ws-2", "active"),
        ("archived-report", None, "archived"),
    ):
        await store.upsert_workflow(
            WorkflowDefinition(
                id=workflow_id,
                tenant_id=T,
                version="v1",
                source=WorkflowSource.PRECREATED,
                definition={"_boltrig_lifecycle": {"status": status}},
                workspace_id=workspace_id,
            )
        )
    await store.upsert_channel(
        Channel(
            id="ch-stale",
            tenant_id=T,
            platform="webhook",
            name="Stale route",
            transport="webhook",
            config={
                "addressing": {
                    "default_target": "arbitrary-agent",
                    "routes": {
                        "known": "workflow:workspace-report",
                        "gone": "workflow:deleted",
                    },
                }
            },
        )
    )
    return Kernel(store), store


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_channel_inventory_projects_scoped_targets_and_stale_routes_honestly():
    kernel, _ = asyncio.run(_seed())
    response = asyncio.run(
        list_channels(
            kernel,
            Principal(
                tenant_id=T,
                subject="lead",
                role="department-head",
                scope={"departments": ["research"]},
                active_workspace_id="ws-1",
            ),
        )
    )
    assert response.status_code == 200
    body = json.loads(response.body)
    catalogue = body["addressing_catalogue"]
    assert catalogue["supports_arbitrary_agent_pinning"] is False
    assert [target["id"] for target in catalogue["targets"]] == [
        "cos",
        "research",
        "workflow:org-report",
        "workflow:workspace-report",
    ]
    research = catalogue["targets"][1]
    assert research["state"] == "restart_required"
    assert research["runtime_liveness"] == "unknown_not_probed_by_catalogue"

    addressing = body["channels"][0]["addressing"]
    assert addressing["effective_default_target"] == "arbitrary-agent"
    assert addressing["default_target_state"] == "stale_or_unsupported"
    assert addressing["valid"] is False
    assert {row["thread"]: row["state"] for row in addressing["routes"]} == {
        "known": "available",
        "gone": "stale_or_unsupported",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_authored_channel_targets_are_validated_against_runtime_contract():
    _, store = asyncio.run(_seed())
    asyncio.run(
        validate_channel_addressing_config(
            store,
            T,
            "ws-1",
            {"addressing": {"default_target": "research"}},
            allowed_departments=["research"],
        )
    )
    asyncio.run(
        validate_channel_addressing_config(
            store,
            T,
            "ws-1",
            {"addressing": {"routes": {"thread": "workflow:workspace-report"}}},
            allowed_departments=["research"],
        )
    )
    with pytest.raises(ValueError, match="unsupported channel addressing target"):
        asyncio.run(
            validate_channel_addressing_config(
                store,
                T,
                "ws-1",
                {"addressing": {"default_target": "arbitrary-agent"}},
                allowed_departments=["research"],
            )
        )
    with pytest.raises(ValueError, match="thread keys"):
        asyncio.run(
            validate_channel_addressing_config(
                store,
                T,
                "ws-1",
                {"addressing": {"routes": {"": "cos"}}},
                allowed_departments=["research"],
            )
        )
    with pytest.raises(ValueError, match="unsupported channel addressing target"):
        asyncio.run(
            validate_channel_addressing_config(
                store,
                T,
                "ws-1",
                {"addressing": {"default_target": "workflow:other-workspace"}},
                allowed_departments=["research"],
            )
        )
    with pytest.raises(ValueError, match="unsupported channel addressing target"):
        asyncio.run(
            validate_channel_addressing_config(
                store,
                T,
                "ws-1",
                {"addressing": {"default_target": "finance"}},
                allowed_departments=["research"],
            )
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-180")
def test_self_onboarding_policy_is_member_only_and_author_scope_bounded():
    _, store = asyncio.run(_seed())
    asyncio.run(
        validate_channel_policy_config(
            store,
            T,
            "ws-1",
            {
                "self_onboard": {
                    "role": "member",
                    "scope": {"departments": ["research"]},
                    "welcome": "Welcome",
                }
            },
            allowed_departments=["research"],
        )
    )
    for onboarding in (
        {"role": "admin", "scope": {"departments": ["research"]}},
        {"role": "member", "scope": {"departments": ["finance"]}},
        {"role": "member", "scope": {"all": True}},
    ):
        with pytest.raises(ValueError, match="self-onboarding"):
            asyncio.run(
                validate_channel_policy_config(
                    store,
                    T,
                    "ws-1",
                    {"self_onboard": onboarding},
                    allowed_departments=["research"],
                )
            )
