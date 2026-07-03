"""Workspace-scoping the workflow resources ([2026] VJS-COUNTY 8, D2).

Phase 5 of the org/workspace tenancy build. A workflow now carries an optional
``workspace_id``: NULL means ORG-WIDE (visible + runnable in every workspace of the
org, exactly as before - every existing workflow is NULL), a SET value scopes it to
that one workspace. These pins prove the D2 rules:

  * FR-WFL-11  a workflow created in an active workspace is STAMPED with it, a
               learned workflow INHERITS the workspace of the run that produced it,
               and match/get return org-wide OR own-workspace workflows only - never
               a workflow scoped to a DIFFERENT workspace; with NO active workspace a
               caller sees exactly the org-wide set (byte-for-byte backward-compat).
  * SEC-116    scoping only NARROWS visibility, never widens authority (COUNTY 5): a
               workflow scoped to another workspace is fail-closed unknown on the
               get / trigger / execute paths (never triggerable cross-workspace), and
               an existing NULL workflow round-trips unchanged.

Everything runs offline against the in-memory store and a bare kernel.
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from boltrig.kernel import Kernel
from boltrig.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import (
    generate_workflow,
    learn_from_success,
    select_or_generate_workflow,
)
from boltrig.workflows.library import WorkflowLibrary

T = "acme"


def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


def _wf(id: str, workspace_id: str | None) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=id, tenant_id=T, version="1.0.0", source=WorkflowSource.LEARNED,
        definition={"name": id, "steps": []}, intent_tags=["billing"],
        origin_task="a prior billing success", workspace_id=workspace_id,
    )


# --- FR-WFL-11: create stamps, learned inherits, match is workspace-scoped -----
@pytest.mark.security
@pytest.mark.invariant("FR-WFL-11")
def test_generate_stamps_active_workspace_and_none_is_org_wide():
    scoped = generate_workflow("a billing run", ["billing"], T, workspace_id="ws-1")
    assert scoped.workspace_id == "ws-1"
    # No active workspace synthesises an ORG-WIDE (None) workflow, exactly as before.
    org_wide = generate_workflow("a billing run", ["billing"], T)
    assert org_wide.workspace_id is None


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-11")
async def test_learned_workflow_inherits_the_runs_workspace():
    # A workspace-scoped generated workflow learns a workspace-scoped workflow.
    gen = generate_workflow("a billing run", ["billing"], T, workspace_id="ws-1")
    learned = await learn_from_success(InMemoryStore(), gen, "origin-task")
    assert learned.source is WorkflowSource.LEARNED
    assert learned.workspace_id == "ws-1"  # scope carried forward, never widened
    # An org-wide generated workflow learns an org-wide one (backward-compat).
    org_gen = generate_workflow("a billing run", ["billing"], T)
    org_learned = await learn_from_success(InMemoryStore(), org_gen, "origin-task")
    assert org_learned.workspace_id is None


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-11")
async def test_match_returns_org_wide_or_own_workspace_never_another():
    store = InMemoryStore()
    # Three equally-matching workflows; ids chosen so the ws-2 one would WIN the
    # deterministic id tiebreak if it were ever visible - so a result that is not it
    # proves it was excluded, not merely out-ranked.
    await store.upsert_workflow(_wf("a-ws2", "ws-2"))
    await store.upsert_workflow(_wf("b-ws1", "ws-1"))
    await store.upsert_workflow(_wf("c-org", None))
    lib = WorkflowLibrary(store)

    in_ws1 = await lib.match(T, ["billing"], active_workspace_id="ws-1")
    assert in_ws1.id == "b-ws1"  # org-wide + ws-1 only; a-ws2 never surfaces

    in_ws2 = await lib.match(T, ["billing"], active_workspace_id="ws-2")
    assert in_ws2.id == "a-ws2"  # its own workspace sees it

    # No active workspace sees EXACTLY the org-wide set - here just c-org.
    none = await lib.match(T, ["billing"], active_workspace_id=None)
    assert none.id == "c-org"


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-11")
async def test_no_active_workspace_sees_exactly_the_org_wide_set_byte_for_byte():
    # Every existing workflow is NULL (org-wide). A caller with no active workspace
    # matches them unchanged - the pre-workspace behaviour, byte-for-byte.
    store = InMemoryStore()
    existing = _wf("legacy", None)
    await store.upsert_workflow(existing)
    matched = await WorkflowLibrary(store).match(T, ["billing"])
    assert matched == existing  # dataclass equality: nothing added, nothing scoped
    # select_or_generate reuses it too (retrieval half unchanged for NULL workflows).
    chosen = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
    assert chosen.id == "legacy"


# --- SEC-116: scoping narrows visibility only; fail-closed cross-workspace ------
@pytest.mark.security
@pytest.mark.invariant("SEC-116")
async def test_get_is_fail_closed_across_a_workspace_boundary():
    store = InMemoryStore()
    scoped = _wf("wf-x", "ws-2")
    await store.upsert_workflow(scoped)
    lib = WorkflowLibrary(store)
    # Its own workspace sees it, byte-for-byte (visibility filter adds no authority).
    assert await lib.get(T, "wf-x", active_workspace_id="ws-2") == scoped
    # A different workspace and no-active-workspace both see NOTHING (fail-closed).
    assert await lib.get(T, "wf-x", active_workspace_id="ws-1") is None
    assert await lib.get(T, "wf-x", active_workspace_id=None) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-116")
async def test_trigger_and_execute_cannot_reach_another_workspace():
    kernel = _kernel()
    store = kernel.store
    await store.upsert_workflow(_wf("wf-x", "ws-2"))
    lib = WorkflowLibrary(store, kernel=kernel)

    # trigger: unknown to a ws-1 caller (fail-closed LookupError), runs for ws-2.
    with pytest.raises(LookupError):
        await lib.trigger(T, "wf-x", {}, active_workspace_id="ws-1")
    desc = await lib.trigger(T, "wf-x", {}, active_workspace_id="ws-2")
    assert desc["workflow_id"] == "wf-x"

    # execute: the InvocationContext carries the active workspace; a ws-1 context
    # cannot reach the ws-2 workflow.
    ctx_ws1 = InvocationContext(tenant_id=T, run_id=uuid.uuid4().hex, workspace_id="ws-1")
    with pytest.raises(LookupError):
        await lib.execute(T, "wf-x", {}, ctx_ws1)


@pytest.mark.security
@pytest.mark.invariant("SEC-116")
async def test_scoping_never_widens_authority_it_only_hides_rows():
    # The visibility filter is additive-narrowing: a WorkflowDefinition carries no
    # authority-bearing field (SEC-84) and the filter never mutates it, so making a
    # workflow workspace-visible cannot add any grant/scope - it only decides
    # whether the row is returned. Prove the returned rows are identical objects to
    # what was stored (no synthesised authority) on every visible path.
    store = InMemoryStore()
    org_wide = _wf("org", None)
    scoped = _wf("scoped", "ws-1")
    await store.upsert_workflow(org_wide)
    await store.upsert_workflow(scoped)
    lib = WorkflowLibrary(store)
    assert await lib.get(T, "org", active_workspace_id="ws-1") == org_wide
    assert await lib.get(T, "scoped", active_workspace_id="ws-1") == scoped
    # workspace_id is the ONLY scoping field on the record; it is not an authority
    # field, so no execution power can ride on it.
    fields = {f.name for f in dataclasses.fields(WorkflowDefinition)}
    assert "workspace_id" in fields
    assert not (fields & {"grants", "scope", "role", "tier", "permissions"})
