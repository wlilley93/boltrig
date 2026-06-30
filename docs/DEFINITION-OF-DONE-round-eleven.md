# Definition of Done - Round Eleven (the router + the Run drawer)

Spec: `requirements-frontend-experience.md` S4 + backlog item 2 - "turn the islands
into a system." The eleven panels had no router, no deep-linking, and no
cross-linking: a run was visible as a chat turn, a Kanban card, an audit tree, a
workflow record, and Insight rows, but nothing connected those views of the SAME
run. Round Eleven gives the run a home and a URL.

## What shipped

### Beat A - the run-events subscription endpoint (backend)

A run could not be watched unless you were the one running it (`POST /v1/chat`).

- `kernel/app.py`: `GET /v1/runs/{run_id}/events`. Tenant-scoped (SEC-56) - a run is
  streamable only if it produced audited activity in the caller's tenant
  (`audit_query`), else 404, no cross-tenant leak. `follow=0` (default) yields the
  current snapshot then ends (deterministic, historical inspection); `follow=1`
  subscribes to the relay (backlog replay + live until close).
- `kernel/events.py`: `EventRelay.snapshot(stream_id)` - a point-in-time backlog read.
- `ui/src/api/client.ts`: `streamRunEvents(runId, onEvent, {follow})` mirroring
  `streamChat` (GET SSE, same frame parser).

### Beat B - the hash router + the global Run drawer (frontend)

- `ui/src/router.ts` (new): a bespoke hash-router store mirroring `identity.ts`
  (module snapshot + listener Set + `useSyncExternalStore`), source of truth is
  `window.location.hash`. `parse()` turns `#/<tab>[/<param>][?run=<id>]` into
  `{tab, param, runId}`; the Run drawer is an orthogonal `?run=` overlay so opening
  it keeps the active tab. Helpers `navigate` / `openRun` / `closeRun` /
  `useRoute`. ~95 lines, ZERO new dependency (the recorded consolidation call).
- `ui/src/panels/chatTurn.tsx` (new): the chat event renderer (`normalizeEvents` +
  `TurnExtras`: tool / reasoning / sub-agent / inline-HITL cards) extracted from
  `ChatPanel` for reuse - one renderer, two surfaces.
- `ui/src/panels/RunView.tsx` (new): the global Run drawer keyed by `run_id`. It
  follows `streamRunEvents(runId, {follow:true})` rendered through the shared chat
  renderer, shows the execution tree from `api.auditTree(runId)` (the ported
  `AuditNodeView`) + a cost/status summary, and answers inline HITL via
  `api.respondHitl`. A `subagent` event becomes a run handle: clicking it re-keys
  the drawer to the child run - the consumer-side run nesting the Round Ten
  backbone enables. A 404 renders a clean "not found / not in your scope" notice
  (authz stays server-side, the AdminPanel pattern).
- `ui/src/App.tsx`: the active tab is driven by `useRoute()` (back/forward + deep
  links work), with the role-gate filtering kept; `<RunView/>` is mounted globally.
- Cross-linked to `openRun` everywhere a `run_id` shows: Kanban cards (replacing
  the old bespoke audit drawer), Chat sub-agent cards, Insight runs + audit-search
  rows, Approvals cards, and the Studio/Canvas workflow run records. A reusable
  `RunLink` in `shared.tsx`.

## Invariants (binding-debt 0)

Two new, bound (`tests/security/test_round_eleven.py`): **SEC-56** (the run-events
stream is tenant-scoped, cross-tenant 404), **FR-EVT-03** (snapshot frames +
unknown-run 404).

## Gate (green)

- `pytest`: **133 passed, 14 skipped**.
- `check_invariants.py`: **declared=80, bound_tests=107, binding_debt=0, PASS**.
- `ruff`: clean. UI `npm run build`: green, no new dependency.

## What this unlocks

One run is now traceable and shareable across the whole product: a Kanban card, an
Insight row, an approval, a chat sub-agent, and a workflow record all open the same
drawer, and the drawer descends the run tree by following sub-agent links. This is
the connective tissue the spec's diagnosis called for, and it unblocks backlog item
3 (the live run canvas), which reuses the same per-run event subscription.
