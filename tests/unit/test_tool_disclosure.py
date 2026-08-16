"""Unit tests for the pure tool-disclosure offer (progressive disclosure, slice 1).

The claims pinned here:

  * THE SUBSET INVARIANT. The offer is always a subset of what the grants admit,
    and it is computed by asking the grant primitive, so deny-dominance and the
    terminal-wildcard rule survive ranking. An upper bound on authority is not
    the selection of what an agent is offered, and this is that rule one level
    up from the ceiling itself.
  * DISCLOSURE IS NOT DEAUTHORISATION. Truncating to a budget, or to nothing at
    all, changes what reaches a model's context and changes no one's authority:
    every verb dropped from the offer is still permitted by the same grants.
  * THE RANKING RULE, one signal at a time, each isolated by making the
    lexicographic tie-break disagree with it, so a passing test cannot be an
    accident of alphabetical order.
  * FAIL-CLOSED INPUTS and determinism: an unvalidated budget, ceiling or skill
    id yields no offer at all, and identical inputs in any order give the
    identical offer.
"""

from __future__ import annotations

import pytest

from boltrig.kernel.tool_disclosure import (
    ToolDisclosureError,
    compute_tool_offer,
    offer_payload,
)
from boltrig.models import Consequence, GrantSet, Verb

TENANT = "acme"


def _verb(
    verb_id: str,
    *,
    noun: str | None = None,
    consequence: Consequence = Consequence.LOW,
) -> Verb:
    return Verb(
        id=verb_id,
        tenant_id=TENANT,
        noun_id=noun if noun is not None else verb_id.split(".")[0],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        description=f"{verb_id} - a candidate tool",
        consequence=consequence,
    )


def _ids(offer: tuple[Verb, ...]) -> list[str]:
    return [verb.id for verb in offer]


@pytest.mark.unit
def test_the_offer_is_always_a_subset_of_what_the_grants_admit() -> None:
    verbs = [
        _verb("mail.send"),
        _verb("mail.read"),
        _verb("ticket.create"),
        _verb("ticket.close"),
        _verb("payroll.pay"),
    ]
    grants = GrantSet.of(["mail.*", "ticket.create"])

    offer = compute_tool_offer(verbs, grants, (), 100)

    assert offer, "a granted surface must produce a non-empty offer"
    for verb in offer:
        assert grants.permits(verb.id), f"{verb.id} was offered without a grant"
    assert set(_ids(offer)) <= {verb.id for verb in verbs if grants.permits(verb.id)}
    assert "payroll.pay" not in _ids(offer)
    assert "ticket.close" not in _ids(offer)


@pytest.mark.unit
def test_a_denied_verb_is_never_offered_even_when_a_loaded_skill_names_its_noun() -> None:
    # The skill affinity signal is the strongest one in the ranking key, so this
    # is the case where a ranking rule could plausibly out-argue an active deny.
    verbs = [_verb("mail.send"), _verb("mail.read")]
    grants = GrantSet.of(["mail.*"], ["mail.send"])

    offer = compute_tool_offer(verbs, grants, ("ops/mail",), 100)

    assert _ids(offer) == ["mail.read"]


@pytest.mark.unit
def test_truncating_the_offer_removes_context_and_removes_no_authority() -> None:
    verbs = [_verb(f"doc.v{index}") for index in range(5)]
    grants = GrantSet.of(["doc.*"])

    offer = compute_tool_offer(verbs, grants, (), 2)

    assert len(offer) == 2
    dropped = [verb for verb in verbs if verb.id not in _ids(offer)]
    assert len(dropped) == 3
    for verb in dropped:
        assert grants.permits(verb.id), "truncation must not touch authority"


@pytest.mark.unit
def test_a_zero_budget_offers_nothing_and_still_authorises_everything() -> None:
    verbs = [_verb("doc.read"), _verb("doc.write")]
    grants = GrantSet.of(["doc.*"])

    assert compute_tool_offer(verbs, grants, (), 0) == ()
    assert all(grants.permits(verb.id) for verb in verbs)


@pytest.mark.unit
def test_an_empty_ceiling_offers_nothing() -> None:
    verbs = [_verb("doc.read"), _verb("doc.write")]

    assert compute_tool_offer(verbs, GrantSet.of([]), (), 100) == ()


@pytest.mark.unit
def test_a_budget_larger_than_the_granted_surface_offers_all_of_it() -> None:
    verbs = [_verb("doc.read"), _verb("doc.write")]
    grants = GrantSet.of(["doc.*"])

    assert _ids(compute_tool_offer(verbs, grants, (), 100)) == ["doc.read", "doc.write"]


