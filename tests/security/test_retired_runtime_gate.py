"""Codex is the only shipped model-backed agent runtime."""

from __future__ import annotations

import pytest

from boltrig.fleet.runtime import ScriptRuntime, UnavailableRuntime, build_runtime
from boltrig.models import AgentCapability, GrantSet, InvocationContext

T = "acme"
RETIRED = (
    "pi",
    "hermes",
    "openai",
    "claude-api",
    "opencode",
    "rivet",
    "rivet_agentos",
    "rivet-agentos",
)


def _cap(runtime: str) -> AgentCapability:
    return AgentCapability("w", T, runtime, ["*"], 2, True, "standard")


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-01")
@pytest.mark.invariant("FR-RUN-21")
@pytest.mark.parametrize("kind", RETIRED)
async def test_retired_runtime_names_are_inert_even_with_old_opt_in_env(
    monkeypatch, kind: str
) -> None:
    monkeypatch.setenv("BOLTRIG_ENABLE_LEGACY_RUNTIMES", "1")
    runtime = build_runtime(_cap(kind))
    assert isinstance(runtime, UnavailableRuntime)
    result = await runtime.run(
        "hello",
        InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="w"),
        tools=[],
    )
    assert result.degraded
    assert result.output["_degraded"] == {
        "runtime": kind,
        "reason": "runtime_unavailable",
    }


@pytest.mark.invariant("FR-RUN-21")
def test_script_remains_the_only_non_codex_runtime() -> None:
    assert isinstance(build_runtime(_cap("script")), ScriptRuntime)
    assert isinstance(build_runtime(_cap("python-script")), ScriptRuntime)
    assert isinstance(build_runtime(_cap("go-binary")), ScriptRuntime)


@pytest.mark.invariant("FR-RUN-21")
def test_runtime_module_exposes_no_legacy_revival_api() -> None:
    import boltrig.fleet.runtime as runtime_module

    assert not hasattr(runtime_module, "LEGACY_RUNTIMES_ENV")
    assert not hasattr(runtime_module, "OpenAiRuntime")
    assert not hasattr(runtime_module, "ClaudeApiRuntime")
    assert not hasattr(runtime_module, "runtime_for_provider")
