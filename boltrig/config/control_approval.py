"""Mutable-resource fingerprints included in governed control approvals."""

from __future__ import annotations

from typing import Any

from boltrig.models import AdapterFailure, InvocationContext

from .control_approval_adapters import (
    MCP_LIFECYCLE_ACTIONS,
    _store_adapter_view,
    adapter_context,
    integration_context,
    mcp_server_context,
)
from .control_approval_registry import (
    AUTHORED_DEFINITION_ACTIONS,
    binding_upsert_context,
    capability_upsert_context,
    noun_context,
    noun_upsert_context,
    skill_context,
    skill_upsert_context,
    verb_context,
    verb_upsert_context,
)
from .control_approval_model_endpoints import (
    model_endpoint_context,
    model_endpoint_upsert_context,
)
from .control_routing_policy_specs import ROUTING_POLICY_ACTIONS
from .control_approval_workflows import (
    CAPABILITY_ACTIONS,
    EVAL_CASE_ACTIONS,
    MODEL_ENDPOINT_ACTIONS,
    WORKFLOW_ACTIONS,
    WORKFLOW_TRIGGER_BINDING_ACTIONS,
    budget_context,
    capability_context,
    eval_case_context,
    eval_case_upsert_context,
    workflow_context,
    workflow_trigger_binding_context,
)

__all__ = [
    "_store_adapter_view",
    "control_approval_context",
    "require_unchanged_approval_context",
]


async def _require_active_human_author(
    store: Any, context: InvocationContext, message: str
) -> None:
    from boltrig.identity.rbac import can_author

    role = str((context.extra or {}).get("principal_role") or "")
    user = await store.get_user(context.tenant_id, context.actor)
    if (
        context.actor_tier != "human"
        or not can_author(role)
        or user is None
        or user.status != "active"
    ):
        raise PermissionError(message)


async def _revoking_your_own(store: Any, params: dict[str, Any], context: Any) -> bool:
    """Whether this revocation is the caller disconnecting their OWN personal
    integration credential -- which is operating their own seat, not
    administering the organisation, and so does not need an author role.

    Without the exemption, connecting is a ONE-WAY DOOR. ``control.integration.connect``
    is low consequence, so any member may seal a personal credential; every
    high-consequence ``control.integration.*`` verb is gated on ``can_author``, so
    the same member could never destroy it. Revoking the organisation's shared row
    stays author-only, and another member's row is reachable only through
    ``control.integration.revoke_member``.
    """
    from boltrig.kernel.integration_scope import is_own_personal_connection

    return await is_own_personal_connection(store, params, context)


