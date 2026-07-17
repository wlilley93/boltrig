"""Flag-gated composition of the Codex read-only execution stack (scaffold).

Steps 1-2 of the Codex ledger wiring. This module CONSTRUCTS the two governed
admission services behind ``BOLTRIG_CODEX_LEDGER`` but CALLS NOTHING. With the
flag off (the default) it is a total no-op: it returns ``None`` and constructs
nothing. With the flag on it builds a small frozen container and parks it on
``app.state.platform``; nothing invokes ``RootRoutingAdmission.admit`` or
``AssignmentAdmission.admit``. Wiring an ``admit()`` into the live chat / pump /
spawn path is a later, court-gated PR, not this one.

Why this lives in ``boltrig/api/`` and not ``boltrig/fleet/application/``:
selecting a store adapter imports the store / infrastructure layer, and the
architecture gate (``scripts/check_architecture.py``) forbids ``fleet.{domain,
ports,application}`` from importing outward. Composition that reaches the store
must therefore sit outside the fleet core, at the API composition boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from boltrig.config.settings import Settings
from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.domain.codex_rollout import CodexRolloutMode, CodexRolloutPolicy
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
    """A parked, inert container of the two Codex admission services.

    Constructed only when ``BOLTRIG_CODEX_LEDGER`` is on and landed on
    ``app.state.platform``. Nothing in this scaffold calls
    ``root_admission.admit`` or ``assignment_admission.admit``; wiring an
    ``admit()`` into the live execution path is a later, court-gated PR.
    """

    root_admission: RootRoutingAdmission
    assignment_admission: AssignmentAdmission


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
    )


__all__ = ["CodexExecutionStack", "build_codex_execution_stack"]
