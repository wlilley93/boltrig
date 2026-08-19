"""Governed authoring of routing policies (SPEC §8, doctrine step 6).

A policy answers "under these circumstances, select THIS binding". Nothing
could author one, so selection always fell through to binding priority and a
tenant with two eligible implementations had no way to say which one a read
should use.

TWO VALIDATIONS, BOTH FAIL-CLOSED, and both about routes that would exist and
never fire:

* the binding must EXIST and belong to the capability the policy names. A
  policy pointing at another capability's binding is not a mistake the router
  can recover from at call time; it selects a binding whose operation does
  something else.
* the binding must be APPROVED. ``offer_candidates`` and the router both filter
  on ``status == "approved"``, so a policy naming a proposed binding is a route
  that resolves to nothing. Refusing at authoring time means the order is
  approve, then route, rather than route and wonder why the verb is missing.

There is no foreign key from ``routing_policies`` to ``capability_bindings``,
so neither of these is enforced by the database and both have to be enforced
here.

BOTH RUN AT APPROVAL-MINT TIME, through the resource-context hook rather than
in the executor, which is what ``control.capability.upsert`` already does. Two
consequences, both wanted: an invalid policy is refused before a HITL request
exists, so nobody is asked to approve nonsense; and the binding's STATUS is part
of the approval fingerprint, so a binding rejected between the approval and its
redemption makes the write refuse instead of publishing a dead route.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import AdapterFailure, InvocationContext
from boltrig.models.capability_routing import RoutingPolicy

from .control_approval import require_unchanged_approval_context
from .control_routing_policy_specs import ROUTING_POLICY_ACTIONS

ROUTING_POLICY_INVALID = "routing_policy_invalid"


def _refuse(message: str) -> AdapterFailure:
    return AdapterFailure(message, status_code=409, reason=ROUTING_POLICY_INVALID)


def _policy_view(policy: RoutingPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "capability_id": policy.capability_id,
        "binding_id": policy.binding_id,
        "operation_class": policy.operation_class,
        "capability_version": policy.capability_version,
        "scope": policy.scope,
        "workspace_id": policy.workspace_id,
        "precedence": policy.precedence,
    }


async def _validated_policy(store: Any, params: dict[str, Any], tenant_id: str):
    scope = params.get("scope", "tenant")
    workspace_id = params.get("workspace_id") or None
    if scope == "workspace" and workspace_id is None:
        raise _refuse("a workspace-scoped policy names the workspace it serves")
    if scope == "tenant" and workspace_id is not None:
        raise _refuse("a tenant-scoped policy cannot name a workspace")
    try:
        policy = RoutingPolicy(
            id=params["id"],
            tenant_id=tenant_id,
            capability_id=params["capability_id"],
            binding_id=params["binding_id"],
            operation_class=params.get("operation_class", "create"),
            capability_version=params.get("capability_version"),
            scope=scope,
            workspace_id=workspace_id,
            precedence=int(params.get("precedence", 100)),
        )
    except ValueError as error:
        raise _refuse(str(error)) from None

    bindings = await store.list_capability_bindings(
        tenant_id, policy.capability_id
    )
    binding = next(
        (item for item in bindings if item.binding_id == policy.binding_id), None
    )
    if binding is None:
        raise _refuse(
            f"binding '{policy.binding_id}' does not implement capability "
            f"'{policy.capability_id}'"
        )
    if binding.status != "approved":
        raise _refuse(
            f"binding '{policy.binding_id}' is {binding.status}; a route to an "
            "unapproved binding resolves to nothing"
        )
    if (
        policy.capability_version is not None
        and policy.capability_version != binding.capability_version
    ):
        raise _refuse(
            f"binding '{policy.binding_id}' implements version "
            f"{binding.capability_version}, not {policy.capability_version}"
        )
    return policy, binding


async def routing_policy_context(
    store: Any, verb: str, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    """The state that must hold between approving a policy edit and making it."""
    if verb == "control.routing_policy.delete":
        current = next(
            (
                policy
                for policy in await store.list_routing_policies(context.tenant_id)
                if policy.id == params["id"]
            ),
            None,
        )
        if current is None:
            # LookupError, which control_approval_context maps to a 404. A delete
            # naming nothing should say so at the door, not after a review.
            raise LookupError("routing policy not found")
        return {"policy": _policy_view(current)}
    policy, binding = await _validated_policy(store, params, context.tenant_id)
    return {
        "policy": _policy_view(policy),
        # The binding's status and version are IN the fingerprint on purpose:
        # both are the reason the policy was allowed, so a change to either has
        # to invalidate the approval.
        "binding": {
            "binding_id": binding.binding_id,
            "capability_id": binding.capability_id,
            "capability_version": binding.capability_version,
            "status": binding.status,
        },
    }


async def execute_routing_policy_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if verb not in ROUTING_POLICY_ACTIONS:
        return None
    await require_unchanged_approval_context(store, loader, verb, params, context)
    if verb == "control.routing_policy.delete":
        if not await store.delete_routing_policy(context.tenant_id, params["id"]):
            # Not a silent success: "already gone" and "never existed" are
            # different answers to somebody editing which implementation a live
            # verb reaches.
            raise LookupError("routing policy not found")
        return Result.success({"deleted": "routing_policy", "id": params["id"]})

    policy, _binding = await _validated_policy(store, params, context.tenant_id)
    await store.upsert_routing_policy(policy)
    return Result.success({"upserted": "routing_policy", **_policy_view(policy)})
