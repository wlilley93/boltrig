"""Org -> workspace tenancy foundation ([2026] VJS-COUNTY 8, D1/D2/D3).

Proves the tenancy data model + membership on BOTH stores (parity): the in-memory
store everywhere, Postgres when BOLTRIG_TEST_DATABASE_URL is set (skips cleanly
offline). This is the FOUNDATION phase - the entities + membership queries only;
no InvocationContext threading, switching, or resource-table workspace_id yet.
"""

from __future__ import annotations

import os

import pytest

from boltrig.identity import ensure_default_org
from boltrig.models import (
    Organisation,
    OrgMember,
    Workspace,
    WorkspaceMember,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "organisations,workspaces,org_members,workspace_members"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    return await _make_store(request.param)


@pytest.mark.invariant("FR-ORG-01")
async def test_workspace_always_belongs_to_an_org(store):
    # D1/D2: an org whose id IS the tenant_id, and a workspace whose tenant_id is
    # that org - so a workspace can never be an orphan.
    await store.create_org(Organisation(id=T, name="Acme", slug="acme"))
    org = await store.get_org(T)
    assert org is not None
    assert org.id == T and org.tenant_id == T

    await store.create_workspace(
        Workspace(id="ws1", tenant_id=T, name="Delivery", slug="delivery")
    )
    ws = await store.get_workspace(T, "ws1")
    assert ws is not None
    # The workspace's owning tenant is the org.
    assert ws.tenant_id == org.id
    assert [w.id for w in await store.list_workspaces(T)] == ["ws1"]


@pytest.mark.invariant("FR-ORG-02")
async def test_ensure_default_org_is_idempotent_and_id_is_tenant_id(store):
    # D1: the org id IS the tenant_id, and the backfill is idempotent - a repeat
    # ensure never creates a second org for the same tenant.
    org1 = await ensure_default_org(store, T)
    org2 = await ensure_default_org(store, T)
    assert org1.id == T == org2.id
    orgs = await store.list_orgs()
    assert [o.id for o in orgs] == [T]  # exactly one


async def test_org_and_workspace_membership_roundtrip(store):
    await store.create_org(Organisation(id=T, name="Acme", slug="acme"))
    await store.create_workspace(
        Workspace(id="ws1", tenant_id=T, name="Delivery", slug="delivery")
    )

    await store.add_org_member(OrgMember(user_id="u1", tenant_id=T, role="admin"))
    await store.add_org_member(OrgMember(user_id="u2", tenant_id=T, role="member"))
    assert {m.user_id for m in await store.list_org_members(T)} == {"u1", "u2"}
    assert [o.id for o in await store.list_orgs_for_user(T, "u1")] == [T]

    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws1", tenant_id=T, role="owner")
    )
    members = await store.list_workspace_members(T, "ws1")
    assert [(m.user_id, m.role) for m in members] == [("u1", "owner")]
    assert [w.id for w in await store.list_workspaces_for_user(T, "u1")] == ["ws1"]
    assert await store.list_workspaces_for_user(T, "u2") == []

    await store.remove_workspace_member(T, "ws1", "u1")
    assert await store.list_workspace_members(T, "ws1") == []
    await store.remove_org_member(T, "u1")
    assert {m.user_id for m in await store.list_org_members(T)} == {"u2"}


@pytest.mark.security
@pytest.mark.invariant("SEC-111")
async def test_get_workspace_member_is_tenant_scoped(store):
    # D11: the single-membership lookup the grant chokepoint uses must be tenant-
    # scoped - it only ever returns a row inside the bound tenant, so a membership
    # under another tenant_id can never confer a workspace role across the boundary.
    await store.create_org(Organisation(id=T, name="Acme", slug="acme"))
    await store.create_workspace(
        Workspace(id="ws1", tenant_id=T, name="Delivery", slug="delivery")
    )
    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws1", tenant_id=T, role="admin")
    )

    # In-tenant: the row (and its role) is returned.
    got = await store.get_workspace_member(T, "ws1", "u1")
    assert got is not None and got.role == "admin"

    # Cross-tenant: the SAME workspace_id/user_id under a different tenant resolves
    # to None (fail-closed) - never another tenant's membership row.
    assert await store.get_workspace_member("other-tenant", "ws1", "u1") is None
    # Unknown member -> None.
    assert await store.get_workspace_member(T, "ws1", "nobody") is None


@pytest.mark.security
@pytest.mark.invariant("SEC-111")
async def test_a_membership_write_cannot_reach_another_orgs_workspace(store):
    """Two orgs, the SAME workspace id, the same user - a real configuration.

    Provisioning mints the same workspace id (`ws_default`) for every org and
    `workspaces` is keyed (tenant_id, id), so this collision is guaranteed rather
    than hypothetical. `workspace_members` used to be keyed (workspace_id,
    user_id), so org B's upsert hit ON CONFLICT against org A's row and ran the
    DO UPDATE arm: it rewrote that user's ROLE inside ORG A, while org B's own
    membership never materialised. RLS would have made it an error instead, but
    RLS is opt-in and was unset on every deployment. Migration 0038.
    """
    other = "other-org"
    for org in (T, other):
        await store.create_org(Organisation(id=org, name=org, slug=org))
        await store.create_workspace(
            Workspace(id="ws_default", tenant_id=org, name="Default", slug=f"d-{org}")
        )

    await store.add_workspace_member(
        WorkspaceMember(user_id="u1", workspace_id="ws_default", tenant_id=T, role="owner")
    )
    # Org B adds the same user to ITS workspace, at a lower role.
    await store.add_workspace_member(
        WorkspaceMember(
            user_id="u1", workspace_id="ws_default", tenant_id=other, role="member"
        )
    )

    # Org A's role is UNTOUCHED by org B's write.
    a = await store.get_workspace_member(T, "ws_default", "u1")
    assert a is not None and a.role == "owner", "org B's write reached org A's row"
    # And org B genuinely has its own membership, rather than silently none.
    b = await store.get_workspace_member(other, "ws_default", "u1")
    assert b is not None and b.role == "member"

    # Both list views stay within their own org.
    assert [(m.tenant_id, m.role) for m in await store.list_workspace_members(T, "ws_default")] == [
        (T, "owner")
    ]
    assert [
        (m.tenant_id, m.role) for m in await store.list_workspace_members(other, "ws_default")
    ] == [(other, "member")]

    # Removing org B's membership must not remove org A's.
    await store.remove_workspace_member(other, "ws_default", "u1")
    assert await store.get_workspace_member(T, "ws_default", "u1") is not None
    assert await store.get_workspace_member(other, "ws_default", "u1") is None


async def test_update_org_and_workspace(store):
    await store.create_org(Organisation(id=T, name="Acme", slug="acme"))
    org = await store.get_org(T)
    org.name = "Acme Corp"
    org.allow_own_ai_keys = True
    await store.update_org(org)
    refreshed = await store.get_org(T)
    assert refreshed.name == "Acme Corp"
    assert refreshed.allow_own_ai_keys is True

    await store.create_workspace(
        Workspace(id="ws1", tenant_id=T, name="Delivery", slug="delivery")
    )
    ws = await store.get_workspace(T, "ws1")
    ws.status = "archived"
    await store.update_workspace(ws)
    assert (await store.get_workspace(T, "ws1")).status == "archived"
