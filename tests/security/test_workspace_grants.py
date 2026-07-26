"""Grant resolution from workspace membership ([2026] VJS-COUNTY 8, D11).

The authorization-critical leg of org/workspace tenancy: when a caller operates
INSIDE an active workspace they are a member of, their org/user grants are NARROWED
by that workspace role's ceiling (effective = org grants ∩ ceiling). This composes
with [2026] VJS-COUNTY 5 (authority is only ever intersected DOWN, never widened).

  - SEC-108: an active member's authority is the INTERSECTION of org grants and the
    workspace-role ceiling, never a union - a member loses the ``control.*`` configure
    namespace, an owner keeps the org grants broad, and narrowing is always a subset.
  - SEC-109: a viewer cannot perform a write verb their org role would otherwise allow
    (the read-only ceiling keeps only concrete read verbs; wildcards collapse).
  - SEC-110: THE CRITICAL RULE - no active workspace (or not a member) keeps EXACTLY
    today's org grants, so every existing single-tenant deploy is unchanged.

These bind at the real seam: ``effective_grants_for_request`` (the grant-resolution
path the session resolver calls) over the InMemoryStore, and the pure
``narrow_grants_to_workspace`` ceiling function, plus an end-to-end assertion through
``GrantSet.permits`` (the chokepoint's verdict) so the intersection actually changes
what a caller may do.
"""

from __future__ import annotations

import pytest

from boltrig.identity.provisioning import (
    current_grants_for_user,
    effective_grants_for_request,
)
from boltrig.identity.rbac import narrow_grants_to_workspace, workspace_role_ceiling
from boltrig.models import GrantSet, User, Workspace, WorkspaceMember
from boltrig.store import InMemoryStore

T = "acme"
WS = "ws-delivery"


async def _store_with_member(role: str, *, user_scope: dict, user_id: str = "u1"):
    """A store seating ``user_id`` with ``user_scope`` as a ``role`` member of one
    active workspace WS, returning (store, user)."""
    store = InMemoryStore()
    user = User(id=user_id, tenant_id=T, role="engineer", scope=user_scope, status="active")
    await store.upsert_user(user)
    await store.create_workspace(Workspace(id=WS, tenant_id=T, name="Delivery", slug="d"))
    await store.add_workspace_member(
        WorkspaceMember(user_id=user_id, workspace_id=WS, tenant_id=T, role=role)
    )
    return store, user


# --- SEC-108: intersection, never union; always a subset ----------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-108")
async def test_active_member_authority_is_org_grants_intersected_with_ceiling():
    # Org grants: broad operate + configure (a wildcard plus a control verb).
    scope = {"verbs": ["ticket.create", "ticket.read", "control.workflow.upsert"]}
    org = current_grants_for_user(User(id="u1", tenant_id=T, scope=scope, status="active"))
    assert org.permits("ticket.create") and org.permits("control.workflow.upsert")

    # As a MEMBER, the caller keeps operate verbs but loses the control.* configure
    # namespace - effective = org ∩ member-ceiling (an intersection, not a union).
    store, user = await _store_with_member("member", user_scope=scope)
    eff = await effective_grants_for_request(store, user, WS)
    assert eff.permits("ticket.create")  # operate: kept
    assert eff.permits("ticket.read")
    assert not eff.permits("control.workflow.upsert")  # configure: narrowed away

    # As an OWNER (broad ceiling), the org grants are preserved unchanged.
    store_o, user_o = await _store_with_member("owner", user_scope=scope, user_id="o1")
    eff_o = await effective_grants_for_request(store_o, user_o, WS)
    assert eff_o.permits("ticket.create") and eff_o.permits("control.workflow.upsert")

    # As an ADMIN (operate + configure), configure is kept but workspace self-admin
    # (control.workspace.*) is owner-only, so it is narrowed away.
    admin_scope = {"verbs": ["ticket.create", "control.workflow.upsert",
                             "control.workspace.member.add"]}
    store_a, user_a = await _store_with_member("admin", user_scope=admin_scope, user_id="a1")
    eff_a = await effective_grants_for_request(store_a, user_a, WS)
    assert eff_a.permits("control.workflow.upsert")  # configure: kept
    assert eff_a.permits("ticket.create")
    assert not eff_a.permits("control.workspace.member.add")  # owner-only: narrowed


@pytest.mark.security
@pytest.mark.invariant("SEC-108")
def test_membership_only_narrows_never_widens():
    # COUNTY 5 property: for EVERY workspace role, narrowing yields a SUBSET of the
    # org grants - a verb the org grant denies is never re-permitted by a ceiling.
    org = GrantSet.of(allow=["ticket.read", "ticket.list"])  # a narrow, read-only org grant
    probe = ["ticket.create", "ticket.delete", "control.workflow.upsert",
             "ticket.read", "ticket.list", "invoice.approve"]
    for role in ("owner", "admin", "member", "agent", "viewer"):
        eff = narrow_grants_to_workspace(org, role)
        for verb in probe:
            if eff.permits(verb):
                # anything the narrowed set permits MUST have been permitted by the org
                assert org.permits(verb), f"{role} widened authority for {verb!r}"

    # An unknown workspace role fails closed to nothing (never widens).
    assert narrow_grants_to_workspace(GrantSet.of(["*"]), "bogus").allow == ()
    assert workspace_role_ceiling("viewer") is None  # viewer has no namespace ceiling


