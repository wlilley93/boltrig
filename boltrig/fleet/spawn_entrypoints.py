"""HTTP and kernel-bound entrypoints over the fleet spawner."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.config.spawn_rules import SpawnRule
from boltrig.models import AgentCapability, DepthExceeded, InvocationContext

from .result import AgentResult
from .spawn_budget import budget_scope_ids, estimate
from .spawn_skills import bound_capability_status

if TYPE_CHECKING:
    from boltrig.kernel import Kernel
    from boltrig.kernel.app import Principal, SpawnBody
    from boltrig.kernel.cost import BudgetReservation
    from boltrig.kernel.dispatch import AgentInvoker


def make_app_spawner(
    kernel: Kernel,
    *,
    codex_config: dict[str, Any] | None = None,
    model_catalogue: Any = None,
    sensitive_endpoint_id: str | None = None,
    spawn_rules: Sequence[SpawnRule] = (),
) -> Callable[[Principal, SpawnBody], Awaitable[dict[str, Any]]]:
    """Adapt a composition-owned spawner to ``POST /v1/spawn``."""
    from .spawn import build_spawner

    spawner = (
        build_spawner(
            kernel,
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=sensitive_endpoint_id,
            spawn_rules=spawn_rules,
        )
        if spawn_rules
        else build_spawner(
            kernel,
            codex_config=codex_config,
            model_catalogue=model_catalogue,
            sensitive_endpoint_id=sensitive_endpoint_id,
        )
    )
    envelope = {"run_id", "parent_run_id", "depth", "skills_loaded"}

    async def app_spawner(principal: Principal, body: SpawnBody) -> dict[str, Any]:
        from fastapi import HTTPException

        from boltrig.kernel.run_access import foreign_run_asserted

        if await foreign_run_asserted(kernel.store, principal, body.context):
            raise HTTPException(status_code=403, detail="not your run")
        extra = {
            key: value for key, value in body.context.items() if key not in envelope
        }
        ctx = principal.context(
            run_id=body.context.get("run_id"),
            parent_run_id=body.context.get("parent_run_id"),
            depth=int(body.context.get("depth", 0)),
            skills=body.context.get("skills_loaded", ()),
            extra=extra,
        )
        return await spawner.spawn(
            tenant_id=principal.tenant_id,
            task=body.task,
            skills=body.skills,
            prefer=body.prefer,
            context=ctx,
            partial_on_budget=False,
            grant_ceiling=principal.grants,
        )

    return app_spawner


async def _reserve_bound_agent(
    kernel: Kernel,
    cap: AgentCapability,
    context: InvocationContext,
    prompt: str,
) -> tuple[BudgetReservation, int, int]:
    child_depth = context.depth + 1
    if child_depth > cap.max_depth:
        raise DepthExceeded(
            f"depth {child_depth} exceeds max_depth {cap.max_depth} "
            f"for capability '{cap.name}'"
        )
    tokens_est, micros_est = estimate(prompt, "", [], cap.cost_tier)
    reservation = await kernel.cost.reserve(
        context.tenant_id,
        scope_ids=budget_scope_ids(context.tenant_id, None),
        tokens=tokens_est,
        micros=micros_est,
        run_id=context.run_id,
    )
    return reservation, tokens_est, micros_est


async def _run_bound_agent(
    spawner: Any,
    kernel: Kernel,
    cap: AgentCapability,
    context: InvocationContext,
    prompt: str,
    reservation: BudgetReservation,
    tokens_est: int,
    micros_est: int,
) -> AgentResult:
    try:
        # The prompt is the egress payload; the routing seam scans it for PII
        # classification before the destination is decided (SEC-13).
        runtime = await spawner._runtime_for(
            context.tenant_id, cap, context, outbound_text=prompt
        )
        result = await runtime.run(prompt, context, tools=list(context.grants.allow))
    except Exception:
        with contextlib.suppress(Exception):
            await kernel.cost.reconcile(
                reservation,
                delta_tokens=-tokens_est,
                delta_micros=-micros_est,
            )
        raise
    await spawner._true_up_cost(
        context.tenant_id,
        reservation,
        cap,
        tokens_est,
        micros_est,
        result,
    )
    return result


def _project_agent_result(result: AgentResult) -> Result:
    if result.ok:
        output = dict(result.output)
        if result.degraded:
            output.setdefault("_degraded", {"reason": "degraded"})
        return Result.success(output)
    return Result.failure(
        AdapterError(ErrorClass.INTERNAL, result.summary or "agent run failed")
    )


def make_agent_invoker(
    kernel: Kernel,
    *,
    codex_config: dict[str, Any] | None = None,
    model_catalogue: Any = None,
    sensitive_endpoint_id: str | None = None,
) -> AgentInvoker:
    """Build the reasoning-verb invoker with process-owned runtime policy."""
    from .runtime import ScriptRuntime
    from .spawn import build_spawner

    spawner = build_spawner(
        kernel,
        codex_config=codex_config,
        model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
    )

    async def agent_invoker(
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        agent_capability: str,
    ) -> Result:
        prompt = f"Verb: {verb}\nParams: {json.dumps(params, default=str, sort_keys=True)}"
        cap, retired = await bound_capability_status(
            kernel.store,
            context.tenant_id,
            agent_capability,
            workspace_id=context.workspace_id,
        )
        if retired:
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    f"agent capability '{agent_capability}' is retired",
                )
            )
        reservation: BudgetReservation | None = None
        tokens_est = micros_est = 0
        if cap is not None:
            reservation, tokens_est, micros_est = await _reserve_bound_agent(
                kernel, cap, context, prompt
            )
        try:
            if cap is None:
                result = await ScriptRuntime().run(
                    prompt, context, tools=list(context.grants.allow)
                )
            else:
                assert reservation is not None
                result = await _run_bound_agent(
                    spawner,
                    kernel,
                    cap,
                    context,
                    prompt,
                    reservation,
                    tokens_est,
                    micros_est,
                )
        except Exception as exc:
            result = AgentResult.degrade(
                runtime=cap.runtime if cap is not None else "script",
                reason=type(exc).__name__,
                prompt=prompt,
            )
        return _project_agent_result(result)

    return agent_invoker
