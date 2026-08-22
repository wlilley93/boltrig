"""A bearer may name the workspace it acts in, and may not name someone else's.

The routes that switch an active context refuse anything without a first-party
session (`access_routes.py`: "active context requires a session login"), and a
PAT bound a workspace only when its owner belonged to exactly one. So a person
running two businesses from one account had every headless call run UNSCOPED,
which is also the state an embedded Opbox Agents console would have been stuck
in, and what a per-workspace agent roster would have had nothing to key off.

The security property under test is the direction of failure. With no active
workspace, ``effective_grants_for_request`` returns the owner's ORG grants
un-narrowed, so a request naming an out-of-reach workspace must REFUSE. Falling
back to None would answer it by widening the caller's authority.
"""

from __future__ import annotations

import pytest

from boltrig.identity.provisioning import current_grants_for_user
from boltrig.identity.tokens import (
    WorkspaceNotPermitted,
    mint_pat,
    resolve_pat_principal,
)
from boltrig.models import GrantSet, User, Workspace, WorkspaceMember
from boltrig.store import InMemoryStore

T = "acme"
SCOPE = {"verbs": ["ticket.create", "ticket.read"]}


async def _two_businesses(*, second_role: str = "owner"):
    """One account, two workspaces: the Principal's "two businesses" case."""
    store = InMemoryStore()
    user = User(id="u1", tenant_id=T, role="engineer", scope=SCOPE, status="active")
    await store.upsert_user(user)
    for ws, name in (("ws-alpha", "Alpha"), ("ws-beta", "Beta")):
        await store.create_workspace(Workspace(id=ws, tenant_id=T, name=name, slug=ws))
    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws-alpha", tenant_id=T, role="owner")
    )
    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws-beta", tenant_id=T, role=second_role)
    )
    _, secret = await mint_pat(
        store, tenant_id=T, user_id="u1", name="console",
        requested_scope=["ticket.create", "ticket.read"],
        user_grants=current_grants_for_user(user),
    )
    return store, secret


@pytest.mark.security
async def test_a_member_of_two_workspaces_can_select_one():
    store, secret = await _two_businesses()

    alpha = await resolve_pat_principal(store, secret, requested_workspace_id="ws-alpha")
    beta = await resolve_pat_principal(store, secret, requested_workspace_id="ws-beta")

    assert alpha is not None and beta is not None
    assert alpha.active_workspace_id == "ws-alpha"
    assert beta.active_workspace_id == "ws-beta"


@pytest.mark.security
async def test_without_a_request_two_memberships_stay_unscoped():
    """The prior behaviour, unchanged: ambiguity is not resolved by guessing."""
    store, secret = await _two_businesses()

    principal = await resolve_pat_principal(store, secret)

    assert principal is not None
    assert principal.active_workspace_id is None


@pytest.mark.security
async def test_naming_a_workspace_you_are_not_in_refuses():
    store, secret = await _two_businesses()
    await store.create_workspace(
        Workspace(id="ws-theirs", tenant_id=T, name="Theirs", slug="t")
    )

    with pytest.raises(WorkspaceNotPermitted):
        await resolve_pat_principal(store, secret, requested_workspace_id="ws-theirs")


@pytest.mark.security
async def test_a_refused_workspace_does_not_widen_authority():
    """THE PROPERTY THIS FILE EXISTS FOR.

    A silent fallback to None is not a smaller answer, it is a BIGGER one: no
    active workspace means the org grants apply un-narrowed. Here the caller is a
    viewer in ws-beta, so a scoped principal cannot write; if naming an
    out-of-reach workspace fell back to unscoped, it would hand them the write.
    """
    store, secret = await _two_businesses(second_role="viewer")

    scoped = await resolve_pat_principal(store, secret, requested_workspace_id="ws-beta")
    assert scoped is not None
    assert not scoped.grants.permits("ticket.create"), "the viewer ceiling must bite"

    unscoped = await resolve_pat_principal(store, secret)
    assert unscoped.active_workspace_id is None
    assert unscoped.grants.permits("ticket.create"), (
        "unscoped really is wider - which is exactly why a refused workspace "
        "must raise rather than fall back to it"
    )

    with pytest.raises(WorkspaceNotPermitted):
        await resolve_pat_principal(store, secret, requested_workspace_id="ws-nope")


@pytest.mark.security
async def test_a_selected_workspace_is_narrowed_by_its_own_role():
    """Selection is not elevation: each workspace applies its own ceiling."""
    store, secret = await _two_businesses(second_role="viewer")

    alpha = await resolve_pat_principal(store, secret, requested_workspace_id="ws-alpha")
    beta = await resolve_pat_principal(store, secret, requested_workspace_id="ws-beta")

    assert alpha.grants.permits("ticket.create"), "owner in alpha"
    assert not beta.grants.permits("ticket.create"), "viewer in beta"
    assert beta.grants.permits("ticket.read")


@pytest.mark.security
async def test_revoking_membership_takes_the_workspace_away_immediately():
    """Re-checked per request through the session path's own function."""
    store, secret = await _two_businesses()
    assert (
        await resolve_pat_principal(store, secret, requested_workspace_id="ws-beta")
    ).active_workspace_id == "ws-beta"

    await store.remove_workspace_member(T, "ws-beta", "u1")

    with pytest.raises(WorkspaceNotPermitted):
        await resolve_pat_principal(store, secret, requested_workspace_id="ws-beta")


@pytest.mark.security
async def test_a_single_membership_still_binds_without_being_asked():
    store = InMemoryStore()
    user = User(id="u1", tenant_id=T, role="engineer", scope=SCOPE, status="active")
    await store.upsert_user(user)
    await store.create_workspace(Workspace(id="ws-only", tenant_id=T, name="O", slug="o"))
    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws-only", tenant_id=T, role="owner")
    )
    _, secret = await mint_pat(
        store, tenant_id=T, user_id="u1", name="t",
        requested_scope=["ticket.read"], user_grants=GrantSet.of(["ticket.read"]),
    )

    principal = await resolve_pat_principal(store, secret)

    assert principal.active_workspace_id == "ws-only"
