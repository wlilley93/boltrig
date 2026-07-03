"""Org -> workspace tenancy isolation + integrity ([2026] VJS-COUNTY 8).

The tenancy foundation must not open a cross-tenant hole (SEC-08 stays true): the
organisation is the tenant boundary and every org/workspace/membership read - the
membership queries switching will later use included - is tenant-scoped and can
never surface another tenant's row. A per-workspace role is confined to the
allowed set, and the four new tenant-scoped tables are RLS-fenced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.models import (
    WORKSPACE_ROLES,
    Organisation,
    OrgMember,
    Workspace,
    WorkspaceMember,
)
from boltrig.models.errors import SchemaValidationError
from boltrig.store import InMemoryStore

_RLS = Path("boltrig/store/rls.sql").resolve()
_SCHEMA = Path("boltrig/store/schema.sql").resolve()


async def _seed(store, tenant: str):
    await store.create_org(Organisation(id=tenant, name=tenant, slug=tenant))
    await store.create_workspace(
        Workspace(id=f"{tenant}-ws", tenant_id=tenant, name="ws", slug=f"{tenant}-ws")
    )
    await store.add_org_member(OrgMember(user_id="shared", tenant_id=tenant, role="admin"))
    await store.add_workspace_member(
        WorkspaceMember(
            user_id="shared", workspace_id=f"{tenant}-ws", tenant_id=tenant, role="member"
        )
    )


@pytest.mark.invariant("SEC-103")
async def test_tenancy_reads_are_tenant_scoped_never_cross_tenant():
    store = InMemoryStore()
    # Two tenants, each a full org/workspace/membership set. The user id "shared"
    # deliberately exists in BOTH so a leak would show up as a cross-tenant row.
    await _seed(store, "acme")
    await _seed(store, "globex")

    # Entity reads: acme never sees globex's org or workspace.
    assert (await store.get_org("acme")).id == "acme"
    assert await store.get_org("globex") is not None  # exists, but under its own key
    assert await store.get_workspace("acme", "globex-ws") is None
    assert [w.id for w in await store.list_workspaces("acme")] == ["acme-ws"]

    # Membership reads: acme's rosters never include globex's rows.
    assert {m.tenant_id for m in await store.list_org_members("acme")} == {"acme"}
    assert {
        m.tenant_id for m in await store.list_workspace_members("acme", "acme-ws")
    } == {"acme"}
    # A cross-tenant workspace id under the wrong tenant yields nothing.
    assert await store.list_workspace_members("acme", "globex-ws") == []

    # The switching-seam membership queries stay tenant-scoped for the shared user.
    assert [o.id for o in await store.list_orgs_for_user("acme", "shared")] == ["acme"]
    assert [
        w.id for w in await store.list_workspaces_for_user("acme", "shared")
    ] == ["acme-ws"]
    # remove under the wrong tenant is a no-op (does not reach globex's row).
    await store.remove_workspace_member("acme", "globex-ws", "shared")
    assert len(await store.list_workspace_members("globex", "globex-ws")) == 1


@pytest.mark.invariant("SEC-104")
async def test_workspace_role_must_be_in_the_allowed_set():
    store = InMemoryStore()
    await store.create_org(Organisation(id="acme", name="acme", slug="acme"))
    await store.create_workspace(
        Workspace(id="ws", tenant_id="acme", name="ws", slug="ws")
    )

    # An out-of-set role is refused before it can be persisted.
    with pytest.raises(SchemaValidationError):
        await store.add_workspace_member(
            WorkspaceMember(
                user_id="u1", workspace_id="ws", tenant_id="acme", role="superadmin"
            )
        )
    assert await store.list_workspace_members("acme", "ws") == []

    # Every allowed role is accepted.
    for i, role in enumerate(sorted(WORKSPACE_ROLES)):
        await store.add_workspace_member(
            WorkspaceMember(
                user_id=f"u{i}", workspace_id="ws", tenant_id="acme", role=role
            )
        )
    got = {m.role for m in await store.list_workspace_members("acme", "ws")}
    assert got == set(WORKSPACE_ROLES)


@pytest.mark.invariant("SEC-105")
def test_the_four_tenancy_tables_are_rls_scoped():
    rls = _RLS.read_text(encoding="utf-8")
    schema = _SCHEMA.read_text(encoding="utf-8")

    # The three tenant_id-column tables are in the generic scoped array.
    for table in ("workspaces", "org_members", "workspace_members"):
        assert f"'{table}'" in rls, f"{table} missing from rls.sql scoped set"
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in schema

    # organisations is fenced via its own id-keyed policy (id IS tenant_id).
    assert "CREATE TABLE IF NOT EXISTS organisations (" in schema
    assert "CREATE POLICY tenant_isolation ON organisations" in rls
    assert "id = current_setting('app.tenant_id', true)" in rls
