# Boltrig Console Frontend - Requirements (brownfield)

Status: FROZEN baseline captured 2026-07-01. The console frontend (`ui/`) is frozen for building; this document is the complete specification of what the app does today (Part A, catalogued from code) and what it should do next (Part B, target requirements). It is authored VJS-brownfield style: current behaviour is recorded exactly as built, target behaviour is layered on top and clearly separated, and every requirement is a single testable sentence with a stable id and a source.

Sources of truth read for Part A: `ui/src/App.tsx`, `ui/src/router.ts`, `ui/src/identity.ts`, `ui/src/useFetch.ts`, `ui/src/appearance.ts`, `ui/src/api/client.ts`, `ui/src/api/types.ts`, every file under `ui/src/panels/`, `ui/vite.config.ts`, and the kernel route surface in `boltrig/kernel/app.py`, `platform_routes.py`, `access_routes.py`, `memory_routes.py`, `channel_routes.py`, plus `boltrig/adapters/builtin/channel_send.py` and `boltrig/identity/rbac.py`.

## Conventions

1. Requirement ids are `REQ-CON-<AREA>-<nn>` and are stable: never renumber, only append.
2. Each requirement carries a source tag:
   - `built` - implemented today; the requirement is a faithful statement of current behaviour and a regression test target.
   - `audit-gap` - found by comparing the UI against the kernel surface; the kernel capability exists with no (or deficient) UI.
   - `corporate-brain` - a known product intent from the standing programme (channels admin, hierarchical work, degraded honesty, cost true-up, canvas channel nodes).
   - `idea-batch` - target items from the 2026-07-01 idea batch (run replay, why-did-this-happen, approval policies, dry-run, MCP catalog, budgets UI, changelog view, agent org view, saved views).
3. Target requirements state their dependency in square brackets, e.g. `[needs: engine degraded flag]`.
4. Console planes: Capability (Router, Studio, Dev console), Orchestration (Chat), Activity (Home, Kanban, Approvals, Insight, Eval, Memory), Account (Admin, Me, Settings).
5. Role vocabularies. Console roles: `org-admin`, `department-head`, `manager`, `lead`, `integrator`, `agent`. `can_author` (kernel `boltrig/identity/rbac.py`, SEC-32) is true for every role except `agent`; the UI mirrors this as `AUTHOR_ROLES`. Console admin gate is `org-admin` only. Channel binding tiers are a separate vocabulary: `superadmin`, `admin`, `member` (`CHANNEL_TIERS` in `channel_gateway.py`).
6. All UI role gates are cosmetic; the kernel is the authoritative gate and returns `403 {status:"denied", reason}` which the UI must render faithfully.

---

# PART A - CURRENT BEHAVIOUR (as built)

## A1. Application shell, navigation and identity

Purpose: the single-page shell hosting all panels, the plane-grouped sidebar, the dev identity mechanism, and the kernel health indicator. Plane: all. Gating: tab visibility per role (cosmetic).

1. REQ-CON-SHELL-01 (built): The console is a single-page React app whose active panel is selected by the URL hash and rendered inside one `<main>` region wrapped in an error boundary keyed by the active tab.
2. REQ-CON-SHELL-02 (built): The sidebar groups tabs under four plane labels in this order: Capability (Router, Studio, Dev console), Orchestration (Chat), Activity (Home, Kanban, Approvals, Insight, Eval, Memory), Account (Admin, Me, Settings).
3. REQ-CON-SHELL-03 (built): The Studio and Dev console tabs are shown only when the current role is in `AUTHOR_ROLES` = {org-admin, department-head, manager, lead, integrator}, and the Admin tab only when the role is `org-admin`.
4. REQ-CON-SHELL-04 (built): When the active tab becomes hidden because the role changed, the shell renders the Home panel instead.
5. REQ-CON-SHELL-05 (built): The sidebar is collapsible (64px rail) and resizable by pointer drag and by keyboard (arrow keys step 8px, shift-arrow 32px, Home/End jump to min/max), clamped to 200..420px, with collapsed state and width persisted in localStorage keys `boltrig:sidebar-collapsed` and `boltrig:sidebar-width`.
6. REQ-CON-SHELL-06 (built): The sidebar resizer is exposed as a WAI-ARIA vertical separator with `aria-valuenow/min/max`.
7. REQ-CON-SHELL-07 (built): A health dot in the sidebar footer polls `GET /healthz` every 15 seconds and shows `kernel: ok` (green), `kernel: unreachable` (red) or `kernel: unknown`.
8. REQ-CON-SHELL-08 (built): An identity chip in the sidebar footer shows the acting subject, role and tenant, marked `dev`, and toggles the expanded identity bar.
9. REQ-CON-SHELL-09 (built): The StudioPanel is code-split (React.lazy) so the @xyflow/react canvas chunk downloads only when Studio (or the Router tree view) is opened, with `react` and `reactflow` also split as manual vendor chunks in the Vite build.
10. REQ-CON-SHELL-10 (built): On first load the shell applies the persisted appearance (theme, density, contrast, font scale, reduced motion) to `<html>` before any panel paints.

### A1.1 Dev identity bar parameter inventory

Every request carries these values as `x-boltrig-*` headers (see A2). Store: localStorage key `boltrig.identity`, exposed via `useSyncExternalStore`.

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Organisation | text | any string | `default` | header `x-boltrig-tenant` |
| Acting as | text | any string | `dev` | header `x-boltrig-subject` |
| Role | select | org-admin, department-head, manager, lead, integrator, agent | `org-admin` | header `x-boltrig-role` |
| Departments | text (comma list) | any | empty | header `x-boltrig-departments` |
| Grants | text (comma list of grant patterns) | e.g. `*`, `ticket.*`, `ticket.create` | `*` | header `x-boltrig-grants` |
| Grant presets | buttons | Admin `*`; Support agent `ticket.*, conversation.*`; Read-only `*.read` | n/a | sets Grants |
| Reset to defaults | button | n/a | n/a | restores the default identity |

11. REQ-CON-SHELL-11 (built): The identity bar edits exactly five values (tenant, subject, role, departments, grants), persists them to localStorage key `boltrig.identity`, and every subsequent request reflects the change immediately.
12. REQ-CON-SHELL-12 (built): Three grant presets and a reset control set the grants field to `*`, `ticket.*, conversation.*`, or `*.read`, and reset restores tenant `default`, subject `dev`, role `org-admin`, grants `*`, departments empty.
13. REQ-CON-SHELL-13 (audit-gap): The kernel dev resolver also reads `x-boltrig-tier`, `x-boltrig-obo` and `x-boltrig-verbs` headers, none of which the identity bar can set, so an agent-tier or on-behalf-of caller cannot be simulated from the UI.

## A2. API client and transport

1. REQ-CON-API-01 (built): All API paths are relative and proxied to the kernel (`/v1` and `/healthz`) by the Vite dev server and the nginx production image, with an optional `VITE_API_BASE` prefix.
2. REQ-CON-API-02 (built): Every request carries the five identity headers `x-boltrig-tenant`, `x-boltrig-subject`, `x-boltrig-grants`, `x-boltrig-role`, `x-boltrig-departments` read live from the identity store.
3. REQ-CON-API-03 (built): Non-2xx responses on writes flagged `tolerateStatus` are returned parsed (so `{status:"denied", reason}` renders inline); all other non-2xx responses throw `ApiError{status, body}`; network failures throw `ApiError` with status 0.
4. REQ-CON-API-04 (built): `POST /v1/chat` and `GET /v1/runs/{id}/events` are consumed as Server-Sent Events: frames are delimited by a blank line, CRLF is normalised, multi-line `data:` payloads are joined, `[DONE]` and unparseable frames are ignored, and a trailing unterminated frame is flushed at stream end.
5. REQ-CON-API-05 (built): `streamRunEvents` accepts `follow` (default false = snapshot then end; `?follow=1` = replay backlog then live until the run closes) and an `AbortSignal`.
6. REQ-CON-API-06 (built): `useFetch` renders errors by kind: HTTP 403 as "You don't have access to this." (calm notice with `errorStatus` 403), status 0 as "Can't reach the server - check your connection.", and anything else as the message plus the body `reason` when present; polling reloads never re-show the blocking loading state once data exists, and stale in-flight responses are dropped by a monotonic sequence guard.
7. REQ-CON-API-07 (built): `apiReason` extracts the kernel `{reason}` from a thrown `ApiError` body so the faithful server reason, never a raw `POST ... -> 403`, is shown.

## A3. Hash router and the global run drawer

1. REQ-CON-NAV-01 (built): The route grammar is `#/<tab>`, `#/<tab>/<param>`, `#/<tab>?run=<id>` (run drawer overlay preserving the tab), and `#/runs/<id>` (deep link carrying the run in the path).
2. REQ-CON-NAV-02 (built): `openRun(runId)` sets `?run=` on the current path without changing the active tab; `closeRun()` removes it; `navigate(path)` switches tab and drops any open drawer.
3. REQ-CON-NAV-03 (built): Browser back/forward and deep links work for tab, param and run-id state because all of it lives in `window.location.hash`.

## A4. Command palette

Purpose: Cmd/Ctrl-K jump-to-anything overlay. Plane: global. Gating: none (verbs listed are already caller-scoped by the server).

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Search input | text | any | empty | client-side substring filter on command label |
| Result rows | list (max 30) | 12 static pages + one row per scoped verb | pages first | page rows call `navigate(/<page>)`; verb rows navigate to `/dev` |
| Keyboard | keys | ArrowUp/ArrowDown move, Enter run, Esc close | n/a | selection index |

1. REQ-CON-PAL-01 (built): Cmd-K or Ctrl-K toggles the palette, the sidebar Search button opens it via the `boltrig:open-palette` custom event, and Esc or a backdrop click closes it.
2. REQ-CON-PAL-02 (built): The palette lists the 12 pages (home, router, studio, dev, chat, kanban, approvals, insight, eval, memory, me, settings) plus one command per verb from `GET /v1/capabilities`, fetched lazily on first open.
3. REQ-CON-PAL-03 (built): Filtering is case-insensitive substring match on the label, capped at 30 rows, with arrow-key selection, Enter to run and mouse-hover selection.
4. REQ-CON-PAL-04 (built): Selecting a verb row navigates to the Dev console; it does not pre-select that verb in the invoke form.
5. REQ-CON-PAL-05 (built): Focus is trapped inside the palette while open and restored to the opener on close.
6. REQ-CON-PAL-06 (idea-batch): Selecting a verb in the palette SHOULD deep-link to the Dev console with that verb pre-selected and its schema form pre-rendered. [needs: dev-console verb query param]

