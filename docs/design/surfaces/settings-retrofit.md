# Settings row + ops shared-form retrofit - build-ready surface spec

Scope: (1) the Settings row of the deck (8 sections re-cut per the pattern language), (2) the Admin manifest editor promoted from raw JSON to structured per-section editors, (3) retrofit briefs for the remaining ops columns, (4) the honest chat-parity registry for every settings/admin write. Designed against the frozen deck mechanics (DESIGN-v2.md), the binding pattern language (P-numbers cited throughout), the visual canon, and the code as it exists (file:line grounded). Backend gaps are flagged `DEPENDS-BACKEND` with the verb that should exist, named per `boltrig/config/control_plane.py` (`control.<noun>.<verb>`).

Conventions used below:
- "Slide frame" = the standard deck slide: own scroller (`overflow:auto; overscroll-behavior:contain`), hairline border, breadcrumb position chip in the header ("Settings / Notifications - 4 of 9"), edge chevrons first/last in tab order, per-slide Suspense + ErrorBoundary (DESIGN-v2 renderer + affordances 2/6).
- Every field is a `Field` v2 (N8) with label/hint/error/meta per P11; every default follows P12; validation timing per P13; errors per P15; state machine per P24. These are not restated per field; only the control choice, copy, and deviations are.
- All `control.*` verbs travel `POST /v1/invoke {noun:"control", verb, params}` returning ok/degraded/denied/error or `202 {status:"pending_human", hitl_request_id}` (app.py:259-283); every such form renders the full result union: ok inline, denied/error per P15/P24, `pending_human` as `PendingHumanCard` (N15, P30).
- No em or en dashes anywhere, in code, copy, or comments (brand law, P22).

---

## 0. One deck-grid amendment (required, low-blast)

DESIGN-v2's grid gives the settings row no columns. The current SettingsPanel is 8 `useState` sub-tabs (SettingsPanel.tsx:1417-1430, 1449-1460), and P19 forbids nested tab systems on deck surfaces ("the deck's columns ARE the tabs"). These two binding documents can only both be satisfied one way:

**The settings row gains columns, one per section, keyed by section id.** Routes: `#/settings` (anchor) and `#/settings/:section` where `:section` is one of `account | appearance | notifications | developer | agent | privacy | security | organisation`. This uses the router's existing second path segment (router.ts:8,30; reader-spec notes nothing consumes `route.param` on this row today, so it is a free slot) and the `segs` extension DESIGN-v2 already defines. `navigate("/settings")` call sites (MePanel.tsx:160) keep working: they land on the anchor. Column identity is id-keyed, never ordinal (DESIGN-v2 decisive call 4). The `organisation` column is cosmetically hidden for non-org-admin (same gate as today, SettingsPanel.tsx:1425-1429); a deep link to it while non-admin renders the faithful denial slide (P24 denied at slide scale), chevrons still live.

This amendment is recorded here as the fork back to DESIGN-v2 it is; it extends the grid in the direction the grid already defines (columns = a row's detail pages). Everything else in this spec fits the frozen mechanics unchanged.

The X5 debt (sub-tab switch silently discards form state, SettingsPanel.tsx:1449-1469) dissolves structurally: sections become slides, slide moves are lossless by construction (P17 draft layer + dirty pinning), and the `SaveBar` (N10) carries unsaved drafts.

---

## 1. The Settings row

### 1.1 Anchor slide: `#/settings` - the settings map

**Purpose.** Orientation + one-glance status. It is a directory, not a form (P20: the 80% path here is "get to the right section in one click").

**Layout.**
- Region A (top): `PageIntro` - title "Settings", lead "Your account, security, and how Boltrig looks and reaches you." (keep existing copy, SettingsPanel.tsx:1444-1447). No primary button on the anchor (P20: zero forms here).
- Region B: identity summary strip - a single `list-card` row: display name, email, role as `tag`, status badge, "from your IdP" gloss. Read from `GET /v1/me/settings` `.profile` (access_routes.py:75-82; client.ts:576).
- Region C: a responsive card grid, one card per section in column order. Each card: section title, one-line description (copy below), and a live fact line in the `meta` style (`--color-text-secondary`) computed from cheap reads:
  - Account and profile - "Name, locale and timezone." Fact: display name or "no display name set".
  - Appearance - "Theme, density, text size, motion and contrast." Fact: current theme.
  - Notifications - "What reaches you, and where." Fact: "n routing rules active" (`GET /v1/me/notifications`, access_routes.py:229-237).
  - Developer and connections - "Personal access tokens and how to connect clients." Fact: "n tokens - m expiring within 14 days" (`GET /v1/me/tokens`, access_routes.py:147-150).
  - Personal agent - "The assistant that runs as you." Fact: "configured (runtime pi-worker)" or "not configured" (`GET /v1/me/agent`, access_routes.py:253-259).
  - Privacy and my data - "Export your data; manage your conversations."
  - Security and sessions - "Active sessions, tokens, your own activity." Fact: "n active sessions".
  - Organisation (org-admin only) - "The user directory and invitations." Fact: "n users - m pending invitations".
- Cards are real buttons navigating right to their column (deck affordance 7: in-content click-through navigates right). Anchor header carries the count-and-peek cue "8 sections >" (7 for non-admin).

**States.** First load: `Skeleton variant="cards" count=8` (N13, P25). Fact-line fetches fail soft: the card renders without the fact (facts are decoration, not gates). No denied state on the anchor (the me-scoped reads are ungated).

### 1.2 `#/settings/account` - Account and profile

Replaces AccountProfile (SettingsPanel.tsx:108-253).

**Layout.** Two regions stacked (form density, P34):
- Region A "Identity" (read-only card): dl rows id (mono), email, role (`StatusBadge`-style tag with the ROLE_OPTIONS hint as TermTip, ux.tsx:432-439), status badge, source IdP group, scope (readable summary, keep `scopeReadable` SettingsPanel.tsx:83-88). Footer line (keep, it is good copy): "Role, scope and group are conferred by your identity provider and are read-only here. Change them via your IdP, or ask an org-admin."
- Region B "Preferences" - three fields, **autosave** per P16 (personal, low-blast, instantly reversible; display name is explicitly autosave-eligible):
  - **Display name** - text input. Hint: "How your name appears across Boltrig." Default: current value (P12).
  - **Timezone** - `EntityPicker` (N4, P6) over `Intl.supportedValuesOf("timeZone")`, grouped by region prefix ("Europe", "America", ...), default = the browser zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) when unset. Meta slot: current local time in the picked zone ("14:32 now").
  - **Locale** - `Select` (P3) over a curated list (en-GB, en-US, de-DE, fr-FR, es-ES, nl-NL, ...) plus "Custom..." revealing a mono input with example `en-GB`. Default: `navigator.language`.
- Each control persists on blur/selection, debounced 800ms, via `PUT /v1/me/settings {settings:{display_name|locale|timezone}}` (access_routes.py:84-98; client.ts:580), Saved wisp per N1's contract; failure reverts the control and renders the server reason (P15, `apiReason`).

**States.** P24 standard. Loading: `Skeleton variant="rows"`.
**Parity.** See registry (section 1.10): stays a direct account route; recommended future verb `account.settings.update` (low consequence).

