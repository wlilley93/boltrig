# Definition of Done - Round Ten (the event backbone)

Spec: `requirements-frontend-experience.md` S6 + backlog item 1 - the highest-
leverage move identified by the grounding: the rich-event plumbing and the
renderer both exist (`ChatPanel` renders tool/reasoning/subagent/HITL; the
`EventRelay` supports replay/re-attach), but the production path published only a
single summary `text_delta`. Round Ten makes real agent activity flow.

## What shipped

Run events are now emitted at the two natural boundaries, as a pure observability
side-channel that never touches the dispatch decision or its 10-step sequence.

- **The dispatch chokepoint** (`kernel/dispatch.py`): the outer `invoke` wrapper -
  the same place audit is written - now emits, keyed by `context.run_id`:
  - `tool_call` before execution (verb, noun, input),
  - `tool_result` after (verb, status, output on success / no output on failure),
  - `hitl` when the call pauses for a human (verb + request id).
  Emission goes through `_emit`, which is fail-safe: no relay or no run_id => no-op;
  a relay error is swallowed so observability can never break the chokepoint (P9).
- **The spawner** (`fleet/spawn.py`): emits a `subagent` event on the PARENT run's
  stream when a child is spawned (task + skills + child run_id + capability), so a
  consumer can follow the spawn into the child's stream. Also fail-safe.
- **Wiring** (`kernel/__init__.py`): the Kernel passes its `EventRelay` to the
  Dispatcher.

The end-to-end link is intact: `PiRuntime` issues its run-scoped MCP token with
`run_id=context.run_id`, and the MCP face preserves it, so the agent's nested verb
calls dispatch under the child run and emit to the child's stream. The `subagent`
event bridges parent -> child.

## Invariants (binding-debt 0)

Three new, all bound (`tests/security/test_round_ten.py`):

- **FR-EVT-01** a verb under a run publishes a paired `tool_call` + `tool_result`;
  a failed call reports status with no output leak.
- **FR-EVT-02** events are a pure side-channel - a relay failure never breaks a
  call, no run_id publishes nothing, and a paused call surfaces a `hitl` event.
- **SEC-55** events are run-keyed and credential-free - a verb's events publish
  ONLY to its own run's stream and never carry credential material.

## Gate (green)

- `pytest`: **131 passed, 14 skipped** (+6).
- `check_invariants.py`: **declared=78, bound_tests=105, binding_debt=0, PASS**.
- `ruff check nankle scripts`: clean.

## Design note: one run, one stream (kernel stays clean)

Events are keyed strictly by the invoking run (SEC-55); the kernel never fans an
event up to a parent run. Nesting is a CONSUMER concern: a consumer that sees a
`subagent` event learns the child run_id and subscribes to that stream too. This
keeps the chokepoint clean and is the correct seam for the next backlog item (the
Run drawer / router), which renders a run tree by following `subagent` links into
child streams.

## Honest seams (deferred, per the backlog)

- **Consumer-side fan-in.** `ChatPanel` today subscribes to the turn's run stream;
  it will now see the turn's own `subagent` event, but following that into the
  child run's tool/result stream is backlog item 2 (the Run drawer / router), where
  run nesting is modelled. The backbone emits correctly per-run; the consumer
  catches up next.
- **`reasoning_delta`.** Emitting model reasoning requires the Pi sidecar (a
  separate service) to stream its reasoning to the relay; deferred to a sidecar
  round. The renderer for it already exists.
- **Live run canvas (S5.3).** Now unblocked - the events it needs exist; building
  the canvas run-mode view is backlog item 3.

This is backlog item 1 done: real `tool_call` / `tool_result` / `hitl` / `subagent`
events now flow to the relay the UI already knows how to render - the plumbing is
no longer dark.