# --- SEC-109: a viewer cannot write, but keeps reads --------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-109")
async def test_viewer_cannot_write_but_keeps_reads():
    # Org grants include an explicit write AND an explicit read verb.
    scope = {"verbs": ["ticket.create", "ticket.delete", "ticket.read", "invoice.read"]}
    store, user = await _store_with_member("viewer", user_scope=scope)
    eff = await effective_grants_for_request(store, user, WS)

    # The write verbs the org role WOULD allow are denied to a workspace viewer.
    assert not eff.permits("ticket.create")
    assert not eff.permits("ticket.delete")
    # Explicit read grants survive.
    assert eff.permits("ticket.read")
    assert eff.permits("invoice.read")

    # A wildcard org grant (ticket.*) spans writes, so a viewer cannot keep it: it
    # collapses (fail-closed, never widen) - the viewer gets no ticket authority.
    wild = narrow_grants_to_workspace(GrantSet.of(["ticket.*"]), "viewer")
    assert not wild.permits("ticket.read")
    assert not wild.permits("ticket.create")


# --- SEC-110: THE CRITICAL RULE - no active workspace keeps full org grants ----
@pytest.mark.security
@pytest.mark.invariant("SEC-110")
async def test_no_active_workspace_keeps_full_org_grants():
    # A single-tenant deploy (no workspaces / no active workspace) keeps EXACTLY
    # today's org grants - effective == current_grants_for_user, byte-for-byte.
    scope = {"verbs": ["ticket.create", "control.workflow.upsert"]}
    store = InMemoryStore()
    user = User(id="u1", tenant_id=T, scope=scope, status="active")
    await store.upsert_user(user)

    org = current_grants_for_user(user)
    eff = await effective_grants_for_request(store, user, None)
    assert (eff.allow, eff.deny) == (org.allow, org.deny)
    assert eff.permits("control.workflow.upsert")  # nothing narrowed away

    # An org-admin ({all: true}) with no active workspace keeps the tenant-wide "*".
    admin = User(id="a1", tenant_id=T, scope={"all": True}, status="active")
    eff_admin = await effective_grants_for_request(store, admin, None)
    assert eff_admin.permits("anything.at_all")


@pytest.mark.security
@pytest.mark.invariant("SEC-110")
async def test_non_member_active_workspace_applies_no_narrowing():
    # An active workspace the caller is NOT a member of applies NO narrowing (fail-
    # closed to the org ceiling, which never widens). The session resolver already
    # drops non-member active workspaces to None; this pins the defence in depth in
    # the grant path itself so a stale/racy active_workspace_id can never narrow-or-
    # escalate against a membership that is not there.
    scope = {"verbs": ["ticket.create", "control.workflow.upsert"]}
    store = InMemoryStore()
    user = User(id="u1", tenant_id=T, scope=scope, status="active")
    await store.upsert_user(user)
    await store.create_workspace(Workspace(id=WS, tenant_id=T, name="D", slug="d"))
    # NOTE: no add_workspace_member - the user is not a member of WS.

    org = current_grants_for_user(user)
    eff = await effective_grants_for_request(store, user, WS)
    assert (eff.allow, eff.deny) == (org.allow, org.deny)
    assert eff.permits("control.workflow.upsert")


# --- SEC-109 on the BEARER path: the hole the direct tests could not see ------
@pytest.mark.security
@pytest.mark.invariant("SEC-109")
async def test_a_viewers_pat_cannot_do_what_their_session_is_refused():
    """The escalation that shipped: the workspace ceiling was applied on the cookie
    path and not on the bearer path.

    Every other test in this file binds the rule at ``effective_grants_for_request``
    or at ``narrow_grants_to_workspace`` - the functions the rule lives in. The PAT
    resolver did not call either of them; it intersected the token's scope with the
    UN-NARROWED org grants while separately binding the user's single workspace as
    active. So the same human, in the same workspace, was refused a write verb
    through the browser and granted it through a token minted from the documented
    POST /v1/me/tokens route.

    A control tested only at the function it lives in says nothing about the path
    that never calls it, which is why this drives the resolver end to end.
    """
    from boltrig.identity.tokens import mint_pat, resolve_pat_principal

    scope = {"verbs": ["ticket.create", "ticket.read"]}
    store, user = await _store_with_member("viewer", user_scope=scope)

    # The org grants really do allow the write - that is what makes this an
    # escalation rather than a token that never had the authority.
    org = current_grants_for_user(user)
    assert org.permits("ticket.create")

    # Mint at the ceiling the session path would compute, as the route does.
    session_grants = await effective_grants_for_request(store, user, WS)
    assert not session_grants.permits("ticket.create"), "the viewer ceiling must bite"
    _, secret = await mint_pat(
        store, tenant_id=T, user_id=user.id, name="cc",
        requested_scope=["ticket.create", "ticket.read"], user_grants=org,
    )

    principal = await resolve_pat_principal(store, secret)
    assert principal is not None
    assert principal.active_workspace_id == WS, "the single membership is bound active"
    assert not principal.grants.permits("ticket.create"), (
        "a viewer's PAT performed a write their session is refused, in the same "
        "workspace, on the same account"
    )
    assert principal.grants.permits("ticket.read"), "reads must still work"
