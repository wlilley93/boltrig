"""PiRuntime - the Pi sidecar behind the Runtime seam (Round Two, Epic RUN).

A ``pi`` capability runs through a sandboxed Pi sidecar service. ``PiRuntime``
opens a run on the sidecar, handing it (a) the composed prompt, (b) an MCP
connection scoped to exactly this run's grants (a run-scoped token, never a tool
credential, SEC-27), and (c) the pinned model endpoint. The sidecar reasons and
calls tools; every tool call is a kernel verb over MCP, so it passes the full
chokepoint (FR-RUN-03). Events are relayed to the conversational stream; a final
result returns a uniform ``AgentResult`` (FR-RUN-04). If the sidecar is
unreachable, there is no model key, or the run errors, it returns a degraded
result (FR-RUN-05, P9).

Reached over the wire only: boltrig/kernel and boltrig/models import nothing from
Pi or the sidecar (SEC-28).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from boltrig.models import InvocationContext

from .result import AgentResult

# issue_token(tenant_id, grants, *, run_id, actor, skills) -> token
TokenIssuer = Callable[..., str]
EventSink = Callable[[dict[str, Any]], None]

_MODEL_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _model_key_for(endpoint: Any, override: str | None) -> str | None:
    if override:
        return override
    kind = getattr(endpoint, "kind", None)
    return os.environ.get(_MODEL_KEY_ENV.get(kind, ""), "") or None if kind else None


class PiRuntime:
    runtime = "pi"

    def __init__(
        self,
        *,
        sidecar_url: str | None,
        mcp_url: str | None = None,
        issue_token: TokenIssuer | None = None,
        revoke_token: Callable[[str], None] | None = None,
        endpoint: Any = None,
        model_api_key: str | None = None,
        event_sink: EventSink | None = None,
        max_steps: int = 12,
        cost_tier: str = "standard",
        timeout: float = 120.0,
    ) -> None:
        self.sidecar_url = sidecar_url
        self.mcp_url = mcp_url
        self._issue = issue_token
        self._revoke = revoke_token
        self.endpoint = endpoint
        self._model_key_override = model_api_key
        self._sink = event_sink
        self.max_steps = max_steps
        self.cost_tier = cost_tier
        self._timeout = timeout

    def build_request(self, prompt: str, context: InvocationContext, token: str) -> dict:
        """The sidecar /run payload. Carries the model key + a run-scoped MCP
        token ONLY - never a tool/verb credential (SEC-27)."""
        from boltrig.fleet.prompt_stack import compose_system_prompt

        return {
            "prompt": prompt,
            # the kernel-composed governance floor + tier character (decision:
            # Corporate Brain III/V); the sidecar prepends it to its loop system
            # prompt so the cage is authoritative on the agentic lane too.
            "system": compose_system_prompt(getattr(context, "actor_tier", "ephemeral")),
            "mcp": {"url": self.mcp_url, "token": token},
            "model": {
                "endpoint": getattr(self.endpoint, "base_url", None),
                "name": getattr(self.endpoint, "model", None),
                "api_key": _model_key_for(self.endpoint, self._model_key_override),
            },
            "limits": {"max_steps": self.max_steps},
        }

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        if not self.sidecar_url or self._issue is None:
            return AgentResult.degrade(runtime="pi", reason="no_sidecar", prompt=prompt)

        # least privilege: an MCP connection scoped to exactly this run's grants
        token = self._issue(
            context.tenant_id, context.grants, run_id=context.run_id,
            actor=context.actor, skills=context.skills_loaded,
        )
        body = self.build_request(prompt, context, token)
        final: dict | None = None
        try:
            import httpx

            # SEC-73 (M2): present the shared sidecar bearer so the sidecar's
            # fail-closed /run auth accepts this call in prod. Unset in dev, where
            # the sidecar runs open; separate from the run-scoped MCP token.
            sidecar_token = os.environ.get("PI_SIDECAR_TOKEN")
            headers = (
                {"Authorization": f"Bearer {sidecar_token}"} if sidecar_token else {}
            )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", self.sidecar_url.rstrip("/") + "/run", json=body, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if self._sink is not None:
                            try:
                                self._sink(event)
                            except Exception:
                                pass  # a relay failure must not fail the run
                        if event.get("type") == "final":
                            final = event
            if final is None:
                return AgentResult.degrade(runtime="pi", reason="no_final", prompt=prompt)
            return AgentResult.succeeded(
                output=final.get("output") or {},
                summary=final.get("summary", ""),
                tokens_used=int(final.get("tokens_used") or 0),
                cost_micros=int(final.get("cost_micros") or 0),
                new_work_items=final.get("new_work_items") or [],
            )
        except Exception as exc:  # sidecar down / no key / transport error -> degrade
            return AgentResult.degrade(runtime="pi", reason=type(exc).__name__, prompt=prompt)
        finally:
            if self._revoke is not None:
                try:
                    self._revoke(token)
                except Exception:
                    pass
