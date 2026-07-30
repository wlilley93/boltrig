"""Final accounting, artifacts, and response projection for a fleet spawn."""

from __future__ import annotations

from typing import Any

from boltrig.config.spawn_rules import SpawnRuleSelection
from boltrig.models import AgentCapability, GrantSet, InvocationContext

from .artifact_production import produce_spawn_artifacts, spawn_result_envelope
from .result import AgentResult

_PUBLIC_ROUTE_KEYS = {"profile", "provider", "model", "runtime", "tier"}


def public_model_route(route: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(route, dict):
        return {}
    return {
        key: str(value)[:160]
        for key, value in route.items()
        if key in _PUBLIC_ROUTE_KEYS and value
    }


async def complete_spawn(
    spawner: Any,
    *,
    tenant_id: str,
    capability: AgentCapability,
    context: InvocationContext,
    skills: list[str],
    run_id: str,
    child_grants: GrantSet,
    reservation: Any,
    tokens_est: int,
    micros_est: int,
    result: AgentResult,
    model_route: dict[str, Any] | None,
    latency_ms: int,
    spawn_rule: SpawnRuleSelection | None,
) -> dict[str, Any]:
    """Settle one successful runtime return through the standard spawn surfaces."""
    if model_route and isinstance(result.output, dict):
        result.output.setdefault("model_route", public_model_route(model_route))
    cost_micros = await spawner._true_up_cost(
        tenant_id,
        reservation,
        capability,
        tokens_est,
        micros_est,
        result,
    )
    artifacts = await produce_spawn_artifacts(
        spawner._kernel,
        result,
        capability_name=capability.name,
        context=context,
        run_id=run_id,
    )
    status = "degraded" if result.degraded or artifacts.rejected else (
        "ok" if result.ok else "error"
    )
    await spawner._audit_spawn(
        tenant_id,
        context,
        capability,
        skills,
        run_id,
        status=status,
        tokens=result.tokens_used,
        cost=cost_micros,
        model_route=model_route,
        latency_ms=latency_ms,
        reason=result.degrade_reason,
        spawn_rule=spawn_rule,
    )
    return spawn_result_envelope(
        run_id=run_id,
        capability_name=capability.name,
        result=result,
        cost_micros=cost_micros,
        effective_grants=child_grants.allow,
        artifacts=artifacts,
        spawn_rule=spawn_rule.receipt() if spawn_rule is not None else None,
    )
