"""Versioned permanent-fleet desired state and honest apply projection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import (
    ConfigRevision,
    InvocationContext,
)

PERMANENT_FLEET_KIND = "permanent_fleet"
PERMANENT_FLEET_REF = "hierarchy"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
_ROUTING = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_RUNTIMES = frozenset({"codex", "script"})
_COST_TIERS = frozenset({"cheap", "standard", "expensive"})
_HEAD_KEYS = frozenset(
    {
        "name", "routing_id", "purpose", "brief", "runtime",
        "model_endpoint", "supported_skills", "max_depth", "cost_tier",
        "budget",
    }
)
_BUDGET_KEYS = frozenset(
    {"token_limit", "cost_limit_micros", "hard_stop", "window"}
)


def _closed(value: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} does not support: {', '.join(unknown)}")


def _bounded_text(value: Any, label: str, maximum: int, *, required: bool) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return text


def _normalise_budget(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("budget must be an object or null")
    _closed(value, _BUDGET_KEYS, "budget")
    token_limit = value.get("token_limit")
    cost_limit = value.get("cost_limit_micros")
    for label, item in (
        ("token_limit", token_limit),
        ("cost_limit_micros", cost_limit),
    ):
        if item is not None and (
            isinstance(item, bool) or not isinstance(item, int) or item < 0
        ):
            raise ValueError(f"{label} must be a non-negative integer or null")
    window = str(value.get("window") or "run")
    if window not in {"run", "daily", "monthly"}:
        raise ValueError("budget window must be run, daily, or monthly")
    return {
        "token_limit": token_limit,
        "cost_limit_micros": cost_limit,
        "hard_stop": bool(value.get("hard_stop", True)),
        "window": window,
    }


def _normalise_head(value: Any, *, chief: bool) -> dict[str, Any]:
    label = "chief" if chief else "department"
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _closed(value, _HEAD_KEYS, label)
    name = str(value.get("name") or "").strip()
    routing_id = str(value.get("routing_id") or "").strip()
    if not _NAME.fullmatch(name):
        raise ValueError(f"{label} name must be a lowercase profile slug")
    if chief:
        if routing_id != "cos":
            raise ValueError("chief routing_id must be cos")
    elif not _ROUTING.fullmatch(routing_id) or routing_id == "cos":
        raise ValueError("department routing_id must be a unique non-cos slug")
    runtime = str(value.get("runtime") or "codex")
    if runtime not in _RUNTIMES:
        raise ValueError("permanent runtime must be codex or script")
    model_endpoint = str(value.get("model_endpoint") or "").strip() or None
    skills = value.get("supported_skills", ["*"])
    if (
        not isinstance(skills, list)
        or not 1 <= len(skills) <= 64
        or any(
            not isinstance(skill, str)
            or not skill.strip()
            or len(skill.strip()) > 128
            for skill in skills
        )
    ):
        raise ValueError("supported_skills must contain 1-64 bounded strings")
    max_depth = value.get("max_depth", 3)
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 5:
        raise ValueError("max_depth must be an integer from 1 to 5")
    cost_tier = str(value.get("cost_tier") or "standard")
    if cost_tier not in _COST_TIERS:
        raise ValueError("cost_tier is invalid")
    return {
        "name": name,
        "routing_id": routing_id,
        "purpose": _bounded_text(
            value.get("purpose"), f"{label} purpose", 500, required=True
        ),
        "brief": _bounded_text(
            value.get("brief"), f"{label} brief", 8000, required=False
        ),
        "runtime": runtime,
        "model_endpoint": model_endpoint,
        "supported_skills": [str(skill).strip() for skill in skills],
        "max_depth": max_depth,
        "cost_tier": cost_tier,
        "budget": _normalise_budget(value.get("budget")),
    }


def normalise_permanent_fleet(value: Any) -> dict[str, Any]:
    """Validate the closed one-chief/many-departments hierarchy."""
    if not isinstance(value, dict):
        raise ValueError("permanent fleet must be an object")
    _closed(value, frozenset({"chief", "departments"}), "permanent fleet")
    chief = _normalise_head(value.get("chief"), chief=True)
    raw_departments = value.get("departments")
    if not isinstance(raw_departments, list) or not 1 <= len(raw_departments) <= 32:
        raise ValueError("permanent fleet requires 1-32 departments")
    departments = [
        _normalise_head(item, chief=False) for item in raw_departments
    ]
    names = [chief["name"], *(item["name"] for item in departments)]
    routes = [item["routing_id"] for item in departments]
    if len(names) != len(set(names)):
        raise ValueError("permanent fleet profile names must be unique")
    if len(routes) != len(set(routes)):
        raise ValueError("department routing_id values must be unique")
    return {"chief": chief, "departments": departments}


def permanent_fleet_generation(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "pf_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


async def latest_permanent_fleet_revision(store: Any, tenant_id: str):
    rows = await store.list_config_revisions(
        tenant_id, PERMANENT_FLEET_KIND, PERMANENT_FLEET_REF
    )
    return max(rows, key=lambda row: row.id or 0, default=None)


def _heads(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [value["chief"], *value["departments"]]


async def _validate_endpoints(store: Any, tenant_id: str, desired: dict[str, Any]) -> None:
    for head in _heads(desired):
        endpoint_id = head["model_endpoint"]
        if not endpoint_id:
            continue
        endpoint = await store.get_model_endpoint(tenant_id, endpoint_id)
        if endpoint is None or not endpoint.is_active:
            raise ValueError(f"model endpoint {endpoint_id!r} is missing or retired")


async def execute_permanent_fleet_operation(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    *,
    admin: Any = None,
) -> Result | None:
    if verb != "control.permanent_fleet.apply":
        return None
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(store, None, verb, params, context)
    if admin is None:
        raise ValueError("admin config is required for hierarchy round-trip")
    desired = normalise_permanent_fleet(params.get("hierarchy"))
    await _validate_endpoints(store, context.tenant_id, desired)
    generation = permanent_fleet_generation(desired)
    # The controlled mutation is one append-only desired-state write. Capability
    # and budget projection deliberately happens at the safe process boundary in
    # apply_manifest; mutating those rows here would be a partial hot apply and a
    # mid-loop failure could leave false parity.
    revision = await store.add_config_revision(
        ConfigRevision(
            tenant_id=context.tenant_id,
            kind=PERMANENT_FLEET_KIND,
            ref=PERMANENT_FLEET_REF,
            version=generation,
            payload={"hierarchy": desired},
            actor=context.actor,
        )
    )
    admin.overlay_section("hierarchy", manifest_hierarchy_section(desired))
    return Result.success(
        {
            "generation": generation,
            "revision": revision.id,
            "apply_state": "restart_required",
            "hot_applied": False,
            "profiles_reconciled": False,
            "reconcile_at": "next_manifest_apply_or_redeploy",
        }
    )


async def permanent_fleet_view(store: Any, tenant_id: str) -> dict[str, Any]:
    from .permanent_fleet_projection import permanent_fleet_view as project

    return await project(
        store,
        tenant_id,
        latest_revision=latest_permanent_fleet_revision,
        normalise=normalise_permanent_fleet,
    )


async def record_permanent_fleet_startup_observation(
    store: Any, tenant_id: str, worker_id: str
) -> str | None:
    """Record one exact generation after a worker constructed its pump.

    Callers must invoke this only *after* applying
    :func:`effective_manifest_from_desired` and constructing ``build_org``.
    Every listed field is construction evidence only: permanent runtimes resolve
    lazily on their first call, so this does not claim a hot reload, a live
    worker, a live model endpoint, or a successfully admitted Codex cell.
    """
    from .permanent_fleet_projection import (
        record_permanent_fleet_startup_observation as record,
    )

    return await record(
        store,
        tenant_id,
        worker_id,
        latest_revision=latest_permanent_fleet_revision,
    )


def hierarchy_from_manifest(manifest: Any) -> dict[str, Any] | None:
    hierarchy = manifest.hierarchy
    if hierarchy.tier1 is None or not hierarchy.tier2:
        return None

    def view(tier: Any, *, chief: bool) -> dict[str, Any]:
        budget = None
        if tier.budget is not None:
            budget = {
                "token_limit": tier.budget.token_limit,
                "cost_limit_micros": tier.budget.cost_limit_micros,
                "hard_stop": tier.budget.hard_stop,
                "window": tier.budget.window,
            }
        return {
            "name": tier.name,
            "routing_id": "cos" if chief else (tier.department or tier.name),
            "purpose": tier.purpose or (
                "Route work across departments"
                if chief else f"Own {tier.department or tier.name} work"
            ),
            "brief": tier.brief,
            "runtime": tier.runtime,
            "model_endpoint": tier.model_endpoint,
            "supported_skills": list(tier.supported_skills),
            "max_depth": tier.max_depth,
            "cost_tier": tier.cost_tier,
            "budget": budget,
        }

    return normalise_permanent_fleet(
        {
            "chief": view(hierarchy.tier1, chief=True),
            "departments": [
                view(tier, chief=False) for tier in hierarchy.tier2
            ],
        }
    )


def manifest_hierarchy_section(desired: dict[str, Any]) -> dict[str, Any]:
    """Project typed desired state into the canonical manifest hierarchy shape."""

    def view(head: dict[str, Any], *, chief: bool) -> dict[str, Any]:
        item = {
            "name": head["name"],
            "runtime": head["runtime"],
            "model_endpoint": head["model_endpoint"],
            "max_depth": head["max_depth"],
            "supported_skills": list(head["supported_skills"]),
            "cost_tier": head["cost_tier"],
            "purpose": head["purpose"],
            "brief": head["brief"],
        }
        if not chief:
            item["department"] = head["routing_id"]
        if head["budget"] is not None:
            item["budget"] = dict(head["budget"])
        return item

    return {
        "tier1": view(desired["chief"], chief=True),
        "tier2": [
            view(head, chief=False) for head in desired["departments"]
        ],
    }


async def overlay_permanent_fleet_export(
    store: Any, tenant_id: str, document: dict[str, Any]
) -> dict[str, Any]:
    """Return an Admin export with the latest governed hierarchy overlaid.

    AdminConfig is built synchronously from the file at process composition,
    while desired state is durable in the async store. Export/get routes call
    this helper so a restart cannot silently revert the exported hierarchy.
    """
    output = dict(document)
    revision = await latest_permanent_fleet_revision(store, tenant_id)
    if revision is None:
        return output
    desired = normalise_permanent_fleet(revision.payload["hierarchy"])
    output["hierarchy"] = manifest_hierarchy_section(desired)
    return output


async def effective_manifest_from_desired(store: Any, manifest: Any) -> Any:
    revision = await latest_permanent_fleet_revision(
        store, manifest.tenant_id
    )
    if revision is None:
        return manifest
    desired = normalise_permanent_fleet(revision.payload["hierarchy"])
    from .manifest import BudgetConfig, HierarchyConfig, HierarchyTier

    def tier(head: dict[str, Any], *, chief: bool) -> HierarchyTier:
        budget = (
            BudgetConfig(**head["budget"]) if head["budget"] is not None else None
        )
        return HierarchyTier(
            name=head["name"],
            runtime=head["runtime"],
            model_endpoint=head["model_endpoint"],
            max_depth=head["max_depth"],
            supported_skills=tuple(head["supported_skills"]),
            cost_tier=head["cost_tier"],
            department=None if chief else head["routing_id"],
            budget=budget,
            purpose=head["purpose"],
            brief=head["brief"],
        )

    return replace(
        manifest,
        hierarchy=HierarchyConfig(
            tier1=tier(desired["chief"], chief=True),
            tier2=tuple(
                tier(head, chief=False) for head in desired["departments"]
            ),
        ),
    )
