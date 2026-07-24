"""GrantSet semantics: deny-dominance (K-5), fail-closed (K-13), wildcards (K-9)."""

import pytest

from boltrig.models import GrantSet


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


@pytest.mark.unit
def test_intersect_expands_a_skill_wildcard_against_an_exact_verb_ceiling():
    # US-IAM-04: a PAT's exact-verb scope must not silently drop a skill's
    # wildcard grants - the wildcard narrows to the ceiling's covered entries.
    skill = GrantSet.of(allow=["opbox.*", "memory.*", "chat.ask_user"])
    ceiling = GrantSet.of(allow=["chat.ask_user", "opbox.matter.list", "memory.remember", "jira.read"])
    effective = skill.intersect(ceiling)
    assert set(effective.allow) == {"chat.ask_user", "opbox.matter.list", "memory.remember"}
    # never widens past either side
    assert "jira.read" not in effective.allow
    assert "opbox.matter.get" not in effective.allow


@pytest.mark.unit
def test_intersect_keeps_existing_exact_and_wildcard_shapes():
    assert GrantSet.of(allow=["opbox.matter.list"]).intersect(GrantSet.of(allow=["opbox.*"])).allow == ("opbox.matter.list",)
    assert GrantSet.of(allow=["opbox.*"]).intersect(GrantSet.of(allow=["opbox.*"])).allow == ("opbox.*",)
    assert GrantSet.of(allow=["opbox.*"]).intersect(GrantSet.of(allow=["*"])).allow == ("opbox.*",)
    assert GrantSet.of(allow=["jira.*"]).intersect(GrantSet.of(allow=["opbox.matter.list"])).allow == ()
