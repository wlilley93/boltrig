"""The layered system prompt is kernel-composed with the governance floor first
and authoritative (Corporate Brain Part III/V; prompt-level twin of the grant
ceiling). Composition correctness; the runtimes prepend it as the system message.
"""

from boltrig.fleet.prompt_stack import GOVERNANCE_FLOOR, compose_system_prompt


def test_floor_is_present_and_first_for_every_agent_tier():
    for tier in ("tier1", "tier2", "ephemeral"):
        sp = compose_system_prompt(tier)
        assert sp is not None
        # the cage is always first, so no lower layer can precede/override it
        assert sp.startswith(GOVERNANCE_FLOOR)


def test_each_tier_has_its_own_character():
    assert "Chief of Staff" in compose_system_prompt("tier1")
    assert "Department Head" in compose_system_prompt("tier2")
    assert "worker" in compose_system_prompt("ephemeral").lower()


def test_department_slant_only_applies_to_heads():
    head = compose_system_prompt(
        "tier2", department="Legal", department_brief="Own all contract review."
    )
    assert "Legal" in head and "contract review" in head
    # a worker never carries a department slant
    assert "department is" not in compose_system_prompt("ephemeral").lower()


def test_head_without_department_still_has_floor_and_character():
    sp = compose_system_prompt("tier2")
    assert sp.startswith(GOVERNANCE_FLOOR) and "Department Head" in sp


def test_human_or_unknown_tier_has_no_agent_character():
    # a human principal / unknown tier asserts no character (runtime sends no system)
    assert compose_system_prompt("human") is None
    assert compose_system_prompt("nonsense") is None
