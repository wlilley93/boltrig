"""Flag-gated composition of the Codex read-only execution stack.

The Codex ledger wiring behind ``BOLTRIG_CODEX_LEDGER``. With the flag off (the
default) it is a total no-op: ``build_codex_execution_stack`` returns ``None`` and
constructs nothing, and the chat root never calls admit. With the flag on it builds
a small frozen container, parks it on ``app.state.platform``, and the chat root
calls ``shadow_admit`` to record ONE execution-neutral ``RootEngineDecision`` per
root run (SEC-170): under the default OFF policy the router returns ``route=LEGACY``
before compatibility/workload are read, so nothing about execution changes. The
ON execution path and ``AssignmentAdmission.admit`` remain deferred to a later,
court-gated PR.

Why this lives in ``boltrig/api/`` and not ``boltrig/fleet/application/``:
selecting a store adapter imports the store / infrastructure layer, and the
architecture gate (``scripts/check_architecture.py``) forbids ``fleet.{domain,
ports,application}`` from importing outward. Composition that reaches the store
must therefore sit outside the fleet core, at the API composition boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from boltrig.config.settings import Settings
from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.domain.codex_rollout import (
    CodexCompatibility,
    CodexRolloutMode,
    CodexRolloutPolicy,
    RootRouteScope,
    RootRoutingFacts,
    RootWorkload,
)
from boltrig.fleet.infrastructure.memory_capability_attestations import (
    MemoryCapabilityAttestationStore,
)
from boltrig.fleet.infrastructure.memory_execution_ledger import MemoryExecutionLedger
from boltrig.fleet.infrastructure.memory_root_engine_decisions import (
    MemoryRootEngineDecisionStore,
)
from boltrig.fleet.ports.capability_attestations import CapabilityAttestationStore
from boltrig.fleet.ports.execution_ledger import ExecutionLedgerStore
from boltrig.fleet.ports.root_engine_decisions import RootEngineDecisionStore
from boltrig.store import Store

log = logging.getLogger(__name__)

# Decisive call 1 (a decisive engineering call, NOT a court fork): the scaffold
# policy is OFF at generation 1. Under CodexRolloutMode.OFF the router
# short-circuits to LEGACY before the generation is ever read (see
# codex_routing.py _route_new_root: the OFF branch returns before generation
# matters), so the generation value is inert for this scaffold. The real
# generation-source question (where a live generation comes from) is deferred to
# the later PR that turns the policy ON.
_SCAFFOLD_POLICY = CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)


@dataclass(frozen=True)
class CodexExecutionStack:
    """A container of the two Codex admission services plus the shadow root call.

    Constructed only when ``BOLTRIG_CODEX_LEDGER`` is on and landed on
    ``app.state.platform``. ``shadow_admit`` is wired at the chat root (SEC-170)
    to record one execution-neutral ``RootEngineDecision`` per root run; under the
    default OFF policy the router returns ``route=LEGACY`` and nothing about
    execution changes. ``assignment_admission.admit`` is still uncalled; wiring the
    ON execution path (and the assignment lane) is a later, court-gated PR.
    """

    root_admission: RootRoutingAdmission
    assignment_admission: AssignmentAdmission
    policy_generation: int

    async def shadow_admit(
        self, tenant_id: str, workspace_id: str | None, run_id: str
    ) -> None:
        """Record one shadow ``RootEngineDecision`` for a chat root, execution-neutral.

        The root run maps onto the existing top-level WorkItem (root_run_id = the
        root WorkItem id = the chat ``run_id``; LOG-2026-07-17-121829). Under the
        default OFF policy the router short-circuits to ``route=LEGACY`` before it
        reads compatibility or workload (``codex_routing.py`` _route_new_root, the
        OFF branch), so this changes NOTHING about how the turn executes: it only
        persists an insert-once decision. ``expected_policy_generation`` is NOT
        inert (the router equality-checks it before routing) so it must match the
        stack's generation; ``compatibility``/``workload`` ARE inert under OFF, so
        the conservative legacy-compatible constants (INELIGIBLE, BOUNDED_READ_ONLY)
        keep a hypothetical ON policy on the legacy path too.

        DECISIVE CALL - SHADOW FAIL-OPEN: any failure (a drifted fact, an invalid
        scope, a store error) is logged and swallowed so the shadow write can NEVER
        break a live chat turn. This method is total: it never raises. Fail-CLOSED
        authority is deferred to the ON-path PR; this increment is execution-neutral.
        A None workspace scope is simply skipped (no valid identifier to key on).
        """
        if workspace_id is None:
            return
        try:
            facts = RootRoutingFacts(
                scope=RootRouteScope(tenant_id, workspace_id, run_id),
                expected_policy_generation=self.policy_generation,
                workload=RootWorkload.BOUNDED_READ_ONLY,
                compatibility=CodexCompatibility.INELIGIBLE,
            )
            await self.root_admission.admit(facts)
        except Exception:  # shadow write, fail-open (see the decisive call above)
            log.warning("codex shadow root admission failed", exc_info=True)


def build_codex_execution_stack(
    settings: Settings, store: Store
) -> CodexExecutionStack | None:
    """Construct the Codex execution stack behind ``BOLTRIG_CODEX_LEDGER``.

    Flag off (the default): return ``None`` and construct nothing (the total
    no-op that keeps live behaviour identical). Flag on: construct and return the
    container, selecting the in-memory vs Postgres store adapters by
    ``isinstance(store, PostgresStore)`` exactly as ``build_store`` branches, and
    CALL NOTHING.
    """
    if not settings.codex_ledger:
        return None

    # Lazy import so the flag-off path never pulls in the Postgres/asyncpg module
    # (mirrors build_store's lazy PostgresStore import). Only reached when on.
    from boltrig.store.postgres import PostgresStore

    decisions: RootEngineDecisionStore
    ledger: ExecutionLedgerStore
    attestations: CapabilityAttestationStore
    if isinstance(store, PostgresStore):
        from boltrig.fleet.infrastructure.postgres_capability_attestations import (
            PostgresCapabilityAttestationStore,
        )
        from boltrig.fleet.infrastructure.postgres_execution_ledger import (
            PostgresExecutionLedger,
        )
        from boltrig.fleet.infrastructure.postgres_root_engine_decisions import (
            PostgresRootEngineDecisionStore,
        )

        # Decisive call 2 (a decisive engineering call, NOT a court fork): hand
        # the store's connection pool to the sibling durable stores. The cleaner
        # shape is a public ``pool`` accessor on PostgresStore, but adding one
        # grows the already-exempted 2342-line postgres.py and would loosen its
        # structural ratchet (forbidden here). Rather than manufacture offsetting
        # deletions in unrelated store code for scaffold that no test exercises,
        # read ``_pool`` directly from this composition root (api layer, outside
        # fleet). Low-blast and reversible: the later ON-path PR can promote it to
        # a public accessor when it also touches postgres.py for real.
        pool = store._pool
        decisions = PostgresRootEngineDecisionStore(pool)
        ledger = PostgresExecutionLedger(pool)
        attestations = PostgresCapabilityAttestationStore(pool)
    else:
        decisions = MemoryRootEngineDecisionStore()
        ledger = MemoryExecutionLedger()
        attestations = MemoryCapabilityAttestationStore()

    return CodexExecutionStack(
        root_admission=RootRoutingAdmission(_SCAFFOLD_POLICY, decisions),
        assignment_admission=AssignmentAdmission(attestations, ledger),
        policy_generation=_SCAFFOLD_POLICY.generation,
    )


__all__ = ["CodexExecutionStack", "build_codex_execution_stack"]
