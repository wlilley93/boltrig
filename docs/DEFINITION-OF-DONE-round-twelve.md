# Definition of Done - Round Twelve (the live run canvas)

Spec: `requirements-frontend-experience.md` S5.3 + backlog item 3 - the same node
graph lighting up as the interpreter executes. The payoff of the event backbone:
execution becomes visible.

## What shipped

### Beat A - per-step events + one-stream coherence (backend)

- `workflows/interpreter.py`: emits a `workflow_step` event per step (`step_id` +
  `running` / `ok` / `failed` / `skipped` / `error`) on the run's stream, as a
  fail-safe side-channel (no relay / no run_id => no-op; publish error swallowed,
  P9). The canvas lights each node by matching `step_id` to the node id.
- It also binds the whole run to one stream: steps now dispatch under a context
  keyed to the run id (`rid`, via `dataclasses.replace`), so the steps' tool
  events, the `workflow_step` events, and the audit rows all cohere on the one
  stream the canvas / Run drawer follow. This also fixed a latent bug: a route-run
  previously dispatched under `context.run_id=None`, emitting no events and writing
  orphaned audit rows; the workflow run's audit tree is now populated.

### Beat B - the live run canvas (frontend)

- `ui/src/panels/WorkflowRunCanvas.tsx` (new): a read-only sibling of
  `WorkflowCanvas` (chosen over a mode-prop to avoid interleaving run-overlay
  state with the large editing component). It imports the shared graph helpers
  (`stepsToGraph`, `extractSteps`, `deriveKind`, `nodeTypes`) - zero graph-logic
  duplication - loads the workflow's static graph, then overlays per-node run
  state from the live `workflow_step` events (`node.id === step_id`).
- Status -> class: no event yet => `pending` (dimmed); `running` => pulsing accent
  (`wf-node--run-running`, the pulse neutralised under the existing reduced-motion
  media block); `ok`/`failed`/`error`/`skipped` => the `--ok`/`--down`/`--warn`
  tokens. Completion is detected when `streamRunEvents(follow:true)` resolves
  (stream closed); any still-`running` node is coerced back so the pulse stops.
- Wiring: the Workflow Studio Run button opens the live canvas on the returned
  `run_id`; an "existing run id" input opens the live canvas for any prior run;
  clicking a node opens the Run drawer (`openRun`) for that run's event log + tree.
- `ChatWorkflowStep` added to the `ChatEvent` union.

### Integration fix (the one-writer catch)

The UI read `subagent.child_run_id` but the backend emitted `run_id` - a
tsc-invisible runtime break that would have left the sub-agent drawer link
undefined. Reconciled at the source: the spawner now emits `child_run_id` (the
clearer name, matching the typed event). Verified the other live events match
(`workflow_step.step_id/status`, `tool_call.verb/input`, `tool_result.verb/status/
output`, `hitl.hitl_request_id`).

## Invariants (binding-debt 0)

One new, bound (`tests/integration/test_round_twelve.py`): **FR-EVT-04**
(per-step events on the run stream + one-stream coherence, incl. skipped
descendants).

## Gate (green)

- `pytest`: **135 passed, 14 skipped**.
- `check_invariants.py`: **declared=81, binding_debt=0, PASS**.
- `ruff`: clean. UI `npm run build`: green, no new dependency.

## What this completes

Backlog items 1-3 are done: events flow (R10), the run has a home and a URL
(R11), and the workflow graph now visibly executes node-by-node (R12). A run is
streamed, traceable, and animated. Remaining backlog: item 4 (home / entry +
real sign-in), item 5 (the registry canvas), item 6 (cross-linking polish).
`reasoning_delta` still awaits the Pi sidecar streaming its reasoning.
