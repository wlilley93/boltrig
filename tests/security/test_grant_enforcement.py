"""Grant enforcement at the kernel (US-IAM-04, SEC-07, K-2)."""

import pytest

from boltrig.models import GrantMissing
from tests.conftest import TENANT, make_ctx
from boltrig.models import GrantSet, TenantPermissions


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
async def test_ungranted_verb_is_denied(kernel):
    # caller holds no grant for ticket.create
    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", "ticket.create", {"title": "x"}, make_ctx([]))


@pytest.mark.security
@pytest.mark.invariant("SEC-07")
async def test_grant_for_other_verb_does_not_authorise(kernel):
    with pytest.raises(GrantMissing):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.read"])
        )


@pytest.mark.security
@pytest.mark.invariant("K-2")
async def test_tenant_ceiling_caps_caller_grants(kernel):
    # Narrow the tenant ceiling so even a caller claiming the grant is denied.
    kernel.store.set_tenant_permissions(
        TenantPermissions(TENANT, GrantSet.of(["ticket.read"]))
    )
    with pytest.raises(GrantMissing):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
