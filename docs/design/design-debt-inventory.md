# Design-debt inventory: every surface failing the Principal's bar

Scope: full sweep of the legacy UI source (all panels, ux.tsx, shared.tsx, App.tsx). Each finding: location, what the user is asked, why it fails, and the considered replacement in one line. Chat-parity flags are noted where the operation is a direct route today and needs a `control.*` verb (per config/control_plane.py naming) before the chat client can do it.

## Cross-cutting (fix once in ux.tsx / shared.tsx, inherited everywhere)

- **X1. `SchemaForm` punts objects/arrays to raw JSON** - ux.tsx:318-319 renders "Edit this field in the JSON view." for any `object`/`array` property. Every guided form degrades to a JSON box the moment a verb has a nested arg. Replacement: nested key-value row editor for objects + list builder for arrays inside SchemaForm; JSON stays the escape hatch only.
- **X2. `csvToList` comma-CSV is the standing pattern for list input** - shared.tsx:48-53 feeds grants, skills, scope, tags, labels, departments across 9 call sites (inventoried per panel below). Replacement: one new `TokenMultiSelect` primitive (searchable options + removable chips + pattern support) specified once, reused everywhere; kill the CSV inputs.
- **X3. `window.confirm` used for destructive actions in 7 places** (SettingsPanel.tsx:552, 976, 892, 1250; AdminPanel.tsx:130; MemoryPanel.tsx:279) despite the sanctioned two-step arm-confirm pattern already existing (ApprovalsPanel.tsx:141-162). Replacement: an `ArmConfirm` primitive extracted from the Approvals card, used for revoke/rollback/forget/delete/deactivate.
- **X4. Raw snake_case table headers** - SettingsPanel.tsx:1050-1057 (`seq`, `ts`, `run_id`), MemoryPanel.tsx:627-637 (`source_kind`, `owner_scope`, `facts_added`). Insight already does this right (InsightPanel.tsx:296-305: "When / Actor / Action"). Replacement: human labels + `TermTip` glossary + relative timestamps.
- **X5. Sub-tab switches silently discard in-progress form state** - StudioPanel.tsx:1401-1416 and SettingsPanel.tsx:1449-1469 unmount the active sub-view on tab click with no dirty guard. Replacement: unsaved-changes guard (arm before leaving a dirty form) or persist draft state per tab.
- **X6. Busy labels collapse to "..."** on most primary buttons (e.g. StudioPanel.tsx:224, 713, 1102). Minor, but off-canon: replace with verb-specific progress ("Saving...", "Generating...").

## Studio > Skills (StudioPanel.tsx)

- **S1. Skill id free text with unenforced format** - :162-164. Hint says "Lowercase, dotted, unique" but nothing validates it and uniqueness is not checked against the loaded skills list. Replacement: pattern-validated input (live invalid state) + duplicate-id warning ("this will overwrite v1.2.0").
- **S2. Version free-text semver** - :165-167. No validation, no auto-bump despite "bump on every change". Replacement: semver stepper defaulting to next-patch of the existing skill.
- **S3. Grants edited as comma CSV** - :181-189 (`csvToList` at :115). The add-chips at :190-205 are append-only (no remove, no search, dumps every verb unfiltered) and write back into the CSV string. Replacement: grants free-text -> scoped verb picker: searchable multiselect with removable pattern chips + role presets, showing each verb's consequence badge.
- **S4. context_requirements raw JSON** - :206-221. Replacement: "requires" key chip builder over known context fields; JSON under Advanced.
- **S5. No edit affordance on the skills list** - :296-304. Editing an existing skill means retyping its id into the create form. Replacement: click a row to load it into the form in edit mode.
- **S6. Test spawn uses the old naked `label.field` primitive** - :238-252: lowercase "skill id" / "task" labels, no hint, and the skill id must be retyped seconds after creating it. Replacement: per-row "Test" action on the skills list, task pre-defaulted.
- **Parity flag**: skill upsert is direct `POST /v1/skills` (api.upsertSkill). Design against `control.skill.upsert` (governed, HITL-holdable) so chat can say "create a skill called triage.summarise that can read and comment on tickets".

## Studio > Router authoring (StudioPanel.tsx)