@pytest.mark.unit
def test_a_loaded_skill_pulls_its_noun_into_a_budget_of_one() -> None:
    # alpha.read wins on the alphabet, so only the skill signal can explain mail.
    verbs = [_verb("alpha.read"), _verb("mail.send")]

    offer = compute_tool_offer(verbs, GrantSet.of(["*"]), ("ops/mail",), 1)

    assert _ids(offer) == ["mail.send"]


@pytest.mark.unit
def test_an_exactly_named_grant_outranks_a_verb_a_wildcard_merely_reached() -> None:
    # a.alpha wins on the alphabet; a.zebra is the one the operator named.
    verbs = [_verb("a.alpha"), _verb("a.zebra")]

    offer = compute_tool_offer(verbs, GrantSet.of(["a.*", "a.zebra"]), (), 1)

    assert _ids(offer) == ["a.zebra"]


@pytest.mark.unit
def test_a_low_consequence_verb_outranks_a_high_consequence_peer() -> None:
    # b.alpha wins on the alphabet; b.zebra is the one that needs no approval.
    verbs = [_verb("b.alpha", consequence=Consequence.HIGH), _verb("b.zebra")]

    offer = compute_tool_offer(verbs, GrantSet.of(["b.*"]), (), 1)

    assert _ids(offer) == ["b.zebra"]


@pytest.mark.unit
def test_the_order_is_total_and_independent_of_the_order_the_verbs_arrived_in() -> None:
    verbs = [_verb("c.one"), _verb("c.two"), _verb("c.three")]
    grants = GrantSet.of(["c.*"])

    forward = _ids(compute_tool_offer(verbs, grants, (), 100))
    backward = _ids(compute_tool_offer(list(reversed(verbs)), grants, (), 100))

    assert forward == backward == ["c.one", "c.three", "c.two"]


@pytest.mark.unit
def test_a_repeated_verb_id_is_offered_once() -> None:
    verbs = [_verb("e.one"), _verb("e.one"), _verb("e.two")]

    offer = compute_tool_offer(verbs, GrantSet.of(["e.*"]), (), 100)

    assert _ids(offer) == ["e.one", "e.two"]


@pytest.mark.unit
def test_the_offer_carries_the_verb_rows_themselves_so_a_caller_can_render_them() -> None:
    verb = _verb("doc.read")

    offer = compute_tool_offer([verb], GrantSet.of(["doc.*"]), (), 100)

    assert offer[0] is verb
    assert offer[0].input_schema == {"type": "object"}


@pytest.mark.unit
def test_model_description_names_high_consequence_without_inventing_other_hints() -> None:
    high = _verb("doc.publish", consequence=Consequence.HIGH)
    low = _verb("doc.read")

    payload = {
        item["name"]: item
        for item in offer_payload([high, low], GrantSet.of(["doc.*"]), ("ops/doc",))
    }

    assert "high-consequence" in payload["doc.publish"]["description"]
    assert "human approval" in payload["doc.publish"]["description"]
    assert "has not executed" in payload["doc.publish"]["description"]
    assert payload["doc.read"]["description"] == low.description
    for item in payload.values():
        assert "destructive" not in item["description"].lower()
        assert "idempotent" not in item["description"].lower()


@pytest.mark.unit
@pytest.mark.parametrize("budget", [-1, True, 1.0, "3", None])
def test_a_budget_that_is_not_a_non_negative_int_yields_no_offer(budget: object) -> None:
    verbs = [_verb("doc.read")]
    with pytest.raises(ToolDisclosureError):
        compute_tool_offer(verbs, GrantSet.of(["*"]), (), budget)


@pytest.mark.unit
def test_a_ceiling_that_is_not_the_grant_primitive_is_refused() -> None:
    with pytest.raises(ToolDisclosureError):
        compute_tool_offer([_verb("doc.read")], ["doc.*"], (), 10)


@pytest.mark.unit
def test_a_skill_id_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(ToolDisclosureError):
        compute_tool_offer([_verb("doc.read")], GrantSet.of(["*"]), (7,), 10)


@pytest.mark.unit
def test_the_function_mutates_nothing_it_is_handed() -> None:
    verbs = [_verb("doc.write"), _verb("doc.read")]
    order_before = _ids(tuple(verbs))
    grants = GrantSet.of(["doc.*"], ["doc.purge"])
    skills = ["ops/doc"]

    compute_tool_offer(verbs, grants, skills, 1)

    assert _ids(tuple(verbs)) == order_before
    assert grants == GrantSet.of(["doc.*"], ["doc.purge"])
    assert skills == ["ops/doc"]
