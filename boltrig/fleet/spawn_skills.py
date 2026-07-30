"""Skill loading and capability selection for ephemeral spawns."""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator

from boltrig.models import (
    COST_TIERS,
    AgentCapability,
    BoltrigError,
    InvocationContext,
    Skill,
)

_COST_ORDER: dict[str, int] = {tier: index for index, tier in enumerate(COST_TIERS)}


def display_task(task: str) -> str:
    """Return a human-readable task for observability events."""
    s = re.sub(
        r'<untrusted\b[^>]*>(.*?)</untrusted>',
        r'\1',
        task,
        flags=re.DOTALL | re.IGNORECASE,
    )
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'^\s*run:\s*[0-9a-f]+\s*$', '', s, flags=re.MULTILINE | re.IGNORECASE)
    s = re.sub(r'^\s*(user|assistant|system):\s*', '', s, flags=re.MULTILINE | re.IGNORECASE)
    return s.strip()


class SkillNotFound(BoltrigError):
    """A referenced skill or parent does not exist."""

    status_code = 404
    reason = "skill_not_found"


class NoCapableRuntime(BoltrigError):
    """No capability supports all requested skills."""

    status_code = 404
    reason = "no_capable_runtime"


class MergedSkills:
    """The composed prompt / grants / requirements of a skill set."""

    def __init__(self) -> None:
        self.prompt_fragments: list[str] = []
        self.tool_grants: list[str] = []
        self.context_requirements: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def add_grant(self, grant: str) -> None:
        if grant not in self.tool_grants:
            self.tool_grants.append(grant)

    def merge_requirements(self, schema: dict[str, Any]) -> None:
        if not schema:
            return
        props = schema.get("properties")
        if isinstance(props, dict):
            self.context_requirements["properties"].update(props)
        required = schema.get("required")
        if isinstance(required, (list, tuple)):
            for key in required:
                if key not in self.context_requirements["required"]:
                    self.context_requirements["required"].append(key)


async def _resolve_skill_chain(
    store: Any, tenant_id: str, skill_id: str, merged: MergedSkills, seen: set[str]
) -> None:
    if skill_id in seen:
        return
    seen.add(skill_id)
    skill: Skill | None = await store.get_skill(tenant_id, skill_id)
    if skill is None:
        raise SkillNotFound(f"unknown skill '{skill_id}'")
    if skill.extends:
        await _resolve_skill_chain(store, tenant_id, skill.extends, merged, seen)
    if skill.prompt_fragment:
        merged.prompt_fragments.append(skill.prompt_fragment)
    for grant in skill.tool_grants:
        merged.add_grant(grant)
    merged.merge_requirements(skill.context_requirements)


async def resolve_skills(store: Any, tenant_id: str, skills: list[str]) -> MergedSkills:
    """Load skills with ``extends`` inheritance and merge them."""
    merged = MergedSkills()
    for skill_id in skills:
        await _resolve_skill_chain(store, tenant_id, skill_id, merged, set())
    return merged


def missing_requirements(
    schema: dict[str, Any], instance: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Validate spawn context against merged skill requirements."""
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if not properties and not required:
        return [], []
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(instance)]
    missing = [key for key in required if key not in instance]
    return missing, errors


def _pattern_covers(pattern: str, skill_id: str) -> bool:
    if pattern == "*":
        return True
    if pattern == skill_id:
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        return skill_id == prefix or skill_id.startswith(prefix + "/")
    return False


def supports(cap: AgentCapability, skills: list[str]) -> bool:
    """True iff a capability covers every requested skill."""
    return all(
        any(_pattern_covers(pattern, skill) for pattern in cap.supported_skills)
        for skill in skills
    )


async def select_capability(
    store: Any, tenant_id: str, skills: list[str], prefer: dict[str, Any]
) -> AgentCapability:
    """Select the cheapest capable runtime, honouring explicit pins."""
    caps = await store.list_capabilities(tenant_id)
    capable = [cap for cap in caps if supports(cap, skills)]
    if not capable:
        raise NoCapableRuntime(
            f"no capability supports skills {skills} for tenant '{tenant_id}'"
        )
    preferred_capability = prefer.get("capability")
    if preferred_capability:
        named = [cap for cap in capable if cap.name == preferred_capability]
        if not named:
            raise NoCapableRuntime(
                f"capability '{preferred_capability}' does not support skills "
                f"{skills} for tenant '{tenant_id}'"
            )
        return named[0]
    preferred_runtime = prefer.get("runtime")
    if preferred_runtime:
        # ``script`` is the stable personal-agent API name for the
        # deterministic ``python-script`` capability. Keep the alias at this
        # authority boundary rather than leaking implementation names into
        # persisted personal-agent configuration.
        accepted_runtimes = (
            {"script", "python-script"}
            if preferred_runtime == "script"
            else {preferred_runtime}
        )
        runtime_matches = [
            cap for cap in capable if cap.runtime in accepted_runtimes
        ]
        if not runtime_matches:
            raise NoCapableRuntime(
                f"runtime '{preferred_runtime}' does not support skills "
                f"{skills} for tenant '{tenant_id}'"
            )
        capable = runtime_matches
    preferred_tier = prefer.get("cost_tier")
    if preferred_tier:
        tier_matches = [cap for cap in capable if cap.cost_tier == preferred_tier]
        if tier_matches:
            capable = tier_matches
    return min(capable, key=lambda cap: (_COST_ORDER.get(cap.cost_tier, 99), cap.name))


async def bound_capability_status(
    store: Any, tenant_id: str, name: str
) -> tuple[AgentCapability | None, bool]:
    """Resolve an agent binding without confusing retirement with absence."""
    active = next(
        (item for item in await store.list_capabilities(tenant_id) if item.name == name),
        None,
    )
    if active is not None:
        return active, False
    retired = any(
        item.name == name and not item.is_active
        for item in await store.list_all_capabilities(tenant_id)
    )
    return None, retired


def context_payload(context: InvocationContext) -> dict[str, Any]:
    """The data a skill's ``context_requirements`` schema validates against."""
    return {
        **dict(context.extra),
        "tenant_id": context.tenant_id,
        "run_id": context.run_id,
        "parent_run_id": context.parent_run_id,
        "depth": context.depth,
        "on_behalf_of": context.on_behalf_of,
        "actor": context.actor,
        "actor_tier": context.actor_tier,
        "skills_loaded": list(context.skills_loaded),
    }
