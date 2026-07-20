"""Spawn logic behind ``POST /v1/spawn``."""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.kernel.cost import price_micros
from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    BudgetExceeded,
    ContextRequirementsUnmet,
    DepthExceeded,
    GrantSet,
    InvocationContext,
    utcnow,
)
from boltrig.observability.langfuse_sink import build_observability_sink

from .result import AgentResult
from .runtime_resolver import RuntimeResolver
from .spawn_skills import (
    NoCapableRuntime as NoCapableRuntime,
    SkillNotFound as SkillNotFound,
    context_payload,
    display_task as _display_task,
    missing_requirements,
    resolve_skills,
    select_capability,
)

if TYPE_CHECKING:
    from boltrig.kernel import Kernel
    from boltrig.kernel.app import Principal, SpawnBody
    from boltrig.kernel.dispatch import AgentInvoker

_PUBLIC_ROUTE_KEYS = {"profile", "provider", "model", "runtime", "tier"}


def _estimate(task: str, prompt: str, skills: list[str], cost_tier: str) -> tuple[int, int]:
    """Deterministic pre-run token/cost estimate for budget reservation."""
    chars = len(task) + len(prompt) + sum(len(skill) for skill in skills)
    tokens = max(16, chars // 4)
    return tokens, price_micros(tokens, cost_tier)


def _public_model_route(route: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(route, dict):
        return {}
    return {
        key: str(value)[:160]
        for key, value in route.items()
        if key in _PUBLIC_ROUTE_KEYS and value
    }


class Spawner:
    """Composes and runs ephemeral agents on top of the kernel."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        self._runtime_resolver = RuntimeResolver(
            kernel,
            sensitive_endpoint_id=sensitive_endpoint_id,
            codex_config=codex_config,
        )
        self._observability = build_observability_sink()

    async def spawn(
        self,
        tenant_id: str,
        task: str,
        skills: list[str],
        prefer: dict[str, Any],
        context: InvocationContext,
        *,
        partial_on_budget: bool = True,
        grant_ceiling: GrantSet | None = None,
    ) -> dict[str, Any]:
        """Spawn one ephemeral agent for ``task`` with ``skills``."""
        kernel = self._kernel
        prefer = prefer or {}
        skills = list(skills or [])

        merged = await resolve_skills(kernel.store, tenant_id, skills)
        instance = {k: v for k, v in context_payload(context).items() if v is not None}
        missing, errors = missing_requirements(merged.context_requirements, instance)
        if missing or errors:
            detail = "; ".join(errors) if errors else "missing required context"
            raise ContextRequirementsUnmet(
                f"spawn context unmet: {detail}", missing=missing or errors
            )

        capability = await self._select_capability(tenant_id, skills, prefer)
        child_depth = context.depth + 1
        if child_depth > capability.max_depth:
            raise DepthExceeded(
                f"depth {child_depth} exceeds max_depth {capability.max_depth} "
                f"for capability '{capability.name}'"
            )

        merged_prompt = "\n\n".join(merged.prompt_fragments)
        run_id = uuid.uuid4().hex
        tokens_est, micros_est = _estimate(task, merged_prompt, skills, capability.cost_tier)
        scope_ids = ["tenant", *([str(prefer["department"])] if prefer.get("department") else [])]
        try:
            await kernel.cost.reserve(
                tenant_id, scope_ids=scope_ids, tokens=tokens_est, micros=micros_est
            )
        except BudgetExceeded:
            await self._audit_spawn(
                tenant_id, context, capability, skills, run_id,
                status="budget_exceeded", tokens=0, cost=0,
            )
            if not partial_on_budget:
                raise
            return self._budget_partial(run_id, capability)

        child_grants = GrantSet.of(allow=list(merged.tool_grants)).intersect(context.grants)
        if grant_ceiling is not None:
            child_grants = child_grants.intersect(grant_ceiling)
        child_ctx = self._child_context(
            tenant_id, run_id, child_depth, context, capability, skills, child_grants
        )

        runtime = await self._runtime_for(tenant_id, capability, context)
        model_route = getattr(runtime, "model_route", None)
        if context.run_id:
            self._publish_subagent_event(context, task, skills, run_id, capability)
        started = time.monotonic()
        result = await runtime.run(
            self._compose_prompt(merged_prompt, task), child_ctx, tools=list(child_grants.allow)
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        if model_route and isinstance(result.output, dict):
            result.output.setdefault("model_route", _public_model_route(model_route))

        await self._true_up_cost(tenant_id, scope_ids, capability, tokens_est, micros_est, result)
        await self._audit_spawn(
            tenant_id,
            context,
            capability,
            skills,
            run_id,
            status=("degraded" if result.degraded else "ok" if result.ok else "error"),
            tokens=result.tokens_used,
            cost=result.cost_micros,
            model_route=model_route,
            latency_ms=latency_ms,
        )
        return {
            "run_id": run_id,
            "agent_type": capability.name,
            "status": "ok" if result.ok else "error",
            "degraded": result.degraded,
            "summary": result.summary,
            "output": result.output,
            "tokens_used": result.tokens_used,
            "cost_micros": result.cost_micros,
            "new_work_items": list(result.new_work_items),
            "effective_grants": list(child_grants.allow),
        }

    async def _select_capability(
        self, tenant_id: str, skills: list[str], prefer: dict[str, Any]
    ) -> AgentCapability:
        return await select_capability(self._kernel.store, tenant_id, skills, prefer)

    async def _runtime_for(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None = None,
    ):
        return await self._runtime_resolver.runtime_for(tenant_id, capability, context)

    def _child_context(
        self,
        tenant_id: str,
        run_id: str,
        child_depth: int,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        grants: GrantSet,
    ) -> InvocationContext:
        return InvocationContext(
            tenant_id=tenant_id,
            run_id=run_id,
            parent_run_id=parent.run_id,
            depth=child_depth,
            on_behalf_of=parent.on_behalf_of,
            workspace_id=parent.workspace_id,
            ip_address=parent.ip_address,
            user_agent=parent.user_agent,
            grants=grants,
            actor=capability.name,
            actor_tier="ephemeral",
            skills_loaded=tuple(skills),
            extra=dict(parent.extra),
        )

    def _publish_subagent_event(
        self,
        context: InvocationContext,
        task: str,
        skills: list[str],
        run_id: str,
        capability: AgentCapability,
    ) -> None:
        try:
            self._kernel.events.publish(
                context.tenant_id, context.run_id,
                {
                    "type": "subagent",
                    "task": _display_task(task),
                    "skills": list(skills),
                    "child_run_id": run_id,
                    "capability": capability.name,
                },
            )
        except Exception:
            pass

    async def _true_up_cost(
        self,
        tenant_id: str,
        scope_ids: list[str],
        capability: AgentCapability,
        tokens_est: int,
        micros_est: int,
        result: AgentResult,
    ) -> None:
        actual_tokens = int(result.tokens_used or 0)
        priced_model: str | None = None
        if capability.model_endpoint and self._kernel.cost.has_prices:
            ep = await self._kernel.store.get_model_endpoint(
                tenant_id, capability.model_endpoint
            )
            priced_model = ep.model if ep is not None else None
        actual_micros = self._kernel.cost.price(
            actual_tokens, capability.cost_tier, model=priced_model
        )
        await self._kernel.cost.reconcile(
            tenant_id,
            scope_ids=scope_ids,
            delta_tokens=actual_tokens - tokens_est,
            delta_micros=actual_micros - micros_est,
        )

    def _compose_prompt(self, merged_prompt: str, task: str) -> str:
        if merged_prompt:
            return f"{merged_prompt}\n\nTask:\n{task}"
        return f"Task:\n{task}"

    async def _audit_spawn(
        self,
        tenant_id: str,
        parent: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        run_id: str,
        *,
        status: str,
        tokens: int,
        cost: int,
        model_route: dict[str, str] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        detail = {"capability": capability.name, "runtime": capability.runtime}
        if model_route:
            detail["model_route"] = _public_model_route(model_route)
        event = AuditEvent(
            tenant_id=tenant_id,
            ts=utcnow(),
            run_id=run_id,
            parent_run_id=parent.run_id,
            actor=capability.name,
            actor_tier="ephemeral",
            depth=parent.depth + 1,
            action_type=ActionType.AGENT_SPAWN,
            status=status,
            latency_ms=latency_ms,
            tokens_used=tokens or None,
            cost_micros=cost or None,
            on_behalf_of=parent.on_behalf_of, workspace_id=parent.workspace_id,
            skills_loaded=list(skills),
            detail=detail,
        )
        await self._kernel.audit.write(event)
        try:
            await self._observability.record_spawn(
                tenant_id=tenant_id,
                parent=parent,
                capability=capability,
                skills=list(skills),
                run_id=run_id,
                status=status,
                tokens=tokens,
                cost_micros=cost,
                model_route=model_route,
                latency_ms=latency_ms,
            )
        except Exception:
            pass

    def _budget_partial(self, run_id: str, capability: AgentCapability) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "agent_type": capability.name,
            "status": "partial",
            "degraded": False,
            "reason": "budget_exceeded",
            "summary": "spawn skipped: budget hard-stop reached",
            "output": {},
            "tokens_used": 0,
            "cost_micros": 0,
            "new_work_items": [],
        }


def build_spawner(
    kernel: Kernel, *, codex_config: dict[str, Any] | None = None
) -> Spawner:
    """Construct the fleet ``Spawner`` for a kernel.

    ``codex_config`` is the trusted read-only Codex provider config assembled at the
    api composition root ([2026] VJS-CC-VJS 2); None (the default) keeps existing
    callers unaffected and the codex runtime degrading to ScriptRuntime.
    """
    return Spawner(kernel, codex_config=codex_config)


def make_app_spawner(
    kernel: Kernel, *, codex_config: dict[str, Any] | None = None
) -> Callable[[Principal, SpawnBody], Awaitable[dict[str, Any]]]:
    """Adapt ``Spawner.spawn`` to the ``POST /v1/spawn`` seam.

    ``codex_config`` (VJS-CC-VJS 2/8) lets a spawn that pins a ``runtime: codex``
    capability answer through the per-cell proxy instead of degrading to a script.
    """
    spawner = build_spawner(kernel, codex_config=codex_config)
    envelope = {"run_id", "parent_run_id", "depth", "skills_loaded"}

    async def app_spawner(principal: Principal, body: SpawnBody) -> dict[str, Any]:
        extra = {key: value for key, value in body.context.items() if key not in envelope}
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
            grant_ceiling=principal.grants,  # SEC-139: cap the child to the caller
        )

    return app_spawner


def make_agent_invoker(kernel: Kernel) -> AgentInvoker:
    """Build the reasoning-verb invoker the kernel attaches."""
    spawner = build_spawner(kernel)

    async def agent_invoker(
        verb: str,
        params: dict[str, Any],
        context: InvocationContext,
        agent_capability: str,
    ) -> Result:
        from .runtime import ScriptRuntime

        prompt = (
            f"Verb: {verb}\n"
            f"Params: {json.dumps(params, default=str, sort_keys=True)}"
        )
        caps = await kernel.store.list_capabilities(context.tenant_id)
        cap = next((item for item in caps if item.name == agent_capability), None)
        try:
            runtime = (
                await spawner._runtime_for(context.tenant_id, cap, context)
                if cap is not None
                else ScriptRuntime()
            )
            result = await runtime.run(prompt, context, tools=list(context.grants.allow))
        except Exception as exc:
            # A raised runtime must never be papered over with an ok=True echo
            # (US-FLT-07): return a degrade-marked result with an audit reason.
            result = AgentResult.degrade(
                runtime=cap.runtime if cap is not None else "script",
                reason=type(exc).__name__,
                prompt=prompt,
            )
        if result.ok:
            output = dict(result.output)
            if result.degraded:
                output.setdefault("_degraded", {"reason": "degraded"})
            return Result.success(output)
        return Result.failure(
            AdapterError(ErrorClass.INTERNAL, result.summary or "agent run failed")
        )

    return agent_invoker
