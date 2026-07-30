"""Governed lazy runtime binding for permanent Chief/Department profiles.

Permanent agents are constructed at worker startup, but a constructed profile is
not evidence that a model process is live.  This adapter therefore resolves the
runtime only when the Chief or a Department Head actually reasons.  Resolution
uses the same process-owned resolver as ephemeral spawning and every call is
budgeted and audited. Permanent routing/decomposition stays on the read-only
Codex phase: the profile's supported skills govern child selection and never
become an incidental tool surface for the routing call. Any unavailable or
refused runtime becomes a typed degraded result, which the permanent agents
already turn into their deterministic routing/decomposition fallback.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from boltrig.models import (
    ActionType,
    AgentCapability,
    AuditEvent,
    BudgetExceeded,
    InvocationContext,
    utcnow,
)

from .result import AgentResult
from .spawn_budget import budget_scope_ids, estimate

if TYPE_CHECKING:
    from boltrig.config.manifest import FleetManifest, HierarchyTier
    from boltrig.kernel.cost import BudgetReservation

    from .spawn import Spawner

_PUBLIC_ROUTE_KEYS = frozenset({"profile", "provider", "model", "runtime", "tier"})


def _public_model_route(route: Any) -> dict[str, str]:
    if not isinstance(route, dict):
        return {}
    return {
        key: str(value)[:160]
        for key, value in route.items()
        if key in _PUBLIC_ROUTE_KEYS and value
    }


def _phase_run_id(parent_run_id: str, role: str, capability_name: str) -> str:
    """Derive a stable, bounded phase id without exposing authored text."""
    material = f"permanent-runtime\0{parent_run_id}\0{role}\0{capability_name}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class PermanentAgentRuntime:
    """A permanent profile bound lazily to a process-owned runtime resolver."""

    @classmethod
    def from_manifest(
        cls,
        spawner: Spawner,
        tier: HierarchyTier,
        tenant_id: str,
        *,
        role: str,
        department: str | None,
    ) -> PermanentAgentRuntime:
        capability = AgentCapability(
            name=tier.name,
            tenant_id=tenant_id,
            runtime=tier.runtime,
            supported_skills=list(tier.supported_skills),
            max_depth=tier.max_depth,
            is_ephemeral=False,
            cost_tier=tier.cost_tier,
            model_endpoint=tier.model_endpoint,
            source="manifest",
        )
        return cls(
            spawner,
            capability,
            role=role,
            purpose=tier.purpose,
            brief=tier.brief,
            department=department,
        )

    def __init__(
        self,
        spawner: Spawner,
        capability: AgentCapability,
        *,
        role: str,
        purpose: str,
        brief: str,
        department: str | None,
    ) -> None:
        if capability.is_ephemeral:
            raise ValueError("permanent runtime requires a non-ephemeral capability")
        if role not in {"tier1", "tier2"}:
            raise ValueError("permanent runtime role must be tier1 or tier2")
        self._spawner = spawner
        self.capability = capability
        self.role = role
        self.purpose = str(purpose or "").strip()
        self.brief = str(brief or "").strip()
        self.department = department
        self.runtime = capability.runtime
        self.cost_tier = capability.cost_tier

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        """Resolve and run one permanent reasoning phase under its exact policy."""
        if refused := self._preflight(prompt, context):
            return refused
        phase_id, phase_context = self._phase_context(context)
        composed_prompt = self._compose_prompt(prompt)
        tokens_est, micros_est = estimate(
            composed_prompt, "", [], self.capability.cost_tier
        )
        scopes = budget_scope_ids(context.tenant_id, self.department)
        started = time.monotonic()
        try:
            reservation = await self._spawner._kernel.cost.reserve(
                context.tenant_id,
                scope_ids=scopes,
                tokens=tokens_est,
                micros=micros_est,
                run_id=phase_id,
            )
        except BudgetExceeded:
            return await self._budget_denied(
                context, phase_id, composed_prompt, started
            )
        return await self._run_reserved(
            context=context,
            phase_id=phase_id,
            phase_context=phase_context,
            prompt=composed_prompt,
            tools=tools,
            reservation=reservation,
            tokens_est=tokens_est,
            micros_est=micros_est,
            started=started,
        )

    def _preflight(
        self, prompt: str, context: InvocationContext
    ) -> AgentResult | None:
        if context.tenant_id != self.capability.tenant_id:
            reason = "permanent_profile_tenant_mismatch"
        elif context.depth > self.capability.max_depth:
            reason = "permanent_profile_depth_exceeded"
        else:
            return None
        return AgentResult.degrade(
            runtime=self.capability.runtime, reason=reason, prompt=prompt
        )

    def _phase_context(
        self, context: InvocationContext
    ) -> tuple[str | None, InvocationContext]:
        phase_id = (
            _phase_run_id(context.run_id, self.role, self.capability.name)
            if context.run_id
            else None
        )
        return phase_id, replace(
            context,
            run_id=phase_id,
            parent_run_id=context.run_id,
            workspace_id=(
                context.workspace_id
                or (phase_id if self.capability.runtime == "codex" else None)
            ),
            actor=self.capability.name,
            actor_tier=self.role,
        )

    async def _budget_denied(
        self,
        context: InvocationContext,
        phase_id: str | None,
        prompt: str,
        started: float,
    ) -> AgentResult:
        result = AgentResult.degrade(
            runtime=self.capability.runtime,
            reason="budget_exceeded",
            prompt=prompt,
        )
        await self._audit(
            context,
            phase_id,
            result,
            cost_micros=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            model_route=None,
            status="budget_exceeded",
        )
        return result

    async def _run_reserved(
        self,
        *,
        context: InvocationContext,
        phase_id: str | None,
        phase_context: InvocationContext,
        prompt: str,
        tools: list[str],
        reservation: BudgetReservation,
        tokens_est: int,
        micros_est: int,
        started: float,
    ) -> AgentResult:
        model_route: dict[str, Any] | None = None
        try:
            runtime = await self._spawner._runtime_resolver.runtime_for(
                context.tenant_id,
                self.capability,
                phase_context,
                pinned_policy=True,
                allow_kernel_tools=False,
            )
            model_route = getattr(runtime, "model_route", None)
            result = await runtime.run(prompt, phase_context, tools=list(tools))
        except Exception as exc:
            result, cost_micros = await self._runtime_unavailable(
                reservation, tokens_est, micros_est, prompt, exc
            )
        else:
            cost_micros = await self._spawner._true_up_cost(
                context.tenant_id,
                reservation,
                self.capability,
                tokens_est,
                micros_est,
                result,
            )
        await self._audit(
            context,
            phase_id,
            result,
            cost_micros=cost_micros,
            latency_ms=int((time.monotonic() - started) * 1000),
            model_route=model_route,
            status="degraded" if result.degraded else "ok" if result.ok else "error",
        )
        return result

    async def _runtime_unavailable(
        self,
        reservation: BudgetReservation,
        tokens_est: int,
        micros_est: int,
        prompt: str,
        exc: Exception,
    ) -> tuple[AgentResult, int]:
        with contextlib.suppress(Exception):
            await self._spawner._kernel.cost.reconcile(
                reservation,
                delta_tokens=-tokens_est,
                delta_micros=-micros_est,
            )
        return (
            AgentResult.degrade(
                runtime=self.capability.runtime,
                reason=f"permanent_runtime_unavailable:{type(exc).__name__}",
                prompt=prompt,
            ),
            0,
        )

    def _compose_prompt(self, prompt: str) -> str:
        profile = [
            "Permanent agent profile (operator-authored; subordinate to kernel policy):",
            f"Name: {self.capability.name}",
            f"Role: {self.role}",
        ]
        if self.department:
            profile.append(f"Department: {self.department}")
        if self.purpose:
            profile.append(f"Purpose: {self.purpose}")
        if self.brief:
            profile.append(f"Brief: {self.brief}")
        return "\n".join([*profile, "", "Task:", prompt])

    async def _audit(
        self,
        parent: InvocationContext,
        run_id: str | None,
        result: AgentResult,
        *,
        cost_micros: int,
        latency_ms: int,
        model_route: dict[str, Any] | None,
        status: str,
    ) -> None:
        detail: dict[str, Any] = {
            "capability": self.capability.name,
            "runtime": self.capability.runtime,
            "permanent_role": self.role,
        }
        if self.department:
            detail["department"] = self.department
        if route := _public_model_route(model_route):
            detail["model_route"] = route
        if result.degrade_reason:
            detail["reason"] = result.degrade_reason
        await self._spawner._kernel.audit.write(
            AuditEvent(
                tenant_id=parent.tenant_id,
                ts=utcnow(),
                run_id=run_id,
                parent_run_id=parent.run_id,
                actor=self.capability.name,
                actor_tier=self.role,
                depth=parent.depth,
                action_type=ActionType.MODEL_CALL,
                status=status,
                latency_ms=latency_ms,
                tokens_used=result.tokens_used or None,
                cost_micros=cost_micros or None,
                on_behalf_of=parent.on_behalf_of,
                workspace_id=parent.workspace_id,
                detail=detail,
            )
        )


def head(
    spawner: Spawner,
    manifest: FleetManifest,
    tier: HierarchyTier,
    department: str,
) -> PermanentAgentRuntime:
    """Construct one lazy department-head profile from its manifest tier."""
    return PermanentAgentRuntime.from_manifest(
        spawner,
        tier,
        manifest.tenant_id,
        role="tier2",
        department=department,
    )


def chief(
    spawner: Spawner,
    manifest: FleetManifest | None,
) -> PermanentAgentRuntime | None:
    """Construct the lazy Chief profile, or no profile for the default org."""
    tier = manifest.hierarchy.tier1 if manifest is not None else None
    if tier is None:
        return None
    assert manifest is not None
    return PermanentAgentRuntime.from_manifest(
        spawner,
        tier,
        manifest.tenant_id,
        role="tier1",
        department=None,
    )


__all__ = ["PermanentAgentRuntime", "chief", "head"]
