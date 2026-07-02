"""The pluggable agent-runtime abstraction (P4, US-FLT-04).

A ``Runtime`` is the seam between the fleet's spawn logic and however an agent
is actually executed: a deterministic in-process script, a Hermes gateway, or
the Claude API. The spawner never imports an SDK directly - it asks
``build_runtime`` for the right implementation given an ``AgentCapability`` and
runs it. Every implementation returns the same ``AgentResult``.

Offline-safety is a hard rule (P9): importing this module never imports an LLM
SDK, and running any runtime with no SDK installed and no API key present falls
back to a clearly-marked degraded result rather than crashing.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from boltrig.models import InvocationContext

from .result import AgentResult

if TYPE_CHECKING:  # avoid importing the model record at runtime; keep it a seam
    from boltrig.models import AgentCapability, ModelEndpoint

# A lookup from a model-endpoint id to its record (or ``None``). The spawner
# resolves this from the store (async) and hands ``build_runtime`` a plain
# sync callable, so the factory itself stays synchronous.
EndpointLookup = Callable[[str], "ModelEndpoint | None"]

# Rough per-token cost by tier (millionths of a currency unit). Used only when a
# backend does not report real usage, so accounting is never left blank.
_MICROS_PER_TOKEN: dict[str, int] = {"cheap": 1, "standard": 5, "expensive": 25}


def _first_env(names: tuple[str, ...]) -> str | None:
    """The first non-empty environment value among ``names`` (empty is falsy)."""
    for env in names:
        value = os.environ.get(env)
        if value:
            return value
    return None


def _estimate_tokens(prompt: str, tools: list[str]) -> int:
    """A deterministic, offline token estimate (~4 chars/token)."""
    chars = len(prompt) + sum(len(t) for t in tools)
    return max(16, chars // 4)


def _system_for(context) -> str | None:
    """The kernel-composed system prompt for this run's tier (may be None)."""
    from boltrig.fleet.prompt_stack import compose_system_prompt

    return compose_system_prompt(getattr(context, "actor_tier", "ephemeral"))


def _messages(context, prompt: str) -> list[dict]:
    """OpenAI-style messages with the authoritative system prompt prepended; the
    caller's prompt is the user content and can never strip the system frame."""
    system = _system_for(context)
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


@runtime_checkable
class Runtime(Protocol):
    """How one agent run is executed. Implementations are stateless per call."""

    runtime: str
    cost_tier: str

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Execute the agent and return a structured ``AgentResult``."""
        ...


class ScriptRuntime:
    """Deterministic, offline, NO-LLM runtime (US-FLT-04).

    Used for integration-only tasks (the agent just needs to drive verbs, not
    reason) and as the universal test / offline fallback. It echoes the task and
    reports zero cost, so it is safe to run anywhere with no network or keys.
    """

    runtime = "python-script"

    def __init__(self, *, cost_tier: str = "cheap") -> None:
        self.cost_tier = cost_tier

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Return a deterministic result echoing the task; zero cost."""
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


class HermesRuntime:
    """A Hermes-gateway-backed runtime (lazy SDK / HTTP, degrade if absent).

    The model is pinned by the resolved ``ModelEndpoint`` (P4). If no endpoint
    is configured, or no API key is present, or the HTTP client cannot be
    imported, it returns a degraded result instead of crashing (P9).
    """

    runtime = "hermes"
    _KEY_ENVS = ("BOLTRIG_HERMES_API_KEY", "HERMES_API_KEY")

    def __init__(
        self, *, endpoint: ModelEndpoint | None = None, cost_tier: str = "standard"
    ) -> None:
        self.endpoint = endpoint
        self.cost_tier = cost_tier

    def _api_key(self) -> str | None:
        return _first_env(self._KEY_ENVS)

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Call the Hermes gateway; degrade cleanly when unconfigured/offline."""
        if self.endpoint is None or not self.endpoint.base_url:
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_endpoint", prompt=prompt
            )
        api_key = self._api_key()
        if api_key is None:
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_api_key", prompt=prompt
            )
        try:  # lazy import: never required at module import time
            import httpx  # noqa: F401  (presence check + client)

            payload = {
                "model": self.endpoint.model,
                "messages": _messages(context, prompt),
                "tools": list(tools),
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.endpoint.base_url.rstrip('/')}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
            return _result_from_chat(data, self.runtime, self.cost_tier, prompt, tools)
        except Exception as exc:  # network/SDK/parse failure -> degrade, never crash
            return AgentResult.degrade(
                runtime=self.runtime, reason=type(exc).__name__, prompt=prompt
            )


class OpenAiRuntime:
    """A native OpenAI-compatible runtime (lazy HTTP, degrade if absent).

    First-class runtime for the sensitive-local lane (US-RUN-01): it talks the
    OpenAI ``/chat/completions`` shape directly, so a local server (vLLM, Ollama)
    or a z.ai/GLM endpoint is a runtime, not only a routing guard. The model is
    pinned by the resolved ``ModelEndpoint`` (P4). With no endpoint or a
    transport failure it returns a degraded result instead of crashing (P9).

    Keyless-local: local servers usually need no auth, so an empty key is NOT a
    hard degrade - only an unset endpoint is. When a key is present it is sent as
    a bearer; when empty, the Authorization header is omitted and the call still
    proceeds. No tool/verb credential is ever placed in the body (SEC-27).
    """

    runtime = "openai"
    _KEY_ENVS = ("BOLTRIG_OPENAI_API_KEY", "OPENAI_API_KEY")

    def __init__(
        self, *, endpoint: ModelEndpoint | None = None, cost_tier: str = "standard"
    ) -> None:
        self.endpoint = endpoint
        self.cost_tier = cost_tier

    def _api_key(self) -> str | None:
        return _first_env(self._KEY_ENVS)

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Call an OpenAI-compatible endpoint; degrade cleanly when unconfigured."""
        if self.endpoint is None or not self.endpoint.base_url:
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_endpoint", prompt=prompt
            )
        api_key = self._api_key()  # empty is fine: keyless local is allowed
        try:  # lazy import: never required at module import time
            import httpx

            payload = {
                "model": self.endpoint.model,
                "messages": _messages(context, prompt),
                "tools": list(tools),  # names only - never a tool/verb credential (SEC-27)
            }
            headers = {}
            if api_key:  # only present a bearer when a real key exists (keyless local)
                headers["Authorization"] = f"Bearer {api_key}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.endpoint.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
            return _result_from_chat(data, self.runtime, self.cost_tier, prompt, tools)
        except Exception as exc:  # network/SDK/parse failure -> degrade, never crash
            return AgentResult.degrade(
                runtime=self.runtime, reason=type(exc).__name__, prompt=prompt
            )


