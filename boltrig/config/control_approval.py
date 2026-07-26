"""Mutable-resource fingerprints included in governed control approvals."""

from __future__ import annotations

from typing import Any

from boltrig.models import AdapterFailure, InvocationContext
from boltrig.workflows.snapshot import workflow_snapshot_digest

from .control_rehydrate import consumer_spec, rehydratable

_WORKFLOW_ACTIONS = frozenset(
    {
        "control.workflow.schedule",
        "control.workflow.trigger",
        "control.workflow.execute",
    }
)


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
            store, context.tenant_id, str(params.get("workspace_id") or ""), context
        )
        return
    if verb.startswith("control.channel.") or verb == "control.eval_case.upsert":
        from boltrig.identity.rbac import can_author

        role = str((context.extra or {}).get("principal_role") or "")
        if not can_author(role):
            raise PermissionError("authoring/admin not permitted for this role")
        return
    if verb.startswith("control.budget."):
        from .control_budget import _require_admin, _scope

        _require_admin(context)
        _scope(context.tenant_id, params)


async def _budget_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    budget = await store.get_budget(context.tenant_id, str(params["scope_id"]))
    if budget is None:
        return {"budget": None}
    return {
        "budget": {
            "id": budget.id,
            "scope_type": budget.scope_type,
            "window": budget.window,
            "hard_stop": budget.hard_stop,
            "token_limit": budget.token_limit,
            "cost_limit_micros": budget.cost_limit_micros,
            "spent_tokens": budget.spent_tokens,
            "spent_micros": budget.spent_micros,
        }
    }


async def _workflow_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    workflow_id = params["workflow_id"]
    workflow = next(
        (
            item
            for item in await store.list_workflows(context.tenant_id)
            if item.id == workflow_id
            and (item.workspace_id is None or item.workspace_id == context.workspace_id)
        ),
        None,
    )
    if workflow is None:
        raise AdapterFailure(
            "workflow not found", status_code=404, reason="control_resource_not_found"
        )
    return {"workflow_sha256": workflow_snapshot_digest(workflow)}


_LIFECYCLE_ACTIONS = frozenset({"control.adapter.deactivate", "control.adapter.delete"})


async def _store_adapter_view(
    store: Any, record: Any, context: InvocationContext
) -> dict[str, Any]:
    """Approval fingerprint for an adapter row the loader has no instance of.

    The lifecycle verbs use it so a non-rehydrated row stays governable, and
    activation uses it for a rehydratable row (execution rebuilds the instance
    on demand; discovery populating the verb set afterwards is the EXPECTED
    post-approval effect, not drift). The verb list comes from the store's
    owned binding/verb rows (empty for an inert row), sorted for a stable
    fingerprint.
    """
    verbs = []
    for verb in await store.list_verbs(context.tenant_id):
        binding = await store.get_binding(context.tenant_id, verb.id)
        if binding is not None and binding.target_ref == record.id:
            verbs.append(
                {
                    "id": verb.id,
                    "input": verb.input_schema,
                    "output": verb.output_schema,
                    "consequence": verb.consequence.value,
                }
            )
    verbs.sort(key=lambda item: item["id"])
    view = {
        "adapter": {
            "id": record.id,
            "version": record.version,
            "runtime": record.runtime,
            "source": record.source,
            "activated": bool(record.activated),
            "verbs": verbs,
        }
    }
    # SEC-61's waiver is justified by THIS approval: control_specs.py says the
    # internal-egress flag "is always human-approved before any call" because
    # registration is inert until the SEC-22 review gate. The approver was never
    # shown it. `control.adapter.activate` takes only {adapter_id}, so the
    # approval payload was an id, and this view emitted id/version/runtime/
    # source/activated/verbs - no url, no allow_internal. A human was asked to
    # approve "adapter mcp-x" and had no way to learn it would be permitted to
    # reach 169.254.169.254.
    #
    # Adding them here does two things at once: the reviewer sees the waiver, and
    # because this dict IS the approval fingerprint, a row whose url or flag
    # changes between the pend and the apply no longer matches an approval given
    # for the old value.
    spec = consumer_spec(getattr(record, "spec_ref", None))
    if spec.get("url") is not None or spec.get("allow_internal"):
        view["adapter"]["target_url"] = spec.get("url")
        view["adapter"]["allow_internal_egress"] = bool(spec.get("allow_internal"))
    return view


async def _adapter_context(
    store: Any, loader: Any, verb: str, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    if loader is None:
        raise AdapterFailure(
            "adapter loader not wired",
            status_code=503,
            reason="control_dependency_unavailable",
        )
    adapter = await loader.get(context.tenant_id, params["adapter_id"])
    if adapter is None:
        record = await store.get_adapter(context.tenant_id, params["adapter_id"])
        if record is None:
            raise AdapterFailure(
                "adapter not found", status_code=404, reason="control_resource_not_found"
            )
        if verb in _LIFECYCLE_ACTIONS:
            return await _store_adapter_view(store, record, context)
        # activate: proceed to a pend only when execution can honestly rebuild
        # the instance (control_rehydrate); an unreconstructible row fails
        # loudly NOW, before any approval work is created.
        if rehydratable(record):
            return await _store_adapter_view(store, record, context)
        raise AdapterFailure(
            "adapter cannot be reconstructed from its store row; "
            "delete and re-register it",
            status_code=409,
            reason="control_adapter_unrehydratable",
        )
    record = await store.get_adapter(context.tenant_id, params["adapter_id"])
    verbs = [
        {
            "id": item.verb_id,
            "input": item.input_schema,
            "output": item.output_schema,
            "consequence": item.consequence,
        }
        for item in adapter.describe()
    ]
    return {
        "adapter": {
            "id": adapter.id,
            "version": adapter.version,
            "runtime": adapter.runtime,
            "source": getattr(adapter, "source", None),
            "activated": bool(record and record.activated),
            "verbs": verbs,
        }
    }


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
    except PermissionError as exc:
        raise AdapterFailure(
            str(exc), status_code=403, reason="control_unauthorised"
        ) from exc
    except LookupError as exc:
        raise AdapterFailure(
            str(exc), status_code=404, reason="control_resource_not_found"
        ) from exc
    if verb in _WORKFLOW_ACTIONS:
        return await _workflow_context(store, params, context)
    if verb in {
        "control.adapter.activate",
        "control.adapter.deactivate",
        "control.adapter.delete",
    }:
        return await _adapter_context(store, loader, verb, params, context)
    if verb.startswith("control.budget."):
        return await _budget_context(store, params, context)
    return None


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
