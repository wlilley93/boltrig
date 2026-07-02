# Agent builder row: build-ready surface spec

Row id `agents` in the deck grid (DESIGN-v2). Anchor (col 0) = the org chart. Columns 1..n = one slide per agent, keyed by agent name, in org order. This spec covers both slides, the create flows, the row data layer, all states, all copy, and the chat-parity mapping. Pattern citations (P-numbers, N-numbers, L-laws) refer to `docs/design/ui-patterns.md`. Everything renders inside the deck slide frame: each slide is its own scroller with the bordered-slide look, breadcrumb position chip in the header, edge chevrons, Ctrl+Alt+Arrow chord (DESIGN-v2 renderer + navigation affordances). No em dashes anywhere, including generated copy.

---

## 0. Routes and column model

```
#/agents                    anchor: org chart
#/agents/:name              per-agent slide, :name = capability name (encodeURIComponent'd)
#/agents/me                 the caller's personal agent slide (reserved key)
#/agents/new                create flow, kind not yet chosen
#/agents/new/:kind          create flow, kind in {head, worker, me}
```

Column order (ID-keyed per DESIGN-v2, never ordinal): `[chief-of-staff (hierarchy.tier1.name), ...tier2 heads in hierarchy order, ...ephemeral_runtimes in config order, "me", "new" (transient, only while active)]`. `me` is always present for authors (the agents row is AUTHOR_ROLES-gated per the DESIGN-v2 grid; non-authors keep the existing ops-row Me tab, out of scope here). `new` appears in the column list only while the route is on it; leaving it removes the column (DESIGN-v2: if the key vanished, navigate to the row anchor - but leaving `new` is always an explicit navigation, so no lurch case arises).

Reserved names: agent creation validates `name` against `^[a-z0-9][a-z0-9-]{1,62}$` and rejects the reserved keys `new` and `me` (P10 minted-id rules; S1 debt fix class).

Sidebar map: the agents row auto-expands its column list when active (DESIGN-v2 affordance 1); each entry = agent name (mono) with a dirty dot when its draft is dirty (P17) and a steady amber dot when a `pending_human` config change for it is unresolved (L4: this IS governance in play).

---

## 1. The row data layer: AgentsRowProvider

A row-scoped provider (the same model DESIGN-v2 mandates for the automations row: slides are stateless views over row-scoped state; edits write through immediately; unmount lossless). Mounted with the row, shared by the anchor and every agent slide via context.

### 1a. Reads (all existing; file:line grounded via reader-agents.md)

| Data | Call | Notes |
|---|---|---|
| Org tiers | `GET /v1/admin/config/hierarchy` (platform_routes.py:323-330) | `{tier1:{name,runtime,model_endpoint,max_depth,supported_skills[],cost_tier,budget}, tier2:[{...+department}]}` (config/manifest.py:92-111; manifest.yaml:43-100). Author/admin gated; a 403 here makes the whole row denied (section 4). |
| Worker pool | `GET /v1/admin/config/ephemeral_runtimes` | `[{name,runtime,model_endpoint,supported_skills[],max_depth,cost_tier}]` |
| Model endpoints | `GET /v1/admin/config/models` | `{endpoints:[{id,kind,model,base_url,data_class}], default, sensitive_endpoint}`. Transport for the endpoint picker. DEPENDS-BACKEND: `GET /v1/model-endpoints` reading store rows (reader-agents item 4); until then the config section is the source and the picker's hint says "as configured", not "as live". |
| Skills | `GET /v1/skills` (platform_routes.py:90-96) | `{skills:[{id,version,extends,tool_grants[],locale}]}`. Omits `prompt_fragment`/`description` (reader-agents item 9). |
| Verbs + bindings | `GET /v1/capabilities` (app.py:373-379; kernel/registry.py:76-111) | `{verbs:[{id,noun,input_schema,output_schema,consequence,binding}]}`, grant-intersected with the caller. Bindings inverted client-side: `binding.target_type === "agent"` groups by `target_ref` (= agent-capability name, models/registry.py:67-75). |
| Budgets | `GET /v1/budgets` (platform_routes.py:400-422) | Department rows matched by `scope_type === "department" && id === dept`. |
| Work | `GET /v1/work` (app.py:431-466) | Items grouped by `owner_member` (= department name). |
| Personal agent | `GET /v1/me/agent` (access_routes.py:253-259; client already has `api.meAgent()`, client.ts:650-652 - fixes the MePanel debt of never reading it) | `{agent:{id,runtime,skills[],enabled} | null}` |
| Pending approvals | `GET /v1/hitl` (app.py:392-406) | Used for pending-marker reconciliation (section 6). |

Fetch policy: hierarchy/ephemeral/models/skills/capabilities fetch once on row mount + on manual refresh + after any successful write; budgets and work poll at 30s with `useFetch { paused }` quiesced when no agents-row slide is active (DESIGN-v2 polling quiesce). No poll ever shows a skeleton (P24: first load only).

### 1b. The assembled org model

```ts
type OrgAgent = {
  name: string;                 // capability name, the column key
  kind: "cos" | "head" | "worker" | "personal";
  department?: string;          // heads only
  runtime: string; modelEndpoint?: string; maxDepth: number;
  costTier: "cheap" | "standard" | "premium" | string;
  isEphemeral: boolean;         // derived: workers true, tiers false
  skillPatterns: string[];      // supported_skills
  matchedSkills: Skill[];       // patterns matched against GET /v1/skills ids
  effectiveGrants: string[];    // union of matchedSkills[].tool_grants
  effectiveVerbs: Verb[];       // effectiveGrants patterns matched against /v1/capabilities ids
  boundVerbs: Verb[];           // inverted binding.target_ref === name
  budget?: BudgetRow;           // dept-scoped row (heads), tier budget from hierarchy (cos)
  workItems?: WorkItem[];       // heads: owner_member === department
};
```

