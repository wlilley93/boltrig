# Risks harvested from SPEC-09-workflows-work-skills.md

RISK: **A workflow step's `action` is an unconstrained string with no allowlist
and no relation to the author's own grants.** The authoring schema types it as a
bare string ([`boltrig/config/control_workflow_schema.py:59`](../../../boltrig/config/control_workflow_schema.py)
`"action": _STRING,`) and the only definition validations at upsert are the
loop and routine contracts
([`boltrig/config/control_workflows.py:69-70`](../../../boltrig/config/control_workflows.py)
`"require_valid_loop_contract(definition)"`). The estate's finding that a
workflow step "can dispatch ANY verb" HOLDS for Boltrig at this commit. The
second half of that finding, "on the service seat", does NOT hold: every step
dispatches under the triggering caller's own `InvocationContext`
([`boltrig/workflows/interpreter.py:145`](../../../boltrig/workflows/interpreter.py)
`"run_ctx = replace(context, run_id=rid) if rid else context"`), and every
automated entry re-derives a bound HUMAN's live grants intersected with a stored
ceiling: cron
([`boltrig/workflows/scheduler_dispatch.py:36`](../../../boltrig/workflows/scheduler_dispatch.py)
`"bounded = current.intersect(schedule.grant_ceiling)"`), webhook
([`boltrig/kernel/workflow_trigger_delivery.py:81`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`"bounded = current.intersect(trigger.grant_ceiling)"`), channel
([`:112`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`"bounded = bounded.intersect(current)"`). There is no service seat in this path.
Severity: MEDIUM. The residual exposure is a CONFUSED DEPUTY, not an escalation:
author A with narrow grants may write a step naming a verb only user B holds, and
B running the workflow executes it under B's authority. Two mitigations exist and
should be stated together with the risk: `control.workflow.upsert` is itself HIGH
consequence, and the approval for `control.workflow.trigger`/`execute` binds the
exact snapshot digest of the definition being run
([`boltrig/config/control_approval_workflows.py:108`](../../../boltrig/config/control_approval_workflows.py)
`fingerprint = {"workflow_sha256": workflow_snapshot_digest(workflow)}`), so B
approves the exact bytes. What does NOT exist is any check that the AUTHOR could
have called the verbs they wrote.

---

RISK: **A shipped library workflow cannot be persisted at all.** Running the
repository's own validator over the five files in `libraries/workflows/`
(read-only, 2026-08-24, pinned tree) returns
`('sweep', 'loop_bindings_require_one_loop_body')` for
[`libraries/workflows/lead-followup-cadence.yaml:31`](../../../libraries/workflows/lead-followup-cadence.yaml)
`"loop_bindings:"`: the bindings are declared on the `flow.loop` step itself,
which is never a member of its own body
([`boltrig/workflows/loop_contract.py:257-259`](../../../boltrig/workflows/loop_contract.py)
`'return LoopContractIssue(step_id, "loop_bindings_require_one_loop_body")'`).
`control.workflow.upsert` would raise `ValueError`. Severity: MEDIUM (the file is
shipped as an example nothing loads, so it is a documentation defect that would
become a runtime defect the moment an operator followed the README).

---

RISK: **Two of the five shipped library workflows encode semantics the
interpreter does not implement.**
[`libraries/workflows/inquiry-autoacknowledge.yaml:46`](../../../libraries/workflows/inquiry-autoacknowledge.yaml)
`"lead_id: $dedupe.output.lead_id"` and
[`libraries/workflows/lead-followup-cadence.yaml:38`](../../../libraries/workflows/lead-followup-cadence.yaml)
`"lead_id: $lead.id"` expect capability params to be reference-resolved. They are
not (section 4.2). Additionally, in `lead-followup-cadence.yaml` the steps
`next-touch` and `exit-replied` are intended as the two arms of the
`still-quiet` branch, but `next-touch` declares no `branch` key and
`exit-replied`'s parent is `replied` (a capability step that produces no branch
label), so under `branch_matches` both would run unconditionally. Severity: LOW
in production (nothing loads the file), HIGH as a source of wrong beliefs.

---

RISK: **The doctrine's claim about `learn_from_success` is false at this
commit.** [`docs/architecture/engine-components.md:615`](../../../docs/architecture/engine-components.md)
says it is "never called anywhere in the repository (not in serving code, not
even in tests; it is exported dead code)". It has a production caller at
[`boltrig/fleet/pump.py:687`](../../../boltrig/fleet/pump.py)
`"await learn_from_success(self._store, wf, item.intent)"` and four test
callers. The generator's own docstring is the accurate one
([`boltrig/workflows/generator.py:11`](../../../boltrig/workflows/generator.py)
"`learn_from_success` is gated on ``GENERATED_WORKFLOW_KEY``, which nothing
under"). Severity: LOW technically, MEDIUM as record integrity: a court was
previously told the loop was live, and the correction has now over-corrected in
the other direction.

---

RISK: **US-WFL-03 "the learning loop is closed" is proven only against a test
double.** The bound test constructs a `_WorkflowHead` stub whose result carries
`"generated_workflow": wf`
([`tests/integration/test_learning_loop.py:156`](../../../tests/integration/test_learning_loop.py)
`"\"new_work_items\": [], \"generated_workflow\": wf,"`), and `GENERATED_WORKFLOW_KEY`
is written by nothing in production (bounded: `rg -n "GENERATED_WORKFLOW_KEY"`,
2026-08-24, pinned tree, two hits, both in `boltrig/fleet/pump.py`, one the
constant and one the read). The invariant therefore cannot go red no matter what
the real department heads return. Severity: MEDIUM (a green that could not have
gone red).

---

RISK: **The doctrine undercounts the shipped workflow library.**
[`docs/architecture/engine-components.md:601`](../../../docs/architecture/engine-components.md)
says "one precreated recipe ships (`libraries/workflows/onboard-employee.yaml`,
a 4-step onboarding DAG)". Five ship. Severity: LOW.

