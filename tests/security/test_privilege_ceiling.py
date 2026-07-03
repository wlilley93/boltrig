"""Privilege ceiling on the roster routes (SEC-102, security review of COUNTY 7).

update_user and create_invite previously wrote role/scope from the request body
with no clamp, and _require_admin admits the admin tier, so an admin could set its
own role to superadmin or invite a superadmin (materialised by first-party
accept-invite). _reject_escalation closes that: no principal may grant a role
ranked above its own, and only the owner (superadmin) may grant all-authority scope.
"""
from __future__ import annotations

import pytest

from boltrig.kernel.access_routes import _reject_escalation
from boltrig.models.errors import GrantMissing


class _P:
    def __init__(self, role: str) -> None:
        self.role = role
        self.subject = "u"
        self.tenant_id = "t"


@pytest.mark.security
@pytest.mark.invariant("SEC-102")
def test_admin_cannot_grant_a_role_above_its_own():
    admin = _P("admin")
    with pytest.raises(GrantMissing):
        _reject_escalation(admin, "superadmin", None)  # admin -> superadmin blocked
    org_admin = _P("org-admin")
    with pytest.raises(GrantMissing):
        _reject_escalation(org_admin, "superadmin", None)
    with pytest.raises(GrantMissing):
        _reject_escalation(org_admin, "admin", None)  # org-admin ranks below admin


@pytest.mark.security
@pytest.mark.invariant("SEC-102")
def test_only_owner_may_grant_all_authority_scope():
    admin = _P("admin")
    with pytest.raises(GrantMissing):
        _reject_escalation(admin, "member", {"all": True})
    # The owner tier may.
    _reject_escalation(_P("superadmin"), "superadmin", {"all": True})


@pytest.mark.security
@pytest.mark.invariant("SEC-102")
def test_granting_an_equal_or_lower_role_is_allowed():
    admin = _P("admin")
    _reject_escalation(admin, "member", None)  # lower - fine
    _reject_escalation(admin, "admin", None)  # equal - fine
    _reject_escalation(admin, None, None)  # no change - fine