## A5. Home panel

Purpose: capability-aware landing dashboard reflecting the caller's scoped state; owns no data, links into real panels. Plane: Activity. Gating: none (Quick start "New workflow" shows only for `AUTHOR_ROLES`).

Cards and their parameters:

| Card | Data source | Poll | Controls / fields shown |
|---|---|---|---|
| Needs you | `GET /v1/hitl` | 8s | count of pending; top 3 requests as type badge + question; each row navigates to /approvals; "View all N" button |
| Recent runs | `GET /v1/runs` | none | Refresh button; top 5 rows: intent, status badge (WORK_STATUS glossary), RunLink "open" or "no run" |
| Work in flight | `GET /v1/work` | none | per-lane counts for in_flight, pending, blocked, awaiting_human, done, failed; "Open the board" button |
| What I can do | `GET /v1/capabilities` | none | total verb count; per-noun count tags sorted alphabetically; "Browse the router" button |
| Quick start | none | n/a | "New conversation" (/chat), "New workflow" (/studio, authors only), "Browse capabilities" (/router) |

1. REQ-CON-HOME-01 (built): Home renders five cards (Needs you, Recent runs, Work in flight, What I can do, Quick start) and never mutates data.
2. REQ-CON-HOME-02 (built): Needs you polls `GET /v1/hitl` every 8 seconds, shows at most three questions with their HITL type badge, and links every row and the overflow button to the Approvals tab.
3. REQ-CON-HOME-03 (built): Recent runs shows the first five rows of `GET /v1/runs` with intent, work-status badge and a RunLink that opens the global run drawer.
4. REQ-CON-HOME-04 (built): Work in flight counts `GET /v1/work` items per status across exactly the six lanes in_flight, pending, blocked, awaiting_human, done, failed.
5. REQ-CON-HOME-05 (built): What I can do groups scoped verbs by noun (empty noun renders as "(unspecified)") and states the count of areas and total actions.
6. REQ-CON-HOME-06 (built): Every card renders its own loading ("Loading..."), error ("Failed to load ...: reason") and empty state, and an empty capabilities result explains that grants decide visibility.
7. REQ-CON-HOME-07 (built): The header shows the acting identity as `subject @ tenant`.

## A6. Router panel (capability browser) and Registry canvas

Purpose: browse everything the identity may do: nouns, verbs, consequence, binding and live adapter health. Plane: Capability. Gating: none (data is server-scoped).

### A6.1 Parameter inventory

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| View toggle | segmented | List, Tree | List | client-side view state |
| Refresh | button | n/a | n/a | reloads `GET /v1/capabilities` and `GET /healthz` |
| Verb row: consequence badge | badge | high (amber), low, unknown | from `verb.consequence` | `VerbInfo.consequence` |
| Verb row: binding | text | `runs via <target_ref>` or "not wired yet" | n/a | `VerbInfo.binding.target_ref` |
| Verb row: health badge | badge | ok, degraded, down, unknown | resolved | `verb.health` else `/healthz` adapters map |
| Changelog card | list (12 rows) | action, ref, actor, relative time | n/a | `GET /v1/capabilities/changelog` |

1. REQ-CON-RTR-01 (built): The Router fetches `GET /v1/capabilities` once and `GET /healthz` on a 15-second poll, and groups verbs by noun sorted alphabetically with verbs sorted by id.
2. REQ-CON-RTR-02 (built): Health per verb resolves in this order: the verb's own `health` field when it is one of ok/degraded/down/unknown; else the `/healthz` adapters map by exact binding ref, then by `<tenant>/<ref>`, then by any key whose last path segment equals the ref; else `unknown`.
3. REQ-CON-RTR-03 (built): A verb with no binding renders "not wired yet" with an explanatory tooltip, and health falls back to unknown.
4. REQ-CON-RTR-04 (built): A health fetch failure degrades softly: a warning line "Health unavailable (reason); showing adapter health as unknown" is shown and all badges read unknown.
5. REQ-CON-RTR-05 (built): The empty state names the caller's grants verbatim and explains that grants decide what appears.
6. REQ-CON-RTR-06 (built): The Tree view (RegistryCanvas, lazy-loaded) renders a read-only three-column React Flow tree, noun (col 0, centred against its verbs) to verb (col 1, consequence badge, health badge when adapter-bound, high-consequence border) to exactly one binding leaf (col 2, coloured agent/service by `target_type`), with pan, zoom, minimap and free node drag but no editing.
7. REQ-CON-RTR-07 (built): User-dragged node positions in the Tree view survive the 15-second health-poll rebuild.
8. REQ-CON-RTR-08 (built): The "Recent capability changes" card lists up to 12 rows of `GET /v1/capabilities/changelog` with action, ref, actor and relative timestamp, plus a Refresh control.
9. REQ-CON-RTR-09 (audit-gap): `GET /v1/capabilities/changelog` is author/admin gated server-side (403 `author_or_admin_required`) but the changelog card is shown to every role, so an `agent` sees a permission notice instead of either a hidden card or useful content; the card SHOULD be gated or the copy tailored.
10. REQ-CON-RTR-10 (audit-gap): The kernel supports `GET /v1/capabilities?noun=<id>` filtering, which no UI surface uses.

## A7. Studio panel (authoring hub)

Purpose: compose what agents can do: skills, router authoring (nouns/verbs/bindings), adapters, workflows. Plane: Capability. Gating: tab offered to `AUTHOR_ROLES` only; a non-author who reaches it sees a warning notice and the server rejects writes with 403.

1. REQ-CON-STU-01 (built): Studio hosts four internal sub-tabs (Skills, Router authoring, Adapter Studio, Workflow Studio) using component state, not the router.
2. REQ-CON-STU-02 (built): Non-author identities see a notice naming their role and listing the five authoring roles, and every write renders the server's `{status, reason}` denial inline (AckLine) rather than throwing.

### A7.1 Skills studio

| Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Skill id | text (required) | lowercase dotted id | empty | `POST /v1/skills` `id` |
| Version | text | semver | `1.0.0` | `version` |
| Instruction | textarea | any | empty | `prompt_fragment` |
| Permissions | text (comma list) | verb ids/patterns | empty | `tool_grants` |
| Add a permission | chip per scoped verb | verbs from `GET /v1/capabilities` | n/a | appends to Permissions |
| Context requirements | textarea (JSON, collapsed under Advanced) | JSON object | `{}` | `context_requirements` |
| Test spawn: skill id | text (required) | existing skill id | empty | path of `POST /v1/skills/{id}/test-spawn` |
| Test spawn: task | text | any | empty (defaults to `test <id>`) | body `task` |

3. REQ-CON-STU-03 (built): Saving a skill posts `{id, version, prompt_fragment, tool_grants, context_requirements}` to `POST /v1/skills`, requires a non-empty id, surfaces invalid JSON in context requirements as a form error before any request, and reloads the skills list on `status:"ok"`.
4. REQ-CON-STU-04 (built): The skills list (`GET /v1/skills`) shows `id`, `vVERSION` and the tool grants as chips, with loading, error and "No skills yet." states.
5. REQ-CON-STU-05 (built): Test spawn posts to `POST /v1/skills/{id}/test-spawn` and renders the returned `effective_grants` chips as the no-escalation evidence (SEC-29) plus the full result JSON, or the denial reason on `status:"denied"`.

### A7.2 Router authoring

| Form | Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Add noun | id | text (required) | any | empty | `POST /v1/nouns` `id` |
| Add noun | description | text | any | empty | `description` |
| Add noun | schema | textarea JSON | object | `{}` | `schema` |
| Add verb | id | text (required) | any | empty | `POST /v1/verbs` `id` |
| Add verb | noun_id | text (required) | existing noun | empty | `noun_id` |
| Add verb | consequence | select | low, high | low | `consequence` |
| Add verb | input_schema | textarea JSON | JSON-Schema object | `{}` | `input_schema` |
| Add verb | output_schema | textarea JSON | JSON-Schema object | `{}` | `output_schema` |
| Set binding | Verb | select | scoped verbs | empty | path of `POST /v1/verbs/{id}/binding` |
| Set binding | Runs via | segmented | adapter, agent | adapter | `target_type` |
| Set binding | Which adapter/agent | select (adapters from `GET /v1/adapters`) or free text (agent) | n/a | empty | `target_ref` |

6. REQ-CON-STU-06 (built): The noun and verb forms validate required ids and JSON fields client-side, post to `POST /v1/nouns` and `POST /v1/verbs`, and render the ack or denial inline.
7. REQ-CON-STU-07 (built): The binding form requires a verb and a target ref, switches the target control between an adapter dropdown and a free-text agent id when the segmented target type changes (clearing the ref), and posts `{target_type, target_ref}` to `POST /v1/verbs/{verbId}/binding`.

### A7.3 Adapter studio

| Form | Field | Type | Default | Maps to |
|---|---|---|---|---|
| Generate | adapter_id | text (required) | empty | `POST /v1/adapters/generate` `adapter_id` |
| Generate | spec | textarea (OpenAPI JSON) | `{}` | `spec` |
| Activate | adapter id | text (required) | empty | path of `POST /v1/adapters/{id}/activate` |
| Activate | reviewer | text | empty | body `reviewer` |
| Register MCP | id | text (required) | empty | `POST /v1/mcp/servers` `id` |
| Register MCP | url | text | empty | `url` |
| Register MCP | token | text | empty | `token` |

8. REQ-CON-STU-08 (built): Generate posts the OpenAPI spec and renders the result with an `activated`/`inert` badge and the generated verb list, and generated adapters land inert (`activated: false`) until reviewed (SEC-22).
9. REQ-CON-STU-09 (built): Activate posts an optional reviewer name and on success shows the bound verbs and reloads the inventory; a response carrying `error` or `reason` renders as the failure text.
10. REQ-CON-STU-10 (built): Register MCP server posts `{id, url?, token?}` to `POST /v1/mcp/servers` and reloads the adapter inventory on ok.
11. REQ-CON-STU-11 (built): The adapter inventory (`GET /v1/adapters`) lists id, runtime, version, an activated/inert badge and a health badge per adapter, with a Refresh control.

