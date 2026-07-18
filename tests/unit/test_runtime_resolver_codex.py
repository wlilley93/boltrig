"""RuntimeResolver codex-lane gating ([2026] VJS-CC-VJS 2).

``_codex_config`` returns the injected trusted-Codex config ONLY for a capability
whose ``runtime == "codex"``, and NEVER on a ``runtime_override`` (Codex is a
trusted, hard-walled lane, not a provider-routing target). Off by default (no
config injected) it returns None so ``build_runtime`` degrades to ScriptRuntime.
"""

from __future__ import annotations

from boltrig.fleet.runtime_resolver import RuntimeResolver
from boltrig.models import AgentCapability


def _capability(runtime: str) -> AgentCapability:
    return AgentCapability(
        name="cap",
        tenant_id="tenant-1",
        runtime=runtime,
        supported_skills=["*"],
        max_depth=2,
        is_ephemeral=True,
        cost_tier="standard",
    )


def _resolver(codex_config: dict[str, object] | None) -> RuntimeResolver:
    # RuntimeResolver.__init__ only stores the kernel; a sentinel object is enough.
    return RuntimeResolver(object(), codex_config=codex_config)


def test_codex_config_none_for_non_codex_capability() -> None:
    resolver = _resolver({"trusted": True})
    assert resolver._codex_config(_capability("pi"), None) is None


def test_codex_config_returns_injected_for_codex_capability() -> None:
    injected = {"trusted": True, "provider": object()}
    resolver = _resolver(injected)
    assert resolver._codex_config(_capability("codex"), None) is injected


def test_codex_config_never_triggers_on_runtime_override() -> None:
    injected = {"trusted": True}
    resolver = _resolver(injected)
    # A non-codex capability with runtime_override == "codex" must NOT select the
    # trusted lane: gating is on capability.runtime only.
    assert resolver._codex_config(_capability("pi"), "codex") is None


def test_codex_config_none_when_no_config_injected() -> None:
    resolver = _resolver(None)
    assert resolver._codex_config(_capability("codex"), None) is None
