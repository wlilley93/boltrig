"""A role that implies authority must never be minted with a scope granting none.

The live defect, Classical Visas 2026-07-27: an invitation carried
``intended_role="admin"`` with ``intended_scope={}``. Grants come from SCOPE
(``grants_for_scope``), never from role, and an empty scope is EMPTY_GRANTS by
design (K-13, fail-closed). So the account was minted reading ``role=admin`` and
holding no verbs at all. Every turn it took had zero tools while the console showed
it as an administrator. Nothing errored - fail-closed is correct - and it was
fail-SILENT that hid it for a day.

The rule is boltrig-internal: whoever provisions a user decides WHICH role to ask
for, and boltrig only insists the role it is handed and the authority it confers
agree. No integration knows anything about this file, and this file knows nothing
about any integration.
"""

from __future__ import annotations

import pytest

from boltrig.identity.provisioning import _coherent_scope
from boltrig.identity.rbac import default_scope_for_role, grants_for_scope


@pytest.mark.parametrize("role", ["superadmin", "admin", "org-admin"])
def test_an_authority_role_with_no_stated_scope_gets_its_canonical_scope(role: str) -> None:
    """This is the exact shape that produced a zero-authority administrator."""
    scope = _coherent_scope(role, {}, "someone@example.com")
    assert scope, f"{role} was minted with a scope granting nothing"
    assert grants_for_scope(scope).allow, f"{role} resolves to no verbs"


@pytest.mark.parametrize(
    "role,stated",
    [
        ("admin", {"verbs": ["widget.list"]}),
        ("superadmin", {"nouns": ["widget"]}),
        ("org-admin", {"verbs": ["a.read"], "deny": ["a.write"]}),
    ],
)
def test_a_stated_scope_is_never_widened(role: str, stated: dict) -> None:
    """A narrow scope is a DELIBERATE choice. Filling a blank must not overrule it."""
    assert _coherent_scope(role, dict(stated), "someone@example.com") == stated


def test_a_role_with_no_canonical_scope_is_left_alone_and_still_grants_nothing() -> None:
    """Authority for these roles is tenant policy, not something to invent here.

    It is reported rather than fabricated: the runtime warning and
    `make user-authority` both surface it, so a member with no scope is visible
    instead of silently toolless.
    """
    assert default_scope_for_role("member") is None
    assert _coherent_scope("member", {}, "someone@example.com") == {}
    assert not grants_for_scope({}).allow


def test_the_live_defect_specifically() -> None:
    """role=admin + scope={} - what the client's invitation actually carried."""
    assert not grants_for_scope({}).allow, "an empty scope must stay fail-closed"
    repaired = _coherent_scope("admin", {}, "info@example.com")
    assert grants_for_scope(repaired).allow == ("*",)
