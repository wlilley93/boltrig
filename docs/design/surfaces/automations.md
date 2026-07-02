# Automations row - build-ready surface spec (deck Beat 3)

Scope: the three surfaces of the automations row of the spatial deck. Grounded in reader-workflows.md (steps schema, rewiring math, execute-vs-trigger honesty), DESIGN-v2.md (deck mechanics, row specifics for automations), the visual canon (DESIGN-SYSTEM.md section 5 node language, COMPONENT-SPECS.md section 1 hero node), and the binding pattern language (P-numbers cited throughout). All amber usage obeys L4. All copy obeys P22 tone rules. No em or en dashes anywhere.

Routes (DESIGN-v2 grid, id-keyed columns):

| Route | Surface |
|---|---|
| `#/automations` | Surface 1: workflow picker anchor (col 0, no wfid) |
| `#/automations/:wfid` | Surface 2: workflow canvas slide (col 0, wf-scoped) |
| `#/automations/:wfid/step/:stepId` | Surface 3: per-step slide (cols 1..n, key = step id, topo order) |

All id segments `encodeURIComponent`'d on write, decoded in parse (DESIGN-v2). `?run=` stays a global overlay and never moves the deck.

Suggested file layout: `ui/src/panels/automations/` containing `AutomationsPicker.tsx`, `WorkflowCanvasSlide.tsx`, `StepSlide.tsx`, `draft.ts` (the row provider), `insert.ts` (pure rewiring functions, unit-testable). Reuse `graphToSteps`/`stepsToGraph`/`deriveKind`/`uniqueStepId`/`renameStep` from `ui/src/panels/WorkflowCanvas.tsx` (export them; do not fork).

---

## 0. Row infrastructure: the AutomationsDraft provider

One provider mounted at the automations row, keyed by `:wfid` from the route (DESIGN-v2 row specifics: "step slides are stateless views over a row-scoped provider holding the graph"). Both the canvas slide and every step slide are views over it; edits write through immediately so slide moves are lossless (P17 layer 1).

### 0.1 State shape

```ts
interface AutomationsDraft {
  wfId: string;
  meta: { version: string; source: WorkflowSource; intent_tags: string[] };
  loaded: { steps: WorkflowStep[]; meta: Meta } | null; // null = never-saved local draft
  nodes: StepNode[]; edges: Edge[];   // THE working truth
  dirty: boolean;                     // graphToSteps(nodes,edges) + meta !== loaded
  invalidJson: string | null;         // step id whose JSON escape hatch is unparseable
  pendingSave: { hitlRequestId: string; sentParams: object } | null;
  lastRun: WorkflowRunRecord | null;  // most recent in-context execute result / stream
}
```

**Decisive call: the graph (nodes + edges) is the single working representation**, per DESIGN-v2. `graphToSteps` (WorkflowCanvas.tsx:221-246) and `stepsToGraph` (WorkflowCanvas.tsx:250-301) are the ONLY converters. This makes the reader's orphan pitfall (reader-workflows section 4: a steps-mutating editor must splice deleted ids out of every `parents` array) impossible by construction: parents are recomputed from edges at save, an edge cannot reference a missing node, and delete-with-edge-cleanup (WorkflowCanvas.tsx:545-551) already strips edges. `parents subset-of ids` therefore holds at every save. Keep graphToSteps normalization exactly: omit `params` when `{}` and `description` when blank (WorkflowCanvas.tsx:241-243) so slide-edited definitions stay byte-comparable.

**Never renumber ids** (reader pitfall: checkpoint keys `(tenant, run_id, step)` interpreter.py:129-132, durable boundary names `workflow:<wf.id>:<step_id>` interpreter.py:181, live `workflow_step.step_id -> node.id` matching WorkflowRunCanvas.tsx:80). Fresh ids come from `uniqueStepId` (WorkflowCanvas.tsx:391-403); renames go through `renameStep`'s full edge repoint (WorkflowCanvas.tsx:509-543).

### 0.2 Load

On `:wfid` change: `GET /v1/workflows/{wfid}` (platform_routes.py:245-254; client.ts:328-330) -> `stepsToGraph(definition.steps, verbsById)` where `verbsById` comes from `GET /v1/capabilities` (client.ts:173-175, fetched once per row mount, 60s poll while row active). 404 body `{"error":"unknown_workflow"}` renders the error state (section 6). If the wfid matches a live local draft (create flow, 1.4), skip the fetch.

### 0.3 Save pipeline (the verb path, P16 + P31 row 1)

Explicit Save only. The verb exists; the console uses it over the coexisting direct `POST /v1/workflows` route (P31 rule 1):

```
POST /v1/invoke   (client.ts:184-186; result union app.py:259-283; InvokeRequest types.ts:86-93)
{ noun: "control", verb: "control.workflow.upsert",
  params: { id, version, source, definition: { steps: graphToSteps(nodes, edges) }, intent_tags },
  idempotency_key: <uuid minted per save attempt> }
```

Verb schema and consequence: control_plane.py:52-63; all `control.*` verbs are `consequence="high"` (control_plane.py:49-50), so **every Save can 202**. Handling per result (P30, P15, P24):

