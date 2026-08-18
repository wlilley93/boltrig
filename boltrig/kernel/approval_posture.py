"""Caller-owned approval posture for delegated agent tool calls.

The posture is consent data, not authority.  It can only decide whether an
already-granted adapter call needs an additional exact-request approval.  It
never widens grants and it never bypasses deployment-blocked verbs, direct
human calls, or control-plane mutations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from boltrig.models import Consequence, InvocationContext, TargetType, UserSetting, Verb, VerbBinding

from .routing import blocking_names, governed_capabilities, unpinned

APPROVAL_POSTURE_SETTING = "agentic.approval_posture"


class ApprovalPosture(StrEnum):
    ALWAYS_ASK = "always_ask"
    RISK_BASED = "risk_based"
    FULL_ACCESS = "full_access"


DEFAULT_APPROVAL_POSTURE = ApprovalPosture.RISK_BASED


def parse_approval_posture(value: Any) -> ApprovalPosture:
    try:
        return ApprovalPosture(value)
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_POSTURE


async def approval_posture_for(
    store: Any, tenant_id: str, user_id: str
) -> tuple[ApprovalPosture, str]:
    rows = await store.list_user_settings(tenant_id, user_id)
    for row in rows:
        if row.key == APPROVAL_POSTURE_SETTING:
            parsed = parse_approval_posture(row.value)
            source = "user_override" if row.value == parsed.value else "safe_default"
            return parsed, source
    return DEFAULT_APPROVAL_POSTURE, "safe_default"


async def persist_approval_posture(
    store: Any, tenant_id: str, user_id: str, posture: ApprovalPosture
) -> None:
    await store.upsert_user_setting(
        UserSetting(
            tenant_id=tenant_id,
            user_id=user_id,
            key=APPROVAL_POSTURE_SETTING,
            value=posture.value,
        )
    )


def is_delegated_agent_call(context: InvocationContext) -> bool:
    return bool(context.on_behalf_of) and context.actor_tier != "human"


async def requires_approval(
    store: Any,
    blocking_verbs: Any,
    verb: str,
    verb_def: Verb,
    binding: VerbBinding,
    plan: Any,
    context: InvocationContext,
) -> bool:
    """Every reason one invocation must pause for a human, in one place.

    Three, in order of bluntness. The operator's always-ask list is matched
    against every name the call answers to - what the caller typed, the
    canonical capability, and the source operation actually executed - because
    an operator who blocked an action meant that action however it is addressed.
    That takes TWO lookups, not one: ``blocking_names`` covers what a name can
    know, and ``governed_capabilities`` covers what only the stored bindings can
    - which capabilities a bare source-operation id implements. Matching names
    alone left the capability spelling governing nothing a model could reach,
    since the MCP face offers source-operation ids and never capability names.

    A binding may then RAISE the consequence of the operation it routes to (SPEC
    §8 step 5), only upwards, since a mapping able to lower it would let a route
    quietly downgrade a governed action. That override is read for the direct
    spelling too, for the same reason: it is a property of the route.

    The operator's own entries are normalised first: a list written with a
    version pin is read as the capability it names, so the gate cannot quietly
    expire when a binding's version moves (``routing.unpinned``).

    Everything else remains the established posture gate.
    """
    blocked = unpinned(blocking_verbs)
    if not blocked.isdisjoint(blocking_names(verb, verb_def, plan)):
        return True
    capabilities, override = await governed_capabilities(
        store, context.tenant_id, verb_def, plan
    )
    if not blocked.isdisjoint(capabilities):
        return True
    if override == "high":
        return True
    return await posture_requires_approval(store, verb, verb_def, binding, context)


async def posture_requires_approval(
    store: Any,
    verb: str,
    verb_def: Verb,
    binding: VerbBinding,
    context: InvocationContext,
) -> bool:
    """Return the posture-controlled approval decision for one invocation.

    Direct human invocations and control-plane mutations retain the established
    consequence gate.  A delegated agent with no usable owner posture also
    fails back to ``risk_based``.
    """
    if not is_delegated_agent_call(context):
        return verb_def.consequence == Consequence.HIGH
    if (
        binding.target_type != TargetType.ADAPTER
        or binding.target_ref == "control"
        or verb.startswith("control.")
    ):
        return verb_def.consequence == Consequence.HIGH

    posture, _source = await approval_posture_for(
        store, context.tenant_id, str(context.on_behalf_of)
    )
    if posture == ApprovalPosture.ALWAYS_ASK:
        return True
    if posture == ApprovalPosture.FULL_ACCESS:
        return False
    return verb_def.consequence == Consequence.HIGH


def approval_posture_view(posture: ApprovalPosture, source: str) -> dict[str, Any]:
    return {
        "posture": posture.value,
        "source": source,
        "enforcement": {
            "applies_to": "delegated_agent_adapter_calls",
            "workspace_blocking_verbs_remain": True,
            "control_plane_approvals_remain": True,
            "direct_human_consequence_gate_remains": True,
            "authority_is_never_widened": True,
        },
    }


__all__ = [
    "APPROVAL_POSTURE_SETTING",
    "ApprovalPosture",
    "DEFAULT_APPROVAL_POSTURE",
    "approval_posture_for",
    "approval_posture_view",
    "parse_approval_posture",
    "persist_approval_posture",
    "posture_requires_approval",
    "requires_approval",
]
