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


async def _sole_active_author(store: Any, tenant_id: str, subject: str) -> bool:
    """True when the subject is the tenant's ONLY active author-tier user.

    The four-eyes bootstrap exemption: on a single-author tenant the independent-
    approver rule is unsatisfiable (every high-consequence control verb, including
    the invitation flow that would add a second human, deadlocks). The exemption
    lifts self-approval ONLY while the tenant has exactly one active author; it
    lapses automatically the moment a second author exists."""
    from boltrig.identity.rbac import AUTHOR_ROLES

    users = await store.list_users(tenant_id)
    authors = [
        u for u in users
        if u.status == "active" and u.role in AUTHOR_ROLES
    ]
    return len(authors) == 1 and authors[0].id == subject


async def approval_response_block(
    store: Any,
    grants: Any,
    request: HITLRequest,
    *,
    tenant_id: str,
    subject: str,
    on_behalf_of: str | None,
    actor_tier: str,
    context: Any,
) -> tuple[str | None, bool]:
    """ONE definition of who may lawfully answer an APPROVAL request.

    Returns ``(block, exempt)``: ``block`` is the refusal detail, None when the
    responder is eligible; ``exempt`` is True only when the sole-author
    bootstrap exemption lifted the independence rule. The response route
    (``authorize_approval_response``) raises on a block; the notice fan-out
    (``eligible_approval_responders``) skips on one - the same rule in both
    postures, so notice and authority cannot drift
    ([2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001, D2)."""
    if actor_tier != "human":
        return "only a human may approve", False
    if not request.verb or not request.request_fingerprint:
        return "approval is not request-bound", False
    if request.assignee and request.assignee != subject:
        return "approval is assigned to another user", False
    initiators = {
        value
        for value in (request.requested_by, request.requested_on_behalf_of)
        if value
    }
    respondents = {value for value in (subject, on_behalf_of) if value}
    exempt = False
    if initiators & respondents:
        if not await _sole_active_author(store, tenant_id, subject):
            return "cannot approve your own request", False
        exempt = True
    permissions = await store.get_tenant_permissions(tenant_id)
    try:
        grants.check(context, request.verb, permissions)
    except GrantMissing:
        return "not authorised to approve this action", False
    return None, exempt


async def eligible_approval_responders(store: Any, request: HITLRequest) -> list[str]:
    """The users who may lawfully answer this APPROVAL request right now.

    The notice fan-out (``_notify_request``) addresses exactly this set - notice
    follows eligibility ([2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001,
    D1/D2). Each candidate is admitted by the SAME ``approval_response_block``
    the response route enforces, with grants resolved exactly as the principal
    resolver resolves them at the door (``current_grants_for_user``), so a user
    the route would refuse is never notified and a user it would admit is never
    missed. Notification widens the audience, never the authority."""
    if request.type != HITLType.APPROVAL:
        return []
    from boltrig.identity.provisioning import current_grants_for_user
    from boltrig.kernel.grants import GrantChecker
    from boltrig.models import InvocationContext

    grants = GrantChecker()
    responders: list[str] = []
    for user in await store.list_users(request.tenant_id):
        context = InvocationContext(
            tenant_id=request.tenant_id,
            grants=current_grants_for_user(user),
            actor=user.id,
            actor_tier="human",
        )
        block, _ = await approval_response_block(
            store, grants, request,
            tenant_id=request.tenant_id,
            subject=user.id,
            on_behalf_of=None,
            actor_tier="human",
            context=context,
        )
        if block is None:
            responders.append(user.id)
    return responders


async def authorize_approval_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Require an independent, assigned human with the live action grant.

    Returns True when the sole-author bootstrap exemption was applied (the
    caller MUST audit-flag it); the exemption never lifts the assignment,
    humanity, or live-grant requirements below. The eligibility rule itself is
    ``approval_response_block`` - ONE definition, shared with the notice
    fan-out so the route and the routing table cannot drift."""
    if request.type != HITLType.APPROVAL:
        return False
    block, exempt = await approval_response_block(
        kernel.store, kernel.grants, request,
        tenant_id=principal.tenant_id,
        subject=principal.subject,
        on_behalf_of=principal.on_behalf_of,
        actor_tier=principal.actor_tier,
        context=principal.context(),
    )
    if block == "approval is not request-bound":
        raise HTTPException(status_code=409, detail=block)
    if block is not None:
        raise HTTPException(status_code=403, detail=block)
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
