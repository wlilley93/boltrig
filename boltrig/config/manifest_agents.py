"""Parsing and legacy normalization for the flat named-agent roster."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from boltrig.models import validate_cost_tier

from .manifest import (
    BudgetConfig,
    FleetManifest,
    NamedAgentConfig,
    NamedAgentsConfig,
)


def parse_named_agents(
    raw: Mapping[str, Any],
    *,
    as_tuple: Callable[[Any], tuple[str, ...]],
    parse_budget: Callable[[Any], BudgetConfig | None],
) -> NamedAgentsConfig:
    """Parse the bounded ``agents`` manifest section."""
    unknown = sorted(set(raw) - {"default", "named"})
    if unknown:
        raise ValueError(f"agents does not support: {', '.join(unknown)}")
    members = tuple(
        _parse_named_agent(item, as_tuple=as_tuple, parse_budget=parse_budget)
        for item in (raw.get("named") or [])
    )
    if not members:
        raise ValueError("agents.named must declare at least one named agent")
    return NamedAgentsConfig(
        default=str(raw.get("default") or members[0].address),
        members=members,
    )


def _parse_named_agent(
    raw: Mapping[str, Any],
    *,
    as_tuple: Callable[[Any], tuple[str, ...]],
    parse_budget: Callable[[Any], BudgetConfig | None],
) -> NamedAgentConfig:
    allowed = {
        "name", "address", "runtime", "model_endpoint", "max_depth",
        "supported_skills", "skills", "cost_tier", "scope_id", "budget",
        "purpose", "brief",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"named agent does not support: {', '.join(unknown)}")
    name = str(raw.get("name") or "").strip()
    address = str(raw.get("address") or name).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", address):
        raise ValueError("named agent address must be a lowercase address slug")
    if not name or len(name) > 128:
        raise ValueError("named agent name is required and must be at most 128 characters")
    runtime = str(raw.get("runtime", "codex"))
    if runtime not in {"codex", "script", "python-script"}:
        raise ValueError("named agent runtime is invalid")
    skills = as_tuple(raw.get("skills", raw.get("supported_skills", ["*"])))
    if not 1 <= len(skills) <= 64 or any(
        not value.strip() or len(value) > 128 for value in skills
    ):
        raise ValueError("named agent supported_skills must contain 1-64 bounded strings")
    max_depth = int(raw.get("max_depth", 3))
    if not 1 <= max_depth <= 5:
        raise ValueError("named agent max_depth must be between 1 and 5")
    scope_id = raw.get("scope_id")
    if scope_id is not None and not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,62}", str(scope_id)
    ):
        raise ValueError("named agent scope_id must be a lowercase address slug")
    purpose = str(raw.get("purpose") or "")
    brief = str(raw.get("brief") or "")
    if len(purpose) > 500 or len(brief) > 8000:
        raise ValueError("named agent prompt policy is too large")
    return NamedAgentConfig(
        name=name,
        address=address,
        runtime=runtime,
        model_endpoint=raw.get("model_endpoint"),
        max_depth=max_depth,
        supported_skills=skills,
        cost_tier=validate_cost_tier(str(raw.get("cost_tier", "standard"))),
        scope_id=str(scope_id) if scope_id is not None else None,
        budget=parse_budget(raw.get("budget")),
        purpose=purpose,
        brief=brief,
    )


def resolve_named_agents(manifest: FleetManifest) -> NamedAgentsConfig:
    """Return the flat roster, converting a legacy hierarchy when necessary."""
    if manifest.named_agents.members:
        return manifest.named_agents
    hierarchy = manifest.hierarchy
    members: list[NamedAgentConfig] = []
    if hierarchy.tier1 is not None:
        chief = hierarchy.tier1
        members.append(
            NamedAgentConfig(
                name=chief.name,
                address="cos",
                runtime=chief.runtime,
                model_endpoint=chief.model_endpoint,
                max_depth=chief.max_depth,
                supported_skills=chief.supported_skills,
                cost_tier=chief.cost_tier,
                budget=chief.budget,
                purpose=chief.purpose,
                brief=chief.brief,
            )
        )
    for legacy in hierarchy.tier2:
        address = legacy.department or legacy.name
        members.append(
            NamedAgentConfig(
                name=legacy.name,
                address=address,
                runtime=legacy.runtime,
                model_endpoint=legacy.model_endpoint,
                max_depth=legacy.max_depth,
                supported_skills=legacy.supported_skills,
                cost_tier=legacy.cost_tier,
                scope_id=address,
                budget=legacy.budget,
                purpose=legacy.purpose,
                brief=legacy.brief,
            )
        )
    default = "cos" if hierarchy.tier1 is not None else None
    return NamedAgentsConfig(
        default=default or (members[0].address if members else None),
        members=tuple(members),
    )