### 1.3 `#/settings/appearance` - Appearance and accessibility

Replaces AppearanceA11y (SettingsPanel.tsx:257-376). All controls **instant-apply** (live preview already exists via `applyAppearance`, SettingsPanel.tsx:278-282) + debounced persist, per P16's autosave carve-out. The explicit "Save appearance" button is removed.

**Controls** (single section, P19 sections not wizard):
- **Theme** - `Segmented` (P3, 3 values): System / Dark / Light. Hint: "Dark is the native Boltrig look."
- **Density** - `Segmented`: Comfortable / Compact. Hint: "Compact tightens tables and lists."
- **Text size** - `Segmented` (4 values, short labels): Small / Normal / Large / Extra large.
- **Reduced motion** - `Switch` (N1, P2: instant-apply setting, both states safe). Hint: "Disables slide transitions and animation."
- **High contrast** - `Switch`. Hint: "Stronger borders and text contrast."
- Persist: `PUT /v1/me/settings` with `appearanceToSettings` keys (appearance.ts; SettingsPanel.tsx:289-291). On failure: revert control AND re-apply the previous appearance (the preview must never drift from the saved truth on error).

An `InfoCallout tone="info"` at the top: "Changes apply immediately and follow you across devices." (One callout, P21 rung 4.)

**States.** P24. Note: the deck's own motion consumes this setting (reader-shell section 2: `:root.reduce-motion` zeroes durations).
**Parity.** Stays direct (`account.settings.update` future verb, see 1.10).

### 1.4 `#/settings/notifications` - the routing matrix

Replaces NotificationsSection (SettingsPanel.tsx:380-542), which today is a one-rule-at-a-time form with an enabled dropdown (L1 failure: the user cannot see their routing posture at a glance).

**Data model ground truth.** Rows `{id, event_type, channel, target?, enabled}` per user (access_routes.py:229-237). `PUT /v1/me/notifications {id?, event_type, channel, target?, enabled?}` upserts; omitting `id` creates a new row (access_routes.py:239-250; client.ts:642). There is **no delete route**: "off" means `enabled:false`. Event types and channels come from the single-source options (ux.tsx:413-427); never re-declare them locally (SettingsPanel.tsx:47-62 duplicates them today - delete that, X-class debt).

**Layout.**
- Region A: `PageIntro` "Notifications", lead "Where each kind of event reaches you." How: "Flip a cell to route an event to a channel. Changes apply immediately."
- Region B: **the matrix** - a P35 table. Rows = 5 event types (friendly labels from `NOTIFY_EVENT_OPTIONS`); columns = 6 channels (`NOTIFY_CHANNEL_OPTIONS`) + a trailing bulk cell = 8 columns of which 6 are switch cells (row header + 6 + bulk; the row header column carries the event label with its TermTip gloss - "Approval needed: an action is paused waiting for a person", reusing the P22 canon). Each cell is a `Switch` (N1): instant-apply, per-cell busy (switch disabled + subtle pulse suppressed under reduce-motion), Saved wisp, revert + footer error on failure (P15).
  - Cell semantics: the client indexes prefs by `event_type:channel`. Toggle on an existing row: `PUT {id, event_type, channel, target: row.target, enabled: next}`. Toggle on with no row: `PUT {event_type, channel, target: channelTarget(channel) || undefined, enabled: true}`.
  - Duplicate rows for one pair (possible, since PUT-without-id always creates): the matrix drives the first; duplicates surface in Region D.
  - Trailing bulk cell per row: two ghost mini-buttons "All" / "None" (exactly two row actions, P35) that serially PUT that row's 6 cells with progress text "Updating 3 of 6...".
- Region C: **Channel targets** - a subordinate section (Tier 2, P18) with one `Field` per targetable channel (email, slack, teams, webhook, pager; in-app needs none):
  - Email - input validated as an address, default = the profile email, meta "used by n rules".
  - Slack / Teams - input, example `#approvals` / a channel or user id.
  - Webhook - input validated as an https URL.
  - Pager - input, example a routing key.
  - Editing a target arms a small inline confirm "Apply to n existing rules" (targets ride on each pref row, so the client re-PUTs every enabled row of that channel serially, progress text). Validation on blur (P13).
- Region D (Tier 3, P18): `Disclosure` "All routing rules (n)" - the raw rules table (event, channel, target, on/off `Switch`, created order), the honest home for per-event target overrides and duplicate cleanup ("Duplicate rule - the matrix uses the first; disable this one."). Changed-count summary on the collapsed state.
- Region E (footer): ghost button **"Use recommended defaults"** - writes 7 rules (in-app on for all 5 event types; email on for approval and escalation), serial with progress, then reloads. This is the empty state's CTA too.

**Empty state** (no prefs at all): the matrix still renders, all off (an all-off matrix teaches the whole value space better than a blank panel), plus an `EmptyState` strip above it: title "Nothing reaches you yet", body "Approvals and escalations will only appear in the app. Route them somewhere you will see them.", action = "Use recommended defaults" (P24, P20).

**States.** P24; poll-free (no live data); denied cannot occur (me-scoped).
**Parity.** Stays direct today. Chat phrasing to design against: "Send budget alerts to my email" -> future `account.notification.route {event_type:"budget_alert", channel:"email", enabled:true}` (low consequence) - `DEPENDS-BACKEND`, see 1.10. `ByChat` (N16, P32) sits in the footer once the verb exists; until then omit it (never advertise a phrasing the orchestrator cannot fulfil - honesty over symmetry).

### 1.5 `#/settings/developer` - Developer and connections

Replaces DeveloperConnections + TokenList (SettingsPanel.tsx:546-763). Three regions: mint flow, token table, connection details.

