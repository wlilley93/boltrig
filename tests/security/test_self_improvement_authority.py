"""Self-improvement authority rail ([2026] VJS-COUNTY 5).

The self-improvement loop (reflection, lesson recall, learned-workflow reuse,
memory.improve, and any future eval-gated promotion / selection loop) may raise
COMPETENCE but never AUTHORITY. These pins keep that rail machine-checked:

1. A workflow definition carries no authority of its own - execution authority is
   derived from the caller's InvocationContext ceiling at the dispatch chokepoint,
   never from the workflow or its provenance. So a learned/generated workflow
   structurally cannot run under a widened ceiling.
2. Promotion (learn_from_success) changes only provenance (source + origin_task),
   never the executable content.
3. The reweight verb (memory.improve) accepts no scope/grant/authority argument.

If any of these fires, the change must go back to court before it lands, per the
ruling. Reweight-only, provenance-blind authority - not trust.
"""
from __future__ import annotations

import dataclasses

import pytest

from boltrig.memory.adapter import MemoryAdapter
from boltrig.models.libraries import WorkflowDefinition, WorkflowSource
from boltrig.workflows.generator import learn_from_success

# Field names that, if they appeared on WorkflowDefinition or in the improve
# verb schema, would let provenance or a reweight carry authority. The rail
# requires NONE of them: authority lives in the caller ceiling, not the artifact.
_AUTHORITY_BEARING = {
    "grants", "grant", "scope", "scopes", "authority", "ceiling",
    "role", "roles", "tier", "permissions", "owner_scope",
}


@pytest.mark.security
@pytest.mark.invariant("SEC-84")
def test_workflow_definition_carries_no_authority_field():
    names = {f.name for f in dataclasses.fields(WorkflowDefinition)}
    leaked = names & _AUTHORITY_BEARING
    assert leaked == set(), (
        f"WorkflowDefinition gained authority-bearing field(s) {leaked}; a "
        "workflow's provenance must never carry authority (COUNTY 5). Execution "
        "authority comes only from the caller ceiling at dispatch. Route to court."
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-84")
async def test_learn_from_success_changes_only_provenance():
    wf = WorkflowDefinition(
        id="wf-1", tenant_id="t1", version="1", source=WorkflowSource.GENERATED,
        definition={"steps": [{"verb": "noop"}]}, intent_tags=["a", "b"],
    )

    saved: list[WorkflowDefinition] = []

    class _Store:
        async def upsert_workflow(self, w: WorkflowDefinition) -> None:
            saved.append(w)

    learned = await learn_from_success(_Store(), wf, "origin-task")

    # Promotion flips source to LEARNED and stamps the proving task - nothing else.
    assert learned.source == WorkflowSource.LEARNED
    for name in ("id", "tenant_id", "version", "definition", "intent_tags"):
        assert getattr(learned, name) == getattr(wf, name), (
            f"learn_from_success altered '{name}'; promotion may change provenance "
            "only, never executable content or authority (COUNTY 5)."
        )
    # The input is not mutated (a new record is built).
    assert wf.source == WorkflowSource.GENERATED
    assert saved and saved[0] is learned


@pytest.mark.security
@pytest.mark.invariant("SEC-84")
def test_memory_improve_verb_takes_no_authority_argument():
    specs = {v.verb_id: v for v in MemoryAdapter(None, None).describe()}
    improve = specs["memory.improve"]
    props = set(improve.input_schema.get("properties", {}))
    assert props == {"signal", "target"}, (
        f"memory.improve exposes inputs {props} beyond signal/target; the reweight "
        "verb must not accept scope/grant/authority (COUNTY 5)."
    )
    assert props & _AUTHORITY_BEARING == set()
