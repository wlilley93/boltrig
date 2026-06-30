# Nankle front-end experience spec (Round Nine) - bringing Nankle to life

The whole-product front-end spec. Not a React Flow canvas in isolation and not an
n8n clone: the experience that makes the governed kernel, the fleet, the memory,
and the node system feel like one living system. Grounded against the actual
`ui/` (11 panels, ~1634 lines of bespoke CSS, `@xyflow/react`) and the backend
route surface as of Round Eight.

- **Status:** Draft, code-grounded.
- **Companion to:** the workflow editor / control plane / node system specs and
  the system overview. Those defined capability; this defines the experience over
  it.

## 1. The diagnosis: why it does not yet feel alive

Three findings from grounding the current UI, in priority order. Each is the real
reason the system reads as "a kernel with panels around it" rather than a product.

1. **The rich-event plumbing is built end to end, but nothing flows through it.**
   `ChatPanel`'s `normalizeEvents` reducer already renders the full vocabulary -
   `text_delta`, `reasoning_delta`, `tool_call` / `tool_result` (paired), `subagent`,
   `hitl` inline, `message_start/end` - and the `EventRelay` already supports a
   bounded replay backlog and re-attach. But the production turn executor
   (`fleet/chat.py::build_turn_executor`) publishes only ONE `text_delta` carrying
   the spawn summary. A repo-wide grep finds no backend code emitting
   `reasoning_delta` / `tool_call` / `tool_result` / `subagent`. **The single
   highest-leverage move in the whole product is to make real agent events flow:
   the UI to display them already exists.**

2. **The eleven panels are islands, not a system.** There is no router, no
   deep-linking, and almost no cross-linking. A run is visible as a chat turn, as a
   Kanban card, as an audit tree, as a workflow run record, and as audit rows in
   Insight - but nothing links those views of the SAME run to each other. You
   cannot click a chat turn and see its Kanban card, or click an approval and land
   on the paused step. The unit that should tie the product together - the run -
   has no home.

3. **Nothing is live; "liveness" is polling, and you log in by typing a header.**
   Kanban polls every 10s, Approvals 8s, Router 15s; the workflow canvas shows a
   post-hoc run record, never a node lighting up as it executes. And identity is a
   dev-only header bar (`identity.ts`) defaulting to a full org-admin - there is no
   entry experience, no sense of "who am I and what can I do here".

The good news the grounding also surfaces: the hard parts are done. Governed
execution, the interpreter, memory, the studios, the audit tree, the canvas
round-trip, multi-axis theming, and the event relay all exist. This spec is mostly
about **connecting and animating what is already there**, not new capability.

## 2. The product thesis

**Nankle is a governed agent operating system.** The front end should present it as
one, organised into three planes that mirror the kernel and read top-to-bottom as
"define -> compose -> watch":

- **The Capability plane (define):** what the organisation's agents CAN do - nouns,
  verbs, bindings, adapters, skills, models. The registry.
- **The Orchestration plane (compose):** how capability is wired into behaviour -
  the workflow canvas, triggers (chat / cron / webhook), agent nodes. The node
  system.
- **The Activity plane (watch):** what is happening and what happened - chat, the
  live run view, Kanban, approvals, the audit/execution tree, cost, memory.

The **node system is the spine** that runs through all three: the same node grammar
defines capability (registry tree), composes behaviour (workflow DAG), and
animates activity (the live run canvas). One visual language, three jobs.

## 3. Separation of concerns (standing instruction to the implementing agent)

Carried from the node-system spec and binding on every section below. Keep three
concerns strictly separate; never let one do another's job.

- **Front-end concerns.** Render nodes, edges, forms, the chat stream, run state.
  Hold local interaction state (drag, zoom, selection, unsaved drafts). Serialise
  to/from the EXACT JSON the backend already expects. Display what the backend
  returns faithfully. **Never hold a client-side copy of authorization** - the
  server's denial (403) is authoritative; the UI shows it, never anticipates it.
  `AdminPanel.tsx` is the reference pattern.
- **Agent concerns.** Reasoning about which granted verb to call, the tool loop,
  and the event stream belong to the runtime (Pi). The front end never simulates,
  predicts, or pre-computes what an agent node will do - it displays what an actual
  run reports. The runtime is unaware it is being visualised.
