"""Just-in-time user provisioning and current-grant resolution (Round Four USR).

A user gains access by being in a mapped IdP group (US-USR-01) or by holding a
pending admin invitation (US-USR-02); an unmapped, un-invited identity is denied
(fail-closed). Provisioning records a ``users`` row that is the authority for the
user's *current* role / scope / status, so a personal access token re-checks
against it and a deactivated user's access (and tokens) stop working at once
(US-USR-03, SEC-34).
"""

from __future__ import annotations

import logging

from boltrig.models import EMPTY_GRANTS, GrantSet, RoleMapping, User, utcnow

from .rbac import (
    DEFAULT_ROLE,
    default_scope_for_role,
    grants_for_scope,
    narrow_grants_to_workspace,
    resolve_role,
)

logger = logging.getLogger(__name__)


def current_grants_for_user(user: User) -> GrantSet:
    """The user's CURRENT verb grants: their provisioned scope as a GrantSet, or
    nothing if deactivated (a deactivated user can do nothing; SEC-34)."""
    if user.status != "active":
        return EMPTY_GRANTS
    return grants_for_scope(user.scope)


async def effective_grants_for_request(
    store, user: User, active_workspace_id: str | None
) -> GrantSet:
    """The caller's EFFECTIVE grants for one request ([2026] VJS-COUNTY 8, D11).

    Starts from the user's org/user grants (``current_grants_for_user``) and, ONLY
    when the caller is operating in an active workspace they are a member of, NARROWS
    them by that workspace role's ceiling (``effective = org grants ∩ ceiling``). This
    composes with COUNTY 5: a workspace membership can only intersect authority DOWN,
    never widen it.

    Backward-compat (the critical rule): with NO active workspace - every existing
    single-tenant deploy, and the backfilled default org that has no workspaces - this
    returns EXACTLY today's grants, unchanged. If the caller is not (or no longer) a
    member of the active workspace, it also returns today's grants (fail-closed to the
    org ceiling, which never widens): the membership lookup is authoritative and a
    missing membership row simply applies no narrowing rather than escalating.
    """
    base = current_grants_for_user(user)
    if not active_workspace_id:
        return base  # no active workspace -> today's grants, unchanged (backward-compat)
    member = await store.get_workspace_member(
        user.tenant_id, active_workspace_id, user.id
    )
    if member is None:
        return base  # not a member -> no workspace narrowing (never widen)
    return narrow_grants_to_workspace(base, member.role)


def _conferring_group(groups: list[str], mappings: list[RoleMapping], role: str) -> str | None:
    """Which held IdP group conferred ``role`` (US-USR-04 transparency)."""
    held = set(groups)
    for m in mappings:
        if m.idp_group in held and m.role == role:
            return m.idp_group
    return None


def _scope_from_grants(grants: GrantSet, base_scope: dict | None) -> dict:
    """A visibility scope whose ``grants_for_scope`` reproduces ``grants`` exactly,
    keeping any department visibility from ``base_scope``. Used when first recording
    a user from a principal whose grants are not already scope-derived (the dev
    resolver), so a minted PAT resolves against matching current grants."""
    if "*" in grants.allow:
        return {"all": True}
    scope: dict = {"verbs": list(grants.allow)}
    if grants.deny:
        scope["deny"] = list(grants.deny)
    depts = (base_scope or {}).get("departments")
    if depts:
        scope["departments"] = list(depts)
    return scope


async def ensure_user_record(store, principal) -> User:
    """Upsert a ``users`` row for an authenticated caller from their principal.

    A previously provisioned user's stored role / scope / status is preserved as
    authoritative (so admin adjustments and deactivations stick, US-USR-03); a
    not-yet-seen user is recorded from the principal with a grant-faithful scope so
    a PAT they mint resolves against matching current grants (SEC-34). This lets
    PATs work even where the resolver does not itself provision (the dev resolver)."""
    existing = await store.get_user(principal.tenant_id, principal.subject)
    if existing is not None:
        existing.last_seen_at = utcnow()
        await store.upsert_user(existing)
        return existing
    user = User(
        id=principal.subject,
        tenant_id=principal.tenant_id,
        role=principal.role,
        scope=_scope_from_grants(principal.grants, principal.scope),
        status="active",
        last_seen_at=utcnow(),
    )
    await store.upsert_user(user)
    return user


