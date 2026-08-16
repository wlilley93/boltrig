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
]