async def _preauthorize_high_consequence(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> None:
    """Reject role/scope-invalid requests before creating approval work."""
    if verb in {"control.ai_key.set", "control.ai_key.delete"}:
        from .control_compat import _authorise_ai_key

        await _authorise_ai_key(
            store,
            context.tenant_id,
            str(params.get("level") or ""),
            str(params.get("scope_id") or ""),
            context,
        )
        return
    if verb in {"control.org.update", "control.workspace.create"}:
        from .control_compat import _require_admin

        _require_admin(context)
        return
    if verb in {
        "control.workspace.update",
        "control.workspace.member.add",
        "control.workspace.member.remove",
    }:
        from .control_compat import _managed_workspace

        await _managed_workspace(
            store,
            context.tenant_id,
            str(params.get("workspace_id") or ""),
            context,
        )
        return
    if verb in WORKFLOW_TRIGGER_BINDING_ACTIONS:
        await _require_active_human_author(
            store,
            context,
            "workflow trigger delegation requires an active human author",
        )
        return
    if verb == "control.workflow.schedule_occurrence.retry":
        await _require_active_human_author(
            store,
            context,
            "workflow occurrence retry requires an active human author",
        )
        return
    if verb == "control.integration.revoke" and await _revoking_your_own(
        store, params, context
    ):
        return
    if verb.startswith(
        (
            "control.channel.",
            "control.eval_case.",
            "control.integration.",
            "control.mcp_server.",
            "control.permanent_fleet.",
            "control.work.",
        )
    ):
        from boltrig.identity.rbac import can_author

        role = str((context.extra or {}).get("principal_role") or "")
        if not can_author(role):
            raise PermissionError("authoring/admin not permitted for this role")
        return
    if verb.startswith("control.budget."):
        from .control_budget import _require_admin, _scope

        _require_admin(context)
        _scope(context.tenant_id, params)


async def _definition_context(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any] | None:
    if verb in AUTHORED_DEFINITION_ACTIONS:
        if verb.startswith("control.skill."):
            return await skill_context(store, params, context)
        if verb.startswith("control.noun."):
            return await noun_context(store, params, context)
        return await verb_context(store, params, context)
    handlers = {
        "control.skill.upsert": skill_upsert_context,
        "control.noun.define": noun_upsert_context,
        "control.verb.define": verb_upsert_context,
        "control.binding.set": binding_upsert_context,
    }
    handler = handlers.get(verb)
    return None if handler is None else await handler(store, params, context)


async def _ai_key_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    proposal = await store.get_ai_key_secret_proposal(
        context.tenant_id, str(params.get("proposal_id") or "")
    )
    if (
        proposal is None
        or proposal.requested_by != context.actor
        or proposal.requested_on_behalf_of != context.on_behalf_of
        or proposal.workspace_id != context.workspace_id
        or proposal.status != "pending"
        or proposal.level != str(params.get("level") or "")
        or proposal.scope_id != str(params.get("scope_id") or "")
        or proposal.provider != str(params.get("provider") or "")
        or proposal.model != str(params.get("model") or "")
        or proposal.base_url != (str(params.get("base_url") or "").strip() or None)
        or proposal.modality != str(params.get("modality") or "text")
        or proposal.secret_digest != str(params.get("secret_digest") or "")
    ):
        raise PermissionError(
            "AI-key proposal is unavailable or does not match this caller"
        )
    current = await store.get_ai_config(
        context.tenant_id, proposal.level, proposal.scope_id, proposal.modality
    )
    return {
        "proposal": {
            "id": proposal.id,
            "status": proposal.status,
            "expires_at": proposal.expires_at.isoformat(),
            "secret_digest": proposal.secret_digest,
        },
        "current": (
            None
            if current is None
            else {
                "level": current.level,
                "scope_id": current.scope_id,
                "provider": current.provider,
                "model": current.model,
                "base_url": current.base_url,
                "modality": current.modality,
                "credential_ref": current.credential_ref,
                "updated_at": current.updated_at.isoformat(),
            }
        ),
    }


async def _resource_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any] | None:
    if verb == "control.ai_key.set":
        return await _ai_key_context(store, params, context)
    if verb in WORKFLOW_ACTIONS:
        return await workflow_context(store, verb, params, context)
    if verb in WORKFLOW_TRIGGER_BINDING_ACTIONS:
        return await workflow_trigger_binding_context(store, verb, params, context)
    if verb in CAPABILITY_ACTIONS:
        return await capability_context(store, params, context)
    if verb == "control.capability.upsert":
        return await capability_upsert_context(store, params, context)
    if verb in ROUTING_POLICY_ACTIONS:
        from .control_routing_policies import routing_policy_context

        return await routing_policy_context(store, verb, params, context)

    if verb == "control.permanent_fleet.apply":
        from .permanent_fleet import latest_permanent_fleet_revision

        revision = await latest_permanent_fleet_revision(
            store, context.tenant_id
        )
        return {
            "generation": revision.version if revision else None,
            "revision": revision.id if revision else None,
        }
    if verb in MODEL_ENDPOINT_ACTIONS:
        return await model_endpoint_context(store, params, context)
    if verb == "control.model_endpoint.upsert":
        return await model_endpoint_upsert_context(store, params, context)
    if verb in EVAL_CASE_ACTIONS:
        return await eval_case_context(store, params, context)
    if verb == "control.eval_case.upsert":
        return await eval_case_upsert_context(store, params, context)
    if verb.startswith("control.channel."):
        from .control_channel_ops import channel_mutation_context

        return await channel_mutation_context(store, verb, params, context)
    definition = await _definition_context(store, verb, params, context)
    if definition is not None:
        return definition
    if verb in {"control.integration.revoke", "control.integration.revoke_member"}:
        return await integration_context(store, params, context)
    if verb in MCP_LIFECYCLE_ACTIONS:
        return await mcp_server_context(
            store, verb, params, context
        )
    if verb.startswith("control.adapter.") and verb != "control.adapter.generate":
        return await adapter_context(store, loader, verb, params, context)
    if verb.startswith("control.budget."):
        return await budget_context(store, params, context)
    if verb in {"control.work.status", "control.work.reparent"}:
        from .control_work import approval_work_context

        return await approval_work_context(store, verb, params, context)
    return None


async def control_approval_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any] | None:
    """Return state that must remain identical between approval and execution."""
    try:
        await _preauthorize_high_consequence(store, verb, params, context)
        return await _resource_context(store, loader, verb, params, context)
    except PermissionError as exc:
        raise AdapterFailure(
            str(exc), status_code=403, reason="control_unauthorised"
        ) from exc
    except LookupError as exc:
        raise AdapterFailure(
            str(exc), status_code=404, reason="control_resource_not_found"
        ) from exc


async def require_unchanged_approval_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> None:
    """Close the gate-to-mutation race by rechecking the approved resource state."""
    fingerprint = context.extra.get("approval_request_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise PermissionError("exact approval evidence is missing")
    expected = context.extra.get("approval_resource_context")
    from boltrig.kernel.hitl import canonical_approval_value

    current = canonical_approval_value(
        await control_approval_context(store, loader, verb, params, context)
    )
    if expected != current:
        raise PermissionError("approved resource changed before execution")