def _coherent_scope(role: str, scope: dict, subject: str) -> dict:
    """A role that implies authority must not arrive with a scope that grants none.

    Grants come from SCOPE (``grants_for_scope``), never from role, and an empty
    scope is EMPTY_GRANTS by design (K-13, fail-closed). So a user can be minted
    reading ``role=admin`` and holding no authority at all - which is exactly what
    happened to a live client on 2026-07-27: an invitation carried
    ``intended_role="admin"`` with ``intended_scope={}``, and every turn that
    account took had zero verbs while the console showed it as an administrator.
    Nothing errored, because fail-closed is correct; it was fail-SILENT that hid it.

    A scope that was NEVER STATED is filled from the role's canonical mapping. A
    scope that WAS stated is never widened, however narrow - that is a deliberate
    choice and this must not overrule it.
    """
    if scope or not role:
        return scope
    default = default_scope_for_role(role)
    if default is None:
        logger.warning(
            "provisioning %s with role=%s and NO scope: grants come from scope, so "
            "this user will hold no verbs (no canonical scope for that role)",
            subject,
            role,
        )
        return scope
    logger.warning(
        "provisioning %s with role=%s and no stated scope; applying the role's "
        "canonical scope so role and authority agree",
        subject,
        role,
    )
    return default


async def provision_user(
    store,
    *,
    tenant_id: str,
    subject: str,
    email: str | None,
    groups: list[str],
    mappings: list[RoleMapping],
) -> User | None:
    """Provision (or refresh) a user on authenticated login (US-USR-01/02).

    Resolves the role/scope from the caller's mapped IdP groups; if none match,
    honours a pending, UNEXPIRED invitation for the verified email (consumed
    atomically, single-use); otherwise returns ``None`` (fail-closed - the
    caller is denied). A previously provisioned user's stored role / scope /
    status is authoritative (admin adjustments and deactivations stick,
    US-USR-03): re-login refreshes presence metadata only, mirroring
    ``ensure_user_record`` - it never recomputes role/scope over an admin's
    change, and a deactivated user stays deactivated until an admin re-enables
    them (re-login cannot self-revive).
    """
    # RLS-live: the tenant is known on entry (from the verified IdP token), and
    # every read/write below (invitations, users) is RLS-scoped. Bind it before
    # the first read so the _RlsPool does not fail closed on login. No-op for the
    # in-memory store and when RLS is off.
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(tenant_id)

    # A previously provisioned user's stored role / scope / status is
    # authoritative (admin adjustments stick, US-USR-03): re-login refreshes
    # presence metadata only, mirroring ensure_user_record.
    existing = await store.get_user(tenant_id, subject)
    if existing is not None:
        existing.last_seen_at = utcnow()
        existing.groups = list(groups)
        if email:
            existing.email = email
        await store.upsert_user(existing)
        return existing

    role, scope = resolve_role(groups, mappings)
    source = "idp"
    source_group: str | None = None

    if role == DEFAULT_ROLE:  # not in any mapped group -> look for an invitation
        inv = await store.find_pending_invitation(tenant_id, email) if email else None
        if inv is None:
            return None  # unmapped and un-invited -> denied (US-USR-01)
        if inv.expires_at is not None and inv.expires_at <= utcnow():
            return None  # an EXPIRED invitation confers nothing (accept-invite parity)
        # Atomic single-use consume (CAS): only the winner is provisioned; a lost
        # race confers nothing either.
        if not await store.consume_invitation(tenant_id, inv.id):
            return None
        role, scope = inv.intended_role, dict(inv.intended_scope)
        source = "invitation"
        scope = _coherent_scope(role, scope, subject)
    else:
        source_group = _conferring_group(groups, mappings, role)

    user = User(
        id=subject,
        tenant_id=tenant_id,
        email=email,
        groups=list(groups),
        role=role,
        scope=scope,
        status="active",
        source=source,
        source_group=source_group,
        last_seen_at=utcnow(),
        created_at=utcnow(),
    )
    await store.upsert_user(user)
    return user
