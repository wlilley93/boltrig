"""Optional Langfuse mirror for runtime observability.

The audit log remains the compliance source of truth. This sink only mirrors a
bounded metadata projection so tracing can fail, lag, or be absent without
affecting agent execution.
"""

from __future__ import annotations

import inspect
import os
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from boltrig.config.environment import is_truthy
from boltrig.models import AgentCapability, InvocationContext


_ROUTE_KEYS = {"provider", "model", "runtime", "profile", "tier"}


class ObservabilitySink(Protocol):
    async def record_spawn(
        self,
        *,
        tenant_id: str,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        run_id: str,
        status: str,
        tokens: int,
        cost_micros: int,
        model_route: Mapping[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Mirror one agent-spawn trace event."""


class NoopObservabilitySink:
    async def record_spawn(
        self,
        *,
        tenant_id: str,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        run_id: str,
        status: str,
        tokens: int,
        cost_micros: int,
        model_route: Mapping[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        return None


def _short(value: Any, *, limit: int = 160) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _route_metadata(model_route: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(model_route, Mapping):
        return {}
    return {
        key: _short(value)
        for key, value in model_route.items()
        if key in _ROUTE_KEYS and _short(value)
    }


def spawn_trace_payload(
    *,
    tenant_id: str,
    parent: InvocationContext,
    capability: AgentCapability,
    skills: list[str],
    run_id: str,
    status: str,
    tokens: int,
    cost_micros: int,
    model_route: Mapping[str, Any] | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    """Return the metadata-only Langfuse event payload for one child agent."""
    metadata: dict[str, Any] = {
        "tenant_id": _short(tenant_id),
        "run_id": _short(run_id),
        "parent_run_id": _short(parent.run_id),
        "workspace_id": _short(parent.workspace_id),
        "capability": _short(capability.name),
        "runtime": _short(capability.runtime),
        "status": _short(status, limit=60),
        "actor_tier": "ephemeral",
        "depth": int(parent.depth or 0) + 1,
        "skills": [_short(skill, limit=120) for skill in skills[:20]],
    }
    route = _route_metadata(model_route)
    if route:
        metadata["model_route"] = route
    if latency_ms is not None:
        metadata["latency_ms"] = int(latency_ms)

    return {
        "name": "boltrig.agent.spawn",
        "id": f"spawn-{_short(run_id, limit=80)}",
        "trace_id": _short(parent.run_id or run_id, limit=80),
        "metadata": metadata,
        "usage_details": {
            "total_tokens": int(tokens or 0),
            "cost_micros": int(cost_micros or 0),
        },
    }


async def _maybe_await(value: Any) -> None:
    if inspect.isawaitable(value):
        await value


@dataclass
class LangfuseObservabilitySink:
    client: Any
    timeout_s: float = 0.25

    async def record_spawn(
        self,
        *,
        tenant_id: str,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        run_id: str,
        status: str,
        tokens: int,
        cost_micros: int,
        model_route: Mapping[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        payload = spawn_trace_payload(
            tenant_id=tenant_id,
            parent=parent,
            capability=capability,
            skills=skills,
            run_id=run_id,
            status=status,
            tokens=tokens,
            cost_micros=cost_micros,
            model_route=model_route,
            latency_ms=latency_ms,
        )
        try:
            await asyncio.wait_for(self._emit(payload), timeout=self.timeout_s)
        except Exception:
            return None

    async def _emit(self, payload: dict[str, Any]) -> None:
        client = self.client
        if hasattr(client, "event"):
            await _maybe_await(client.event(**payload))
            await self._flush()
            return
        if hasattr(client, "create_event"):
            await _maybe_await(client.create_event(**payload))
            await self._flush()
            return
        if hasattr(client, "trace"):
            trace = client.trace(
                id=payload["trace_id"],
                name=payload["name"],
                metadata=payload["metadata"],
            )
            if hasattr(trace, "event"):
                await _maybe_await(
                    trace.event(
                        name=payload["name"],
                        id=payload["id"],
                        metadata=payload["metadata"],
                        usage_details=payload["usage_details"],
                    )
                )
            await self._flush()
            return

    async def _flush(self) -> None:
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            await _maybe_await(flush())


def build_observability_sink(
    env: Mapping[str, str] | None = None,
    *,
    client: Any | None = None,
) -> ObservabilitySink:
    """Build a fail-closed sink from env without requiring Langfuse at import time."""
    if client is not None:
        return LangfuseObservabilitySink(client)
    env = os.environ if env is None else env
    enabled = _short(env.get("BOLTRIG_LANGFUSE_ENABLED") or env.get("LANGFUSE_ENABLED"))
    if not is_truthy(enabled):
        return NoopObservabilitySink()
    public_key = _short(env.get("LANGFUSE_PUBLIC_KEY"))
    secret_key = _short(env.get("LANGFUSE_SECRET_KEY"))
    if not public_key or not secret_key:
        return NoopObservabilitySink()
    try:
        from langfuse import Langfuse  # type: ignore
    except Exception:
        return NoopObservabilitySink()

    kwargs: dict[str, str] = {"public_key": public_key, "secret_key": secret_key}
    host = _short(env.get("LANGFUSE_HOST"))
    if host:
        kwargs["host"] = host
    try:
        return LangfuseObservabilitySink(Langfuse(**kwargs))
    except Exception:
        return NoopObservabilitySink()