### A7.4 Workflow studio (form view)

| Form | Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Upsert | id | text (required) | any | empty | `POST /v1/workflows` `id` |
| Upsert | version | text | semver | `1.0.0` | `version` |
| Upsert | source | read-only provenance | precreated, generated, learned | precreated for a new authored definition | omitted from `POST /v1/workflows`; assigned/preserved by the kernel |
| Upsert | definition / steps | textarea JSON | object | `{}` | `definition` |
| Upsert | intent_tags | text (comma list) | any | empty | `intent_tags` |
| Schedule | Workflow | select from `GET /v1/workflows` | existing ids | empty | path of `POST /v1/workflows/{id}/schedule` |
| Schedule | When (cron) | text (required) | 5-field cron | empty | `cron` |
| Schedule | cron presets | chips | Hourly `0 * * * *`, Daily 9am `0 9 * * *`, Weekdays 9am `0 9 * * 1-5`, Mondays 9am `0 9 * * 1` | n/a | sets cron |
| Schedule | Timezone | select | UTC, Europe/London, Europe/Paris, America/New_York, America/Chicago, America/Los_Angeles, Asia/Singapore, Asia/Tokyo, Australia/Sydney | UTC | `timezone` |
| Trigger | Workflow | select | existing ids | empty | path of `POST /v1/workflows/{id}/trigger` |
| Trigger | Inputs | textarea JSON | object | `{}` | `inputs` |
| Execute | Workflow | select | existing ids | empty | path of `POST /v1/workflows/{id}/execute` |
| Execute | Inputs | textarea JSON | object | `{}` | `inputs` |
| View runs | Workflow | select | existing ids | empty | `GET /v1/workflows/{id}/runs` |
| Verb palette | click-to-copy rows | scoped verbs | n/a | copies verb id to clipboard for use as a step `action` |

12. REQ-CON-STU-12 (built): Upsert saves `{id, version, definition, intent_tags}`, validating the definition JSON client-side and reloading the workflow list on ok. `source` remains read-only and kernel-owned.
13. REQ-CON-STU-13 (built): Trigger renders the returned run descriptor with engine badge, durable/in-process badge, status badge, a RunLink when `run_id` is present and the raw descriptor JSON; a descriptor carrying `error` renders as the error.
14. REQ-CON-STU-14 (built): Execute runs the stored steps synchronously through the chokepoint and renders the run record: overall status badge (completed=ok, failed=down, paused=degraded), RunLink, workflow id and version, and per-step rows with id, action, status badge, failure reason and output JSON.
15. REQ-CON-STU-15 (built): View runs lists the run ids returned by `GET /v1/workflows/{id}/runs` each as a RunLink.
16. REQ-CON-STU-16 (built): The workflows list shows id, version, source badge and intent tags; the verb palette lists scoped verbs with consequence and binding type and copies the verb id to the clipboard on click, showing "copied".

### A7.5 Workflow canvas (edit mode)

Purpose: visual editor over the identical `definition.steps` contract (`{id, parents[], action, params?, description?}`); Save serialises the graph byte-for-byte to what the form view would send.

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Workflow id / version / source / intent_tags | source is read-only; other fields as form view | as form view | `1.0.0`, kernel-assigned precreated | `POST /v1/workflows` omits source |
| Save / Run / Clear | buttons | n/a | n/a | Save = upsert `{definition:{steps}}`; Run = `POST /v1/workflows/{id}/execute` with `{}` inputs; Clear empties the canvas |
| existing run id + View run | text + button | run id | empty | opens the live run canvas for the current workflow id |
| Verb palette | click-to-add rows + search box (shown when more than 6 verbs) | scoped verbs, filter on id or noun | empty filter | adds a step node; node kind derived from binding (agent bound = agent, adapter bound = service, else kernel-run) |
| Triggers | buttons | + chat, + cron, + webhook | n/a | adds a visual trigger entry node (excluded from serialisation) |
| Edge drawing | drag handle to handle | step-to-step edges become `parents`; trigger edges contribute no parent | n/a | `steps[].parents` |
| Step inspector: id | text | unique node id | selected node id | renames the step and re-points edges; duplicate id is an inline error |
| Step inspector: action (verb) | select | scoped verbs | node's action | swaps the verb in place, re-deriving kind and consequence |
| Step inspector: kind | read-only text | agent, service, kernel-run | derived | display only |
| Step inspector: description | text | any | node description | `steps[].description` |
| Step inspector: parameters | SchemaForm from the verb's `input_schema`, with an "Edit as JSON" fallback; plain JSON textarea when the verb has no schema | typed values | `{}` | `steps[].params` |
| Apply / Rename id / Delete | buttons | n/a | n/a | commit inspector, rename node, remove node and its edges |
| Load definition (JSON) | textarea + button | steps array, `{steps:[...]}`, or `{definition:{steps:[...]}}` | empty | renders steps onto the canvas (inverse of Save) |
| Serialised steps (preview) | read-only JSON | n/a | live | the exact `definition.steps` Save will send |

17. REQ-CON-WFC-01 (built): Loading a workflow (pick from the list, or paste JSON) lays steps out left-to-right by dependency depth and emits one edge per parent link, and saving performs the exact inverse with steps ordered parents-before-children (Kahn topological order, falling back to insertion order on a cycle so Save never throws).
18. REQ-CON-WFC-02 (built): Node kind is derived only from the chosen verb's binding (never a hand-kept list): agent-bound = agent, adapter-bound = service, otherwise kernel-run.
19. REQ-CON-WFC-03 (built): A step whose verb is high-consequence shows a "!" marker foreshadowing the approval pause, on the palette row and on the node.
20. REQ-CON-WFC-04 (built): Trigger nodes (chat, cron, webhook) are visual entry markers only, have a source handle only, and are excluded from the serialised steps.
21. REQ-CON-WFC-05 (built): Unsaved inspector edits are committed before selection moves (node click or palette add); invalid params JSON blocks the navigation and shows the parse error instead of silently dropping the edits.
22. REQ-CON-WFC-06 (built): New step ids are generated from the verb's last dotted segment, sanitised to `[a-zA-Z0-9_]` and de-duplicated with a numeric suffix.
23. REQ-CON-WFC-07 (built): Run executes the current workflow id and, when a `run_id` comes back, switches into the live run canvas; the run record is also rendered below the canvas exactly as in the form view.

### A7.6 Workflow run canvas (live mode)

24. REQ-CON-WFC-08 (built): The run canvas renders the stored workflow graph (via `GET /v1/workflows/{wfId}`) read-only (no drag, connect or select) and overlays per-node run status from `workflow_step` events on `GET /v1/runs/{runId}/events?follow=1`, matching `step_id` to node id.
25. REQ-CON-WFC-09 (built): Node run states are pending (default), running (pulsing, honouring prefers-reduced-motion), ok, failed, error, skipped; when the stream closes any node still "running" reverts to pending, and a live/stream-closed badge reflects stream state.
26. REQ-CON-WFC-10 (built): Clicking any node opens the global run drawer for the run; a 404 from both the workflow read and the stream renders one clean "Run or workflow not found, or not in your visibility scope." notice.
27. REQ-CON-WFC-11 (built): follow=1 replays already-emitted events before going live, so the canvas lights correctly for an already-finished run.

## A8. Dev console

Purpose: run one verb by hand, spawn an ephemeral agent, and read generated adapter source. Plane: Capability. Gating: tab for `AUTHOR_ROLES` (cosmetic); the chokepoint is the real gate.

### A8.1 Parameter inventory

| Section | Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Invoke | Verb | select | scoped verbs labelled `noun / verb.id` | empty | sets `noun` + `verb` for `POST /v1/invoke` |
| Invoke | Arguments | SchemaForm from `input_schema` (strings, numbers, booleans, enums typed; object/array deferred to JSON), with "Edit as JSON / show schema" fallback; plain JSON textarea when no schema | typed values | schema skeleton (typed placeholders per property) | `params` |
| Invoke (Advanced) | Run id | text | run id | empty | merged into `context.run_id` |
| Invoke (Advanced) | Noun / Verb id | text | any | auto-set from picker | `noun`, `verb` (manual override) |
| Invoke (Advanced) | Extra context | textarea JSON | object | empty | `context` |
| Spawn | Task | textarea (required) | plain language | empty | `POST /v1/spawn` `task` |
| Spawn | Skills | text (comma list) + add-a-skill chips from `GET /v1/skills` | skill ids | empty | `skills` |
| Spawn (Advanced) | Prefer | textarea JSON | object, e.g. `{"runtime":"pi-worker"}` | empty | `prefer` |
| Adapter source | Adapter | select from `GET /v1/adapters` labelled `id (runtime version)` | registered adapters | empty | `GET /v1/adapters/{id}/source` |

1. REQ-CON-DEV-01 (built): Picking a verb sets noun and verb, shows the selection with its consequence badge, and prefills the params box with a typed skeleton derived from the verb's `input_schema` unless the user has already typed.
2. REQ-CON-DEV-02 (built): A high-consequence verb shows a consequence callout warning that the action is real, possibly irreversible, and may pause for human approval.
3. REQ-CON-DEV-03 (built): Invoke renders the kernel result union faithfully: `ok` and `degraded` show the output (degraded adds the notice "Adapter degraded; the output below is best-effort."), `pending_human` shows the HITL request id and points to Approvals, `denied` and `error` show the reason; a `run_id` found at the top level or inside `output` renders as a RunLink.
4. REQ-CON-DEV-04 (built): Spawn posts `{task, skills?, prefer?}` and renders the status badge, RunLink, failure reason, the `effective_grants` chips (permissions the agent actually got) and the full result JSON.
5. REQ-CON-DEV-05 (built): Adapter source loads `GET /v1/adapters/{id}/source` read-only into a code block, rendering a response `error` field as the failure text.
6. REQ-CON-DEV-06 (built): An empty scoped registry renders the empty state "No verbs are available to you" explaining that grants decide visibility.
7. REQ-CON-DEV-07 (audit-gap): The invoke form does not surface `idempotency_key` or `approval_id` as first-class fields (only reachable by hand-typing context or not at all), although `POST /v1/invoke` accepts both, so resuming a paused invoke with its approval id cannot be done from the UI.

