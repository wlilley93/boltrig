---
area: 09 Workflows, work items, skills and the YAML libraries
id-block: BT-REQ-0900 to BT-REQ-0999
referent-commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec agent, area 09
date: 2026-08-24
---

## Bound of this reading

Every Python file in scope was read end to end: `boltrig/workflows/` (17 files,
2 916 lines), `boltrig/work/` (5 files, 396 lines), `boltrig/skills/`
(4 files, 535 lines), `boltrig/kernel/channel_workflow_trigger_bridge.py`
(42 lines). Every file under `libraries/` (40 files) and `schemas/` (4 files)
was opened; the 471 KB `schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json`
was sampled at its manifest and pin-checker only, not read in full.

Adjacent modules were read where they own a contract this area depends on and
are cited as such, not specified here: `boltrig/fleet/hatchet_app.py`
(task bodies), `boltrig/fleet/routine_run.py`, `boltrig/fleet/spawn.py` and
`boltrig/fleet/spawn_skills.py` (the second skill resolver),
`boltrig/config/control_workflow*.py` and `control_workflows.py` (the authoring
verbs), `boltrig/kernel/workflow_trigger_delivery.py`,
`boltrig/kernel/platform_routes/workflows.py`, `boltrig/models/libraries.py`,
`boltrig/models/grants.py`, `boltrig/models/context.py`, `migrations/baseline.sql`
and migrations 0005, 0014, 0020, 0050, 0055, 0057, 0075.

One measurement was taken by importing the repository's own validator in a
read-only Python process (no tests, no services, nothing written): the five
shipped `libraries/workflows/*.yaml` definitions were run through
`boltrig.workflows.loop_contract.validate_loop_contract`. Result recorded under
RISKS. Nothing else was executed.

Absence claims in this file always name their bound inline.

---

## 2. Purpose

This area is Boltrig's "behaviour is data" claim made concrete. A workflow is a
JSON DAG stored as a row, walked at run time by a generic interpreter that
dispatches every step through the kernel chokepoint, so new orchestration is
authored rather than coded. A skill is a YAML document carrying a prompt
fragment, a wish-list of verb grants and a JSON Schema of what the job must
supply; the work library is the single translation from any raw source payload
into the one normalised `WorkItem` shape, and `libraries/` plus `schemas/` are
the on-disk data these three subsystems read.

## 3. Boundaries

**Owns.** The step model and its execution semantics (`boltrig/workflows/`),
the loop and routine authoring contracts, the cron scheduler and its occurrence
lifecycle, the skill parse/resolve/shelf path (`boltrig/skills/`), work-item
normalisation and channel provenance (`boltrig/work/`), and the shipped data
under `libraries/`.

**Does not own, and must not reimplement.** Authority. The interpreter never
consults a grant set, never mints a context, and never decides consequence: it
calls `kernel.invoke` and records what comes back
([`boltrig/workflows/step_execution.py:284`](../../../boltrig/workflows/step_execution.py)
`"return await kernel.invoke("`). Durability is likewise not owned here: the
executor boundary and the checkpoint store are injected seams
([`boltrig/workflows/interpreter.py:127`](../../../boltrig/workflows/interpreter.py)
`"store: Any | None = None,"`).

**Forbidden imports.** `boltrig/workflows/` imports `boltrig.models` and its own
package only; the library facade deliberately keeps config out:
[`boltrig/workflows/library.py:52`](../../../boltrig/workflows/library.py)
`"to avoid importing config into the workflows package (layering)"`. That is why
the reserved draft prefix is a duplicated literal rather than a shared import
(see RISKS). `boltrig/skills/` states the same rule:
[`boltrig/skills/__init__.py:3`](../../../boltrig/skills/__init__.py)
`"Skills are data, not code (P1)"`, and the fleet spawner is the consumer, not
the other way round. `boltrig/work/` depends on `boltrig.models` and
`boltrig.text_envelope` only.

**The one-chokepoint carve-out.** Control-plane nouns are handled inside the
interpreter and never dispatched. The code states and justifies the carve-out:
[`boltrig/workflows/control_flow.py:19`](../../../boltrig/workflows/control_flow.py)
`"that doctrine governs EXTERNAL actions and capability"`. The carve-out set is
closed: [`boltrig/workflows/control_flow.py:40`](../../../boltrig/workflows/control_flow.py)
`CONTROL_NOUNS = frozenset({"trigger", "flow", "code"})`.

---

## 4. Objects and contracts

### 4.1 `WorkflowDefinition`

The stored row. Fields:
[`boltrig/models/libraries.py:164-181`](../../../boltrig/models/libraries.py)
`"definition: dict[str, Any]  # Hatchet workflow spec"`.

| field | type | meaning |
| --- | --- | --- |
| `id` | str | workflow id; `__draft__:` prefix is kernel-reserved |
| `tenant_id` | str | tenant fence |
| `version` | str | free-form; the store returns the latest version per id |
| `source` | enum | `precreated` / `generated` / `learned`, kernel-owned |
| `definition` | dict | the DAG plus reserved keys (below) |
| `intent_tags` | list[str] | matching hints; used only by the unwired `match` |
| `origin_task` | str or None | set by `learn_from_success` |
| `workspace_id` | str or None | NULL means org-wide |

Reserved keys inside `definition`:

- `steps` - the DAG (below).
- `_boltrig_lifecycle` - `{status: active|archived, schedule: ...}`, written by
  the lifecycle verbs, read by every runnable seam
  ([`boltrig/workflows/library.py:46`](../../../boltrig/workflows/library.py)
  `lifecycle.get("status") == "archived"`).
- `schedule` - the legacy inline cron spec, superseded by the
  `workflow_schedules` row but still projected
  ([`boltrig/kernel/platform_routes/workflows.py:21`](../../../boltrig/kernel/platform_routes/workflows.py)
  `legacy_schedule = raw.get("schedule", workflow.definition.get("schedule"))`).
- `_boltrig_routine` - the v1 conversational routine contract (section 4.5).
- `name`, `version`, `on`, `inputs`, `synthesis` - written by the generator and
  by the shipped YAML; read by nothing at run time (bounded:
  `rg -n '"on"|\["on"\]|definition\["inputs"\]' boltrig/`, 2026-08-24, pinned
  tree, no reader found).

### 4.2 The step

Authored shape, from the closed schema
[`boltrig/config/control_workflow_schema.py:55-75`](../../../boltrig/config/control_workflow_schema.py)
`'"required": ["id", "action"],'`:

| key | type | required | semantics |
| --- | --- | --- | --- |
| `id` | string | yes | unique within the definition; `<x>__<n>` is reserved |
| `action` | string | yes | `<noun>.<verb>`; an unconstrained string |
| `parents` | string[] | no | edges; a missing parent makes the step unrunnable |
| `params` | object | no | verb params, passed VERBATIM |
| `with` | object | no | alias for `params`, lower precedence |
| `branch` | string | no | the branch label this step requires |
| `loop_bindings` | object | no | max 32 entries, `item` or `index` only |
| `on_error` | enum | no | `fail` (default) / `branch` / `default` |
| `default_output` | object | no | substituted under `on_error: default` |
| `retry` | object | no | `{max: 0..5, interval_ms: 0..60000}` |
| `description`, `name` | string | no | authored prose, never read at run time |

`additionalProperties` is `True` on the step and on the definition
([`boltrig/config/control_workflow_schema.py:74`](../../../boltrig/config/control_workflow_schema.py)
`"additionalProperties": True,`), so an author may store any extra key.

Param precedence is a single function shared by the interpreter and the loop
validator: non-empty `params`, else `with`, else `params`
([`boltrig/workflows/loop_contract.py:60-70`](../../../boltrig/workflows/loop_contract.py)
`"Mirror interpreter precedence: non-empty params, otherwise with, then params."`).

**The load-bearing contract fact: capability step params are NOT resolved.**
`resolve_ref` is called from three places only, all inside `control_flow.py`:
branch predicates, multi-case conditions and `items_from` (bounded:
`rg -n "resolve_ref" --type py`, 2026-08-24, pinned tree, 7 hits, all in
`boltrig/workflows/control_flow.py`). A capability step's `params` dict travels
unchanged from the stored definition into `kernel.invoke`
([`boltrig/workflows/interpreter.py:352-357`](../../../boltrig/workflows/interpreter.py)
`"params=params, approval_id=approval_id,"`). A step authored with
`params: {lead_id: $dedupe.output.lead_id}` therefore dispatches the literal
string `"$dedupe.output.lead_id"`. The only declarative way to move data into a
step is `loop_bindings`, which replaces a whole top-level param value. The
shipped YAML says so in terms:
[`libraries/workflows/sleep-distillation-craft.yaml:3`](../../../libraries/workflows/sleep-distillation-craft.yaml)
`"step outputs cannot thread between workflow"`.

### 4.3 Control-plane step kinds

| action | effect | recorded output |
| --- | --- | --- |
| `trigger.start` | no-op entry | `{entry: true, inputs: {...}}` |
| `flow.end` | terminal marker | `{terminal: true}` |
| `flow.branch` | evaluates a predicate or case list | `{branch: "<label>"}` |
| `flow.loop` | expands a bounded body per item | `{items, count, items_digest[, skipped_overflow]}` |
| `code.run` | recognised, NEVER executed | `{executed: false, reason, script_len}` |
| any other `trigger.*`/`flow.*`/`code.*` | `skipped` | `{reason: "unknown control action ..."}` |

Cited: [`boltrig/workflows/control_flow.py:212-265`](../../../boltrig/workflows/control_flow.py)
`'"reason": "code execution disabled (no sandbox configured)"'`.

The declarative operator set is closed and fail-closed on anything else:
`eq, ne, exists, not_exists, is_null, not_null, empty, not_empty, gt, lt, gte,
lte, in, not_in, contains, not_contains, starts_with, ends_with`
([`boltrig/workflows/control_flow.py:87-126`](../../../boltrig/workflows/control_flow.py)
`"Evaluate a declarative comparison. Unknown ops are false (fail-closed)."`).
A `TypeError` from an ordering comparison is caught and returns false
(same function, `"except TypeError:"` at line 124).

Two branch shapes are supported. Legacy single predicate yields `"true"` or
`"false"`; multi-case yields the first matching case's label in declaration
order, else `default_label`, else `"false"`
([`boltrig/workflows/control_flow.py:172-197`](../../../boltrig/workflows/control_flow.py)
`'return default if isinstance(default, str) and default else "false"'`).
A case with no `conditions` matches unconditionally (the else arm); a case with
a non-string or empty label never matches.

### 4.4 The loop contract

A closed data contract validated at authoring time and again at run start.
Constants: [`boltrig/models/libraries.py:157-160`](../../../boltrig/models/libraries.py)
`"WORKFLOW_LOOP_MAX_ITEMS = 100"`, `WORKFLOW_LOOP_MAX_BINDINGS = 32`,
`WORKFLOW_LOOP_MAX_BOUND_BYTES = 256 * 1024`,
`WORKFLOW_LOOP_BINDING_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$"`.
Parallel window cap: [`boltrig/workflows/loop_execution.py:164`](../../../boltrig/workflows/loop_execution.py)
`"WORKFLOW_LOOP_MAX_PARALLEL = 10"`.

The complete refusal vocabulary from `validate_loop_contract`
([`boltrig/workflows/loop_contract.py:151-272`](../../../boltrig/workflows/loop_contract.py)):

`loop_steps_must_be_array`, `loop_step_must_be_object`, `loop_step_id_invalid`,
`loop_parents_invalid`, `loop_step_id_reserved`, `nested_loop_not_supported`,
`loop_params_must_be_object`, `loop_requires_one_item_source`,
`loop_on_item_error_invalid`, `loop_parallel_invalid`,
`loop_items_must_be_array`, `loop_items_not_json`, `loop_items_too_large`,
`loop_items_from_invalid`, `loop_items_from_must_reference_ancestor`,
`loop_bindings_must_be_object`, `loop_bindings_require_one_loop_body`,
`loop_binding_limit_exceeded`, `loop_binding_params_must_be_object`,
`loop_binding_target_invalid`, `loop_binding_source_invalid`,
`loop_binding_target_missing`.

The body of a loop is its maximal self-contained descendant sub-graph: a step
joins the body only when EVERY parent is the loop step or already in the body
([`boltrig/workflows/loop_contract.py:93`](../../../boltrig/workflows/loop_contract.py)
`"if all(parent == loop_id or parent in body for parent in parents):"`).
Expansion clones the body once per item, renames each clone `<id>__<k>` and
rewires intra-body parents to the same iteration
([`boltrig/workflows/control_flow.py:303-336`](../../../boltrig/workflows/control_flow.py)
`'clone["id"] = f"{sid}__{k}"'`).

### 4.5 The routine contract (`_boltrig_routine`)

Closed v1 shape, `additionalProperties: False` at the schema and re-checked in
code: [`boltrig/workflows/routine_contract.py:28-58`](../../../boltrig/workflows/routine_contract.py)
`'raise ValueError("v1 conversational routines cannot contain graph steps")'`.

| field | rule |
| --- | --- |
| `version` | must equal `1` |
| `name` | 1..120 chars after strip |
| `goal` | 1..4000 chars after strip |
| `companion_id` | exactly `familiar` or `jarvis` |
| `notify.completion` | strict bool, default `True` |
| `steps` | must be absent or an EMPTY list |

