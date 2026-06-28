"""GrantSet semantics: deny-dominance (K-5), fail-closed (K-13), wildcards (K-9)."""

import pytest

from nankle.models import GrantSet


@pytest.mark.unit
@pytest.mark.invariant("K-13")
def test_empty_grants_deny_everything():
    g = GrantSet.of([])
    assert not g.permits("ticket.create")


@pytest.mark.unit
def test_exact_and_terminal_wildcard():
    g = GrantSet.of(["ticket.create", "doc.*"])
    assert g.permits("ticket.create")
    assert not g.permits("ticket.delete")
    assert g.permits("doc.read")
    assert g.permits("doc.write")


@pytest.mark.unit
@pytest.mark.invariant("K-9")
def test_wildcard_does_not_match_prefix_collision():
    g = GrantSet.of(["jira.*"])
    assert g.permits("jira.read")
    assert not g.permits("jirax.read")  # prefix-collision rejected


@pytest.mark.unit
@pytest.mark.invariant("K-5")
def test_deny_dominates_allow():
    g = GrantSet.of(allow=["ticket.*"], deny=["ticket.delete"])
    assert g.permits("ticket.create")
    assert not g.permits("ticket.delete")  # deny beats the covering allow


@pytest.mark.unit
def test_star_is_tenant_wide():
    g = GrantSet.of(["*"])
    assert g.permits("anything.at.all")
