"""Spawn logic behind ``POST /v1/spawn``."""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Sequence

from boltrig.config.spawn_rules import SpawnRule, SpawnRuleSelection
from boltrig.kernel.held_call import sweep_run_credentials_if_settled
from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    GrantSet,
    InvocationContext,
    utcnow,
)
from boltrig.observability.langfuse_sink import build_observability_sink

from .chat_authority import inherit_on_behalf_bearer
from .result import AgentResult
from .runtime_resolver import RuntimeResolver
from .spawn_completion import complete_spawn, public_model_route
from .spawn_budget import estimate
from .spawn_policy import (
    build_child_context,
    prepare_spawn_intake,
    publish_subagent_event,
)
from .spawn_reservation import reserve_spawn
from .spawn_skills import (
    SkillNotFound as SkillNotFound,
    display_task as _display_task,  # noqa: F401 - compatibility import
)

if TYPE_CHECKING:
    from boltrig.kernel import Kernel
    from boltrig.kernel.cost import BudgetReservation

log = logging.getLogger(__name__)

_public_model_route = public_model_route


class Spawner:
    """Composes and runs ephemeral agents on top of the kernel."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
        model_catalogue: Any = None,
        spawn_rules: Sequence[SpawnRule] = (),
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        self._runtime_resolver = RuntimeResolver(
            kernel, sensitive_endpoint_id=sensitive_endpoint_id,
            codex_config=codex_config, model_catalogue=model_catalogue,
        )
        self._observability = build_observability_sink()
        self._base_spawn_rules = tuple(spawn_rules)

    def observability_status(self) -> dict[str, Any]:
        """Return only the sink's process-local, content-free attempt counters."""

        return self._observability.status_snapshot()

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
        announce_child: bool = True,
    ) -> dict[str, Any]:
        """Spawn one ephemeral agent for ``task`` with ``skills``.

        ``announce_child`` is false only when this spawn *is* the public root
        execution already represented by ``context.run_id`` (the direct chat
        lane). Delegated callers keep the default so their real child lifecycle
        remains visible and paired.
        """
        kernel = self._kernel
        intake = await prepare_spawn_intake(
            kernel.store,
            tenant_id,
            base_rules=self._base_spawn_rules,
            skills=skills or [],
            prefer=prefer or {},
            context=context,
        )
        skills, prefer = intake.skills, intake.prefer
        capability, spawn_rule = intake.capability, intake.spawn_rule
        run_id = uuid.uuid4().hex
        tokens_est, micros_est = estimate(task, intake.merged_prompt, skills, capability.cost_tier)
        reservation = await reserve_spawn(
            self,
            tenant_id=tenant_id,
            context=context,
            capability=capability,
            skills=skills,
            prefer=prefer,
            run_id=run_id,
            tokens_est=tokens_est,
            micros_est=micros_est,
            partial_on_budget=partial_on_budget,
            spawn_rule=spawn_rule,
        )
        if isinstance(reservation, dict):
            return reservation

        child_grants, child_ctx = self._prepare_child(
            tenant_id, run_id, intake, context, capability, skills, grant_ceiling
        )

        result, model_route, latency_ms = await self._invoke_runtime(
            tenant_id,
            capability,
            context,
            task=task,
            skills=skills,
            run_id=run_id,
            merged_prompt=intake.merged_prompt,
            child_ctx=child_ctx,
            child_grants=child_grants,
            reservation=reservation,
            tokens_est=tokens_est,
            micros_est=micros_est,
            spawn_rule=spawn_rule,
            announce_child=announce_child,
        )
        return await complete_spawn(
            self,
            tenant_id=tenant_id,
            capability=capability,
            context=context,
            skills=skills,
            run_id=run_id,
            child_grants=child_grants,
            reservation=reservation,
            tokens_est=tokens_est,
            micros_est=micros_est,
            result=result,
            model_route=model_route,
            latency_ms=latency_ms,
            spawn_rule=spawn_rule,
        )

    def _prepare_child(
        self,
        tenant_id: str,
        run_id: str,
        intake: Any,
        context: InvocationContext,
        capability: AgentCapability,
        skills: list[str],
        grant_ceiling: GrantSet | None,
    ) -> tuple[GrantSet, InvocationContext]:
        child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect(
            context.grants
        )
        if grant_ceiling is not None:
            child_grants = child_grants.intersect(grant_ceiling)
        child_ctx = self._child_context(
            tenant_id,
            run_id,
            intake.child_depth,
            context,
            capability,
            skills,
            child_grants,
            intake.spawn_rule,
        )
        return child_grants, child_ctx

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
        reservation: BudgetReservation,
        tokens_est: int,
        micros_est: int,
        spawn_rule: SpawnRuleSelection | None,
        announce_child: bool,
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
        await self._inherit_adapter_bearer(tenant_id, context.run_id, run_id, context.on_behalf_of)
        try:
            runtime = await self._runtime_for(tenant_id, capability, context)
            model_route = getattr(runtime, "model_route", None)
            if context.run_id and announce_child:
                self._publish_subagent_event(context, task, skills, run_id, capability, spawn_rule)
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
                    reservation,
                    delta_tokens=-tokens_est,
                    delta_micros=-micros_est,
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
        spawn_rule: SpawnRuleSelection | None = None,
    ) -> InvocationContext:
        return build_child_context(
            tenant_id, run_id, child_depth, parent, capability, skills, grants, spawn_rule
        )

    def _publish_subagent_event(
        self,
        context: InvocationContext,
        task: str,
        skills: list[str],
        run_id: str,
        capability: AgentCapability,
        spawn_rule: SpawnRuleSelection | None,
    ) -> None:
        publish_subagent_event(
            self._kernel.events,
            context,
            task,
            skills,
            run_id,
            capability,
            spawn_rule,
        )

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
            await sweep_run_credentials_if_settled(self._kernel.store, tenant_id, run_id)
        except Exception:  # noqa: BLE001 - a sweep fault is the pre-existing leak
            log.warning(
                "could not retire the run-scoped credentials of child run '%s'",
                run_id,
                exc_info=True,
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
                context.tenant_id,
                context.run_id,
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
        reservation: BudgetReservation,
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
            ep = await self._kernel.store.get_model_endpoint(tenant_id, capability.model_endpoint)
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
            reservation,
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
        spawn_rule: SpawnRuleSelection | None = None,
    ) -> None:
        detail = {"capability": capability.name, "runtime": capability.runtime}
        if spawn_rule is not None:
            detail["spawn_rule"] = spawn_rule.receipt()
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
            on_behalf_of=parent.on_behalf_of,
            workspace_id=parent.workspace_id,
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

    def _budget_partial(
        self,
        run_id: str,
        capability: AgentCapability,
        spawn_rule: SpawnRuleSelection | None,
    ) -> dict[str, Any]:
        result = {
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
        if spawn_rule is not None:
            result["spawn_rule"] = spawn_rule.receipt()
        return result


def build_spawner(
    kernel: Kernel,
    *,
    codex_config: dict[str, Any] | None = None,
    model_catalogue: Any = None,
    sensitive_endpoint_id: str | None = None,
    spawn_rules: Sequence[SpawnRule] = (),
) -> Spawner:
    """Construct the fleet ``Spawner`` for a kernel.

    ``codex_config`` is the trusted read-only Codex provider config assembled at the
    api composition root ([2026] VJS-CC-VJS 2); None (the default) keeps existing
    callers unaffected and the codex runtime degrade-marked unavailable.
    ``sensitive_endpoint_id`` is the manifest's local-only routing role. None keeps
    the router fail-closed: sensitive work must already name a sensitive endpoint
    or it is refused rather than escaping through a standard provider.
    """
    return Spawner(
        kernel, codex_config=codex_config, model_catalogue=model_catalogue,
        sensitive_endpoint_id=sensitive_endpoint_id,
        spawn_rules=spawn_rules,
    )


from .spawn_entrypoints import make_agent_invoker as make_agent_invoker, make_app_spawner as make_app_spawner  # noqa: E402