- **Kernel concerns.** All authorization - grants, the dispatch chokepoint, HITL,
  audit - stays in the kernel. The node palette is populated from the kernel's
  scoped registry (`/v1/capabilities`), never a separately maintained list. The
  kernel never special-cases a call by which surface triggered it. **If building
  this spec ever requires the kernel to know about the UI, stop and reconsider.**

## 4. The connective tissue: the run as the unit of continuity

The one structural change that turns islands into a system. Every meaningful thing
in Nankle already carries a `run_id` (chat turns mint one; work items set
`hatchet_run_id`; audit rows, workflow run records, and HITL requests all reference
it). The front end must treat **the run as a first-class, linkable object**.

- **A client-side router + URL state (the one new front-end dependency, S10).** Every
  primary view gets a URL: `/chat/:conversationId`, `/runs/:runId`, `/work`,
  `/canvas/:workflowId`, `/registry`, `/approvals`, `/insight`, `/admin/:section`,
  `/memory`, `/settings/:section`. Deep-linking and back/forward become possible;
  a run is shareable.
- **The Run drawer - one component, reachable from everywhere.** A `RunView`
  keyed by `run_id` that shows: the live event stream (or replay), the execution
  tree (`/v1/audit/tree/{run_id}`), the per-step workflow record if it was a
  workflow, cost, and any HITL request on it. Every surface that shows a `run_id`
  (Kanban card, chat turn, Insight row, workflow run, approval) links to it. This
  is the spine of cross-navigation: one run, traceable from message -> work item
  -> workflow run -> per-step audit -> the verbs it called.
- **Consistent entity links.** A verb id anywhere links to its registry node; a
  skill chip links to the skill; an actor links to its runs; a workflow id links to
  its canvas. Wherever an id renders, it is a link to that id's home.

## 5. The spine: the node system as three connected canvases

One node grammar (`@xyflow/react`, already adopted), three modes. Node kind is
always derived from the kernel's binding (`binding.target_type`), never a separate
list (separation of concerns, kernel plane).

### 5.1 The Registry canvas (Capability plane) - a tree, not a DAG

Where capability is defined. Nouns -> verbs -> bindings, hierarchical (a verb
terminates in exactly one binding: an adapter or an agent). Replaces / augments the
flat `RouterPanel` and the form-based Router sub-tab of `StudioPanel`.

- Nodes: noun (group), verb (with consequence badge + live adapter health), binding
  (adapter or agent target). Credentials are shown as references only, never values
  (the `AdminPanel` rule).
- Editing inline maps to the existing governed writes: `upsertNoun`, `upsertVerb`,
  `setBinding` (or, once migrated, the `control.*` verbs from Round Seven, so even
  registry edits run the chokepoint - see open item 11.2).
- The same canvas, tree layout: this is why React Flow was chosen over a
  second graph library. A new verb authored here immediately appears in the
  workflow palette, because both read the same scoped registry.
- `web.fetch` (Round Eight) shows here as a high-consequence, SSRF-guarded verb
  bound to the `web` adapter - the visible proof that "internet access" is a
  governed node, not an escape hatch.

### 5.2 The Workflow canvas (Orchestration plane) - four node kinds

Where capability is composed. This is the existing `WorkflowCanvas`, widened from a
step editor into the product's authoring centre.

- **Kernel-run node:** dispatches one fixed verb. May also trigger another whole
  `WorkflowDefinition` as a composable sub-run (depth-limited - open item 11.1).
- **Service node:** mechanically identical, grouped because its verb reaches an
  external SaaS, so an author sees at a glance what leaves the system. Not a
  separate code path - derived from the adapter binding.
- **Agent node:** hands a sub-problem to Pi, which reasons among the run seat's
  granted verbs rather than a pre-wired sequence. The "uncaged = internet access"
  question resolved in Round Eight: an agent node may be granted `web.fetch`; it
  still cannot bypass the kernel.
- **Trigger nodes (chat / cron / webhook):** entry points at the front of the same
  canvas, not a separate concept - they already produce the same `WorkItem` shape
  (`chat.py` / `normalise.py`). Chat-as-trigger means a conversation can start a
  flow. Excluded from the serialised executable `steps` (they are entry points).

