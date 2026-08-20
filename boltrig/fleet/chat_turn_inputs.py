"""Trusted work/context records for a direct chat turn."""

from __future__ import annotations

from boltrig.kernel.work_authority import stamp_creator_ceiling
from boltrig.models import GrantSet, InvocationContext, WorkItem, WorkStatus

from .chat_origin import normalised_origin


def chat_work_item(
    tenant_id: str,
    user_id: str,
    run_id: str,
    message: str,
    origin: str | None,
    workspace_id: str | None,
    ceiling: GrantSet,
    owner: str,
) -> WorkItem:
    item = WorkItem(
        id=run_id,
        tenant_id=tenant_id,
        source="chat",
        intent=message,
        source_id=normalised_origin(origin),
        confidence=1.0,
        convergent=False,
        status=WorkStatus.IN_FLIGHT,
        owner_member=owner,
        hatchet_run_id=run_id,
        on_behalf_of=user_id,
        workspace_id=workspace_id,
    )
    stamp_creator_ceiling(item, ceiling)
    return item


def chat_invocation_context(
    *,
    tenant_id,
    user_id,
    role,
    ceiling,
    conversation_id,
    run_id,
    workspace_id,
    scope,
    model_profile_id,
    model_choice_id,
    attachments,
    actor,
) -> InvocationContext:
    return InvocationContext(
        tenant_id=tenant_id,
        grants=GrantSet.of(
            list(ceiling.allow) + (["agent.send", "chat.present"] if actor else []),
            list(ceiling.deny),
        ),
        actor=actor or "chief-of-staff",
        actor_tier="tier1",
        run_id=run_id,
        on_behalf_of=user_id,
        workspace_id=workspace_id,
        extra={
            "conversation_id": conversation_id,
            "input_modality": (
                "vision"
                if any(
                    str(item.get("media_type") or "").lower().startswith("image/")
                    for item in attachments or []
                )
                else "text"
            ),
            "principal_role": role,
            **({"principal_scope": dict(scope)} if scope is not None else {}),
            **({"model_profile": model_profile_id} if model_profile_id else {}),
            **({"model_endpoint_id": model_choice_id} if model_choice_id else {}),
        },
    )
