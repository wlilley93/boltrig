"""Agent-runtime selection for the Codex-owned fleet.

Codex is the only model-backed agent runtime Boltrig ships.  ``ScriptRuntime``
remains as the deterministic, non-agent execution seam used by tests and
integration-only capabilities.  Historical provider-native, OpenCode, and
Rivet runtimes are deliberately not importable or feature-gated: a stale stored
capability naming one fails honestly through ``UnavailableRuntime``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from boltrig.models import InvocationContext

from .result import AgentResult

if TYPE_CHECKING:
    from boltrig.models import AgentCapability


@runtime_checkable
class Runtime(Protocol):
    """How one agent run is executed. Implementations are stateless per call."""

    runtime: str
    cost_tier: str

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Execute the agent and return a structured result."""
        ...


class ScriptRuntime:
    """Deterministic, offline, non-model runtime for explicit script work."""

    runtime = "python-script"

    def __init__(self, *, cost_tier: str = "cheap") -> None:
        self.cost_tier = cost_tier

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        return AgentResult.succeeded(
            output={
                "runtime": self.runtime,
                "task": prompt,
                "tools": list(tools),
                "actor": context.actor,
                "depth": context.depth,
            },
            summary=f"script run by {context.actor} (depth {context.depth})",
            tokens_used=0,
            cost_micros=0,
        )


class UnavailableRuntime(ScriptRuntime):
    """Typed, non-executing result for stale or unconfigured runtime names."""

    def __init__(self, *, requested: str, cost_tier: str = "cheap") -> None:
        super().__init__(cost_tier=cost_tier)
        self._requested = requested

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        return AgentResult.degrade(
            runtime=self._requested, reason="runtime_unavailable", prompt=prompt
        )


def build_runtime(
    capability: AgentCapability,
    endpoint_lookup: object | None = None,
    *,
    codex_config: dict[str, Any] | None = None,
) -> Runtime:
    """Build Codex or an explicit deterministic script runtime.

    ``endpoint_lookup`` remains in the call shape because endpoint resolution is
    owned by ``RuntimeResolver``; it is intentionally unused here.  Unknown and
    retired names never revive a provider client or subprocess lane.
    """

    del endpoint_lookup
    kind = capability.runtime
    if kind == "codex":
        from .codex_runtime import build_trusted_codex_runtime

        return build_trusted_codex_runtime(codex_config, capability.cost_tier)
    if kind in {"script", "python-script", "go-binary"}:
        return ScriptRuntime(cost_tier=capability.cost_tier or "cheap")
    return UnavailableRuntime(requested=kind, cost_tier=capability.cost_tier or "cheap")


__all__ = [
    "Runtime",
    "ScriptRuntime",
    "UnavailableRuntime",
    "build_runtime",
]