The canvas serialises to the EXACT `definition.steps` contract (it already does:
Kahn topo-order on save), so the Round Seven interpreter runs precisely what is
drawn. Save -> `upsertWorkflow`; Run -> `executeWorkflow`; palette from the scoped
`/v1/capabilities`; authz server-side.

### 5.3 The Run canvas (Activity plane) - the same graph, alive

The missing piece that most makes Nankle "come to life", and the payoff for the
event-backbone work (S6). The workflow canvas, in read-only run mode, with the
SAME node layout lighting up as the interpreter executes:

- Each node carries live state: pending / running / paused-at-HITL / ok / failed /
  skipped, animated as events arrive, colour-keyed to the existing `--ok/--warn/
  --down` tokens and the `runBadgeClass`/`stepBadgeClass` helpers.
- A paused-at-HITL node is actionable inline (answer the approval right on the node,
  via the shared HITL store `ApprovalsPanel`/`ChatPanel` already use).
- An agent node expands to show its live reasoning + tool calls (the same
  `ToolCard`/reasoning rendering `ChatPanel` already has - reused, not rebuilt).
- After completion it becomes the run's permanent record, reconstructable from the
  audit tree (`/v1/audit/tree/{run_id}`) so a historical run renders identically to
  a live one - exactly how `ChatPanel` already replays persisted events.

## 6. The event backbone (the highest-leverage build)

Make real agent events flow, so every surface built to display them lights up. This
is primarily a BACKEND wiring task that unlocks UI that already exists.

- The spawner / `PiRuntime` already produce tool/reasoning/sub-agent activity
  internally (`pi_runtime.py` consumes a `final` event and relays text). Publish the
  intermediate events to the `EventRelay` keyed by `run_id`: `reasoning_delta` on
  model reasoning, `tool_call` / `tool_result` around each kernel verb the agent
  invokes (the chokepoint is the natural emission point), `subagent` on a spawn,
  `hitl` when a gate fires.
- Because the relay already fans out by `run_id` with replay, BOTH the Chat surface
  and the Run canvas subscribe to the same stream with zero new transport. The
  `RunView` drawer (S4) subscribes by `run_id`; `ChatPanel` already does.
- Respect the separation of concerns: events are a faithful report of what the
  runtime did, emitted at the kernel chokepoint and the runtime boundary - the front
  end never synthesises them.
- This single change lights up: live tool/reasoning/sub-agent cards in chat (latent
  today), the live Run canvas (S5.3), and a live execution feel across the product -
  all from UI that is already written.

## 7. The surrounding surfaces, each tied to a guarantee it makes visible

Every existing panel keeps its job but gains a place in the three-plane IA and links
into the run spine. None are thrown away - they are connected.

| Surface | Plane | The kernel guarantee it makes visible | Connect by |
| --- | --- | --- | --- |
| Registry (was Router + Router studio) | Capability | scoped visibility != authority | verb -> palette, verb -> runs that called it |
| Adapter / Skill / Model studios | Capability | capability is data, governed authoring | adapter health -> registry node |
| Workflow canvas | Orchestration | composition over the chokepoint | node -> verb -> run |
| Chat | Orchestration + Activity | a conversation is a governed trigger (with continuity, Round Six) | turn -> Run drawer; trigger -> flow |
| Run canvas / Run drawer (new) | Activity | every step is one governed, audited call | the spine - links everywhere |
| Kanban | Activity | work in flight, source-agnostic | card -> Run drawer (already opens the audit tree) |
| Approvals | Activity | the HITL gate, made human | approval -> the paused node/run |
| Insight | Activity | the audit log as scope-filtered truth | row -> Run drawer; add the `run` filter the client already supports |
| Memory | Activity | kernel-governed, scope-isolated knowledge | fact -> the run/ingestion that created it |
| Me / Settings | (cross) | delegated-only authority, your data | personal agent -> its capped runs |

## 8. Entry and identity (make "who am I" real)

Today: a dev header bar defaulting to org-admin, no login. The experience needs a
real front door without breaking the dev path.

- **A landing / sign-in surface.** In production, the OIDC/PAT path the backend
  already supports (`build_principal_resolver`, `/v1/me/*`, PAT mint) drives a real
  session; the dev header bar stays behind a dev flag. A first-run sense of "you are
  X, in tenant Y, with these capabilities".
