"""Spawn logic behind ``POST /v1/spawn``."""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.kernel.cost import price_micros
from boltrig.kernel.held_call import sweep_run_credentials_if_settled
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

from .chat_authority import inherit_on_behalf_bearer
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

log = logging.getLogger(__name__)

_PUBLIC_ROUTE_KEYS = {"profile", "provider", "model", "runtime", "tier"}


def _budget_scope_ids(tenant_id: str, department: Any | None) -> list[str]:
    """The budget scopes one spawn is metered against.

    The TENANT budget's scope id IS the tenant id. That is the convention
    everywhere else, and ``control.budget.upsert`` REFUSES to create a tenant-scope
    row under any other id ("tenant budget must target the active organisation",
    config/control_budget.py). Reserving against the literal string ``"tenant"``
    matched no row, so ``get_budget`` returned None and reserve/reconcile treated
    the scope as UNMETERED: the tenant's hard-stop cap could never fire and its
    spend ledger stayed at zero however much it spent. The DEPARTMENT leg was
    always correct - the manifest seeds it under the department name.
    """
    return [tenant_id, *([str(department)] if department else [])]


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
        scope_ids = _budget_scope_ids(tenant_id, prefer.get("department"))
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

        result, model_route, latency_ms = await self._invoke_runtime(
            tenant_id, capability, context,
            task=task, skills=skills, run_id=run_id, merged_prompt=merged_prompt,
            child_ctx=child_ctx, child_grants=child_grants, scope_ids=scope_ids,
            tokens_est=tokens_est, micros_est=micros_est,
        )
        if model_route and isinstance(result.output, dict):
            result.output.setdefault("model_route", _public_model_route(model_route))

        # The PRICED cost (see _true_up_cost), never result.cost_micros.
        cost_micros = await self._true_up_cost(
            tenant_id, scope_ids, capability, tokens_est, micros_est, result)
        await self._audit_spawn(
            tenant_id,
            context,
            capability,
            skills,
            run_id,
            status=("degraded" if result.degraded else "ok" if result.ok else "error"),
            tokens=result.tokens_used,
            cost=cost_micros,
            model_route=model_route, latency_ms=latency_ms, reason=result.degrade_reason,
        )
        return {
            "run_id": run_id,
            "agent_type": capability.name,
            "status": "ok" if result.ok else "error",
            "degraded": result.degraded,
            "summary": result.summary,
            "output": result.output,
            "tokens_used": result.tokens_used,
            "cost_micros": cost_micros,
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

    async def _invoke_runtime(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext,
        *,
        task: str,
        skills: list[str],
        run_id: str,
        merged_prompt: str,
        child_ctx: InvocationContext,
        child_grants: GrantSet,
        scope_ids: list[str],
        tokens_est: int,
        micros_est: int,
    ) -> tuple[AgentResult, dict[str, Any] | None, int]:
        """Resolve the runtime and run the turn, refunding the reservation on a raise.

        A run that never happened must not keep its reservation: the full estimate
        is refunded (delta = -estimate) so a raised runtime cannot leak budget
        against the tenant's hard stop (FR-COST-03).

        Delegation-tree completeness (G3, SDK-CONTRACT §5): whenever a ``subagent``
        open frame is published (``context.run_id`` set), a paired ``subagent_end``
        settle frame is published for the SAME ``child_run_id`` on the SAME parent
        relay - on the success return AND on a runtime raise - so a consumer never
        renders the child RUNNING forever."""
        opened = False
        # The delegation boundary is also where the permission-parity seal has to
        # cross: see _inherit_adapter_bearer for why the child cannot use the seal
        # the chat turn wrote against the ROOT run id.
        await self._inherit_adapter_bearer(
            tenant_id, context.run_id, run_id, context.on_behalf_of
        )
        try:
            runtime = await self._runtime_for(tenant_id, capability, context)
            model_route = getattr(runtime, "model_route", None)
            if context.run_id:
                self._publish_subagent_event(context, task, skills, run_id, capability)
                opened = True
            started = time.monotonic()
            result = await runtime.run(
                self._compose_prompt(merged_prompt, task), child_ctx, tools=list(child_grants.allow)
            )
        except Exception:
            if opened:
                # The child opened but the runtime raised: settle its node as
                # errored (G3) BEFORE the reservation refund + re-raise, so the
                # tree flips out of RUNNING even on a failed spawn.
                self._publish_subagent_end_event(context, run_id, "error")
            with contextlib.suppress(Exception):
                await self._kernel.cost.reconcile(
                    tenant_id, scope_ids=scope_ids,
                    delta_tokens=-tokens_est, delta_micros=-micros_est,
                )
            await self._retire_child_credentials(tenant_id, run_id)
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        if opened:
            # Symmetric completion (G3): status mirrors the spawn audit/return
            # derivation (spawn.py `status=`), so the node settles ok/degraded/error.
            status = "degraded" if result.degraded else "ok" if result.ok else "error"
            self._publish_subagent_end_event(context, run_id, status)
        await self._retire_child_credentials(tenant_id, run_id)
        return result, model_route, latency_ms

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
        # A read-only Codex leaf is scoped by a run + workspace. Under [2026]
        # VJS-CC-VJS 8 the kernel orchestrates the leaf, so it supplies the leaf's
        # read-only scope: when a scopeless caller (e.g. /v1/spawn with no active
        # workspace) orchestrates a codex leaf, scope it to its OWN run. The phase is
        # read-only, writes nothing, and its per-cell tree is already run/slot
        # isolated, so the run is a sufficient and self-contained scope. Other
        # runtimes keep inheriting the parent's workspace unchanged (None stays None).
        workspace_id = parent.workspace_id
        if workspace_id is None and capability.runtime == "codex":
            workspace_id = run_id
        return InvocationContext(
            tenant_id=tenant_id,
            run_id=run_id,
            parent_run_id=parent.run_id,
            depth=child_depth,
            on_behalf_of=parent.on_behalf_of,
            workspace_id=workspace_id,
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

    async def _retire_child_credentials(self, tenant_id: str, run_id: str) -> None:
        """Retire the bearer this child inherited, at the child's run terminal.

        Called from the SAME two exits as ``_publish_subagent_end_event`` (the
        runtime raise and the success return) and for the same reason: those are
        the two ways a child run ends, so a terminal wired to only one of them
        leaks on the other.

        Necessary because a delegated child has NO work item, so the pump's
        terminal hook (``sweep_run_credentials_if_settled``, pump.py) - can never fire
        for it. ``_inherit_adapter_bearer`` re-seals the caller's bearer under the
        CHILD run id, so without this every delegated turn left a second live
        bearer at rest forever (observed live: one root row plus one child row per
        turn, none ever deleted).

        Guarded by ``sweep_run_credentials_if_settled``: when the gate held a
        write, the resume replays under the CHILD's context and therefore needs
        this exact bearer, so the seal must outlive the child. Best-effort (P9),
        exactly like the inherit that created it: hygiene never fails a spawn.
        """
        try:
            await sweep_run_credentials_if_settled(
                self._kernel.store, tenant_id, run_id
            )
        except Exception:  # noqa: BLE001 - a sweep fault is the pre-existing leak
            log.warning(
                "could not retire the run-scoped credentials of child run '%s'",
                run_id, exc_info=True,
            )

    def _publish_subagent_end_event(
        self,
        context: InvocationContext,
        run_id: str,
        status: str,
    ) -> None:
        """Settle a delegated child on the parent relay (G3, SDK-CONTRACT §5).

        The paired terminal of ``_publish_subagent_event``: published on the SAME
        stream (parent ``context.run_id``) and carrying the SAME ``child_run_id``
        as the open frame, so a consumer flips exactly that tree node from RUNNING
        to its terminal state. ``status`` is one of ok|degraded|error (mirroring
        the spawn audit/return status). Best-effort, exactly like the open: a relay
        failure never breaks the turn."""
        try:
            self._kernel.events.publish(
                context.tenant_id, context.run_id,
                {
                    "type": "subagent_end",
                    "child_run_id": run_id,
                    "status": status,
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
    ) -> int:
        """Reconcile the budget reservation against real usage and RETURN what the
        run actually cost.

        The priced figure has to come back: a runtime reports TOKENS, not money
        (pricing is the tenant's per-model/tier rate, which only the accountant
        knows), so `result.cost_micros` stays 0 for every runtime that does not
        price itself. This method already computed the real number and then dropped
        it, so the budget was trued up correctly while the audit tree and the spawn
        return recorded a cost of zero - a tenant could spend and still read as free.
        """
        actual_tokens = int(result.tokens_used or 0)
        priced_model: str | None = None
        if capability.model_endpoint and self._kernel.cost.has_prices:
            ep = await self._kernel.store.get_model_endpoint(
                tenant_id, capability.model_endpoint
            )
            priced_model = ep.model if ep is not None else None
        # Priced LEG BY LEG when the runtime reported the split. Input and output
        # differ by more than 2x on the rate cards the fleet bills from, and an
        # agent turn is heavily input-weighted, so pricing a whole run at the
        # output rate over-bills it substantially. A runtime that reports no split
        # (0/0) is priced on the total exactly as before - never at zero.
        actual_micros = self._kernel.cost.price(
            actual_tokens,
            capability.cost_tier,
            model=priced_model,
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
        )
        await self._kernel.cost.reconcile(
            tenant_id,
            scope_ids=scope_ids,
            delta_tokens=actual_tokens - tokens_est,
            delta_micros=actual_micros - micros_est,
        )
        return actual_micros

    def _compose_prompt(self, merged_prompt: str, task: str) -> str:
        if merged_prompt:
            return f"{merged_prompt}\n\nTask:\n{task}"
        return f"Task:\n{task}"

    async def _inherit_adapter_bearer(
        self,
        tenant_id: str,
        parent_run_id: str | None,
        child_run_id: str,
        owner: str | None,
    ) -> None:
        """Carry a run-scoped adapter bearer from the spawning run to its child.

        The permission-parity passthrough has to survive DELEGATION. The chat turn
        seals the caller's clamped external bearer against the ROOT run id, but a
        chat turn never calls a verb itself: it spawns an ephemeral worker, and the
        dispatch happens under the CHILD's run id, which is what
        ``resolve_run_scoped_credential`` is keyed by. Without this the child misses
        the seal, silently falls back to the adapter's static credential, and every
        parity-dependent verb call is rejected downstream (observed end to end on the
        opbox door as ``adapter_unauthorised``, with the agent honestly reporting it
        had no authorised tools).

        Re-sealing for the child is a PROPAGATION, not a widening: the same bearer,
        already clamped to min(agent,user), for the same adapter, for a run that is
        part of the same turn on behalf of the same person. Each run holds its own
        ref, so ``sweep_run_credentials_if_settled`` still clears it on that run's terminal and the
        fail-closed scoping is unchanged - a foreign run still resolves to None.

        Best-effort by construction: when no
        bearer is sealed (every dev / non-passthrough tenant) this is a no-op and
        dispatch keeps using the adapter's static credential exactly as before, so
        the change is execution-neutral for anyone not using the parity seam. A
        failure here must never take down a spawn that would otherwise succeed - the
        worst case is the pre-existing behaviour, a fallback to the static credential.
        """
        await inherit_on_behalf_bearer(
            self._kernel.credentials,
            tenant_id,
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            owner=owner,
        )

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
        reason: str | None = None,
    ) -> None:
        detail = {"capability": capability.name, "runtime": capability.runtime}
        if model_route:
            detail["model_route"] = _public_model_route(model_route)
        if reason:  # a degraded row recorded WHAT failed but never why
            detail["reason"] = reason
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
            # The run never happened: honest degradation (US-FLT-07), so the chat
            # executor flags the turn instead of presenting a skip as success.
            "degraded": True,
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
    callers unaffected and the codex runtime degrade-marked unavailable.
    """
    return Spawner(kernel, codex_config=codex_config)


def make_app_spawner(
    kernel: Kernel, *, codex_config: dict[str, Any] | None = None
) -> Callable[[Principal, SpawnBody], Awaitable[dict[str, Any]]]:
    """Adapt ``Spawner.spawn`` to the ``POST /v1/spawn`` seam.

    ``codex_config`` (VJS-CC-VJS 2/8) lets a spawn that pins a ``runtime: codex``
    capability answer through the per-cell proxy instead of a degrade-marked
    unavailable result.
    """
    spawner = build_spawner(kernel, codex_config=codex_config)
    envelope = {"run_id", "parent_run_id", "depth", "skills_loaded"}

    async def app_spawner(principal: Principal, body: SpawnBody) -> dict[str, Any]:
        # SEC-186, and it matters more here than at /v1/invoke: an unchecked
        # parent_run_id would launder a stranger's sealed bearer into a run the
        # caller owns outright (see _inherit_adapter_bearer). Same status and
        # wording as the sibling fence in kernel/hitl_http.py.
        from fastapi import HTTPException

        from boltrig.kernel.run_access import foreign_run_asserted

        if await foreign_run_asserted(kernel.store, principal, body.context):
            raise HTTPException(status_code=403, detail="not your run")
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
        if cap is not None:
            # The same governance Spawner.spawn applies, or an agent-bound verb is
            # an unmetered side door around it: the depth cap first, then a budget
            # reservation that is refunded if the run raises and trued up after.
            child_depth = context.depth + 1
            if child_depth > cap.max_depth:
                raise DepthExceeded(
                    f"depth {child_depth} exceeds max_depth {cap.max_depth} "
                    f"for capability '{cap.name}'"
                )
            scope_ids = _budget_scope_ids(context.tenant_id, None)
            tokens_est, micros_est = _estimate(prompt, "", [], cap.cost_tier)
            await kernel.cost.reserve(
                context.tenant_id, scope_ids=scope_ids, tokens=tokens_est, micros=micros_est
            )
        try:
            if cap is not None:
                try:
                    runtime = await spawner._runtime_for(context.tenant_id, cap, context)
                    result = await runtime.run(prompt, context, tools=list(context.grants.allow))
                except Exception:
                    with contextlib.suppress(Exception):
                        await kernel.cost.reconcile(
                            context.tenant_id, scope_ids=scope_ids,
                            delta_tokens=-tokens_est, delta_micros=-micros_est,
                        )
                    raise
                await spawner._true_up_cost(
                    context.tenant_id, scope_ids, cap, tokens_est, micros_est, result
                )
            else:
                # No capability: the unmetered deterministic script fallback is deliberate.
                result = await ScriptRuntime().run(
                    prompt, context, tools=list(context.grants.allow)
                )
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
