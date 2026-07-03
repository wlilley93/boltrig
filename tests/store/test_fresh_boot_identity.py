"""Fresh-boot Postgres identity + tenancy round-trip (regression net).

A duplicate `users` table in schema.sql (a stale minimal def before the full
Round Four one) shadowed the real table under CREATE TABLE IF NOT EXISTS, so a
FRESH boot got a `users` table with no `role` column and every upsert_user (and
the genesis owner seed) failed. CI was GREEN through it because no Postgres test
ever wrote a user carrying `role` against a freshly schema-applied database - a
coverage hole, not a CI gap (PostgresStore.connect(apply_schema=True) already
loads schema.sql).

This test closes that hole permanently: it drives connect(apply_schema=True) - the
exact fresh-boot path - then writes and reads back a user with the full identity
column set, plus the org/workspace/membership the genesis seed creates. It is
gated on BOLTRIG_TEST_DATABASE_URL, so it RUNS in CI (real Postgres) and skips
cleanly offline. A schema.sql that shadows or drops an identity/tenancy column
turns this red at once.
"""
from __future__ import annotations

import os

import pytest

from boltrig.models import (
    OrgMember,
    Organisation,
    User,
    Workspace,
    WorkspaceMember,
    utcnow,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for the fresh-boot Postgres test"
)

T = "freshboot"


async def _fresh_store():
    """Connect with apply_schema=True (the fresh-boot path), scoped to a clean
    slate for this test's tenant so it is order-independent."""
    from boltrig.store import PostgresStore
    from boltrig.store.postgres import set_current_tenant

    store = await PostgresStore.connect(DSN, apply_schema=True)
    set_current_tenant(T)
    # Clean this tenant's rows only (leave the shared schema + other tenants).
    await store._pool.execute("DELETE FROM workspace_members WHERE tenant_id=$1", T)
    await store._pool.execute("DELETE FROM org_members WHERE tenant_id=$1", T)
    await store._pool.execute("DELETE FROM workspaces WHERE tenant_id=$1", T)
    await store._pool.execute("DELETE FROM organisations WHERE id=$1", T)
    await store._pool.execute("DELETE FROM users WHERE tenant_id=$1", T)
    return store


@pytest.mark.security
async def test_fresh_boot_user_role_roundtrips():
    """upsert_user + get_user preserve the full identity column set on a freshly
    schema-applied Postgres. This is the exact write the duplicate-users bug broke
    (column "role" of relation "users" does not exist)."""
    store = await _fresh_store()
    try:
        now = utcnow()
        u = User(
            id="owner@example.com", tenant_id=T, email="owner@example.com",
            display_name="Owner", groups=[], role="superadmin",
            scope={"all": True}, status="active", source="initiate",
            source_group=None, last_seen_at=now, created_at=now,
        )
        await store.upsert_user(u)
        got = await store.get_user(T, "owner@example.com")
        assert got is not None
        assert got.role == "superadmin"
        assert got.scope == {"all": True}
        assert got.status == "active"
        assert got.source == "initiate"
    finally:
        await store.close()


@pytest.mark.security
async def test_fresh_boot_org_workspace_membership_seed():
    """The genesis seed path (org + workspace + owner memberships) writes and reads
    back on a fresh Postgres - the tenancy tables load and round-trip."""
    store = await _fresh_store()
    try:
        now = utcnow()
        await store.create_org(
            Organisation(id=T, name="Fresh Co", slug=f"fresh-{T}", created_at=now,
                         updated_at=now)
        )
        await store.add_org_member(
            OrgMember(user_id="owner@example.com", tenant_id=T, role="superadmin",
                      created_at=now)
        )
        await store.create_workspace(
            Workspace(id="ws_main", tenant_id=T, name="Main", slug=f"main-{T}",
                      created_at=now, updated_at=now)
        )
        await store.add_workspace_member(
            WorkspaceMember(user_id="owner@example.com", workspace_id="ws_main",
                            tenant_id=T, role="owner", created_at=now)
        )
        org = await store.get_org(T)
        assert org is not None and org.name == "Fresh Co"
        wss = await store.list_workspaces_for_user(T, "owner@example.com")
        assert [w.id for w in wss] == ["ws_main"]
        member = await store.get_workspace_member(T, "ws_main", "owner@example.com")
        assert member is not None and member.role == "owner"
    finally:
        await store.close()
