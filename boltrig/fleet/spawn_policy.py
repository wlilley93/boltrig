"""Governed spawn intake and trusted spawn-rule receipt propagation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from boltrig.config.spawn_rules import (
    SpawnRule,
    SpawnRuleMatchError,
    SpawnRuleSelection,
    SpawnRuleValidationError,
    apply_spawn_rule,
    effective_spawn_rules,
)
from boltrig.models.context import InvocationContext
from boltrig.models.errors import (
    ContextRequirementsUnmet,
    DepthExceeded,
    SpawnRulePolicyInvalid,
)
from boltrig.models.familiar import derive_familiar_genotype
from boltrig.models.grants import GrantSet
from boltrig.models.libraries import AgentCapability

from .spawn_skills import (
    NoCapableRuntime,
    context_payload,
    display_task,
    missing_requirements,
    resolve_skills,
    select_capability,
)

if TYPE_CHECKING:
    from boltrig.store.base import Store

_SPAWN_RULE_CONTEXT_KEY = "boltrig_spawn_rule"


@dataclass(frozen=True)
class SpawnIntake:
    """Validated inputs and routing selected at the spawn boundary."""

    skills: list[str]
    prefer: dict[str, Any]
    merged_prompt: str
    tool_grants: tuple[str, ...]
    capability: AgentCapability
    child_depth: int
    spawn_rule: SpawnRuleSelection | None


async def _effective_rules(
    store: Store,
    tenant_id: str,
    base_rules: Sequence[SpawnRule],
) -> tuple[SpawnRule, ...]:
    try:
        snapshot = await effective_spawn_rules(store, tenant_id, base_rules)
    except Exception as exc:
        if isinstance(exc, SpawnRuleValidationError):
            raise SpawnRulePolicyInvalid(
                "current spawn-rule policy is invalid"
            ) from exc
        raise SpawnRulePolicyInvalid(
            "current spawn-rule policy could not be read"
        ) from exc
    return snapshot.rules


async def prepare_spawn_intake(
    store: Store,
    tenant_id: str,
    *,
    base_rules: Sequence[SpawnRule],
    skills: Sequence[str],
    prefer: Mapping[str, Any],
    context: InvocationContext,
) -> SpawnIntake:
    """Resolve one policy snapshot, capability and depth before reserving spend."""

    rules = await _effective_rules(store, tenant_id, base_rules)
    try:
        effective_skills, effective_prefer, spawn_rule = apply_spawn_rule(
            rules, skills=skills, prefer=prefer
        )
    except (SpawnRuleMatchError, SpawnRuleValidationError) as exc:
        raise SpawnRulePolicyInvalid(str(exc)) from exc

    merged = await resolve_skills(store, tenant_id, effective_skills)
    instance = {
        key: value
        for key, value in context_payload(context).items()
        if value is not None
    }
    missing, errors = missing_requirements(merged.context_requirements, instance)
    if missing or errors:
        detail = "; ".join(errors) if errors else "missing required context"
        raise ContextRequirementsUnmet(
            f"spawn context unmet: {detail}", missing=missing or errors
        )

    try:
        capability = await select_capability(
            store,
            tenant_id,
            effective_skills,
            effective_prefer,
            workspace_id=context.workspace_id,
        )
    except NoCapableRuntime as exc:
        if spawn_rule is None:
            raise
        raise SpawnRulePolicyInvalid(
            f"spawn rule '{spawn_rule.rule_id}' targets an unavailable "
            "or incompatible capability"
        ) from exc

    child_depth = context.depth + 1
    max_depth = capability.max_depth
    if spawn_rule is not None and spawn_rule.max_depth is not None:
        max_depth = min(max_depth, spawn_rule.max_depth)
    if child_depth > max_depth:
        raise DepthExceeded(
            f"depth {child_depth} exceeds max_depth {max_depth} "
            f"for capability '{capability.name}'"
        )
    return SpawnIntake(
        skills=effective_skills,
        prefer=effective_prefer,
        merged_prompt="\n\n".join(merged.prompt_fragments),
        tool_grants=tuple(merged.tool_grants),
        capability=capability,
        child_depth=child_depth,
        spawn_rule=spawn_rule,
    )


def build_child_context(
    tenant_id: str,
    run_id: str,
    child_depth: int,
    parent: InvocationContext,
    capability: AgentCapability,
    skills: Sequence[str],
    grants: GrantSet,
    spawn_rule: SpawnRuleSelection | None = None,
) -> InvocationContext:
    """Build a least-authority child context and stamp only trusted rule data."""

    workspace_id = parent.workspace_id
    if workspace_id is None and capability.runtime == "codex":
        workspace_id = run_id
    extra = {
        key: value
        for key, value in parent.extra.items()
        if key != _SPAWN_RULE_CONTEXT_KEY
    }
    if spawn_rule is not None:
        extra[_SPAWN_RULE_CONTEXT_KEY] = spawn_rule.receipt()
    return InvocationContext(
        tenant_id=tenant_id,
        run_id=run_id,
        parent_run_id=parent.run_id,
        depth=child_depth,
        on_behalf_of=parent.on_behalf_of,
        workspace_id=workspace_id,
        ip_address=parent.ip_address,
        user_agent=parent.user_agent,
        grants=grants,
        actor=capability.name,
        actor_tier="ephemeral",
        skills_loaded=tuple(skills),
        extra=extra,
    )


def publish_subagent_event(
    events: Any,
    context: InvocationContext,
    task: str,
    skills: Sequence[str],
    run_id: str,
    capability: AgentCapability,
    spawn_rule: SpawnRuleSelection | None,
) -> None:
    """Publish the bounded public delegation receipt without failing the spawn."""

    try:
        event = {
            "type": "subagent",
            "task": display_task(task),
            "skills": list(skills),
            "child_run_id": run_id,
            "capability": capability.name,
            "name": capability.name,
            "familiar_genotype": derive_familiar_genotype(
                capability.name
            ).as_view(),
        }
        if spawn_rule is not None:
            event["spawn_rule"] = spawn_rule.receipt()
        events.publish(context.tenant_id, context.run_id, event)
    except Exception:
        pass


__all__ = [
    "SpawnIntake",
    "build_child_context",
    "prepare_spawn_intake",
    "publish_subagent_event",
]
