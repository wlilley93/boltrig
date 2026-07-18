"""SEC-172: the Codex shadow root admission at the PUMP root lane.

The pump is the second top-level entry point (the chat root is the first,
``test_codex_shadow_root_admission.py``). These drive a REAL pump cycle
(``WorkPump.handle_claimed_item`` via ``run_once``) and pin the guarantees of
wiring ``CodexExecutionStack.shadow_admit`` at the pump's root lane:

* flag off (``codex_execution=None``, the default wiring): a pump ROOT item
  records NO ``RootEngineDecision`` and the pump behaves identically;
* flag on (OFF policy): a pump ROOT item (``parent_id is None``) records EXACTLY
  ONE decision whose route is LEGACY, and execution is UNCHANGED; a CHILD item
  (``parent_id`` set) records NOTHING - only roots are admitted;
* re-handling the same root is a safe replay: still exactly one decision, no error
  (``RootRoutingAdmission.admit`` is insert-once).

Everything runs offline: a script capability makes decomposition deterministic;
the shadow write only records, it never changes how the item executes.
"""

from __future__ import annotations

import pytest

import uuid
from typing import Any

from boltrig.api.codex_execution import CodexExecutionStack, build_codex_execution_stack
from boltrig.config.settings import Settings
from boltrig.fleet import (
    ChiefOfStaff,
    Department,
    DepartmentHead,
    WorkPump,
    build_spawner,
)
from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.application.root_admission import RootRoutingAdmission
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
from boltrig.models import (
    AgentCapability,
    GrantSet,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore

T = "acme"
WS = "ws1"
DEPT = "engineering"


def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


async def _add_script_cap(kernel: Kernel) -> None:
    await kernel.store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 3, True, "cheap")
    )


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


def _pump(kernel: Kernel, *, codex_execution: CodexExecutionStack | None = None) -> WorkPump:
    spawner = build_spawner(kernel)
    heads = {DEPT: DepartmentHead(DEPT, [], [], 32, spawner=spawner, store=kernel.store)}
    cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=["bug", "fix"])])
    return WorkPump(kernel, spawner, cos, heads, None, codex_execution=codex_execution)


def _item(intent: str = "fix the login bug", **kw) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4().hex, tenant_id=T, source="internal", intent=intent,
        confidence=0.9, convergent=False, workspace_id=WS, **kw,
    )


# --- flag OFF: the default wiring records nothing and is execution-neutral -----
@pytest.mark.invariant("SEC-173")
async def test_flag_off_pump_root_records_no_decision() -> None:
    """Flag off (the default): the pump wires ``None``, so a ROOT item never calls
    admit - nothing is recorded and the item completes exactly as before."""
    # The production build is None with the flag off, so the pump's construction
    # site (build_org) passes None and no admit is ever reached.
    assert build_codex_execution_stack(Settings(codex_ledger=False), InMemoryStore()) is None
    assert build_codex_execution_stack(Settings(), InMemoryStore()) is None

    kernel = _kernel()
    await _add_script_cap(kernel)
    pump = _pump(kernel)  # codex_execution defaults to None (flag off)
    assert pump._codex_execution is None
    item = _item()
    await kernel.store.create_work_item(item)

    assert await pump.run_once(T) is True
    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE  # the item completed normally, untouched


# --- flag ON: a ROOT records exactly one LEGACY decision; execution unchanged ---
@pytest.mark.invariant("SEC-173")
async def test_flag_on_pump_root_records_one_legacy_decision() -> None:
    """Flag on (OFF policy): a pump ROOT (``parent_id is None``) records EXACTLY ONE
    decision, route LEGACY, for its root run; and the item still completes DONE."""
    kernel = _kernel()
    await _add_script_cap(kernel)
    decisions = MemoryRootEngineDecisionStore()
    pump = _pump(kernel, codex_execution=_on_stack(decisions))
    item = _item()  # a ROOT: parent_id is None
    await kernel.store.create_work_item(item)

    assert await pump.run_once(T) is True

    # Exactly one decision, for this root run (root_run_id = the root WorkItem id),
    # on the legacy path (rollout off).
    assert len(decisions._records) == 1
    decision = await decisions.get(RootRouteScope(T, WS, item.id))
    assert isinstance(decision, RootEngineDecision)
    assert decision.route is EngineRoute.LEGACY
    assert decision.reason_code is RoutingReason.ROLLOUT_OFF
    assert decision.policy_generation == 1

    # Execution neutral: the shadow write changed nothing about the outcome.
    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE


@pytest.mark.invariant("SEC-173")
async def test_flag_on_pump_child_records_nothing() -> None:
    """Only ROOTS are admitted: a CHILD item (``parent_id`` set) records no decision,
    even with the stack wired on."""
    kernel = _kernel()
    await _add_script_cap(kernel)
    decisions = MemoryRootEngineDecisionStore()
    pump = _pump(kernel, codex_execution=_on_stack(decisions))

    root = _item("the root epic", status=WorkStatus.DONE)  # not claimable
    await kernel.store.create_work_item(root)
    child = _item("a filed child", parent_id=root.id)  # PENDING, parent_id set
    await kernel.store.create_work_item(child)

    # The sole PENDING item is the child; the pump claims and handles it.
    assert await pump.run_once(T) is True

    # A child begins no root run: nothing is recorded.
    assert decisions._records == {}
    handled = await kernel.store.get_work_item(T, child.id)
    assert handled.status == WorkStatus.DONE  # the child still executed


# --- replay: re-handling the same root is a safe replay (insert-once) ----------
@pytest.mark.invariant("SEC-173")
async def test_rehandling_the_same_root_is_a_safe_replay() -> None:
    """Re-handling the same root item (a requeue/retry) admits again, which REPLAYS
    the insert-once decision: still exactly one record and never an error."""
    kernel = _kernel()
    await _add_script_cap(kernel)
    decisions = MemoryRootEngineDecisionStore()
    pump = _pump(kernel, codex_execution=_on_stack(decisions))
    item = _item()
    await kernel.store.create_work_item(item)

    # Handle the same root twice, directly. The second admit is a verbatim replay.
    await pump.handle_claimed_item(item)
    await pump.handle_claimed_item(item)

    assert len(decisions._records) == 1  # one record, no double-insert, no error
    decision = await decisions.get(RootRouteScope(T, WS, item.id))
    assert isinstance(decision, RootEngineDecision)
    assert decision.route is EngineRoute.LEGACY