**Region A: Mint a personal access token - a 3-step wizard** (P19: this is genuinely two-phase - scope choice depends on knowing the token's purpose, and the finish yields a one-time secret; it earns wizard status alongside invite-user). Step indicator "1 Name - 2 Scope - 3 Review"; Back never loses state.

- **Step 1 - Name and lifetime.**
  - Name - mono input, required, the surface's ONE blank-required field and first focus (P12 case 4). Hint: "What this token is for, so you recognise it later." Example: `laptop-claude-code`. Uniqueness is advisory only (server does not enforce): meta shows "you already have a token with this name" as a warn, not an error.
  - Lifetime - `Stepper` (N6, P8): min 1, max 365, step 1, unit "days", default **90** (mirror `DEFAULT_TTL_DAYS`, tokens.py:26; max mirrors `MAX_TTL_DAYS=365`, tokens.py:25,43-46). Hint: "Clamped to 365 days at most." Meta: computed expiry date ("expires 30 Sep 2026").
- **Step 2 - Scope.** `ScopeBuilder` (N5, P7), the PAT variant: the tree is the caller's OWN grants (source: caller-scoped `GET /v1/capabilities`, client.ts:173, which is already grant-filtered), presets row: **"All my grants"** (default: chips empty + a note "empty scope = everything you can do today", matching mint_pat's fallback to the user's allow set, tokens.py:66) and **"Read-only"** (patterns `*.get`, `*.list`, `*.query` intersected with grants). Live match preview per P7. Critical honesty rule: the server silently DROPS requested patterns the caller's grants do not permit (tokens.py:67-68 `effective_scope` filter) - the preview must therefore render a warn line "2 patterns will be dropped - your grants do not cover them" listing them, so the minted token never surprises. Teaching hint (one-time, P21 rung 3): "The token can never exceed you - it is re-checked against your live grants on every use (SEC-34)."
- **Step 3 - Review and mint.** Restates name, lifetime + expiry date, scope chips + "matches n verbs today". `InfoCallout tone="info"`: "The secret is shown once, immediately after minting. Have somewhere safe ready." Primary button "Mint token" (the only `btn--primary` on the slide, P20). Busy: "Minting...".
  - Call: `POST /v1/me/tokens {name, scope?, ttl_days}` (access_routes.py:152-172; client.ts:608). 400 with reason renders at the footer (P15); the name error highlights step 1's field.

**The show-once secret moment** - `SecretOnce` (N18, registered in section 3). On `{status:"ok", secret, ...}` the wizard is replaced in place by the SecretOnce card:
- Warn-tone elevated card (`--color-warn` accent - NOT amber; no kernel governance is in play, L4).
- Headline: "Copy your token now." Body: "This is the only time the secret is shown. It is never stored in the clear and cannot be retrieved again." (existing copy, SettingsPanel.tsx:705-709, kept).
- The secret in a mono block; clicking it selects all; primary "Copy" flips to "Copied" for 2s.
- Meta line: "token `laptop-claude-code` (id) - expires 30 Sep 2026" + the scope `GrantList`.
- "Done" ghost button: if Copy was clicked, dismisses immediately; if never clicked, it arms in place (P27 semantics): "Dismiss without copying? The secret cannot be shown again." / "Dismiss anyway" + Cancel.
- While mounted: `beforeunload` guard; slide navigation is permitted (P17: never block; the slide is dirty-pinned keep-alive so the secret survives a deck move) and the sidebar map shows the dirty dot. `aria-live="polite"` announce: "Token minted. Copy it now."
- On dismiss: token table refreshes, wizard resets to step 1.

**Region B: token table** (shared component with 1.8, rendered once per slide). P35 table: Name (mono), Scope ("n grants" expanding to `GrantList`), Created (relative, absolute on title), Last used ("never" muted), Expires (warn text when <14 days), Status (revoked badge), row action **Revoke** = `ArmConfirm` in the row (N14, P27, tone danger; kills X3's `window.confirm` at SettingsPanel.tsx:552): restate "Revoke `laptop-claude-code`? Any client using it stops working immediately." / "Confirm revoke" -> `DELETE /v1/me/tokens/{id}` (access_routes.py:174-182; client.ts:616). Empty: "No tokens yet. Mint one above to connect Claude Code, curl, or any MCP client." (CTA scrolls to Region A.)

**Region C: connection details** - keep the CopyRow card verbatim (MCP endpoint, REST base, auth header, claude-mcp-add + curl snippets) from `GET /v1/me/connections` (access_routes.py:184-205; client.ts:623). This is already considered UI.

**States.** P24; skeleton rows on first token-list load.
**Parity.** PAT mint is deliberately **not** given a chat path: a secret streamed into a conversation transcript persists in conversation storage and audit detail, violating the show-once containment the whole flow exists for (PAT-02 spirit, access_routes.py:50-51,171). Headless parity already exists as the REST route itself (US-HEAD-01, access_routes.py docstring:6-8). This is a recorded, reasoned exception to L2, not an oversight. Revoke IS chat-eligible: future `account.token.revoke {id}` - see 1.10.

### 1.6 `#/settings/agent` - Personal agent

Replaces PersonalAgentSection (SettingsPanel.tsx:767-868) AND becomes the single configure surface; MePanel keeps only invoke ("Ask your agent") and links here ("Configure in Settings"), removing the duplicated editor (MePanel.tsx:16-112; consolidation principle - two divergent editors of one object is the exact smell the pointer card at MePanel.tsx:154-166 already avoids for notifications).

**Layout.**
- Region A "Current agent" card: seeded from `GET /v1/me/agent` (access_routes.py:253-259; client.ts:650) - fixing the reader-agents finding that the current form starts blank each time. Rows: runtime (mono), skills (`GrantList`), enabled badge. Below: the SEC-30 teaching callout (P21 rung 4, keep the substance of SettingsPanel.tsx:831-835): "Your agent runs on your behalf and its grants are capped to your own, so it can never act beyond you. Ask it from the Me page."
- Region B "Configure" form, explicit Save (P16: this shapes what an agent may do; not autosave):
  - **Runtime** - `Segmented` (P3): "pi-worker (recommended)" / "Custom...". Custom reveals a mono input. Default `pi-worker` (mirrors the route default, platform_routes.py:527). Hint: "The worker that runs your agent. Leave as pi-worker unless told otherwise." There is no runtimes list read anywhere (reader-agents gap: no capability/runtime list route) - `DEPENDS-BACKEND (read)`: a runtimes read would upgrade this to an `EntityPicker`; flagged, not blocking.
  - **Skills** - `ChipPicker` (N3, P5): candidates from `GET /v1/skills` (client.ts:241), removable chips, search, mono values. This is the MePanel add-chips interaction (MePanel.tsx:16-104) promoted to the primitive, now with remove and search. Empty-set inline note: "No skills selected. Your agent will have nothing it can do." Kills the comma-CSV input (X2; SettingsPanel.tsx:851, MePanel.tsx:86).
  - **Enabled** - rendered as a read-only badge with hint "Disabling is not yet supported." The GET returns `enabled` but the configure route does not accept it (platform_routes.py:526-528 hardcodes the model defaults and mints a new id every save) - never render a control the server ignores (honesty over symmetry). `DEPENDS-BACKEND`: enable/disable lands with the verb below.
- `SaveBar` (N10) when dirty: "Unsaved changes to your personal agent" + "Save agent" + Discard (arm-confirm).
- Footer: `ByChat` (P32): builds phrasing from form state, e.g. "Give my personal agent the research skill and keep pi-worker as the runtime" -> prefills the chat composer via `setComposerPrefill`, never auto-sends.

**API.** Today: `POST /v1/me/agent {runtime, skills[]}` (platform_routes.py:524-529; client.ts:487) - direct, ungoverned, not audited on configure (reader-agents parity table). **Design target: `control.personal_agent.configure {runtime, skills, enabled}`** - `DEPENDS-BACKEND`, consequence LOW (self-scoped, delegation-capped blast radius; P5's worked example already fixes this at low, a recorded deviation from the all-high `control.*` convention of control_plane.py:49-50, justified because the object can never exceed its owner, SEC-30). The form submits through the direct route until the verb lands, behind the same Save handler (P31 rule 2), and already renders the P30 result union so the transport flip is call-site only.

**States.** P24. `pending_human` cannot occur on the direct route; the form is nonetheless built to render it (N15) for the verb future.

### 1.7 `#/settings/privacy` - Privacy and my data

Replaces PrivacyData (SettingsPanel.tsx:872-967).

- Region A "Export my data": lead copy kept ("A copy of your own conversations, owned work items and settings. Your data only - nothing from other users.", SET-60). One primary action "Prepare export" -> `GET /v1/me/export` (access_routes.py:112-129; client.ts:592); on success the button row becomes: summary line "n conversations - m work items - k settings keys", **"Download JSON"** (file download, the AD4 idiom - no inline raw dump), and a `Disclosure` "Preview" containing the `CodeBlock` (Tier 3, P18).
- Region B "My conversations": listed from the export payload (that is where the list lives today; an independent list read is a nice-to-have, not required). Rows: title ("(untitled)" muted), id (mono, middle-truncated per P34), status badge. Row action **Delete** = `ArmConfirm` (P27; kills X3 at SettingsPanel.tsx:892): restate "Delete 'triage escalation'? This closes it for your account; retention rules govern the underlying records." (honest to the implementation: delete = status CLOSED, retention-aware, access_routes.py:139-142) / "Confirm delete" -> `DELETE /v1/me/conversations/{id}` (access_routes.py:131-144; client.ts:596). Busy "Deleting...". Refreshes the export data on success.
- Empty (export loaded, zero conversations): "No conversations. Start one in Chat." CTA -> `/chat`.

**States.** P24; the export call is user-initiated so there is no first-load skeleton, only button busy text.
**Parity.** Delete conversation: chat can already do this in spirit ("Delete my triage conversation" - the orchestrator uses the same soft-close route, per P27's worked example). Export stays console/REST (a file artifact; chat would just restate the REST call).

### 1.8 `#/settings/security` - Security and sessions

Replaces SecuritySessions (SettingsPanel.tsx:971-1097).

- Region A: the IdP notice kept verbatim as an `InfoCallout tone="info"` (SettingsPanel.tsx:1084-1089): "Boltrig stores no passwords and runs no MFA of its own - sign-in, MFA and password resets are managed entirely by your identity provider. Tokens and sessions below are your standing credentials here; revoke any you do not recognise."
- Region B: **Active sessions** P35 table: Client (mono), Created, Last seen (relative + absolute title), Status; row action Revoke = `ArmConfirm` (kills X3 at SettingsPanel.tsx:976): "Revoke this session? That device is signed out immediately." -> `DELETE /v1/me/sessions/{id}` (access_routes.py:218-226; client.ts:631). The caller's CURRENT session, when identifiable, is badged "this device" and its revoke restatement says "You will be signed out here."
- Region C: **Personal access tokens** - the same token-table component as 1.5 Region B (one component, two mounts; a "Mint" link routes to `#/settings/developer`).
- Region D: **My activity** - P35 table over `GET /v1/me/activity` (access_routes.py:100-110; client.ts:588), fixing X4's raw snake_case headers (SettingsPanel.tsx:1050-1057): columns **When** (relative, absolute title) / **Action** (verb, mono) / **Result** (`StatusBadge` with the AUDIT_STATUS glossary, ux.tsx:355-361) / **Run** (`RunLink` when run_id present, shared.tsx:73-83 - opens the global drawer without moving the deck; muted "-" otherwise). `seq` is dropped from display (an internal cursor, not user information). Sticky thead inside the slide scroller (P35). "Load more" if the 200-row cap is hit.

**States.** P24; skeleton rows for each table's first load.
**Parity.** Session/token revoke: future `account.session.revoke` / `account.token.revoke` (low), see 1.10; reads are reads (L2 needs no affordance).

### 1.9 `#/settings/organisation` - Organisation (org-admin)

Replaces OrganisationSection + UserRow (SettingsPanel.tsx:1101-1397). Cosmetic gate: column hidden unless org-admin (identity role); server denial rendered faithfully regardless (L3: `GET /v1/admin/users` returns `{status:"denied", reason}` on 403, access_routes.py:262-267, and the panel already reads that shape, SettingsPanel.tsx:1263-1273 - keep exactly that, rendered as the P24 denied callout at slide scale, chevrons live).

**Region A: the intro.** `PageIntro` "Organisation", lead "Who is in the organisation and what they may do." How: "Deeper configuration (privacy, network, models, approvals) lives in Admin, under Ops." (cross-link navigates to the ops row admin column).

**Region B: user directory** - P35 table (data-heavy surface, honours compact density): columns **User** (email mono + display name secondary), **Role**, **Scope** (readable summary; "Edit" ghost), **Status** (badge), **Last seen** (relative), **Actions**. Filter input focused by "/" (P36). Source `GET /v1/admin/users` (access_routes.py:262-269; client.ts:654).

- **Role change flow** (considered, not instant): the Role cell renders the current role as a `Select` over `ROLE_OPTIONS` (6 values with hints, ux.tsx:432-439; P3: >4 values). Changing the selection does NOT write; the row enters a pending state: a chip "agent -> manager" plus inline "Apply" (weighted) + "Cancel". The Apply confirm carries the target role's hint line as its restatement ("manager: Manages a team."); when the target is org-admin it additionally carries an `InfoCallout tone="warn"` (not amber - no kernel governance is in play, L4): "org-admin has full access to everything, including this directory." Apply -> `PATCH /v1/admin/users/{id} {role}` (access_routes.py:271-289; client.ts:660); the server reason renders in-row on failure (P15).
- **Deactivate** = `ArmConfirm`, tone danger: "Deactivate ada@acme.com? Their access stops immediately and their tokens stop resolving." (US-USR-03 access_routes.py:285; PAT fail-closed on deactivated owners, tokens.py:85-90) / "Confirm deactivate" -> `PATCH {status:"deactivated"}`. **Activate** is a plain button (restorative, low-blast).
- **Scope editor** (replaces the raw JSON textarea, SettingsPanel.tsx:1186-1199): "Edit scope" expands an inline editor beneath the row (in-flow, no modal):
  - **All access** - `Segmented` Yes/No mapping `{all:true}`; when Yes, the remaining fields collapse with the note "All access overrides everything below."
  - **Departments** - `ChipPicker` free-entry, candidates = the union of `hierarchy.tier2[].department` from `GET /v1/admin/config/hierarchy` (readable to this admin: `_can` = author roles, platform_routes.py:323-330,567-569) and distinct departments in existing users' scopes.
  - **Nouns** - `ChipPicker` over registry noun ids (`GET /v1/capabilities`).
  - **Verbs** - `ScopeBuilder` (P7) with match preview.
  - **Advanced: edit as JSON** - `JsonDisclosure` (N9, P10), two-way synced; unknown keys in the stored scope are preserved on save (the form serializes `{...unknownRest, ...knownFields}`) and the disclosure summary notes "2 keys not shown above are preserved."
  - Save scope -> `PATCH {scope}`; explicit Save (P16, shared state).

**Region C: invitations.**
- **Invite a user - a 3-step wizard** (P19 names this one of the two lawful wizards; corrected to ground truth: no secret is issued - the invitation only pre-stages a role for an SSO identity, SEC-35, access_routes.py:306-328):
  - Step 1 **Identity**: email input, required (the surface's one blank-required field, P12 case 4), validated as an address on blur.
  - Step 2 **Role and scope**: Role `Select` over ROLE_OPTIONS defaulting to `agent` (the server default, access_routes.py:318, and the least-privilege default); a live description line under the select (the ROLE hint, meta slot). Tier 3 `Disclosure` "Scope (optional)": the same departments ChipPicker as Region B, riding as `scope` in the create body (accepted: `body.get("scope", {})`, access_routes.py:319).
  - Step 3 **Lifetime and review**: TTL `Stepper` 1-90 days, default **14** (server default, access_routes.py:321), unit "days", meta = computed expiry date. Review restates email, role + its hint, scope, expiry. `InfoCallout tone="info"`: "Boltrig records the invitation - it sends no email and creates no password. Access begins when they sign in through your identity provider; share the sign-in link yourself." Primary "Create invitation" -> `POST /v1/admin/invitations {email, role, scope?, ttl_days}` (client.ts:673). Result card: the invitation row + a Copy button for the org sign-in URL.
- **Invitations list**: table: Email (mono), Role, Status (badge; pending/accepted/revoked/expired), Invited by, Expires (relative, warn <3 days). Row action Revoke (pending only) = `ArmConfirm` (kills X3 at SettingsPanel.tsx:1250): "Revoke the invitation for ada@acme.com? They will not be pre-staged when they sign in." -> `DELETE /v1/admin/invitations/{id}` (access_routes.py:330-342; client.ts:683). Empty: "No invitations. Invite someone above; they get access the first time they sign in through your IdP."

**States.** P24 with the slide-scale denied treatment described above; skeletons on first table loads; every write failure renders the server reason verbatim.
**Parity + ByChat.** All three writes here are governance-weight and SHOULD be verbs (the HITL gate holding a role escalation for a second admin's approval is precisely the product): `control.user.update {user_id, role?, scope?, status?}`, `control.invitation.create {email, role, scope?, ttl_days}`, `control.invitation.revoke {id}` - all `DEPENDS-BACKEND`, consequence high, params mirroring the PATCH/POST bodies. `ByChat` renders on Region B and C with phrasings like "Make ada@acme.com a manager" and "Invite bob@acme.com as an integrator for 14 days"; forms are built on the P30 result union so the 202 path renders `PendingHumanCard` the day the verbs land. Until then the direct routes are the transport behind the same forms (P31 rule 2) and ByChat is withheld (same honesty rule as 1.4).

### 1.10 Settings chat-parity registry (P31 table, honest column included)

| Write | Today (file:line) | Verb path | Consequence | Honest disposition |
|---|---|---|---|---|
| Profile prefs (name/locale/tz) | `PUT /v1/me/settings` (access_routes.py:84-98) | `account.settings.update` | low | STAYS DIRECT for the console; verb recommended so chat can do it. Never a `control.*` high verb: autosaving through HITL is forbidden (P16). |
| Appearance | same route | same verb | low | Same as above. |
| Notification routing | `PUT /v1/me/notifications` (access_routes.py:239-250) | `account.notification.route` | low | DEPENDS-BACKEND; matrix is verb-ready. |
| PAT mint | `POST /v1/me/tokens` (access_routes.py:152-172) | none, deliberately | - | RECORDED EXCEPTION to L2: secret-in-transcript defeats show-once (see 1.5). Headless parity = the REST route (US-HEAD-01). |
| PAT revoke | `DELETE /v1/me/tokens/{id}` (access_routes.py:174-182) | `account.token.revoke {id}` | low | DEPENDS-BACKEND. |
| Session revoke | `DELETE /v1/me/sessions/{id}` (access_routes.py:218-226) | `account.session.revoke {id}` | low | DEPENDS-BACKEND. |
| Conversation delete | `DELETE /v1/me/conversations/{id}` (access_routes.py:131-144) | orchestrator soft-close (exists in spirit) | low | Chat phrasing: "Delete my triage conversation." |
| Personal agent configure | `POST /v1/me/agent` (platform_routes.py:524-529) | `control.personal_agent.configure` | LOW (recorded deviation, see 1.6) | DEPENDS-BACKEND (P31 registry row exists). |
| Directory: role/scope/status | `PATCH /v1/admin/users/{id}` (access_routes.py:271-289) | `control.user.update` | high | DEPENDS-BACKEND. The flagship HITL candidate: role escalation held for approval. |
| Invitation create / revoke | `POST` / `DELETE /v1/admin/invitations` (access_routes.py:306-342) | `control.invitation.create` / `.revoke` | high | DEPENDS-BACKEND. |

Reads are the shared `GET /v1/*` surface for both clients (P31 rule 3); no affordance needed (P32 "not for reads").

---

## 2. Admin: manifest sections promoted to structured editors

Placement: the admin column of the ops row (DESIGN-v2 grid), one slide. The 8 sections stay inside one slide selected by the existing header `Select` (AdminPanel.tsx:186-199) - this is a keyed accessor over ONE resource (the manifest), not a nested tab system, so it does not offend P19; blowing 8 more columns into the already-10-column ops row was considered and rejected (grid legibility, DESIGN-v2 decisive call 1). Section switching with a dirty draft triggers the P17 arm-confirm ("Discard unsaved changes to Network?") - X5 fixed.

Gate honesty: config writes are gated to AUTHOR roles server-side (`_require_author`, platform_routes.py:333-345, rbac.py:138-140), broader than the org-admin the current cosmetic warning claims (AdminPanel.tsx:33,202-207). Keep the cosmetic gate as-is but correct the copy: "Config editing needs an authoring role; the server enforces this." A 403/denied renders faithfully (AdminPanel.tsx:66-68 pattern, kept; P24).

### 2.0 Slide shell

- Region A: `PageIntro` "Admin", lead "Edit your organisation's configuration." How: "Pick a section and change its settings. Every save is recorded as a revision you can roll back to. Secrets are never shown, only referenced." Actions: the section `Select` (8 options with the SECTION_INFO labels/blurbs, AdminPanel.tsx:20-31) + Reload.
- Region B (left, wide): the active section's structured editor (2.1) with its own `SaveBar`.
- Region C (right rail): revision history (2.2), then manifest export + credential references (2.3).

### 2.1 Per-section editors

Load: `GET /v1/admin/config/{section}` (platform_routes.py:323-330; client.ts:381); `value` may be null -> the editor renders kernel defaults per P12 (the manifest dataclass defaults ARE the kernel's own defaults, source 1). Save: `PUT /v1/admin/config/{section} {value}` (platform_routes.py:332-345; client.ts:388). The server validates nothing beyond non-null (admin.py:37-47), so client validation is the only validation, and every editor MUST round-trip unknown keys: form state = known fields + an opaque `rest`; serialization = `{...rest, ...knownFields}`; the JSON escape hatch shows everything; a collapsed `JsonDisclosure` summary notes "n keys not shown above are preserved" whenever `rest` is non-empty. Every editor ends with the P10 `JsonDisclosure` "Advanced: edit as JSON", two-way synced, invalid JSON blocking save and section-switch (P17's one lawful block).

Field lists, grounded in the typed dataclasses (manifest.py):

**privacy** (PrivacyConfig, manifest.py:172-179):
- Redact personal data (`pii_redaction`) - `Segmented` Yes/No (P2: governance-adjacent boolean in a saved form, never a cheerful switch), default No. Current hint: "Stored policy flag. Automatic model/adapter-boundary PII redaction is not wired yet."
- Data residency (`data_residency`) - input, optional, example `eu`. Current hint: "Stored residency label. It does not currently constrain processing or storage."
- Retention (`retention_days`) - a `Segmented` "Use default / Delete closed conversations after..." where the second option reveals a `Stepper` (P8) min 1, unit "days". It controls the fleet janitor's hard-erasure of CLOSED conversations only; open conversations, work, memory and audit have separate lifecycles.
- Fields to redact (`redact_fields`) - `ChipPicker` free-entry, mono chips, example `ssn`. Current hint: "Stored field names. They are not currently applied to model or adapter payloads."

**network** (NetworkConfig, manifest.py:161-169):
- Air-gapped (`air_gapped`) - `Segmented` Yes/No, default No; choosing Yes reveals an `InfoCallout tone="warn"`: "Air-gapped blocks all adapter egress. Adapters that call external systems will fail their health checks." (P21 rung 4: changes what happens next.)
- HTTPS proxy (`https_proxy`) - input, optional, validated as a URL on blur, example `http://proxy.internal:3128`.
- CA bundle (`ca_bundle`) - mono input, optional, example `/etc/ssl/org-ca.pem`.
- Allowed domains (`allowed_domains`) - the SSRF allowlist as a proper list editor: `ChipPicker` free-entry with per-chip validation (hostname shape; `*.example.com` wildcards accepted), mono chips, meta "n domains". Hint: "If any domains are listed, adapter calls may only reach these." Teaching callout above the pair (one per concept, P21): "Egress control: outbound adapter traffic is checked against these lists before any request leaves."
- Blocked domains (`blocked_domains`) - same control. Hint: "Never reachable, even if allowed above. Deny wins." (deny-dominant, the kernel norm.)

**hitl** (HitlConfig, manifest.py:150-158) - Tier 1 by law: everything here is consequence machinery (P18 "consequence/HITL-relevant fields are Tier 1"):
- Primary channel (`primary_channel`) - `Select` over `NOTIFY_CHANNEL_OPTIONS` (ux.tsx:420-427), default slack (the dataclass default). Current hint: "Stored preferred channel. It does not currently deliver approval requests."
- Also notify via (`notify_via`) - `ChipPicker` over the same channel set. It is stored policy and is not currently consumed by the HITL gate.
- Approval timeout (`approval_timeout_seconds`) - `Stepper` unit "seconds", min 60, step 300, default 3600; meta slot humanizes ("= 1 hour"). Hint: "How long an approval may be answered before it times out." This timeout is enforced.
- Escalation chain (`escalation_chain`) - **`OrderedPicker` (N17, new primitive, section 3)**: an ordered list of people; candidates from `GET /v1/admin/users` (email + role badge per row); numbered rows; reorder via up/down buttons and Alt+ArrowUp/Down (P36 addition); remove per row. Current hint: "Stored ordered escalation targets. Timed-out approvals do not traverse this chain yet."
- Always-blocking verbs (`blocking_verbs`) - `ScopeBuilder` (P7) over the caller-scoped verb tree, consequence-high rows carrying the amber marker (lawful: this IS kernel governance, L4). Hint: "These verbs always pause for a person, whatever their consequence class."

**models** (ModelsConfig, manifest.py:68-79, endpoint shape manifest.py:317-328):
- **Endpoints** - a card list editor: each endpoint renders as a card (id mono header; kind + data_class badges; model; base_url muted) with Edit expanding an inline form and Remove (ArmConfirm; removal from the LIST is a config edit, saved with the section - no delete route is involved). "Add endpoint" appends a blank card in edit mode. Fields per card:
  - id - mono input, required, unique within the list (P13 blur check against siblings).
  - kind - `Select`: anthropic (default, manifest.py:322) / openai-compatible / local / Custom... (reveals input).
  - model - mono input, required, example `claude-sonnet-4-5`.
  - base_url - URL input, optional. Hint: "Only for gateways and local endpoints."
  - fallback - `EntityPicker` (P6) over the OTHER endpoint ids in this list, optional.
  - data_class - `CardSelect` (N2, P4, the pattern's own worked example): "standard" vs "sensitive", the sensitive card carrying "Sensitive-tagged work is routed only to this endpoint."
- Default endpoint (`default`) - `EntityPicker` over the endpoint ids.
- Sensitive endpoint (`sensitive_endpoint`) - `EntityPicker` over the endpoint ids; warn meta if the chosen endpoint's data_class is standard ("this endpoint is not marked sensitive").
- Prices (`prices`) - a local key-value row editor (composed from existing vocabulary, not a new registered primitive: rows of [model mono input | micros-per-token number input | remove], plus "Add price"): meta per row computes "= $2.40 per 1M tokens". Hint: "Micros per token. A model absent here falls back to its cost tier's default." (manifest.py:75-79.)

**notifications / personal_agents / evaluation / memory** - the four schema-less `extra` sections (manifest.py:199-206, 470-471). Per P9's honesty rule for schema-less objects, each renders: the section blurb, an `InfoCallout tone="info"` "This section has no typed schema yet - it is edited as JSON and saved as-is.", and the `JsonDisclosure` rendered OPEN as the primary control (the lawful exception: it is honestly labelled and it is the only truthful control). `DEPENDS-BACKEND (schema)`: typed section models (or a `GET /v1/admin/config/{section}/schema`) upgrade each to a `SchemaForm` v2 face; when the notifications section is typed, its editor becomes the org-scope twin of the 1.4 matrix vocabulary.

### 2.2 Save with diff, revision history, rollback

- **Diff-before-save** (fixes AD2): the section Save button arms in place; the armed state shows a `DiffView` (N19, section 3) of draft vs last-loaded value (changed/added/removed keys, mono, old red-tinted, new green-tinted, unchanged elided) above the restatement "Apply to live configuration? This changes behaviour immediately and records a revision." + "Apply" (primary) + Cancel. Busy "Saving...". Success: "Saved revision #n." and the history rail refreshes (`putConfig` response carries `revision`, platform_routes.py:341).
- **Revision history** (right rail): rows `#id` (mono), version hash (muted), actor, relative time, "rollback" badge when `rolled_back` (platform_routes.py:346-355; client.ts:398). Row actions: "Diff" and "Rollback".
  - **Diff vs live** (fixes AD3): requires the revision's stored value, which the history route does NOT return (summaries only, platform_routes.py:352-355; the payload lives in ConfigRevision, admin.py:42-47). `DEPENDS-BACKEND (read)`: `GET /v1/admin/config/{section}/history/{revision_id}` returning `payload.value`. Until it lands, the Diff action is absent (not disabled-and-mysterious) and rollback restates only identity.
  - **Rollback** = `ArmConfirm` tone danger (kills X3 at AdminPanel.tsx:130-135): restate "Roll back Network to revision #12 (by ada, 3 days ago)? This changes live configuration now and records a new revision." - with the DiffView inside the armed state once the revision read exists. Confirm "Roll back" -> `POST /v1/admin/config/{section}/rollback {revision_id}` (platform_routes.py:356-368; client.ts:405); the response `value` reloads the editor.
- Dirty guard: switching section or leaving the slide with a dirty draft follows P17 (drafts survive slide moves via keep-alive pinning; section-switch inside the slide arm-confirms because the editor is keyed by section).

### 2.3 Export and credentials

- **Manifest export** (fixes AD4): one button "Export manifest" -> `POST /v1/admin/config/export` (platform_routes.py:370-375; client.ts:415); result renders a summary line ("8 sections - n adapters - n model endpoints - round-trip re-importable") + "Download boltrig-manifest.json" + Copy; the inline dump moves into a collapsed `Disclosure` "Preview".
- **Credential references**: a small P35 table (Adapter | Reference), refs only, never values (admin.py:75-83; AdminPanel.tsx:266-292 behaviour kept), each ref mono with the existing title gloss "Credential reference - the secret value is held server-side."

### 2.4 Admin parity

| Write | Today | Verb path | Status |
|---|---|---|---|
| Section save | `PUT /v1/admin/config/{section}` (platform_routes.py:332-345) | `control.config.upsert {section, value}` | DEPENDS-BACKEND, consequence high. THE flagship 202 surface: an org config change held for a second pair of eyes is the product thesis. Chat: "Block all egress except api.stripe.com" -> the orchestrator composes the network section value and invokes -> 202 -> inline hitl card (P33). |
| Rollback | `POST .../rollback` (platform_routes.py:356-368) | `control.config.rollback {section, revision_id}` | DEPENDS-BACKEND, high. |
| Hierarchy edit | `PUT /v1/admin/config/hierarchy` | `control.hierarchy.upsert` | Already registered in P31; the UI must keep the honesty note that it does NOT rebuild the running org (worker reads the manifest at boot, api/worker.py:37-46 per reader-agents) - an `InfoCallout tone="warn"` on that section: "Saving updates configuration; the running org re-reads it at the next worker restart." |

All editors are built on the P30 result union now (ok/denied/error today; `PendingHumanCard` ready), so the verb flip is transport-only (P31 rule 2). `ByChat` appears on each section editor once `control.config.upsert` exists, generating phrasing from the DIFF, not the whole section ("Set retention to 90 days and turn on PII redaction").

---

## 3. Register additions (the lawful fork back to the pattern document)

The pattern language says a needed-but-unregistered control is a fork back to the register, not a local invention. This spec adds three, each with demonstrated need:

| # | Name | Props (essence) | States | Built from | Need |
|---|---|---|---|---|---|
| N17 | `OrderedPicker` | `value:string[], onChange, options:[{id,label,badges}], addLabel` | empty / populated / reordering / disabled | `ChipPicker` candidates + numbered `.row-line` list + up/down `btn--sm`; keyboard Alt+ArrowUp/Down moves the focused row; `aria-live` announces "ada moved to position 2"; new `.ux-ordered` | `hitl.escalation_chain` is ORDER-SIGNIFICANT (P5 explicitly deferred an ordered editor until a surface needed one; this is that surface) |
| N18 | `SecretOnce` | `secret, meta:ReactNode, onDone, copyLabel?` | shown / copied / arm-dismiss / done(null) | warn `InfoCallout` + mono block + `.btn--primary` copy + P27 arm semantics on uncopied dismiss; `beforeunload` guard while mounted; new `.ux-secret` | PAT mint (1.5); reusable for any future show-once material (MCP registration tokens) |
| N19 | `DiffView` | `before:object, after:object, elideUnchanged?` | identical / changed | mono two-tone rows using `--color-ok`/`--color-down` text tints (never amber, L4); flat key-path list (`network.allowed_domains[2]`); new `.ux-diff` | admin diff-before-save + rollback restatement (2.2); reusable for AD3 revision diffs |

All three: semantic tokens only, `ux-` prefix, after the v3 cascade layer, focus ring + 44px coarse targets (P36), reduce-motion honoured.

---

## 4. Ops retrofit briefs (the vocabulary lands console-wide)

Cross-cutting first, fixed once and inherited (from the debt inventory): X1 SchemaForm v2 upgrade in place (P9) removes the "Edit this field in the JSON view." punt (ux.tsx:318-319); X2 every `csvToList` call site becomes `ChipPicker`/`ScopeBuilder` (shared.tsx:48-53); X3 every `window.confirm` becomes `ArmConfirm` (7 sites enumerated in the debt inventory); X4 human table headers + TermTip + relative time; X6 busy labels become verb-specific text.

**Router** (RouterPanel.tsx) - read surface, already close to canon:
1. P35 table anatomy on verb rows: sticky thead inside the slide scroller, hover raise, 7-column budget, mono ids middle-truncated.
2. P21 rung 2: TermTip glosses on "runs via" (the P22 binding one-liner) and health badges; keep the glossary as single source.
3. P24: keep the grants-scoping empty state (RouterPanel.tsx:243-249, already the canonical example); changelog timestamps go relative-with-title.
4. Every entity id links to its home (agents to `#/agents/:name`, workflows to `#/automations/:wfid`) per the R9 entity-link contract; run ids are `RunLink`.
5. Poll quiesce: the 15s health poll (RouterPanel.tsx:135) threads `useSlideActive` (DESIGN-v2 already lists it).

**Dev console** (DevConsolePanel.tsx) - the good exemplar; residual debt:
1. D1: spawn skills CSV+append-chips (:441-462) -> `ChipPicker` (P5) over `GET /v1/skills`.
2. D2: `Prefer (JSON)` (:466-477) -> runtime `Select` + model endpoint `EntityPicker` (P6); leftover JSON in a `JsonDisclosure` (P10).
3. D3 resolved per P28 not a double gate: no arm-confirm on high-consequence Run; instead the button label goes honest ("Request approval and run" when the picked verb is high) beneath the existing amber callout, and the 202 one-liner (:103-106) upgrades to `PendingHumanCard` (N15, P30) with live resolution and inline approval when the caller can approve.
4. D4: idempotency key gets its own mono Field inside Tier 3 (P18); remaining context stays a `JsonDisclosure`.
5. Verb picker (:279 flat select) -> `EntityPicker` grouped by noun with consequence badges and the inline preview card (P6 flagship retrofit).

**Approvals** (ApprovalsPanel.tsx) - the arm-confirm origin (:141-176), stays canonical:
1. P33: resolution reconciles from the 8s `GET /v1/hitl` poll, never a component-local resolved map; a request resolved elsewhere (chat, another admin) flips in place with "answered by ada, 2m ago".
2. `hitl_request_id` mono + copyable on every card (N15 symmetry, so a 202 card elsewhere can be found here).
3. Notes field gets full Field treatment: hint "Recorded in the audit log with your decision." (P11).
4. Sort/group by urgency: `blocking` first with the HITL_URGENCY glossary badges (ux.tsx:369-372); amber stays exclusively on consequence/HITL markers (L4 audit).
5. Empty state per P24: "Nothing needs you. High-consequence actions will pause here for approval." - no CTA fabricated (waiting IS the state), optional ByChat-free.

**Kanban** (KanbanPanel.tsx):
1. Keep the empty-state-to-chat routing (:107-116) - it is the P24/P20 canonical example.
2. Lane headers get TermTip glosses from WORK_STATUS (ux.tsx:342-353); `awaiting_human` lane header links to `#/approvals` and its cards carry the amber badge (lawful, L4).
3. P25: skeleton cards on first load only; the 10s poll (:75) never blanks lanes (useFetch stale-keep already guarantees; verify no spinner) and threads slide-quiesce.
4. Card meta: confidence/convergent get rung-2 glosses; "View run" stays `RunLink` (:135).
5. P34 compact density honoured (data-heavy surface).

**Insight** (InsightPanel.tsx):
1. Audit filter row: verb filter -> `EntityPicker` over the registry (P6); actor stays free text but gains a "me" preset chip; run-id keeps mono input; "/" focuses filters (P36).
2. P35: results table gains "Load more" (streams, not books), sticky thead, relative timestamps; keep the exemplary human headers (:296-305).
3. Cost/budget numbers: right-aligned tabular, micros humanized ("$2.41" with micros on title); hard-stop badge gets its gloss ("Work stops when this budget is exhausted") via the glossary, not local copy (P22).
4. Audit export: author/admin server gate rendered as the calm 403 callout (P24 denied), no retry.
5. Every run_id a `RunLink` (already true, :307-326) - preserve through any refit.

**Eval** (EvalPanel.tsx):
1. `forbidden_grants` chips-synced-with-raw-JSON (:86-124) -> `ScopeBuilder` (P7); the JSON assertions become its `JsonDisclosure` escape hatch, two-way (P10).
2. Target picker: skill|workflow segmented + `EntityPicker` over the chosen kind (P3 + P6).
3. Case input JSON gains a `SchemaForm` v2 face when the target declares an input schema; stays `JsonDisclosure`, honestly labelled, when not (P9/P10).
4. Labels -> `ChipPicker` free-entry with candidates from existing cases (P5).
5. Run results: pass/fail as `StatusBadge`, `effective_grants` as `GrantList` with the SEC-29 hint ("proof the run never escalated"), run ids as `RunLink`.

**Memory** (MemoryPanel.tsx):
1. X3: Forget confirm (:279) -> `ArmConfirm` tone danger: "Forget this fact? Provenance stays in the audit log." (P27).
2. X4: browse table headers (:627-637) humanized: Kind / Scope / Class / Added, with TermTip glosses; sensitive class badge gloss "kept on the local endpoint only" (SEC-43).
3. Recall: mode `Segmented` already right (P3 exemplar); `limit` -> `Stepper` 1-50 default 20 (P8, mirroring the route default `int(body.get("limit", 20))`, platform_routes.py:562).
4. Remember: data class -> `CardSelect` standard vs sensitive (P4) with the residency sentence on the sensitive card.
5. Keep the "memory not enabled" mapping of `binding_not_found` as an info callout with enablement guidance (:66-75) - it is the P21 rung-4 pattern done right; ingest table gains Load more.

**Home** (HomePanel.tsx):
1. P25 skeletons on first load of NeedsYou/RecentRuns/WorkInFlight; the 8s HITL poll updates in place, slide-quiesced.
2. NeedsYou cards: amber accents only via the HITL badges (L4); each card links to `#/approvals`; no inline approve on Home (the approvals ritual is not duplicated).
3. QuickStart actions align to P20 declared 80% paths and route to deck anchors (`/chat`, `/automations`, `/router`); the AUTHOR_ROLES gate stays cosmetic (:235-250).
4. WhatICanDo noun groups: verb rows carry consequence badges + glosses so foreshadowing starts on the landing surface (P28).
5. All ids/verbs mono; run rows `RunLink` (:81-119 kept).

---

## 5. Consolidated DEPENDS-BACKEND register

Verbs (all following control_plane.py naming and its params-mirror-the-store-model rule; consequence high unless noted):

1. `control.user.update {user_id, role?, scope?, status?}` - directory writes (1.9).
2. `control.invitation.create {email, role, scope?, ttl_days}` / `control.invitation.revoke {id}` (1.9).
3. `control.config.upsert {section, value}` / `control.config.rollback {section, revision_id}` (2.4).
4. `control.personal_agent.configure {runtime, skills, enabled}` - consequence LOW, recorded deviation (1.6, P5).
5. `account.settings.update`, `account.notification.route`, `account.token.revoke`, `account.session.revoke` - low-consequence self-scope verbs so chat reaches the account plane (1.10). Recommended, lower priority.

Reads:
6. `GET /v1/admin/config/{section}/history/{revision_id}` returning the revision payload value - unlocks AD3 revision diffs and diff-inside-rollback (2.2).
7. Section schemas for `notifications | personal_agents | evaluation | memory` (typed models or a schema read) - upgrades the four JSON-honest editors to SchemaForm faces (2.1).
8. A runtimes list read - upgrades the personal-agent runtime control to an EntityPicker (1.6).
9. Personal-agent configure should stop minting a new id per save and accept `enabled` (platform_routes.py:526-528) - prerequisite for verb 4's params being honest.

Explicit non-dependencies: PAT mint chat verb (deliberately excluded, 1.5/1.10); notification pref delete route (disable suffices, 1.4); an ordered-list storage-shape change (`escalation_chain` is already an ordered array, manifest.py:157). A durable timeout-to-notification consumer is still required before that array may be presented as an active escalation chain.

## 6. Build order (an engineer's sequencing, no decisions left open)

1. Primitives: Field v2 (N8), Switch (N1), ChipPicker (N3), Stepper (N6), JsonDisclosure (N9), ArmConfirm (N14), SaveBar (N10), Disclosure (N11), Skeleton (N13) - then EntityPicker (N4), ScopeBuilder (N5), CardSelect (N2), PendingHumanCard (N15), ByChat (N16), and this spec's N17/N18/N19.
2. Settings row: routes + anchor, then sections in order account, appearance, security, privacy (pure retrofits), notifications matrix, developer wizard + SecretOnce, personal agent (+ MePanel de-duplication), organisation.
3. Admin: shell + dirty guard, typed section editors (privacy, network, hitl, models), DiffView save/rollback, export/credentials, JSON-honest extra sections.
4. Ops retrofits in the X-then-panel order of section 4 (cross-cutting fixes first so panels inherit them).
5. Verb flips as backend deps land: each is a transport swap inside an already-P30-shaped form; add ByChat at each flip.

Key source files: `/home/jellytot/Projects/boltrig/ui/src/panels/SettingsPanel.tsx`, `/home/jellytot/Projects/boltrig/ui/src/panels/AdminPanel.tsx`, `/home/jellytot/Projects/boltrig/ui/src/panels/MePanel.tsx`, `/home/jellytot/Projects/boltrig/ui/src/panels/ux.tsx`, `/home/jellytot/Projects/boltrig/ui/src/panels/shared.tsx`, `/home/jellytot/Projects/boltrig/ui/src/api/client.ts`, `/home/jellytot/Projects/boltrig/boltrig/kernel/access_routes.py`, `/home/jellytot/Projects/boltrig/boltrig/kernel/platform_routes.py`, `/home/jellytot/Projects/boltrig/boltrig/config/manifest.py`, `/home/jellytot/Projects/boltrig/boltrig/config/admin.py`, `/home/jellytot/Projects/boltrig/boltrig/config/control_plane.py`, `/home/jellytot/Projects/boltrig/boltrig/identity/tokens.py`.