## A9. Chat panel

Purpose: converse with the orchestrator; live streamed transcript with reasoning, tool cards, sub-agent cards, workflow step checklists and inline HITL. Plane: Orchestration. Gating: none.

### A9.1 Parameter inventory

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Conversation rail | list | conversations with title, status badge, relative updated time | most recent | `GET /v1/conversations`; select loads `GET /v1/conversations/{id}` |
| New conversation | button | n/a | n/a | clears active id; next send omits `conversation_id` |
| Composer | textarea | any; Enter sends, Shift-Enter newline | empty | `POST /v1/chat` `{message, conversation_id?}` |
| Send | button | disabled while streaming or empty | n/a | starts the SSE stream |
| Example prompts | chips | "Create a ticket for a refund request", "Summarise today's escalations", "What can you do for me?" | n/a | fills the composer |
| Inline HITL card | option buttons (approval: options or approve/reject fallback) or free-text (clarification) + optional notes | server options | n/a | `POST /v1/hitl/{id}/respond` `{decision, notes}` |

1. REQ-CON-CHAT-01 (built): Sending a message streams `POST /v1/chat` as SSE and renders events as they arrive: text deltas, dimmed reasoning ("thinking"), a workflow StepsCard folding `workflow_step` events by step id, expandable ToolCards pairing each `tool_result` with the most recent still-running `tool_call` of the same verb, SubagentCards, and inline HITL cards.
2. REQ-CON-CHAT-02 (built): A new conversation's id is captured from the first `message_start` event and threaded into subsequent sends.
3. REQ-CON-CHAT-03 (built): When the stream ends cleanly the transcript is re-fetched from the server (the persisted messages replace the optimistic local turn) and the conversation list reloads.
4. REQ-CON-CHAT-04 (built): A dropped stream keeps the partial turn on screen and offers a Reconnect button that re-fetches the persisted conversation (US-CONV-07); a user-initiated abort is not treated as an error.
5. REQ-CON-CHAT-05 (built): Re-opened conversations re-render the same structured cards as the live stream because persisted messages carry their `events` array.
6. REQ-CON-CHAT-06 (built): Inline HITL approval cards show the request's options (falling back to approve/reject), clarifications show a free-text answer, both accept optional notes, and answering marks the card resolved in place; the same request is shared with the Approvals panel store.
7. REQ-CON-CHAT-07 (built): A sub-agent card's child run id is a handle that opens the global run drawer for that child run.
8. REQ-CON-CHAT-08 (built): While streaming with no text yet, a "thinking..." placeholder shows; the composer button reads "Thinking..." and is disabled.
9. REQ-CON-CHAT-09 (built): Denied or failed chat requests render the kernel's faithful reason (via the canonical `{status, reason}` envelope), not the raw HTTP status line.
10. REQ-CON-CHAT-10 (built): The message region is an `aria-live="polite"` region with `aria-busy` while streaming.

## A10. Kanban panel

Purpose: board of work items in status lanes. Plane: Activity. Gating: none (rows are department-scoped server-side).

### A10.1 Parameter inventory

| Element | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Lanes | fixed columns | pending, in_flight, blocked, awaiting_human, done, failed (in that order) | n/a | `WorkItem.status` |
| Card: intent | text | any ("(no description)" fallback) | n/a | `WorkItem.intent` |
| Card: Came from | text | source or "unknown" | n/a | `WorkItem.source` |
| Card: Owner | text | owner or "unassigned" | n/a | `WorkItem.owner_member` |
| Card: Confidence | percentage | `round(confidence*100)%` or "unknown" | n/a | `WorkItem.confidence` |
| Card: Convergent | yes/no | n/a | n/a | `WorkItem.convergent` |
| Card: View run | button | shown when `hatchet_run_id` set, else "Not started yet" | n/a | `openRun(hatchet_run_id)` |
| Refresh | button + 10s poll | n/a | n/a | `GET /v1/work` |

1. REQ-CON-KAN-01 (built): The board polls `GET /v1/work` (no status query param; lane bucketing is client-side) every 10 seconds and shows the total item count in the header.
2. REQ-CON-KAN-02 (built): Each card shows intent, source, owner, confidence percentage and convergent flag, and a "View run" handle opening the run drawer when the item has a `hatchet_run_id`.
3. REQ-CON-KAN-03 (built): Lane headers carry the plain-language status tooltip from the shared WORK_STATUS glossary and a per-lane count, and an empty lane reads "Nothing here".
4. REQ-CON-KAN-04 (built): The board-wide empty state offers a "Start in Chat" action; fetch failures render via FetchError with retry.
5. REQ-CON-KAN-05 (audit-gap): `WorkItem.parent_id` is returned by the API and typed in the client but is not rendered anywhere, so parent/child structure is invisible on the board.
6. REQ-CON-KAN-06 (audit-gap): Cards are not clickable through to a work-item detail view even though `GET /v1/work/{id}` exists (see B2).
7. REQ-CON-KAN-07 (audit-gap): The board offers no filters (owner, source, convergent, text) and no server-side `?status=` narrowing despite the endpoint supporting it.

## A11. Approvals panel (HITL)

Purpose: the canonical safety surface for pending human-in-the-loop requests. Plane: Activity. Gating: none to view; the kernel enforces that only a human tier may approve and that a requester may never approve their own request (SEC-14).

### A11.1 Parameter inventory

| Element | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Card badges | badges | HITL type (approval, clarification, escalation); "high" consequence badge on approvals; urgency (blocking, async) when present | n/a | `HITLRequest.type/urgency` |
| Question | text | server question or a fallback line | n/a | `question` |
| Work item link | code | shown when set | n/a | `work_item_id` |
| Traces to run | RunLink | shown when the context object carries `run_id` or `run` | n/a | `context.run_id` |
| Full details | collapsible pre | JSON or string context | collapsed | `context` |
| Option buttons | buttons | server `options`; approve/yes/allow style primary, reject/no/deny style danger, others neutral | n/a | arm-then-confirm before `POST /v1/hitl/{id}/respond` |
| Your answer | text input + Send | free text (when no options) | empty | `decision` |
| Notes | textarea | any | empty | `notes` (recorded in the audit trail) |
| Refresh | button + 8s poll | n/a | n/a | `GET /v1/hitl` |

1. REQ-CON-APR-01 (built): The panel polls `GET /v1/hitl` every 8 seconds and shows the count of waiting requests.
2. REQ-CON-APR-02 (built): Option-based decisions are two-step: clicking an option arms a confirmation callout restating the choice, and only the explicit Confirm posts the response.
3. REQ-CON-APR-03 (built): Requests with no fixed options (clarification, escalation) present a free-text answer field whose text is sent back to the asking agent as the decision.
4. REQ-CON-APR-04 (built): A successful response replaces the respond controls with a recorded confirmation stating whether the action will continue (approve-like) or will not run (otherwise), and reloads the list.
5. REQ-CON-APR-05 (built): A rejected response surfaces the kernel's faithful reason (403/409 body `reason`), for example self-approval and non-human-tier denials.
6. REQ-CON-APR-06 (built): The empty state reads as all-caught-up and explains when requests appear.
7. REQ-CON-APR-07 (audit-gap): The list shows only pending requests with no history of answered requests, no filtering by type or urgency, and no link from a request to the approval policy that raised it.

## A12. Run drawer (RunView)

Purpose: the single global run inspector keyed by `?run=<id>`, reachable from every surface showing a run id. Plane: global overlay. Gating: server-side; a 404 renders as not-in-scope.

1. REQ-CON-RUN-01 (built): The drawer is mounted once globally, opens whenever the route carries a run id, re-keys (resetting its stream) when navigating to a child run, closes on Esc, backdrop click or the close button, and traps focus while open restoring it to the opener.
2. REQ-CON-RUN-02 (built): The drawer shows three things: a summary from the audit-tree root (`GET /v1/audit/tree/{run_id}`: actor, tier badge, status counts, `total_cost_micros`), the live event stream (`GET /v1/runs/{id}/events?follow=1`) rendered with the identical chat turn renderer, and the full recursive execution tree (per node: run id, actor, tier badge, status counts, cost).
3. REQ-CON-RUN-03 (built): Sub-agent cards inside the drawer navigate the drawer down the run nesting; inline HITL cards are answerable inside the drawer.
4. REQ-CON-RUN-04 (built): Once the stream has settled and there is more than one event, a replay scrubber (range input, 1..N) reveals events up to an index with a step counter and an End control returning to the full view.
5. REQ-CON-RUN-05 (built): When both the tree fetch and the stream return 404 the drawer shows the single message "Run not found, or not in your visibility scope." rather than two raw errors.
6. REQ-CON-RUN-06 (built): Stream errors other than 404 render as "Stream: reason" while the tree still renders, and vice versa (degraded, not blank).
7. REQ-CON-RUN-07 (audit-gap): `workflow_step` events render in the drawer as the StepsCard but nothing links the drawer to the workflow run canvas for the same run.

## A13. Insight panel

Purpose: scoped cost rollup, budgets, runs list and audit search (SEC-33: scope-filtered server-side). Plane: Activity. Gating: none to view; audit export is author/admin gated server-side.

### A13.1 Parameter inventory

| Section | Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Cost | scope label | text | "all" or department list | n/a | `GET /v1/cost` `scope` |
| Cost | total + per-actor rows | money (micros/1e6, raw micros on hover) | n/a | n/a | `total_cost_micros`, `by_actor` |
| Budgets | rows | scope_type tag (tenant, department, workflow), id, window (run, daily, monthly), hard-stop badge, progress bar (worst of token/cost percentage; warn at 70, down at 90), token and cost spent/limit lines | n/a | n/a | `GET /v1/budgets` |
| Runs | rows | RunLink or "no run", intent, work-status badge, owner | n/a | n/a | `GET /v1/runs` |
| Audit search | Actor | select | "Any actor" + actor keys from the cost rollup | empty | `GET /v1/audit/search?actor=` |
| Audit search | Action | select | "Any action" + scoped verb ids | empty | `?verb=` |
| Audit search | Run id | text | run id | empty | `?run=` |
| Audit search | results table | columns #, When, Actor, Action, Status (AUDIT_STATUS badge), Run (RunLink) | n/a | n/a | `results` (server caps at last 500) |
| Export audit | button | author/admin only server-side | n/a | n/a | `POST /v1/audit/export` rendered as JSON |

