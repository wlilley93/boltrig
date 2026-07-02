# Boltrig UI pattern language

Draft of `docs/design/ui-patterns.md`. Binding on every deck surface and every retrofit of an existing panel. Written by the pattern-language seat against: the visual canon (`docs/design/DESIGN-SYSTEM.md`, `COMPONENT-SPECS.md`, `CLAUDE-DESIGN-BRIEFING.md`), the frozen deck mechanics (`DESIGN-v2.md`), the ground-truth readers (chat, agents, workflows, shell, spec), and the code as it exists: `ui/src/panels/ux.tsx`, `ui/src/panels/shared.tsx`, `ui/src/styles.css`, `boltrig/config/control_plane.py`.

How to cite: surface designers reference patterns by number ("the step-slide verb field follows P6 + P9"). New components come only from the register in section 9; if a surface needs a control not in this document, that is a fork back to this document, not a local invention.

Vocabulary note: "verb path" means the kernel invocation a flow traverses: `POST /v1/invoke {noun, verb, params}` returning `{status:"ok"|"degraded"|"denied"|"error"}` or `202 {status:"pending_human", hitl_request_id}` (app.py:259-283). "Direct route" means an author-gated HTTP route that bypasses the chokepoint (e.g. `POST /v1/skills`); the readers enumerate these and this document treats each as a backend dependency to be replaced by a `control.*` verb, following the naming and shape of `boltrig/config/control_plane.py`.

---

## The five laws (cross-cutting, every pattern serves them)

