"""Legacy runtime lanes are gated behind BOLTRIG_ENABLE_LEGACY_RUNTIMES (decision 0012).

Codex is the only target agent runtime and script stays the deterministic
non-agent fallback; every other lane (hermes / openai / claude-api / pi /
opencode / rivet) is staged-cutover rollback residue. With the flag unset a
legacy lane request returns the typed unavailable result instead of reaching
the lane; with it set, dispatch is exactly what it was (rollback-ability).
"""

from __future__ import annotations

import pytest

from boltrig.fleet.runtime import (
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
    ["hermes", "openai", "claude-api", "pi", "opencode", "rivet", "rivet_agentos", "rivet-agentos"],
)
def test_legacy_lanes_are_gated_off_by_default(monkeypatch, kind):
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    assert isinstance(build_runtime(_cap(kind)), UnavailableRuntime)


async def test_gated_lane_returns_the_typed_unavailable_result(monkeypatch):
    monkeypatch.delenv(LEGACY_RUNTIMES_ENV, raising=False)
    rt = build_runtime(_cap("pi"))
    res = await rt.run("hello", _ctx(), tools=[])
    # degrade-marked under the REQUESTED lane's name, never an unmarked echo
    assert res.ok and res.degraded
    assert res.output["_degraded"] == {"runtime": "pi", "reason": "runtime_unavailable"}


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
