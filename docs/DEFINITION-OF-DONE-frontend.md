# Definition of Done - the front-end experience backlog (items 1-6)

Spec: `requirements-frontend-experience.md`. The "bring Boltrig to life" arc. All
six backlog items are built, behind the green gate, with the kernel never learning
the UI exists. This is the honest implemented-vs-seam ledger for the whole arc.

## What shipped (in leverage order)

1. **Event backbone (R10).** The dispatch chokepoint emits `tool_call` /
   `tool_result` / `hitl` and the spawner emits `subagent`, fail-safe, run-keyed
   (SEC-55). Real agent activity now flows to the relay the UI already renders.
2. **Router + Run drawer (R11).** A bespoke hash-router (no dep) + a global
   `run_id`-keyed Run drawer (live events via the shared chat renderer + the audit
   tree + inline HITL), cross-linked from every surface; `GET /v1/runs/{id}/events`
   tenant-scoped (SEC-56). One run is traceable and shareable.
3. **Live run canvas (R12).** The workflow graph lights up node-by-node from
   per-step `workflow_step` events (FR-EVT-04); the run is bound to one coherent
   stream.
4. **Capability-aware Home (R13).** The default landing - needs-you / recent runs
   / work-in-flight / quick-start / what-I-can-do (from the scoped capabilities) -
   plus an identity chip over the dev sign-in.
5. **Registry canvas (R13).** Nouns/verbs/bindings as a React Flow tree; `web.fetch`
   first-class as a governed node; List/Tree toggle.
6. **Three-plane nav + Dev console + Insight run filter (R13).** Tabs grouped into
   Capability/Orchestration/Activity (routes/gates unchanged); a Dev console
   surfacing `invoke`/`spawn`/`adapterSource` (effective_grants as no-escalation
   evidence); the `run` audit-search filter.

## Doctrine adherence (per AGENTS.md)

- **The kernel never learned the UI exists.** Every surface reads the same scoped
  registry / event relay / chokepoint; no UI special-casing in the core.
- **Structured streaming preserved.** Tool streams are never collapsed into prose;
  verb outputs stay data; rendering lives in the head (the extracted `chatTurn`
  renderer + the canvas). The relay is re-attachable.
- **Dependency discipline.** Recorded calls: ADOPT React Flow (graph-shaped data,
  spec-blessed) and a bespoke hash-router (zero dep, mirrors `identity.ts`);
  REJECT Vercel AI Elements / a global-state lib / a component framework
  (consolidation). No new dependency entered the UI beyond `@xyflow/react`.
- **One integration bug caught at the boundary** (the one-writer rule working): the
  `subagent` event field `run_id` vs the UI's `child_run_id` - tsc-invisible,
  reconciled at the source (R12).

## Gate (green throughout)

- `pytest`: **136 passed, 14 skipped**.
- `check_invariants.py`: **declared=82, bound_tests=110, binding_debt=0, PASS**.
- New invariants this arc: SEC-55, SEC-56, FR-EVT-01/02/03/04 (events + the run
  stream), plus FR-GW-01 (Bifrost wiring). UI build green; no new npm dependency
  beyond React Flow.

## Honest seams (still seams - do not describe as wired)

- **`reasoning_delta`** is rendered by the UI but not emitted: it needs the Pi
  sidecar (a separate service) to stream its reasoning to the relay. The chat /
  Run drawer / canvas will light up further once it does.
- **Bifrost** is now wired into the stack (the compose service, FR-GW-01) and is
  one env line from active, but it is NOT running here - no provider keys, and
  cache-hit warmth is unproven (Pi spec sequencing step 4). The seam guarantee
  (SEC-47: per-conversation pinning, sensitive-never-routed) holds; the running
  gateway does not.
- **Real sign-in** is the R4 OIDC/PAT resolver behind a dev-header default; a true
  browser OIDC flow needs a live IdP (Principal dep).
- **Live cross-worker run state** uses the in-process relay; a multi-replica
  deployment swaps it for Redis pub/sub behind the same interface (noted in
  `events.py`).

This closes the front-end experience spec. What I verified: the offline gate
(pytest + invariants + ruff) and the UI build, every round. What I did NOT verify:
anything requiring a running Bifrost, a live IdP, a live Hatchet engine, or the Pi
sidecar streaming reasoning - those remain seams by design.
