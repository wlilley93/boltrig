"""Spawn logic behind ``POST /v1/spawn``."""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Sequence

from boltrig.config.spawn_rules import SpawnRule, SpawnRuleSelection
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
)
from boltrig.observability.langfuse_sink import build_observability_sink

from .result import AgentResult
from .runtime_resolver import RuntimeResolver
from .spawn_completion import complete_spawn
from .spawn_budget import estimate
from .spawn_policy import (
    build_child_context,
    prepare_spawn_intake,
)
from .spawn_reservation import reserve_spawn
from .spawn_lifecycle import SpawnLifecycleMixin
from .spawn_skills import (
    SkillNotFound as SkillNotFound,
    display_task as _display_task,  # noqa: F401 - compatibility import
)

if TYPE_CHECKING:
    from boltrig.kernel import Kernel
    from boltrig.kernel.cost import BudgetReservation

log = logging.getLogger(__name__)

class Spawner(SpawnLifecycleMixin):
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
        intake, run_id, tokens_est, micros_est, reservation = await self._plan_and_reserve(
            tenant_id, task, skills, prefer, context,
            partial_on_budget=partial_on_budget,
        )
        if isinstance(reservation, dict):
            return reservation
        skills = intake.skills
        capability, spawn_rule = intake.capability, intake.spawn_rule

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

    async def _plan_and_reserve(
        self,
        tenant_id: str,
        task: str,
        skills: list[str],
        prefer: dict[str, Any],
        context: InvocationContext,
        *,
        partial_on_budget: bool,
    ):
        """Resolve intake (skills/prefer/capability/rule), mint the run id and
        estimate, and take the budget reservation. Returns the early-return
        partial dict IN PLACE of a reservation when the budget hard-stop hit."""
        intake = await prepare_spawn_intake(
            self._kernel.store,
            tenant_id,
            base_rules=self._base_spawn_rules,
            skills=skills or [],
            prefer=prefer or {},
            context=context,
        )
        resolved_skills = intake.skills
        capability, spawn_rule = intake.capability, intake.spawn_rule
        run_id = uuid.uuid4().hex
        tokens_est, micros_est = estimate(
            task, intake.merged_prompt, resolved_skills, capability.cost_tier
        )
        reservation = await reserve_spawn(
            self,
            tenant_id=tenant_id,
            context=context,
            capability=capability,
            skills=resolved_skills,
            prefer=intake.prefer,
            run_id=run_id,
            tokens_est=tokens_est,
            micros_est=micros_est,
            partial_on_budget=partial_on_budget,
            spawn_rule=spawn_rule,
        )
        return intake, run_id, tokens_est, micros_est, reservation

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
        *,
        outbound_text: str | None = None,
    ):
        return await self._runtime_resolver.runtime_for(
            tenant_id, capability, context, outbound_text=outbound_text
        )

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
            # The composed prompt IS the egress payload: hand it to the routing
            # seam so the PII scanner classifies it before the destination is
            # decided (SEC-13). Detection reroutes; it never rewrites.
            runtime = await self._runtime_for(
                tenant_id,
                capability,
                context,
                outbound_text=self._compose_prompt(merged_prompt, task),
            )
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