- **A capability-aware home.** After entry, land on a dashboard (not `router` by
  default): my pending approvals, my recent runs, work in flight, quick-start a chat
  or a workflow - the "what can I do / what needs me" view. This is where the
  three-plane IA is introduced.
- **Honest gating.** Keep the cosmetic tab gates, but every gated action still shows
  the server's 403 faithfully; the home adapts to the caller's scoped capabilities
  (from `/v1/capabilities`) rather than a hardcoded tab list.

## 9. Look and feel

Keep the bespoke, dark-first, multi-axis system (`styles.css`: theme / density /
contrast / font-scale / reduced-motion already exist) - it is good and dependency-
light. Do NOT add a component framework (consolidation; the existing tokens +
primitives cover it). Additions: a coherent left-nav for the three planes (replacing
the flat tab strip), the Run drawer chrome, node run-state animation tokens, and a
home/dashboard layout. Accessibility parity with the existing AA work
(`aria-live` on streams, focusable nodes, reduced-motion respected on canvas
animation).

## 10. Dependency decisions (recorded calls)

- **Adopt a tiny client-side router** (e.g. a ~1-2kb hash/history router, or
  `react-router` if its weight is justified by the deep-linking + Run-drawer routing
  that the whole spine depends on). This is the one genuinely new front-end concern;
  it is load-bearing for S4. Decision recorded; the specific library is a low-blast
  follow-on call, not a fork.
- **Reject a global-state library.** The identity store (`useSyncExternalStore`) +
  per-panel `useFetch` + URL state cover it; a run-event store can be a small
  `useSyncExternalStore` like identity. Consolidation over adding Redux/Zustand.
- **Reject a component framework / a second graph lib / a chat framework.** Carried
  from prior rounds: bespoke CSS, one graph dep (`@xyflow/react`), and the existing
  `ChatPanel`+SSE stand. Vercel AI Elements stays rejected - the renderer exists.

## 11. Open items / forks

- **11.1 Sub-workflow recursion depth.** Composable sub-workflow nodes introduce
  workflows-triggering-workflows; reuse the kernel's agent `max_depth` to bound it.
  First-impression design - route to the court before building.
- **11.2 Governed registry/workflow writes.** Whether the registry editor's writes
  (`upsertNoun/Verb/setBinding`, `upsertWorkflow`) migrate onto the Round Seven
  `control.*` governed verbs (so authoring itself runs the chokepoint + HITL) is the
  same open governance question; settle it once for all control-plane writes.
- **11.3 Live run-state transport at scale.** The Run canvas uses the existing
  per-run SSE relay; whether a tenant-wide "all active runs" feed (for Kanban/home
  liveness beyond polling) needs its own event channel is undesigned.
- **11.4 Surfacing the unused chokepoint.** `api.invoke` / `api.spawn` /
  `api.adapterSource` are client-ready but unsurfaced; a "developer console" (run a
  raw verb, inspect generated adapter source) is a natural Capability-plane addition.

## 12. Build backlog (prioritised, grounded)

Sequenced by leverage. Each is a buildable round; the early ones unlock the most.

1. **The event backbone (S6).** Emit real `tool_call`/`tool_result`/`reasoning_delta`/
   `subagent`/`hitl` from the chokepoint + runtime to the relay. Lights up the chat
   renderer that already exists. Highest leverage, mostly backend.
2. **The router + Run drawer (S4).** URL state + a `RunView` keyed by `run_id`,
   linked from Kanban / chat / Insight / approvals / workflow runs. Turns islands
   into a system.
3. **The live Run canvas (S5.3).** The workflow graph in run mode, lit by the S6
   events; inline HITL on a paused node.
4. **The home / entry experience (S8).** Capability-aware dashboard + the real
   sign-in path; dev headers behind a flag.
5. **The Registry canvas (S5.1).** Tree-mode React Flow over nouns/verbs/bindings,
   replacing the flat Router browser; `web.fetch` visible as a governed node.
6. **Polish + connect (S7).** Cross-entity links everywhere, the `run` audit filter,
   the developer console (11.4), three-plane left-nav.

This is the plan to bring Nankle to life: make the events flow (the plumbing is
built), give the run a home and a URL (so the parts connect), animate the canvas
(so execution is visible), and put a real front door on it (so it is someone's
system) - each step building on capability that already ships, none of it asking the
kernel to know the UI exists.
