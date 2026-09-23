"""Spawn lifecycle telemetry (arc-1 structural partial).

The child-terminal + observability half of ``fleet/spawn.py``: subagent event
frames, credential retirement at the child's terminal, cost true-up, bearer
inheritance, the spawn audit row and the budget-partial return - extracted
verbatim as a mixin. ``Spawner`` composes it; the method surface on the final
class is unchanged (spawn_reservation/spawn_completion/spawn_entrypoints call
these through the spawner instance).

Host contract: uses ``self._kernel`` (store/events/cost/audit/credentials) and
``self._observability`` (set by Spawner.__init__).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from boltrig.config.spawn_rules import SpawnRuleSelection
from boltrig.kernel.held_call import sweep_run_credentials_if_settled
from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    InvocationContext,
    utcnow,
)

from .chat_authority import inherit_on_behalf_bearer
from .result import AgentResult
from .spawn_completion import public_model_route
from .spawn_policy import publish_subagent_event

if TYPE_CHECKING:
    from boltrig.kernel.cost import BudgetReservation

log = logging.getLogger(__name__)

_public_model_route = public_model_route


class SpawnLifecycleMixin:
    """Child-terminal + telemetry methods for ``Spawner``."""

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
