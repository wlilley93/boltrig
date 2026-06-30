"""Tenant isolation: no cross-tenant read or dispatch (SEC-08, K-22)."""

import pytest

from boltrig.models import BindingNotFound, GrantSet, TenantPermissions
from tests.conftest import make_ctx


@pytest.mark.security
@pytest.mark.invariant("SEC-08")
async def test_other_tenant_cannot_see_this_tenants_verbs(kernel):
    # kernel registered verbs under TENANT only; a different tenant sees nothing.
    kernel.store.set_tenant_permissions(
        TenantPermissions("other", GrantSet.of(["ticket.*"]))
    )
    disco = await kernel.discover("other")
    assert disco["verbs"] == []


@pytest.mark.security
@pytest.mark.invariant("SEC-08")
async def test_other_tenant_dispatch_fails_closed(kernel):
    kernel.store.set_tenant_permissions(
        TenantPermissions("other", GrantSet.of(["ticket.*"]))
    )
    ctx = make_ctx(["ticket.create"])
    # override the tenant on the context to the foreign tenant
    from dataclasses import replace

    other_ctx = replace(ctx, tenant_id="other")
    with pytest.raises(BindingNotFound):
        await kernel.invoke("ticket", "ticket.create", {"title": "x"}, other_ctx)


@pytest.mark.security
async def test_this_tenant_still_works(kernel):
    out = await kernel.invoke(
        "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
    )
    assert out["status"] == "open"