1. REQ-CON-INS-01 (built): Cost renders the scoped total and per-actor spend in currency units (micros divided by one million, 2..4 decimal places) with the raw micros on hover, and names the caller's scope.
2. REQ-CON-INS-02 (built): Budgets renders each budget with scope type, window, hard-stop badge and an accessible progress bar (role progressbar with aria values) driven by the worst of token and cost utilisation, colour-shifting at 70% and 90%.
3. REQ-CON-INS-03 (built): Audit search sends only the non-empty filters of actor, verb and run, states the result count and scope, and explains that an empty result can be scoping rather than a bug.
4. REQ-CON-INS-04 (built): Audit export renders a denial (`error` field) as a warning notice, and a success as the JSON export body inline.
5. REQ-CON-INS-05 (built): Every run id in the runs list and the audit table is a RunLink into the run drawer.
6. REQ-CON-INS-06 (audit-gap): Budgets are read-only: no UI exists to create or edit a budget (the kernel exposes no budget-write route either, so this is paired UI plus kernel work).
7. REQ-CON-INS-07 (audit-gap): Audit search has no time-range filter, no pagination and no status filter, and export downloads render inline as JSON rather than as a file download.
8. REQ-CON-INS-08 (audit-gap): Cost has no time dimension (no per-day series, no window selector); it is a single lifetime rollup.

## A14. Eval panel

Purpose: no-escalation evaluation harness: create a case, run it under the initiator's grants, list runs. Plane: Activity. Gating: none (SEC-29 enforced kernel-side).

### A14.1 Parameter inventory

| Section | Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Create | Test | segmented | A skill, A workflow | skill | `POST /v1/eval/cases` `target_kind` |
| Create | Which one | select | skill ids (`GET /v1/skills`) or workflow ids (`GET /v1/workflows`) per kind | empty | `target_ref` |
| Create | Case id | text | any; blank auto-generates; set to overwrite | empty | `id` |
| Create | Input | textarea JSON | object | `{}` | `input` |
| Create | Forbidden permissions | chips (click to remove) + add-select of scoped verbs | verb ids | `["ticket.create"]` | `assertions.forbidden_grants` |
| Create | Assertions (Advanced) | textarea JSON | object; `forbidden_grants` is the supported key | `{"forbidden_grants": ["ticket.create"]}` | `assertions` |
| Create | Labels | text (comma list) | any | empty | `labels` |
| Run | Case | select | case ids derived from prior runs plus the just-created id | empty | `POST /v1/eval/run` `case_id` |
| Runs list | Filter by case | select | "All cases" + case ids | all | `GET /v1/eval/runs?case_id=` |

1. REQ-CON-EVAL-01 (built): The guided forbidden-grants chips and the raw assertions JSON are two views of the same object: toggling a chip rewrites `assertions.forbidden_grants` and editing the JSON updates the chips.
2. REQ-CON-EVAL-02 (built): Creating a case selects it in the run step ("It's selected below - run it next.") and reloads the runs list.
3. REQ-CON-EVAL-03 (built): Running a case renders passed/failed badge, score (0..1), run id, the run's `effective_grants` chips as the no-escalation evidence, and the full detail JSON.
4. REQ-CON-EVAL-04 (built): The runs list shows case id, run id, pass/fail badge and score per run, filterable by case id server-side.
5. REQ-CON-EVAL-05 (audit-gap): There is no list-cases read (kernel exposes none), so the case selector is reconstructed from run history and the last-created id, and a never-run case created in an earlier session is not offered.

## A15. Memory panel

Purpose: scoped memory surface: Recall, Browse, Remember, Ingest (SEC-31/40/42/43 kernel-side). Plane: Activity. Gating: none; disabled memory surfaces as "memory not enabled" (`binding_not_found`).

### A15.1 Parameter inventory

| Tab | Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|---|
| Recall | query | text (required) | plain language | empty | `POST /v1/memory/recall` `query` |
| Recall | How to search | select | graph_completion ("Connections (default)"), similarity | graph_completion | `mode` |
| Recall | Max results | numeric text | integer | `20` | `limit` |
| Browse | Show only | select | Any type, entity, relationship, summary, document_chunk | any | `GET /v1/memory/facts?kind=` |
| Browse | Forget | button per fact (confirm dialog) | n/a | n/a | `POST /v1/memory/forget` `{target: factId}` |
| Remember | content | textarea (required) | one plain-language fact | empty | `POST /v1/memory/remember` `content` |
| Remember | Type | select | entity, relationship, summary, document_chunk | entity | `kind` |
| Remember | Sensitivity | select | standard, sensitive (kept local-only) | standard | `data_class` |
| Ingest | Where it comes from | select | document, conversation, verb_result, feedback | document | `POST /v1/memory/ingest` `source_kind` |
| Ingest | Source reference | text | URL or identifier | empty | `source_ref` |
| Ingest | Items | textarea | one fact per line (trimmed, empties dropped) | empty | `items[]` |

1. REQ-CON-MEM-01 (built): Memory hosts four internal sub-tabs (Recall, Browse, Remember, Ingest) and every verb-route denial (`status` error/denied) renders inline, with `binding_not_found` translated to "memory not enabled".
2. REQ-CON-MEM-02 (built): Each fact renders as a card with kind tag, owner-scope badge, data-class badge (sensitive = red with a local-only tooltip), the content (text or JSON), and provenance (source kind, source ref, created at, and in Connections mode a hops badge plus the traversal path chips).
3. REQ-CON-MEM-03 (built): Recall requires a query, sends mode and parsed limit, and renders results with count or the calm "No facts in scope match this query." guidance.
4. REQ-CON-MEM-04 (built): Browse lists scope-filtered facts with a kind filter, shows the caller's visible scopes as chips, and its Forget button confirms, posts the erasure, reports facts removed and reloads.
5. REQ-CON-MEM-05 (built): Browse renders a `binding_not_found` fetch failure as the callout "Memory is not enabled for your org." instead of an error.
6. REQ-CON-MEM-06 (built): Remember requires content, sends kind and data class, shows a sensitive-data callout when sensitive is selected, and on success shows the owner scope and fact id chips.
7. REQ-CON-MEM-07 (built): Ingest splits the items textarea into one fact per non-empty line, posts them with source kind and ref, renders `ingestion_status`, `facts_added` and `screened`, and maintains an ingestions history table with columns source_kind, source_ref, owner_scope, status, facts_added, screened, created_at.
8. REQ-CON-MEM-08 (audit-gap): `MemoryRememberRequest` supports `owner_scope`, `source_kind`, `source_ref` and `relates_to`, and `MemoryForgetRequest` supports `source_ref` erasure, none of which the Remember/Browse UI exposes.

## A16. Me panel

Purpose: personal agent configure/invoke, a pointer to notification settings, and a legacy scoped memory query. Plane: Account. Gating: none (delegated-only kernel-side, SEC-30/31).

### A16.1 Parameter inventory

| Section | Field | Type | Default | Maps to |
|---|---|---|---|---|
| Personal agent | Runtime | text | `pi-worker` | `POST /v1/me/agent` `runtime` |
| Personal agent | Skills | text (comma list) + add-a-skill chips from `GET /v1/skills` | empty | `skills` |
| Ask your agent | Message | textarea (required) | empty | `POST /v1/me/agent/invoke` `message` |
| Notifications | Manage in Settings | button | n/a | navigates to /settings |
| Memory query | Type | text | empty | `POST /v1/memory/query` `kind` |

1. REQ-CON-ME-01 (built): Saving the personal agent posts runtime and skills and confirms with the agent id and owner.
2. REQ-CON-ME-02 (built): Asking the agent renders the delegated spawn result with `effective_grants` chips proving the cap to the owner's grants (SEC-30), and renders `denied`/`no_personal_agent` errors inline.
3. REQ-CON-ME-03 (built): Notifications are deliberately edited only in Settings; Me shows a pointer card, preventing two divergent editors.
4. REQ-CON-ME-04 (built): Memory query posts an optional kind filter to `POST /v1/memory/query` and lists items with kind, owner scope and content, plus the caller's scopes.
5. REQ-CON-ME-05 (audit-gap): Me's memory query duplicates the Memory panel's Browse with a weaker, provenance-free rendering over a different endpoint; the two SHOULD converge on one surface.

## A17. Settings panel

Purpose: account, appearance, notifications, developer/connections, personal agent view, privacy/data, security/sessions, organisation admin. Plane: Account. Gating: Organisation sub-tab offered to `org-admin` only; every gated call renders the server denial.

1. REQ-CON-SET-01 (built): Settings hosts eight internal sub-tabs (Account & Profile, Appearance & Accessibility, Notifications, Developer & Connections, Personal Agent, Privacy & My Data, Security & Sessions, Organisation), the last gated to org-admin, with fallback to Account when the active tab becomes hidden.

### A17.1 Account & Profile

| Field | Type | Default | Maps to |
|---|---|---|---|
| Identity card (read-only) | id, email, role tag, status badge, source IdP group, scope summary | n/a | `GET /v1/me/settings` `profile` |
| display name | text | seeded from settings/profile | `PUT /v1/me/settings` `settings.display_name` |
| locale | text (e.g. en-GB) | seeded | `settings.locale` |
| timezone | text (e.g. Europe/London) | seeded | `settings.timezone` |

2. REQ-CON-SET-02 (built): The identity card is read-only with copy explaining that role, scope and group come from the IdP; the preferences form seeds once from the server and saves display name, locale and timezone via `PUT /v1/me/settings` with a `{settings:{...}}` body.

### A17.2 Appearance & Accessibility

| Field | Type | Allowed values | Default | Maps to (server setting key) |
|---|---|---|---|---|
| theme | select | system, dark, light | system | `theme` |
| density | select | comfortable, compact | comfortable | `density` |
| font size | select | 0.9 (small), 1 (normal), 1.1 (large), 1.25 (extra large) | 1 | `font_scale` |
| reduced motion | select | off, on | off | `a11y.reduced_motion` |
| high contrast | select | off, on | off | `a11y.high_contrast` |

