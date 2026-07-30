"""Desired/observed projection for versioned permanent-fleet state."""

from __future__ import annotations

import re
from typing import Any, Callable

from boltrig.models import PermanentFleetObservation, utcnow


def _heads(desired: dict[str, Any]) -> list[dict[str, Any]]:
    return [desired["chief"], *desired["departments"]]


async def _desired_projection_state(
    store: Any, tenant_id: str, desired: dict[str, Any]
) -> tuple[bool, str]:
    capabilities = {
        item.name: item
        for item in await store.list_all_capabilities(tenant_id)
    }
    profiles_match = all(
        (
            (row := capabilities.get(head["name"])) is not None
            and row.source == "manifest"
            and row.is_active
            and not row.is_ephemeral
            and row.runtime == head["runtime"]
            and row.model_endpoint == head["model_endpoint"]
            and row.supported_skills == head["supported_skills"]
            and row.max_depth == head["max_depth"]
            and row.cost_tier == head["cost_tier"]
        )
        for head in _heads(desired)
    )
    authored_budgets = [
        (head, index == 0)
        for index, head in enumerate(_heads(desired))
        if head["budget"] is not None
    ]
    if not authored_budgets:
        return profiles_match, "not_authored"
    budgets_match = True
    for head, chief in authored_budgets:
        row = await store.get_budget(
            tenant_id, tenant_id if chief else head["routing_id"]
        )
        value = head["budget"]
        budgets_match = budgets_match and bool(
            row is not None
            and row.scope_type == ("tenant" if chief else "department")
            and row.token_limit == value["token_limit"]
            and row.cost_limit_micros == value["cost_limit_micros"]
            and row.hard_stop == value["hard_stop"]
            and row.window == value["window"]
        )
    return profiles_match, (
        "projected" if budgets_match else "desired_awaiting_manifest_apply"
    )


def _field_state(
    startup_fields: set[str], budget_projection: str
) -> dict[str, str]:
    constructed = {
        name: (
            "startup_constructed_liveness_unknown"
            if name in startup_fields
            else "awaiting_worker_restart"
        )
        for name in (
            "department_routing_identity",
            "department_supported_skills",
            "chief_routing_identity",
            "chief_supported_skills",
        )
    }
    prompt_policy = {
        name: (
            "startup_prompt_policy_consumed_runtime_liveness_unknown"
            if name in startup_fields
            else "awaiting_worker_restart"
        )
        for name in ("purpose", "brief")
    }
    runtime_policy = {
        name: (
            "startup_policy_consumed_runtime_liveness_unknown"
            if name in startup_fields
            else "awaiting_worker_restart"
        )
        for name in ("runtime", "model_endpoint", "max_depth", "cost_tier")
    }
    return {
        **constructed,
        "budget_policy": budget_projection,
        **prompt_policy,
        **runtime_policy,
    }


def _observation_view(row: Any) -> dict[str, Any]:
    return {
        "worker_id": row.worker_id,
        "generation": row.generation,
        "status": row.status,
        "apply_mode": row.apply_mode,
        "applied_fields": row.applied_fields,
        "inactive_fields": row.inactive_fields,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
    }


async def permanent_fleet_view(
    store: Any,
    tenant_id: str,
    *,
    latest_revision: Callable[..., Any],
    normalise: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    revision = await latest_revision(store, tenant_id)
    observations = await store.list_permanent_fleet_observations(tenant_id)
    if revision is None:
        return {
            "status": "not_configured",
            "hierarchy": None,
            "generation": None,
            "revision": None,
            "apply_state": "not_configured",
            "observations": [],
        }
    desired = normalise(revision.payload["hierarchy"])
    profiles_reconciled, budget_projection = await _desired_projection_state(
        store, tenant_id, desired
    )
    matching = [
        row
        for row in observations
        if row.generation == revision.version and row.status == "applied"
    ]
    startup_fields = {
        field for row in matching for field in row.applied_fields
    }
    projection_pending = (
        not profiles_reconciled
        or budget_projection == "desired_awaiting_manifest_apply"
    )
    return {
        "status": "configured",
        "hierarchy": desired,
        "generation": revision.version,
        "revision": revision.id,
        "apply_state": (
            "startup_applied_liveness_unknown" if matching else "restart_required"
        ),
        "hot_applied": False,
        "runtime_liveness": "unknown_not_probed_by_startup",
        "profiles_reconciled": profiles_reconciled,
        "reconcile_at": (
            "next_manifest_apply_or_redeploy" if projection_pending else None
        ),
        "projection_state": {
            "persistent_profiles": (
                "projected"
                if profiles_reconciled
                else "desired_awaiting_manifest_apply"
            ),
            "budget_policy": budget_projection,
        },
        "observations": [_observation_view(row) for row in observations],
        "field_state": _field_state(startup_fields, budget_projection),
    }


async def record_permanent_fleet_startup_observation(
    store: Any,
    tenant_id: str,
    worker_id: str,
    *,
    latest_revision: Callable[..., Any],
) -> str | None:
    revision = await latest_revision(store, tenant_id)
    if revision is None:
        return None
    identity = str(worker_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", identity):
        raise ValueError("worker_id is invalid")
    await store.upsert_permanent_fleet_observation(
        PermanentFleetObservation(
            tenant_id=tenant_id,
            worker_id=identity,
            generation=revision.version,
            status="applied",
            apply_mode="startup_snapshot",
            applied_fields=[
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
            ],
            inactive_fields=[],
            observed_at=utcnow(),
        )
    )
    return revision.version
