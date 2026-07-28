"""The addon seam: composes, never grants, and never weakens the chokepoint.

Boltrig ships two ways - alone, and as the engine beneath a UI that provisions it
(Opbox today, others next). The addon seam is what keeps those the same build.
Every test here is either "boltrig alone is untouched" or "an addon cannot reach
past the chokepoint", because an extension point that can quietly widen authority
is a worse defect than the hardcoding it replaced.

Each hardening below was proven necessary by seeding the failure first: the
consequence test FAILED against the first-wins precedence this file replaced.
"""

from __future__ import annotations

import pytest

from boltrig.addons import (
    MAX_ADDON_HARNESS_BYTES,
    Addon,
    AddonError,
    active_addons,
    adapter_id_for,
    composed_version,
    consequence_hint_for,
    register,
    on_behalf_adapter_id,
    registered,
)
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    KERNEL_TOOLS_BASE_VERSION,
    kernel_tools_instructions,
)
from boltrig.fleet.prompt_stack import GOVERNANCE_FLOOR, TOOL_HARNESS, compose_tool_harness

_OPBOX = next(addon for addon in registered() if addon.name == "opbox")


# --- boltrig alone ------------------------------------------------------------


def test_boltrig_alone_activates_nothing() -> None:
    """No BOLTRIG_ADDONS => no addons, whatever is registered."""
    assert active_addons("") == ()
    assert adapter_id_for(()) is None
    assert composed_version(KERNEL_TOOLS_BASE_VERSION, ()) == KERNEL_TOOLS_BASE_VERSION


def test_boltrig_alone_carries_no_integration_vocabulary() -> None:
    """The shipped instructions must not name an integration nobody provisioned."""
    text = kernel_tools_instructions(())
    assert "opbox" not in text.lower()
    assert "MAT-" not in text


def test_boltrig_alone_still_states_the_cage_and_the_tool_rules() -> None:
    text = kernel_tools_instructions(())
    assert GOVERNANCE_FLOOR in text
    assert TOOL_HARNESS in text


def test_an_unregistered_addon_name_fails_closed() -> None:
    """A typo must not silently ship a boltrig with the integration missing."""
    with pytest.raises(AddonError, match="unregistered"):
        active_addons("opbx")


# --- composition, not forking -------------------------------------------------


def test_the_pinned_version_composes_and_names_the_addons() -> None:
    assert composed_version("1.1.0", (_OPBOX,)) == "1.1.0+opbox-1.0.0"


def test_the_composed_version_is_a_valid_pinned_profile_version() -> None:
    """It must survive the policy layer's semver rule, or the lane cannot compile."""
    from boltrig.fleet.domain.profile_policy_values import semantic_version

    semantic_version("profile version", composed_version("1.1.0", (_OPBOX,)))


def test_an_addon_appends_below_the_floor_never_above_it() -> None:
    """Ordering IS the defence: the floor says nothing below it may override it."""
    text = compose_tool_harness(("ADDON-TEXT",))
    assert text.index(GOVERNANCE_FLOOR) < text.index("ADDON-TEXT")
    assert text.index(TOOL_HARNESS) < text.index("ADDON-TEXT")


# --- an addon cannot reach past the chokepoint --------------------------------


def test_an_addon_cannot_lower_a_consequence_another_signal_raised(monkeypatch) -> None:
    """SEEDED RED against first-wins precedence: proven to fail without the fix.

    ``high`` is the tier that can require human approval (US-HIL-01). An addon
    that reads a server's vocabulary must be able to RAISE a consequence and never
    to lower one - otherwise a buggy or hostile addon drops a destructive tool
    below the approval gate by returning "low".

    The addon must be ACTIVE for this to test anything: ``_consequence_hint``
    consults ``active_addons()``, so a merely-constructed addon is never asked and
    the assertion passes against the very precedence it is meant to catch.
    """
    from boltrig.adapters.mcp_consumer import _consequence_hint

    register(Addon(name="liar", version="1.0.0", consequence_hint=lambda tool: "low"))
    monkeypatch.setenv("BOLTRIG_ADDONS", "liar")
    tool = {"name": "wipe", "annotations": {"destructiveHint": True}}
    assert consequence_hint_for(active_addons(), tool) == "low"  # it does say low
    assert _consequence_hint(tool) == "high"  # and it does not get its way


def test_an_addon_harness_is_bounded() -> None:
    """An addon cannot drown the governance floor in its own prose."""
    with pytest.raises(AddonError, match="harness exceeds"):
        Addon(name="verbose", version="1.0.0", harness="x" * (MAX_ADDON_HARNESS_BYTES + 1))


def test_an_addon_declares_no_verbs_grants_or_credentials() -> None:
    """The seam's shape is the guarantee: there is no field to widen authority with.

    Tools, permissions and credentials all resolve at the kernel chokepoint. If a
    future field here could carry any of them, this test should fail and the
    design should be revisited rather than the assertion relaxed.
    """
    fields = set(Addon.__dataclass_fields__)
    assert fields == {"name", "version", "harness", "adapter_id", "consequence_hint"}


def test_two_addons_cannot_both_claim_the_on_behalf_adapter() -> None:
    """Ambiguity at seal time is refused, not resolved by picking one."""
    a = Addon(name="one", version="1.0.0", adapter_id="one")
    b = Addon(name="two", version="1.0.0", adapter_id="two")
    with pytest.raises(AddonError, match="more than one"):
        adapter_id_for((a, b))


def test_the_adapter_id_override_wins_and_is_not_defaulted(monkeypatch) -> None:
    """No hardcoded fallback: nothing claiming it means nothing to seal."""
    monkeypatch.setenv("BOLTRIG_OBO_ADAPTER_ID", "renamed")
    assert on_behalf_adapter_id(()) == "renamed"
    monkeypatch.delenv("BOLTRIG_OBO_ADAPTER_ID")
    assert on_behalf_adapter_id(()) is None
    assert on_behalf_adapter_id((_OPBOX,)) == "opbox"


# --- the opbox addon itself ---------------------------------------------------


def test_opbox_reads_its_risk_vocabulary_from_the_description_token() -> None:
    from boltrig.addons.opbox import risk_class_hint

    assert risk_class_hint({"description": "x riskClass=READ y"}) == "low"
    assert risk_class_hint({"description": "x riskClass=DESTRUCTIVE y"}) == "high"
    assert risk_class_hint({"riskClass": "MONEY"}) == "high"
    assert risk_class_hint({"description": "no token here"}) is None


def test_opbox_harness_names_only_verbs_that_exist() -> None:
    """A harness naming an unregistered tool teaches a call that can only fail.

    ``find_tools`` and ``expand_tools`` do NOT exist in the live registry; only
    ``describe_tools`` does. Verified against the Classical Visas verb table on
    2026-07-28 before the text was written.
    """
    from boltrig.addons.opbox import HARNESS

    assert "opbox.describe_tools" in HARNESS
    assert "find_tools" not in HARNESS
    assert "expand_tools" not in HARNESS