---

RISK: **Three of the five modules in `boltrig/work/` are unreachable, including
the only status-transition guard.** `WorkItemStore`, `InternalQueueAdapter` and
the `QueueAdapter` protocol have no caller anywhere, tests included (bounded:
`rg -n "WorkItemStore|InternalQueueAdapter|QueueAdapter|write_back_discovered|score_confidence\("`
over the whole tree, 2026-08-24, pinned tree; the only non-`boltrig/work/` hits
are three documentation files). The consequence is not cosmetic: the legal
transition table and the compare-and-swap that enforces it live in
`WorkItemStore.transition`
([`boltrig/work/store.py:96`](../../../boltrig/work/store.py)
`"if not await self._store.transition_work_item_status("`), which is the ONLY
caller of `transition_work_item_status` in the tree, while the pump and five
other fleet modules write status with a plain `store.update_work_item`
([`boltrig/fleet/pump.py:484`](../../../boltrig/fleet/pump.py)
`"await self._store.update_work_item(item)"`). The repository already recorded
this ([`docs/vjs/2026-VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001-opinion.md:72`](../../../docs/vjs/2026-VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001-opinion.md)
"the pump can produce transitions that boltrig/work/store.py declares
impossible"). Severity: HIGH. A terminal state (DONE, CANCELLED) has no outgoing
edge in the declared model and no enforcement on the path that actually runs.

---

RISK: **The governed skill-authoring verb validates nothing the YAML loader
validates.** `upsert_skill_record` builds the `Skill` from raw params with no
semver check, no `check_schema` on `context_requirements` and no `extends` cycle
check ([`boltrig/config/control_operations.py:65-78`](../../../boltrig/config/control_operations.py)
`'context_requirements=params.get("context_requirements", {}),'`), while
`parse_skill` does all three
([`boltrig/skills/schema.py:113-117`](../../../boltrig/skills/schema.py)
`"Draft202012Validator.check_schema(context_requirements)"`). A control-plane
authored skill carrying an invalid schema reaches
`Draft202012Validator(schema).iter_errors(...)` at
[`boltrig/skills/shelf.py:191`](../../../boltrig/skills/shelf.py)
`"errors = [e.message for e in Draft202012Validator(schema).iter_errors(job_context)]"`
and at [`boltrig/fleet/spawn_skills.py:112`](../../../boltrig/fleet/spawn_skills.py)
`"errors = [e.message for e in Draft202012Validator(schema).iter_errors(instance)]"`,
neither of which catches `SchemaError`. Severity: MEDIUM.

---

RISK: **Two skill resolvers, two behaviours on a cyclic `extends`.** The loader
raises ([`boltrig/skills/loader.py:68-71`](../../../boltrig/skills/loader.py)
`'f"cyclic \'extends\' chain revisits \'{current}\'"'`), the spawn resolver
silently returns a partial chain
([`boltrig/fleet/spawn_skills.py:80-82`](../../../boltrig/fleet/spawn_skills.py)
`"if skill_id in seen:"`). The spawn path is the one production uses for agent
runs; the loader path is used only by the shelf's `skill.load`. Severity: MEDIUM
(a self-extending skill resolves to a DIFFERENT grant set depending on which
door you came through, and the tested behaviour is the one production does not
take).

---

RISK: **Draft rows are excluded from the runnable shelf but not from the read
surface.** `WorkflowLibrary` filters `__draft__:` in `get` and `match`
([`boltrig/workflows/library.py:162`](../../../boltrig/workflows/library.py)
`"if wf.id == id and not _is_draft(wf) and _visible_in_workspace(wf, active_workspace_id):"`),
but `GET /v1/workflows` filters only on workspace
([`boltrig/kernel/platform_routes/workflows.py:129-130`](../../../boltrig/kernel/platform_routes/workflows.py)
`"if _visible(workflow, p.active_workspace_id)"`), and `GET /v1/workflows/{wf_id}`
will return a draft's full `definition` when addressed by its draft id. Drafts
are LOW consequence to write, so unapproved definition content is visible on an
authenticated read surface. Severity: LOW (no authority is conferred; drafts are
never runnable) but it is a real divergence between two views of the same shelf.

---

RISK: **The reserved draft prefix is a duplicated string literal.**
[`boltrig/config/control_workflows.py:40`](../../../boltrig/config/control_workflows.py)
`DRAFT_ID_PREFIX = "__draft__:"` and
[`boltrig/workflows/library.py:53`](../../../boltrig/workflows/library.py)
`_DRAFT_ID_PREFIX = "__draft__:"`. The duplication is deliberate and explained
(a layering rule forbids importing config into the workflows package), but two
copies of a security-relevant constant is one copy and a future disagreement.
Severity: LOW.

---

RISK: **`GET /v1/workflows` can be 500'd by one malformed stored routine.**
`_routine` calls `routine_spec`, which RAISES on any contract violation
([`boltrig/kernel/platform_routes/workflows.py:49`](../../../boltrig/kernel/platform_routes/workflows.py)
`"spec = routine_spec(workflow.definition)"` and
[`boltrig/workflows/routine_contract.py:33`](../../../boltrig/workflows/routine_contract.py)
`raise ValueError("routine must be an object")`), and the list route maps it
over every workflow. Both authoring verbs validate, so the only ways in are a
direct `store.upsert_workflow` (which `learn_from_success` and the generator both
use, [`boltrig/workflows/generator.py:116`](../../../boltrig/workflows/generator.py)
`"await store.upsert_workflow(learned)"`) or a pre-validation row. Severity: LOW,
but it is a projection that raises rather than degrading.

---

RISK: **The workflow scheduler serves exactly one tenant.**
`run_workflow_scheduler_forever` takes a single `tenant_id`
([`boltrig/workflows/scheduler_loop.py:63-66`](../../../boltrig/workflows/scheduler_loop.py)
`"tenant_id: str,"`) and the worker passes the manifest tenant
([`boltrig/api/worker.py:287`](../../../boltrig/api/worker.py)
`"tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT"`).
On a multi-tenant deployment every other tenant's cron schedule accumulates
`next_due_at` in the past and never fires, and its `observed_status` is never
updated, so it does not even read as degraded. Severity: MEDIUM, contingent on
whether multi-tenant single-worker deployments exist (see OPEN QUESTIONS).

---

RISK: **A cron occurrence bypasses the trigger verb's HITL gate.** The scheduled
path calls `WorkflowLibrary.trigger` directly
([`boltrig/workflows/scheduler_dispatch.py:170`](../../../boltrig/workflows/scheduler_dispatch.py)
`"descriptor = await workflows.trigger("`) rather than
`kernel.invoke("control", "control.workflow.trigger", ...)`, so the HIGH
consequence classification of that verb
([`boltrig/config/control_workflow_specs.py:113-118`](../../../boltrig/config/control_workflow_specs.py)
`'"control.workflow.trigger",'` under the default `consequence="high"`) never
applies per occurrence. Only the grant is checked
([`:38`](../../../boltrig/workflows/scheduler_dispatch.py)
`'return None, "scheduling_trigger_grant_revoked"'`). The webhook path does NOT
bypass it. This is defensible design (the schedule creation was itself approved,
and each STEP is still consequence-gated at the chokepoint), but the asymmetry
between the two automated entries is undocumented in code. Severity: LOW-MEDIUM.

---

RISK: **The queued context envelope carries grants verbatim and is not
re-derived at execution.** `context_from_envelope` reconstructs the `GrantSet`
from the payload
([`boltrig/models/context.py:91`](../../../boltrig/models/context.py)
`"grants=GrantSet.of(list(grants.get(\"allow\") or []), list(grants.get(\"deny\") or []))"`),
so a workflow queued before a grant revocation still executes its steps with the
pre-revocation grant set when the worker picks it up. The cron and webhook paths
re-derive at ENQUEUE time; nothing re-derives at RUN time. Severity: MEDIUM,
bounded by how long a task can sit queued.

---

RISK: **A definition has no step-count bound and the interpreter has no
recursion depth counter.** `WORKFLOW_DEFINITION_SCHEMA` puts no `maxItems` on
`steps` ([`boltrig/config/control_workflow_schema.py:79`](../../../boltrig/config/control_workflow_schema.py)
`"steps": {"type": "array", "items": _STEP},`) and the interpreter never
touches `context.depth`. Loop fan-out is bounded (100 items, 10 concurrent,
nested loops refused), but a flat 10 000-step definition dispatches 10 000 times
in one walk. A workflow step naming `control.workflow.execute` is stopped only by
that verb's HIGH consequence gate, not by a depth counter. Severity: LOW-MEDIUM.

---

RISK: **A capability step whose adapter output happens to contain a `branch` key
silently gates its descendants.** `_record_success` leaves an author- or
adapter-produced `branch` key alone
([`boltrig/workflows/step_execution.py:215-219`](../../../boltrig/workflows/step_execution.py)
`"# (An author-produced ``branch`` key is left alone.)"`) and `branch_matches`
reads any parent's `output["branch"]` regardless of the parent's action
([`boltrig/workflows/control_flow.py:282`](../../../boltrig/workflows/control_flow.py)
`produced = pout.get("branch")`). Severity: LOW.

---

RISK: **The DAG-parity semantics are unbound by any invariant.** 28 tests in
`tests/unit/test_workflow_parity.py` carry no `@pytest.mark.invariant` (bounded:
`rg -n "pytest.mark.invariant" tests/unit/test_workflow_parity.py`, 2026-08-24,
pinned tree, zero hits), so `make invariants` has nothing to say if
`on_error`, retry, the OR-join, parallel iteration or the approval branch handles
regress. Per the authoring contract, an unbound correctness requirement is itself
a finding. Severity: MEDIUM.

---

RISK: **`schemas/emotion/1.0.0/phenotype.schema.json` is enforced by nothing.**
No code loads it and no test asserts the published phenotype conforms to it
(bounded: `rg -n "phenotype.schema"` over the tree, 2026-08-24, pinned tree,
zero hits outside the file itself). The other two schema contracts have gates
(`make codex-protocol`, `tests/test_persona_layer.py`). Severity: LOW.

---

RISK: **The story ids this area's docstrings cite are not invariants.**
`US-SKL-01/02/03` (skill parse, inheritance merge, locale selection),
`US-WRK-01/02`, `FR-WRK-02` (normalisation, confidence, convergent mode) and
`US-EXE-04` (the discovery cap) appear throughout
`boltrig/skills/` and `boltrig/work/` docstrings but none of them is a key in
`tests/invariants.yaml` (bounded: parsed every top-level key of
`tests/invariants.yaml`, 421 entries, 2026-08-24, pinned tree; all eight are
absent). A reader who takes a docstring story id as a binding is wrong.
Severity: LOW-MEDIUM.

---

RISK: **`select_locale` and the whole locale-variant mechanism are unreachable
and unpopulated.** No caller anywhere (bounded: `rg -n "select_locale"`,
2026-08-24, pinned tree, hits only in `boltrig/skills/loader.py`,
`boltrig/skills/__init__.py` and two `docs/refactoring/` allow-lists) and no
`base@locale` file exists on disk (`find libraries/skills -name '*@*'`, zero
results). The module docstring nonetheless presents locale selection as one of
its three jobs ([`boltrig/skills/loader.py:11`](../../../boltrig/skills/loader.py)
`"* :func:`select_locale` picks a localised variant of a skill, falling back to"`).
Severity: LOW.

---