3. REQ-CON-SET-03 (built): Appearance changes preview live (data attributes, a `--font-scale` variable and a `reduce-motion` class on `<html>`), Save persists them via `PUT /v1/me/settings`, localStorage key `boltrig.appearance` mirrors them for instant-on, and server values adopted on load overwrite the local mirror (server is source of truth across devices).

### A17.3 Notifications

| Field | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| event type | server select | exact `catalogue.events` (`approval`, `escalation`, `hitl_expired`, `work_status`) | first available | `PUT /v1/me/notifications` `event_type` |
| channel | server select | enabled socket channels in `catalogue.transports` with a verified caller binding | first available | exact channel id in `channel` |
| target | server select | verified targets for the selected transport | first available | `target` |
| enabled | select | enabled, disabled | enabled | `enabled` |
| per-row Enable/Disable | button | toggles `enabled`, re-sending the row with its `id` | n/a | same endpoint |

4. REQ-CON-SET-04 (built): Notification routings and their last durable delivery state are listed from `GET /v1/me/notifications` and created or toggled via `PUT /v1/me/notifications` (the scope-locked, audited endpoint; the old `/v1/notifications/prefs` pair was removed). A static self-bound test uses `POST /v1/me/notifications/{id}/test`. Worker renders only the server catalogue; it does not offer in-app, email, arbitrary targets, or event names without a real producer/delivery path.

### A17.4 Developer & Connections

| Field | Type | Default | Maps to |
|---|---|---|---|
| token name | text (required) | empty | `POST /v1/me/tokens` `name` |
| scope | text (comma list, optional; subset of own grants) | empty | `scope` |
| ttl_days | numeric text (optional) | empty | `ttl_days` |
| Token list | rows: name, revoked badge, created/last-used/expires, scope chips, Revoke button (confirm) | n/a | `GET /v1/me/tokens`, `DELETE /v1/me/tokens/{id}` |
| Connection details | copy rows: MCP endpoint, REST base, auth, claude_code snippet, curl snippet, note | n/a | `GET /v1/me/connections` |

5. REQ-CON-SET-05 (built): Minting a token shows the secret exactly once in a warning box with a copy control and the message that it cannot be retrieved again (SEC-34/PAT-02), clears the form, and forces the token list to reload; listed tokens never include the secret or hash.
6. REQ-CON-SET-06 (built): Revoking a token requires a confirm dialog warning that clients using it stop working immediately.

### A17.5 Personal Agent, Privacy, Security

7. REQ-CON-SET-07 (built): The Personal Agent section shows the current agent (runtime, enabled badge, skill chips) from `GET /v1/me/agent` and reconfigures it via `POST /v1/me/agent`, with copy pointing invocation to the Me tab.
8. REQ-CON-SET-08 (built): Privacy & My Data loads `GET /v1/me/export` (own conversations, work items and settings only), offers a Download JSON file (`boltrig-export.json`), and deletes individual conversations via `DELETE /v1/me/conversations/{id}` after a confirm.
9. REQ-CON-SET-09 (built): Security & Sessions states that Boltrig stores no passwords and runs no MFA (IdP-owned, SET-71), lists sessions (`GET /v1/me/sessions`: client, revoked badge, created, last seen) with confirm-guarded revoke, re-uses the token list, and shows My activity as a table (seq, ts, verb, status, run_id) from `GET /v1/me/activity`.
10. REQ-CON-SET-10 (audit-gap): Activity rows show `run_id` as plain text, not as a RunLink into the run drawer.

### A17.6 Organisation (org-admin)

| Element | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| User row: role | select | the six console roles | user's role | `PATCH /v1/admin/users/{id}` `{role}` |
| User row: status | Activate/Deactivate button | active, deactivated | n/a | `{status}` |
| User row: scope | textarea JSON (departments / nouns / verbs visible) under "Edit scope" | object | user's scope | `{scope}` |
| Invite: email | text (required) | email | empty | `POST /v1/admin/invitations` `email` |
| Invite: role | select | the six console roles | agent | `role` |
| Invite: ttl_days | numeric text | number | `14` | `ttl_days` |
| Invitation rows | email, intended role, status, invited by, expires; Revoke button on pending | n/a | n/a | `GET /v1/admin/invitations`, `DELETE /v1/admin/invitations/{id}` |

11. REQ-CON-SET-11 (built): The user directory lists each user with email/id, display name, source and group, readable scope summary, inline role select (immediate PATCH), status badge and an activate/deactivate toggle, rendering per-row failures inline.
12. REQ-CON-SET-12 (built): A server denial of the directory or invitations (body without the `users`/`invitations` key) renders as "denied: reason" rather than an empty list.
13. REQ-CON-SET-13 (built): Invitations pre-stage a role for an SSO identity (no password created, SEC-35), and only pending invitations offer Revoke (confirm-guarded).

## A18. Admin panel (manifest config)

Purpose: edit manifest sections with revision history, rollback, export, and credential references. Plane: Account. Gating: tab for org-admin (cosmetic); server enforces.

### A18.1 Parameter inventory

| Control | Type | Allowed values | Default | Maps to |
|---|---|---|---|---|
| Section | select | privacy, network, hitl, models, notifications, personal_agents, evaluation, memory (each with a plain-language blurb) | privacy | `GET/PUT /v1/admin/config/{section}` |
| Settings (JSON) | textarea | JSON | section value, `{}` when unset | `PUT` body `{value}` |
| Save | button | n/a | n/a | records a revision |
| Revision history | rows: #id, version, rollback badge, actor, created_at, per-row Rollback (confirm) | n/a | n/a | `GET .../history`, `POST .../rollback` `{revision_id}` |
| Export manifest | button | n/a | n/a | `POST /v1/admin/config/export` rendered as JSON |
| Load credentials | button | n/a | n/a | `GET /v1/admin/credentials` (references only, never secrets, US-ADM-03) |

1. REQ-CON-ADM-01 (built): Selecting a section loads its live JSON (null pre-filled as `{}` so a first save is well-formed) and its revision history; a 403/denied response renders as "denied: reason" and hides the editor.
2. REQ-CON-ADM-02 (built): Save validates the editor as JSON client-side, puts `{value}`, confirms with the new revision id, and reloads history; Rollback is confirm-guarded, states that it changes live configuration and records a new revision, and repopulates the editor with the rolled-back value.
3. REQ-CON-ADM-03 (built): Credential references list adapter and credential ref only, with a tooltip stating the secret value is held server-side.
4. REQ-CON-ADM-04 (built): Export renders a re-importable manifest equivalent to the live configuration inline as JSON.
5. REQ-CON-ADM-05 (audit-gap): The section list is hard-coded in the UI; a manifest section unknown to `SECTION_INFO` cannot be edited even though the kernel route is generic over `{section}`.

## A19. Shared machinery (cross-cutting current behaviour)

1. REQ-CON-UX-01 (built): Every panel opens with a PageIntro (title, one-line lead, optional how-it-works aside, optional actions), and forms use the Field primitive (label + hint + example) with Select/Segmented controls over known value spaces instead of naked free text.
2. REQ-CON-UX-02 (built): Status vocabulary is centralised in glossaries (WORK_STATUS, AUDIT_STATUS, HITL_TYPE, HITL_URGENCY, CONSEQUENCE) and rendered via StatusBadge with plain-language label, colour class and tooltip, unknown values falling back to the raw token.
3. REQ-CON-UX-03 (built): SchemaForm renders typed inputs from a JSON-Schema `properties` map (enum select, boolean segmented, number input, string input; object/array deferred to the JSON view) with required-field markers, and is used by the Dev console and the canvas step inspector.
4. REQ-CON-UX-04 (built): Money is always rendered as micros divided by one million with the raw micros available on hover; run costs render as `<n>µ`.
5. REQ-CON-UX-05 (built): Every surfaced run id is rendered through RunLink so the run drawer is one click away, except the gaps explicitly listed (REQ-CON-SET-10).
6. REQ-CON-UX-06 (built): The panel ErrorBoundary catches a render crash and shows a recoverable message scoped to the panel, keyed so switching tabs resets it.
7. REQ-CON-UX-07 (built): No em or en dash characters appear in console copy; hyphens and " - " are used instead.

---

# PART B - KERNEL SURFACE AND CURRENT UI GAPS

## B1. Endpoint inventory and UI coverage

