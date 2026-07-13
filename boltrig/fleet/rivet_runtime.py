"""Rivet AgentOS runtime behind the Boltrig Runtime seam.

Rivet is the v2 sandbox boundary for non-coding/tool agents. The runtime is a
thin HTTP bridge: Boltrig issues a scoped MCP token, sends no tool credentials,
and receives the same AgentResult shape as every other runtime.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.models import InvocationContext

from .result import AgentResult

TokenIssuer = Callable[..., str]
Transport = Callable[[str, dict[str, Any], dict[str, str]], Awaitable[tuple[int, Any]]]

_DEFAULT_RUN_PATH = "/runs"


class RivetAgentOSRuntime:
    runtime = "rivet_agentos"

    def __init__(
        self,
        *,
        agentos_url: str | None,
        mcp_url: str | None = None,
        issue_token: TokenIssuer | None = None,
        revoke_token: Callable[[str], None] | None = None,
        endpoint: Any = None,
        cost_tier: str = "standard",
        agentos_token: str | None = None,
        run_path: str = _DEFAULT_RUN_PATH,
        transport: Transport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.agentos_url = agentos_url.rstrip("/") if agentos_url else None
        self.mcp_url = mcp_url
        self._issue = issue_token
        self._revoke = revoke_token
        self.endpoint = endpoint
        self.cost_tier = cost_tier
        self.agentos_token = agentos_token or os.environ.get("RIVET_AGENTOS_TOKEN")
        self.run_path = run_path if run_path.startswith("/") else f"/{run_path}"
        self._transport = transport
        self._timeout = timeout

    def build_request(self, prompt: str, context: InvocationContext, token: str, tools: list[str]):
        from boltrig.fleet.prompt_stack import compose_system_prompt

        return {
            "task": prompt,
            "system": compose_system_prompt(getattr(context, "actor_tier", "ephemeral")),
            "mcp": {"url": self.mcp_url, "token": token},
            "model": {
                "provider": getattr(self.endpoint, "kind", None),
                "endpoint": getattr(self.endpoint, "base_url", None),
                "name": getattr(self.endpoint, "model", None),
            },
            "tools": list(tools),
            "context": {
                "tenant_id": context.tenant_id,
                "run_id": context.run_id,
                "parent_run_id": context.parent_run_id,
                "actor": context.actor,
                "workspace_id": context.workspace_id,
                "skills": list(context.skills_loaded),
            },
        }

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        if not self.agentos_url or self._issue is None:
            return AgentResult.degrade(
                runtime=self.runtime, reason="no_agentos", prompt=prompt
            )
        token = self._issue(
            context.tenant_id,
            context.grants,
            run_id=context.run_id,
            actor=context.actor,
            skills=context.skills_loaded,
            workspace_id=context.workspace_id,
            on_behalf_of=context.on_behalf_of,
            extra=dict(context.extra),
        )
        try:
            payload = self.build_request(prompt, context, token, tools)
            headers = {"Content-Type": "application/json"}
            if self.agentos_token:
                headers["Authorization"] = f"Bearer {self.agentos_token}"
            status, data = await self._post(self.agentos_url + self.run_path, payload, headers)
            if status >= 400:
                return AgentResult.degrade(
                    runtime=self.runtime, reason=f"http_{status}", prompt=prompt
                )
            return _result(data, token)
        except Exception as exc:
            return AgentResult.degrade(
                runtime=self.runtime, reason=type(exc).__name__, prompt=prompt
            )
        finally:
            if self._revoke is not None:
                try:
                    self._revoke(token)
                except Exception:
                    pass

    async def _post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, Any]:
        if self._transport is not None:
            return await self._transport(url, payload, headers)
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            try:
                data = response.json()
            except ValueError:
                data = {}
            return response.status_code, data


def _result(data: Any, token: str) -> AgentResult:
    payload = data if isinstance(data, dict) else {}
    output = _redact(payload.get("output") or payload, token)
    summary = str(_redact(payload.get("summary") or "", token))
    tokens = int(payload.get("tokens_used") or payload.get("tokens") or 0)
    cost = int(payload.get("cost_micros") or 0)
    return AgentResult.succeeded(
        output=output if isinstance(output, dict) else {"result": output},
        summary=summary,
        tokens_used=tokens,
        cost_micros=cost,
        new_work_items=list(payload.get("new_work_items") or []),
    )


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value
