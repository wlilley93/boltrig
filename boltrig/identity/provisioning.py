"""Just-in-time user provisioning and current-grant resolution (Round Four USR).

A user gains access by being in a mapped IdP group (US-USR-01) or by holding a
pending admin invitation (US-USR-02); an unmapped, un-invited identity is denied
(fail-closed). Provisioning records a ``users`` row that is the authority for the
user's *current* role / scope / status, so a personal access token re-checks
against it and a deactivated user's access (and tokens) stop working at once
(US-USR-03, SEC-34).
"""

from __future__ import annotations

from boltrig.models import EMPTY_GRANTS, GrantSet, RoleMapping, User, utcnow

from .rbac import DEFAULT_ROLE, grants_for_scope, resolve_role


def current_grants_for_user(user: User) -> GrantSet:
    """The user's CURRENT verb grants: their provisioned scope as a GrantSet, or
    nothing if deactivated (a deactivated user can do nothing; SEC-34)."""
    if user.status != "active":
        return EMPTY_GRANTS
    return grants_for_scope(user.scope)


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
    honours a pending invitation for the verified email; otherwise returns
    ``None`` (fail-closed - the caller is denied). A previously deactivated user
    stays deactivated until an admin re-enables them (re-login cannot self-revive).
    """
    role, scope = resolve_role(groups, mappings)
    source = "idp"
    source_group: str | None = None

    if role == DEFAULT_ROLE:  # not in any mapped group -> look for an invitation
        inv = await store.find_pending_invitation(tenant_id, email) if email else None
        if inv is None:
            return None  # unmapped and un-invited -> denied (US-USR-01)
        role, scope = inv.intended_role, dict(inv.intended_scope)
        source = "invitation"
        inv.status = "accepted"
        await store.update_invitation(inv)
    else:
        source_group = _conferring_group(groups, mappings, role)

    existing = await store.get_user(tenant_id, subject)
    status = existing.status if existing else "active"  # deactivation persists
    user = User(
        id=subject,
        tenant_id=tenant_id,
        email=email,
        display_name=existing.display_name if existing else None,
        groups=list(groups),
        role=role,
        scope=scope,
        status=status,
        source=source,
        source_group=source_group,
        last_seen_at=utcnow(),
        created_at=existing.created_at if existing else utcnow(),
    )
    await store.upsert_user(user)
    return user
