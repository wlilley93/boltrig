"""Legacy runtime lanes are gated behind BOLTRIG_ENABLE_LEGACY_RUNTIMES (decision 0012).

Codex is the only target agent runtime and script stays the deterministic
non-agent fallback; every other lane (hermes / openai / claude-api / opencode /
rivet) is staged-cutover rollback residue. With the flag unset a legacy lane
request returns the typed unavailable result instead of reaching the lane; with
it set, dispatch is exactly what it was (rollback-ability).

GATED is not RETIRED, and the difference is the point of this file. A gated lane
comes back by setting one environment variable; a retired lane (``pi``, removed
under [2026] VJS-PC 20 L1) does not come back at all, and lands on the same typed
unavailable result by the UNKNOWN-kind path instead.

This file also carries the discharge of PC-20 **L3**, which conditions the whole
retirement: the multi-runtime routing mechanism must stay LIVE CODE and at least
one non-Codex leaf must stay re-wirable by configuration alone, with no fresh
order, while production_ready is False. That is a property of the shipped code, so
it gets an assertion rather than a sentence in a document.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.runtime import (
    _LEGACY_RUNTIME_KINDS,
    LEGACY_RUNTIMES_ENV,
    ClaudeApiRuntime,
    OpenAiRuntime,
    ScriptRuntime,
    UnavailableRuntime,
    build_runtime,
)
from boltrig.models import AgentCapability, GrantSet, InvocationContext

T = "acme"


def _cap(runtime: str) -> AgentCapability:
    return AgentCapability("w", T, runtime, ["*"], 2, True, "standard", model_endpoint=None)


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="w")


@pytest.mark.parametrize(
    "kind",
    ["hermes", "openai", "claude-api", "opencode", "rivet", "rivet_agentos", "rivet-agentos"],
)
def test_legacy_lanes_are_gated_off_by_default(monkeypatch, kind):
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    assert isinstance(build_runtime(_cap(kind)), UnavailableRuntime)


async def test_gated_lane_returns_the_typed_unavailable_result(monkeypatch):
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    rt = build_runtime(_cap("opencode"))
    res = await rt.run("hello", _ctx(), tools=[])
    # degrade-marked under the REQUESTED lane's name, never an unmarked echo
    assert res.ok and res.degraded
    assert res.output["_degraded"] == {"runtime": "opencode", "reason": "runtime_unavailable"}


# --------------------------------------------------------------------------- #
# The Pi lane is RETIRED, not gated ([2026] VJS-PC 20 L1)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("FR-RUN-01")
async def test_a_retired_pi_capability_still_degrades_rather_than_crashing(monkeypatch):
    """A manifest left naming ``runtime: pi`` must degrade, not raise (P9).

    This is the compatibility question the retirement actually turns on. Both prod
    tenants have the lane disabled, but a tenant manifest, an ai_config or a stored
    capability can still SAY ``pi`` after the code is gone, and the honest outcome
    is the same typed unavailable result it produced while gated - reached by the
    unknown-kind fallback now instead of the legacy gate. Observably identical, so
    no deploy changes behaviour on the day the lane is deleted.
    """
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    rt = build_runtime(_cap("pi"))
    res = await rt.run("hello", _ctx(), tools=[])
    assert res.ok and res.degraded
    assert res.output["_degraded"] == {"runtime": "pi", "reason": "runtime_unavailable"}


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-01")
def test_the_opt_in_flag_does_not_bring_pi_back(monkeypatch):
    """The flag is the difference between GATED and RETIRED.

    Setting it restores every remaining legacy lane. It must NOT restore Pi: there
    is no Pi lane left to restore, and a test that only checked the flag-unset case
    would pass identically whether the lane was deleted or merely gated.
    """
    monkeypatch.setenv(LEGACY_RUNTIMES_ENV, "1")
    assert "pi" not in _LEGACY_RUNTIME_KINDS
    assert isinstance(build_runtime(_cap("pi")), UnavailableRuntime)


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-21")
def test_the_multi_runtime_routing_seam_stays_live(monkeypatch):
    """[2026] VJS-PC 20 L3, asserted rather than asserted-in-prose.

    The grant to collapse the wired roster to Codex alone is CONDITIONED on the
    routing mechanism remaining live code, with at least one non-Codex governed
    leaf re-wirable by configuration alone and no fresh order, until
    production_ready is unblocked. Emptying this set, or reducing it to Codex, is
    expressly forbidden. So: the roster is non-empty, and a lane in it is really
    constructed - not merely listed - by setting one environment variable.
    """
    assert _LEGACY_RUNTIME_KINDS, "PC-20 L3 forbids removing the routing mechanism"
    monkeypatch.setenv(LEGACY_RUNTIMES_ENV, "1")
    rewired = [build_runtime(_cap(kind)) for kind in sorted(_LEGACY_RUNTIME_KINDS)]
    assert [rt for rt in rewired if not isinstance(rt, UnavailableRuntime)], (
        "no non-Codex leaf is re-wirable by configuration alone: PC-20 L3 is breached"
    )


def test_opt_in_flag_restores_legacy_dispatch(monkeypatch):
    monkeypatch.setenv(LEGACY_RUNTIMES_ENV, "1")
    assert isinstance(build_runtime(_cap("openai")), OpenAiRuntime)
    assert isinstance(build_runtime(_cap("claude-api")), ClaudeApiRuntime)
    assert not isinstance(build_runtime(_cap("openai")), UnavailableRuntime)


def test_provider_override_to_a_legacy_lane_is_gated_too(monkeypatch):
    # An ai_config provider override (D5) cannot reach a legacy lane while gated.
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    rt = build_runtime(_cap("script"), runtime_override="openai")
    assert isinstance(rt, UnavailableRuntime)


def test_script_lane_is_not_gated(monkeypatch):
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    rt = build_runtime(_cap("script"))
    assert isinstance(rt, ScriptRuntime) and not isinstance(rt, UnavailableRuntime)
    # an unknown kind was ALREADY the unavailable fallback, flag or no flag
    assert isinstance(build_runtime(_cap("frobnicate")), UnavailableRuntime)
