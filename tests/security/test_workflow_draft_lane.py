"""Draft lane: iterate freely (low-consequence), publish deliberately (high).

The chat-first Studio's authoring cost model. A draft is a non-runnable
working copy under a reserved id prefix:

* ``control.workflow.draft.upsert`` is LOW consequence - no HITL hold - so an
  iterate loop does not pay an approval per edit;
* a draft never reaches a runnable path (get / match / trigger / execute all
  exclude it) and cannot shadow the published version on the shelf;
* ``control.workflow.publish`` is HIGH consequence and copies the draft to the
  real id, so exactly one governed approval gates going live;
* the reserved prefix cannot be smuggled through the ordinary upsert.

Every verb still flows through kernel.invoke - grant-check and audit apply to
the draft too; only the HITL gate differs by consequence.
"""

from __future__ import annotations

import pytest

from boltrig.config.control_plane import build_control_plane_adapter
from boltrig.config.control_workflows import DRAFT_ID_PREFIX, draft_id_for
from boltrig.kernel import Kernel
from boltrig.models import (
    AdapterFailure,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

T = "workflow-draft"

_DEF = {"steps": [{"id": "s", "action": "trigger.start", "params": {}}]}
_DEF_V2 = {"steps": [{"id": "s", "action": "trigger.start", "params": {}},
                     {"id": "e", "parents": ["s"], "action": "flow.end", "params": {}}]}


def _ctx() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="author",
        actor_tier="human",
        run_id="run-draft",
        extra={"principal_role": "superadmin", "principal_scope": {"all": True}},
    )


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    control = build_control_plane_adapter(store, loader=kernel.loader, registry=kernel.registry)
    control.set_workflows(WorkflowLibrary(store, kernel=kernel))
    await kernel.register_adapter(T, control)
    return kernel


async def _approved(kernel: Kernel, verb: str, params: dict) -> dict:
    with pytest.raises(PendingHuman) as held:
        await kernel.invoke("control", verb, params, _ctx())
    rid = held.value.hitl_request_id
    await kernel.hitl.answer(T, rid, "approve", "reviewer")
    return await kernel.invoke("control", verb, params, _ctx(), approval_id=rid)


@pytest.mark.security
async def test_draft_upsert_is_low_consequence_no_hold() -> None:
    kernel = await _kernel()
    # No PendingHuman: the draft applies in one call.
    out = await kernel.invoke(
        "control", "control.workflow.draft.upsert",
        {"id": "wf1", "definition": _DEF}, _ctx(),
    )
    assert out["upserted"] == "draft"
    assert out["draft_id"] == draft_id_for("wf1")


@pytest.mark.security
async def test_draft_is_not_runnable_and_does_not_shadow() -> None:
    kernel = await _kernel()
    lib = WorkflowLibrary(kernel.store, kernel=kernel)
    # A published v1 exists; then a draft (with a different body) is saved.
    await _approved(kernel, "control.workflow.upsert", {"id": "wf1", "definition": _DEF})
    await kernel.invoke(
        "control", "control.workflow.draft.upsert",
        {"id": "wf1", "definition": _DEF_V2}, _ctx(),
    )
    # The runnable shelf still resolves the PUBLISHED body, not the draft.
    got = await lib.get(T, "wf1")
    assert got is not None
    assert len(got.definition["steps"]) == 1  # the published v1, not the 2-step draft
    # The draft id itself is never runnable.
    assert await lib.get(T, draft_id_for("wf1")) is None
    with pytest.raises(LookupError):
        await lib.trigger(T, draft_id_for("wf1"), {})


@pytest.mark.security
async def test_publish_promotes_the_draft_to_runnable() -> None:
    kernel = await _kernel()
    lib = WorkflowLibrary(kernel.store, kernel=kernel)
    await kernel.invoke(
        "control", "control.workflow.draft.upsert",
        {"id": "wf2", "definition": _DEF_V2}, _ctx(),
    )
    # Not runnable before publish.
    assert await lib.get(T, "wf2") is None
    out = await _approved(kernel, "control.workflow.publish", {"id": "wf2"})
    assert out["published"] == "workflow"
    # Now runnable, carrying the draft's body.
    got = await lib.get(T, "wf2")
    assert got is not None
    assert len(got.definition["steps"]) == 2


@pytest.mark.security
async def test_publish_without_a_draft_fails_closed() -> None:
    kernel = await _kernel()
    # The record helper raises LookupError; the kernel wraps it at the governed
    # boundary as AdapterFailure - either way, publish of a missing draft fails
    # closed rather than materialising an empty workflow.
    with pytest.raises((LookupError, AdapterFailure)):
        await _approved(kernel, "control.workflow.publish", {"id": "ghost"})


@pytest.mark.security
async def test_reserved_prefix_cannot_be_smuggled_through_upsert() -> None:
    kernel = await _kernel()
    with pytest.raises((ValueError, Exception)):
        await _approved(
            kernel, "control.workflow.upsert",
            {"id": f"{DRAFT_ID_PREFIX}forged", "definition": _DEF},
        )