| Method + path | Consumed by | Notes |
|---|---|---|
| GET /healthz | shell HealthDot, Router | adapters map keyed `<tenant>/<adapterId>` |
| POST /v1/invoke | Dev console | union: ok / pending_human(202) / degraded(503) / denied(403) / error |
| POST /v1/chat (SSE) | Chat | ChatEvent frames |
| GET /v1/conversations, GET /v1/conversations/{id} | Chat, Settings privacy | 403 on foreign conversation (SEC-25) |
| GET /v1/capabilities[?noun=] | Router, Home, palette, Studio, Dev, Eval, Insight, canvas | `?noun=` unused by UI |
| POST /v1/spawn | Dev console | |
| GET /v1/hitl, POST /v1/hitl/{id}/respond | Approvals, Home, chat/run HITL cards | SEC-14 human-only, no self-approval |
| GET /v1/work[?status=] | Kanban, Home | `?status=` unused by UI |
| GET /v1/work/{item_id} | NOTHING | item + children (parent_id tree) + audit trail; see B2 |
| GET /v1/audit/tree/{run_id} | Run drawer | |
| GET /v1/runs/{run_id}/events[?follow=1] | Run drawer, run canvas | tenant-scoped (SEC-56) |
| POST /v1/mcp | NOTHING (documented via Settings connection snippets) | run-token and user-bearer doors |
| /v1/skills GET+POST, /v1/skills/{id}/test-spawn | Studio, Dev, Me, Eval | |
| /v1/nouns POST, /v1/verbs POST, /v1/verbs/{id}/binding POST | Studio | |
| /v1/adapters GET, /generate, /{id}/source, /{id}/activate | Studio, Dev | |
| /v1/mcp/servers POST | Studio | register only; no list/review/detail UI |
| /v1/workflows GET+POST, /{id} GET, /schedule, /trigger, /execute, /runs | Studio (form + canvas), Eval | |
| /v1/admin/config/{section} GET+PUT, /history, /rollback, /export, /v1/admin/credentials | Admin | |
| GET /v1/cost, GET /v1/budgets | Insight | read-only |
| GET /v1/capabilities/changelog | Router | author/admin gated server-side |
| GET /v1/audit/search, POST /v1/audit/export | Insight | export author/admin gated |
| GET /v1/runs | Insight, Home | |
| /v1/eval/cases POST, /v1/eval/run POST, /v1/eval/runs GET | Eval | no case-list read exists |
| /v1/me/agent POST+GET, /v1/me/agent/invoke | Me, Settings | |
| /v1/memory/query POST | Me | legacy duplicate of facts read |
| /v1/memory recall/remember/forget/ingest POST, facts/ingestions GET | Memory | |
| /v1/me settings GET+PUT, activity, export, conversations DELETE, tokens GET+POST+DELETE, connections, sessions GET+DELETE, notifications GET+PUT | Settings | |
| /v1/admin/users GET+PATCH, /v1/admin/invitations GET+POST+DELETE | Settings Organisation | |
| GET /v1/channels | NOTHING | admin (can_author) gated list |
| POST /v1/channels | NOTHING | connect: platform (webhook, msteams), name, signing_secret (stored kernel-side as a credential ref), config, enabled, unpaired_behavior; returns channel id + inbound_url |
| PATCH /v1/channels/{id} | NOTHING | configure: name, config, unpaired_behavior, enabled |
| DELETE /v1/channels/{id} | NOTHING | disconnect |
| POST /v1/channels/{id}/inbound | n/a (external webhook, signature-authenticated, no principal) | pairing-code consume path lives here |
| POST /v1/channels/{id}/pair | NOTHING | issues a one-time pairing code (shown ONCE), body: external_user_id, subject, role in {superadmin, admin, member}, ttl_minutes 1..60 (default 15); 5-attempt lockout |
| POST /v1/channels/{id}/bindings | NOTHING | direct admin bind: external_user_id, subject, role |
| GET /v1/channels/{id}/bindings | NOTHING | list: id, external_user_id, subject, role |
| DELETE /v1/channels/{id}/bindings/{binding_id} | NOTHING | path channel is authoritative |

## B2. Named gaps (current, testable statements)

1. REQ-CON-GAP-01 (audit-gap): No console surface consumes any `/v1/channels*` route, so channels can only be administered by hand-crafted HTTP calls.
2. REQ-CON-GAP-02 (audit-gap): No console surface consumes `GET /v1/work/{item_id}`, so the work-item children tree (`parent_id` nesting) and per-item audit trail are unreachable from the UI.
3. REQ-CON-GAP-03 (audit-gap): The `channel.send` verb (noun `channel`, consequence high, input `{channel_id (required), text (required), target?}`, rate limit 60/min/tenant) is invocable only through the generic Dev console; no channel-aware picker exists and the workflow canvas has no channel-send node affordance beyond the generic verb palette.
4. REQ-CON-GAP-04 (audit-gap): The canvas trigger nodes (chat, cron, webhook) are purely visual and serialise to nothing, so a webhook/channel trigger cannot be wired to a real channel.
5. REQ-CON-GAP-05 (audit-gap): `InvokeResult.status:"degraded"` is rendered honestly in the Dev console only; Kanban, RunView, Chat tool cards and the workflow run record have no degraded rendering distinct from ok.
6. REQ-CON-GAP-06 (audit-gap): Registered MCP servers cannot be listed, inspected or reviewed in the UI; only registration (Studio) exists, although the kernel treats generated/registered capability as inert-until-activated.
7. REQ-CON-GAP-07 (audit-gap): There is no UI for pagination anywhere; audit search truncates to the last 500 server-side with no cursor.

---

# PART C - TARGET REQUIREMENTS (should-do)

Target requirements are numbered within new areas. Each states its dependency; "buildable now" means the kernel surface already exists.

## C1. Channels admin page (new console page, Account or Capability plane)

Intent (corporate-brain, decision 0003): set up channels, administer them, pair senders, and use them in workflows (connect/disconnect/send, bindings, pairing codes).

1. REQ-CON-CHN-01 (corporate-brain): The console SHALL add a Channels page, gated to `can_author` roles (mirroring the kernel gate), listing the tenant's channels from `GET /v1/channels` with columns id, platform, name, transport, enabled badge and unpaired_behavior. [buildable now]
2. REQ-CON-CHN-02 (corporate-brain): The Channels page SHALL provide a Connect form posting `POST /v1/channels` with platform (select: webhook, msteams), name (required text), signing_secret (password field, write-only, never re-displayed), config (JSON, including `sender_field` and `outbound_url`), enabled (toggle, default on) and unpaired_behavior (select: reject (default), ignore, pair). [buildable now]
3. REQ-CON-CHN-03 (corporate-brain): On successful connect the page SHALL display the returned channel id and the absolute inbound webhook URL (`/v1/channels/{id}/inbound`) with a copy control. [buildable now]
4. REQ-CON-CHN-04 (corporate-brain): Each channel row SHALL offer Configure (PATCH of name, config, unpaired_behavior, enabled) and a confirm-guarded Disconnect (DELETE). [buildable now]
5. REQ-CON-CHN-05 (corporate-brain): A channel detail view SHALL list bindings from `GET /v1/channels/{id}/bindings` (external_user_id, subject, role) with a confirm-guarded per-row unbind (DELETE .../bindings/{binding_id}). [buildable now]
6. REQ-CON-CHN-06 (corporate-brain): The detail view SHALL provide a Bind sender form posting external_user_id (required), subject (required) and role (select: superadmin, admin, member; default member) to `POST /v1/channels/{id}/bindings`. [buildable now]
7. REQ-CON-CHN-07 (corporate-brain): The detail view SHALL provide an Issue pairing code form (external_user_id, subject, role, ttl_minutes numeric 1..60 default 15) posting to `POST /v1/channels/{id}/pair` and SHALL display the returned code exactly once with a copy control and the warning that it is never shown again (mirroring the PAT secret pattern). [buildable now]
8. REQ-CON-CHN-08 (corporate-brain): The pairing UI SHALL state the pairing contract in plain language: 15-minute default expiry, five wrong attempts lock the code, single use. [buildable now]
9. REQ-CON-CHN-09 (corporate-brain): The Channels page SHALL provide a Send test message action per enabled channel that invokes the governed `channel.send` verb via `POST /v1/invoke` (noun `channel`, verb `channel.send`, params channel_id + text + optional target) and renders the full result union including the pending_human pause and the `{status:"queued"}` no-outbound-url case as distinct states. [buildable now]
10. REQ-CON-CHN-10 (corporate-brain): Channel admin actions surfaced in the UI SHALL be traceable: each mutating action's result SHOULD link to its audit row via the Insight audit search pre-filtered to verb `channel.*`. [buildable now]
11. REQ-CON-CHN-11 (corporate-brain): Socket-transport platforms (Slack/Discord class) SHALL render as "queued for sidecar delivery" wherever a send result reports `status:"queued"`, honestly distinguishing Phase-1 queueing from delivery. [needs: socket sidecar (Phase 2) for actual delivery; the honest label is buildable now]

## C2. Hierarchical work board (Linear-lookalike)