- **L1 - Considered controls.** Structured pickers over free text; progressive disclosure over walls of options; labelled, defaulted, validated inputs over raw JSON. Free text only where free text is the genuinely right control: names, descriptions, prompts, questions.
- **L2 - Chat parity.** The console and the chat are two clients of one verb-space. Every write flow in every surface spec MUST name its verb path and its conversational phrasing. No UI-only capability. Where today's operation is a direct route, design against the `control.*` verb that should exist and flag the backend dependency (P31 carries the registry).
- **L3 - Server authority.** Role gates are cosmetic. The server's 403/denied body is always rendered faithfully via `apiReason` (shared.tsx:14-24). The UI never pre-guesses a denial and never invents a reason.
- **L4 - Amber is reserved.** `--color-consequence-high` (#FF7A45) appears ONLY when the kernel's governance is in play: consequence-high verbs, HITL pauses, `pending_human`. Local destructive actions are red (`--color-down`); warnings are `--color-warn`. If a surface uses amber for anything else it is wrong.
- **L5 - No blank-required.** Every field ships a sensible default (P12). A form that opens with an empty required field is a design failure to be justified, not a neutral choice.

---

## 1. Control taxonomy

### P1 - The decision table (data shape to control)

This table is the whole of section 1 in one view. The rest of the section specifies each row.

| Data shape | Control | Primitive | Status |
|---|---|---|---|
| boolean inside an explicitly-saved form | Segmented Yes/No | `Segmented` (ux.tsx:113-140) | exists |
| boolean that applies instantly (a setting) | switch | `Switch` (N1) | new |
| enum, 2-4 values, short labels | segmented control | `Segmented` | exists |
| enum, >4 values or long labels | labelled select | `Select` (ux.tsx:80-110) | exists |
| enum where choosing needs metadata (cost, capability, risk) | card select | `CardSelect` (N2) | new |
| multi-select from a known finite set | chip picker with search | `ChipPicker` (N3) | new |
| reference to one entity (verb, skill, model endpoint, agent, workflow) | searchable grouped picker + inline preview | `EntityPicker` (N4) | new |
| grant / scope / skill patterns | scope builder: verb tree + pattern chips + live match preview + presets | `ScopeBuilder` (N5) | new |
| bounded number with meaning (depth, TTL, limit) | stepper with unit | `Stepper` (N6) | new |
| unbounded number / free numeric id | `input[type=number]` inside `Field` | exists | exists |
| structured object WITH a JSON schema | schema-driven form | `SchemaForm` v2 (N7 upgrade) | upgrade |
| structured object WITHOUT a schema | JSON escape hatch inside a disclosure | `JsonDisclosure` (N9) | new |
| short free text (name, title, id being minted) | `input` inside `Field`; mono when it is a system identifier | exists | exists |
| long free text (prompt, description, question, notes) | auto-growing `textarea` inside `Field` | exists | exists |
| raw JSON as primary control | NEVER | - | forbidden |

Raw JSON is only lawful as the explicit "advanced" escape hatch of P10, always inside a collapsed disclosure, never the first thing a user sees. The current `SchemaForm` fallback line "Edit this field in the JSON view." (ux.tsx:319) is exactly the smell this table exists to remove.

### P2 - Boolean: Segmented vs Switch

**Anatomy.** In an explicitly-saved form: `Segmented` with options Yes/No (exactly as SchemaForm renders booleans today, ux.tsx:296-307), full `Field` treatment (label, hint). For instant-apply settings: `Switch` (N1), `role="switch"`, label left, control right, a transient "Saved" wisp (fades in `--dur-med`) on successful persist, reverts with a faithful error on failure.

**Use when** the value is truly binary and both states are safe.
**Not when** one state has governance weight. `hard_stop` on a budget or `is_ephemeral` on a capability stay Segmented inside the saved form with a hint explaining the consequence; never a cheerful instant toggle.
**Boltrig example.** Notification channel enable/disable rows in Settings become `Switch` (they apply immediately via `putMeSettings`). `is_ephemeral` on the agent slide's capability form stays `Segmented` with hint "Ephemeral profiles are spawned per task and discarded."
**Verb path.** Capability booleans travel in `control.capability.upsert` params; chat: "Make worker-cheap a durable profile" -> orchestrator invokes `control.capability.upsert {name:"worker-cheap", is_ephemeral:false, ...}` -> 202 pending_human (consequence high).

### P3 - Enum: Segmented (<=4) vs Select (>4)

**Anatomy.** `Segmented` shows all values at once, current pressed (`btn--seg-on`, aria-pressed); each option may carry a `hint` tooltip (Option.hint exists, ux.tsx:73-77). `Select` is the native labelled dropdown; first option is never a fake blank when a default exists (L5): default is preselected, "Choose..." placeholder appears only when no default is defensible AND the field is optional.

**Use** Segmented when the whole value space fits on one line at compact density and seeing all options teaches the domain (mode switches, source types). Select above 4 values or when labels are long.
**Not** Segmented for values with rich tradeoffs (that is P4), and never Select for 2 values (a dropdown hiding a binary is dead weight).
**Boltrig example.** Memory recall mode (similarity vs Connections) is Segmented (MemoryPanel already does this). Role assignment uses `Select` over `ROLE_OPTIONS` (6 values, hints exist, ux.tsx:432-439). Workflow `source` (precreated/generated/learned) is Segmented with hints.

### P4 - Enum with metadata: CardSelect

**Anatomy** (N2). A `role="radiogroup"` of 2-5 cards in a responsive row. Each card: title (`--fs-md`, 600), one sentence of meaning (`--color-text-secondary`), meta badges (existing `.badge` families). Selected card: `--color-accent` border + the focus ring token. Arrow keys move selection (radio semantics); click or Space selects.

**Use when** the user cannot choose correctly without comparing attributes: cost, capability coverage, risk class.
**Not when** the enum is self-describing (P3) or has >5 options (that is an `EntityPicker`, P6, with preview).
**Boltrig example.** Choosing `cost_tier` on an agent slide: cards "cheap / standard / premium" each with an indicative cost line and which runtimes qualify. Choosing `data_class` on a model endpoint: "standard" vs "sensitive" where the sensitive card carries the hint "sensitive-tagged work is routed only to this endpoint".
**Verb path.** `control.capability.upsert` / `control.model_endpoint.upsert` params; chat: "Route sensitive work to the local endpoint" -> `control.model_endpoint.upsert {id:..., data_class:"sensitive"}` -> 202.

### P5 - Multi-select from a known set: ChipPicker

**Anatomy** (N3). Selected values render as removable chips (existing `.tag`/`.chip` vocabulary, mono when values are system ids). Below or beside: a search input filtering the known set; matching candidates render as add-chips (the exact interaction MePanel already has for skills, MePanel.tsx:16-104, promoted to a primitive). Keyboard: type to filter, ArrowDown into candidates, Enter adds, Backspace in empty search removes the last chip. Empty set shows the P24 empty treatment inline ("No skills selected. Add at least one so the agent can act.").

**Use when** picking several values from a finite enumerable set the server can list.
**Not when** the set is patterns/scopes (that is P7 ScopeBuilder - patterns need match preview) or when order matters (use an ordered list editor, which no current surface needs; do not build one speculatively).
**Boltrig example.** Personal-agent skills (source `GET /v1/skills`), `intent_tags` on a workflow (free-entry variant: candidates from existing tags, plus "add '<text>'"), notification channels per event type (`NOTIFY_CHANNEL_OPTIONS`, ux.tsx:420-427).
**Verb path.** Personal agent: today the direct route `POST /v1/me/agent` (platform_routes.py:524-545); design against `control.personal_agent.configure` (backend dependency, P31). Chat: "Give my agent the research skill" -> that verb -> low consequence, immediate ok.

### P6 - Entity reference: EntityPicker

**Anatomy** (N4). A trigger button styled as an input: current value (mono for ids) + kind badge + chevron. Opens an in-flow dropdown panel (no portals exist in this codebase and the deck transform breaks `position:fixed`, reader-shell section 3, so the panel is absolutely positioned inside the field wrapper, z-index 30, below drawer 70 / palette 80). Panel = search input (autofocus) + grouped results (group headers: noun for verbs, kind for endpoints, tier/department for agents) + per-row: id (mono), display label, meta badges (consequence for verbs, health for adapter-bound, runtime for agents). Keyboard: ArrowUp/Down, Enter select, Escape close. On selection, an **inline preview card** renders under the field: for a verb - consequence badge, binding ("runs via <adapter|agent>", from `binding.target_type`), 1-line description, param count; for an agent - runtime, model endpoint, cost tier; for a model endpoint - kind, model, data_class; for a workflow - version, step count, intent tags; for a skill - version, grant count.

**Use for** every reference to another entity in the system. The verb pickers in DevConsole (a flat `<select>` over the whole registry today, DevConsolePanel.tsx:279) and the step slide's action field are the flagship retrofits.
**Not for** enums (P3/P4) and not as a browse surface: if the user's real task is exploration, link to the entity's home (Router tree, agent slide) instead.
**Boltrig example.** Step slide "Action" field: EntityPicker over caller-scoped `/v1/capabilities`, grouped by noun, consequence-high rows carrying the amber marker so the author sees the approval pause coming (visual canon: "foreshadows that running it will pause for approval", DESIGN-SYSTEM.md section 5).
**Verb path.** The picker itself is a read (`GET /v1/capabilities`); the write it feeds is the owning form's verb (e.g. `control.workflow.upsert` for a step edit). Chat: "Change the notify step to use ticket.create" -> orchestrator edits the definition and invokes `control.workflow.upsert` -> 202.

### P7 - Grants and scopes: ScopeBuilder

**Anatomy** (N5). Three stacked zones inside one `Field`:
1. **Value chips**: the actual value, a `string[]` of grant tokens/patterns (`ticket.*`, `web.fetch`), mono chips, removable. This is the same value shape as `skill.tool_grants`, PAT scopes, `supported_skills` patterns and eval `forbidden_grants`, so one primitive serves all four.
2. **The verb tree**: caller-scoped `GET /v1/capabilities` grouped by noun; noun rows expand to verb rows; each row has an add affordance; consequence-high verbs carry the amber marker inline. A search box filters the tree. Adding a whole noun offers "add ticket.* (pattern)" vs "add the 3 verbs individually" - patterns are a taught concept here, with a one-time `Hint`: "A pattern like ticket.* also covers verbs added later."
3. **Live match preview**: a computed line under the chips: "Matches 7 verbs today (2 high consequence)" with an expandable match list. A pattern matching nothing renders a warn state: "matches no verbs today - it will apply to future verbs that fit."
Plus a **presets** row of ghost buttons (e.g. "Read-only", "Everything low-consequence", "Department default") that populate chips; presets are client-side sugar, the value stays the pattern list.

**Use for** anything whose value is grant/scope patterns: skill `tool_grants` (StudioPanel), PAT scope subset (Settings, SEC-34 - preset here is "All my grants" and the tree is capped at the caller's own grants, mirrored server-side), capability `supported_skills` (tree is over skills not verbs, same anatomy), eval `forbidden_grants`.
**Not for** simple multi-select (P5) - if there are no patterns and no match semantics, ChipPicker is enough.
**Verb path.** Skill grants: today direct `POST /v1/skills`; design against `control.skill.upsert` (P31). Chat: "Create a triage skill that can read tickets but never send email" -> `control.skill.upsert {id:"triage", tool_grants:["ticket.get","ticket.list"]}`; the orchestrator states the match preview back in prose before invoking.

### P8 - Numbers: Stepper with units

**Anatomy** (N6). `input[type=number]` flanked by minus/plus buttons (`btn--sm`), a unit suffix inside the field ("levels", "days", "facts"), min/max/step enforced, clamp on blur, the whole thing inside `Field` with the range stated in the hint ("1 to 5. Deeper trees cost more and are harder to audit.").

**Use for** bounded quantities where nudging is natural: `max_depth`, invite TTL, recall `limit`, hop count.
**Not for** unbounded or precise identifiers (ports, budget micros): plain numeric input with example text. Sliders only when the value is continuous AND the extremes are safe; Boltrig currently has no such value, so no slider primitive is registered (keep the vocabulary minimal).
**Boltrig example.** Agent slide `max_depth` stepper 1-5, default 1 (mirroring the kernel default, control_plane.py:107).

### P9 - Structured objects: SchemaForm v2

**Anatomy** (N7, an upgrade of ux.tsx:258-330 in place, same call signature). Rules:
- **Required-first ordering**: required properties render first in schema order, then optional, then the advanced disclosure.
- **Per-type controls from P1**: boolean -> Segmented; enum <=4 -> Segmented, >4 -> Select; number/integer with min+max -> Stepper, else numeric input; string -> input (textarea when `format` hints long text or the description says prompt/body); array of enum -> ChipPicker (known set); array of string -> ChipPicker (free-entry); object one level deep -> an inline bordered group with its own properties recursed once; deeper nesting or additionalProperties -> `JsonDisclosure` for that subtree only, never for the whole form.
- **Defaults**: `schema.default` wins; else the type's zero-cost skeleton (the logic of `skeletonFromSchema`, DevConsolePanel.tsx:52, moves into the form so defaults are visible values, not a JSON string).
- **Validation**: required, type, enum membership, min/max, checked per P14 timing; errors placed per P15.
- **Advanced folding**: when optional fields > 6, optional tail collapses into a "More options (n)" disclosure (P19).
- **The escape hatch**: one `JsonDisclosure` at the form's end, "Advanced: edit as JSON", two-way synced (P10).

**Use for** every verb `params` surface: DevConsole invoke, step-slide params, HITL context re-display.
**Not for** objects whose schema is `{"type":"object"}` with no properties (the `_OBJ` outputs, control_plane.py:34): render `JsonDisclosure` directly, honestly labelled.
**Verb path.** SchemaForm v2 IS the parity engine: it renders exactly the `input_schema` the orchestrator validates against, so the form and the chat sentence compile to the same params object.

### P10 - Free text and the JSON escape hatch

**Free text is lawful for**: names/ids being minted (mono input, charset hint, uniqueness checked on blur where a read exists), descriptions, prompts (`prompt_fragment` in the skills studio: auto-growing textarea, mono OFF - prose is prose), questions and notes (HITL clarification answers, approval notes). Everything else must justify itself against P1.
**JsonDisclosure** (N9): a collapsed `<details>`-based disclosure labelled "Advanced: edit as JSON", containing the mono textarea + a validity line. Two-way sync contract: opening it serializes current form state (`prettyJson`); a valid edit reflects back into the form on blur; an invalid edit blocks collapse and blocks save with the P15 error treatment ("invalid JSON", the `parseJson` message, shared.tsx:37-45). The disclosure summary shows a dot when JSON has diverged unapplied.
**When NOT**: never as the primary control (L1); never for values a structured control exists for; never auto-expanded.
**Boltrig example.** Eval case input JSON keeps the escape hatch but gains a SchemaForm face when the target skill declares a schema; workflow paste-import (`extractSteps` accepts three shapes, WorkflowCanvas.tsx:305-317) stays a JSON textarea because import IS the advanced path - but inside a disclosure on the automations picker slide, not a primary control.

---

## 2. Form anatomy

### P11 - Field discipline (the extended Field)

**Anatomy.** `Field` (ux.tsx:39-71) is the one wrapper for every labelled control, extended with `error?: ReactNode` and `meta?: ReactNode` (N8, upgrade in place):
- **Label**: sentence case, noun phrase, no colon, no trailing period. Required marker stays the existing `*` with title tooltip.
- **Control**: exactly one control per Field.
- **Hint**: what it is + why it matters, one sentence, `--color-text-secondary`. A hint is not a warning (that is a callout, P21) and not a validation message.
- **Example**: a concrete value in `code` ("e.g. `ticket.*`") - keep for pattern-shaped and id-shaped inputs; drop when the default already demonstrates the shape (a visible default outranks an example, L5).
- **Error**: below hint, `--color-down` text, `aria-describedby` + `aria-invalid` wired, control border flips to `--color-down`.
- **Meta** (right-aligned slot in the label row): live derived facts - a match count, a health badge, "12 of 60 chars".
**When NOT**: naked controls are lawful only inside table rows and card headers where the column/context is the label; even there `aria-label` is mandatory (Select and Segmented already accept it).

### P12 - Defaults policy

Every field ships a default. Sources, in order: (1) the kernel's own defaults, mirrored exactly so the form shows what the kernel would do anyway (`supported_skills:["*"]`, `max_depth:1`, `is_ephemeral:true`, `cost_tier:"standard"`, control_plane.py:106-110; `version:"1.0.0"`, `source:"precreated"`, control_plane.py:97-98); (2) `schema.default`; (3) the type's neutral skeleton; (4) for entity references with no defensible default (which verb? which agent?), the field is the surface's FIRST focus and its empty state teaches ("Choose the verb this step runs. Everything else has a default."). A required field that opens blank is permitted only in case (4) and there may be at most one per surface (P20).
**Boltrig example.** The step slide opens with params prefilled from schema defaults the moment a verb is chosen; Save is enabled immediately; the author's minimum path is: pick verb, press Save.

### P13 - Validation timing

- Validate a field on **blur**, not on first keystroke.
- Once a field has shown an error, revalidate on **change** so the error clears the moment it is fixed.
- Submit/Save validates everything and moves focus to the first errored field.
- JSON textareas validate on blur AND on any attempt to commit/navigate (the canvas dirty-inspector guard, WorkflowCanvas.tsx:444-454, generalized by P17).
- Async checks (id uniqueness, pattern match counts) run debounced 400ms after change, render in the `meta` slot, and never block typing.
- Server-side failure after submit is placed per P15 and always carries the faithful reason (`apiReason`).

### P14 - (folded into P13/P15; number reserved to keep citations stable)

### P15 - Error placement

Field-scoped errors live in the Field's error slot (P11). Cross-field and server errors render ONCE at the form footer, immediately above the actions, as `ErrorState`/`FetchError` with the server's reason verbatim; a 403 renders as the calm warn callout, not red (ux.tsx:206-241). Never a toast (no toast system exists and none is being added), never an alert(), never only colour. The form footer error and a field error may coexist when the server names the field ("reason: unknown model_endpoint" also highlights that field when the mapping is unambiguous).

### P16 - Save models

- **Explicit Save** for anything that traverses a verb, an author-gated route, or shared state: workflow definitions, skills, capabilities, model endpoints, hierarchy, bindings, admin config. Save button label names the object ("Save workflow"), busy state shows progress text ("Saving..."), success renders the result union faithfully (ok / degraded / pending_human per P30, denied/error per P28/P29).
- **Autosave (debounced, with a quiet "Saved" affirmation)** only for personal, low-blast, instantly-reversible preferences: appearance (already live-preview + persist, SettingsPanel.tsx:257-376), notification routing, display name.
- **Never autosave through a governed verb.** Every `control.*` verb is consequence high; autosaving would fire a 202 pending_human per keystroke and spam the approvals inbox. This is a hard rule, not a taste rule.
- Draft-vs-saved is P17's contract.

### P17 - Dirty state and unsaved changes in a moving deck

The deck's row-scoped provider model (DESIGN-v2: step slides are stateless views over a row-scoped graph provider; edits write through immediately, unmount lossless) generalizes:
- **Two layers**: field edits commit to an in-memory **draft** immediately (slide moves are lossless by construction); draft-to-server is the explicit Save of P16.
- **The SaveBar** (N10): a bar pinned to the bottom of any slide whose owning draft is dirty: "Unsaved changes to <object>" + Save (primary) + Discard (ghost, arm-confirm per P29). On a multi-slide draft (a workflow's step slides), the SaveBar appears on every slide of that row and saves the whole draft.
- **Dirty pinning**: dirty slides are keep-alive pinned (DESIGN-v2 mount policy), and the sidebar map + minimap show a dirty dot on that row.
- **Blocking is the exception**: navigation away never destroys a draft, so navigation is never blocked, with ONE exception: an invalid JSON escape hatch (unparseable text cannot round-trip into the draft) blocks the slide move with focus returned to the textarea and the P15 error (the existing canvas guard's semantics).
- Route-level leave (switching workflows, closing the SPA) with a dirty draft: `beforeunload` guard plus an in-app arm-confirm on the picker ("Discard unsaved changes to invoice-flow?").

---

## 3. Progressive disclosure

### P18 - The three tiers

- **Tier 1 (always visible)**: identity + required fields + anything with no default (P12 case 4). Must fit without scrolling at comfortable density on a 1280px slide.
- **Tier 2 (visible, subordinate)**: common optional fields, grouped under plain section headers, after Tier 1.
- **Tier 3 (collapsed)**: rarely-touched and expert fields inside a Disclosure (N11) labelled "More options" or a named group ("Delivery windows"), with a **changed-count summary** on the collapsed state: "More options (2 changed)". Non-default values must be discoverable without expanding: the count is mandatory.
**When NOT**: never hide a field whose CURRENT value deviates from default in a way that changes behaviour the user is looking at ("why is this paused?" must never be answered inside a collapsed tier - consequence/HITL-relevant fields are Tier 1 by law, L4).
**Boltrig example.** DevConsole invoke: verb picker + SchemaForm required fields are Tier 1; description/context Tier 2; run-id, manual entry, raw JSON are Tier 3 (matching the panel's existing "advanced" instinct, DevConsolePanel.tsx:86-135, now formalized).

### P19 - Steps vs sections vs disclosure

- **Steps (a wizard)** only when later choices genuinely depend on earlier ones or the operation is two-phase in the kernel. Boltrig has exactly two today: MCP server register -> review -> activate (SEC-22 makes activation a distinct reviewed act, platform_routes.py:201-228) and invite user (identity -> role -> TTL -> issued secret shown once). Wizards get a step indicator, back never loses state, and the final step restates everything (it doubles as the arm step, P29, when the finish is high-consequence).
- **Sections** when fields are peers: settings sub-pages, the agent slide.
- **Disclosure** for Tier 3 only.
**When NOT**: never a wizard for a single upsert (a skill is one Save, not four steps); never tabs inside a slide (the deck's columns ARE the tabs; nested tab systems are forbidden on deck surfaces).

### P20 - The 80% path

Every surface declares its 80% path in its spec: the sequence a competent user takes for the most common intent, and it must be completable using only Tier 1 controls and one primary action. Corollaries: exactly ONE `btn--primary` per surface at rest; at most one blank-required field (P12); the 80% path is what the empty state's CTA starts (P24) and what the ByChat phrasing describes (P32).
**Boltrig example.** Automations row: 80% path is "pick a workflow, see the canvas, run it" - so the picker slide is a list with Run affordances, not a form; authoring is the columns to the right.

---

## 4. Teaching UI

### P21 - The teaching ladder

For any concept on any surface, apply the FIRST sufficient rung, never two rungs for the same concept in the same view:
1. **Nothing**: universal concepts (save, search).
2. **TermTip** (ux.tsx:404-410, native title gloss): compact surfaces - column headers, dt labels, badges. Every badge already carries its gloss via the glossary (WORK_STATUS/AUDIT_STATUS/HITL_TYPE/HITL_URGENCY/CONSEQUENCE, ux.tsx:342-377); keep that as the single source.
3. **Hint** (ux.tsx:244-246): a control whose correct use needs one sentence of why.
4. **InfoCallout** (ux.tsx:143-158): a concept that changes what happens NEXT: the high-consequence foreshadow before an invoke (tone consequence), a 403 explanation (tone warn), "memory not enabled" (tone info). One callout per concept per surface, placed where the consequence lands (above the action, not at page top).
5. **CoachMark** (N12): first-use only, one per surface maximum, dismiss persisted in `localStorage boltrig.coach.<id>`, never re-shown, never modal. Reserved for the deck's own novel mechanics (the first time a user lands on a column slide: "You are one step right of the canvas. Ctrl+Alt+Left goes back.") and the first pending_human a user ever sees.

### P22 - The concept canon (single-source copy)

These one-liners live in the ux.tsx glossary and are the ONLY definitions any surface renders (extend the glossary, never write a local variant):
- **verb**: "An action an agent can take, like ticket.create. Every action runs through the kernel."
- **noun**: "A thing verbs act on. Verbs are grouped by their noun."
- **consequence**: "How much an action matters. High-consequence actions pause for a human before they run." (CONSEQUENCE glossary exists, ux.tsx:374-377.)
- **grant**: "Permission to use a verb. Patterns like ticket.* cover every verb that fits."
- **HITL / approval**: "A pause where a person approves, answers, or takes over before work continues." (HITL_TYPE exists.)
- **binding**: "What actually fulfils a verb: an adapter (a connected system) or an agent."
- **skill**: "A packaged ability: instructions plus the grants it needs."
- **run**: "One traced execution. Everything an agent did, in order, auditable."
**Tone rules for all copy**: calm, precise, active voice, present tense, second person where a person acts; sentence case; no exclamation marks; no scare-words ("dangerous") - state facts ("sends email outside the org; pauses for approval"); no jargon without its rung-2 gloss on first use; ids/verbs/patterns always in mono (brand law, DESIGN-SYSTEM.md section 3); never blame the user ("That id is taken", not "You entered a duplicate id"). No em or en dashes anywhere, ever.

### P23 - (reserved; coach marks specified in P21 rung 5 and N12)

---

## 5. States

### P24 - The state machine and its precedence

Every data surface renders exactly one of, in precedence order: **denied (403) > error > loading (first load only) > empty > ready (possibly degraded-flagged)**. `useFetch` already scopes blocking "loading" to the first load and keeps stale data through polls (useFetch.ts:51-53): therefore polls and reloads NEVER show skeletons or spinners; content updates in place. Never render an empty state for a denial (a 403 with an empty-looking body is still denied), and never an error state for emptiness.

- **Empty** (`EmptyState`, ux.tsx:161-180): title says what would be here; body says what it means; exactly one CTA starting the 80% path (P20); optionally the ByChat alternative (P32): "or ask in chat". Kanban's empty already routes to /chat - keep that as the canonical example.
- **Denied**: the calm warn callout with the server's reason verbatim + "Ask an admin to widen your access." (FetchError's 403 branch, ux.tsx:216-218). No retry button (retrying a 403 is noise). The DESIGN-v2 "faithful 403 slide" for the agents row is this pattern at slide scale: PageIntro + the callout, chevrons still live so the user is not trapped.
- **Error**: `ErrorState` with reason + "Try again"; network (`status 0`) copy is "Can't reach the server - check your connection."
- **Degraded**: content SHOWS, flagged: a `badge--degraded` at the data's edge plus, where the result union says `status:"degraded"`, a warn callout naming what was unhealthy. Degraded is information, not a wall.

### P25 - Skeleton vs spinner policy

- **Skeleton** (N13): first load of a surface whose shape is known (tables, card lists, the transcript, the org chart): 3-5 shimmer bars/blocks in the target layout, `--color-bg-card` base, shimmer disabled under reduce-motion (static blocks). Skeletons never appear longer than once per mount and never during polls.
- **Spinner**: none exists and none is added at surface scale. Button-local busy is TEXT ("Saving...", "Recording...", the existing idiom in ApprovalsPanel/DevConsole) plus disabled state.
- **Streams**: a streaming turn shows the cyan arrival treatment (visual canon), not a spinner; "waiting for the first event" is a single muted line ("Working...").

---

## 6. Destructive and high-consequence

### P26 - (reserved)

### P27 - Local destructive: two-step arm-confirm

**Anatomy** (`ArmConfirm`, N14, an extraction of ApprovalsPanel.tsx:141-176 and the Memory Forget confirm): step 1, a plain button states the act ("Delete conversation"); arming swaps IN PLACE (no modal, no portal) to a restatement + confirm pair: an `InfoCallout` (tone warn for local destructive; red button `btn` with down colouring) restating object and effect ("Delete 'triage escalation'? Its transcript stays in the audit log.") + "Confirm delete" + Cancel (ghost). Disarm on Cancel, Escape, or slide navigation. Enter confirms only while the confirm button itself is focused: no default-Enter destruction. States: rest / armed / busy ("Deleting...") / done or faithful error.
**Use for** every destructive or irreversible-feeling local act: delete conversation, forget fact, revoke token/session, revoke invitation, config rollback.
**Not for** kernel-governed high-consequence acts - those do not need a heavier client ritual, because the kernel itself holds them (P30); the arm step there is honesty about the pause, not a second gate. And never `window.confirm`.
**Verb path.** Delete conversation: `DELETE /v1/me/conversations/{id}` today; chat: "Delete my triage conversation" -> orchestrator uses the same soft-close; note deletes for skills/verbs/bindings/capabilities/workflows DO NOT EXIST anywhere (reader-agents section 1c) - no surface may render a delete affordance for those until `control.*.delete` verbs land (P31).

### P28 - Consequence foreshadowing

Any control about to submit through a consequence-high verb carries, at rest, the amber signal BEFORE the act: the `badge--conseq-high` on the verb row/picker, and an `InfoCallout tone="consequence"` directly above the primary action: "This is a high-consequence change. It will pause for a human approval before it takes effect." (The DevConsole already does this; it becomes law for every `control.*` form, since all `control.*` verbs are high, control_plane.py:49-50.) The button label stays honest: "Request change" reads better than "Save" when a pause is certain.

### P29 - (reserved)

### P30 - The 202 pending_human moment (Boltrig's signature state)

**Anatomy** (`PendingHumanCard`, N15). When an invoke returns `{status:"pending_human", hitl_request_id}` the surface renders a first-class card, not an error and not a toast:
- Amber-orange left accent bar (`--color-consequence-high`), steady, never pulsing (canon: paused is steady vs running's pulse).
- Headline: "Paused for approval".
- Body: what was asked, faithfully: the verb id (mono), a params summary (SchemaForm values read-only, JSON in a disclosure), and the plain sentence "A person needs to approve this before it runs."
- The `hitl_request_id` in mono, copyable.
- Primary link: "Open in Approvals" -> `#/approvals` (the ops row slide); secondary: the run link when a run_id exists (`RunLink`).
- **Live resolution**: the card polls `GET /v1/hitl` (8s, pausing when its slide is inactive per the deck's quiesce contract) and flips in place: approved -> ok treatment with the result; rejected -> the denial treatment with the recorded reason. If the CURRENT user can approve it, the full approval card (COMPONENT-SPECS section 4) renders inline INSIDE the PendingHumanCard so the round trip is zero clicks - but the arm-confirm ritual of the approvals surface still applies (no rubber stamp).
**Use** everywhere a write can 202: every `control.*` form, DevConsole invoke (upgrading its current one-liner, DevConsolePanel.tsx:103-106), workflow run pauses (the paused step slide + run drawer), chat (where the same event renders as the inline hitl card - P33 symmetry).
**Not**: never render pending_human as a failure, never auto-retry it, and never suppress it into a spinner. The pause IS the product.

---

## 7. Chat parity as a pattern

### P31 - The parity law and the write registry

Every surface spec MUST contain a parity table: UI action | verb path | chat phrasing | status. The binding registry of console writes as of this draft:

| Console write | Verb path | Status |
|---|---|---|
| Workflow save (canvas, step slides) | `control.workflow.upsert` | verb exists (also a direct route; UI uses the verb) |
| Agent capability save (agent slide) | `control.capability.upsert` | verb exists |
| Model endpoint save | `control.model_endpoint.upsert` | verb exists |
| Skill create/update (studio) | `control.skill.upsert` | BACKEND DEP (today direct `POST /v1/skills`) |
| Verb/noun authoring | `control.verb.upsert`, `control.noun.upsert` | BACKEND DEP (today direct) |
| Verb binding | `control.binding.upsert` | BACKEND DEP (today direct `POST /v1/verbs/{id}/binding`) |
| MCP server register / adapter activate | `control.mcp_server.register`, `control.adapter.activate` | BACKEND DEP (SEC-22 review context must ride in params) |
| Org hierarchy edit | `control.hierarchy.upsert` | BACKEND DEP (today `PUT /v1/admin/config/hierarchy`; note it does not rebuild the live org - the UI must say so honestly) |
| Personal agent configure | `control.personal_agent.configure` | BACKEND DEP (today ungoverned `POST /v1/me/agent`) |
| Any delete | `control.*.delete` | DOES NOT EXIST; no delete affordances until it does |
| HITL respond | `POST /v1/hitl/{id}/respond` | exists; same route serves chat's inline card and the approvals surface |

Rules: (1) the console always prefers the verb over a coexisting direct route; (2) a BACKEND DEP row means the surface is designed and built against the verb's intended shape (control_plane.py naming: `control.<noun>.<verb>`, consequence high, params mirroring the store model) with the direct route as a temporary transport behind the same form, flagged in the surface spec; (3) reads stay reads: `GET /v1/*` routes are the shared read surface for both clients.

### P32 - The ByChat affordance

**Anatomy** (`ByChat`, N16). A quiet ghost affordance on every write surface (form footer, next to the primary action) and every empty state: "Do this in chat". Activating it reveals (inline disclosure) the equivalent conversational phrasing generated FROM CURRENT FORM STATE, e.g. on a step slide: "Add a step after fetch-invoice that runs ticket.create with priority high" - then a button "Open in chat" which (a) stores the phrasing via a one-shot module store (`setComposerPrefill(text)`, the identity-store idiom; a hash query param is not used because `?run=` owns the query slot), (b) `navigate("/chat")` (the deck animates to the chat anchor), (c) ChatPanel consumes the prefill into the composer, focused, NOT auto-sent. The user reviews and sends; the orchestrator invokes the SAME verb from the P31 table; a high-consequence result streams back as the inline hitl card.
**Use** on every write flow and empty state; it is the parity law made visible and it teaches users that chat is a full client.
**Not** on read-only surfaces (chat parity for reads is just asking; no affordance needed), and never as auto-send (the user always owns the send).

### P33 - HITL symmetry

One pause, two renderings, one truth: a 202 in the console renders PendingHumanCard (P30); the same pause in chat renders the inline hitl card (chatTurn.tsx:238-329); both resolve through `POST /v1/hitl/{id}/respond`; the approvals surface is the canonical inbox both link into. Resolution state must reconcile from the server (poll `GET /v1/hitl`), not live only in component memory (the current `resolvedHitls` local map is the anti-pattern, reader-chat section 4). A user who starts in the UI, gets paused, and approves from chat (or vice versa) must see a consistent story on both surfaces.

---

## 8. Density and keyboard

### P34 - Density rules

- Surfaces declare themselves **data-heavy** (audit, runs, work, budgets, user directory, capability lists) or **form** (everything in sections 1-2). Data-heavy surfaces honour `data-density="compact"` aggressively (the existing `--gap` collapse, styles.css:123-125) and prefer tables; form surfaces stay comfortable even under compact (fields never tighter than 8px vertical rhythm - cramped forms cause errors).
- Mono for every id, verb, grant, run id, hash (brand law). Long ids middle-truncate with full value on title and click-to-copy.
- Numbers right-aligned, tabular where the font allows; timestamps relative with absolute on title.

### P35 - Table anatomy

Header: `--fs-xs`, uppercase, `--color-text-secondary`, each unobvious column head carrying its TermTip gloss (P21 rung 2). Rows: 36px comfortable / 30px compact; hairline `--color-border-subtle` separators; hover raises to `--color-bg-card`. `thead` is `position:sticky; top:0` INSIDE the slide scroller (lawful now that each slide is its own scroller, DESIGN-v2 renderer). Cells: ids mono; every run id a `RunLink` (shared.tsx:73-83, opens the global drawer without moving the deck); status cells are `StatusBadge` from the glossary; empty cell renders a muted "-", never blank. Column budget: 7 max; beyond that the row links to its entity's home. Row actions: at most two inline (icon+label ghost buttons); destructive row actions arm-confirm IN the row (P27), never a modal. Pagination: "Load more" over page numbers (audit/runs are streams, not books).

### P36 - Keyboard map (beyond the deck chord)

- Global (exists, preserved): Cmd/Ctrl+K palette; Escape closes palette/drawer; Ctrl+Alt+Arrow deck moves with the guardrails DESIGN-v2 enumerates (never in inputs, .react-flow, or under open overlays).
- Forms: Enter submits a single-input form; Cmd/Ctrl+Enter submits textareas (chat composer, notes); plain Enter in a textarea is a newline, always.
- Pickers (EntityPicker/ChipPicker/CardSelect): type-to-filter, ArrowUp/Down, Enter select, Escape close, Backspace-on-empty removes last chip; roving tabindex inside listboxes so Tab always leaves the widget in one step.
- Lists/tables: "/" focuses the surface's filter input when focus is not already in an editable.
- ArmConfirm: Enter confirms only on the focused confirm button; Escape disarms.
- Every interactive element keeps the visible focus ring (styles.css:1581-1590); 44px targets under `(pointer:coarse)` (styles.css:1593-1604) apply to all new primitives, including chevrons and chips.

---

## 9. New primitives register

Minimal by law: three are in-place upgrades of existing code, two are extractions of existing panel logic. All live in `ux.tsx` (or a sibling `ux-pickers.tsx` if size demands), reference semantic `--color-*` tokens only, join the CSS cascade after the v3 layer, follow `block__elem--modifier` naming with the `ux-` prefix, and ship all P24 states plus reduced-motion behaviour.

| # | Name | Props (essence) | States | Extends |
|---|---|---|---|---|
| N1 | `Switch` | `checked, onChange, label, disabled, busy` | off/on/busy/saved-wisp/error(revert) | `.seg`/`.btn` tokens; `role="switch"`; new `.ux-switch` |
| N2 | `CardSelect` | `value, onChange, options:[{value,label,body,badges}], ariaLabel` | rest/selected/hover/focus/disabled | `.card` surfaces + `.badge`; new `.ux-cardsel`, radiogroup semantics |
| N3 | `ChipPicker` | `value:string[], onChange, options:Option[], searchable, allowFree?, mono?` | empty/filtering/full/disabled | `.tag`/`.chip` + input styles; new `.ux-chips` |
| N4 | `EntityPicker` | `value, onChange, groups:[{label, items:[{id,label,badges,preview}]}], placeholder, renderPreview?` | closed/open/filtering/no-matches/selected(+preview)/disabled | `.btn`, `.badge`, `.cmdk__list` list styling; new `.ux-picker` (absolute panel, z-index 30) |
| N5 | `ScopeBuilder` | `value:string[], onChange, tree:{noun:[verb]}, matches:(patterns)=>Verb[], presets?:[{label,value}]` | empty/populated/pattern-no-match(warn)/preview-expanded | composes N3 chips + a tree list + `Hint`/`InfoCallout`; new `.ux-scope` |
| N6 | `Stepper` | `value, onChange, min, max, step, unit?` | rest/at-min/at-max/error | `input[type=number]` + `.btn--sm`; new `.ux-stepper` |
| N7 | `SchemaForm` v2 | same signature as today (ux.tsx:258-266) + `errors?, onValidity?` | per P9; per-field P11 states | upgrade in place; consumes N3/N4/N6/N9 |
| N8 | `Field` v2 | + `error?: ReactNode, meta?: ReactNode` | + errored | upgrade in place; `.ux-field__error`, `.ux-field__meta` |
| N9 | `JsonDisclosure` | `value:object, onChange, label?` | collapsed/expanded/diverged(dot)/invalid(blocks) | `<details>` + `.codeblock` + `parseJson`; new `.ux-jsond` |
| N10 | `SaveBar` | `dirty, objectLabel, onSave, onDiscard, busy, result?` | hidden/dirty/busy/result(ok, degraded, pending_human via N15, denied, error) | `.btn--primary` + `ErrorState`; new `.ux-savebar` pinned in slide |
| N11 | `Disclosure` | `summary, changedCount?, children, defaultOpen?` | collapsed/expanded | `<details>` styled; new `.ux-disclosure` |
| N12 | `CoachMark` | `id, children` (self-dismissing via localStorage `boltrig.coach.<id>`) | unseen/dismissed(null) | `InfoCallout tone="info"` + dismiss button; no new CSS beyond `.ux-coach` |
| N13 | `Skeleton` | `variant:"rows"|"cards"|"transcript", count?` | shimmering/static(reduce-motion) | `--color-bg-card`; new `.ux-skel`, `aria-hidden`, honours `:root.reduce-motion` |
| N14 | `ArmConfirm` | `label, confirmLabel, tone:"danger"|"consequence", summary:ReactNode, onConfirm, busy` | rest/armed/busy | extraction of ApprovalsPanel.tsx:141-176; `InfoCallout` + `.btn`; disarm on Escape/navigation |
| N15 | `PendingHumanCard` | `hitlRequestId, verbId, params, runId?, canAnswerInline?` | pending/approved/rejected/expired | `.ux-callout--consequence` + `.badge--conseq-high` + `RunLink`; polls `/v1/hitl` with slide-quiesce; new `.ux-pending` |
| N16 | `ByChat` | `phrase:string` (or `buildPhrase:()=>string`) | rest/revealed | ghost `.btn` + `Disclosure`; module store `setComposerPrefill` |

Everything else in this document composes existing vocabulary: `PageIntro`, `Field`, `Select`, `Segmented`, `InfoCallout`, `EmptyState`, `ErrorState`, `FetchError`, `Hint`, `StatusBadge`, `TermTip`, `RunLink`, `GrantList`, `CodeBlock`, the badge/tag/chip CSS families, and the glossary maps: extend those, never fork them.

---

## Appendix: bar-to-pattern map (for the surface designers)

- Principal bar 1 (considered, structured, guided): P1-P20, L1, L5.
- Principal bar 2 (chat parity): P31-P33, L2, plus the verb-path line every pattern's Boltrig example carries.
- Visual canon (amber reserved, mono ids, calm dark instrument): L4, P22, P28, P30, P34.
- Server authority: L3, P24 (denied), P15 (faithful reasons).
- Deck mechanics: P17 (dirty pinning + SaveBar), P24 (slide-scale 403), P30/N15 (poll quiesce), P35 (sticky thead inside slide scrollers), P36 (chord guardrails).