`routine_spec` is both the parser and the validator; `require_valid_routine_contract`
is just a call to it ([`boltrig/workflows/routine_contract.py:61-62`](../../../boltrig/workflows/routine_contract.py)
`"def require_valid_routine_contract(definition: dict[str, Any]) -> None:"`).

### 4.6 The snapshot

`build_workflow_snapshot` freezes eight fields into canonical JSON
(`sort_keys`, `separators=(",",":")`, `allow_nan=False`), round-trips them so
later mutation of the in-memory row cannot change what was approved, and returns
`{schema: 1, workflow: <frozen>, sha256: <hex>}`
([`boltrig/workflows/snapshot.py:45-65`](../../../boltrig/workflows/snapshot.py)
`"Freeze the exact approved definition into a self-verifying JSON document."`).
`workflow_from_snapshot` verifies the envelope shape, the schema version, the
digest with `hmac.compare_digest`, tenant/id identity and workspace scope, and
raises `WorkflowSnapshotError` on any drift
([`boltrig/workflows/snapshot.py:107`](../../../boltrig/workflows/snapshot.py)
`"if not hmac.compare_digest(digest, expected):"`).

### 4.7 `Skill`

[`boltrig/models/libraries.py:63-79`](../../../boltrig/models/libraries.py)
`'tool_grants: list[str] = field(default_factory=list)  # ["jira.read", "jira.write"]'`.
Fields: `id`, `tenant_id`, `version` (semver at YAML load), `prompt_fragment`,
`tool_grants`, `context_requirements` (a JSON Schema), `extends`, `locale`,
`description` (the shelf label), `is_active` (archival).

A skill's `tool_grants` are a REQUEST, never an award. The spawner computes
`GrantSet.of(allow=skill grants).intersect(caller grants)` and then intersects
any explicit ceiling
([`boltrig/fleet/spawn.py:169-173`](../../../boltrig/fleet/spawn.py)
`"child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect("`).
`GrantSet.intersect` is deny-union, allow-intersection, with terminal-wildcard
narrowing ([`boltrig/models/grants.py:110-143`](../../../boltrig/models/grants.py)
`"Tenant ∩ skill grants. Allows must be permitted by BOTH; denies union."`).
That is the whole of "how a skill is granted": there is no other award path.

### 4.8 `WorkItem` intake objects

`normalise` is the single translation point. It shallow-copies the raw payload,
extracts an intent from an alias list, a source id, six named constraint
facets, scores confidence and derives convergent/divergent
([`boltrig/work/normalise.py:58-83`](../../../boltrig/work/normalise.py)
`"raw = dict(raw or {})"`).

Confidence weights sum to 1.0 and are a deterministic facet heuristic:
title 0.30, description 0.25, acceptance criteria 0.20, assignee 0.15,
deadline 0.10 ([`boltrig/work/queue.py:20-26`](../../../boltrig/work/queue.py)
`'(0.30, ("title", "summary", "name", "subject")),'`). Convergent threshold
0.7 ([`boltrig/work/queue.py:28`](../../../boltrig/work/queue.py)
`"CONVERGENT_THRESHOLD = 0.7"`).

Channel provenance is a kernel-authored reserved constraint. Four fields are
derived after authentication and can never come from the provider payload;
provider identifiers are bounded to 512 chars and kept private; the public
projection deliberately omits them
([`boltrig/work/channel_provenance.py:64-85`](../../../boltrig/work/channel_provenance.py)
`"item.constraints.pop(CHANNEL_MESSAGE_PROVENANCE_KEY, None)"` and
[`:95-125`](../../../boltrig/work/channel_provenance.py)
`"Return the safe UI/API projection; never expose raw provider identities."`).

---

## 5. Control flow

### 5.1 Authoring a workflow (the write path)

1. `control.workflow.upsert` (HIGH consequence, so the HITL gate holds it) or
   `control.workflow.draft.upsert` (LOW, applies in one call) reaches
   `execute_workflow_control`
   ([`boltrig/config/control_workflow_specs.py:24`](../../../boltrig/config/control_workflow_specs.py)
   `consequence: str = "high",` and
   [`:61`](../../../boltrig/config/control_workflow_specs.py) `'consequence="low",'`).
   **Failure branch:** an ungranted caller is refused at the chokepoint; a
   high-consequence call with no approval raises `PendingHuman`.
2. For the mutable actions the approval fingerprint is re-checked against live
   resource state before the write
   ([`boltrig/config/control_approval.py:329-338`](../../../boltrig/config/control_approval.py)
   `'raise PermissionError("exact approval evidence is missing")'`). The workflow
   fingerprint is the snapshot digest
   ([`boltrig/config/control_approval_workflows.py:108`](../../../boltrig/config/control_approval_workflows.py)
   `fingerprint = {"workflow_sha256": workflow_snapshot_digest(workflow)}`).
   **Failure branch:** `approved resource changed before execution`.
3. `upsert_workflow_record` refuses a caller-supplied `source`, refuses the
   reserved draft prefix, then runs exactly two definition validations:
   the loop contract and the routine contract
   ([`boltrig/config/control_workflows.py:69-70`](../../../boltrig/config/control_workflows.py)
   `"require_valid_loop_contract(definition)"`).
   **Failure branch:** `ValueError("invalid loop contract: <reason>")` or the
   routine contract's own `ValueError`. **There is no validation of `action`
   against the verb registry, and none of the author's own grants.**
4. Lifecycle and schedule keys are carried forward from the existing row so an
   edit cannot silently unschedule or unarchive
   ([`boltrig/config/control_workflows.py:72-76`](../../../boltrig/config/control_workflows.py)
   `'definition.setdefault("_boltrig_lifecycle", lifecycle)'`).
5. `store.upsert_workflow` writes `(tenant_id, id, version)`.

`control.workflow.publish` reads `__draft__:<id>` and re-enters step 3 through
the ordinary upsert, inheriting its guards
([`boltrig/config/control_workflows.py:150`](../../../boltrig/config/control_workflows.py)
`"return await upsert_workflow_record("`).

### 5.2 Running a workflow (the interpreter walk)

`run_workflow_definition(kernel, wf, inputs, context, executor=, run_id=, store=)`.

1. Resolve `rid` from the explicit argument, then `context.run_id`, then
   `executor.new_run_id()`; rebind the context to it so steps, events and audit
   share one id ([`boltrig/workflows/interpreter.py:143-145`](../../../boltrig/workflows/interpreter.py)
   `"run_ctx = replace(context, run_id=rid) if rid else context"`).
2. Bind a fail-safe event emitter to `kernel.events`; every publish is wrapped
   in a bare `except Exception: pass`
   ([`boltrig/workflows/interpreter.py:148-156`](../../../boltrig/workflows/interpreter.py)
   `'relay.publish(run_ctx.tenant_id, rid, {"type": "workflow_step", **event})'`).
   **Failure branch:** a broken relay cannot fail a run (P9).
3. If a store seam is wired and `rid` is set, load prior checkpoints keyed by
   step ([`boltrig/workflows/interpreter.py:163`](../../../boltrig/workflows/interpreter.py)
   `"prior = {c.step: c for c in await store.list_checkpoints(wf.tenant_id, rid)}"`).
   Checkpoint keys are workflow-scoped `f"{wf.id}:{step}"`
   ([`:170`](../../../boltrig/workflows/interpreter.py) `'return f"{wf.id}:{step}"'`)
   because the underlying table keys only `(tenant, run_id, step)`
   ([`migrations/versions/0005_durable_delegation.py:38`](../../../migrations/versions/0005_durable_delegation.py)
   `"PRIMARY KEY (tenant_id, run_id, step)"`).
4. Re-validate the loop contract. **Failure branch:** the whole run returns a
   value-free `failed` record with the offending step marked and every other
   step `invalid_loop_contract`, before any dispatch
   ([`boltrig/workflows/loop_execution.py:20-65`](../../../boltrig/workflows/loop_execution.py)
   `"Build and emit a value-free failure receipt, or return ``None``."`).
5. Topologically order the steps (Kahn, stable among independents). Steps in a
   cycle or naming a missing parent come back separately and are recorded
   `skipped` / `missing_parent_or_cycle`, and they enter `failed`, so the run
   fails ([`boltrig/workflows/interpreter.py:81-110`](../../../boltrig/workflows/interpreter.py)
   `"indegree[s[\"id\"]] += 1  # missing parent => never satisfiable"`).
6. Seed `results["inputs"]` with the run inputs, but only when no authored step
   claims the id `inputs`
   ([`boltrig/workflows/interpreter.py:187`](../../../boltrig/workflows/interpreter.py)
   `if not any(s.get("id") == "inputs" for s in steps):`).
7. Walk the ordered list. Per step, in this exact order:
   a. **Checkpoint replay.** A prior `ok` checkpoint replays the recorded output
      and is never re-dispatched; a replayed `flow.loop` re-resolves its items
      and re-expands only when the recorded output matches exactly, else the
      step fails `loop_replay_mismatch`
      ([`boltrig/workflows/loop_execution.py:114-125`](../../../boltrig/workflows/loop_execution.py)
      `'"reason": "loop_replay_mismatch",'`).
   b. **Failure lineage.** Any parent in `failed_or_skipped` skips the child
      `parent_failed` and poisons its own descendants
      ([`boltrig/workflows/interpreter.py:257`](../../../boltrig/workflows/interpreter.py)
      `"if any(p in failed_or_skipped for p in parents):"`).
   c. **OR-join.** The child skips `parents_skipped` only when EVERY parent was
      benign-skipped ([`:268`](../../../boltrig/workflows/interpreter.py)
      `"if parents and all(p in benign_skipped for p in parents):"`).
   d. **Mixed loop parent.** A step with a parent inside an expanded loop body
      but outside the body itself is skipped `mixed_loop_parent` rather than
      dispatched with unresolvable refs
      ([`:280`](../../../boltrig/workflows/interpreter.py)
      `"if any(p in loops.original_body_ids for p in step.get(\"parents\", []) or []):"`).
   e. **Branch gate.** A step declaring `branch` must match the label of every
      parent that produced one; a mismatch is a BENIGN skip
      ([`boltrig/workflows/control_flow.py:268-285`](../../../boltrig/workflows/control_flow.py)
      `'return False, "branch_mismatch"'`).
   f. **Control step** (noun in `CONTROL_NOUNS`): resolved locally, checkpointed
      `ok` on success, and on a successful `flow.loop` the body is expanded into
      the walk in place. A parallel-declared, capability-only body then runs its
      iterations through a semaphore window instead of inline
      ([`boltrig/workflows/interpreter.py:329-338`](../../../boltrig/workflows/interpreter.py)
      `"ordered, par_paused, par_stop = await run_parallel_block("`).
      **Failure branch:** a non-`ok` control outcome (only `flow.loop` with
      unusable items, or an unknown control verb) adds the step to both
      `failed_or_skipped` and `failed`.
   g. **Capability step:** `run_capability_step` (section 5.3).
8. Aggregate loop clones back onto their original step ids, absorbing item
   errors under `continue`/`drop`
   ([`boltrig/workflows/control_flow.py:345-397`](../../../boltrig/workflows/control_flow.py)
   `'"Honesty (US-FLT-07 posture): absorbed errors are visible in the"'`).
9. Overall status: `paused` if any step paused, else `failed` if `failed` is
   non-empty, else `completed`. Emit the terminal `workflow_run` marker and
   return the record with `run_id, workflow_id, tenant_id, version, status,
   exceptions_count, steps[], inputs`
   ([`boltrig/workflows/interpreter.py:374-393`](../../../boltrig/workflows/interpreter.py)
   `'"exceptions_count": len(exceptions) + absorbed_item_errors,'`).

### 5.3 One capability step