Pattern matching (`ticket.*` style, `*` wildcard) is one shared pure function, unit-tested (DESIGN-v2 decisive call 6: pure functions, no new test framework). The provider also holds: `draftsByAgent` (P17 drafts), `createDraft`, `pendingByAgent` (hitl ids, section 6), and `sessionOrgEdits` (whether a hierarchy PUT happened this session, drives the staleness callout).

Honesty rule carried everywhere: the hierarchy section is config, and `PUT /v1/admin/config/hierarchy` edits the AdminConfig doc only; it does not rebuild the running org (config/admin.py:37-47; the fleet worker reads the manifest at boot, api/worker.py:37-46). Worker-profile capability rows written via `control.capability.upsert` ARE live for spawning (the spawner reads the store, fleet/spawn.py:391-408). The UI copy distinguishes these two truths explicitly (sections 3.4, 5.2, 5.3).

---

## 2. Slide A: the org chart anchor (#/agents)

### 2.1 Layout, region by region

The slide sets itself `overflow:hidden` (exception to the slide-scroller default: the canvas owns the space) and stacks four regions vertically:

1. **Header strip** (fixed, top): breadcrumb chip "Agents - org (1 of n)" (deck standard), title "Agents" (`--fs-xl`, 600), a counts line in `--color-text-secondary`: "1 chief of staff, 2 departments, 3 worker profiles" (numbers live from the model). Right-aligned actions: **New agent** (`btn--primary`, the single primary at rest, P20) and **Do this in chat** (ByChat, N16, P32). No other buttons.
2. **Callout slot** (conditional): the staleness callout after an org edit this session (copy in 8.3), and the CoachMark on first visit (P21 rung 5, id `boltrig.coach.agents-org`): "Each card is an agent. Open one to see and change what it can do. New agents start here." Dismiss persisted, never re-shown, never modal.
3. **Canvas** (flex:1): the @xyflow/react org chart, dot-grid background on `--color-bg-base`, minimal controls + minimap bottom-right offset above the deck minimap (DESIGN-SYSTEM section 5). Reuses RegistryCanvas's scaffolding: column/row layout algorithm shape (RegistryCanvas.tsx:146-218), drag-position preservation across refetches (:241-250), custom node types with Handles. Deck motion is translate-only so React Flow hit-testing stays correct (reader-shell section 3); the chord never fires inside `.react-flow` (P36).
4. **Facts strip** (fixed, bottom, 56px comfortable / 44px compact): renders only while a node is selected. Contents: kind badge, name (mono), "runtime pi - model standard - depth 3", skills matched count, verbs bound count, budget one-liner, and one button **Open agent** (`btn` ghost; still not a second primary). Empty selection hides the strip entirely.

### 2.2 Node anatomy (instances of the COMPONENT-SPECS section 1 hero node, kind = agent)

All nodes: `--color-bg-card`, `--radius-md`, 4px left accent bar, focusable, operable by keyboard, visible `--focus-ring`, 44px min targets under `(pointer:coarse)`. Kind is identifiable without reading the label (COMPONENT-SPECS acceptance). New CSS joins after the v3 layer as `.org-node`, `.org-node--cos|head|worker|personal|ghost`, `.org-pool`, composing the existing `.wf-node--agent` / `.badge` vocabulary.

