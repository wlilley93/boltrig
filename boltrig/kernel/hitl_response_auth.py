"""Object-level visibility and response policy for pending HITL requests."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from boltrig.models import GrantMissing, HITLRequest, HITLType

from .routing import governed_aliases


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


async def _granted_any_alias(
    store: Any, grants: Any, context: Any, tenant_id: str, verb: str, permissions: Any
) -> bool:
    """Whether this caller holds authority over the ACTION, by any of its names.

    A routed call is recorded under the capability the caller typed, while the
    people who administer the system it touches hold grants on the source
    operation. Checking the recorded spelling alone left such a call held for a
    human who was not permitted to see it (``routing.governed_aliases``).
    """
    for name in await governed_aliases(store, tenant_id, verb):
        try:
            grants.check(context, name, permissions)
        except GrantMissing:
            continue
        return True
    return False


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
    return await _granted_any_alias(
        kernel.store, kernel.grants, principal.context(), principal.tenant_id,
        request.verb, permissions,
    )


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
    posture: Any = None,
    credential_kind: str = "machine",
) -> tuple[str | None, str | None]:
    """ONE definition of who may lawfully answer an APPROVAL request.

    Returns ``(block, relief)``: ``block`` is the refusal detail, None when the
    responder is eligible; ``relief`` names which rule lifted independence -
    ``"sole_author"`` (the bootstrap exemption: the rule was unsatisfiable) or
    ``"development_posture"`` (deliberately suspended on a declared tenant) -
    and is None when no relief was needed or none applied. The response route
    (``authorize_approval_response``) raises on a block; the notice fan-out
    (``eligible_approval_responders``) skips on one - the same rule in both
    postures, so notice and authority cannot drift
    ([2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001, D2)."""
    if actor_tier != "human":
        return "only a human may approve", None
    if not request.verb or not request.request_fingerprint:
        return "approval is not request-bound", None
    if request.assignee and request.assignee != subject:
        return "approval is assigned to another user", None
    initiators = {
        value
        for value in (request.requested_by, request.requested_on_behalf_of)
        if value
    }
    respondents = {value for value in (subject, on_behalf_of) if value}
    relief: str | None = None
    if initiators & respondents:
        # TWO reliefs can lift independence, and they are reported separately
        # because they mean different things to whoever reads the record: the
        # bootstrap exemption says the rule was UNSATISFIABLE (one author), the
        # development posture says it was DELIBERATELY SUSPENDED on a tenant not
        # yet in service. Sole-author is tried first: where it applies nothing
        # needed declaring, so nothing should be reported as declared.
        if await _sole_active_author(store, tenant_id, subject):
            relief = "sole_author"
        else:
            blocked = await _development_posture_block(
                store, tenant_id, posture, request, subject, credential_kind
            )
            if blocked is not None:
                return "cannot approve your own request", None
            relief = "development_posture"
    permissions = await store.get_tenant_permissions(tenant_id)
    if not await _granted_any_alias(
        store, grants, context, tenant_id, request.verb, permissions
    ):
        # AFTER the relief, never before: dev_posture.posture_block lifts
        # INDEPENDENCE and never authority, so a superadmin without the verb's
        # grant is refused under a posture exactly as without one.
        return "not authorised to approve this action", None
    return None, relief


async def _development_posture_block(
    store: Any,
    tenant_id: str,
    posture: Any,
    request: HITLRequest,
    subject: str,
    credential_kind: str,
) -> str | None:
    """None when the declared development posture admits this self-approval.

    The role and the author roll are read from the STORE, not from the caller's
    principal: the posture admits superadmin only, and a principal is shaped by
    the request. ``credential_kind`` is the one thing that MUST come from the
    principal, because it is a fact about how this caller authenticated and
    nothing in the store can answer it.
    """
    from boltrig.config.author_ratchet import is_active_author
    from boltrig.config.dev_posture import posture_block
    from boltrig.config.environment import development_signal, production_signal
    from boltrig.config.settings import load_settings
    from boltrig.models import utcnow

    user = await store.get_user(tenant_id, subject)
    users = await store.list_users(tenant_id)
    settings = load_settings()
    return posture_block(
        posture,
        now=utcnow(),
        production_signal=production_signal(),
        development_signal=development_signal(),
        real_ingress=(
            settings.oidc_configured
            or settings.cf_access_configured
            or settings.session_auth_configured
        ),
        credential_kind=credential_kind,
        active_author_ids=[
            str(getattr(u, "id", "")) for u in users if is_active_author(u)
        ],
        verb=request.verb,
        subject_role=str(getattr(user, "role", "") or ""),
    )


async def eligible_approval_responders(
    store: Any, request: HITLRequest, *, posture: Any = None
) -> list[str]:
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
        block, _relief = await approval_response_block(
            store, grants, request,
            tenant_id=request.tenant_id,
            subject=user.id,
            on_behalf_of=None,
            actor_tier="human",
            context=context,
            # D6. Without the posture here, notice was computed against
            # posture=None while the route used the live one, so under a posture
            # the route admitted a user the notice never told. Measured before
            # the fix: notice ['client@cv'], route ['client@cv', 'operator@cv'].
            posture=posture,
            # A notice asks whether this PERSON may answer, so eligibility is
            # computed as though they arrive at a door, not with whatever
            # credential some later request happens to carry. This keeps the
            # notice set a superset of the route set, which is the safe
            # direction: nobody the route would admit is missed.
            credential_kind="session",
        )
        if block is None:
            responders.append(user.id)
    return responders


async def authorize_approval_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Require an independent, assigned human with the live action grant.

    Returns the NAME of the relief that lifted independence, or None. The
    caller MUST record it: an approval nobody independent reviewed is exactly
    the thing a reader of the record needs to see. No relief ever lifts the
    assignment, humanity, or live-grant requirements below. The eligibility rule itself is
    ``approval_response_block`` - ONE definition, shared with the notice
    fan-out so the route and the routing table cannot drift."""
    if request.type != HITLType.APPROVAL:
        return False
    block, relief = await approval_response_block(
        kernel.store, kernel.grants, request,
        tenant_id=principal.tenant_id,
        subject=principal.subject,
        on_behalf_of=principal.on_behalf_of,
        actor_tier=principal.actor_tier,
        context=principal.context(),
        posture=getattr(getattr(kernel, "hitl", None), "development_posture", None),
        # HOW this caller authenticated, which is the only fact here the store
        # cannot answer. Defaults to "machine" on a principal that does not say,
        # so a resolver nobody labelled is refused rather than admitted (D4).
        credential_kind=getattr(principal, "credential_kind", "machine"),
    )
    if block == "approval is not request-bound":
        raise HTTPException(status_code=409, detail=block)
    if block is not None:
        raise HTTPException(status_code=403, detail=block)
    return relief


async def authorize_hitl_response(
    kernel: Any, principal: Any, request: HITLRequest
) -> bool:
    """Apply common scope, then the type-specific mutation authorization.

    Returns the relief the APPROVAL path applied, if any (see
    authorize_approval_response) - the caller MUST audit-flag it."""
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