1. If resuming a paused step, pre-check the checkpointed HITL request read-only.
   A rejected or timed-out decision resolves through the step's error strategy
   as `approval_rejected` / `approval_timeout` rather than re-dispatching into a
   gate that would ask forever. Anything unreadable, pending, consumed or
   approvingly answered resolves `resume` (fail-closed to the kernel's gate)
   ([`boltrig/workflows/step_execution.py:48-88`](../../../boltrig/workflows/step_execution.py)
   `"Fail-closed: anything unreadable, pending, consumed, or approvingly"`).
2. Mint the per-step idempotency key `workflow:<wf>:<run>:<step>` when
   checkpointing is on and the verb is not idempotency-disabled
   ([`:127`](../../../boltrig/workflows/step_execution.py)
   `'return f"workflow:{wf.id}:{rid}:{step_id}"'`).
3. Read the clamped retry policy: `max` capped at 5, `interval_ms` capped at
   60 000, non-numeric values yielding `(0, 0.0)`
   ([`:93-103`](../../../boltrig/workflows/step_execution.py)
   `"except (TypeError, ValueError):"`).
4. Dispatch, inside `executor.run_step(f"workflow:{wf.id}:{step_id}", ...)` when
   an executor is wired, inline otherwise
   ([`:344-351`](../../../boltrig/workflows/step_execution.py)
   `'boundary = f"workflow:{wf.id}:{step_id}"'`).
   - **Success:** record `ok`; under `on_error: branch` stamp `branch: "success"`
     unless the adapter already produced a `branch` key; checkpoint `ok`.
   - **`IdempotencyConflict` on a keyed dispatch:** fall back to exactly one
     keyless invoke ([`:288-295`](../../../boltrig/workflows/step_execution.py)
     `"except IdempotencyConflict:"`).
   - **`BoltrigError` with reason in `{pending_human, approval_required}`:**
     record `paused` with the HITL request id, checkpoint `paused`, stop the
     walk. Never retried, never absorbed
     ([`:356-359`](../../../boltrig/workflows/step_execution.py)
     `"if reason in PAUSE_REASONS:"`).
   - **Any other `BoltrigError`:** status `failed`, reason = the error's reason.
   - **Any other `Exception`:** status `error`, reason = the exception class
     name; the fleet is never crashed by an adapter bug
     ([`:361`](../../../boltrig/workflows/step_execution.py)
     `"except Exception as exc:  # an adapter bug must not crash the fleet (P9)"`).
5. Retry while `attempt < max_retries`, sleeping `interval_ms`, emitting a
   `running` event with reason `retry_<n>`.
6. On exhaustion apply the strategy: `fail` poisons descendants; `branch` writes
   `{error_message, error_type, branch: "fail"}`; `default` writes
   `default_output` with the two error keys overriding same-named defaults.
   Absorbed failures record step status `exception`, append to `exceptions`, and
   are checkpointed `ok` so a resume replays the absorption
   ([`:158-170`](../../../boltrig/workflows/step_execution.py)
   `'output = {**base, **error_keys}'`).

### 5.4 Trigger (the durable enqueue path)

1. `WorkflowLibrary.trigger` resolves the workflow through `get`, which
   excludes drafts and enforces workspace visibility
   ([`boltrig/workflows/library.py:162`](../../../boltrig/workflows/library.py)
   `"if wf.id == id and not _is_draft(wf) and _visible_in_workspace(wf, active_workspace_id):"`).
   **Failure branch:** `LookupError`.
2. Archived fails closed with `PermissionError("workflow_archived")`
   ([`:241`](../../../boltrig/workflows/library.py) `"if _archived(wf):"`).
3. Build the snapshot; if the caller supplied `expected_workflow_sha256` and it
   differs, raise `RuntimeError("workflow_snapshot_changed")`
   ([`:66-70`](../../../boltrig/workflows/library.py)
   `'raise RuntimeError("workflow_snapshot_changed")'`).
4. If the definition carries `_boltrig_routine`, require an authenticated
   context and pre-create the deterministic owner-scoped conversation
   `routine-<sha256(run_id)[:32]>`, then read it back and verify all seven
   binding fields
   ([`:87-121`](../../../boltrig/workflows/library.py)
   `'raise PermissionError("routine_conversation_binding_mismatch")'`).
   **Failure branch:** `routine_requires_authenticated_context`,
   `routine_requires_authenticated_owner`, or the binding mismatch.
5. Build the immutable run descriptor (`run_id, tenant_id, workflow_id, version,
   workflow_sha256, source, engine, durable, status: queued, inputs, queued_at`).
6. With an executor AND a context, enqueue `TASK_WORKFLOW_RUN` carrying the
   snapshot and the serialised context envelope
   ([`:284`](../../../boltrig/workflows/library.py)
   `'"ctx_envelope": context_to_envelope(queued_context),'`). With an executor
   and NO context, only a bookkeeping `run_step` is recorded and nothing runs.
7. The task body rebuilds the context, fences payload tenant against envelope
   tenant, restores the workflow from the verified snapshot, and either runs the
   routine conversation or the interpreter with BOTH the executor and
   `kernel.store` wired
   ([`boltrig/fleet/hatchet_app.py:118-160`](../../../boltrig/fleet/hatchet_app.py)
   `'ctx = context_from_envelope(payload["ctx_envelope"])'` and
   `"store=kernel.store,"`).
8. A returned `completed`/`failed` settles the schedule occurrence outcome; an
   infrastructure exception is re-raised so the engine may retry and the
   occurrence stays in flight
   ([`boltrig/fleet/hatchet_app.py:161-177`](../../../boltrig/fleet/hatchet_app.py)
   `"# An infrastructure/task exception is not a terminal workflow verdict:"`).

### 5.5 Execute (the single-shot path)

`WorkflowLibrary.execute` requires a wired kernel, scopes resolution to
`context.workspace_id`, refuses archived, and calls the interpreter with the
executor but NO store, so there is no checkpointing
([`boltrig/workflows/library.py:314-324`](../../../boltrig/workflows/library.py)
`'raise RuntimeError("WorkflowLibrary.execute requires a kernel")'`).

### 5.6 The cron scheduler

Per cycle, per tenant ([`boltrig/workflows/scheduler.py:336-372`](../../../boltrig/workflows/scheduler.py)
`"Reconcile due schedules once and return queued logical occurrences."`):

1. Recover prior retryable/expired occurrences, capped at 50 per batch
   ([`boltrig/workflows/scheduler_dispatch.py:15`](../../../boltrig/workflows/scheduler_dispatch.py)
   `"MAX_RECOVERY_BATCH = 50"`).
2. For each schedule, check the workflow is available and not archived, then
   re-derive authority: the bound `authority_subject` must resolve to an ACTIVE
   user, must still be a member of the schedule's workspace, and its LIVE
   effective grants intersected with the captured `grant_ceiling` must still
   permit `control.workflow.trigger`
   ([`boltrig/workflows/scheduler_dispatch.py:18-54`](../../../boltrig/workflows/scheduler_dispatch.py)
   `"bounded = current.intersect(schedule.grant_ceiling)"`).
   **Failure branches, each recorded as observed state, never invented:**
   `scheduling_authority_not_bound`, `scheduling_authority_revoked`,
   `scheduling_workspace_membership_revoked`, `scheduling_trigger_grant_revoked`,
   `scheduled_workflow_unavailable`, `scheduled_workflow_archived`,
   `durable_executor_required`.
3. Initialise `next_due_at` on first sight and return (no catch-up on creation).
4. While due and under the catch-up cap of 3, claim the occurrence row by
   `(tenant, workflow, scheduled_for)` with a lease, stamping the workflow and
   schedule digests and the deterministic run id
   `wfs_<sha256(tenant\0workflow\0iso-utc)>`
   ([`boltrig/workflows/scheduler_cron.py:190-194`](../../../boltrig/workflows/scheduler_cron.py)
   `'return f"wfs_{hashlib.sha256(value.encode()).hexdigest()}"'`).
5. Dispatch by calling `WorkflowLibrary.trigger` DIRECTLY with the reconstructed
   authority context and `expected_workflow_sha256`
   ([`boltrig/workflows/scheduler_dispatch.py:170`](../../../boltrig/workflows/scheduler_dispatch.py)
   `"descriptor = await workflows.trigger("`). **Failure branch:** any exception
   marks the occurrence `retryable` while `attempts < 3`, else `failed`, reason
   `schedule_dispatch_failed`.
6. Advance the schedule with a CAS on `expected_due_at`; if the cap is hit with
   work still due, skip forward and record `missed_occurrences_truncated`
   ([`boltrig/workflows/scheduler.py:277-286`](../../../boltrig/workflows/scheduler.py)
   `'reason="missed_occurrences_truncated",'`).

Recovery re-checks the digests and fails `occurrence_snapshot_changed` if either
the workflow or the authority-bearing schedule state changed
([`boltrig/workflows/scheduler_dispatch.py:236-244`](../../../boltrig/workflows/scheduler_dispatch.py)
`'reason="occurrence_snapshot_changed",'`).

### 5.7 The forever loop

`run_workflow_scheduler_forever` reads the overdue count from the stored
`next_due_at` values BEFORE reconciling, deliberately not from the reconcile
path, so "saw work and did none" is distinguishable from "had nothing to do"
([`boltrig/workflows/scheduler_loop.py:44`](../../../boltrig/workflows/scheduler_loop.py)
`"job is to disagree with the reconcile path when that path is broken, which it"`).
It records a durable background-job receipt each cycle, swallows any cycle
exception and continues, and re-raises `CancelledError`.

### 5.8 Event-source triggers (webhook and channel)

`deliver_trigger` is the shared body. Preflight: an existing delivery row for the
same `(tenant, trigger, event digest)` returns `duplicate` 200; a disabled
trigger 409; an unavailable workflow 403 `workflow_unavailable`; an archived one
409; a principal that failed re-authorisation 403 `authority_revoked`
([`boltrig/kernel/workflow_trigger_delivery.py:141-177`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`'return {"status": "denied", "receipt": delivery_view(row)}, 403'`).

Admission builds the params (`workflow_id`, `inputs.trigger`, `inputs.event`,
an `idempotency_key` of `workflow-trigger:<trigger>:<digest>`) and a
deterministic `wft_<sha256>` run id, then dispatches
`control.workflow.trigger` through `dispatch_control_route`, which enters
`kernel.invoke` ([`boltrig/kernel/control_routes.py:77`](../../../boltrig/kernel/control_routes.py)
`"output = await kernel.invoke("`). A held gate produces a `pending_human`
receipt with 202.

Authority for a webhook is the trigger's stored owner re-derived live and
intersected with the stored ceiling
([`boltrig/kernel/workflow_trigger_delivery.py:70-93`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`"bounded = current.intersect(trigger.grant_ceiling)"`); for a channel it is the
authenticated channel principal narrowed by the same intersection
([`:96-120`](../../../boltrig/kernel/workflow_trigger_delivery.py)
`"bounded = bounded.intersect(current)"`).

The channel bridge in this area is a thin adapter: it tries the HITL reply path
first and only then delivers workflow triggers, answering 202 with the per
trigger outcomes
([`boltrig/kernel/channel_workflow_trigger_bridge.py:29-41`](../../../boltrig/kernel/channel_workflow_trigger_bridge.py)
`"triggered = await deliver_channel_workflow_triggers("`).

### 5.9 A conversational routine occurrence

1. `trigger` allocates the conversation (5.4 step 4) and enqueues.
2. `run_workflow_body` detects the routine and routes to
   `run_routine_conversation` instead of the interpreter; a missing chat service
   or a missing conversation binding raises rather than silently degrading
   ([`boltrig/fleet/hatchet_app.py:135-137`](../../../boltrig/fleet/hatchet_app.py)
   `'raise RuntimeError("routine_conversation_binding_missing")'`).
3. The runner re-validates the conversation binding, then checks checkpoints:
   `routine:completed` short-circuits to `completed`; an unanswered HITL message
   returns `paused` with the request's own run id as `resume_scope`; otherwise
   it composes the turn.
4. The initial prompt wraps the trigger payload with `wrap_untrusted` and tells
   the model to treat it as data
   ([`boltrig/fleet/routine_run.py:56-69`](../../../boltrig/fleet/routine_run.py)
   `"trigger_data = wrap_untrusted("`). A resume prompt does the same for the
   human's answer.
5. The turn runs through the ordinary `ChatService.handle_turn` under the
   context's own grants, workspace and scope, with an idempotency key derived
   from the occurrence and, on resume, from the exact request and response ids
   ([`boltrig/fleet/routine_run.py:227-233`](../../../boltrig/fleet/routine_run.py)
   `'f"routine:{run.occurrence_run_id}:resume:{decision.request.id}:"'`).
6. Completion checkpoints FIRST, then optionally notifies, and swallows any
   notification failure
   ([`boltrig/fleet/routine_run.py:158-178`](../../../boltrig/fleet/routine_run.py)
   `"# The chat is canonical. Record completion before the optional notification"`).

### 5.10 Loading skills from disk at boot

`load_skills_dir` walks `*.yaml` then `*.yml` under the directory, skips any
document that is not a mapping, parses and upserts each one, and returns the
loaded ids ([`boltrig/skills/loader.py:37-54`](../../../boltrig/skills/loader.py)
`"a broken library should be loud, not silently partial"`). Boot calls it for
`libraries/skills` only and swallows any failure so a bad skill file cannot stop
a boot ([`boltrig/api/bootstrap.py:305-313`](../../../boltrig/api/bootstrap.py)
`"except Exception as exc:  # a bad skill file should not stop boot"`).

### 5.11 Using a skill through the shelf

`skill.search` returns id, version, description, `tool_grant_count` and
`extends`, sorted by id, clamped to 1..100
([`boltrig/skills/shelf.py:137-153`](../../../boltrig/skills/shelf.py)
`'"tool_grant_count": len(s.tool_grants),'`). `skill.describe` adds the grants
and the requirements schema, still without the body. `skill.load` resolves the
inheritance chain, drops `None` context values, validates against the merged
schema and raises `ContextRequirementsUnmet` listing the missing keys or the
validator messages, then returns the composed body plus the grants AS DATA
([`boltrig/skills/shelf.py:194-210`](../../../boltrig/skills/shelf.py)
`"raise ContextRequirementsUnmet("`).

---

## 6. Data

### 6.1 Tables

| table | key | owner migration | notes |
| --- | --- | --- | --- |
| `workflow_definitions` | `(tenant_id, id, version)` | [`migrations/baseline.sql:95`](../../../migrations/baseline.sql) `"CREATE TABLE IF NOT EXISTS workflow_definitions ("` | `definition JSONB`, `intent_tags JSONB`; `workspace_id` added by 0014 |
| `workflow_run_records` | `(tenant_id, run_id)` | [`migrations/versions/0020_workflow_run_records.py:28`](../../../migrations/versions/0020_workflow_run_records.py) `"CREATE TABLE IF NOT EXISTS workflow_run_records ("` | observability only; write failures swallowed |
| `run_checkpoints` | `(tenant_id, run_id, step)` | [`migrations/versions/0005_durable_delegation.py:30`](../../../migrations/versions/0005_durable_delegation.py) `"CREATE TABLE IF NOT EXISTS run_checkpoints ("` | `status`, `output JSONB`, `hitl_request_id` |
| `workflow_schedules` | `(tenant_id, workflow_id)` | [`migrations/versions/0055_workflow_schedules.py:20`](../../../migrations/versions/0055_workflow_schedules.py) `"CREATE TABLE IF NOT EXISTS workflow_schedules ("` | `authority_subject`, `grant_allow/deny JSONB`, closed `observed_status` check |
| `workflow_schedule_occurrences` | `(tenant_id, workflow_id, scheduled_for)`, unique `(tenant_id, run_id)` | 0055 + [`0057`](../../../migrations/versions/0057_workflow_occurrence_lifecycle.py) `"ADD COLUMN workflow_sha256 TEXT,"` | lease shape CHECK; digests and retry counters from 0057 |
| `workflow_triggers` | `(tenant_id, id)`, unique `(tenant_id, workflow_id, name)` | [`migrations/versions/0050_workflow_triggers.py:20`](../../../migrations/versions/0050_workflow_triggers.py) `"CREATE TABLE IF NOT EXISTS workflow_triggers ("` | shape CHECK ties `source` to `channel_id`/`secret_hash` |
| `workflow_trigger_deliveries` | `(tenant_id, trigger_id, source_event_digest)` | 0050 | digest constrained to `^[0-9a-f]{64}$` |
| `skills` | `(tenant_id, id, version)` | [`migrations/baseline.sql:67`](../../../migrations/baseline.sql) `"CREATE TABLE IF NOT EXISTS skills ("` | `tool_grants JSONB`, `context_requirements JSONB` |
| `work_items` | `(tenant_id, id)` | [`migrations/baseline.sql:124`](../../../migrations/baseline.sql) `"CREATE TABLE IF NOT EXISTS work_items ("` | `constraints JSONB` holds the channel provenance stamp |
| `conversations` (routine columns) | `(tenant_id, id)` | [`migrations/versions/0075_routine_conversations.py:20`](../../../migrations/versions/0075_routine_conversations.py) `"ALTER TABLE conversations"` | `origin`, `source_ref`, `source_run_id`, `companion_id`; partial UNIQUE on `(tenant_id, source_run_id) WHERE origin='routine'` |

Indexes worth naming: `workflow_schedules_due_idx (tenant_id, next_due_at,
workflow_id)`, `workflow_schedule_occurrences_claim_idx (tenant_id, status,
lease_expires_at, scheduled_for)`, `workflow_triggers_channel_idx` partial on
`source='channel'`, `work_items_status_idx`, `work_items_parent_idx`.

### 6.2 Retention, encryption, isolation

Nothing in this area encrypts a column. Tenant isolation is by `tenant_id` in
every key plus the shared RLS replay; the workspace column is deliberately an
application filter and NOT an RLS predicate, because an RLS predicate on
`workspace_id` would hide the org-wide NULL rows
([`boltrig/models/libraries.py:179-180`](../../../boltrig/models/libraries.py)
`"RLS stays tenant_id-fenced; this is an application filter on top"`).
No retention policy trims `workflow_run_records`, `run_checkpoints` or
`workflow_schedule_occurrences` (bounded:
`rg -n "retention|DELETE FROM (run_checkpoints|workflow_run_records|workflow_schedule_occurrences)" boltrig/ migrations/`,
2026-08-24, pinned tree, no deleter found).

### 6.3 Digests

- Workflow snapshot: sha256 over canonical JSON of eight fields
  ([`boltrig/workflows/snapshot.py:57`](../../../boltrig/workflows/snapshot.py)
  `"encoded = _canonical(body)"`).
- Schedule authority digest: sha256 over tenant, workflow, workspace, cron,
  timezone, authority subject and both grant arrays
  ([`boltrig/workflows/scheduler_cron.py:197-216`](../../../boltrig/workflows/scheduler_cron.py)
  `'"""Bind an occurrence to authority-bearing schedule desired state."""'`).
- Loop items digest: sha256 over the canonical JSON of the SELECTED (capped)
  items ([`boltrig/workflows/loop_contract.py:144-148`](../../../boltrig/workflows/loop_contract.py)
  `"digest=hashlib.sha256(canonical).hexdigest(),"`).
- Trigger event digest: `sha256(source_scope + NUL + source_event_id)`
  ([`boltrig/kernel/workflow_trigger_delivery.py:54-57`](../../../boltrig/kernel/workflow_trigger_delivery.py)
  `'f"{source_scope}\\0{source_event_id}".encode()'`).

### 6.4 The on-disk libraries

| directory | files | loaded at run time? |
| --- | --- | --- |
| `libraries/skills/` | 25 YAML (8 declare `tool_grants`, 1 uses `extends`, 3 have no `description`, 0 locale variants) | YES, at boot |
| `libraries/workflows/` | 5 YAML | NO |
| `libraries/prompts/` | 7 Markdown, 111 lines total | NO |
| `libraries/emotion/` | 3 YAML, 195 lines | YES, by the emotion tables loader |

`libraries/workflows/` is authoring data. Nothing scans it: the only code path
naming a `libraries/` directory besides emotion is the skills loader
([`boltrig/api/bootstrap.py:64`](../../../boltrig/api/bootstrap.py)
`_SKILLS_DIR_CANDIDATES = ("/app/libraries/skills", "libraries/skills")`), and
the shipped YAML says so itself
([`libraries/workflows/sleep-distillation-craft.yaml:12`](../../../libraries/workflows/sleep-distillation-craft.yaml)
`"NOTE this file is authoring data, not a boot-time load"`). Bounded:
`rg -n 'libraries/' --type py -g '!tests/**'`, 2026-08-24, pinned tree, hits only
in `boltrig/emotion/tables.py`, `boltrig/api/bootstrap.py` and two scripts.

`libraries/prompts/` is referenced by no code at all. Bounded:
`rg -n "libraries/prompts"`, 2026-08-24, pinned tree, exactly one hit, and that
hit is a prose mention in a design document
([`docs/architecture/engine-components.md:369`](../../../docs/architecture/engine-components.md)
`"prompt data also under"`). A second sweep over the five prompt filenames
(`rg -n "campaign-planner|chief-of-staff|lead-responder|outbound-reviewer|challenger"`
excluding `libraries/prompts/` itself, same date and tree) found no code hit that
reads any of those files.

`libraries/emotion/` IS live: `boltrig/emotion/tables.py` searches
`/app/libraries/emotion`, `libraries/emotion`, then the repo-relative path
([`boltrig/emotion/tables.py:27`](../../../boltrig/emotion/tables.py)
`_TABLE_DIR_CANDIDATES = ("/app/libraries/emotion", "libraries/emotion")`).
Its event map consumes this area's own step events
([`libraries/emotion/event_map.yaml:25`](../../../libraries/emotion/event_map.yaml)
`"- {type: workflow_step, where: {status: ok}, appraise: step_ok, intensity: 0.4}"`,
matching [`boltrig/workflows/interpreter.py:154`](../../../boltrig/workflows/interpreter.py)
`{"type": "workflow_step", **event}`).

### 6.5 `schemas/` as the contract surface

`schemas/` holds VERSIONED EXTERNAL CONTRACTS, not runtime configuration. It is
four files in three version-named directories:

| path | what it fixes | who enforces it |
| --- | --- | --- |
| `schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json` (471 KB) | the exact Codex App Server protocol Boltrig is pinned to | [`scripts/check_codex_protocol.py:26`](../../../scripts/check_codex_protocol.py) `PIN_SCHEMA_SHA256 = "66ab7534f29e1ee7c065eb15c799d5f6e93fdd1d0ba86c262c3842a6a8f3d0c8"`, run by `make codex-protocol` |
| `schemas/codex/0.144.3/manifest.json` | the binary digest, target triple, allowed transports and canonicalisation rule | same checker; [`schemas/codex/0.144.3/manifest.json`](../../../schemas/codex/0.144.3/manifest.json) `"canonicalization": "json-sort-keys-compact-lf-v1"` |
| `schemas/character-bundle/v1/character-bundle.schema.json` (18 KB) | the character bundle manifest: a bundle ships CONFIGURATION ONLY | [`schemas/character-bundle/v1/character-bundle.schema.json:5`](../../../schemas/character-bundle/v1/character-bundle.schema.json) `"A bundle ships CONFIGURATION ONLY -- never executable code"`; read by [`tests/test_persona_layer.py:148`](../../../tests/test_persona_layer.py) `"schemas/character-bundle/v1/character-bundle.schema.json"` |
| `schemas/emotion/1.0.0/phenotype.schema.json` | the phenotype file the emotion relay publishes to `$XDG_RUNTIME_DIR` | documentary only (see RISKS) |

The directory convention is `schemas/<contract>/<version>/`, and the version is
part of the path so a bump is a new directory rather than an edit
([`docs/decisions/0022-hold-the-codex-pin-at-0-144-3.md:34`](../../../docs/decisions/0022-hold-the-codex-pin-at-0-144-3.md)
"`schemas/codex/` holds `0.144.3` and nothing else."). The codex pin also carries
a bundle probe: 267 files, a canonical sha256 over relative-path plus per-file
digest lines.

---

## 7. Configuration surface

| name | default | effect if wrong |
| --- | --- | --- |
| `BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL` | `15.0` seconds ([`boltrig/workflows/scheduler_cron.py:14`](../../../boltrig/workflows/scheduler_cron.py) `"DEFAULT_INTERVAL_SECONDS = 15.0"`) | unparseable falls back to 15.0; `0` or negative clamps to 0.0 and the worker DISABLES the scheduler entirely, logging `workflow scheduler disabled (interval<=0)` ([`boltrig/api/worker.py:248`](../../../boltrig/api/worker.py) `log.info("workflow scheduler disabled (interval<=0)")`) |
| `BOLTRIG_EMOTION_TEMPO` | `model.yaml`'s `tempo: 60.0` | non-numeric or non-positive is ignored ([`boltrig/emotion/tables.py:75-84`](../../../boltrig/emotion/tables.py) `"return override if override > 0.0 else default"`) |

Bounded: `rg -n "environ|getenv" boltrig/workflows/ boltrig/work/ boltrig/skills/`,
2026-08-24, pinned tree, exactly one hit: the `os.environ.get` on line 176,
inside `scheduler_interval_from_env`, which reads
([`boltrig/workflows/scheduler_cron.py:177`](../../../boltrig/workflows/scheduler_cron.py)
`"BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL",`). No other environment variable
changes this area's behaviour.

Manifest and directory keys:

| key | default | effect |
| --- | --- | --- |
| skills directory | `/app/libraries/skills`, then `libraries/skills` | absent means no skills are loaded and every `skill.load` is `unknown skill` |
| emotion tables directory | `/app/libraries/emotion`, `libraries/emotion`, then repo-relative | absent or malformed disables the emotion feature entirely, silently |
| `manifest.tenant_id` | `_DEFAULT_TENANT` | selects the ONE tenant the workflow scheduler reconciles ([`boltrig/api/worker.py:287`](../../../boltrig/api/worker.py) `"tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT"`) |

Non-configurable policy constants that behave like configuration and can only be
changed by a code edit: `MAX_STEP_RETRIES = 5`, `MAX_RETRY_INTERVAL_MS = 60_000`,
`WORKFLOW_LOOP_MAX_ITEMS = 100`, `WORKFLOW_LOOP_MAX_BINDINGS = 32`,
`WORKFLOW_LOOP_MAX_BOUND_BYTES = 256 KiB`, `WORKFLOW_LOOP_MAX_PARALLEL = 10`,
`MAX_CATCH_UP = 3`, `MAX_MANUAL_RETRIES = 3`, `DEFAULT_LEASE_SECONDS = 120`,
`MAX_DISPATCH_ATTEMPTS = 3`, `MAX_RECOVERY_BATCH = 50`,
`MAX_TRIGGER_EVENT_BYTES = 256 KiB`, `MAX_SKILL_SEARCH_RESULTS = 100`,
`CONVERGENT_THRESHOLD = 0.7`, routine input cap 64 KiB.

---

## 8. PROCESS

### 8.1 Authoring a workflow, end to end

1. Draft freely: `POST /v1/workflows` is the published upsert, but chat-first
   authoring uses `control.workflow.draft.upsert`, which is LOW consequence and
   applies without a hold. A draft is never runnable and never shadows the
   published row.
2. Publish deliberately: `control.workflow.publish` is HIGH consequence and the
   approval binds the DRAFT's content digest.
3. Verify the definition is loop-valid BEFORE publishing. The authoring path
   refuses an invalid loop contract with a `ValueError`; there is no way to
   store one and discover it at run time.
4. Run it: `POST /v1/workflows/{wf_id}/execute` (synchronous, single-shot) or
   `POST /v1/workflows/{wf_id}/trigger` (durable enqueue). Both are HIGH
   consequence, so expect a `pending_human` 202 the first time and re-issue with
   the approval id.
5. Observe: `GET /v1/workflows/{wf_id}/runs` lists run ids the caller may see;
   `GET /v1/workflow-stats` aggregates run counts. Both are read routes
   registered in [`boltrig/kernel/platform_routes/workflows.py:332-341`](../../../boltrig/kernel/platform_routes/workflows.py)
   `"def register(app, P, K) -> None:"`.

### 8.2 Scheduling a workflow

`control.workflow.schedule` with a 5- or 6-field cron and an IANA timezone.
`schedule_spec` validates BOTH before persisting, so a bad schedule fails at
definition time and not at the next tick
([`boltrig/workflows/generator.py:253-267`](../../../boltrig/workflows/generator.py)
`'raise ValueError(f"unknown timezone {timezone!r}: {exc}") from exc'`).

**The operational trap, stated by the shipped YAML itself:** schedule AS A REAL
USER holding `control.workflow.trigger`. A schedule created by a service
principal persists with `observed_status: needs_action` and
`scheduling_authority_not_bound` and never runs
([`libraries/workflows/sleep-distillation-craft.yaml:15`](../../../libraries/workflows/sleep-distillation-craft.yaml)
`"AS A REAL USER holding"`, matching
[`boltrig/config/control_workflows.py:196-218`](../../../boltrig/config/control_workflows.py)
`'observed_reason: str | None = "scheduling_authority_not_bound"'`).

**Diagnosing a schedule that is not firing.** Read
`GET /v1/workflows/{wf_id}`'s `schedule_state`, which projects desired versus
observed with an explicit reason
([`boltrig/workflows/scheduler_state.py:12-17`](../../../boltrig/workflows/scheduler_state.py)
`'"""Project explicit desired/observed state without pretending metadata runs."""'`).
The reason vocabulary is closed and is listed in section 5.6. Then check, in
order: is the worker running with a durable executor (`durable_executor_required`
means it is not); is `BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL` above zero; is the
schedule's tenant the worker's manifest tenant.

**Recovering a failed occurrence.** `control.workflow.schedule_occurrence.retry`
takes the exact `(workflow_id, scheduled_for, run_id)` triple, requires
independent approval, is capped at `MAX_MANUAL_RETRIES = 3`, and reuses the same
logical run id; the author-scoped receipt list is
`GET /v1/workflows/{wf_id}/schedule/occurrences`
([`boltrig/kernel/platform_routes/workflows.py:196`](../../../boltrig/kernel/platform_routes/workflows.py)
`"async def workflow_schedule_occurrences(wf_id: str, limit: int = 25, k=K, p=P) -> JSONResponse:"`).

### 8.3 Resuming a paused run

A paused step leaves a `paused` checkpoint carrying the HITL request id. The
answer bridge pushes the scoped approval event and the engine re-enters the same
task; the interpreter replays every `ok` checkpoint, reaches the paused step and
re-invokes with the approval id, and the kernel's consume-if-approved CAS lets
exactly one execution through. If the human REJECTED or the request timed out,
the interpreter resolves the step through its error strategy instead of asking
again. Nothing here is manual; the operator action is answering the HITL request.

### 8.4 Adding a skill

Two routes, and they do not validate the same things.

- **Data route:** drop a YAML file under `libraries/skills/` and restart. Boot
  parses it with `parse_skill`, which enforces semver, string types and a valid
  Draft 2020-12 `context_requirements`, and reports every error at once.
- **Governed route:** `control.skill.upsert`. This constructs the `Skill`
  directly and runs NONE of those checks
  ([`boltrig/config/control_operations.py:65-78`](../../../boltrig/config/control_operations.py)
  `'tool_grants=params.get("tool_grants", []),'`). See RISKS.

Either way the grants are a request. To give an agent reach you must widen the
CALLER's grants; editing a skill can only ever narrow what that caller offers a
child.

### 8.5 Gates that must pass before this area ships

- `make invariants` - `scripts/check_invariants.py`, the K-29/K-30 binding gate:
  every claimed invariant must name a test.
- `make structure` - `scripts/check_structure.py`. The interpreter carries an
  expiring debt ratchet: 393 file lines, 275 function lines, owner
  `workflow-maintainers`, expires 2026-12-31
  ([`docs/refactoring/structural-exemptions.json:359`](../../../docs/refactoring/structural-exemptions.json)
  `"boltrig/workflows/interpreter.py": {`).
- `make unwired-claims` and `make reachability` - the dead-code gates. Three of
  this area's symbols are carried as recorded exceptions there
  (`select_locale`, `select_or_generate_workflow`, `InternalQueueAdapter.push`).
- `make codex-protocol` - the `schemas/codex/` pin.
- Area-specific security gate: `tests/security/test_skill_grant_expansion.py`
  reads every `libraries/skills/*.yaml` and holds the shipped grants to three
  rules (no wildcard over a CONSUMED namespace, no expansion above
  `MAX_KERNEL_TOOLS`, no namespace that resolves to zero registered verbs)
  against a vendored verb surface
  ([`tests/security/test_skill_grant_expansion.py:52-56`](../../../tests/security/test_skill_grant_expansion.py)
  `'_SKILLS = _REPO / "libraries" / "skills"'`).

### 8.6 Bringing the scheduler up

`_start_workflow_scheduler` is called from the worker's background task set and
returns `None` when the interval is not positive
([`boltrig/api/worker.py:237-266`](../../../boltrig/api/worker.py)
`'"""Start the store-backed cron reconciler used by every executor mode."""'`).
It logs tenant, interval and durability at start, which is the fastest way to
confirm it is alive and whether occurrences can actually enqueue.

---

## 9. Failure modes and fail-open / fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| Unknown branch operator | FAIL-CLOSED (false) | [`boltrig/workflows/control_flow.py:88`](../../../boltrig/workflows/control_flow.py) `"Unknown ops are false (fail-closed)."` is the docstring of `_compare`; the operator ladder ends at line 123 and falls through to a bare `return False` |
| Malformed multi-case case | FAIL-CLOSED (never matches) | [`control_flow.py:157-166`](../../../boltrig/workflows/control_flow.py) `"if not isinstance(conditions, list):"` |
| Case with empty `conditions` | FAIL-OPEN (always matches, the else arm) | [`control_flow.py:155-156`](../../../boltrig/workflows/control_flow.py) `"if not conditions:"` |
| Unresolvable `$ref` in a predicate | FAIL-OPEN (None) | [`boltrig/workflows/control_flow.py:63`](../../../boltrig/workflows/control_flow.py) `"literal). An unresolvable reference yields ``None`` (fail-open: a branch on"` |
| `flow.branch` with no params | FAIL-OPEN (True) | [`control_flow.py:136-137`](../../../boltrig/workflows/control_flow.py) `"if not params:"` then `"return True"` |
| Step with no `branch` key | FAIL-OPEN (runs) | [`control_flow.py:277-279`](../../../boltrig/workflows/control_flow.py) `"if declared is None:"` |
| Unknown control verb | FAIL-CLOSED (`skipped` + run fails) | [`boltrig/workflows/control_flow.py:265`](../../../boltrig/workflows/control_flow.py) `return {"status": "skipped", "output": {"reason": f"unknown control action {action}"}}` |
| Cycle or missing parent | FAIL-CLOSED (`skipped`, run fails) | [`boltrig/workflows/interpreter.py:97`](../../../boltrig/workflows/interpreter.py) `"indegree[s[\"id\"]] += 1  # missing parent => never satisfiable"` |
| Failure-lineage parent | FAIL-CLOSED | [`boltrig/workflows/interpreter.py:256`](../../../boltrig/workflows/interpreter.py) `"# A step with a failure-lineage parent cannot run (fail-closed)."` |
| Branch-lineage parent (OR-join) | FAIL-OPEN by design (one delivered parent runs the merge) | [`interpreter.py:266-268`](../../../boltrig/workflows/interpreter.py) `"# OR-join: a step runs when at least one parent delivered."` |
| Invalid loop contract at run start | FAIL-CLOSED (zero dispatches) | [`loop_execution.py:31-32`](../../../boltrig/workflows/loop_execution.py) `"issue = validate_loop_contract(definition)"` |
| Loop items not a list | FAIL-CLOSED (`loop_items_unavailable`) | [`control_flow.py:234-238`](../../../boltrig/workflows/control_flow.py) `'"reason": "loop_items_unavailable",'` |
| Loop item overflow past 100 | TRUNCATE, but recorded | [`boltrig/workflows/control_flow.py:251`](../../../boltrig/workflows/control_flow.py) `output["skipped_overflow"] = bounded.overflow` |
| Unknown `on_item_error` at run time | FAIL-CLOSED to `fail` | [`loop_execution.py:155-158`](../../../boltrig/workflows/loop_execution.py) `'"""The loop\'s declared item-error mode; unknown values fail closed to ``fail``."""'` |
| Invalid `parallel` at run time | FAIL-CLOSED to 1 | [`loop_execution.py:167-172`](../../../boltrig/workflows/loop_execution.py) `"invalid fails closed to 1"` |
| Control step inside a parallel body | FAIL-CLOSED to sequential | [`boltrig/workflows/loop_execution.py:194`](../../../boltrig/workflows/loop_execution.py) `"if any(control_flow.is_control_step(c.get(\"action\", \"\")) for c in clones):"` |
| Unknown `on_error` | FAIL-CLOSED to `fail` | [`boltrig/workflows/step_execution.py:109`](../../../boltrig/workflows/step_execution.py) `return strategy if strategy in ERROR_STRATEGIES else "fail"` |
| Non-numeric `retry` | FAIL-CLOSED to no retry | [`step_execution.py:101-102`](../../../boltrig/workflows/step_execution.py) `"except (TypeError, ValueError):"` |
| Pause disposition unreadable | FAIL-CLOSED to `resume` (the kernel gate decides) | [`step_execution.py:56-60`](../../../boltrig/workflows/step_execution.py) `"Fail-closed: anything unreadable, pending, consumed, or approvingly"` |
| `IdempotencyConflict` with a key | FAIL-OPEN to one keyless invoke (at-least-once, stated) | [`step_execution.py:290-295`](../../../boltrig/workflows/step_execution.py) `"# COMPLETED prior record replays inside the kernel and never"` |
| Adapter raising a non-Boltrig exception | CONTAINED (status `error`, run continues per strategy) | [`boltrig/workflows/step_execution.py:361`](../../../boltrig/workflows/step_execution.py) `"except Exception as exc:  # an adapter bug must not crash the fleet (P9)"` |
| Event relay failure | FAIL-SAFE (swallowed) | [`interpreter.py:155-156`](../../../boltrig/workflows/interpreter.py) `"except Exception:"` then `"pass"` |
| Run-stat write failure | FAIL-SAFE (swallowed) | [`boltrig/config/control_workflow_dispatch.py:257`](../../../boltrig/config/control_workflow_dispatch.py) `"pass  # Observability cannot invalidate an already-completed run."` |
| Reuse-signal harvest failure | FAIL-SAFE (swallowed) | [`boltrig/workflows/signals.py:59`](../../../boltrig/workflows/signals.py) `"except Exception:  # a harvest failure never fails the run that produced it (P9)"` |
| Snapshot digest / identity / workspace drift | FAIL-CLOSED (`WorkflowSnapshotError`) | [`snapshot.py:107-113`](../../../boltrig/workflows/snapshot.py) `'raise WorkflowSnapshotError("workflow snapshot is outside the active workspace")'` |
| Task payload tenant vs envelope tenant | FAIL-CLOSED (`TenantIsolation`) | [`hatchet_app.py:82-85`](../../../boltrig/fleet/hatchet_app.py) `"raise TenantIsolation("` |
| Schedule authority revoked | FAIL-CLOSED, recorded as observed state | [`boltrig/workflows/scheduler_dispatch.py:26`](../../../boltrig/workflows/scheduler_dispatch.py) `return None, "scheduling_authority_revoked"` |
| Scheduler cycle exception | CONTAINED (logged, loop continues) | [`scheduler_loop.py:107-109`](../../../boltrig/workflows/scheduler_loop.py) `'log.warning("workflow schedule reconciliation failed", exc_info=True)'` |
| Skill directory load failure at boot | FAIL-OPEN (boot continues with no skills) | [`boltrig/api/bootstrap.py:312`](../../../boltrig/api/bootstrap.py) `"except Exception as exc:  # a bad skill file should not stop boot"` |
| Cyclic `extends` in the LOADER | FAIL-CLOSED (raises) | [`loader.py:68-71`](../../../boltrig/skills/loader.py) `"raise SkillValidationError("` |
| Cyclic `extends` in the SPAWN resolver | FAIL-OPEN (silently returns a partial chain) | [`spawn_skills.py:80-82`](../../../boltrig/fleet/spawn_skills.py) `"if skill_id in seen:"` then `"return"` |
| Unknown skill at spawn | FAIL-CLOSED (`SkillNotFound`, 404) | [`spawn_skills.py:85-86`](../../../boltrig/fleet/spawn_skills.py) `'raise SkillNotFound(f"unknown skill \'{skill_id}\'")'` |
| Skill context requirements unmet | FAIL-CLOSED (`ContextRequirementsUnmet`) | [`shelf.py:193-196`](../../../boltrig/skills/shelf.py) `'detail = "; ".join(errors) if errors else "missing required context"'` |
| Emotion table parse failure | FAIL-OPEN (feature off, silently) | [`emotion/tables.py:6-8`](../../../boltrig/emotion/tables.py) `"shape, non-numeric value) returns ``None`` so the feature stays off"` |
| Trigger event over 256 KiB | FAIL-CLOSED (`event_too_large`) | [`workflow_trigger_delivery.py:276-277`](../../../boltrig/kernel/workflow_trigger_delivery.py) `'return [{"status": "error", "reason": "event_too_large"}]'` |
| Routine notification failure | FAIL-SAFE (swallowed after the completion checkpoint) | [`routine_run.py:175-178`](../../../boltrig/fleet/routine_run.py) `"# Notification delivery is a side channel, never the authority for"` |

---

## 10. What is proven

Invariants in `tests/invariants.yaml` that bind this area, with the tests that
carry them:

| id | what it fixes | test |
| --- | --- | --- |
| FR-CTL-02 | dependency order, per-step durable boundary, descendants of a failure skipped | `tests/integration/test_round_seven.py::test_interpreter_runs_steps_in_dependency_order_each_durable`, `::test_interpreter_skips_descendants_of_a_failed_step` |
| FR-CTL-03 | control nouns resolved locally, `code.run` disabled | `tests/integration/test_control_flow.py::test_trigger_and_end_are_no_ops_that_complete` and five siblings |
| SEC-50 | a step cannot escalate past caller grants | `tests/security/test_round_seven.py::test_workflow_step_cannot_escalate_past_caller_grants` |
| FR-WFL-19 | the closed bounded loop contract, reserved clone ids, empty input dispatches nothing, invalid contracts refused before persistence | `tests/integration/test_control_flow.py::test_invalid_loop_contract_dispatches_nothing`, `tests/integration/test_durable_resume.py::test_loop_hitl_approves_each_bound_iteration_exactly_once`, `tests/security/test_workflow_lifecycle.py::test_authored_loop_contract_rejects_invalid_bindings_before_save` |
| NFR-REL-02 | checkpoint replay, per-step boundaries, lost-checkpoint replay via idempotency key | `tests/integration/test_durable_resume.py::test_interrupted_run_resumes_from_last_checkpoint`, `::test_completed_step_with_lost_checkpoint_replays_via_idempotency` |
| NFR-REL-03 | a HITL answer resumes exactly once | `tests/integration/test_durable_resume.py::test_hitl_answer_resumes_paused_run_exactly_once` |
| FR-WFL-11 | workspace scoping narrows visibility, never authority | `tests/security/test_workflow_workspace_scope.py` (5 tests) |
| FR-WFL-18 | one current definition per id on both stores | `tests/store/test_store_parity.py::test_list_workflows_returns_latest_version_per_id_on_both_stores` |
| FR-WFL-20 | cron is canonical desired state with re-authorised observed reconciliation; DST, bounded catch-up, atomic lease, honest at-least-once | `tests/security/test_workflow_scheduler.py` (7 tests) |
| FR-WFL-21 | bounded author-scoped occurrence receipts and exact approved retry | `tests/security/test_workflow_occurrence_lifecycle.py` (4 tests) |
| FR-SKILL-01 | the shelf returns descriptions, never bodies, and enforces the same bound at schema and seam | `tests/security/test_round_fifteen.py::test_skill_search_returns_descriptions_not_bodies`, `tests/unit/test_skill_loader.py::test_skill_search_caps_direct_callers_and_declares_the_same_schema_bound` |
| FR-SKILL-02 | `skill.load` binds context and refuses on mismatch | `tests/security/test_round_fifteen.py::test_skill_load_composes_body_and_binds_context` |
| SEC-57 | the shelf is governed and load does not escalate | `tests/security/test_round_fifteen.py::test_skill_shelf_is_governed_and_load_does_not_escalate` |
| EMO-5 | the appraisal table is data and mutating it changes behaviour with no code edit | `tests/emotion/test_engine.py::test_appraisal_table_is_data_and_mutating_it_changes_behavior` |
| CHAN-PROV-01 | kernel-authored channel provenance | `tests/invariants.yaml` CHAN-PROV-01 entry |

Additional coverage that exists but binds NO invariant id
(bounded: `rg -n "pytest.mark.invariant" tests/unit/test_workflow_parity.py`,
2026-08-24, pinned tree, zero hits): `tests/unit/test_workflow_parity.py` is
28 tests covering the OR-join, multi-case branch, the expanded operator set,
`on_error: branch|default`, bounded retry, `on_item_error: continue|drop`,
windowed parallel iteration, the `$inputs` sugar, and the rejected/timed-out
approval branch handles. Same for `tests/unit/test_loop_contract.py` (8 tests),
`tests/unit/test_loop_expansion.py` (6 tests),
`tests/security/test_workflow_draft_lane.py` (5 tests) and
`tests/integration/test_conversational_routines.py` (7 tests). These are real
tests; they are simply not part of the declared invariant register, so
`make invariants` cannot notice if they are deleted.

The shipped skill data has its own gate:
`tests/security/test_skill_grant_expansion.py` (4 tests) proves the vendored verb
surface matches the registered catalogue, no shipped skill wildcards a consumed
namespace, no skill expands past `MAX_KERNEL_TOOLS`, and no granted namespace
resolves to zero verbs. Its `_load_skills` helper asserts it read at least five
GRANTING skills so the sweep cannot pass vacuously
([`tests/security/test_skill_grant_expansion.py:59-63`](../../../tests/security/test_skill_grant_expansion.py)
`'f"scanned nothing: {_SKILLS} yielded {len(granting)} skill(s) with "'`).

---

## 11. RISKS

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

RISK: **The doctrine undercounts the shipped workflow library.**
[`docs/architecture/engine-components.md:601`](../../../docs/architecture/engine-components.md)
says "one precreated recipe ships (`libraries/workflows/onboard-employee.yaml`,
a 4-step onboarding DAG)". Five ship. Severity: LOW.

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

RISK: **The reserved draft prefix is a duplicated string literal.**
[`boltrig/config/control_workflows.py:40`](../../../boltrig/config/control_workflows.py)
`DRAFT_ID_PREFIX = "__draft__:"` and
[`boltrig/workflows/library.py:53`](../../../boltrig/workflows/library.py)
`_DRAFT_ID_PREFIX = "__draft__:"`. The duplication is deliberate and explained
(a layering rule forbids importing config into the workflows package), but two
copies of a security-relevant constant is one copy and a future disagreement.
Severity: LOW.

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

RISK: **The queued context envelope carries grants verbatim and is not
re-derived at execution.** `context_from_envelope` reconstructs the `GrantSet`
from the payload
([`boltrig/models/context.py:91`](../../../boltrig/models/context.py)
`"grants=GrantSet.of(list(grants.get(\"allow\") or []), list(grants.get(\"deny\") or []))"`),
so a workflow queued before a grant revocation still executes its steps with the
pre-revocation grant set when the worker picks it up. The cron and webhook paths
re-derive at ENQUEUE time; nothing re-derives at RUN time. Severity: MEDIUM,
bounded by how long a task can sit queued.

RISK: **A definition has no step-count bound and the interpreter has no
recursion depth counter.** `WORKFLOW_DEFINITION_SCHEMA` puts no `maxItems` on
`steps` ([`boltrig/config/control_workflow_schema.py:79`](../../../boltrig/config/control_workflow_schema.py)
`"steps": {"type": "array", "items": _STEP},`) and the interpreter never
touches `context.depth`. Loop fan-out is bounded (100 items, 10 concurrent,
nested loops refused), but a flat 10 000-step definition dispatches 10 000 times
in one walk. A workflow step naming `control.workflow.execute` is stopped only by
that verb's HIGH consequence gate, not by a depth counter. Severity: LOW-MEDIUM.

RISK: **A capability step whose adapter output happens to contain a `branch` key
silently gates its descendants.** `_record_success` leaves an author- or
adapter-produced `branch` key alone
([`boltrig/workflows/step_execution.py:215-219`](../../../boltrig/workflows/step_execution.py)
`"# (An author-produced ``branch`` key is left alone.)"`) and `branch_matches`
reads any parent's `output["branch"]` regardless of the parent's action
([`boltrig/workflows/control_flow.py:282`](../../../boltrig/workflows/control_flow.py)
`produced = pout.get("branch")`). Severity: LOW.

RISK: **The DAG-parity semantics are unbound by any invariant.** 28 tests in
`tests/unit/test_workflow_parity.py` carry no `@pytest.mark.invariant` (bounded:
`rg -n "pytest.mark.invariant" tests/unit/test_workflow_parity.py`, 2026-08-24,
pinned tree, zero hits), so `make invariants` has nothing to say if
`on_error`, retry, the OR-join, parallel iteration or the approval branch handles
regress. Per the authoring contract, an unbound correctness requirement is itself
a finding. Severity: MEDIUM.

RISK: **`schemas/emotion/1.0.0/phenotype.schema.json` is enforced by nothing.**
No code loads it and no test asserts the published phenotype conforms to it
(bounded: `rg -n "phenotype.schema"` over the tree, 2026-08-24, pinned tree,
zero hits outside the file itself). The other two schema contracts have gates
(`make codex-protocol`, `tests/test_persona_layer.py`). Severity: LOW.

RISK: **The story ids this area's docstrings cite are not invariants.**
`US-SKL-01/02/03` (skill parse, inheritance merge, locale selection),
`US-WRK-01/02`, `FR-WRK-02` (normalisation, confidence, convergent mode) and
`US-EXE-04` (the discovery cap) appear throughout
`boltrig/skills/` and `boltrig/work/` docstrings but none of them is a key in
`tests/invariants.yaml` (bounded: parsed every top-level key of
`tests/invariants.yaml`, 421 entries, 2026-08-24, pinned tree; all eight are
absent). A reader who takes a docstring story id as a binding is wrong.
Severity: LOW-MEDIUM.

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

## 12. OPEN QUESTIONS

1. **Is a multi-tenant, single-worker deployment supported?** If it is, the
   one-tenant scheduler (RISKS) is an outage class. Settled by: the deployment
   manifests under `deploy/` and whether any of them run one worker against a
   store holding more than one `tenant_id`. Not read in this pass; it belongs to
   the deployment area's referent.

2. **Was the cron bypass of `control.workflow.trigger`'s HITL gate a deliberate
   decision?** `FR-WFL-20` describes re-authorisation but says nothing about
   consequence gating. Settled by: a decision record under `docs/decisions/`
   naming the scheduled-occurrence approval posture, or its absence.

3. **How long may a task sit queued before the envelope's grants are stale?**
   The envelope carries grants verbatim; the answer depends on the Hatchet queue
   retention and retry policy, which lives outside this area. Settled by: the
   `HatchetExecutor` configuration and the engine's task TTL.

4. **Should `libraries/workflows/` be loaded, deleted or explicitly labelled?**
   Today it is data that no path reads, containing at least one file that cannot
   be persisted. Settled by: a product decision, not a code reading.

5. **Does any tenant have a `_boltrig_routine` workflow authored before the
   contract existed?** That is the only way the list route's raising projection
   (RISKS) can fire. Settled by: a query against a live store, which this pass
   deliberately did not perform.

6. **Is `WorkflowLibrary.match`'s waiver still live?** The docstring says it
   "retires on expiry without an answer" against
   [`docs/decisions/0019-route-by-intent-is-the-principals.md`](../../../docs/decisions/0019-route-by-intent-is-the-principals.md),
   but no expiry DATE is recorded in the code. Settled by: reading the order's
   own expiry clause, which is in the VJS record rather than the source.

7. **Is `code.run` intended to become executable?** The interpreter records
   intent and a script length but never runs anything
   ([`boltrig/workflows/control_flow.py:260`](../../../boltrig/workflows/control_flow.py)
   `"reason": "code execution disabled (no sandbox configured)"`). Whether a
   sandbox is planned changes whether this is a SEAM or permanently DEAD.
   Settled by: a decision record naming the sandbox.

---

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0900 | A workflow is data: the executable graph lives entirely in the WorkflowDefinition.definition JSON column and adding one requires no code change. | IMPLEMENTED | `boltrig/models/libraries.py:169 "definition: dict[str, Any]  # Hatchet workflow spec"` | FR-CTL-02 |
| BT-REQ-0901 | The interpreter orders steps by Kahn topological sort honouring each step parents list and keeps definition order among independent steps. | IMPLEMENTED | `boltrig/workflows/interpreter.py:81 "Order steps so every parent precedes its children"` | FR-CTL-02 |
| BT-REQ-0902 | A step naming a missing parent or lying in a cycle is recorded skipped with reason missing_parent_or_cycle and fails the run. | IMPLEMENTED | `boltrig/workflows/interpreter.py:97 "# missing parent => never satisfiable"` | FR-CTL-02 |
| BT-REQ-0903 | Every non-control step is dispatched through kernel.invoke and there is no second dispatch path in the interpreter. | IMPLEMENTED | `boltrig/workflows/step_execution.py:283 "return await kernel.invoke("` | SEC-50 |
| BT-REQ-0904 | A step action is an unconstrained string: no allowlist, no registry pre-check and no comparison against the author own grants exists at authoring or run time. | IMPLEMENTED-UNTESTED | `boltrig/config/control_workflow_schema.py:59 "action: _STRING,"` | - |
| BT-REQ-0905 | A workflow step executes under the triggering caller own InvocationContext; no service or system seat is minted for a workflow run. | IMPLEMENTED | `boltrig/workflows/interpreter.py:145 "run_ctx = replace(context, run_id=rid) if rid else context"` | SEC-50 |
| BT-REQ-0906 | The control nouns trigger, flow and code are resolved inside the interpreter and never reach kernel.invoke; a control noun with an unknown verb records skipped and fails the run. | IMPLEMENTED | `boltrig/workflows/control_flow.py:40 "CONTROL_NOUNS = frozenset({trigger, flow, code})"` | FR-CTL-03 |
| BT-REQ-0907 | code.run is recognised and records its script length but never executes anything. | IMPLEMENTED | `boltrig/workflows/control_flow.py:260 "code execution disabled (no sandbox configured)"` | FR-CTL-03 |
| BT-REQ-0908 | Branch predicates are declarative left/op/right structures with no eval; an unknown operator or a TypeError from an ordering comparison evaluates false. | IMPLEMENTED | `boltrig/workflows/control_flow.py:88 "Unknown ops are false (fail-closed)."` | FR-CTL-03 |
| BT-REQ-0909 | A multi-case flow.branch returns the first matching case label in declaration order, else default_label, else the literal false; a case with no conditions is the unconditional else arm and a case without a non-empty string label never matches. | IMPLEMENTED | `boltrig/workflows/control_flow.py:196 "return default if isinstance(default, str) and default else false"` | - |
| BT-REQ-0910 | A step that declares no branch key always satisfies the branch gate and runs. | IMPLEMENTED | `boltrig/workflows/control_flow.py:277 "declared = step.get(branch)"` | - |
| BT-REQ-0911 | An unresolvable $step.path reference resolves to None rather than raising. | IMPLEMENTED | `boltrig/workflows/control_flow.py:63 "An unresolvable reference yields ``None`` (fail-open"` | - |
| BT-REQ-0912 | Capability step params are passed to kernel.invoke verbatim: reference resolution happens only in branch predicates, multi-case conditions and items_from. | IMPLEMENTED | `boltrig/workflows/interpreter.py:355 "params=params, approval_id=approval_id,"` | - |
| BT-REQ-0913 | loop_bindings replace a whole top-level param value with a deep copy of the item or the zero-based index and never interpolate a string. | IMPLEMENTED | `boltrig/workflows/loop_contract.py:297 "bound[target] = copy.deepcopy(item) if source == item else index"` | FR-WFL-19 |
| BT-REQ-0914 | A flow.loop must declare exactly one item source, and an items_from reference must point at an ancestor step output. | IMPLEMENTED | `boltrig/workflows/loop_contract.py:191 "loop_requires_one_item_source"` | FR-WFL-19 |
| BT-REQ-0915 | Loop items are capped at 100 selected values and 256 KiB of canonical JSON, and the discarded excess is recorded as skipped_overflow. | IMPLEMENTED | `boltrig/workflows/loop_contract.py:130 "selected = copy.deepcopy(items[:WORKFLOW_LOOP_MAX_ITEMS])"` | FR-WFL-19 |
| BT-REQ-0916 | Nested loops are refused at authoring time and per-iteration clone ids use the reserved <id>__<n> namespace that an authored id may not occupy. | IMPLEMENTED | `boltrig/workflows/loop_contract.py:239 "nested_loop_not_supported"` | FR-WFL-19 |
| BT-REQ-0917 | An invalid loop contract fails the entire run with a value-free receipt before any step is dispatched. | IMPLEMENTED | `boltrig/workflows/loop_execution.py:30 "Build and emit a value-free failure receipt"` | FR-WFL-19 |
| BT-REQ-0918 | A loop body is the maximal descendant sub-graph in which every step has all of its parents inside the loop or the body. | IMPLEMENTED | `boltrig/workflows/loop_contract.py:93 "if all(parent == loop_id or parent in body for parent in parents):"` | FR-WFL-19 |
| BT-REQ-0919 | A step mixing a loop-body parent with a parent outside the body is skipped with reason mixed_loop_parent rather than dispatched with unresolvable references. | IMPLEMENTED | `boltrig/workflows/interpreter.py:282 "reason: mixed_loop_parent"` | - |
| BT-REQ-0920 | on_item_error continue or drop absorbs a failed iteration, keeps the aggregate ok, clears the clone from the failed set and reports errors and errored_indexes. | IMPLEMENTED | `boltrig/workflows/control_flow.py:388 "output[errors] = len(errored)"` | - |
| BT-REQ-0921 | A loop declaring parallel between 2 and 10 runs a capability-only body concurrently through a semaphore window, and a body containing any control step falls back to the sequential walk. | IMPLEMENTED | `boltrig/workflows/loop_execution.py:164 "WORKFLOW_LOOP_MAX_PARALLEL = 10"` | - |
| BT-REQ-0922 | Per-step retry is clamped to at most 5 additional attempts and 60000 ms, a non-integer retry value disables retry, and an on_error value outside {fail, branch, default} fails closed to fail. | IMPLEMENTED | `boltrig/workflows/step_execution.py:36 "MAX_STEP_RETRIES = 5"` | - |
| BT-REQ-0923 | on_error branch writes branch fail on an exhausted failure and stamps branch success on a successful step, while on_error default substitutes default_output with error_message and error_type overriding same-named keys. | IMPLEMENTED | `boltrig/workflows/step_execution.py:219 "output = {**output, branch: success}"` | - |
| BT-REQ-0924 | An absorbed step failure records status exception, increments the run exceptions_count and is checkpointed ok so a resume replays the absorption. | IMPLEMENTED | `boltrig/workflows/step_execution.py:168 "status: exception"` | - |
| BT-REQ-0925 | A HITL pause is never retried, is never absorbed by an error strategy, and with the checkpoint seam wired is checkpointed paused with its request id before the walk stops. | IMPLEMENTED | `boltrig/workflows/step_execution.py:356 "if reason in PAUSE_REASONS:"` | NFR-REL-03 |
| BT-REQ-0926 | A resumed paused step re-invokes the same verb with the checkpointed approval id so the consume-if-approved CAS executes it exactly once. | IMPLEMENTED | `boltrig/workflows/interpreter.py:347 "approval_id = done.hitl_request_id if done is not None and done.status == paused else None"` | NFR-REL-03 |
| BT-REQ-0927 | A rejected or timed-out approval resolves the step through its error strategy without re-dispatching; any other disposition falls closed to resume so the kernel gate decides, and the pre-check never writes. | IMPLEMENTED | `boltrig/workflows/step_execution.py:256 "reason = approval_rejected if disposition == rejected else approval_timeout"` | - |
| BT-REQ-0928 | Checkpoint keys are workflow-scoped as <workflow_id>:<step> and a step with a prior ok checkpoint replays its recorded output instead of being re-dispatched. | IMPLEMENTED | `boltrig/workflows/interpreter.py:170 "return f\"{wf.id}:{step}\""` | NFR-REL-02 |
| BT-REQ-0929 | A replayed flow.loop re-resolves its items and re-expands only when the recorded output matches exactly, otherwise the step fails loop_replay_mismatch. | IMPLEMENTED | `boltrig/workflows/loop_execution.py:124 "reason: loop_replay_mismatch"` | FR-WFL-19 |
| BT-REQ-0930 | A checkpointed step dispatches with the deterministic key workflow:<wf>:<run>:<step> unless the verb is idempotency-disabled, and an IdempotencyConflict falls back to exactly one keyless invoke. | IMPLEMENTED | `boltrig/workflows/step_execution.py:127 "return f\"workflow:{wf.id}:{rid}:{step_id}\""` | NFR-REL-02 |
| BT-REQ-0931 | The run status is paused if any step paused, else failed if any step genuinely failed, else completed; branch and propagation skips never fail the run. | IMPLEMENTED | `boltrig/workflows/interpreter.py:374 "if paused:"` | - |
| BT-REQ-0932 | A step with any failure-lineage parent is skipped parent_failed, while a step whose parents are all benign branch skips is skipped parents_skipped, so a merge node after a branch runs exactly once. | IMPLEMENTED | `boltrig/workflows/interpreter.py:268 "if parents and all(p in benign_skipped for p in parents):"` | FR-CTL-02 |
| BT-REQ-0933 | The run inputs are referenceable as $inputs.<key>, seeded only when no authored step claims the id inputs. | IMPLEMENTED | `boltrig/workflows/interpreter.py:187 "if not any(s.get(id) == inputs for s in steps):"` | - |
| BT-REQ-0934 | Every step publishes a workflow_step event and the run publishes a terminal workflow_run marker, both inside a swallowing try so the relay can never affect a run. | IMPLEMENTED | `boltrig/workflows/interpreter.py:154 "relay.publish(run_ctx.tenant_id, rid, {type: workflow_step, **event})"` | FR-EVT-04 |
| BT-REQ-0935 | Draft rows under the reserved __draft__: prefix are excluded from get, match, trigger and execute, and the prefix cannot be smuggled through the ordinary upsert. | IMPLEMENTED | `boltrig/workflows/library.py:57 "return wf.id.startswith(_DRAFT_ID_PREFIX)"` | - |
| BT-REQ-0936 | A workflow is resolvable only when it is org-wide or belongs to the caller active workspace, and an archived workflow fails closed at trigger, execute and schedule. | IMPLEMENTED | `boltrig/workflows/library.py:41 "return wf.workspace_id is None or wf.workspace_id == active_workspace_id"` | FR-WFL-11 |
| BT-REQ-0937 | trigger freezes the definition into a canonical-JSON sha256 snapshot, refuses a caller-supplied expected digest that differs, and the task body fails closed on digest, schema, identity or workspace drift when restoring it. | IMPLEMENTED | `boltrig/workflows/snapshot.py:107 "if not hmac.compare_digest(digest, expected):"` | - |
| BT-REQ-0938 | A durable task payload whose tenant differs from its context envelope tenant is refused before any dispatch. | IMPLEMENTED | `boltrig/fleet/hatchet_app.py:83 "raise TenantIsolation("` | SEC-08 |
| BT-REQ-0939 | WorkflowLibrary.execute runs single-shot with the executor boundary and no checkpoint store. | IMPLEMENTED | `boltrig/workflows/library.py:323 "return await run_workflow_definition("` | FR-CTL-02 |
| BT-REQ-0940 | The trigger path task body wires both the executor boundary and kernel.store, so it combines per-step boundaries with checkpoint resume. | IMPLEMENTED | `boltrig/fleet/hatchet_app.py:159 "store=kernel.store,"` | NFR-REL-02 |
| BT-REQ-0941 | An infrastructure exception inside the workflow task body is re-raised so the engine may retry and the logical occurrence stays in flight. | IMPLEMENTED | `boltrig/fleet/hatchet_app.py:162 "# An infrastructure/task exception is not a terminal workflow verdict:"` | FR-WFL-21 |
| BT-REQ-0942 | Every scheduled occurrence re-authorizes the bound human: active user, workspace membership, and live effective grants intersected with the captured ceiling permitting control.workflow.trigger. | IMPLEMENTED | `boltrig/workflows/scheduler_dispatch.py:36 "bounded = current.intersect(schedule.grant_ceiling)"` | FR-WFL-20 |
| BT-REQ-0943 | A schedule created by a caller with no matching active user row persists with observed status needs_action and never runs. | IMPLEMENTED | `boltrig/config/control_workflows.py:199 "observed_reason: str | None = scheduling_authority_not_bound"` | FR-WFL-20 |
| BT-REQ-0944 | A logical occurrence is claimed atomically by (tenant, workflow, scheduled_for) under a lease and carries the deterministic run id wfs_<sha256>. | IMPLEMENTED | `boltrig/workflows/scheduler_cron.py:194 "return f\"wfs_{hashlib.sha256(value.encode()).hexdigest()}\""` | FR-WFL-20 |
| BT-REQ-0945 | Occurrence catch-up is capped at 3 per schedule per cycle and the remainder is skipped forward with reason missed_occurrences_truncated. | IMPLEMENTED | `boltrig/workflows/scheduler.py:33 "MAX_CATCH_UP = 3"` | FR-WFL-20 |
| BT-REQ-0946 | A cron schedule is validated at definition time for field count and IANA timezone, and the parser applies day-of-month OR day-of-week when neither is a wildcard while returning only instants that exist in the target zone. | IMPLEMENTED | `boltrig/workflows/scheduler_cron.py:137 "return day_match or weekday_match"` | FR-WFL-20 |
| BT-REQ-0947 | An occurrence whose workflow snapshot or authority-bearing schedule digest changed is failed with reason occurrence_snapshot_changed. | IMPLEMENTED | `boltrig/workflows/scheduler_dispatch.py:243 "reason=occurrence_snapshot_changed,"` | FR-WFL-21 |
| BT-REQ-0948 | A failed dispatch marks the occurrence retryable while attempts are under 3 and failed thereafter, with reason schedule_dispatch_failed. | IMPLEMENTED | `boltrig/workflows/scheduler_dispatch.py:14 "MAX_DISPATCH_ATTEMPTS = 3"` | FR-WFL-21 |
| BT-REQ-0949 | The scheduler forever-loop derives its overdue count from the stored next_due_at values rather than from the reconcile path, so inaction is distinguishable from idleness. | IMPLEMENTED | `boltrig/workflows/scheduler_loop.py:44 "job is to disagree with the reconcile path when that path is broken"` | - |
| BT-REQ-0950 | The workflow scheduler reconciles exactly one tenant, the worker manifest tenant. | IMPLEMENTED-UNTESTED | `boltrig/api/worker.py:287 "tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT"` | - |
| BT-REQ-0951 | The scheduled dispatch path calls WorkflowLibrary.trigger directly, so it is grant-checked but not HITL-gated per occurrence. | IMPLEMENTED | `boltrig/workflows/scheduler_dispatch.py:170 "descriptor = await workflows.trigger("` | - |
| BT-REQ-0952 | Webhook and channel trigger deliveries dispatch control.workflow.trigger through the kernel chokepoint and can return a pending_human receipt. | IMPLEMENTED | `boltrig/kernel/workflow_trigger_delivery.py:240 "control.workflow.trigger,"` | - |
| BT-REQ-0953 | A trigger authority is always a live re-derivation of a stored human owner or an authenticated channel principal, intersected with the trigger stored grant ceiling. | IMPLEMENTED | `boltrig/kernel/workflow_trigger_delivery.py:81 "bounded = current.intersect(trigger.grant_ceiling)"` | - |
| BT-REQ-0954 | Trigger delivery is idempotent by sha256(source_scope NUL source_event_id) and a repeat returns the recorded receipt as duplicate. | IMPLEMENTED | `boltrig/kernel/workflow_trigger_delivery.py:56 "f\"{source_scope}\\0{source_event_id}\".encode()"` | - |
| BT-REQ-0955 | A trigger event body larger than 256 KiB of canonical JSON is refused with reason event_too_large. | IMPLEMENTED | `boltrig/kernel/workflow_trigger_delivery.py:22 "MAX_TRIGGER_EVENT_BYTES = 256 * 1024"` | - |
| BT-REQ-0956 | The channel intake bridge tries the HITL reply path first and only then delivers workflow triggers, answering 202 with the per-trigger outcomes. | IMPLEMENTED | `boltrig/kernel/channel_workflow_trigger_bridge.py:29 "triggered = await deliver_channel_workflow_triggers("` | - |
| BT-REQ-0957 | A v1 conversational routine is one goal plus one trigger and must contain zero graph steps. | IMPLEMENTED | `boltrig/workflows/routine_contract.py:57 "v1 conversational routines cannot contain graph steps"` | - |
| BT-REQ-0958 | A routine companion_id must be exactly familiar or jarvis and every routine field is closed against unknown keys. | IMPLEMENTED | `boltrig/workflows/routine_contract.py:15 "ROUTINE_COMPANIONS = frozenset({familiar, jarvis})"` | - |
| BT-REQ-0959 | Each routine occurrence requires an authenticated human owner and allocates one deterministic owner-scoped conversation before enqueue, re-read to verify all seven binding fields. | IMPLEMENTED | `boltrig/workflows/library.py:120 "raise PermissionError(routine_conversation_binding_mismatch)"` | - |
| BT-REQ-0960 | Routine trigger inputs and human answers enter the model wrapped as explicitly untrusted data. | IMPLEMENTED | `boltrig/fleet/routine_run.py:56 "trigger_data = wrap_untrusted("` | - |
| BT-REQ-0961 | A routine turn runs through the ordinary chat runtime under the triggering context grants, workspace and scope; it never mints authority of its own. | IMPLEMENTED | `boltrig/fleet/routine_run.py:240 "grants=run.context.grants,"` | - |
| BT-REQ-0962 | A routine turn idempotency key is derived from the occurrence run id and, on resume, the exact HITL request and response ids. | IMPLEMENTED | `boltrig/fleet/routine_run.py:231 "f\"routine:{run.occurrence_run_id}:resume:{decision.request.id}:\""` | - |
| BT-REQ-0963 | Routine completion is checkpointed before the optional notification, and a notification failure cannot change the recorded outcome. | IMPLEMENTED | `boltrig/fleet/routine_run.py:158 "# The chat is canonical. Record completion before the optional notification"` | - |
| BT-REQ-0964 | Routine inputs are capped at 64 KiB of JSON and must be JSON serialisable. | IMPLEMENTED | `boltrig/fleet/routine_run.py:19 "_INPUT_BYTES_MAX = 64 * 1024"` | - |
| BT-REQ-0965 | parse_skill validates id, semver version, string types and that context_requirements is a valid Draft 2020-12 schema, reporting every error at once. | IMPLEMENTED | `boltrig/skills/schema.py:115 "Draft202012Validator.check_schema(context_requirements)"` | - |
| BT-REQ-0966 | The governed control.skill.upsert path performs none of the parse_skill validations. | IMPLEMENTED-UNTESTED | `boltrig/config/control_operations.py:71 "tool_grants=params.get(tool_grants, []),"` | - |
| BT-REQ-0967 | resolve_skill merges an extends chain parent-first: prompts concatenated, grants order-preserving union, requirements merged, base never mutated. | IMPLEMENTED | `boltrig/skills/loader.py:108 "if grant not in tool_grants:  # order-preserving union"` | - |
| BT-REQ-0968 | A cyclic extends chain raises in the skills loader but silently resolves to a partial chain in the fleet spawn resolver. | IMPLEMENTED | `boltrig/fleet/spawn_skills.py:81 "if skill_id in seen:"` | - |
| BT-REQ-0969 | A skill tool_grants list is a request, not an award: the spawner intersects it with the caller grants and any explicit ceiling. | IMPLEMENTED | `boltrig/fleet/spawn.py:169 "child_grants = GrantSet.of(allow=list(intake.tool_grants)).intersect("` | SEC-07 |
| BT-REQ-0970 | skill.search returns selection metadata only and never the prompt_fragment body, clamped to at most 100 results. | IMPLEMENTED | `boltrig/skills/shelf.py:145 "description: s.description or s.id,  # fall back to the id as a label"` | FR-SKILL-01 |
| BT-REQ-0971 | skill.load validates the supplied job context against the inheritance-merged requirements and raises ContextRequirementsUnmet on any mismatch. | IMPLEMENTED | `boltrig/skills/shelf.py:194 "raise ContextRequirementsUnmet("` | FR-SKILL-02 |
| BT-REQ-0972 | skill.load returns the resolved tool_grants as data and grants nothing, so loading a skill can never escalate the caller. | IMPLEMENTED | `boltrig/skills/shelf.py:200 "# tool_grants are returned as DATA (what the skill wants) - loading does"` | SEC-57 |
| BT-REQ-0973 | All three skill shelf verbs are consequence low and run the ordinary dispatch chokepoint, tenant-scoped. | IMPLEMENTED | `boltrig/skills/shelf.py:83 "consequence=low,"` | SEC-57 |
| BT-REQ-0974 | The boot skill loader reads only libraries/skills, skips non-mapping documents, and a load failure is logged and swallowed so boot continues. | IMPLEMENTED | `boltrig/api/bootstrap.py:64 "_SKILLS_DIR_CANDIDATES = (/app/libraries/skills, libraries/skills)"` | - |
| BT-REQ-0975 | select_locale and the base@locale variant convention are unreachable: no caller exists and no variant file ships. | DEAD | `boltrig/skills/loader.py:134 "async def select_locale("` | - |
| BT-REQ-0976 | libraries/workflows/*.yaml is authoring data that no runtime path loads. | IMPLEMENTED | `libraries/workflows/sleep-distillation-craft.yaml:13 "NOTE this file is authoring data, not a boot-time load"` | - |
| BT-REQ-0977 | libraries/prompts/*.md is referenced by no code in the tree. | DEAD | `docs/architecture/engine-components.md:369 "prompt data also under `libraries/prompts/`"` | - |
| BT-REQ-0978 | libraries/emotion/*.yaml loads into frozen dataclasses, any parse failure returns None so the feature stays off, and its event map consumes the interpreter own workflow_step events. | IMPLEMENTED | `boltrig/emotion/tables.py:27 "_TABLE_DIR_CANDIDATES = (/app/libraries/emotion, libraries/emotion)"` | EMO-5 |
| BT-REQ-0979 | schemas/ holds versioned external contracts under <contract>/<version>/ and the Codex protocol pin is digest-verified by a gate rather than trusted. | IMPLEMENTED | `scripts/check_codex_protocol.py:26 "PIN_SCHEMA_SHA256 = 66ab7534f29e1ee7c065eb15c799d5f6e93fdd1d0ba86c262c3842a6a8f3d0c8"` | - |
| BT-REQ-0980 | schemas/emotion/1.0.0/phenotype.schema.json is documentary: no code loads it and no gate validates against it. | DEAD | `schemas/emotion/1.0.0/phenotype.schema.json:3 "The atomically-written phenotype snapshot the emotion relay publishes"` | - |
| BT-REQ-0981 | boltrig.work.normalise is the single translation from any raw source payload to a WorkItem, preserves the raw payload verbatim, and derives convergent mode from a deterministic weighted-facet confidence score at threshold 0.7. | IMPLEMENTED | `boltrig/work/queue.py:28 "CONVERGENT_THRESHOLD = 0.7"` | - |
| BT-REQ-0982 | WorkItemStore, its legal-transition table, its status compare-and-swap and write_back_discovered have no caller anywhere in the tree, and the fleet writes work-item status directly instead. | DEAD | `boltrig/work/store.py:96 "if not await self._store.transition_work_item_status("` | - |
| BT-REQ-0983 | The QueueAdapter protocol and InternalQueueAdapter have no implementation or caller outside their own module. | DEAD | `boltrig/work/queue.py:69 "class QueueAdapter(Protocol):"` | - |
| BT-REQ-0984 | Channel provenance is kernel-authored: four fields are derived after authentication, provider identifiers are bounded to 512 chars and kept out of the public projection. | IMPLEMENTED | `boltrig/work/channel_provenance.py:64 "item.constraints.pop(CHANNEL_MESSAGE_PROVENANCE_KEY, None)"` | CHAN-PROV-01 |
| BT-REQ-0985 | The workflow learning leg never fires: the pump keys on an outcome field that no production department head writes. | DEAD | `boltrig/fleet/pump.py:683 "wf = outcome.get(GENERATED_WORKFLOW_KEY)"` | - |
| BT-REQ-0986 | select_or_generate_workflow and WorkflowLibrary.match have no production caller; production selects a workflow by explicit id. | DEAD | `boltrig/workflows/library.py:180 "NOT REACHABLE FROM PRODUCTION."` | - |
| BT-REQ-0987 | Workflow synthesis uses a reasoning runtime when one is supplied and falls back to the fixed five-stage deterministic pipeline on any failure. | IMPLEMENTED | `boltrig/workflows/generator.py:196 "if runtime is None:"` | US-WFL-02 |
| BT-REQ-0988 | harvest_reuse_signal feeds free feedback only into memory reweighting through the chokepoint under the caller own context, and swallows every failure. | IMPLEMENTED | `boltrig/workflows/signals.py:56 "memory, memory.improve,"` | - |
| BT-REQ-0989 | control.workflow.upsert, publish, schedule, trigger and execute are HIGH consequence with only draft.upsert LOW, and the approval for a trigger, execute or schedule binds the exact definition snapshot digest re-checked before the mutation. | IMPLEMENTED | `boltrig/config/control_approval_workflows.py:108 "fingerprint = {workflow_sha256: workflow_snapshot_digest(workflow)}"` | - |
| BT-REQ-0990 | The only definition validations performed at authoring time are the loop contract and the routine contract. | IMPLEMENTED | `boltrig/config/control_workflows.py:69 "require_valid_loop_contract(definition)"` | - |
| BT-REQ-0991 | A workflow definition has no maximum step count and the interpreter maintains no recursion depth counter. | IMPLEMENTED-UNTESTED | `boltrig/config/control_workflow_schema.py:79 "steps: {type: array, items: _STEP},"` | - |
| BT-REQ-0992 | Draft rows are excluded from the runnable shelf but not from the workflow read routes, which filter only on workspace. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/workflows.py:129 "if _visible(workflow, p.active_workspace_id)"` | - |
| BT-REQ-0993 | The workflow list route projects each stored routine through routine_spec, which raises rather than degrading on a malformed contract. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/workflows.py:49 "spec = routine_spec(workflow.definition)"` | - |
| BT-REQ-0994 | BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL defaults to 15.0 seconds; a non-positive value disables the scheduler and an unparseable value falls back to the default. | IMPLEMENTED | `boltrig/workflows/scheduler_cron.py:177 "BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL,"` | - |
| BT-REQ-0995 | The queued context envelope carries the caller grants verbatim and nothing re-derives them when the worker later executes the task. | IMPLEMENTED-UNTESTED | `boltrig/models/context.py:91 "grants=GrantSet.of(list(grants.get(allow) or []), list(grants.get(deny) or []))"` | - |
| BT-REQ-0996 | The DAG-parity semantics (error strategies, retry, OR-join, multi-case branch, parallel loops, approval branch handles) are covered by 28 tests that bind no invariant id. | IMPLEMENTED | `tests/unit/test_workflow_parity.py:1 "Graphon-parity control-flow semantics for the workflow interpreter."` | - |
| BT-REQ-0997 | The shipped skill library is gated: no wildcard over a consumed namespace, no expansion above MAX_KERNEL_TOOLS, and no granted namespace that resolves to zero registered verbs. | IMPLEMENTED | `tests/security/test_skill_grant_expansion.py:53 "_SKILLS = _REPO / libraries / skills"` | - |
| BT-REQ-0998 | The shipped workflow lead-followup-cadence.yaml fails the loop contract and therefore cannot be persisted through control.workflow.upsert. | IMPLEMENTED-UNTESTED | `libraries/workflows/lead-followup-cadence.yaml:34 "loop_bindings:"` | - |
| BT-REQ-0999 | The interpreter per-step durable boundary is a SEAM, not a durable engine step: HatchetExecutor.run_step awaits the callable directly because the installed SDK exposes no public durable child-step API, so per-step recovery rests on task retry plus checkpoints plus the per-step idempotency key. | SEAM | `boltrig/fleet/workers.py:159 "Await ``fn`` directly. This is NOT a durable engine step"` | NFR-REL-02 |