class ClaudeApiRuntime:
    """A Claude-API-backed runtime (lazy ``anthropic`` import, degrade if absent).

    The model is pinned by the resolved ``ModelEndpoint`` (P4). With no SDK
    installed or no ``ANTHROPIC_API_KEY`` it returns a degraded result (P9).
    """

    runtime = "claude-api"
    _KEY_ENVS = ("ANTHROPIC_API_KEY", "BOLTRIG_ANTHROPIC_API_KEY")
    _DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(
        self, *, endpoint: ModelEndpoint | None = None, cost_tier: str = "expensive"
    ) -> None:
        self.endpoint = endpoint
        self.cost_tier = cost_tier

    def _api_key(self) -> str | None:
        return _first_env(self._KEY_ENVS)

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Call the Claude API; degrade cleanly when the SDK/key is absent."""
        api_key = self._api_key()
        if api_key is None:
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_api_key", prompt=prompt
            )
        try:
            from anthropic import AsyncAnthropic  # lazy: optional dependency
        except Exception as exc:
            return AgentResult.degrade(
                runtime=self.runtime, reason=f"sdk_absent:{type(exc).__name__}",
                prompt=prompt,
            )
        model = (self.endpoint.model if self.endpoint else None) or self._DEFAULT_MODEL
        base_url = self.endpoint.base_url if self.endpoint else None
        try:
            client = AsyncAnthropic(api_key=api_key, base_url=base_url)
            # Anthropic takes the system prompt as a top-level param, not a message.
            system = _system_for(context)
            create_kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                create_kwargs["system"] = system
            msg = await client.messages.create(**create_kwargs)
            text = "".join(
                getattr(block, "text", "") for block in getattr(msg, "content", [])
            )
            usage = getattr(msg, "usage", None)
            tokens = 0
            if usage is not None:
                tokens = int(getattr(usage, "input_tokens", 0)) + int(
                    getattr(usage, "output_tokens", 0)
                )
            cost = tokens * _MICROS_PER_TOKEN.get(self.cost_tier, 5)
            return AgentResult.succeeded(
                output={"runtime": self.runtime, "model": model, "text": text},
                summary=text[:256],
                tokens_used=tokens,
                cost_micros=cost,
            )
        except Exception as exc:  # API/network failure -> degrade, never crash
            return AgentResult.degrade(
                runtime=self.runtime, reason=type(exc).__name__, prompt=prompt
            )


def _result_from_chat(
    data: dict[str, Any], runtime: str, cost_tier: str, prompt: str, tools: list[str]
) -> AgentResult:
    """Map an OpenAI-shaped chat-completions response into an ``AgentResult``."""
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        text = ""
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    if tokens == 0:
        tokens = _estimate_tokens(prompt, tools)
    cost = tokens * _MICROS_PER_TOKEN.get(cost_tier, 5)
    return AgentResult.succeeded(
        output={"runtime": runtime, "text": text},
        summary=text[:256],
        tokens_used=tokens,
        cost_micros=cost,
    )


def build_runtime(
    capability: AgentCapability,
    endpoint_lookup: EndpointLookup | None = None,
    *,
    pi_config: dict[str, Any] | None = None,
) -> Runtime:
    """Select the runtime implementation for a capability (P4, US-FLT-04, US-RUN-01).

    Dispatch is by ``capability.runtime``. The model endpoint (if any) is
    resolved through ``endpoint_lookup`` so the chosen model is pinned by data,
    not code. ``pi_config`` supplies the Pi sidecar wiring (sidecar_url, mcp_url,
    issue_token, ...); absent it, a ``pi`` capability still resolves to a
    PiRuntime that degrades offline. Unknown runtimes fall back to ScriptRuntime.
    """
    endpoint: ModelEndpoint | None = None
    if capability.model_endpoint and endpoint_lookup is not None:
        endpoint = endpoint_lookup(capability.model_endpoint)

    kind = capability.runtime
    if kind == "hermes":
        return HermesRuntime(endpoint=endpoint, cost_tier=capability.cost_tier)
    if kind == "openai":
        return OpenAiRuntime(endpoint=endpoint, cost_tier=capability.cost_tier)
    if kind == "claude-api":
        return ClaudeApiRuntime(endpoint=endpoint, cost_tier=capability.cost_tier)
    if kind == "pi":
        from .pi_runtime import PiRuntime

        cfg = dict(pi_config or {})
        cfg.setdefault("sidecar_url", None)  # no config -> degrades offline (FR-RUN-05)
        return PiRuntime(
            endpoint=endpoint, cost_tier=capability.cost_tier or "standard", **cfg
        )
    # 'script' / 'python-script' / 'go-binary' / anything unknown -> deterministic.
    return ScriptRuntime(cost_tier=capability.cost_tier or "cheap")
