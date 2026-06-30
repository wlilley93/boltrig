"""RLS-live auth bootstrap (SEC-65): the tenant GUC is bound BEFORE the first
RLS-scoped read on every authentication path.

PAT and IdP login both read tenant-scoped rows (``users``, invitations) to build
the principal. Under RLS those reads fail closed unless the tenant is already
bound. The PAT table itself is the one cross-tenant lookup (it resolves the
tenant from the hash); once it does, the tenant must be bound before the owner
read - otherwise a valid token 401s as "de-provisioned". These tests capture the
bound tenant at read time and assert it is already set, so a regression that
moves the bind after the read is caught without needing a live Postgres.
"""

import pytest

from boltrig.identity.provisioning import provision_user
from boltrig.identity.tokens import mint_pat, resolve_pat_principal
from boltrig.models import GrantSet, RoleMapping, User, utcnow
from boltrig.store import InMemoryStore
from boltrig.store.postgres import _current_tenant, set_current_tenant

TENANT = "acme"


def _seed_user() -> User:
    return User(
        id="u1",
        tenant_id=TENANT,
        email="u1@acme.test",
        display_name="U1",
        groups=["eng"],
        role="author",
        scope={},
        status="active",
        source="idp",
        source_group="eng",
        last_seen_at=utcnow(),
        created_at=utcnow(),
    )


@pytest.mark.invariant("SEC-65")
async def test_pat_resolution_binds_tenant_before_the_owner_read():
    store = InMemoryStore()
    user = _seed_user()
    await store.upsert_user(user)
    pat, secret = await mint_pat(
        store,
        tenant_id=TENANT,
        user_id=user.id,
        name="ci",
        requested_scope=["ticket.create"],
        user_grants=GrantSet.of(allow=["ticket.create"]),
    )

    # Capture the tenant bound at the moment the RLS-scoped users read happens.
    seen: list[str | None] = []
    orig_get_user = store.get_user

    async def spy_get_user(tenant_id, user_id):
        seen.append(_current_tenant.get())
        return await orig_get_user(tenant_id, user_id)

    store.get_user = spy_get_user  # type: ignore[method-assign]

    set_current_tenant(None)  # start unbound, as a fresh request would
    p = await resolve_pat_principal(store, secret)

    assert p is not None and p.tenant_id == TENANT
    assert seen == [TENANT]  # bound BEFORE the owner read, not None
    set_current_tenant(None)


@pytest.mark.invariant("SEC-65")
async def test_provision_user_binds_tenant_before_the_first_read():
    store = InMemoryStore()

    seen: list[str | None] = []
    orig_get_user = store.get_user

    async def spy_get_user(tenant_id, user_id):
        seen.append(_current_tenant.get())
        return await orig_get_user(tenant_id, user_id)

    store.get_user = spy_get_user  # type: ignore[method-assign]

    set_current_tenant(None)
    user = await provision_user(
        store,
        tenant_id=TENANT,
        subject="u2",
        email="u2@acme.test",
        groups=["eng"],
        mappings=[RoleMapping(tenant_id=TENANT, idp_group="eng", role="author", scope={})],
    )

    assert user is not None and user.tenant_id == TENANT
    assert seen == [TENANT]  # the existing-user read saw the bound tenant
    set_current_tenant(None)