Intent (corporate-brain, #74): epic/story/task-style nesting via `parent_id`; three modes of work; per-ticket audit log via `GET /v1/work/{id}`.

1. REQ-CON-WRK-01 (corporate-brain): The Kanban page SHALL become a work board with three view modes selectable by segmented control: Project (convergent goal list grouped by parent), Linear (operational state-machine list ordered by status progression), and Board (the existing non-linear kanban lanes). [buildable now]
2. REQ-CON-WRK-02 (corporate-brain): In every mode, items with children (any item referenced by another's `parent_id`) SHALL render as expandable parents showing a child count and roll-up status, nesting to arbitrary depth. [buildable now]
3. REQ-CON-WRK-03 (corporate-brain): Clicking any work item SHALL open a work-item detail view backed by `GET /v1/work/{item_id}` showing the item fields (id, intent, status, confidence, convergent, owner_member, source, parent_id, hatchet_run_id, on_behalf_of), its children as a tree, and its audit trail. [buildable now]
4. REQ-CON-WRK-04 (corporate-brain): The per-ticket audit trail SHALL render each event with ts, actor, actor_tier, noun.verb, status badge (AUDIT_STATUS glossary) and an expandable detail JSON, newest last, up to the endpoint's 200-event cap with the cap stated. [buildable now]
5. REQ-CON-WRK-05 (corporate-brain): The detail view SHALL deep-link (`#/kanban/<itemId>` or equivalent) so a work item is addressable, and a child row SHALL navigate the detail view to that child. [buildable now]
6. REQ-CON-WRK-06 (corporate-brain): A 404 from the detail endpoint SHALL render as "not found or not in your visibility scope" (department scoping makes out-of-scope items simply absent). [buildable now]
7. REQ-CON-WRK-07 (corporate-brain): The board SHALL offer client-side filters for owner, source, convergent and free-text intent, and a server-side status filter using `GET /v1/work?status=`. [buildable now]
8. REQ-CON-WRK-08 (corporate-brain): The Project mode SHALL visually distinguish convergent items (goal-like, settling on a single answer) from non-convergent ones using the existing convergent flag. [buildable now]
9. REQ-CON-WRK-09 (corporate-brain): Status changes and re-parenting from the board are OUT of scope until the kernel exposes a governed work-item write verb; the UI SHALL NOT fake local mutation. [needs: kernel work-item write surface]

## C3. Workflow canvas: channel triggers and channel.send

1. REQ-CON-WFT-01 (corporate-brain): The canvas trigger palette SHALL add a "channel" trigger node that binds to a real channel chosen from `GET /v1/channels`, rendering the channel name and platform on the node. [buildable now for display; needs: kernel trigger-binding persistence for the binding to be executable]
2. REQ-CON-WFT-02 (corporate-brain): Trigger nodes carrying a channel binding SHALL serialise into the workflow definition (a `triggers` array alongside `steps`) instead of being dropped, once the kernel definition schema accepts triggers. [needs: engine definition-schema beat for triggers]
3. REQ-CON-WFT-03 (corporate-brain): The verb palette SHALL present `channel.send` as a first-class channel node whose inspector offers a channel select (from `GET /v1/channels`) for `channel_id`, a text field for `text` and an optional `target`, rather than a raw JSON params box. [buildable now]
4. REQ-CON-WFT-04 (corporate-brain): A `channel.send` step node SHALL carry the high-consequence marker and copy stating it pauses for approval by default (SEC-39). [buildable now]

## C4. Degraded honesty (Kanban / RunView / everywhere)

Intent (corporate-brain): surface degraded results honestly; an engine-level degraded flag is being added.

1. REQ-CON-DEG-01 (corporate-brain): Chat and Run drawer tool cards SHALL render a distinct `degraded` status badge (amber) when a tool result reports degraded, separate from ok and error. [needs: engine beat emitting degraded on tool_result events]
2. REQ-CON-DEG-02 (corporate-brain): Work items whose latest run contains degraded activity SHALL carry a visible "degraded" marker on their board card and in the work-item detail header. [needs: engine degraded flag on the work item or run summary]
3. REQ-CON-DEG-03 (corporate-brain): The Run drawer summary SHALL surface the degraded count from the audit-tree root `statuses` map as an explicit amber chip whenever `statuses.degraded > 0`, not merely inside the `s:n` text. [buildable now]
4. REQ-CON-DEG-04 (corporate-brain): The workflow run canvas and run record SHALL render a step that completed via a degraded fallback in the degraded colour, distinct from ok. [needs: interpreter emitting degraded step status]
5. REQ-CON-DEG-05 (corporate-brain): Degraded output SHALL always be accompanied by the plain-language notice that the output is best-effort because a backing service was unhealthy (extending the existing Dev console copy to every surface). [buildable with DEG-01..04]

## C5. Insight: cost true-up

1. REQ-CON-COST-01 (corporate-brain): The Insight cost card SHALL distinguish estimated from trued-up (provider-reconciled) cost per actor, showing both values and a reconciliation badge when they diverge. [needs: kernel cost true-up fields]
2. REQ-CON-COST-02 (corporate-brain): Insight SHALL add a cost-over-time view (per day, selectable window) so spend trends are visible, replacing the single lifetime rollup. [needs: kernel time-bucketed cost read]
3. REQ-CON-COST-03 (corporate-brain): Every run drawer cost figure SHALL state whether it is estimated or trued-up once the engine carries the distinction. [needs: kernel cost true-up fields]

## C6. Run replay and trust timeline

1. REQ-CON-RPL-01 (idea-batch): The Run drawer SHALL extend the existing replay scrubber into a trust timeline: stepping the scrubber SHALL highlight the corresponding node of the audit execution tree chronologically, so the tree and the event log stay in lockstep at every replay position. [buildable now]
2. REQ-CON-RPL-02 (idea-batch): The replay scrubber SHALL display the timestamp of the currently revealed event when event frames carry timestamps. [needs: run event frames carrying ts]
3. REQ-CON-RPL-03 (idea-batch): Replay SHALL be reachable for closed runs from every RunLink without special mode switching (the snapshot stream already ends and arms replay; this behaviour SHALL be preserved as a contract). [buildable now]

## C7. "Why did this happen" provenance links

1. REQ-CON-WHY-01 (idea-batch): Every surfaced action (tool card, audit row, work-item trail entry) SHALL offer a "why" affordance resolving to the exact grant pattern that authorised it, the approval (HITL response id and approver) when one gated it, and the audit row (seq) recording it. [needs: kernel decision-basis fields on audit events]
2. REQ-CON-WHY-02 (idea-batch): For HITL-gated actions the why-view SHALL link to the answered approval including the approver's notes, using the existing hitl request/response records. [needs: kernel read for answered HITL by id]
3. REQ-CON-WHY-03 (idea-batch): The why-view SHALL render `effective_grants` alongside the matched grant so a viewer can see both the ceiling and the specific pattern that matched. [needs: kernel decision-basis fields]

## C8. Approval policies and delegation

1. REQ-CON-POL-01 (idea-batch): The console SHALL provide an approval-policy editor (Admin plane) declaring which verbs or consequence levels require HITL and who may approve, rendered as structured controls over the manifest `hitl` section rather than raw JSON. [buildable now over `PUT /v1/admin/config/hitl`; needs: agreed hitl section schema]
2. REQ-CON-POL-02 (idea-batch): The policy editor SHALL support delegated approval: naming subjects or roles who may approve on another's behalf, with the delegation recorded and shown on the answered approval. [needs: kernel delegation model in the HITL service]
3. REQ-CON-POL-03 (idea-batch): The Approvals panel SHALL show, per request, which policy rule raised it once the kernel attaches the rule reference to the HITL request. [needs: kernel policy-reference on HITL requests]
4. REQ-CON-POL-04 (idea-batch): Policy changes SHALL ride the existing revision history and rollback of the config section, and the editor SHALL surface that history inline. [buildable now]

## C9. Dry-run mode

1. REQ-CON-DRY-01 (idea-batch): The Dev console invoke form and the workflow Run control SHALL offer a dry-run toggle that executes in a no-side-effects mode and renders what WOULD happen (the resolved binding, the grant decision, the would-be HITL pause, and the simulated output) clearly watermarked as a dry run. [needs: kernel dry-run capability, engine follow-on]
2. REQ-CON-DRY-02 (idea-batch): Dry-run results SHALL be visually unambiguous (distinct banner and badge) so a simulated success can never be mistaken for a real one. [needs: DRY-01]
3. REQ-CON-DRY-03 (idea-batch): Dry runs SHALL be audited as dry runs and excluded from cost rollups, and the UI SHALL state this. [needs: kernel dry-run capability]

## C10. MCP catalog

1. REQ-CON-MCP-01 (idea-batch): The console SHALL provide an MCP catalog view listing registered external MCP servers with their tools, activation state and health, extending the inert-until-reviewed flow that exists for generated adapters. [needs: kernel list/detail reads for MCP servers and their tools]
2. REQ-CON-MCP-02 (idea-batch): The catalog SHALL support review-and-activate per server (mirroring adapter activation with a named reviewer) and show which verbs each server contributes. [needs: kernel MCP activation surface]
3. REQ-CON-MCP-03 (idea-batch): Registering an MCP server (existing Studio form) SHALL move into or link from the catalog so registration, review and activation are one flow. [buildable once MCP-01 exists]

## C11. Budgets UI (write side)

1. REQ-CON-BUD-01 (idea-batch): Insight budgets SHALL gain create and edit forms for per-scope budgets: scope_type (tenant, department, workflow), scope id, window (run, daily, monthly), token_limit, cost_limit_micros (entered in currency units), and hard_stop toggle. [needs: kernel budget write routes]
2. REQ-CON-BUD-02 (idea-batch): A budget at or past its hard-stop SHALL render an explicit "stopped" state distinct from the 90% warning colour, with copy explaining that spending is blocked. [buildable now for display of full bars; the stopped semantic needs the kernel to expose the tripped state]
3. REQ-CON-BUD-03 (idea-batch): Budget burn-down SHALL be visible over time (spend curve against the window), not only as a single utilisation bar. [needs: kernel time-bucketed spend read]

## C12. Capability changelog view

1. REQ-CON-LOG-01 (idea-batch): The capability changelog SHALL become a full view (not only the 12-row Router card) with filters for actor, action and ref, over `GET /v1/capabilities/changelog`. [buildable now]
2. REQ-CON-LOG-02 (idea-batch): The changelog view SHALL be offered only to roles that pass the server gate (author/admin), resolving REQ-CON-RTR-09. [buildable now]
3. REQ-CON-LOG-03 (idea-batch): Each changelog row SHALL link to the affected object where one exists (a verb to the Router entry, a workflow to the Studio, an adapter to the inventory). [buildable now]

## C13. Agent org view

1. REQ-CON-ORG-01 (idea-batch): The console SHALL render the manifest agent hierarchy (CoS, departments, heads, workers) as an org chart using the established React Flow canvas pattern. [needs: kernel read exposing the org/manifest hierarchy]
2. REQ-CON-ORG-02 (idea-batch): Org chart nodes SHALL carry live status (active runs, last activity, health) and click through to the relevant runs in Insight. [needs: kernel per-agent status read]
3. REQ-CON-ORG-03 (idea-batch): The org view SHALL be read-only in its first release; org mutation stays in the manifest/Admin flow. [needs: ORG-01]

## C14. Saved views and shareable deep links

1. REQ-CON-VIEW-01 (idea-batch): Kanban/work-board and Insight filter state SHALL serialise into the URL hash query so any filtered view is a shareable deep link, consistent with the existing `?run=` pattern. [buildable now]
2. REQ-CON-VIEW-02 (idea-batch): Users SHALL be able to save named views (a name plus the serialised filter state) persisted as per-user settings via the existing `PUT /v1/me/settings`, and recall them from a view switcher on the page. [buildable now]
3. REQ-CON-VIEW-03 (idea-batch): Opening a deep link whose filters yield nothing in the viewer's scope SHALL render the standard scoped-empty explanation, never an error. [buildable now]

## C15. Command palette (status)

1. REQ-CON-PALT-01 (idea-batch): The command palette is BUILT; its current behaviour is specified in A4 (REQ-CON-PAL-01..05) and the one enhancement carried forward is REQ-CON-PAL-06 (verb pre-selection deep link).

---

# Appendix - test hooks

- The dev identity mechanism (A1.1) makes every role/gating requirement testable by header manipulation alone.
- SSE requirements (A2, A9, A12) are testable against the kernel's real streams; the frame parser tolerances (CRLF, multi-line data, trailing frame) are unit-testable in isolation.
- Every `tolerateStatus` write path is testable by asserting the inline rendering of `{status:"denied", reason}` for a non-author identity.
- Round-trip requirements (A7.5 canvas serialise/load, A17.2 appearance settings keys) are property-testable: load(save(x)) must equal x for the steps contract, and the five appearance keys must match `theme`, `density`, `font_scale`, `a11y.reduced_motion`, `a11y.high_contrast`.