- **R1. NounForm is entirely naked** - :350-382: `id`, `description` bare inputs, `schema (JSON)` textarea; old `label.field` style, no hints, no examples, no format validation. Replacement: guided noun creator: id pattern validation + a schema property builder (name/type/description rows, the inverse of SchemaForm) with JSON escape hatch.
- **R2. VerbForm: `noun_id` is free text** - :437-440 even though the noun registry is one fetch away (`api.capabilities()` is already used two components down). Replacement: noun Select from the registry.
- **R3. VerbForm: input/output schemas as raw JSON** - :454-469. Replacement: same schema property builder as R1.
- **R4. Consequence is a bare low/high `<select>` with zero teaching** - :441-452, while the CONSEQUENCE glossary (ux.tsx:374-377) exists unused here. Replacement: Segmented with the glossary hints + an amber InfoCallout when "high" is chosen ("this verb will pause for human approval").
- **R5. BindingForm agent target is free text** - :555. The adapter branch gets a Select; the agent branch gets a naked input. Replacement: agent picker over capability profiles (backend dep: a list read for `control.capability` profiles; flag it).
- **Parity flag**: upsertNoun/upsertVerb/setBinding are direct routes; design against `control.noun.upsert` / `control.verb.upsert` / `control.binding.set`.

## Studio > Adapter Studio (StudioPanel.tsx)

- **A1. OpenAPI spec = one raw JSON textarea** - :699-706 plus a naked `adapter_id` input at :692-698. No URL import, no file upload, no pre-flight parse, no preview of what verbs will be generated. Replacement: import from URL / file / paste with a parsed preview (endpoints -> proposed verbs + consequence guesses) before Generate.
- **A2. Activate adapter requires retyping the id and hand-typing the reviewer** - :741-757. The activation reviewer of record (SEC-22) is a free-text self-attestation, and the inventory listing the inert adapters sits right next to it. Replacement: per-row "Activate" on the inventory, reviewer defaulted to the caller identity, arm-confirm listing the exact verbs about to go live.
- **A3. Activation is single-click** - :758-762. This is the moment inert generated code becomes live governed capability and there is no confirmation at all. Replacement: two-step arm-confirm (consequence tone).
- **A4. MCP token in a visible plain input** - :785-791. A secret typed into an unmasked text field with no masking, no paste-and-forget handling, no URL validation on `url`. Replacement: masked secret input + URL validation + "Test connection" before Register.

## Studio > Workflow form view (StudioPanel.tsx)