- **Chief of Staff card** (row 0, centered, one only): cyan accent bar (`--color-accent`, agent kind). Header: name in mono (`chief-of-staff`), kind chip "Chief of Staff". Body: two badge rows: `runtime pi` + `model standard` + `depth 4`, then `skills: *` + `fulfils n verbs` (count only; verb fan-in stays a count, never edges - the Router registry canvas already draws verb->binding, consolidation over duplication). Footer: tenant budget meter (section 7) when tier1 budget exists.
- **Department card** (row 1, one per tier2 entry): the department and its head are one card, because they are 1:1 (the head IS the department's agent, fleet/pump.py:433-479). Top band (`--color-bg-raised`, hairline bottom border): department name in sentence case ("Engineering"), right-aligned work count badge ("3 in flight", from `owner_member` grouping) and the budget meter. Below the band: the head agent identity: name mono (`head-of-engineering`), cyan accent bar, badges `runtime` / `model` / `depth` / `cost tier`, skill patterns as up to 3 mono chips + "+n more", "fulfils n verbs" count. A steady amber `badge--conseq-high` "pending approval" chip appears when a `pending_human` config change for this agent is unresolved (L4 lawful: kernel governance in play).
- **Worker pool band** (row 2): one wide container node (`.org-pool`, `--color-bg-raised`, dashed `--color-border-subtle` border) titled "Worker pool" with the gloss line "Ephemeral workers are convened per task. The profile is chosen by skill coverage and cost tier, then discarded." Inside: one mini-card per ephemeral runtime: mono name, `cost_tier` badge (cheap tier gets `--color-text-muted` treatment, premium gets `--color-accent-2`), `runtime` chip, skills pattern chip. Mini-cards are individually focusable/clickable (they are columns of this row).
- **Your agent card** (row 2, right of the pool): indigo accent bar (`--color-accent-2`, "agent-flavoured secondary"). Title "Your agent", subtitle the runtime profile it references in mono ("runs as `worker-cheap`"), skills count, `enabled` state as a StatusBadge. When no personal agent exists: the card renders in ghost style (dashed border, muted) with "Not set up yet" and clicking it opens `#/agents/new/me`.
- **Ghost add cards** (author affordance, the visual create entry): a dashed, muted card at the end of the departments row labelled "+ Add department" and one inside the pool labelled "+ Add worker profile". Click navigates to `#/agents/new/head` / `#/agents/new/worker`. Ghost cards are real buttons in the canvas node layer, in tab order after the real nodes.

### 2.3 Edges (what a line means)

- **CoS -> each department card**: solid 1.5px `--color-border-strong`. Meaning: routes work to. No label (the tier structure is the label).
- **Department card -> worker pool**: dashed 1.5px `--color-border-subtle`, one per department, all terminating on the pool container. One shared caption rendered once under the pool title (not per-edge): "Heads convene workers from this pool." (Edge-per-head is honest: tier2 character convenes workers; the pool is org-wide, not per-department, so edges end on the container, never on a specific profile.)
- **Your agent -> its runtime profile mini-card**: dotted 1.5px `--color-accent-2`. Meaning: runs as.
- No verb edges, no skill edges (counts on cards; the detail lives one slide right). Animated dash only if a run is live on an edge; the org chart has no live-run overlay in this beat, so all edges are static.

### 2.4 Hover, selection, click-through, keyboard

- **Hover**: card raises to `--elev-1`, border to `--color-border-strong`. Native `title` on truncated ids (mono ids middle-truncate per P34).
- **Selection** (single click or Enter with node focused... see below): accent ring per COMPONENT-SPECS (selected = accent ring), facts strip appears. Exactly one selection; Escape clears it (only when the palette/drawer are closed; their Escape handlers win).
- **Click-through** (DESIGN-v2 affordance 7): double-click a card, click "Open agent" in the facts strip, or press Enter while the card is focused and already selected -> `navigate("#/agents/<name>")`; the deck animates one column right (or further, ID-keyed).
- **Keyboard**: nodes are focusable in layout order (CoS, heads left-to-right, pool profiles, your agent, ghost cards); Tab walks them (React Flow `nodesFocusable`); Enter on an unselected node selects, Enter again opens. Arrow keys inside the canvas pan per React Flow default; the deck chord Ctrl+Alt+Arrow is suppressed inside `.react-flow` (P36), so the edge chevrons and the facts strip button are the keyboard route out.
- **Drag**: nodes draggable; positions preserved across refetches exactly like RegistryCanvas (:241-250); structure changes (new agent) recompute layout for new nodes only.

### 2.5 The 80% path (P20)

"See the org, open an agent": land on `#/agents`, read the chart, double-click a card. Zero forms, zero Tier-2 controls. The one primary at rest is New agent; the empty state's CTA starts the create path (P24).

### 2.6 Anchor parity line (L2)

The anchor is a read surface; parity for reads is just asking. The ByChat affordance on the header still teaches it: phrase generated "Show me the org: departments, their heads, and the worker pool" (P32; prefill via `setComposerPrefill`, navigate to `#/chat`, never auto-send).

---

## 3. Slide B: the per-agent slide (#/agents/:name)

One layout, four kind-variants (CoS / head / worker / personal). Regions top to bottom inside the slide scroller. The slide is a stateless view over the provider's `draftsByAgent[name]` (P17): every edit writes through to the draft immediately; slide moves are lossless; the SaveBar (N10) pins to the slide bottom whenever the draft is dirty and saves the WHOLE profile.

### 3.1 Profile card (hero header region)

A full-width card, `--color-bg-card`, cyan left accent bar (indigo for the personal agent):

- Line 1: agent name, mono, `--fs-xl`, click-to-copy; kind chip ("Chief of Staff" / "Department head" / "Worker profile" / "Your agent"); for heads, the department name; the steady amber "pending approval" chip when a pending_human change is unresolved (section 6).
- Line 2, at-a-glance facts as labelled badges (every unobvious label carries its TermTip gloss, P21 rung 2): `runtime pi` - `model standard` (mono, with the endpoint's kind and a `data_class: sensitive` marker where applicable) - `depth 3` (gloss: "How many levels of sub-agents this agent may spawn.") - `cost tier standard` - `ephemeral` badge for workers (gloss from P2: "Ephemeral profiles are spawned per task and discarded.").
- Line 3 (heads and CoS only): the budget meter (section 7) + "n work items in flight".

### 3.2 Section: Soul (honest about composition)

Header "Soul" with TermTip: "What this agent is told it is. Composed by the kernel in layers; lower layers can never override higher ones." Rendered as a vertical stack of layer cards, each with a lock or edit affordance, mirroring `compose_system_prompt` exactly (fleet/prompt_stack.py:107-127):

1. **Governance floor** (all kinds): locked card (lock glyph, `--color-text-muted` border), label "Layer 1 - Governance floor (every agent, immutable)", body = the GOVERNANCE_FLOOR text verbatim (prompt_stack.py:27-37), collapsed to 2 lines with a Disclosure (N11) "Show full text". Hint: "This layer is the cage. It cannot be edited from anywhere."
2. **Tier character**: locked card, label "Layer 2 - Tier character (`tier1` / `tier2` / `ephemeral`)", body = the TIER_CHARACTER text for this kind verbatim (prompt_stack.py:84-104), same collapse. Hint: "Set by the agent's tier, shared by every agent at that tier."
3. **Department slant** (heads only): a card with two parts: the fixed line "Your department is engineering." (rendered as the kernel will compose it) and **Department brief**, the one editable soul field: auto-growing textarea (P10 long free text, prose, mono OFF), label "Department brief", hint "Extra standing context for this head. Sits below the governance floor and tier character; it can narrow, never widen.", placeholder "e.g. Prefer the internal ticket system for all engineering work. Escalate anything touching production credentials."
   **DEPENDS-BACKEND (SOUL-1)**: `department_brief` is plumbed into `compose_system_prompt` but nothing populates it from config (prompt_stack.py:118-125; reader-agents item 3). Required seam: the hierarchy tier2 entry gains a `brief` field, the pump passes it through, and the write travels via `control.hierarchy.upsert` (P31 registry). Until the seam lands, this field renders read-only-disabled with the honest line "Not wired up yet: the kernel supports a department brief but nothing stores one. Coming with the org-config verb." Never fake the write.
4. **Skill fragments** (workers and personal only): a card listing the matched skills whose `prompt_fragment`s are merged at spawn (fleet/spawn.py:236,267): skill ids as mono chips + the line "Each skill adds its own instructions when a worker is convened with it." **DEPENDS-BACKEND (SOUL-2)**: `GET /v1/skills` omits `prompt_fragment` and there is no `GET /v1/skills/{id}` (platform_routes.py:90-96; reader-agents item 9), so the fragment text is not readable; render the honest line "Fragment text is not readable via the API yet." Needed: single-skill read including `prompt_fragment`.

No per-agent free-form soul field is designed, because none exists (reader-agents 1c: agent persona/soul DOES NOT EXIST). The layer stack IS the truth, and rendering it faithfully is the design.

### 3.3 Section: Skills (the capability's reach)

One Field (P11): label "Skill patterns", hint "Which skills this agent may be imbued with. Patterns like `analysis/*` also cover skills added later.", control = **ScopeBuilder** (N5, P7) with the tree over SKILLS not verbs:

- Zone 1, value chips: the draft's `supported_skills` patterns, mono, removable.
- Zone 2, the tree: skills from `GET /v1/skills` grouped by path prefix (the `analysis/` in `analysis/ticket-decomposition`); each row shows the skill id (mono), version badge, and grant count; add affordance per row; adding a whole group offers "add `analysis/*` (pattern)" vs individual ids, with the one-time pattern Hint (P7).
- Zone 3, live match preview: "Matches 4 skills today" with the expandable match list; each matched skill row shows its `tool_grants` as a GrantList (this is the "matched-skills preview with tool_grants shown"); a no-match pattern renders the P7 warn state.
- Presets row: "Everything (`*`)" and "Match department (`<dept>/*`)" for heads.

Meta slot (P11): the match count. Async recompute is client-side and instant (all data local), so no debounce needed; still renders in meta, never blocks typing (P13).

### 3.4 Section: Verbs (two honest views, stacked, not tabs)

**View 1 - "Fulfils these verbs"** (the inverted binding view): table (P35) of verbs where `binding.target_type === "agent" && target_ref === name`. Columns: Verb (mono, `RunLink`-style click opens nothing here; it links to the Router home for that verb), Noun, Consequence (`StatusBadge` from the CONSEQUENCE glossary, high rows amber), Bound (relative time if known, else "-"). Empty view copy: "No verbs are bound to this agent. Binding a verb makes this agent the thing that fulfils it."

Row actions: none destructive (no unbind exists anywhere: deletes DO NOT EXIST, reader-agents 1c; P27 forbids rendering delete affordances until `control.binding.delete` lands). One footer action: **Bind a verb to this agent** (ghost) -> inline reveal (Disclosure, not a modal) containing one EntityPicker (P6, N4) over `GET /v1/capabilities` grouped by noun, consequence badges inline, preview card showing the verb's current binding ("currently runs via adapter `github`") so rebinding is a seen, deliberate act; then an ArmConfirm (N14, tone consequence) restating: "Bind `ticket.triage` to `head-of-engineering`? It currently runs via adapter `github`. Dispatching it will spawn this agent instead." Confirm label "Bind verb".
Write: `POST /v1/verbs/{verb_id}/binding {target_type:"agent", target_ref:name}` (platform_routes.py:166-177), direct author-gated route. **DEPENDS-BACKEND (PAR-3)**: design against `control.binding.upsert` (P31 registry row "Verb binding"); the direct route is the temporary transport behind the same form. This also fixes debt R5 (agent target was free text; here it is structural: the agent IS the context).

**View 2 - "Can call (effective grants)"**: a computed, read-only view with the intro line "What this agent could invoke, computed from its skill patterns: patterns match skills, skills carry grants, grants match verbs." Renders: the effective grant patterns as mono chips (union of matched skills' `tool_grants`), then the resolved verb list grouped by noun with consequence badges, "n verbs (m high consequence)". Honesty footnote (InfoCallout tone info, one per surface, P21 rung 4): "At run time a parent may narrow this further: a worker only ever receives a subset of its parent's authority." (fleet/spawn.py:297-301). Second footnote when relevant: "This view is computed with your grants; verbs outside your own scope are not shown." (the `/v1/capabilities` read is caller-intersected, kernel/registry.py:76-111).

**MCP note**: no per-agent MCP section exists because MCP consumers are tenant-wide verb sources, not per-agent attachments (reader-agents 1b item 5). A single muted line closes the verbs section: "Connected MCP servers contribute verbs tenant-wide; manage them in the Studio." Never a per-agent MCP picker (that would be UI pretending a backend exists).

### 3.5 Section: Model and limits (the editable capability core)

Fields, all committing to the draft (P17), all defaulted (P12 from the kernel's own defaults, control_plane.py:106-110):

| Field | Control | Spec |
|---|---|---|
| Model endpoint | EntityPicker (P6, N4) | Over `models.endpoints` from config; rows: id (mono), kind badge, model, `data_class` badge. Preview card under the field: kind, model, base_url host, data_class; sensitive endpoints carry the hint "sensitive-tagged work is routed only to this endpoint". Hint: "Which model serves this agent." In-flow absolute panel, z-index 30 (no portals, transformed ancestor). |
| Cost tier | CardSelect (P4, N2) | Three cards: "cheap - lowest-cost models, best for bulk work" / "standard - the default balance" / "premium - strongest models, highest cost". Radiogroup semantics, arrow keys. |
| Max depth | Stepper (P8, N6) | min 1, max 5, unit "levels", hint "1 to 5. How many levels of sub-agents this agent may spawn. Deeper trees cost more and are harder to audit." Default: current value; kernel default 1 (control_plane.py:107). |
| Runtime | Select (P3) | Options = union of runtimes observed across all capabilities plus the built-ins (`pi`, `hermes`); hint "The engine that runs this agent." **DEPENDS-BACKEND (PAR-6)**: a runtime registry read; until then the observed-union is honest and stated in the hint ("runtimes currently in use"). |
| Ephemeral | Segmented Yes/No (P2), Tier 3 | Inside the "More options" Disclosure (P18/N11) with changed-count summary. Hint: "Ephemeral profiles are spawned per task and discarded. Durable agents hold a seat in the org." For heads/CoS a warn Hint appends: "Making a seated agent ephemeral removes it from the org's durable structure." (It stays Segmented in the saved form, never a switch: governance weight, P2.) |
| Name | mono input, disabled in edit | Hint: "Names are permanent. Saving under a new name creates a new profile; it does not rename this one." (upsert keys on name, control_plane.py:104-113). |

Tier map (P18): Tier 1 = profile card + Skills + Model endpoint; Tier 2 = cost tier, max depth, runtime, the verbs views; Tier 3 = ephemeral + the JsonDisclosure escape hatch (N9, P10) "Advanced: edit as JSON" over the exact `control.capability.upsert` params object, two-way synced.

### 3.6 Section: Budget (read-only burn-down)

Heads: the department budget row from `GET /v1/budgets` (`scope_type:"department", id:<dept>`); CoS: the tier1 budget. Renders the budget meter (section 7) plus the facts line: "12.4 of 20.0 units spent this day - hard stop on" ("hard stop" gets a TermTip: "When spent reaches the limit, work stops instead of overspending."). Workers and personal agents: section renders one muted line: "Budgets are held by departments and the tenant, not by worker profiles."
Editing: not in this beat. Footer line: "Budgets are set in the org configuration." **DEPENDS-BACKEND (PAR-5)**: a `control.hierarchy.upsert` (or dedicated `control.budget.upsert`) verb; when it lands, this section gains a Disclosure edit with ArmConfirm. Until then no write affordance is rendered.

### 3.7 Section: Work (heads and CoS only)

Table (P35) of `GET /v1/work` items where `owner_member === department` (CoS: all items): columns When (relative, absolute on title), Item, Status (`StatusBadge` via WORK_STATUS glossary), Run (RunLink, opens the global drawer without moving the deck). "Load more" pagination. Empty: "No work in flight for engineering." Polls 30s, quiesced when the slide is inactive.

### 3.8 The save flow (the signature write)

1. Any edit -> draft dirty -> **SaveBar** (N10) pins to the slide bottom: "Unsaved changes to `head-of-engineering`" + primary button + Discard (ghost, arm-confirm per P27 semantics: "Discard changes to `head-of-engineering`? Your edits since the last save are lost." / "Confirm discard").
2. Because every `control.*` verb is consequence high (control_plane.py:49-50), the SaveBar carries the P28 foreshadow permanently while dirty: an `InfoCallout tone="consequence"` directly above the button: "This is a high-consequence change. It will pause for a human approval before it takes effect." Button label is honest: **Request change** (not "Save").
3. Submit: `POST /v1/invoke {noun:"control", verb:"control.capability.upsert", params:{name, runtime, supported_skills, max_depth, is_ephemeral, cost_tier, model_endpoint}}` (control_plane.py:64-76; app.py:259-283). Busy label "Requesting..." (X6 fix). Never autosave (P16 hard rule: autosaving a governed verb spams the approvals inbox).
4. Result rendering in the SaveBar result slot, the full union (P16):
   - `ok` -> quiet ok treatment "Change applied", draft becomes the saved state, provider refetches, sidebar dirty dot clears.
   - `202 pending_human` -> **PendingHumanCard** (N15, P30) renders inline: amber left bar, steady; headline "Paused for approval"; body: verb id `control.capability.upsert` mono, params summary as read-only SchemaForm values with JSON in a disclosure, "A person needs to approve this before it takes effect."; `hitl_request_id` mono copyable; "Open in Approvals" -> `#/approvals`; polls `GET /v1/hitl` at 8s, quiesced with the slide; approved -> flips to ok in place + provider refetch; rejected -> denial treatment with the recorded reason. If the current user can approve (they are not the requester and are human, SEC-14, app.py:408-427), the full approval card renders inline INSIDE it, arm-confirm still applying (P30, no rubber stamp). The draft stays pinned dirty-frozen (fields read-only with a "pending approval" wash) until resolution; Discard remains available.
   - `denied`/403 -> the calm warn callout with the server's reason verbatim (L3, P15, P24), no retry button.
   - `error` -> ErrorState with reason + "Try again".
5. While pending: the org chart card and the sidebar entry show the steady amber pending chip (section 6).

### 3.9 The personal agent slide (#/agents/me)

Profile card variant: indigo accent, title "Your agent", facts: runtime profile (mono), enabled StatusBadge, skills count. Sections:

- **Runs as**: EntityPicker over the worker-pool profiles (ephemeral runtimes) with the preview card (runtime, model, cost tier). Hint: "Your agent borrows a worker profile from the pool."
- **Skills**: ChipPicker (P5, N3) over `GET /v1/skills` ids (this is exact-id attachment, not patterns, per PersonalAgent.skills, models/platform.py:70-77 - so ChipPicker, not ScopeBuilder; P7's "no patterns, no match semantics" rule). This retires MePanel's append-only chips (design debt, MePanel.tsx:16-104).
- **Try it**: a small composer: one textarea + "Send to my agent" -> `POST /v1/me/agent/invoke {message}`; the response area renders `effective_grants` from the SpawnResult as a GrantList (the existing MePanel idiom, honest about the ceiling).
- Save flow: SaveBar, but the write is TODAY the ungoverned direct `POST /v1/me/agent {runtime, skills}` (platform_routes.py:524-545). Because that is not a governed verb, the SaveBar shows NO consequence foreshadow and the button says "Save agent" (foreshadowing a pause that will not happen would be dishonest). **DEPENDS-BACKEND (PAR-4)**: `control.personal_agent.configure`; when it lands the foreshadow + Request-change labelling switch on.
- **Honesty constraints**: the configure route hardcodes defaults and always mints a new uuid id, and does not accept `enabled` (platform_routes.py:524-529; reader-agents item 7 in section 3). Therefore: no enable/disable Switch is rendered (it would be a lie), the id is displayed but labelled "changes on every save (backend limitation)", both flagged DEPENDS-BACKEND (PAR-4 covers accepting `enabled` + stable id).

### 3.10 CoS and worker slide variants

- CoS: no department slant layer, no department work filter (shows all), Skills section present (tier1 has `supported_skills`), no delete/demote affordances (none exist).
- Worker: adds the P2 example exactly: `ephemeral` defaults Yes; the Soul section shows layers 1, 2 (ephemeral character), 4 (skill fragments); no budget, no work; an InfoCallout tone info once per surface: "Changes to worker profiles take effect for the next spawn; already-running workers are unaffected." (store-read at spawn, fleet/spawn.py:391-408).

---

## 4. Slide states (P24 precedence: denied > error > loading > empty > ready)

| State | Anchor | Agent slide |
|---|---|---|
| **Denied** | Hierarchy `GET` 403 -> the faithful denied slide (DESIGN-v2): PageIntro "Agents" + calm warn callout with the server's reason verbatim + "Ask an admin to widen your access." No retry. Chevrons stay live (the user is not trapped). | Same treatment if any constituent read 403s; per-section denial (e.g. budgets denied but capability readable) renders the callout inside that section only, rest of slide ready. |
| **Error** | ErrorState + "Try again"; status 0 copy "Can't reach the server - check your connection." | Same, per P24. |
| **Loading** | Skeleton (N13, first load only): variant "cards": one centered bar (CoS), a row of 3 card blocks, one wide band. Shimmer off under reduce-motion. Polls never re-skeleton. | Skeleton variant "cards": hero bar + 3 section blocks. |
| **Empty** (fresh org: no tier2, no ephemeral runtimes) | EmptyState (ux.tsx:161-180): title "No agents yet"; body "Your org has a chief of staff and nothing else. Add a department with a head agent, or a worker profile for the pool."; one CTA "Create your first agent" -> `#/agents/new`; plus the ByChat line "or ask in chat: 'Create an engineering department with a head agent'." (P20/P32). If even tier1 is absent, same state with body "Nothing is configured yet." | Unknown `:name` (key vanished / bad deep link): per DESIGN-v2, navigate to the row anchor; a direct deep link renders one frame of "No agent named `x`" then redirects. |
| **Pending** | Steady amber chip on the affected card. | Frozen-dirty fields + PendingHumanCard (3.8). |
| **Ready degraded** | If capabilities read failed but hierarchy loaded: chart renders, verb counts show "-" with a `badge--degraded` and a warn callout naming what was unhealthy (P24 degraded is information, not a wall). | Same per section. |

---

## 5. The create flows (#/agents/new[/:kind])

The `new` column slide. Header: breadcrumb "Agents - new agent". Region 1 is the kind chooser; regions below appear per kind. Back-navigation (chevron left) never loses the create draft (row-scoped `createDraft`, P17).

### 5.1 Kind chooser: CardSelect (P4, N2)

Prompt line: "What kind of agent?" Three cards (radiogroup):

1. **Department head (durable)** - "A seated agent that owns a department. Work is routed to it; it convenes workers." Badges: `tier 2`, `needs org config`.
2. **Worker profile (ephemeral)** - "A reusable profile the pool spawns per task, then discards." Badges: `pool`, `live on approval`.
3. **Your personal agent** - "A private assistant that acts only with your delegated authority." Badge: `only you`.

Pre-selected when the route carries `:kind` (ghost-card entry from the chart). Choosing navigates to `#/agents/new/<kind>` (route is the state; deck stays on the same slide key).

### 5.2 Worker profile: ONE form, not a wizard (P19: never a wizard for a single upsert)

Sections (P19 sections, single Save):

- **Identity** (Tier 1): Name: mono input, charset hint "Lowercase letters, digits, hyphens. e.g. `worker-scraper`", live pattern validation on blur (P13), uniqueness checked against the assembled capability names with the duplicate warning "That name exists. Saving will replace `worker-cheap`'s profile." (S1 class fix). This is the surface's ONE blank-required field (P12 case 4) and takes first focus.
- **Skills** (Tier 1): ScopeBuilder as in 3.3, default `["*"]` (kernel default, control_plane.py:106) with hint "Start wide, narrow later. `*` lets this profile take any skill."
- **Model and limits** (Tier 2): endpoint EntityPicker (default = the config `models.default`), cost tier CardSelect (default standard), depth Stepper (default 2, matching the manifest convention for workers; the kernel default 1 is stated in the hint).
- **More options** (Tier 3, Disclosure): ephemeral Segmented (default Yes), JsonDisclosure escape hatch.

Footer: consequence foreshadow callout (P28) + primary **Request worker profile** + ByChat. Submit = one `control.capability.upsert` invoke; the result union renders per 3.8. On `ok` or approval: success line "Profile `worker-scraper` is live. The pool can spawn it for the next matching task." + link "Open its page" -> `#/agents/worker-scraper` (the new column now exists; provider refetched). The 80% path: type a name, press Request (everything else defaulted, L5).

### 5.3 Department head: a genuine wizard (P19: later steps depend on earlier ones AND the operation is two-phase in the kernel)

This is the one flow in this row that is lawfully a wizard, because it writes TWO different stores through two different doors: the governed capability upsert (may pause for approval) and the versioned hierarchy config PUT (org structure). The wizard makes that two-phase truth legible instead of hiding it. Step indicator: an `ol` with `aria-current="step"`, labels below; Back never loses state; the final step restates everything and doubles as the arm step (P19/P29 semantics).

**Step 1 - Department.** Fields: Department name (sentence-case input, hint "The routing bucket. Work addressed to this department lands with its head."; uniqueness vs existing tier2 departments) and Head agent name (mono, defaulted live from the department: "legal" -> `head-of-legal`, editable, same validation as 5.2; a visible generated default outranks an example, P11/P12).

**Step 2 - Soul.** Read-only preview of layers 1 + 2 (tier2 character) exactly as 3.2, so the author sees what the agent will be told, plus the Department brief textarea (disabled with the SOUL-1 honesty line until the seam lands).

**Step 3 - Skills.** ScopeBuilder; default preset applied: `["<department>/*", "analysis/*"]` shown as chips (mirrors the manifest convention, manifest.yaml tier2 entries) with match preview live.

**Step 4 - Model and budget.** Endpoint EntityPicker (default `models.default`), cost tier CardSelect (default standard), depth Stepper (default 3, the tier2 convention). Budget subsection: limit numeric input with unit "units/day" (plain numeric, not a Stepper: unbounded precise value, P8 not-when) + window Segmented (daily/weekly, P3) + hard stop Segmented Yes/No with hint "When spent reaches the limit, work stops instead of overspending." Default: 20 units daily, hard stop Yes (the manifest convention).

**Step 5 - Review and create.** Restates every choice as read-only Field rows grouped by step. Then the two-phase truth, stated plainly inside an InfoCallout tone consequence:
"Creating a head is two changes:
1. The agent profile - a governed change. It will pause for a human approval.
2. The org chart entry - a versioned config change, applied immediately once you confirm.
The running org picks up new departments when the fleet worker restarts." (api/worker.py:37-46; config/admin.py:37-47 - never claim liveness that does not exist.)
Primary: **Request head agent** -> `control.capability.upsert` (params: name, runtime pi, supported_skills, max_depth, cost_tier, model_endpoint, is_ephemeral:false).
- On `ok` OR when the PendingHumanCard resolves approved: the second half unlocks in place: a fresh button **Add to org chart** with ArmConfirm (N14, tone consequence): "Add `legal` with head `head-of-legal` to the org configuration? This writes revision n+1." Confirm -> `PUT /v1/admin/config/hierarchy {value: <current hierarchy with the new tier2 entry appended>}` (platform_routes.py:332-344; read-modify-write from the freshly refetched section to avoid clobbering). Never auto-fired on poll resolution: a human clicks the second write.
- On rejected: denial treatment; "Add to org chart" never unlocks; the draft persists for amendment.
- Success: "Department `legal` created (config revision n). The head goes live when the fleet worker restarts." + staleness callout pinned on the anchor (8.3) + link "Open `head-of-legal`".

**DEPENDS-BACKEND (PAR-2)**: the hierarchy half must become `control.hierarchy.upsert` (P31 registry; consequence high; params = the section value). The wizard is designed against that verb: when it lands, the second button becomes a second governed invoke with its own PendingHumanCard, and the copy drops "applied immediately". **DEPENDS-BACKEND (ORG-1)**: an org-apply seam (reader-agents item 8): nothing rebuilds the running CoS/heads pump without a worker restart; the honest restart line stays until a reload seam exists.

### 5.4 Personal agent create (kind = me)

The 3.9 form in create mode: runtime EntityPicker over pool profiles (default: the cheapest profile, stated), skills ChipPicker (default: empty is NOT acceptable per L5 unless nothing is sensible; default = no preselection but the field is first-focus with the teaching empty line "Pick at least one skill so your agent can act.", P12 case 4). Primary "Set up my agent" -> `POST /v1/me/agent`. Success navigates to `#/agents/me`.

---

## 6. Pending-approval reconciliation (P33 symmetry)

`pendingByAgent` is fed two ways: (a) every 202 this session records `{hitl_request_id, agentName}`; (b) on row mount and each PendingHumanCard poll tick, `GET /v1/hitl` rows are scanned for requests whose `context` identifies a `control.capability.upsert` for a known agent name (the context dict rides the request, app.py:392-406). Resolution always reconciles from the server, never component memory alone (P33; the `resolvedHitls` local-map anti-pattern is explicitly not reproduced). A pause started in chat ("make worker-cheap durable") therefore shows the same amber chip on the org chart and the same frozen state on the agent slide; approving from either side converges via the same `POST /v1/hitl/{id}/respond`. **DEPENDS-BACKEND (PAR-7, soft)**: a filterable HITL list (`GET /v1/hitl?verb=control.capability.upsert`) or a guaranteed context shape (`context.verb_id`, `context.params.name`) would make (b) exact instead of best-effort; until then the scan is best-effort and the session map is authoritative for chips.

---

## 7. BudgetMeter (display-only; proposed register addition)

The pattern register has no burn-down display; per its own rule this is a fork back to the pattern document, filed here as proposed **N17 BudgetMeter** (display-only, non-interactive, so no control-taxonomy conflict). Anatomy: a 6px track (`--color-bg-raised`, hairline border) with a fill = spent/limit; fill colour `--color-accent` below 80%, `--color-warn` 80-99%, `--color-down` at/after 100%; NEVER `--color-consequence-high` (L4: nearing a budget is a warning, not a governance pause). Right-aligned facts text (P34 numbers): "62% - 12.4 of 20.0/day", `hard stop` chip when true. `role="img"` with `aria-label` = the facts sentence. Text fallback (and the compact-density rendering on chart cards): the facts sentence alone. Cost figures derive from `spent_micros/cost_limit_micros`; token budgets render the same shape with unit "tokens".

---

## 8. Copy blocks (canonical strings)

### 8.1 Glossary additions (P22: extend ux.tsx glossary, never local variants)
- **department**: "A routing bucket owned by one head agent. Work addressed to it lands with the head."
- **worker pool**: "Reusable ephemeral profiles. The kernel picks one per task by skill coverage and cost tier."
- **depth**: "How many levels of sub-agents an agent may spawn."
- **soul**: "What an agent is told it is: governance floor, then tier character, then department slant. Lower layers never override higher ones."
- **ephemeral**: "Spawned for one task, then discarded."

### 8.2 Key labels and hints (already placed above; the load-bearing ones)
- Skills field hint: "Which skills this agent may be imbued with. Patterns like `analysis/*` also cover skills added later."
- Name permanence hint: "Names are permanent. Saving under a new name creates a new profile; it does not rename this one."
- Consequence foreshadow (P28, verbatim everywhere): "This is a high-consequence change. It will pause for a human approval before it takes effect."
- PendingHumanCard body line: "A person needs to approve this before it takes effect."

### 8.3 Staleness callout (anchor, after any hierarchy PUT this session; InfoCallout tone warn)
"Org configuration updated (revision n). The running org picks up structure changes when the fleet worker restarts." Dismissible; re-appears per further edit.

---

## 9. Chat-parity registry for this row (P31; every flow, verb path, phrasing, status)

| UI flow | Verb path | Chat phrasing (ByChat-generated from state) | Status |
|---|---|---|---|
| Edit agent profile (skills/model/tier/depth) + Request change | `control.capability.upsert` via `POST /v1/invoke`, 202 pending_human path (control_plane.py:64-76; app.py:259-283) | "Give `head-of-engineering` the `writing/*` skills as well and set its depth to 3" | EXISTS (governed) |
| Create worker profile | `control.capability.upsert` (is_ephemeral true) | "Create a cheap worker profile called `worker-scraper` that can use scraping skills, depth 2" | EXISTS (governed) |
| Create head, phase 1 (profile) | `control.capability.upsert` (is_ephemeral false) | "Create a legal department head agent on the standard model" | EXISTS (governed) |
| Create head, phase 2 (org entry) / budget edit | `control.hierarchy.upsert` | "Add the legal department to the org chart" | **DEPENDS-BACKEND PAR-2** (today direct `PUT /v1/admin/config/hierarchy`, platform_routes.py:332-344; chat CANNOT do this today - a named parity gap, flagged in the wizard spec) |
| Bind a verb to an agent | `control.binding.upsert` | "Make `head-of-engineering` fulfil `ticket.triage`" | **DEPENDS-BACKEND PAR-3** (today direct `POST /v1/verbs/{id}/binding`, platform_routes.py:166-177) |
| Configure personal agent | `control.personal_agent.configure` | "Set up my agent as `worker-cheap` with the research skill" | **DEPENDS-BACKEND PAR-4** (today ungoverned `POST /v1/me/agent`, platform_routes.py:524-545; also needs `enabled` + stable id) |
| Edit department brief (soul seam) | `control.hierarchy.upsert` carrying `tier2[].brief` | "Set the engineering brief to: prefer the internal ticket system" | **DEPENDS-BACKEND SOUL-1** (prompt_stack.py:118-125 seam unpopulated) |
| Model endpoint change (from the picker's "manage endpoints" link, out of row scope) | `control.model_endpoint.upsert` (control_plane.py:77-88) | "Route sensitive work to the local endpoint" | EXISTS (governed) |
| Approve/reject a pause | `POST /v1/hitl/{id}/respond` (app.py:408-427) | inline hitl card in chat / PendingHumanCard inline approval here | EXISTS (one route, both clients, P33) |
| Any delete (agent, binding, department) | `control.*.delete` | - | DOES NOT EXIST; no delete affordances rendered anywhere on this row (P27/P31) |
| Reads (org, skills, budgets, work) | shared `GET /v1/*` | "Show me the org" / "What can head-of-engineering call?" | EXISTS |

ByChat (N16, P32) appears on: the anchor header, every SaveBar, both create-form footers, and every empty state. Phrase built from current draft state; prefill via `setComposerPrefill`, navigate `#/chat`, composer focused, never auto-sent.

## 10. Consolidated DEPENDS-BACKEND ledger

- **PAR-2** `control.hierarchy.upsert` (org structure + budgets + brief as one section verb, consequence high, params = section value; note in its spec that it does not rebuild the live org, ORG-1).
- **PAR-3** `control.binding.upsert`.
- **PAR-4** `control.personal_agent.configure` (accept `enabled`, stable id).
- **PAR-5** budget editing (rides PAR-2 or `control.budget.upsert`).
- **PAR-6** runtime registry read.
- **PAR-7** filterable/typed HITL list for cross-session pending markers (soft).
- **SOUL-1** hierarchy `brief` -> `compose_system_prompt(department_brief=...)` seam.
- **SOUL-2** `GET /v1/skills/{id}` including `prompt_fragment` (also unblocks the skill-fragment soul layer).
- **ORG-1** org-apply/reload seam so hierarchy changes reach the running pump without a worker restart.
- **CAP-1** (nice-to-have) `GET /v1/capabilities/profiles` listing AgentCapability store rows; until then the config sections are the transport and the anchor states config truth, not store truth, in the staleness callout.

## 11. Build notes for the implementing engineer

- New CSS: `.org-node` family, `.org-pool`, `.org-facts-strip`, `.ux-budgetmeter`; join the cascade after the v3 layer, semantic `--color-*` tokens only, `block__elem--modifier` naming (reader-shell section 2). Deck motion stays translate3d (React Flow constraint, reader-shell section 3); EntityPicker panels are absolute in-flow, z-index 30 (< drawer 70 < palette 80).
- Reuse: RegistryCanvas layout + drag-preservation logic (RegistryCanvas.tsx:146-218, 241-250); ApprovalsPanel arm-confirm extraction (N14); glossary maps in ux.tsx (extend per 8.1); `apiReason` for every faithful error (shared.tsx:14-24).
- Primitives consumed (all from the register): N2 CardSelect, N3 ChipPicker, N4 EntityPicker, N5 ScopeBuilder, N6 Stepper, N8 Field v2, N9 JsonDisclosure, N10 SaveBar, N11 Disclosure, N12 CoachMark, N13 Skeleton, N14 ArmConfirm, N15 PendingHumanCard, N16 ByChat; proposed N17 BudgetMeter (section 7, needs pattern-doc ratification).
- Design debt retired by this spec: S1 (id validation + duplicate warning), R5 (agent binding target structural), X3 (arm-confirm not window.confirm), X6 (verb-specific busy labels), MePanel append-only chips + never-reading `meAgent`, and the P31 rule that the console prefers the verb over any coexisting direct route.