- `ok` -> SaveBar flashes "Saved as v{version}", `loaded` updates, dirty clears.
- `pending_human` -> the SaveBar's result zone renders `PendingHumanCard` (N15): amber left bar, "Paused for approval", `control.workflow.upsert` mono, params summary read-only with JSON in a disclosure, `hitl_request_id` mono copyable, "Open in Approvals" -> `#/approvals`, inline approval card if the caller can approve. Polls `GET /v1/hitl` at 8s, quiesced when the slide is inactive (deck quiesce contract). Approved -> dirty recomputes against `sentParams` (normally clean), card flips to ok. Rejected -> card flips to the denial treatment with the recorded reason; draft stays dirty. **While a save is pending, the Save button is disabled with hint "A previous save is awaiting approval."** Editing stays allowed; the pending card describes the snapshot that was sent.
- `denied` -> calm warn callout at the SaveBar with the server reason verbatim via `apiReason` (shared.tsx:14-24) + "Ask an admin to widen your access." No retry (P24).
- `error` -> `ErrorState` with reason + "Try again".

**Version auto-bump (fixes debt S2/C1):** Save always writes next-patch of `loaded.meta.version` (1.0.0 -> 1.0.1); the SaveBar states it: "Save workflow - saves as v1.0.1". Override lives in the canvas meta disclosure (Tier 3, P18). Never-saved drafts save as 1.0.0.

### 0.4 Dirty state (P17)

