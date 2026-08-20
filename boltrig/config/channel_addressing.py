"""Canonical, browser-safe channel addressing catalogue and validation.

Channels address declared durable named peers or workflows. Unknown slugs are
never inferred or routed through a hierarchy: the flat worker pump parks them.
"""

from __future__ import annotations

from typing import Any

from .permanent_fleet import permanent_fleet_view


def _workflow_is_active(workflow: Any) -> bool:
    lifecycle = workflow.definition.get("_boltrig_lifecycle") or {}
    return not isinstance(lifecycle, dict) or lifecycle.get("status", "active") == "active"


def _workspace_visible(workflow: Any, workspace_id: str | None) -> bool:
    return workflow.workspace_id is None or workflow.workspace_id == workspace_id


async def _workflow_targets(
    store: Any, tenant_id: str, workspace_id: str | None
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    workflows = sorted(
        await store.list_workflows(tenant_id), key=lambda workflow: workflow.id
    )
    for workflow in workflows:
        if not _workspace_visible(workflow, workspace_id) or not _workflow_is_active(workflow):
            continue
        targets.append(
            {
                "id": f"workflow:{workflow.id}",
                "kind": "workflow",
                "label": workflow.id,
                "state": "available",
                "runtime_liveness": "not_applicable",
            }
        )
    return targets


async def channel_addressing_catalogue(
    store: Any,
    tenant_id: str,
    workspace_id: str | None,
    *,
    allowed_departments: list[str] | None = None,
) -> dict[str, Any]:
    """Project only targets the runtime can resolve, scoped for this caller."""
    targets: list[dict[str, Any]] = []
    roster = await store.list_named_agents(tenant_id)
    default_target = next(
        (agent.address for agent in roster if agent.default_for_intake),
        roster[0].address if roster else "cos",
    )
    visible = None if allowed_departments is None else set(allowed_departments)
    for agent in roster:
        if visible is not None and agent.scope_id and agent.scope_id not in visible:
            continue
        targets.append(
            {
                "id": agent.address,
                "kind": "named_agent",
                "label": agent.name,
                "state": "available",
                "default": agent.default_for_intake,
                "scope_id": agent.scope_id,
                "runtime_liveness": "unknown_not_probed_by_catalogue",
            }
        )

    # Read compatibility for a database awaiting its next manifest projection.
    # Runtime composition never rebuilds this hierarchy.
    if not roster:
        targets.append(
            {
                "id": "cos",
                "kind": "named_agent",
                "label": "Default agent",
                "state": "available",
                "default": True,
                "runtime_liveness": "unknown_not_probed_by_catalogue",
            }
        )
        fleet = await permanent_fleet_view(store, tenant_id)
        hierarchy = fleet.get("hierarchy")
    else:
        hierarchy = None
    if isinstance(hierarchy, dict):
        department_state = (
            "startup_constructed_liveness_unknown"
            if fleet.get("apply_state") == "startup_applied_liveness_unknown"
            else "restart_required"
        )
        for department in hierarchy.get("departments") or []:
            routing_id = str(department.get("routing_id") or "")
            if not routing_id or (visible is not None and routing_id not in visible):
                continue
            targets.append(
                {
                    "id": routing_id,
                    "kind": "named_agent",
                    "label": str(department.get("name") or routing_id),
                    "state": department_state,
                    "runtime_liveness": "unknown_not_probed_by_catalogue",
                }
            )

    targets.extend(await _workflow_targets(store, tenant_id, workspace_id))

    return {
        "targets": targets,
        "default_target": default_target,
        "supports_arbitrary_agent_pinning": True,
        "scope": {
            "workspace_id": workspace_id,
            "departments": (
                "all" if allowed_departments is None else list(allowed_departments)
            ),
        },
    }


def project_channel_addressing(
    config: dict[str, Any] | None,
    catalogue: dict[str, Any],
) -> dict[str, Any]:
    """Describe configured/effective targets without treating stale data as live."""
    addressing = (config or {}).get("addressing") or {}
    if not isinstance(addressing, dict):
        addressing = {}
    known = {
        str(target["id"]): target
        for target in catalogue.get("targets") or []
        if isinstance(target, dict) and target.get("id")
    }
    configured = addressing.get("default_target")
    configured_default = configured if isinstance(configured, str) and configured else None
    effective_default = configured_default or str(
        catalogue.get("default_target") or "cos"
    )

    projected_routes = []
    routes = addressing.get("routes") or {}
    if isinstance(routes, dict):
        for thread, target in routes.items():
            target_id = target if isinstance(target, str) else ""
            projected_routes.append(
                {
                    "thread": str(thread),
                    "target": target_id,
                    "state": (
                        known[target_id]["state"]
                        if target_id in known
                        else "stale_or_unsupported"
                    ),
                }
            )

    default = known.get(effective_default)
    valid = default is not None and all(
        route["state"] != "stale_or_unsupported" for route in projected_routes
    )
    return {
        "configured_default_target": configured_default,
        "effective_default_target": effective_default,
        "default_target_state": (
            default["state"] if default is not None else "stale_or_unsupported"
        ),
        "routes": projected_routes,
        "valid": valid,
    }


async def validate_channel_addressing_config(
    store: Any,
    tenant_id: str,
    workspace_id: str | None,
    config: dict[str, Any],
    *,
    allowed_departments: list[str] | None = None,
) -> None:
    """Reject target claims the runtime cannot resolve as authored."""
    addressing = config.get("addressing")
    if addressing is None:
        return
    if not isinstance(addressing, dict):
        raise ValueError("channel addressing must be an object")
    routes = addressing.get("routes", {})
    if not isinstance(routes, dict):
        raise ValueError("channel addressing routes must be an object")
    if len(routes) > 100:
        raise ValueError("channel addressing supports at most 100 thread routes")
    if any(
        not isinstance(thread, str)
        or not thread.strip()
        or len(thread) > 512
        for thread in routes
    ):
        raise ValueError("channel addressing thread keys must be non-empty strings")

    catalogue = await channel_addressing_catalogue(
        store,
        tenant_id,
        workspace_id,
        allowed_departments=allowed_departments,
    )
    known = {str(item["id"]) for item in catalogue["targets"]}
    values: list[Any] = []
    if "default_target" in addressing:
        values.append(addressing["default_target"])
    values.extend(routes.values())
    for target in values:
        if not isinstance(target, str) or not target.strip() or target not in known:
            raise ValueError(f"unsupported channel addressing target: {target!r}")


def _validate_self_onboarding(
    config: dict[str, Any],
    *,
    allowed_departments: list[str] | None,
) -> None:
    onboarding = config.get("self_onboard")
    if onboarding is None:
        return
    if not isinstance(onboarding, dict):
        raise ValueError("channel self-onboarding must be an object")
    if str(onboarding.get("role") or "") != "member":
        raise ValueError("channel self-onboarding role must be member")
    scope = onboarding.get("scope", {})
    if not isinstance(scope, dict) or set(scope) - {"departments"}:
        raise ValueError(
            "channel self-onboarding scope supports departments only"
        )
    departments = scope.get("departments", [])
    if (
        not isinstance(departments, list)
        or len(departments) > 32
        or any(
            not isinstance(department, str)
            or not department.strip()
            or len(department) > 128
            for department in departments
        )
        or len(set(departments)) != len(departments)
    ):
        raise ValueError(
            "channel self-onboarding departments must be unique bounded strings"
        )
    if allowed_departments is not None and not set(departments).issubset(
        allowed_departments
    ):
        raise ValueError(
            "channel self-onboarding departments exceed the author scope"
        )
    welcome = onboarding.get("welcome", "")
    if not isinstance(welcome, str) or len(welcome) > 2000:
        raise ValueError(
            "channel self-onboarding welcome must be at most 2000 characters"
        )


async def validate_channel_policy_config(
    store: Any,
    tenant_id: str,
    workspace_id: str | None,
    config: dict[str, Any],
    *,
    allowed_departments: list[str] | None = None,
) -> None:
    """Validate every consumed channel-policy field at the governed write seam."""
    await validate_channel_addressing_config(
        store,
        tenant_id,
        workspace_id,
        config,
        allowed_departments=allowed_departments,
    )
    _validate_self_onboarding(
        config, allowed_departments=allowed_departments
    )


__all__ = [
    "channel_addressing_catalogue",
    "project_channel_addressing",
    "validate_channel_addressing_config",
    "validate_channel_policy_config",
]
