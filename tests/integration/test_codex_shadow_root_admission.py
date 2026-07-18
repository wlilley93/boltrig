"""SEC-172: the Codex shadow root admission is an execution-neutral shadow write.

These drive a REAL chat turn (ChatService + build_turn_executor) and pin the three
guarantees of wiring ``RootRoutingAdmission.admit`` at the chat root:

* flag off (``codex_execution=None``, the default wiring): NO ``RootEngineDecision``
  is recorded and the turn behaves identically (the no-op that keeps live behaviour
  identical);
* flag on (OFF policy): the root records EXACTLY ONE decision whose route is LEGACY,
  and the turn's execution is UNCHANGED versus the flag-off turn;
* a shadow admission that raises is swallowed - the live turn still completes.

The turns run against a hermes-only kernel with no endpoint, so every spawn degrades
(P9) rather than reasoning; the degraded reply is the deterministic, model-free
observation point. Bound to SEC-172 in tests/invariants.yaml.
"""

from __future__ import annotations

from typing import Any

import pytest

from boltrig.api.codex_execution import CodexExecutionStack, build_codex_execution_stack
from boltrig.config.settings import Settings
from boltrig.fleet import build_spawner
from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.fleet.domain.codex_rollout import (
    CodexRolloutMode,
    CodexRolloutPolicy,
    EngineRoute,
    RootEngineDecision,
    RootRouteScope,
    RoutingReason,
)
from boltrig.fleet.infrastructure.memory_capability_attestations import (
    MemoryCapabilityAttestationStore,
)
from boltrig.fleet.infrastructure.memory_execution_ledger import MemoryExecutionLedger
from boltrig.fleet.infrastructure.memory_root_engine_decisions import (
    MemoryRootEngineDecisionStore,
)
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.models import AgentCapability, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
WS = "ws1"


def _on_stack(decisions: Any) -> CodexExecutionStack:
    """A flag-on stack over an observable decision store, at OFF policy generation 1
    (exactly what ``build_codex_execution_stack`` builds, but with the store exposed
    so a test can read what the root recorded)."""
    policy = CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)
    return CodexExecutionStack(
        root_admission=RootRoutingAdmission(policy, decisions),
        assignment_admission=AssignmentAdmission(
            MemoryCapabilityAttestationStore(), MemoryExecutionLedger()
        ),
        policy_generation=1,
    )


async def _run_turn(
    codex_execution: CodexExecutionStack | None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Drive one full chat turn end to end; return (run_id, reply_text, events)."""
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await kernel.store.upsert_capability(
        AgentCapability("hermes-worker", T, "hermes", ["*"], 2, True, "standard")
    )
    chat = ChatService(
        kernel.store,
        EventRelay(),
        turn_executor=build_turn_executor(
            kernel, build_spawner(kernel), continuity=False, codex_execution=codex_execution
        ),
    )
    events = [
        e
        async for e in chat.handle_turn(
            tenant_id=T, user_id="alice", role="engineer", message="do the thing",
            workspace_id=WS,
        )
    ]
    run_id = next(e["run_id"] for e in events if e.get("type") == "message_start")
    reply = "".join(e.get("delta", "") for e in events if e.get("type") == "text_delta")
    return run_id, reply, events


@pytest.mark.invariant("SEC-172")
async def test_flag_off_records_no_decision_and_is_execution_neutral() -> None:
    """The heart of the no-op guarantee: flag off (the default) wires ``None``, so
    the chat root never calls admit - nothing is recorded and the turn is clean."""
    # The production wiring: flag off => build_codex_execution_stack returns None.
    assert build_codex_execution_stack(Settings(codex_ledger=False), InMemoryStore()) is None
    assert build_codex_execution_stack(Settings(), InMemoryStore()) is None

    # A turn with the flag-off value (None) completes normally: the executor's
    # ``if codex_execution is not None`` branch is skipped, so admit is never reached
    # and no decision store is ever touched.
    _, reply, events = await _run_turn(None)
    assert reply  # the turn produced a reply
    assert "turn error" not in reply
    assert any(e.get("type") == "message_end" for e in events)


@pytest.mark.invariant("SEC-172")
async def test_flag_on_records_one_legacy_decision_and_execution_is_unchanged() -> None:
    """Flag on (OFF policy): the root records EXACTLY ONE decision, route LEGACY,
    and the turn's execution is byte-for-byte the same as the flag-off turn."""
    decisions = MemoryRootEngineDecisionStore()
    run_id, reply_on, _ = await _run_turn(_on_stack(decisions))

    # Exactly one decision, for this root run, on the legacy path (rollout off).
    assert len(decisions._records) == 1
    decision = await decisions.get(RootRouteScope(T, WS, run_id))
    assert isinstance(decision, RootEngineDecision)
    assert decision.route is EngineRoute.LEGACY
    assert decision.reason_code is RoutingReason.ROLLOUT_OFF
    assert decision.policy_generation == 1

    # Execution neutral: the shadow write changed nothing about the reply.
    _, reply_off, _ = await _run_turn(None)
    assert reply_on == reply_off


@pytest.mark.invariant("SEC-172")
async def test_shadow_admit_failure_is_swallowed_and_turn_completes() -> None:
    """Shadow fail-open: an admission that raises must NEVER break a live turn.

    The stack's decision store raises on every call, so ``admit`` raises inside
    ``shadow_admit``; the swallow keeps the turn running to its normal (degraded)
    reply. Without the try/except the RuntimeError would propagate into the executor
    and surface as a ``(turn error: RuntimeError)`` reply - which this asserts against.
    """

    class _BoomStore:
        async def get(self, scope: RootRouteScope) -> RootEngineDecision | None:
            raise RuntimeError("boom")

        async def insert_once(self, decision: RootEngineDecision) -> Any:
            raise RuntimeError("boom")

    _, reply, events = await _run_turn(_on_stack(_BoomStore()))
    assert reply
    assert "turn error" not in reply  # the shadow failure never surfaced
    assert any(e.get("type") == "message_end" for e in events)