- SaveBar (N10) pinned to the bottom of the canvas slide AND every step slide of the row while dirty: "Unsaved changes to `invoice-flow`" + compact `InfoCallout tone="consequence"`: "Saving a workflow is a high-consequence change. It may pause for a human approval." (P28: the foreshadow is law for every control.* form) + `Save workflow` (the surface's one `btn--primary`, P20) + `Discard` (ghost, arm-confirm N14: "Discard unsaved changes to invoice-flow? This reloads the saved version.").
- Dirty slides are keep-alive pinned; sidebar map + minimap show the dirty dot on the row (DESIGN-v2 mount policy).
- Navigation never destroys the draft and is never blocked, with ONE exception: `invalidJson` set (an unparseable JSON escape hatch) blocks the slide move, returns focus to the textarea, and shows the P15 error - the generalization of the canvas dirty-inspector guard (WorkflowCanvas.tsx:444-454).
- Route-level leave with dirty draft (picker click to another workflow, closing the SPA): `beforeunload` guard + in-app arm-confirm on the picker card: "Discard unsaved changes to invoice-flow?"

---

## 1. Surface 1: the workflow picker anchor (`#/automations`)

A list surface, not a form (P20: the 80% path is "pick a workflow, see the canvas, run it").

### 1.1 Layout, region by region

Outer container: the deck slide frame (own scroller, bordered, `overflow:auto`). Top to bottom:

1. **PageIntro**: title "Automations", subtitle "Workflows are governed chains of verbs. Every step runs through the kernel; high-consequence steps pause for approval." (rung 4 teaching folded into the intro; concepts glossed via the P22 glossary thereafter).
2. **Toolbar row**: left, a filter input (placeholder "Filter by id or tag", "/" focuses it per P36, filters client-side on id + intent_tags). Right, `New workflow` (`btn--primary`, the one primary at rest) and the ByChat ghost (N16, P32) with phrase "Create a workflow called <name> that <does what>".
3. **Card grid** (`.auto-card` on `.card` surfaces, responsive columns, min 320px). Cards sorted by id.
4. **Inline create region** (1.4), rendered above the grid only while creating.

### 1.2 Workflow card anatomy

Data: `GET /v1/workflows` -> `{workflows:[{id, version, source, intent_tags}]}` (platform_routes.py:239-243; client.ts:324-326; types.ts:382-391). Summaries only; do not invent step counts.

- Row 1: workflow id, mono, `--fs-md` 600, middle-truncated with full value on title (P34).
- Row 2: `v{version}` badge + source badge with its glossary gloss via TermTip (P21 rung 2; new glossary entries, P22 extend-never-fork): `precreated` "Authored by a person", `generated` "Authored by an agent from a task", `learned` "Distilled from repeated successful runs".
- Row 3: intent tag chips (`.tag`, up to 4, "+n" overflow on title).
- Card click / Enter: `navigate("/automations/<id>")`.
- Row actions (max two, P35): `Open` (ghost, same as card click) and `Run` (ghost) which navigates to the canvas slide with a one-shot run intent (`setAutomationsIntent("run")`, the identity-store idiom P32 uses) so the canvas opens with its Run region expanded and focused. Run inputs are handled ONLY on the canvas (one place, considered).
- **No delete and no rename affordance.** No delete route or verb exists (P31: `control.*.delete` DOES NOT EXIST; P27). Instead the card overflow offers `Duplicate as...` : inline mono id input (validated per 1.4) whose confirm performs `control.workflow.upsert` under the new id with the fetched definition - a real capability the verb already gives us.

### 1.3 States (P24 precedence: denied > error > loading > empty > ready)

- **Denied**: the row is AUTHOR_ROLES-gated cosmetically (DESIGN-v2 grid); if the server 403s the list, render the faithful slide-scale denial: PageIntro + calm warn callout with the server reason verbatim + "Ask an admin to widen your access.", chevrons still live (P24, DESIGN-v2 "faithful 403 slide").
- **Error**: `ErrorState` + "Try again"; network copy "Can't reach the server - check your connection."
- **Loading**: first load only, `Skeleton variant="cards" count={4}` (N13, P25). Polls never skeleton.
- **Empty**: `EmptyState` (ux.tsx:161-180): title "No workflows yet", body "A workflow is a governed chain of verbs that agents run step by step.", CTA "Create your first workflow" (starts 1.4), plus the ByChat line: "or ask in chat: 'Create a workflow called invoice-triage that fetches an invoice then posts it to Slack'" (P32 on empty states).
- **Ready**: the grid.

### 1.4 Create-new flow (not a wizard - a single upsert, P19)

`New workflow` expands an inline create region (Disclosure-style, no route change):

- **Workflow id** (Field, N8): mono input, required, the surface's ONE blank field (P12 case 4), autofocused. Hint: "Lowercase, dots, dashes. This is the workflow's permanent id." Example: `` e.g. `invoice-triage` ``. Validated on blur (P13) against `^[a-z0-9][a-z0-9._-]*$`; uniqueness checked against the loaded list, error copy "That id is taken" (P22: never blame the user). Meta slot shows the check result.
- **Intent tags** (optional, Tier 2): ChipPicker (N3, P5), free-entry variant, candidates = union of existing workflows' intent_tags. Hint: "Helps agents find this workflow for matching tasks."
- `source` and `version` are NOT shown (fixes debt W3): source defaults `precreated`, version `1.0.0`, kernel-mirrored defaults (control_plane.py:97-98, P12 source 1). Both editable later in the canvas meta disclosure.
- Primary action: `Create draft`. **Decisive call: creation is LOCAL.** It mints an AutomationsDraft with zero steps (`loaded: null`) and navigates to `#/automations/<id>`; no server write happens until the first Save. Rationale: `control.workflow.upsert` is consequence-high; saving an empty shell would fire a HITL round trip before anything is authored (P16's never-autosave logic applied to creation). The canvas slide shows a `draft - not saved` badge until first Save. A reload before saving loses the draft; the `beforeunload` guard (0.4) covers it.

Chat parity: "Create a workflow called invoice-triage" -> orchestrator invokes `control.workflow.upsert {id:"invoice-triage", definition:{steps:[...]}}` -> 202 pending_human -> inline hitl card in chat (P33).

---

## 2. Surface 2: the workflow canvas slide (`#/automations/:wfid`)

The existing WorkflowCanvas elevated to the bar. Selection lives ONLY in the route (DESIGN-v2): there is no inspector panel here anymore - **the step slide IS the inspector**; clicking a node navigates right.

### 2.1 Layout, region by region

Deck slide frame; internal layout is a column flex, the canvas flex-fills.

1. **Slide header** (one row): breadcrumb position chip "Automations / `invoice-flow`" (deck standard, same string as the aria label); workflow id mono click-to-copy; `v{version}` badge (shows the pending auto-bump as "v1.0.0 -> v1.0.1" while dirty); source badge with gloss; `draft - not saved` badge when `loaded === null`; dirty dot; the count-and-peek cue "`5 steps >`" (DESIGN-v2 affordance 7), a real button navigating to the FIRST step slide.
2. **Toolbar row**: left: `Run` control (2.4) and `Add step` (appends at the sink set, 2.3). Right: `Details` disclosure toggle (2.5) and `Runs` disclosure toggle (2.6), plus the ByChat ghost.
3. **Body**: horizontal split.
   - **Step rail** (left, 240px, collapsible to 36px): the topo-ordered step list, the accessible alternative to the canvas and the peek affordance into columns. Each row: step id mono, verb id mono small, consequence-high amber marker where applicable (L4), last-run status dot (passive, from `draft.lastRun`), all with glossary TermTips (P21 rung 2). Row click / Enter: navigate right to that step slide. Row hover: highlights the node on the canvas.
   - **Canvas** (`.wf-canvas--slide { flex:1; min-height:0 }`, replacing the fixed 560px `.wf-canvas`, styles.css:1718-1724): React Flow with `nodeTypes` from WorkflowCanvas.tsx. Deck motion is translate-only so React Flow hit-testing is safe (reader-shell section 3); never scale.
4. **SaveBar** (N10) pinned at the slide bottom while dirty (0.4).

### 2.2 The hero node (COMPONENT-SPECS section 1, DESIGN-SYSTEM section 5)

Upgrade `StepNodeView` (WorkflowCanvas.tsx:135-163) to the canon:

- Surface `--color-bg-card`, `--radius-md`, **4px left accent bar keyed to kind**: kernel-run `--color-border-strong`, service `--color-accent-2`, agent `--color-accent`, trigger dashed `--color-warn` (kind derived from `binding.target_type` via `deriveKind`, WorkflowCanvas.tsx:125-130, never a client list).
- Step id (label) + kind chip on the top row; verb id in mono below; consequence-high marker in `--color-consequence-high` with the existing title gloss (WorkflowCanvas.tsx:141-149) - amber ONLY here and in run-paused (L4).
- Passive last-run status dot bottom-right (colour + glyph, not hue alone) using the `--color-run-*` tokens; `paused` steady ring + "needs you" badge, visibly distinct from running's pulse; reduced-motion swaps pulse for a static ring (canon acceptance).
- Focusable; Enter/click navigates right to `#/automations/:wfid/step/<id>`; verb id copyable.
- **Edge + affordance**: hovering or focusing an edge reveals a small `+` button at the edge midpoint (`.wf-edge__add`, 44px target under pointer:coarse). Click = insert on that exact edge (math in 3.4). This is the pointer path for insert-between; the step slide edges (3.4) are the keyboard path.

Drag-to-connect stays for power users, **cycle-guarded at connect time**: refuse a connection whose target can already reach the source (BFS over edges), with an inline warn hint "That connection would create a cycle." (fixes the silent topoOrder fallback trap, WorkflowCanvas.tsx:216-217 vs interpreter skip, reader-workflows section 4). Delete key with a node selected opens the same ArmConfirm-with-impact as the step slide's danger zone (3.6), rendered as an in-slide footer bar (no modal, no portal - reader-shell: transforms break fixed positioning).

### 2.3 Add step (append)

`Add step` in the toolbar: mints `uniqueStepId` and creates N with `parents = the current sink set` (all steps no other step lists as a parent) so the graph keeps one terminal node - the reader's recommended "append at the end" (reader-workflows section 4 APPEND). Zero steps -> N is the root (`parents:[]`). Then navigate right to N's slide, which opens in choose-your-verb state (3.2). Draft dirty. The per-slide append (parents `[T.id]` only) lives on the step slides (3.4).

Empty canvas state: `EmptyState` centered on the canvas area: title "No steps yet", body "Add the first step and choose the verb it runs.", CTA "Add the first step" (same action), plus ByChat "or ask in chat: 'Add a step to invoice-flow that runs invoice.fetch'".

### 2.4 Run control (durability honesty - reader-workflows section 5)

`Run` opens an inline arm region under the toolbar (no modal):

1. **Inputs**: when the definition declares an input schema, SchemaForm v2 over it (P9) - DEPENDS-BACKEND: no input schema is surfaced on the summary or detail today (debt W5). Until then: `JsonDisclosure` (N9) defaulting `{}`, hint "Most workflows run with no inputs." Never a bare primary JSON box (P10).
2. **Consequence foreshadow** (P28): when any step's verb is consequence-high, `InfoCallout tone="consequence"`: "This workflow has 2 high-consequence steps. The run will pause for approval when it reaches them."
3. **Mode** (Segmented, P3, 2 values):
   - **Run now** (default): `POST /v1/workflows/{wfid}/execute {inputs}` (platform_routes.py:299-314; client.ts:361-370) -> full `WorkflowRunRecord` (types.ts:452-467). Honest hint: "Runs immediately and streams progress here. Foreground runs do not checkpoint: they do not survive a restart and do not auto-resume after an approval." (library.py:114-132 passes no store; reader-workflows section 5.)
   - **Queue**: `POST /v1/workflows/{wfid}/trigger {inputs}` (platform_routes.py:286-297; client.ts:352-358) -> queue descriptor `{run_id, engine, durable, status:"queued"}` (library.py:74-112). Render the descriptor faithfully: "Queued on `hatchet` - durable" or "Queued on `local` - not durable" from the response fields, never a client guess. **DEPENDS-BACKEND (honesty callout, tone warn): nothing currently consumes the queue - the trigger route records an enqueue boundary but does not enqueue `TASK_WORKFLOW_RUN` (only the pump does, fleet/pump.py:182). Copy on the result: "Queued. Note: queued runs are not yet picked up by the engine from this route."** Keep the mode visible (it teaches the durable path) but honest.
4. Primary: `Start run` (busy text "Running..." per P25; the SaveBar's Save stays the slide's primary at rest - while the run region is open, Start run takes the primary style and Save drops to secondary, preserving one-primary (P20)).

On execute response / while streaming: the canvas enters **run overlay mode** (read-only): node statuses overlay exactly as WorkflowRunCanvas does (`statusById[node.id] ?? "pending"` from `workflow_step` events via `streamRunEvents(runId, ..., {follow:true})`, client.ts:752-795; app.py:534-558; WorkflowRunCanvas.tsx:79-104), edges animate dash only on live edges (canon), and an exit chip "Back to editing" restores edit mode. `openRun(run_id)` (shared.tsx:73-83) is offered as "Open run drawer" but not forced. A `paused` node shows the steady amber ring + "needs you"; clicking it navigates right to the step slide, which renders the PendingHumanCard (3.7). The record lands in `draft.lastRun` (feeds the passive badges). Dirty edits are refused while in overlay mode; exiting restores them untouched.

If the caller has unsaved changes when starting a run: warn callout in the arm region: "The run uses the last saved version (v1.0.0). Your unsaved changes are not included." (execute walks the STORED definition.)

### 2.5 Details disclosure (Tier 3, P18/P19 sections not tabs)

`Disclosure` (N11) "Details" with changed-count summary. Contains, as Fields (P11):

- **Version** (mono input, prefilled with the auto-bump target; hint "Bumps automatically on save; override only for a deliberate re-version.").
- **Source** (Segmented, 3 values, glossary hints - P3; it exists here for honesty, defaulted and rarely touched, per debt W3).
- **Intent tags** (ChipPicker as in 1.4).
- **Import / export**: `JsonDisclosure` "Advanced: definition as JSON" two-way synced with the graph (P10); paste accepts the three `extractSteps` shapes (WorkflowCanvas.tsx:305-317). Applying a paste that replaces steps arms first (fixes debt C3): ArmConfirm "Replace all 5 steps with the pasted definition?". Invalid JSON blocks collapse and Save (P10, P17).

### 2.6 Runs disclosure

`Disclosure` "Runs" listing run ids as `RunLink`s (mono, opens the global drawer without moving the deck). **Honest label (do not reproduce the caveat silently): "Recent run ids (tenant-wide). The server does not yet filter runs by workflow."** - `GET /v1/workflows/{wfid}/runs` returns up to 100 distinct run ids from the tenant audit log regardless of wfid (platform_routes.py:316-320). DEPENDS-BACKEND: workflow-filtered runs; relabel to "Runs of this workflow" when it lands. This also fixes debt C2 (the bare run-id paste box is deleted; the drawer covers inspection).

**Schedule** row inside Details: cron `Select` of presets (hourly, daily 09:00, weekdays 09:00, custom) + custom 5-field input when custom; client-side validity check + "Next 3 runs: ..." preview from a small pure util (no new dependency, S10 discipline); `Validate schedule` calls `POST /v1/workflows/{wfid}/schedule` (platform_routes.py:273-284) and renders the returned spec. **DEPENDS-BACKEND (honest note): validation returns a spec; nothing persists or fires the schedule yet.** (Fixes debt W6 without overclaiming.)

### 2.7 States

- **Denied** (403 on detail): faithful slide-scale denial as in 1.3.
- **Error / 404**: `unknown_workflow` -> `ErrorState`: "This workflow does not exist or is not in your scope." + "Back to automations" CTA. Network error -> standard copy + Try again.
- **Loading**: `Skeleton variant="cards"` shaped as rail rows + a canvas block, first load only.
- **Empty**: 2.3's canvas empty state (header still renders identity).
- **Ready / run overlay / pending save**: as specified.

---

## 3. Surface 3: the per-step slide (`#/automations/:wfid/step/:stepId`)

The Principal's granular full-screen step editor. A form surface (P34: comfortable rhythm even under compact). Stateless view over the row provider: it finds its node by id; parents/children are the incoming/outgoing edges.

### 3.1 Layout, region by region

Deck slide frame. Left and right edge columns carry the deck chevrons PLUS the plus affordances (3.4). Body is a single scrolling column, max-width 760px centered:

1. **Header row**: breadcrumb chip "Automations / `invoice-flow` / `fetch-invoice` - step 2 of 5" (topo position; same string announced by the deck's live region); kind chip; consequence badge (glossary-glossed); **passive last-run badge** (from `draft.lastRun` only, no new fetch - DESIGN-v2: "passive last-run badge only from in-context run records"): `StatusBadge` for the step's status + relative time + `RunLink` to the run; dirty dot.
2. **Step id** (inline rename): the id renders mono `--fs-lg` with a pencil ghost button. Editing swaps to a mono input; validated per 1.4 charset + uniqueness via the `uniqueStepId` take-set; commit on Enter/blur runs `renameStep` semantics (repoint every edge, WorkflowCanvas.tsx:509-543) then `navigate` with replace to the new step route (back never hits a dead id). Hint (rung 3): "Renaming changes this step's identity for future runs. Past runs and paused checkpoints keep the old name." (reader pitfall: ids key checkpoints and durable boundaries.)
3. **PendingHumanCard zone** (3.7) - rendered only when this step is paused.
4. **Action** - Tier 1 (3.2).
5. **Parameters** - Tier 1/2 (3.3).
6. **Description** - Tier 2: auto-growing textarea in a Field (P10 prose, mono OFF). Label "Description", hint "Shown on the canvas and in run records." Omitted from the saved step when blank (normalization, 0.1).
7. **Runs after / runs before** - Tier 2 (3.5).
8. **Danger zone** - Tier 3 (3.6).
9. **Footer**: ByChat ghost (3.8). SaveBar pinned below when the draft is dirty (0.4 - it saves the WHOLE workflow draft, appearing on every slide of the row).

### 3.2 Action (the verb) - EntityPicker (N4, P6)

The step's one potentially-blank required field (P12 case 4): a brand-new step opens with this field focused and its empty state teaching: "Choose the verb this step runs. Everything else has a default."

- Trigger button styled as an input: current verb id mono + kind badge + chevron. Open panel is absolutely positioned inside the field wrapper, z-index 30 (no portals; the deck transform breaks fixed - reader-shell section 3).
- Panel: search input autofocused; results grouped by **noun** from caller-scoped `GET /v1/capabilities`; per row: verb id mono, one-line description, **consequence badge with the amber marker on high** (the author sees the approval pause coming - P6 flagship, DESIGN-SYSTEM section 5 foreshadow), binding badge "runs via `slack` adapter" / "runs via agent" (from `binding.target_type`), health badge for adapter-bound rows. Keyboard per P36 picker map.
- Inline preview card after selection: consequence, binding, description, param count.
- **Consequence teaching** (P28 + P21 rung 4): when the chosen verb is high, an `InfoCallout tone="consequence"` renders directly under the field (where the consequence lands): "This step is high consequence. Runs will pause here for a human approval before it executes." One callout, amber reserved for exactly this (L4).
- **Verb swap**: re-derives kind + consequence (existing logic, WorkflowCanvas.tsx:459-471) and re-seeds params from the new schema's defaults; values are preserved for same-named same-typed properties and dropped otherwise, with a quiet info line "2 parameters from the previous verb were dropped." (guards the stale-params pitfall, reader-workflows section 4: the kernel only catches it at dispatch as a run-time step failure).

### 3.3 Parameters - SchemaForm v2 (N7, P9)

Rendered from `verb.input_schema` (the same machinery as the existing inspector, WorkflowCanvas.tsx:925-958, upgraded):

- Required-first ordering; per-type controls from the P1 decision table (boolean -> Segmented; enum <=4 -> Segmented, >4 -> Select; bounded number -> Stepper N6; array -> ChipPicker N3; one-level object -> inline bordered group; deeper -> JsonDisclosure for that subtree only). This kills X1 for the step surface.
- Defaults visible as values (P12: `schema.default`, else the type skeleton - the `skeletonFromSchema` logic moves into the form).
- Optional tail beyond 6 fields collapses into "More options (n)" with the mandatory changed-count (P18 Tier 3).
- One `JsonDisclosure` "Advanced: edit as JSON" at the end, two-way synced; invalid JSON sets `draft.invalidJson = stepId`, blocking slide navigation and Save with focus returned (P10, P17, the canvas guard's semantics generalized).
- **No schema** (`{"type":"object"}`, control_plane.py:34 pattern): render the JsonDisclosure directly, expanded, honestly labelled: "This verb declares no parameter schema. Edit parameters as JSON." (P9 not-when clause.)
- Validation timing per P13; field errors per P11/P15.
- Params write through to the node immediately (draft layer); persistence is the SaveBar.

The interpreter accepts `with` as a params alias (interpreter.py:166) but the editor always writes `params` (graphToSteps contract).

### 3.4 The plus affordances (the Principal's ask: exact placement and parents math)

Both slide edges carry a vertical group, inset 16px from the edge, clear of scrollbars (DESIGN-v2 affordance 2): the **nav chevron** centered (navigates; unchanged deck behaviour) and, 12px below it, the **plus button** (creates). Both are real buttons, first/last in the slide tab order, 44px under pointer:coarse, subtle at rest and stronger on hover/:focus-visible. The plus is visually distinct from the chevron (a `+` glyph in a bordered square vs the bare chevron) so navigate-vs-create never confuses. On hover/focus-visible the plus reveals its text label inline.

All insertion math is pure edge surgery in `insert.ts` (unit-tested), mirroring reader-workflows section 4 exactly. New ids always minted via `uniqueStepId`; existing ids never touched. **Neither operation can create a cycle** (the new node sits strictly inside the existing partial order, reader-workflows section 4). The new step appears in the column list at its topo position; column identity is id-keyed so the deck re-derives indexes without lurch (DESIGN-v2 grid). After either operation the deck navigates to the new step's slide, which opens in choose-your-verb state (3.2). Draft dirty; SaveBar appears.

**Right edge plus - "Add step after `fetch-invoice`"** (aria-label exactly that):
- Current step T has NO children: one click appends. `N = {id: fresh, parents: [T.id]}` (edge T -> N). Nothing else changes (reader APPEND).
- T HAS children C1..Cn: one click opens a small in-flow panel (`.ux-picker` anatomy, P6 keyboard map) - progressive disclosure only when the DAG makes the intent ambiguous (L1):
  - "New branch after `fetch-invoice`" (first, default): `N.parents = [T.id]`; children untouched (T now fans out).
  - "Insert between `fetch-invoice` and `notify-slack`" - one row per child C: the single-edge splice: `N.parents = [T.id]`; `C.parents = C.parents.map(p => p === T.id ? N.id : p)` (edge surgery: retarget edge T -> C to T -> N, add N -> C). T's other children keep pointing at T; C's other parents untouched (reader INSERT, multi-parent rule).

**Left edge plus - "Insert step before `notify-slack`"**:
- Current step B is a ROOT: one click: `N = {parents: []}`; `B.parents = [N.id]` (N becomes a root feeding B; other roots stay roots - reader insert-before-root).
- B has ONE parent A: one click: splice A -> B (same math as above with T = A, C = B).
- B has parents A1..An: panel "Insert on which incoming path?":
  - One row per parent: "between `A1` and `notify-slack`" (splice only that edge).
  - Last row: "Before all paths (join)": `N.parents = [A1..An]`; `B.parents = [N.id]` (retarget every incoming edge to N, add N -> B).

**Canvas edge plus** (2.2) performs the single-edge splice for its exact edge - the pointer-first equivalent; the slide edges are the keyboard-first equivalent.

**First/last slide edge cases**: on the last step slide the right chevron is absent (no next step) and the plus reads "Append step"; on the first step slide the left chevron navigates to the canvas (col 0) and the left plus still offers insert-before-root.

### 3.5 Parents editor - "Runs after" (visual, cycle-guarded)

A Field labelled "Runs after", hint "The steps that must finish before this one starts. No parents means this step runs first."

- Current parents as removable mono chips (ChipPicker anatomy, N3 - values are step ids, a known finite set, so P5 not P7: no patterns, no match semantics).
- "Add parent" opens an EntityPicker (N4) over the workflow's steps; **eligible = all steps minus self minus descendants of self** (BFS over edges). Ineligible rows render disabled with the reason inline: "would create a cycle" (surfacing cycles in-editor, per DESIGN-v2 and the reader's warning that save-time topoOrder silently falls back while the interpreter skips).
- Removing the last parent is legal and re-labels the state line to "Root step - runs first" (a taught state, not an error).
- Below the field, a read-only relationship strip: "Runs before: `notify-slack`, `archive`" - each id a button navigating to that step's slide (children are edges out; editing a child's parents happens on the child's slide, one owner per fact).
- Meta slot (N8): "2 parents - 2 children".

### 3.6 Danger zone - delete with downstream-impact preview

`ArmConfirm` (N14, P27), **red not amber** (L4: deleting a draft step is a local destructive act; governance holds the change at Save):

- Rest: ghost button "Delete step".
- Armed (in place, no modal): an `InfoCallout tone="warn"` containing the computed impact preview plus a rewiring choice:
  - Impact lines, computed from edges: "`notify-slack` and `archive` currently run after this step." For each child, what the chosen option does to it.
  - **Rewiring choice** (Segmented, P3 - the reader requires the editor to decide re-parent vs new-roots; we make it the user's explicit, defaulted choice):
    - "Reconnect children to this step's parents" (default): every child C replaces `fetch-invoice` in its parents with fetch-invoice's parents (splice-through: delete B from A -> B -> C yields A -> C). Preview line: "`notify-slack` will run after `invoice.fetch` instead."
    - "Leave children as new starting steps": children simply lose the edge (C may become a root). Preview: "`notify-slack` will run first."
  - Downstream honesty line when relevant: "Nothing is orphaned: parents are recomputed from the canvas, so no step is left naming a missing parent." (True by construction, 0.1 - and it is why the interpreter's skipped-subtree failure mode, interpreter.py:136-141 and 156-161, cannot be produced by this editor.)
  - Buttons: "Confirm delete" (red) + Cancel (ghost). Enter confirms only on the focused confirm button; Escape or slide navigation disarms (P36).
- On confirm: remove node + its edges (+ splice-through edges if chosen), navigate left to the previous step in topo order (or the canvas if none), draft dirty. Busy text "Deleting...".

### 3.7 The paused / pending_human state (P30, P33)

When the in-context run record or live stream marks THIS step `paused` with a `hitl_request_id` (interpreter.py:191-211 records both), render `PendingHumanCard` (N15) at the top of the slide body:

- Amber left accent bar, steady, never pulsing (canon). Headline "Paused for approval".
- Body: the verb id mono, the params the run asked with (SchemaForm values read-only, JSON in a disclosure), "A person needs to approve this before it runs.", the `hitl_request_id` mono copyable.
- Primary link "Open in Approvals" -> `#/approvals`; secondary `RunLink` to the run.
- Polls `GET /v1/hitl` at 8s, quiesced while the slide is inactive; resolution reconciles from the server, never component memory alone (P33 - the `resolvedHitls` local map is the named anti-pattern). If the caller can approve, the full approval card renders inline INSIDE the card, arm-confirm ritual intact (no rubber stamp, COMPONENT-SPECS section 4).
- **Resume honesty** (reader-workflows section 5): for a foreground run (execute path, no checkpoint store) append the plain line: "This was a foreground run. Approving releases the request, but the run does not resume on its own: run the workflow again after approving." For a durable engine run (only when the record/events carry the durable markers, e.g. `replayed: true`, interpreter.py:150-153) the line reads: "This run will resume automatically when approved." Never claim durability for the Run-now path (it is single-shot and non-checkpointed, library.py:114-132).

### 3.8 ByChat and keyboard

- **ByChat** (N16, P32) in the footer builds its phrase from the CURRENT draft delta for this step, e.g. after using the right-edge plus and picking `slack.post`: "In `invoice-flow`, add a step after `fetch-invoice` that runs `slack.post` with channel #billing". Activating reveals the phrase in a disclosure + "Open in chat": `setComposerPrefill(phrase)`, `navigate("/chat")`, composer prefilled and focused, never auto-sent. The orchestrator's path is identical to the console's: read `GET /v1/workflows/invoice-flow`, edit `definition.steps`, invoke `control.workflow.upsert` -> 202 -> inline hitl card in chat (P33 symmetry). This is the affordance that makes "add a step that posts to Slack after step 2" visibly the same operation.
- Keyboard: deck chord per DESIGN-v2 (never while focus is in inputs or .react-flow); Enter submits nothing globally (this is a multi-field form); pickers per P36; the plus buttons and chevrons are first/last in tab order.

### 3.9 Step slide states

- **Unknown step id** (key vanished, e.g. after a discard): the deck rule applies - navigate to the row anchor (DESIGN-v2 grid).
- **Denied / error / loading**: inherited from the row load (the step slide never fetches independently except capabilities, already cached).
- **New step (choose-your-verb)**: Action field focused, its empty state teaching; params region shows a muted line "Parameters appear once a verb is chosen."; Save enabled the moment a verb is chosen (P12: the author's minimum path is pick verb, press Save).
- **Paused**: 3.7. **Dirty**: SaveBar. **Pending save**: SaveBar's PendingHumanCard (0.3).

---

## 4. Chat parity registry for this row (P31)

| Console action | Verb path | Chat phrasing (ByChat-generated shape) | Status |
|---|---|---|---|
| Create workflow (1.4) | `control.workflow.upsert` (control_plane.py:52-63) via `POST /v1/invoke` | "Create a workflow called `invoice-triage` that fetches an invoice then posts it to Slack" | verb exists; UI uses it (direct `POST /v1/workflows`, platform_routes.py:256-271, coexists; console prefers the verb) |
| Save any draft change: add/insert/delete/rename step, params, parents, description, meta (0.3) | `control.workflow.upsert` with the full modified `definition` (the whole-definition upsert is the unit; no granular step verbs exist) | "In `invoice-flow`, add a step after `fetch-invoice` that runs `slack.post` with channel #billing" / "Remove the `archive` step from `invoice-flow` and reconnect its children" | verb exists |
| Duplicate as (1.2) | `control.workflow.upsert` under the new id | "Copy `invoice-flow` as `invoice-flow-v2`" | verb exists |
| Run now (2.4) | today direct `POST /v1/workflows/{id}/execute` (platform_routes.py:299-314) | "Run `invoice-flow` now" | DEPENDS-BACKEND: `control.workflow.execute` (or an orchestrator workflow tool). Note the governance story already holds either way: every step dispatches through the chokepoint under the caller's own grants (SEC-50 comment, platform_routes.py:300-303) |
| Queue durable run (2.4) | today direct `POST /v1/workflows/{id}/trigger` | "Queue `invoice-flow` to run durably" | DEPENDS-BACKEND: `control.workflow.trigger` verb AND the engine wiring (trigger route does not enqueue `TASK_WORKFLOW_RUN`; only fleet/pump.py:182 produces it) |
| Schedule (2.6) | today direct `POST /v1/workflows/{id}/schedule` (validate-only) | "Run `invoice-flow` every weekday at 9am" | DEPENDS-BACKEND: `control.workflow.schedule` + schedule persistence/firing |
| Delete workflow | none | none | DOES NOT EXIST (`control.workflow.delete`); NO delete affordance rendered anywhere until it lands (P27/P31 rule) |
| Approve a paused step (3.7) | `POST /v1/hitl/{id}/respond` (client.ts:213) | answer the inline hitl card in chat | exists; one route serves both clients (P33) |

Reads are shared reads (P31 rule 3): `GET /v1/workflows`, `GET /v1/workflows/{id}`, `GET /v1/capabilities`, `GET /v1/hitl`, `GET /v1/runs/{id}/events`.

---

## 5. Consolidated states matrix (P24 precedence per surface)

| State | Picker | Canvas slide | Step slide |
|---|---|---|---|
| denied | faithful 403 slide, reason verbatim, no retry | same | inherited from row |
| error | ErrorState + Try again; network copy standard | 404 `unknown_workflow` -> "does not exist or not in your scope" + Back CTA | key vanished -> navigate to row anchor |
| loading (first only) | Skeleton cards x4 | Skeleton rail + canvas block | none (row-fed) |
| empty | EmptyState + create CTA + ByChat | canvas EmptyState "No steps yet" + CTA | choose-your-verb state |
| ready | card grid | edit mode | form |
| degraded | n/a (list) | run result `status:"degraded"` -> badge + warn callout naming the unhealthy part | last-run badge shows it |
| pending_human | n/a | SaveBar PendingHumanCard; paused node amber steady + needs-you | PendingHumanCard at top (3.7) |
| dirty | leave-guard on card click | SaveBar | SaveBar (whole-draft) |

---

## 6. DEPENDS-BACKEND ledger (this row)

1. `control.workflow.execute` verb (or orchestrator workflow tool) so chat can run a workflow without a bespoke route binding. Console transports via `POST /v1/workflows/{id}/execute` behind the same control until then (P31 rule 2).
2. `control.workflow.trigger` verb AND wiring the trigger route (or the verb) to actually enqueue `TASK_WORKFLOW_RUN` - today only fleet/pump.py:182 produces it; the Queue mode carries the honest warn note until fixed.
3. `control.workflow.schedule` verb + schedule persistence and firing - today `POST /v1/workflows/{id}/schedule` validates and returns a spec only (platform_routes.py:273-284).
4. Workflow-filtered runs: `GET /v1/workflows/{id}/runs` is tenant-wide unfiltered (platform_routes.py:316-320); the Runs disclosure is labelled honestly until filtered.
5. `control.workflow.delete` - until it exists, no delete affordance for workflows anywhere (steps are definition edits and are fine).
6. Workflow input schema surfaced on the detail/summary so the Run region can render SchemaForm instead of the JSON disclosure (debt W5).

## 7. Build notes

- **New CSS** (join the cascade after the v3 layer, `--color-*` tokens only, block__elem--modifier): `.auto-card`, `.wf-canvas--slide`, `.steprail` (+ `__row`, `--collapsed`), `.wf-node__bar` (kind accent bar), `.wf-edge__add`, `.slide-edge` (+ `__chevron`, `__add`), plus the register's `.ux-savebar`, `.ux-pending`, `.ux-picker`, `.ux-chips`, `.ux-jsond`, `.ux-disclosure`, `.ux-skel`, `.ux-stepper`.
- **Primitives consumed** (register, section 9 of the pattern language): N3 ChipPicker, N4 EntityPicker, N6 Stepper, N7 SchemaForm v2, N8 Field v2, N9 JsonDisclosure, N10 SaveBar, N11 Disclosure, N13 Skeleton, N14 ArmConfirm, N15 PendingHumanCard, N16 ByChat. No new primitives beyond the register; the plus-panel reuses `.ux-picker` anatomy.
- **Glossary additions** (P22, extend never fork): `precreated` / `generated` / `learned` glosses; "workflow": "A governed chain of verbs agents run step by step."
- **Debt retired by this design**: W1-W7, C1-C6 (StudioPanel's workflow tab and the five stacked forms are superseded; point `#/studio`'s workflow tab at `#/automations`), X1 (for this surface, via SchemaForm v2), X2 (intent tags via ChipPicker), plus the clipboard verb palette (W2) replaced by real insert semantics.
- **Pure-function discipline**: `insert.ts` (append, splice-edge, insert-before-root, join-insert, splice-through-delete, descendants BFS) and the cron next-3 preview are pure and unit-tested (DESIGN-v2 decisive call 6: router-style logic stays testable without a UI framework).
- **Deck contracts honoured**: translate-only motion over React Flow (reader-shell section 3), no portals or fixed positioning inside slides, poll quiesce on inactive slides, id-keyed columns with no-lurch re-derivation, chevrons/plus in tab order, reduce-motion collapses all animation, `?run=` never moves the deck.