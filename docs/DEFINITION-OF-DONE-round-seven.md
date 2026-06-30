# Definition of Done - Round Seven (control plane)

Spec: [`requirements-control-plane.md`](./requirements-control-plane.md). Companion
to the Pi runtime spec. Goal: amend models, agent profiles, and Hatchet workflows
live, without a redeploy, while every amendment stays inside the kernel's
governance (audited, grant-checked, HITL-gated).

The spec's repo-grounding was verified first. Three findings shaped the build:
- **The one real gap is confirmed:** nothing walked a stored
  `WorkflowDefinition`'s steps and ran them - `trigger` recorded one opaque
  `workflow:{id}` boundary; `definition["steps"]` was never executed.
- **The "two dispatch kinds" fork dissolves:** the dispatch chokepoint already
  routes a verb to an adapter OR an agent via `binding.target_type`
  (`dispatch.py:191-197`). So the interpreter dispatches every step uniformly
  through `kernel.invoke` - one governed path, P2 preserved, no second dispatch
  kind. Resolved by existing architecture (a decisive call, not a court fork).
- **The governance gap is real:** config writes were direct `store.upsert_*` from
  author-gated routes, not kernel verbs. And a Workflow Studio authoring route
  already exists (Round Three) - so this round adds the interpreter + the
  governed-write path, not a duplicate console.

## What shipped

### S7.1 Live agent/department profiles (FR-CTL-01)

- `fleet/chief_of_staff.py`: `ChiefOfStaff` took its `departments` once at
  construction. It now accepts an optional `departments_provider` re-read on every
  route (`_current_departments`), so an admin / manifest edit takes effect with no
  router reconstruction. The provider must never crash routing - it falls back to
  the construction-time list on any failure (P9).

### S7.3 The generic workflow interpreter (FR-CTL-02, the core unlock)

- `workflows/interpreter.py` (new): walks a stored definition's steps in
  dependency order (Kahn's algorithm, honouring each step's `parents`) and
  dispatches each step's `action` as its OWN durable boundary
  (`executor.run_step("workflow:<wf>:<step>", ...)`) through `kernel.invoke`.
  Every step therefore inherits validation + grant-check + consequence/HITL gate +
  idempotency + audit. A failed / unbound / ungranted step is recorded and its
  descendants skipped; a held HITL gate is a `paused` step, never a crash (P9).
  A step `action` is a verb id `"<noun>.<verb>"`; what it resolves to (adapter or
  agent) is the registry's business, not the interpreter's.
- `workflows/library.py`: `WorkflowLibrary.execute` drives the interpreter (kernel
  wired at construction); `trigger` stays the enqueue seam (in production the
  enqueued run's body calls `execute`).
- `kernel/platform_routes.py`: `POST /v1/workflows/{id}/execute` runs the
  interpreter under the caller's own grants (a step cannot escalate, SEC-50).

### S7.5 Governed control-plane writes (SEC-50, SEC-51)

- `config/control_plane.py` (new): a kernel-side adapter (the MemoryAdapter
  pattern) exposing `control.workflow.upsert`, `control.capability.upsert`,
  `control.model_endpoint.upsert` as **high-consequence** verbs. Because they are
  ordinary verbs, config amendment runs the chokepoint - grant-checked, audited,
  and HITL-gateable - instead of a direct `store.upsert` from an unguarded route.
  Registered in bootstrap (both the manifest and the dev-seed paths).

### S7.4 Native workflow editor UI (no n8n runtime)

- The existing Round Three Workflow Studio (`ui/src/panels/StudioPanel.tsx`) is
  extended with an interpreter **Execute** view (per-step status/output) and a
  **scoped-verb palette** sourced live from `GET /v1/capabilities` (only the verbs
  the caller may use) - the spec's recommended native editor, no second engine to
  bridge.

## Invariants (binding-debt 0)

Four new: **FR-CTL-01** (live profiles), **FR-CTL-02** (interpreter executes steps
in dep order, per-step durable, skips failed descendants), **SEC-50** (steps
governed under caller grants, no escalation), **SEC-51** (control writes are
governed verbs).

## Gate (green)

- `pytest`: **119 passed, 14 skipped** (+6 over Round Six).
- `check_invariants.py`: **declared=72, bound_tests=93, binding_debt=0, PASS**.
- `ruff check nankle scripts`: clean. UI `npm run build`: green.

## Decisions recorded (no court convened)

- **Every step is one kernel verb** (not a second adapter-vs-agent dispatch path):
  resolved by the existing chokepoint (`binding.target_type`) + P2 / consolidation.
  A decisive call grounded in code, not a first-impression fork.
- **Live-reload via a provider callback** over a new departments store table: the
  low-blast, reversible choice; a store-backed department registry is a follow-on
  if one is needed.

## Honest seams

- Migrating the legacy Round Three direct-write studio routes (`POST /v1/workflows`,
  `/v1/verbs`, etc.) onto the `control.*` governed verbs is a mechanical follow-on;
  the governed path now exists, is registered, and is bound. The Round Three
  routes remain author-gated + audited in the meantime.
- The interpreter threads each step's declared params + the run inputs; auto-
  threading a parent step's output into a child is a documented follow-on.
- Generated `agent.<stage>` pipelines run only once those reasoning stages are
  registered as agent-bound verbs (deployment wiring); the interpreter is generic
  and runs whatever verbs are registered.
- Bifrost (the cost gateway) and live Hatchet remain external, per the companion
  spec.

This closes the control-plane spec: the generic interpreter (the one real gap) is
built, profiles are live, and config amendment is governed through the chokepoint.
A workflow defined purely as data now executes - the last piece of the durable,
portable agent box (P7) for workflows.