- **W1. The core authoring surface is `definition / steps (JSON)`** - :1084-1091, a raw textarea, and the FORM is the default view (:1354 `useState<WorkflowView>("form")`) with the canvas demoted to a toggle. Replacement: the guided builder (canvas / step list) is the default and primary editor; JSON is the escape hatch. (The deck design's one-slide-per-step model supersedes both.)
- **W2. Verb palette is a copy-to-clipboard workflow** - :1301-1344: click a verb to copy its id, then hand-paste it into the JSON at the right spot; clipboard fails silently in insecure contexts (:1037-1044). Replacement: click inserts a step (append/insert semantics), never clipboard.
- **W3. `source` enum exposed raw (resolved)** - Workflow provenance is now read-only in both authoring surfaces. New authored definitions become `precreated` server-side, edits preserve existing provenance, and only internal synthesis/learning paths can mint `generated` or `learned`.
- **W4. intent_tags comma list** - :1092-1094. Replacement: tag token input with suggestions from existing workflows' tags.
- **W5. Trigger/Execute `Inputs (JSON)`** - :1151-1157 and :1188-1194: raw JSON even though a workflow definition could declare an input schema. Replacement: SchemaForm over the workflow's declared inputs; keyed fields fallback (backend dep: workflow input schema surfaced on the summary).
- **W6. Cron field has presets but no validation or preview** - :1115-1117. A bad 5-field expression is only caught server-side. Replacement: cron validity check + "next 3 runs: ..." preview in the chosen timezone.
- **W7. Five stacked sibling forms on one page** - :1053-1267 (Upsert / Schedule / Trigger / Execute / View runs), four of which repeat the same workflow picker; Trigger vs Execute is never explained (durable engine vs in-process interpreter). Replacement: one workflow detail context with actions (the deck's per-workflow column), Trigger/Execute unified with a plain-language mode note.

## Studio > Workflow canvas (WorkflowCanvas.tsx)

- **C1. Metadata fields duplicated naked** - :684-707 (`id`, `version`, `source` in old `label.field` style) and intent_tags CSV again at :709-712. Same fixes as W3/W4.
- **C2. "existing run id" bare paste box to view a run** - :743-752, when `api.workflowRuns(id)` can list them. Replacement: run picker (dropdown of recent runs with status badges) for the current workflow.
- **C3. Clear and Load-from-JSON destroy the canvas with no confirm and no undo** - :724 (Clear), :579-597 (Load replaces all nodes/edges). Replacement: arm-confirm on replace/clear, or an undo toast.
- **C4. Inspector params fall back to raw `params (JSON)`** - :949-957 when the verb has no schema, and even with a schema, object/array args hit X1. Replacement: X1 fix + always-guided param rows.
- **C5. Apply / Rename id as separate explicit buttons** - :959-968 with subtle dirty-commit-on-navigate logic (:475-501). Replacement: auto-commit on blur with inline validation; rename inline on the id field with the duplicate check.
- **C6. Delete step with no undo** - :545-551, 966. Replacement: undo toast (low blast, but the canvas has no history at all).

## Dev console (DevConsolePanel.tsx)

Broadly the good exemplar (verb picker, SchemaForm, consequence callout, empty state). Residual debt:

- **D1. Spawn skills comma CSV** - :441-445 with append-only chips (:446-462), same shape as S3. Replacement: skills multiselect with removable chips.
- **D2. `Prefer (JSON)` raw** - :466-477. The value space is small and known (runtime, model). Replacement: structured routing prefs: runtime Select + model endpoint Select; JSON under a deeper Advanced.
- **D3. High-consequence verbs run on a single click** - :409-417: the amber callout at :331-336 teaches the stakes, but "Run verb" does not arm-confirm even for consequence=high. Replacement: arm-confirm on Run when the selected verb is high (mirrors the kernel's own pause, sets expectation of the 202 pending_human path).
- **D4. `Extra context (JSON)`** - :396-407. Acceptable as Advanced, but the one known key (`idempotency_key`) deserves its own field. Replacement: idempotency key input + JSON leftover.

## Admin (AdminPanel.tsx) - the flagship offender

- **AD1. Every org config section is one raw "Settings (JSON)" textarea editing live production config** - :224-231, saved with no validation beyond `JSON.parse` (:104-109) and copy that admits "Saving changes it immediately" (:232-235). Privacy policy, network egress, HITL thresholds, model routing - all hand-typed JSON. Replacement: per-section structured forms driven by policy schemas (the sections are already enumerated with blurbs at :20-29), diff-before-save, JSON escape hatch per section.
- **AD2. Save is unconfirmed; Rollback is a native `window.confirm`** - :129-135. Replacement: arm-confirm carrying a rendered diff of what will change.
- **AD3. Revision history has no diff view** - :309-323 shows `#id version actor` only, so rollback is blind. Replacement: click a revision to see its diff against live before rolling back.
- **AD4. Manifest export dumps raw JSON inline** - :263. Replacement: Download file + copy actions with a summary line (n sections, m bytes).
- **Parity flag**: config get/put/rollback/export are direct `/v1/config*` routes. Design against `control.config.put` (high consequence, HITL-holdable) so "raise the HITL threshold for refunds" works from chat with the 202 pending_human path.

## Settings (SettingsPanel.tsx)

- **SE1. Locale and timezone as free text** - :226-241 (placeholders only). A typo'd timezone silently corrupts scheduling and display; a TZ option list already exists in StudioPanel.tsx:850-860. Replacement: shared locale/timezone Selects (move TZ_OPTIONS into ux.tsx).
- **SE2. Notification `target` is one free-text field for six channel kinds** - :453-459 ("address / channel / url"). No per-channel validation, no test-send; a broken pager target fails silently at the worst moment. Replacement: channel-conditional input (email validator / URL validator / #channel picker) + "Send test" action.
- **SE3. `enabled` as a yes/no dropdown** - :461-469. Replacement: Segmented or switch.
- **SE4. Notification routings cannot be deleted** - :507-537 offers only Enable/Disable. Replacement: remove action (arm-confirm).
- **SE5. PAT mint scope as comma CSV** - :676-682, when the entire point (SEC-34) is "a subset of YOUR grants". Replacement: checklist of the caller's own grants (pre-scoped, select-all/none), never free text.
- **SE6. `ttl_days` as a free-text numeric string** - :683-690 (and invite ttl at :1334-1336) validated only by `Number.isNaN`. Replacement: preset Select (7 / 30 / 90 / no expiry) + computed "expires on <date>" preview.
- **SE7. Token/session/conversation/invite revocation via `window.confirm`** - :552, :976, :892, :1250. Replacement: X3 arm-confirm.
- **SE8. Personal agent editor duplicated and naked** - :841-852 (runtime free text, skills CSV) duplicates MePanel:76-87, directly contradicting the panel's own single-editor rationale for notifications (MePanel:152-156). Replacement: one editor (Settings), runtime Select over known runtimes, skills multiselect; Me links to it.
- **SE9. Per-user authz scope edited as raw JSON** - :1186-1199: an org-admin hand-writes `{departments:[...], nouns:[...], verbs:[...]}` per user with no vocabulary help. Replacement: structured scope builder: departments multiselect + noun/verb pattern chips from the registry, with a "what this user will see" preview.
- **SE10. Role change fires instantly on select-change** - :1155-1169: choosing a role in the dropdown PATCHes immediately; a mis-click grants org-admin with no confirmation. Replacement: pending-change + arm-confirm styled as consequence (this is a privilege escalation control).
- **SE11. Deactivate user is one unconfirmed click** - :1175-1183, and the page itself says "revokes their access immediately" (:1280-1281). Replacement: arm-confirm.
- **SE12. Privacy export prints the entire export JSON inline** - :935 before offering download. Replacement: summary counts (n conversations, n work items) + Download; never dump the blob.
- **Parity flag**: patchUser / invitations / mint-token are direct admin/me routes; design against `control.user.update`, `control.invitation.create` (high consequence) for chat parity.

## Me (MePanel.tsx)

- **ME1. Runtime free text** - :76-81 ("Leave as pi-worker unless told otherwise" is a Select begging to exist). Replacement: runtime Select (backend dep: a runtimes list read; flag it).
- **ME2. Skills comma CSV with append-only chips** - :83-104. Replacement: multiselect (same control as D1/S3).
- **ME3. Memory "Type" free text with a vocabulary that contradicts MemoryPanel** - :198-200 suggests "fact, preference, note" while MemoryPanel's real kind enum is entity/relationship/summary/document_chunk (MemoryPanel.tsx:45-50). Two divergent memory query surfaces. Replacement: reuse KIND_FILTER_OPTIONS, or delete MemoryQuery and link to the Memory panel (consolidation).
- **ME4. Agent answers rendered as a raw SpawnResult CodeBlock** - :139-146. Replacement: render the answer text first, raw result collapsed under details.

## Memory (MemoryPanel.tsx) - near-canon, residual items

- **MM1. Forget via `window.confirm`** - :279, despite a proper danger button. Replacement: arm-confirm on the fact card.
- **MM2. "Max results" free numeric input** - Recall :220-226. Replacement: preset Select (10/20/50) or stepper.
- **MM3. Ingest has no file/document path** - :580-586: "Document" source kind still means hand-pasting lines into a textarea. Replacement: file picker / URL fetch for document sources (backend dep if no upload route), textarea kept for pasted passages.
- **MM4. Ingestions table raw snake_case headers** - :627-637 (X4).
- **MM5. Remember kind Select never persists its default** - :448 `value={kind || "entity"}` renders "entity" but state stays "" and the API is sent `undefined`. What the user sees is not what is sent. Replacement: initialise state to "entity".

## Insight (InsightPanel.tsx) - good; residual

- **IN1. Audit export prints raw JSON inline** - :334. Replacement: file download + row-count summary.
- **IN2. No date-range filter on audit search** - :264-274 (actor/verb/run only), the first thing a real investigator reaches for. Replacement: from/to date pickers (flag if the route lacks the params).

## Chat (ChatPanel.tsx)

- **CH1. No Stop control while streaming** - :361-367: Send just disables; the abort machinery exists (`abortRef`, :156-157) but is only triggered by switching conversations. Replacement: Send morphs into Stop during a stream.
- **CH2. No conversation rename/delete/archive in the rail** - :250-269; deletion exists but only buried in Settings > Privacy (SettingsPanel:891-905). Replacement: per-conversation overflow menu (rename, delete with arm-confirm).
- **CH3. Conversation status badge unglossed** - :259-261 renders the raw status token with itself as the tooltip. Replacement: a glossary entry (ux.tsx pattern) for conversation states.
- **CH4. Example prompts hardcoded** - :22-26, not derived from the caller's actual scoped verbs, so they can suggest things the identity cannot do. Replacement: derive suggestions from /v1/capabilities.

## Approvals (ApprovalsPanel.tsx) - the exemplar; residual

- **AP1. "Full details" context is a raw JSON pre** - :127-134. The one place a non-technical approver MUST understand exactly what will run. Replacement: structured stakes rendering: verb, consequence badge, params as a labelled table, raw JSON collapsed beneath.
- **AP2. No ordering or filtering of the queue** - :257-261 renders arrival order; blocking requests should outrank async, and type filters matter at volume. Replacement: sort blocking-first + type/urgency filter chips.

## Kanban / Home / Router / RunView / canvases - largely clean

- **KB1. Kanban cards are dead ends** - KanbanPanel.tsx:25-72: no reassign, no cancel, no priority; acceptable for a read surface but flag for the deck (needs `control.work_item.*` verbs for any write; backend dep).
- **RV1. Run drawer cost shown as raw micros** - RunView.tsx:39-41, 153-155 (`cost: 12345µ`) while Insight already has `money()` (InsightPanel.tsx:26-30). Replacement: shared money formatter.
- **CP1. Command palette breaks its promise** - CommandPalette.tsx:89-94: "Run verb" items just `navigate("/dev")` without preselecting the verb; the user lands on an empty picker. Replacement: deep-link `/dev?verb=<id>` and preselect.

## App shell / dev identity (App.tsx) - dev-only, lower weight

- **AS1. Grants as free-text patterns** - :318-329 (presets help, :254-258) and departments CSV at :306-316. Dev sign-in only, but it is the very grants surface the product teaches everywhere else. Replacement: grant pattern builder (noun picker + verb/wildcard) reused from S3's picker.

## Chat-parity backend dependency ledger (design against these verbs)

Console operations that today hit direct routes and therefore have no chat/orchestrator equivalent. Each retrofit flow above must name its verb path; these are the missing verbs (control_plane.py naming, high-consequence writes take the 202 pending_human path):

`control.skill.upsert`, `control.noun.upsert`, `control.verb.upsert`, `control.binding.set`, `control.adapter.generate`, `control.adapter.activate`, `control.mcp_server.register`, `control.workflow.upsert` (exists - reader-agents.md:39 - prefer it over the direct route), `control.workflow.schedule`, `control.config.put`, `control.config.rollback`, `control.user.update`, `control.user.deactivate`, `control.invitation.create`, `control.notification.route`, plus list reads for runtimes and capability profiles (R5/ME1).

# Top 10 worst offenders (weighted by real-operator hit frequency)

1. **Admin config = raw live-JSON textarea per section** (AdminPanel.tsx:224-231, AD1-AD3). Every org policy change funnels through it, it edits production immediately, and the safety net (revisions) has no diff. Highest blast, regular admin traffic.
2. **Workflow authoring defaults to a JSON textarea with a copy-paste verb palette** (StudioPanel.tsx:1084-1091, :1301-1344; W1/W2). The product's core creative loop is hand-writing the steps contract.
3. **The permission surface is comma-CSV free text everywhere** (StudioPanel.tsx:181, SettingsPanel.tsx:676, MePanel.tsx:83, DevConsolePanel.tsx:441; S3/SE5/ME2/D1). Grants are Boltrig's central concept and every operator types them raw, daily.
4. **User directory: instant role escalation + raw JSON scope editor + unconfirmed deactivate** (SettingsPanel.tsx:1155-1199; SE9-SE11). Admin authz actions with zero friction and hand-written scope objects.
5. **Chat lacks Stop and conversation management** (ChatPanel.tsx:361, :250; CH1/CH2). Chat is the highest-frequency surface in the product; a runaway stream cannot be cancelled.
6. **Adapter Studio: raw OpenAPI paste, retype-to-activate, plaintext secret token** (StudioPanel.tsx:699, :741, :785; A1-A4). The onboarding path for every external capability.
7. **`window.confirm` for every destructive action** (7 sites, X3). Tokens, sessions, rollbacks, forgets, invites - all off-canon, all bypassing the arm-confirm teaching pattern operators learn in Approvals.
8. **Notification target: one unvalidated free-text field for six channel types, no test-send, no delete** (SettingsPanel.tsx:453-459, :507; SE2/SE4). Silently broken alerting on the safety-critical approval channel.
9. **Router authoring noun/verb forms: free-text noun_id, raw JSON schemas, untaught consequence select** (StudioPanel.tsx:350-479; R1-R4). The surface that DEFINES the governed verb space is the least governed form in the app.
10. **Chat-parity gaps: config, users, skills, nouns/verbs, adapters all write via direct routes** (parity ledger above). Until the `control.*` verbs exist, the Principal's "the chat can do everything the console can" bar is structurally unmeetable; every retrofit above must be specced against the verb, with the direct route flagged as transitional.
