"""Object-level visibility and response policy for pending HITL requests."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import GrantMissing, HITLRequest, HITLType


def _principal_ids(principal: Any) -> set[str]:
    return {
        value for value in (principal.subject, principal.on_behalf_of) if value
    }


def _requester_ids(request: HITLRequest) -> set[str]:
    return {
        value
        for value in (request.requested_by, request.requested_on_behalf_of)
        if value
    }


async def related_work_item(kernel: Any, request: HITLRequest) -> Any:
    """The work item a HITL request is linked to (by id, else by run id).

    Shared by the scope check below and by channel intake's thread matching -
    one definition of 'the item this request concerns'."""
    if request.work_item_id:
        item = await kernel.store.get_work_item(
            request.tenant_id, request.work_item_id
        )
        if item is not None:
            return item
    if request.run_id:
        return await kernel.store.get_work_item_by_run_id(
            request.tenant_id, request.run_id
        )
    return None


async def _scope_matches(
    kernel: Any, principal: Any, request: HITLRequest, item: Any
) -> bool:
    from boltrig.identity.rbac import departments_for

    departments = departments_for(principal.role, principal.scope)
    if request.workspace_id is not None:
        active = principal.active_workspace_id
        if active is not None and active != request.workspace_id:
            return False
        if active is None and departments is not None:
            member = await kernel.store.get_workspace_member(
                principal.tenant_id, request.workspace_id, principal.subject
            )
            if member is None:
                return False
    if departments is None:
        return True
    caller_departments = set(departments)
    owner = getattr(item, "on_behalf_of", None)
    involved = _requester_ids(request) | {value for value in (request.assignee, owner) if value}
    if _principal_ids(principal) & involved:
        return True
    if request.department_scope is not None:
        return bool(caller_departments & set(request.department_scope))
    item_department = getattr(item, "owner_member", None)
    return item_department is None or item_department in caller_departments


async def authorize_hitl_scope(
    kernel: Any, principal: Any, request: HITLRequest
) -> Any:
    """Return the linked item when the request is in scope, else hide its existence."""
    item = await related_work_item(kernel, request)
    if not await _scope_matches(kernel, principal, request, item):
        raise HTTPException(status_code=404, detail="unknown request")
    return item


async def _approval_visible(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    if _principal_ids(principal) & _requester_ids(request):
        return True
    if request.assignee and request.assignee != principal.subject:
        return False
    if principal.actor_tier != "human":
        return False
    if not request.verb:
        return True
    permissions = await kernel.store.get_tenant_permissions(principal.tenant_id)
    try:
        kernel.grants.check(principal.context(), request.verb, permissions)
    except GrantMissing:
        return False
    return True


async def hitl_request_visible(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Whether the caller may receive this request from a collection endpoint."""
    try:
        item = await authorize_hitl_scope(kernel, principal, request)
    except HTTPException:
        return False
    owner = getattr(item, "on_behalf_of", None)
    identities = _principal_ids(principal)
    if request.type == HITLType.QUESTION:
        return bool(owner and owner == principal.subject)
    if request.type == HITLType.APPROVAL:
        return await _approval_visible(kernel, principal, request)
    initiators = _requester_ids(request) | ({owner} if owner else set())
    if identities & initiators:
        return True
    if principal.actor_tier != "human":
        return False
    return request.assignee in identities if request.assignee else True


async def _sole_active_author(kernel: Any, principal: Any) -> bool:
    """True when the principal is the tenant's ONLY active author-tier user.

    The four-eyes bootstrap exemption: on a single-author tenant the independent-
    approver rule is unsatisfiable (every high-consequence control verb, including
    the invitation flow that would add a second human, deadlocks). The exemption
    lifts self-approval ONLY while the tenant has exactly one active author; it
    lapses automatically the moment a second author exists."""
    from boltrig.identity.rbac import AUTHOR_ROLES

    users = await kernel.store.list_users(principal.tenant_id)
    authors = [
        u for u in users
        if u.status == "active" and u.role in AUTHOR_ROLES
    ]
    return len(authors) == 1 and authors[0].id == principal.subject


async def authorize_approval_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Require an independent, assigned human with the live action grant.

    Returns True when the sole-author bootstrap exemption was applied (the
    caller MUST audit-flag it); the exemption never lifts the assignment,
    humanity, or live-grant requirements below."""
    if request.type != HITLType.APPROVAL:
        return False
    if principal.actor_tier != "human":
        raise HTTPException(status_code=403, detail="only a human may approve")
    if not request.verb or not request.request_fingerprint:
        raise HTTPException(status_code=409, detail="approval is not request-bound")
    if request.assignee and request.assignee != principal.subject:
        raise HTTPException(status_code=403, detail="approval is assigned to another user")
    initiators = {
        value
        for value in (request.requested_by, request.requested_on_behalf_of)
        if value
    }
    respondents = {
        value for value in (principal.subject, principal.on_behalf_of) if value
    }
    exempt = False
    if initiators & respondents:
        if not await _sole_active_author(kernel, principal):
            raise HTTPException(status_code=403, detail="cannot approve your own request")
        exempt = True
    permissions = await kernel.store.get_tenant_permissions(principal.tenant_id)
    try:
        kernel.grants.check(principal.context(), request.verb, permissions)
    except GrantMissing as exc:
        raise HTTPException(
            status_code=403, detail="not authorised to approve this action"
        ) from exc
    return exempt


async def authorize_hitl_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Apply common scope, then the type-specific mutation authorization.

    Returns True only when the APPROVAL path applied the sole-author bootstrap
    exemption (see authorize_approval_response) - the caller MUST audit-flag it."""
    item = await authorize_hitl_scope(kernel, principal, request)
    if request.type == HITLType.QUESTION:
        owner = getattr(item, "on_behalf_of", None)
        if not owner or owner != principal.subject:
            raise HTTPException(status_code=404, detail="unknown request")
        raise HTTPException(status_code=409, detail="use the question answer route")
    if request.type == HITLType.APPROVAL:
        return await authorize_approval_response(kernel, principal, request)
    if principal.actor_tier != "human":
        raise HTTPException(status_code=403, detail="only a human may respond")
    owner = getattr(item, "on_behalf_of", None)
    initiators = _requester_ids(request) | ({owner} if owner else set())
    if _principal_ids(principal) & initiators:
        raise HTTPException(status_code=403, detail="cannot answer your own request")
    if request.assignee and request.assignee != principal.subject:
        raise HTTPException(status_code=403, detail="request is assigned to another user")
    return False
