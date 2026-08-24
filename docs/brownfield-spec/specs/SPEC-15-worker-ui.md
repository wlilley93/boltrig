---
area: 15 The worker UI, the primary surface
id-block: BT-REQ-1500 to BT-REQ-1599
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec author, area 15
date: 2026-08-24
---

# SPEC 15: The Worker UI, the primary surface

## Bound of this reading

Measured scale of the area in the pinned tree: `apps/worker` holds 461 `.ts` and
`.tsx` files totalling 107,124 lines, of which `apps/worker/src` holds 330
non-test modules totalling 68,446 lines; `apps/worker/tests` plus the five
in-tree `*.test.tsx` files hold 125 test files with 1,092 `it`/`test` cases in
178 `describe` blocks; `apps/worker/src` holds 42 CSS files totalling 12,817
lines; `apps/worker/src-tauri/src` holds 14 Rust files totalling 8,605 lines.
(`REFERENT.md` quotes 427 files and 99,610 lines for this directory; the
difference is `find` scope, not a disagreement about the tree.)

**Read in full**: `src/main.tsx`, `src/App.tsx`, `src/routes.ts`,
`src/useRouteSelection.ts`, `src/useMediaQuery.ts`, `src/client.ts`,
`src/apiOrigin.ts`, `src/theme.ts`, `src/shortcuts.ts`, `src/onboarding.ts`,
`src/settingsSections.ts`, `src/desktop.ts`, `src/desktopApiTransport.ts`,
`src/desktopTrust.ts`, `src/desktopDownload.ts`, `src/components/AuthGate.tsx`,
all nine files under `src/components/auth/`, all twelve files under
`src/components/shell/`, `src/components/WorkerGlobalContext.tsx`,
`src/components/ExactApprovalFinalizer.tsx`, `src/components/AccountView.tsx`,
`src/components/integrations/capabilityTabs.ts`,
`src/components/integrations/IntegrationsSurface.tsx`,
`src/components/RoutinesView.tsx`, `src/components/browser/BrowserWorkspace.tsx`,
`src/components/Views.tsx`, `apps/worker/vite.config.ts`,
`apps/worker/nginx.conf`, `apps/worker/Dockerfile`, `apps/worker/index.html`,
`apps/worker/package.json`, `apps/worker/tsconfig.json`, `apps/worker/README.md`,
`apps/worker/scripts/require-desktop-origin.mjs`,
`apps/worker/familiar-island/vite.config.ts`, decision 0021 in full, and the
Decision 0027 sections that amend it.

**Sampled with depth on the load-bearing paths**: `src/components/ChatView.tsx`
(1,324 lines; lines 1 to 900 read line by line, the render tail read at the
continuity and composer call sites); `src/components/VoiceCall.tsx` (1,525
lines; the whole start/connect/reconnect/teardown path, `websocketUrl`,
`socketCloseError`, the status vocabulary); `src/localAgentClient.ts` (380 lines,
top-level surface plus the storage and projection functions);
`sdks/web/src/client.ts` at its transport core, `followConversation`,
`streamChat` and `pumpSseFrames`.

**Sampled at exported surface plus one representative body**: `ParityViews.tsx`,
`OperationsView.tsx`, `ChannelsView.tsx`, `AutomationView.tsx`,
`IntegrationsView.tsx`, `EvaluationsView.tsx`, `OrganisationView.tsx`,
`BuildView.tsx`, `knowledge/KnowledgeView.tsx`, `Shell.tsx`,
`SettingsSurface.tsx`, `settings/*`, `chat/*`, `onboarding/*`, `routine/*`,
`build/*`.

**Enumerated mechanically rather than read**: every `client.<method>(` call site
in `apps/worker/src`, grouped per file; every module with no importer; every
`import.meta.env.*` read; every `localStorage`/`sessionStorage` user; every
`createContext` call; every direct `fetch(` call.

**NOT read**: the shader, renderer and tuning modules under `src/components/canvas/`,
`familiar/`, `jarvis/`, `ultron/`, `colossus/` and `src/bundles/` beyond their
registration surface, which area 14 owns; `src-tauri/src/*.rs` beyond the command
names the web layer invokes; `src/styles.css` beyond its first 90 lines and
targeted rule lookups; the per-view CSS beyond the parity tests that assert on it;
`tests/visual/` beyond its file list and the dev-only Vite plugins that serve it.
No claim here concerns shader output, native Rust behaviour, or rendered pixels.

Nothing outside that bound is asserted.

---

## 2. Purpose

The Worker is Boltrig's only first-party browser surface and the payload the
Tauri desktop packages: one React 19 single-page application, hash-routed over
sixteen top-level routes, that renders conversations, live turns, approvals,
artifacts and every governed control plane the kernel exposes. It owns
presentation and nothing else: it holds no authority, no credential, no model
route and no workflow state, and reaches the kernel only through the typed
`@wlilley93/boltrig-web-sdk` client over same-origin HTTP, server-sent events
and one WebSocket for live voice. Its second job is honesty: where a server
capability is absent, uncertified or degraded, the surface is required to draw
a typed unavailable state rather than a control that pretends to work.

## 3. Boundaries

**What this area owns.** The route table and hash router; the shell frame,
navigation rail and command palette; the auth gate and its screens; the
onboarding gate; every route view and its data fetching; the chat transcript,
composer, task inspector and live-turn projection; the realtime voice call
surface and its media graph; the settings surface and its row kit; the theme,
appearance and character bootstraps; the desktop transport shims; the CSS token
layer and the nginx image that serves the built bundle.

**What it must not touch, and the rule.**

- **No authority, credential, connector execution, workflow state, memory truth,
  artifact production or model routing.** Decision 0021 at
  [`docs/decisions/0021-worker-primary-surface-and-realtime-voice.md:37`](../../../docs/decisions/0021-worker-primary-surface-and-realtime-voice.md) `does not own authority, credentials, connector execution,`.
  Enforced as a static shipment boundary by
  [`tests/security/test_worker_surface_boundary.py:58`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_ships_no_openworker_agent_server_or_provider_secret_path`.
- **Exactly one network client.** Every backend call goes through the single
  `BoltrigClient` instance at
  [`apps/worker/src/client.ts:32`](../../../apps/worker/src/client.ts) `export const client = new BoltrigClient({`.
  There is exactly ONE direct `fetch(` in `apps/worker/src`, the optional
  self-hosted TTS interrupt at
  [`apps/worker/src/components/voiceBargeInGraph.ts:282`](../../../apps/worker/src/components/voiceBargeInGraph.ts) `void fetch(`,
  inert unless `VITE_SELF_HOSTED_TTS_ORIGIN` is set (bounded: `rg -n "\bfetch\(" src`
  and `rg -n "XMLHttpRequest" src` over `apps/worker/src`, 2026-08-24, pinned
  tree; the second returns nothing).
- **No second HTML entrypoint in the shipped bundle.** `index.html` is the only
  Vite input; the shader bench and parity harness pages under `tests/visual/`
  are served only by dev-mode plugins declared
  [`apps/worker/vite.config.ts:76`](../../../apps/worker/vite.config.ts) `apply:`.
- **No raw HTML into the transcript.** Markdown is rendered by `react-markdown`
  with `remark-gfm` only and no `rehype-raw`, at
  [`apps/worker/src/components/chat/OrderedWorkTranscript.tsx:128`](../../../apps/worker/src/components/chat/OrderedWorkTranscript.tsx) `<ReactMarkdown remarkPlugins={[remarkGfm]}>`.
  There is no `dangerouslySetInnerHTML` in `apps/worker/src` (bounded: `rg -n
  "dangerouslySetInnerHTML" src`, 2026-08-24, pinned tree).
- **The desktop webview may supply no executable, argv, cwd or native path.**
  The desktop HTTP shim refuses anything that is not the configured origin plus
  a `/v1` path, at
  [`apps/worker/src/desktopApiTransport.ts:130`](../../../apps/worker/src/desktopApiTransport.ts) `url.origin !== configured`,
  throwing `desktop_api_path_invalid`. Bound by SEC-WRK-01.
- **The retired Operator path must stay 404 rather than fall through to the SPA**,
  at [`apps/worker/nginx.conf:106`](../../../apps/worker/nginx.conf) `location = /operator { return 404; }`.

**One import direction crosses the app boundary.** `src/styles.css` imports three
token files from the repository's `docs/` tree, at
[`apps/worker/src/styles.css:1`](../../../apps/worker/src/styles.css) `@import`.
The Dockerfile copies exactly those three files into the build context, at
[`apps/worker/Dockerfile:32`](../../../apps/worker/Dockerfile) `COPY docs/design/imported/tokens/colors.css`,
so image build and source agree. Nothing else in `apps/worker/src` reads `docs/`
(bounded: `rg -n "docs/design" src`, 2026-08-24, pinned tree).

## 4. Objects and contracts

### 4.1 The route table

There is no router library, no `react-router`, and no history API use. `WorkerRoute`
is a closed union of sixteen string ids plus a `Set` of the same sixteen values, and
any hash that does not name one of them resolves to `chat`, at
[`apps/worker/src/routes.ts:19`](../../../apps/worker/src/routes.ts) `const routes = new Set<WorkerRoute>([`
and [`apps/worker/src/routes.ts:40`](../../../apps/worker/src/routes.ts) `return routes.has(candidate) ? candidate :`.

A hash has at most two meaningful segments, `#/<route>` and `#/<route>/<selectionId>`.
A third segment invalidates the selection, at
[`apps/worker/src/routes.ts:52`](../../../apps/worker/src/routes.ts) `if (route !== expectedRoute || !encodedId || extra) return null;`,
and a selection id is capped at 256 characters after `decodeURIComponent`, at
[`apps/worker/src/routes.ts:55`](../../../apps/worker/src/routes.ts) `return id && id.length <= 256 ? id : null;`.
Navigation is a hash write, at
[`apps/worker/src/routes.ts:68`](../../../apps/worker/src/routes.ts) `window.location.hash = routeHash(route, selectionId);`,
and every listener is a `hashchange` handler.

The sixteen routes are split into a lazily-imported core set of eight and a
supporting set of eight, at
[`apps/worker/src/components/shell/AppRouteSurface.tsx:64`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `const CORE_ROUTES = new Set<WorkerRoute>([`.

### 4.2 Screen and route inventory

Each row was derived by reading the two switch statements in
`apps/worker/src/components/shell/AppRouteSurface.tsx` and then enumerating every
`client.<method>(` call site in the named component and its imports.

| hash | component mounted | selection segment | what it shows | SDK methods it calls |
|---|---|---|---|---|
| `#/home` | `HomeView` in `components/OperationsView.tsx`, or `MobileToday` under 640px | none | pending approvals, recent runs, spend, runtime posture, four pulse cards linking to runs and Operations | `consoleOverview`; phone variant `conversations`, `hitl`, `respondHitl` |
| `#/chat[/<conversationId>]` | `ChatView` in the browser, `LocalChatView` when a Tauri runtime is present | conversation id | transcript, live turn, composer, queued steers, subagent tabs, task inspector, artifacts, voice dock, Familiar Stage | `streamChat`, `followConversation`, `conversation`, `conversations`, `artifacts`, `downloadArtifact`, `cancelRun`, `respondHitl`; from its children `namedAgents`, `chatConfig`, `chatModelChoices`, `reorderConversationQueue`, `familiarPhenotype`, `meSettings`, `capabilities`, `invoke`, `auditTree`, `runTopology`, `runEvents`, `revertRun`, `runEffects`, `hitl`, `invokeApprovalState` |
| `#/runs[/<runId>]` | `RunsView` in `components/ParityViews.tsx` | run id | cursor-paged run list with five filters, cancel, audit tree, subagent topology | `runs`, `auditTree`, `runTopology`, `cancelRun` |
| `#/work[/<workId>]` | `WorkView` in `components/ParityViews.tsx` | work id | project, linear and board modes over canonical work | `work`, `workDetail`, `createWork`, `assignWork`, `transitionWork`, `reparentWork` |
| `#/agents[/<name>]` | `AgentsView` in `components/ParityViews.tsx` | capability name | agent capability profiles, permanent fleet topology editor, profile editor | `agentCapabilities`, `retireAgentCapability`, `restoreAgentCapability`, `permanentFleet`, `applyPermanentFleet`, `modelEndpoints`, `invoke` |
| `#/account` | `SettingsView section=you`, NOT `AccountView` | none | the You settings pane | `meSettings`, `putMeSettings`, `logout`, `currentOrg`, `workspaces`, `meNotifications` |
| `#/build[/<tab>]` | `BuildView` | `actions`, `skills`, `run`, `registry`, `adapters`, `models`, `routing` | capability registry, skills, capability runner, adapters and MCP servers, model endpoints, spawn rules | `verbs`, `nouns`, `verb`, `noun`, `upsertVerb`, `upsertNoun`, `archiveVerb`, `archiveNoun`, `restoreVerb`, `restoreNoun`, `setBinding`, `skills`, `skill`, `upsertSkill`, `archiveSkill`, `restoreSkill`, `testSpawn`, `capabilities`, `invoke`, `invokeApprovalState`, `adapters`, `adapterSource`, `generateAdapter`, `activateAdapter`, `deactivateAdapter`, `deleteAdapter`, `registerMcpServer`, `mcpServers`, `mcpServer`, `probeMcpServer`, `updateMcpServer`, `activateMcpServer`, `deactivateMcpServer`, `retireMcpServer`, `restoreMcpServer`, `deleteMcpServer`, `modelEndpoints`, `modelEndpoint`, `modelPolicy`, `retireModelEndpoint`, `restoreModelEndpoint`, `spawnRules`, `simulateSpawnRules`, `capabilityChangelog`, `agentCapabilities`, `approvalPosture`, `hitlPolicy` |
| `#/browser` | `components/browser/BrowserWorkspace.tsx` | none | shared cloud browser: address bar, frame canvas, click and type controls, DOM inspector | `invoke` only, dispatching `browser.frame.read`, `browser.tabs.list`, `browser.inspect` and the interaction verbs |
| `#/channels` | `ChannelsView`, 2,141 lines | none | channel connect, configure, pair, bind, gateway session tokens, delivery receipts and retry | `channels`, `connectChannel`, `configureChannel`, `disconnectChannel`, `pairChannel`, `bindChannel`, `deleteChannelBinding`, `channelBindings`, `channelDeliveries`, `retryChannelDelivery`, `channelGatewaySession`, `channelPairFinalizations`, `invoke`, `invokeApprovalState` |
| `#/evaluations[/<caseId>]` | `EvaluationsView` | eval case id | eval fixtures, run, durable history, archive and restore | `evalCases`, `createEvalCase`, `archiveEvalCase`, `restoreEvalCase`, `runEval`, `evalRuns` |
| `#/automations[/<workflowId>]` | `RoutinesView`, NOT `AutomationView` | ignored by `RoutinesView` | plain-language routine goal, companion choice, manual or daily schedule | `workflows`, `workflow`, `upsertWorkflow`, `scheduleWorkflow`, `unscheduleWorkflow`, `triggerWorkflow` |
| `#/knowledge[/<assetId>]` | `components/knowledge/KnowledgeView.tsx`, re-exported through `ParityViews` | knowledge asset id | asset list, cited search, upload, download original, erase, Remembers tab | `knowledgeAssets`, `knowledgeAsset`, `knowledgeSearch`, `knowledgeOriginal`, `uploadKnowledge`, `eraseKnowledgeAsset`, `memoryFacts`, `memoryForget` |
| `#/memory[/<factId>]` | `MemoryView` in `components/ParityViews.tsx` | fact id | browse, recall, remember, ingest and review tabs over durable memory | `memoryFacts`, `memoryFact`, `memoryRecall`, `memoryRemember`, `memoryImprove`, `memoryIngest`, `memoryIngestions`, `memoryForget`, `memoryCandidates`, `memoryCandidateReview`, `memoryTimeline`, `respondHitl` |
| `#/integrations[/<tab>]` | `components/integrations/IntegrationsSurface.tsx`; `connections` is the default and clears the segment | `capabilities`, `rules`, `review` | provider catalogue and connections, capability catalogue, routing rules, capability review queue | `integrationCatalogue`, `integrationConnections`, `integrationConnectionHealth`, `startIntegrationOAuth`, `submitIntegrationSecret`, `disconnectIntegration`, `addons`, `mcpServers`, `capabilityCatalogue`, `routingPolicies`, `capabilityBindings`, `invoke`, `memberIntegrationConnections`, `revokeMemberIntegrationConnection` |
| `#/organisation` | `OrganisationView` | none | three tabs: overview policy, workspaces, administration | `currentOrg`, `meSettings`, `updateCurrentOrg`, `workspaces`, `workspaceMembers`, `createWorkspace`, `updateWorkspace`, `addWorkspaceMember`, `removeWorkspaceMember`, `adminUsers`, `adminInvitations`, `orgMembers`, `createInvitation`, `revokeInvitation`, `patchUser` |
| `#/settings[/<section>]` | `SettingsView` on desktop widths, `MobileSettings` under 640px, `settings/SearchResults` while a settings query is non-empty | one of fifteen `SettingsSection` ids | one calm row surface per section | `meSettings`, `putMeSettings`, `budgets`, `cost`, `health`, `readiness`, `hitl`, `sensing`, `putSensingCamera`, `putSensingPresence`, `deleteSensingEnrollment`, `knowledgeProviders`, `setKnowledgeProvider`, `auditSearch`, `currentOrg`, `updateCurrentOrg`, `bifrostModels`, `chatModelChoices`, `modelEndpoint`, `modelEndpoints`, `retireModelEndpoint`, `restoreModelEndpoint`, `invoke`, `approvalPosture`, `putApprovalPosture`, `conversations`, `restoreMyConversation`, `resetEmotion`, `characterAdopted`, `devices`, `createDeviceRoot`, `revokeDevice`, `revokeDeviceRoot`, `deviceLeases`, `logout` |

The `chat` route is the only one that swaps component by runtime, at
[`apps/worker/src/components/shell/AppRouteSurface.tsx:71`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `return hasDesktopRuntime() ? <LocalChatView`.
The `account` route does not render an account view, at
[`apps/worker/src/components/shell/AppRouteSurface.tsx:98`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `return <SettingsView section=`.
The `automations` route renders Routines v1, at
[`apps/worker/src/components/shell/AppRouteSurface.tsx:84`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `return <RoutinesView />;`.

Eleven of the sixteen route ids are absent from the primary navigation list, which
carries five destinations only: chat, agents, integrations (labelled Plugins),
browser and automations (labelled Routines), at
[`apps/worker/src/components/shell/ShellNav.tsx:5`](../../../apps/worker/src/components/shell/ShellNav.tsx) `const primary: Array<{`.
Two of the eleven have another sidebar path: the identity menu reaches `settings`
and `organisation`, at
[`apps/worker/src/components/Shell.tsx:152`](../../../apps/worker/src/components/Shell.tsx) `if (action === `.
`build` and `knowledge` are reached from the agent tab strip that Build, Agents and
Knowledge share, at
[`apps/worker/src/components/build/AgentTabsStrip.tsx:30`](../../../apps/worker/src/components/build/AgentTabsStrip.tsx) `else navigate(`.
The remaining seven, `home`, `runs`, `work`, `account`, `channels`, `evaluations`
and `memory`, have no navigation entry at all and are reachable only by hash, by
the command palette, or by one in-page link each. The palette carries a row for all
sixteen, at
[`apps/worker/src/components/CommandPalette.tsx:48`](../../../apps/worker/src/components/CommandPalette.tsx) `export const workerCommands: Command[] = [`.

Four routes carry a second level of hash routing through a shared hook,
`useRouteSelection`: build tabs, integrations tabs, knowledge asset selection and
automations workflow selection, plus run, work, agent, evaluation and memory
selection ids (bounded: `rg -n "useRouteSelection\(" src` returns nine call sites
plus the definition, 2026-08-24, pinned tree).

### 4.3 The settings section list

Fifteen `SettingsSection` ids exist. Ten are navigable entries in
`SETTINGS_SECTIONS` (`you`, `behaviour`, `autonomy`, `spend`, `models`,
`shortcuts`, `health`, `organisation`, `advanced`, `archived`), `operations` is a
valid deep link deliberately kept out of the nav, and `sensing`, `sight`,
`knowledge` and `overnight` are legacy deep links that all resolve to the Behaviour
pane, at
[`apps/worker/src/settingsSections.ts:114`](../../../apps/worker/src/settingsSections.ts) `const LEGACY_BEHAVIOUR_ENTRIES: Partial<Record<SettingsSection, SettingsEntry>> = {`
and [`apps/worker/src/settingsSections.ts:142`](../../../apps/worker/src/settingsSections.ts) `if (id === `.
The section-to-pane map is total over the union, so an unknown section cannot draw
a blank page, at
[`apps/worker/src/components/SettingsSurface.tsx:93`](../../../apps/worker/src/components/SettingsSurface.tsx) `const SETTINGS_PANES: Record<SettingsSection, SettingsPane> = {`.

### 4.4 Identity, the only application-wide object

`WorkerIdentity` is `{ user, role, organisation, workspace }` plus a three-state
`identityStatus`, at
[`apps/worker/src/components/WorkerGlobalContext.tsx:17`](../../../apps/worker/src/components/WorkerGlobalContext.tsx) `export interface WorkerIdentity {`.
It is composed from four independent calls under `Promise.allSettled`, at
[`apps/worker/src/components/WorkerGlobalContext.tsx:41`](../../../apps/worker/src/components/WorkerGlobalContext.tsx) `await Promise.allSettled([`,
and `identityStatus` degrades to unavailable when the org, workspace or overview
call failed, at
[`apps/worker/src/components/WorkerGlobalContext.tsx:83`](../../../apps/worker/src/components/WorkerGlobalContext.tsx) `setIdentityStatus(`.
A failed `meSettings` is the only case that nulls the identity outright. This is
the ONLY React context in the application (bounded: `rg -n "createContext" src`
returns one file, 2026-08-24, pinned tree).

### 4.5 Per-surface load state

There is no shared query cache, no store library and no fetch deduplication. Every
view holds its own `useState` and a small state union, and that union is declared
five separate times in two different shapes:

| declaration | members |
|---|---|
| [`apps/worker/src/components/ParityViews.tsx:34`](../../../apps/worker/src/components/ParityViews.tsx) `type SurfaceState = ` | loading, ready, denied, not-found, unavailable |
| [`apps/worker/src/components/knowledge/KnowledgeView.tsx:39`](../../../apps/worker/src/components/knowledge/KnowledgeView.tsx) `type SurfaceState = ` | the same five |
| [`apps/worker/src/components/EvaluationsView.tsx:23`](../../../apps/worker/src/components/EvaluationsView.tsx) `type SurfaceState = ` | four, no not-found |
| [`apps/worker/src/components/ChannelsView.tsx:28`](../../../apps/worker/src/components/ChannelsView.tsx) `type SurfaceState = ` | four, no not-found |
| [`apps/worker/src/components/AutomationView.tsx:119`](../../../apps/worker/src/components/AutomationView.tsx) `type AutomationState = ` | four, differently named |

The status-to-state mapping is duplicated with them, at
[`apps/worker/src/components/ParityViews.tsx:37`](../../../apps/worker/src/components/ParityViews.tsx) `function failureState(error: unknown):`:
401 and 403 become denied, 404 becomes not-found, everything else becomes
unavailable.

### 4.6 The exact-approval finalizer, the one governed-mutation contract

Twenty-six modules share one hook for the case where a governed route answers
`pending_human`, at
[`apps/worker/src/components/ExactApprovalFinalizer.tsx:86`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `export function useExactApprovalFinalizer<`
(bounded: `rg -ln "useExactApprovalFinalizer" src` returns 27 paths including the
definition, 2026-08-24, pinned tree). Its contract:

1. `begin(input, result, label)` returns false unless the result is
   `pending_human`, so it can never claim a mutation that already applied.
2. The held input is a JSON clone, so later form edits cannot change what a human
   approved, at
   [`apps/worker/src/components/ExactApprovalFinalizer.tsx:83`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `return JSON.parse(JSON.stringify(input)) as TInput;`.
3. `continueExact()` reads `client.invokeApprovalState(approvalId)` and
   short-circuits on pending, rejected, expired and consumed BEFORE replaying, at
   [`apps/worker/src/components/ExactApprovalFinalizer.tsx:157`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `async function continueExact() {`.
4. A second `pending_human` after replay retains the same cloned input under the
   NEW approval id rather than stranding a valid second request.
5. The terminal states are a closed union of eight values including `null`, at
   [`apps/worker/src/components/ExactApprovalFinalizer.tsx:5`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `export type ExactApprovalFinalizationState =`.

`governedRouteRefusal` is the companion decoder: a governed body with no `run_id`
and a denied, error, unavailable or degraded status is a refusal and never a
success, at
[`apps/worker/src/components/ExactApprovalFinalizer.tsx:37`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `export function governedRouteRefusal(`.

### 4.7 The character registry

Four bodies are registered in the stock build from committed bundles, at
[`apps/worker/src/components/characters.ts:355`](../../../apps/worker/src/components/characters.ts) `registerCharacter(FAMILIAR);`
through `registerCharacter(COLOSSUS);` on line 358. The plugin join point ships
empty by design, at
[`apps/worker/src/characterPlugins.ts:20`](../../../apps/worker/src/characterPlugins.ts) `export {};`.
The selected body is a presentation-only setting with its own key and change
event, deliberately not folded into the theme, at
[`apps/worker/src/character.ts:20`](../../../apps/worker/src/character.ts) `export const CHARACTER_SETTING_KEY = `.

## 5. Control flow

### 5.1 Boot, in order

1. `bootstrapAppearance()` reads `localStorage` and stamps `data-theme`,
   `data-theme-preference`, `data-density`, `data-contrast`, `--font-scale` and the
   `reduce-motion` class on `<html>` BEFORE React mounts, at
   [`apps/worker/src/main.tsx:17`](../../../apps/worker/src/main.tsx) `bootstrapAppearance();`
   and [`apps/worker/src/theme.ts:186`](../../../apps/worker/src/theme.ts) `export function applyAppearance(appearance: Appearance): Appearance {`.
   **Failure branch**: a throwing `localStorage` yields the product default, at
   [`apps/worker/src/theme.ts:149`](../../../apps/worker/src/theme.ts) `return { ...DEFAULT_APPEARANCE };`,
   whose theme is dark rather than system, at
   [`apps/worker/src/theme.ts:37`](../../../apps/worker/src/theme.ts) `theme: `.
2. `bootstrapCharacter()` and `bootstrapProductName()` run next. The product name
   is fetched once from the unauthenticated `/v1/branding`, with a validated
   `localStorage` cache so only the first visit to an origin can show the wrong
   wordmark, at
   [`apps/worker/src/productName.ts:25`](../../../apps/worker/src/productName.ts) `const KNOWN = new Set([DEFAULT_PRODUCT_NAME,`.
   **Failure branch**: an unrecognised cached value is discarded, not rendered.
3. React mounts a fixed five-deep wrapper, `StrictMode > WorkerErrorBoundary >
   AuthGate > WorkerGlobalContextProvider > App`, at
   [`apps/worker/src/main.tsx:29`](../../../apps/worker/src/main.tsx) `<WorkerErrorBoundary>`.
4. `App` reads two breakpoints, 640px for phone and 760px for the compact rail, at
   [`apps/worker/src/App.tsx:9`](../../../apps/worker/src/App.tsx) `const phone = useMediaQuery(`,
   then composes four hooks and renders `AppFrame`.
5. `AppFrame` renders the sidebar plus a `Suspense`-wrapped `AppRouteSurface`.
   Every route component and the command palette are `React.lazy` dynamic imports,
   at [`apps/worker/src/components/shell/AppRouteSurface.tsx:157`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `function lazyNamed<`.
   **Failure branch**: a chunk that fails to load is caught by
   `WorkerErrorBoundary`, which recognises the dynamic-import failure family and
   reloads ONCE per error fingerprint, remembering the attempt in `sessionStorage`,
   at [`apps/worker/src/components/WorkerErrorBoundary.tsx:25`](../../../apps/worker/src/components/WorkerErrorBoundary.tsx) `export function isRecoverableChunkError(error: unknown): boolean {`.

### 5.2 Authentication from the browser

1. `AuthGate` first splits off the pre-session hashes `#/accept-invite`,
   `#/forgot-password` and `#/reset-password`. Those render their own screens and
   never probe the session, at
   [`apps/worker/src/components/auth/routing.ts:3`](../../../apps/worker/src/components/auth/routing.ts) `export function recoveryFlowFromHash(hash = window.location.hash): RecoveryFlow {`.
2. A desktop build with no configured API origin fails closed BEFORE offering
   sign-in, at
   [`apps/worker/src/components/AuthGate.tsx:136`](../../../apps/worker/src/components/AuthGate.tsx) `if (isDesktop && !configuredApiOrigin()) return <DesktopServerMissing />;`.
3. Otherwise the gate probes the existing session, at
   [`apps/worker/src/components/AuthGate.tsx:49`](../../../apps/worker/src/components/AuthGate.tsx) `void client.meSettings()`.
   Success applies the server-authoritative character before any private UI mounts
   and moves to authenticated.
4. **Failure branch, typed.** A 403 whose body carries detail
   `password_change_required` or `two_factor_enrollment_required` routes to the
   matching screen; every other failure is unauthenticated, at
   [`apps/worker/src/components/AuthGate.tsx:78`](../../../apps/worker/src/components/AuthGate.tsx) `if (detail === `.
5. `LoginScreen` posts `client.login` and branches on a closed status vocabulary of
   `ok`, `2fa_required`, `password_change_required` and `2fa_enrollment_required`,
   falling back to the server-supplied reason string, at
   [`apps/worker/src/components/auth/LoginScreen.tsx:28`](../../../apps/worker/src/components/auth/LoginScreen.tsx) `if (result.status === `.
   **Failure branch**: a thrown request becomes one opaque message that does not
   distinguish a wrong password from a network failure, which is the intended
   non-enumeration posture.
6. Once authenticated, a rotation timer refreshes every four hours AND on every
   `visibilitychange` to visible, at
   [`apps/worker/src/components/AuthGate.tsx:104`](../../../apps/worker/src/components/AuthGate.tsx) `const timer = window.setInterval(rotate, 4 * 60 * 60 * 1000);`.
   **Failure branch**: a 401 from `refreshSession` does NOT sign the user out
   directly; it re-probes `meSettings` first, so a cookie rotated by another tab
   cannot evict this one, at
   [`apps/worker/src/components/AuthGate.tsx:95`](../../../apps/worker/src/components/AuthGate.tsx) `// Re-resolve after a possible shared-cookie rotation in another tab.`.
7. The authenticated tree is `OnboardingGate > DesktopAccountBridge > App`.
   Onboarding is gated on one settings key equalling one integer, at
   [`apps/worker/src/onboarding.ts:8`](../../../apps/worker/src/onboarding.ts) `return settings?.[ONBOARDING_SETTING_KEY] !== ONBOARDING_VERSION;`.

Session authority is the httpOnly cookie plus a double-submit CSRF token. The SDK
sends cookies when no bearer is configured, at
[`sdks/web/src/client.ts:336`](../../../sdks/web/src/client.ts) `private credentials(): RequestCredentials {`,
and attaches the CSRF header only on mutating methods, at
[`sdks/web/src/client.ts:368`](../../../sdks/web/src/client.ts) `if (csrf && mutating.has(method)) headers.set(`.
The Worker supplies the token getter, preferring a value remembered from the last
login or refresh response over the cookie, at
[`apps/worker/src/client.ts:19`](../../../apps/worker/src/client.ts) `function browserSessionCsrf(): string | null {`.

### 5.3 Authentication from the desktop shell

The desktop keeps the same SDK surface but replaces exactly four session-issuing
calls with origin-pinned native invocations, because WKWebView does not persist
cross-site `Set-Cookie` for a `tauri://` document, at
[`apps/worker/src/client.ts:41`](../../../apps/worker/src/client.ts) `if (isDesktop) {`.
Every other call goes through `desktopApiFetch`, a fetch-shaped shim that refuses a
URL whose origin is not the configured one or whose path is not under `/v1`, caps
the request at 25 MiB, at
[`apps/worker/src/desktopApiTransport.ts:11`](../../../apps/worker/src/desktopApiTransport.ts) `const DESKTOP_API_MAX_REQUEST_BYTES = 25 * 1024 * 1024;`,
hands `{method, path, headers, body}` to the native `desktop_api_request` command,
and decodes a magic-prefixed binary envelope whose metadata is capped at 64 KiB and
whose response headers are whitelisted to four names, at
[`apps/worker/src/desktopApiTransport.ts:15`](../../../apps/worker/src/desktopApiTransport.ts) `const SAFE_RESPONSE_HEADERS = new Set([`.
**Failure branch**: every parse failure funnels to one reason, at
[`apps/worker/src/desktopApiTransport.ts:27`](../../../apps/worker/src/desktopApiTransport.ts) `throw new Error(`.

After account auth, `DesktopAccountBridge` reconciles the per-computer key:
`device_agent_status` reports the local state; `reenrollment_required` demands a
replace; a device id absent from `client.devices()` means the key belongs to a
different or revoked account. **Failure branch, fail-open by design**: a transient
`devices()` failure resolves to ready rather than looping the user back to sign-in
or destroying a possibly valid key, at
[`apps/worker/src/components/auth/useDesktopAccountBridge.ts:33`](../../../apps/worker/src/components/auth/useDesktopAccountBridge.ts) `// Account auth succeeded. A transient device-list failure must not turn`.

### 5.4 Chat, the send path

1. `send()` validates the local selection first: an invalid agent or model choice,
   or a conversation whose status is not active, is refused with a message and no
   request, at
   [`apps/worker/src/components/ChatView.tsx:341`](../../../apps/worker/src/components/ChatView.tsx) `async function send(`.
2. A new `AbortController` is registered and the current generation captured.
   `client.streamChat` posts `/v1/chat` with a client-minted `idempotency_key` and
   `origin: worker`, at
   [`apps/worker/src/components/ChatView.tsx:377`](../../../apps/worker/src/components/ChatView.tsx) `const queued = await client.streamChat({`.
3. **Two-outcome contract.** A 202 returns a queue receipt and NO stream, meaning
   the turn joined an already-admitted run; a 200 streams SSE frames, at
   [`sdks/web/src/client.ts:2596`](../../../sdks/web/src/client.ts) `if (response.status === 202) return (await parseResponse(response)) as ChatQueued;`.
4. On a queue receipt the view echoes the user message locally and, when no other
   stream is open, schedules a follow attach in the `finally` block so the live turn
   does not become invisible, at
   [`apps/worker/src/components/ChatView.tsx:447`](../../../apps/worker/src/components/ChatView.tsx) `if (followQueuedId && followStillOwned) void reattach(followQueuedId, 0, true);`.
5. Every frame passes an ownership check before touching state. The generation
   counter exists because the SDK resolves an ABORTED stream with `undefined`,
   which is otherwise indistinguishable from a naturally completed one, at
   [`apps/worker/src/components/ChatView.tsx:180`](../../../apps/worker/src/components/ChatView.tsx) `const conversationGenerationRef = useRef(0);`.
6. `acceptLiveEvent` fans out by event type: `steer_queued` reloads the thread,
   `steer_consumed` clears the local echo, `artifact` refreshes the artifact page,
   `artifact_rejected` and `event_unavailable` raise explicit notices, and
   `message_start` re-pins the active run and adopts a stream-created conversation
   id, at [`apps/worker/src/components/ChatView.tsx:724`](../../../apps/worker/src/components/ChatView.tsx) `function acceptLiveEvent(`.
7. **Failure branch.** Any throw sets the error line and, when a live conversation
   was held, also sets the continuity notice and arms the manual reconnect, at
   [`apps/worker/src/components/ChatView.tsx:435`](../../../apps/worker/src/components/ChatView.tsx) `setContinuity(`.
   A 413 is returned to the composer as `true` so the draft is restored rather than
   lost.

### 5.5 Chat, the reattach path, which is the realtime transport

The live transport is server-sent events read from a `fetch` body, not
`EventSource` and not a WebSocket. There is exactly one `new WebSocket(` in the
whole of `apps/worker/src` and it belongs to voice (bounded: `rg -n "EventSource|new
WebSocket" src`, 2026-08-24, pinned tree, one hit, in `components/VoiceCall.tsx`).

1. `hydrateConversation` loads the thread; if it reports an active run and no
   stream is already owned, a follow is attached at cursor zero, at
   [`apps/worker/src/components/ChatView.tsx:488`](../../../apps/worker/src/components/ChatView.tsx) `async function hydrateConversation(id: string, ownsLiveStream: boolean) {`.
2. `reattach` refuses to double-attach, optionally resets the live event buffer,
   posts a reconnecting notice, and calls `client.followConversation`, at
   [`apps/worker/src/components/ChatView.tsx:663`](../../../apps/worker/src/components/ChatView.tsx) `setRetryFollow(false);`.
3. The SDK issues `GET /v1/conversations/{id}/events?follow=1&since=<cursor>` with
   an event-stream accept header, rejecting a non-integer or negative cursor
   client-side before the request, at
   [`sdks/web/src/client.ts:515`](../../../sdks/web/src/client.ts) `async followConversation(`.
4. **Three typed outcomes.** HTTP 409 means no active run and is returned as an
   `idle` result carrying the unchanged cursor, not as an error; a completed stream
   is `ended`; an aborted one is `aborted`.
5. Frame validation is strict and fails the whole follow: a frame with a
   non-integer or negative cursor, or with no event, is rejected, at
   [`sdks/web/src/client.ts:566`](../../../sdks/web/src/client.ts) `|| frame.cursor < 0`,
   and a cursor that goes BACKWARDS is rejected, at
   [`sdks/web/src/client.ts:571`](../../../sdks/web/src/client.ts) `if (sawFrame && frame.cursor < cursor) {`.
   Heartbeat frames advance the cursor and are not delivered to the caller.
6. A `replay_truncated` flag on any frame replaces the continuity notice with the
   bounded-replay explanation, at
   [`apps/worker/src/components/ChatView.tsx:676`](../../../apps/worker/src/components/ChatView.tsx) `if (frame.replay_truncated) {`.
7. When the follow ends naturally the view reloads the durable thread, clears the
   live buffer, and if the thread reports ANOTHER active run it re-attaches at
   cursor zero from the `finally` block, at
   [`apps/worker/src/components/ChatView.tsx:720`](../../../apps/worker/src/components/ChatView.tsx) `if (nextRunStillOwned) void reattach(id, 0, true);`.

**Reconnect behaviour, stated plainly: there is no automatic retry and no backoff.**
A dropped follow arms a flag whose only consumer is a Reconnect button, at
[`apps/worker/src/components/ChatView.tsx:1240`](../../../apps/worker/src/components/ChatView.tsx) `{retryFollow && conversationId && (`,
which replays from the last observed cursor, at
[`apps/worker/src/components/ChatView.tsx:1244`](../../../apps/worker/src/components/ChatView.tsx) `onClick={() => void reattach(`.
The single automatic re-attach in the file is the run-to-run handoff in step 7,
which is a success path, not a recovery path.

One SSE frame parser is shared by all three streaming methods, `streamChat`,
`followConversation` and `runEvents`. It splits on a blank line, concatenates every
`data:` line in a frame and parses the result as JSON, at
[`sdks/web/src/client.ts:2633`](../../../sdks/web/src/client.ts) `async function pumpSseFrames<T>(`.
**Failure branch**: a malformed frame throws out of the pump and ends the stream.

### 5.6 Realtime voice

1. Voice affordances render only when the SDK exposes call creation and the
   conversation is active or absent, at
   [`apps/worker/src/components/ChatView.tsx:853`](../../../apps/worker/src/components/ChatView.tsx) `const voiceAvailable = typeof client.createCall === `.
2. `start()` calls `client.createCall` FIRST. Microphone permission is requested
   only later, inside `connect()`, so the browser prompt never appears for a call
   the kernel refused, at
   [`apps/worker/src/components/VoiceCall.tsx:455`](../../../apps/worker/src/components/VoiceCall.tsx) `async function start() {`
   and [`apps/worker/src/components/VoiceCall.tsx:594`](../../../apps/worker/src/components/VoiceCall.tsx) `stream = await navigator.mediaDevices.getUserMedia({`.
3. **Typed unavailability.** A `realtime_unavailable` call status adopts the
   text-continuation conversation, refreshes recent calls and posts a plain-language
   notice. No socket opens and no microphone is touched, at
   [`apps/worker/src/components/VoiceCall.tsx:483`](../../../apps/worker/src/components/VoiceCall.tsx) `if (result.call.status === `.
4. `connect()` refuses a response with no media token or no websocket URL, then
   builds the graph: `getUserMedia` in mono with echo cancellation, noise
   suppression and AGC, into a 4096-frame `ScriptProcessorNode`, a muted gain to the
   destination, a barge-in capture analyser, a playback gain and a playback
   analyser.
5. The socket URL is RESOLVED, not taken raw: the kernel returns a relative path,
   resolved against the document in the browser and against the configured API
   origin in the desktop shell, then upgraded to `ws:` or `wss:`, at
   [`apps/worker/src/components/VoiceCall.tsx:1439`](../../../apps/worker/src/components/VoiceCall.tsx) `function websocketUrl(value: string): string {`
   and [`apps/worker/src/components/VoiceCall.tsx:618`](../../../apps/worker/src/components/VoiceCall.tsx) `socket = new WebSocket(websocketUrl(result.websocket_url));`.
6. **The bearer never enters the URL.** It is sent as the first frame after the
   socket opens, at
   [`apps/worker/src/components/VoiceCall.tsx:692`](../../../apps/worker/src/components/VoiceCall.tsx) `type: `.
7. Microphone PCM is sent only once ready has arrived, the call is unmuted and the
   socket is OPEN; capture is resampled to 16-bit 24 kHz, at
   [`apps/worker/src/components/VoiceCall.tsx:663`](../../../apps/worker/src/components/VoiceCall.tsx) `const pcm = resamplePcm16(input, context?.sampleRate ?? 24_000, 24_000);`.
8. Inbound `ArrayBuffer` frames are synthesized PCM scheduled on the audio context;
   inbound strings are control frames, of which exactly two types are honoured,
   `ready` and `call_event`. Unknown control frames are ignored silently.
9. A fifteen-second readiness timeout releases the microphone and reports it, at
   [`apps/worker/src/components/VoiceCall.tsx:90`](../../../apps/worker/src/components/VoiceCall.tsx) `const VOICE_READY_TIMEOUT_MS = 15_000;`.
10. **Close codes are a typed vocabulary**: 4429 is capacity and terminal, 4401 is a
    spent one-time session and reconnectable, 1013 is provider unavailability and
    terminal, anything else is reconnectable, at
    [`apps/worker/src/components/VoiceCall.tsx:1500`](../../../apps/worker/src/components/VoiceCall.tsx) `function socketCloseError(event: CloseEvent): VoiceConnectionError {`.
11. **Voice reconnect is manual too.** `reconnect()` runs only from the call
    screen's reconnect prop and always mints a fresh session through
    `client.reopenCall`; the spent bearer is never reused, at
    [`apps/worker/src/components/VoiceCall.tsx:506`](../../../apps/worker/src/components/VoiceCall.tsx) `async function reconnect() {`
    and [`apps/worker/src/components/VoiceCall.tsx:1115`](../../../apps/worker/src/components/VoiceCall.tsx) `onReconnect={() => void reconnect()}`.
    Only five statuses are treated as reopenable, at
    [`apps/worker/src/components/VoiceCall.tsx:1214`](../../../apps/worker/src/components/VoiceCall.tsx) `return [`.
12. Mid-call typed text rides the same media socket and is rendered only when the
    gateway echoes it back as a transcript event, at
    [`apps/worker/src/components/VoiceCall.tsx:879`](../../../apps/worker/src/components/VoiceCall.tsx) `socket.send(JSON.stringify({ type: `.
13. Every connection attempt is fenced by a monotonic attempt counter; a late
    callback from a superseded attempt raises a cancellation error that the failure
    reporter swallows, so a stale socket cannot repaint a newer call's status.

Text-chat reply speech is a different path entirely: opt-in, and dispatched as the
governed `voice.speak` verb through the ordinary invoke route, never a provider
call, at
[`apps/worker/src/components/chat/useReplySpeech.ts:205`](../../../apps/worker/src/components/chat/useReplySpeech.ts) `const result = await client.invoke({`.

### 5.7 The desktop-local chat path

When a Tauri runtime is present, the `chat` route mounts `LocalChatView` instead of
`ChatView`, at
[`apps/worker/src/components/shell/AppRouteSurface.tsx:71`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `return hasDesktopRuntime() ? <LocalChatView`.
That surface never calls `/v1/chat`. It drives a native Codex App Server over Tauri
channels and keeps its conversations in `localStorage`, at
[`apps/worker/src/localAgentClient.ts:11`](../../../apps/worker/src/localAgentClient.ts) `const STORAGE_KEY = `,
capped at 8 MiB, 100 conversations and 2,000 messages. Local ids are namespaced
`local:<threadId>` and native events are projected into the SAME `ChatEvent`
vocabulary the cloud stream uses, at
[`apps/worker/src/localAgentClient.ts:207`](../../../apps/worker/src/localAgentClient.ts) `export function localEventToChatEvent(event: LocalAgentEvent): ChatEvent | null {`.
The conversation directory switches source on the same predicate, at
[`apps/worker/src/components/shell/useConversationDirectory.ts:32`](../../../apps/worker/src/components/shell/useConversationDirectory.ts) `if (hasDesktopRuntime()) {`.
The non-crossing of the two lanes is asserted by
[`tests/security/test_worker_surface_boundary.py:188`](../../../tests/security/test_worker_surface_boundary.py) `def test_browser_cloud_and_desktop_local_agent_routes_cannot_silently_cross():`.

## 6. Data

The Worker owns no database, no table, no migration and no index. Everything
durable lives behind the kernel; the only client-side persistence is browser
storage, and every write is wrapped so that a hardened context degrades rather
than fails.

### 6.1 localStorage keys, complete

| key | written by | contents | what breaks if it is lost or hostile |
|---|---|---|---|
| `boltrig.appearance` | [`apps/worker/src/theme.ts:46`](../../../apps/worker/src/theme.ts) `const APPEARANCE_STORAGE_KEY = ` | normalised `{theme, density, fontScale, reducedMotion, highContrast}` | nothing: every field is re-normalised against a closed option list on read, and a throw yields the product default |
| `boltrig-worker-theme` | [`apps/worker/src/theme.ts:47`](../../../apps/worker/src/theme.ts) `const LEGACY_THEME_KEY = ` | the theme preference alone | downgrade compatibility only |
| `boltrig.character` | [`apps/worker/src/character.ts:44`](../../../apps/worker/src/character.ts) `const STORAGE_KEY = ` | selected body id | an id whose character is not registered resolves to the default AT RENDER TIME rather than being rejected on read |
| `boltrig.character.skin` | [`apps/worker/src/character.ts:45`](../../../apps/worker/src/character.ts) `const SKIN_STORAGE_KEY = ` | selected skin id | same, shape-checked only |
| `boltrig.product-name` | [`apps/worker/src/productName.ts:21`](../../../apps/worker/src/productName.ts) `const CACHE_KEY = ` | the last known deployment name | an unknown value is discarded rather than rendered, because the wordmark is not a place to display arbitrary attacker text |
| `boltrig.shell-preferences.v1` | [`apps/worker/src/components/shell/shellPreferences.ts:16`](../../../apps/worker/src/components/shell/shellPreferences.ts) `export const SHELL_PREFERENCES_V1_KEY = ` | pinned conversation ids | pins are lost; nothing else |
| `boltrig-worker-pinned-conversations` | [`apps/worker/src/components/shell/shellPreferences.ts:17`](../../../apps/worker/src/components/shell/shellPreferences.ts) `export const LEGACY_PINNED_CONVERSATIONS_KEY = ` | the same list, mirrored for a rollback build | downgrade compatibility only |
| `boltrig.sidebar-organize.v1` | [`apps/worker/src/components/shell/shellPreferences.ts:18`](../../../apps/worker/src/components/shell/shellPreferences.ts) `export const SHELL_ORGANIZE_MODE_KEY = ` | project, agent or list grouping | grouping resets |
| `boltrig.local-conversations.v1` | [`apps/worker/src/localAgentClient.ts:11`](../../../apps/worker/src/localAgentClient.ts) `const STORAGE_KEY = ` | the ENTIRE desktop-local conversation corpus | on the desktop this is the only copy of a local task; see RISK-1509 |
| `boltrig-worker-voice-banner-dismissed` | [`apps/worker/src/components/chat/VoiceBanner.tsx:3`](../../../apps/worker/src/components/chat/VoiceBanner.tsx) `const DISMISS_KEY = ` | one boolean | the banner reappears |
| `boltrig.bargeIn.mode`, `boltrig.bargeIn.diagnostics` | [`apps/worker/src/components/voiceSelfTrigger.ts:237`](../../../apps/worker/src/components/voiceSelfTrigger.ts) `return (globalThis.localStorage?.getItem(key) ?? ` | developer overrides for the barge-in gate | falls back to the build-time environment, then the default |

### 6.2 sessionStorage keys, complete

| key | written by | contents |
|---|---|---|
| `boltrig.worker.chunk-recovery` | [`apps/worker/src/components/WorkerErrorBoundary.tsx:5`](../../../apps/worker/src/components/WorkerErrorBoundary.tsx) `export const WORKER_CHUNK_RECOVERY_KEY = ` | the fingerprint of the last dynamic-import failure, so the one-shot reload cannot loop |
| `boltrig.pending-chat-agent.v1` | [`apps/worker/src/components/chat/pendingChatTarget.ts:1`](../../../apps/worker/src/components/chat/pendingChatTarget.ts) `const PENDING_AGENT_KEY = ` | one agent address carried across a route transition, shape-checked against a strict pattern on both write and read |

`localStorage` and `sessionStorage` are used by exactly seven and two modules
respectively (bounded: `rg -ln "localStorage" src` and `rg -ln "sessionStorage"
src` over `apps/worker/src`, 2026-08-24, pinned tree).

### 6.3 Storage the Worker deliberately does NOT use

The README states that exact retry inputs, staged writes and recovered read bytes
for local device actions stay in renderer memory only and never enter browser
storage. That holds in the pinned tree: `LocalDeviceActions.tsx` calls no storage
API (bounded: `rg -n "localStorage|sessionStorage|indexedDB" src/components/LocalDeviceActions.tsx`
returns nothing, 2026-08-24, pinned tree). The same is true of the enrollment
secrets and one-time recovery codes in `AccountRequirementScreens.tsx`.

### 6.4 Design tokens as data

The token layer is three imported CSS files plus a console alias layer defined in
`src/styles.css`. The imported layer is dark-first, at
[`docs/design/imported/tokens/colors.css:10`](../../../docs/design/imported/tokens/colors.css) `Dark is the primary theme (the :root defaults). Light + high-contrast follow.`,
and the Worker overrides it with a light-first console palette whose deviations
from the downloaded design component are enumerated with their WCAG reason, at
[`apps/worker/src/styles.css:20`](../../../apps/worker/src/styles.css) `* Accessibility deviations from the design component, forced by WCAG 2.2`.

## 7. Configuration surface

### 7.1 Build-time, baked into the bundle

Exactly three `VITE_` variables are read anywhere in `apps/worker/src` (bounded:
`rg -o "import\.meta\.env\.[A-Z_]+" src`, 2026-08-24, pinned tree). There are no
reads of `import.meta.env.DEV`, `MODE` or `PROD`, so the shipped bundle has no
dev-only branch.

| variable | default | read at | what breaks if it is wrong |
|---|---|---|---|
| `VITE_API_BASE` | empty | [`apps/worker/src/apiOrigin.ts:41`](../../../apps/worker/src/apiOrigin.ts) `export function configuredApiOrigin(): string {` | empty is correct for the web image (same-origin behind nginx). Empty in a desktop build makes every call resolve against `tauri://localhost`, which the auth gate refuses outright |
| `VITE_DESKTOP_DOWNLOAD_URL` | empty | [`apps/worker/src/desktopDownload.ts:11`](../../../apps/worker/src/desktopDownload.ts) `const raw = (import.meta.env.VITE_DESKTOP_DOWNLOAD_URL ?? ` | a non-HTTPS or credential-bearing value is treated as absent and the download action is not rendered |
| `VITE_SELF_HOSTED_TTS_ORIGIN` | empty | [`apps/worker/src/components/voiceBargeInGraph.ts:260`](../../../apps/worker/src/components/voiceBargeInGraph.ts) `const raw = (import.meta.env.VITE_SELF_HOSTED_TTS_ORIGIN ?? ` | absent means the upstream barge-in cancel is never attempted; an unparseable or credentialed value is treated as absent rather than guessed |

`envPrefix` is widened to include `TAURI_`, at
[`apps/worker/vite.config.ts:465`](../../../apps/worker/vite.config.ts) `envPrefix: [`.

### 7.2 URL-carried page modes, per load, never persisted

`?theme=light|dark` clamps ONLY the effective palette, at
[`apps/worker/src/theme.ts:63`](../../../apps/worker/src/theme.ts) `export function forcedThemeOverride(): WorkerTheme | null {`,
and `?embed=1` stamps a data attribute so an embedding host supplies the chrome, at
[`apps/worker/src/theme.ts:74`](../../../apps/worker/src/theme.ts) `export function isEmbedMode(): boolean {`.
Neither touches `localStorage` or kernel settings. Both are re-read from
`window.location.search` on every call, which survives hash navigation because the
app is a hash router.

### 7.3 Deployment, the web image

| key | default | where | what breaks if it is wrong |
|---|---|---|---|
| `WORKER_PORT` | 8082 | [`docker-compose.yml:492`](../../../docker-compose.yml) `- "${WORKER_PORT:-8082}:8080"` | container side is fixed at 8080 because the image runs unprivileged, at [`apps/worker/nginx.conf:11`](../../../apps/worker/nginx.conf) `listen 8080;` and [`apps/worker/Dockerfile:63`](../../../apps/worker/Dockerfile) `USER nginx` |
| `BOLTRIG_DESKTOP_DOWNLOAD_URL` | empty | [`.env.example:130`](../../../.env.example) `BOLTRIG_DESKTOP_DOWNLOAD_URL=` | compose maps it onto the build arg, at [`docker-compose.yml:485`](../../../docker-compose.yml) `VITE_DESKTOP_DOWNLOAD_URL: ${BOLTRIG_DESKTOP_DOWNLOAD_URL:-}`. A direct `docker build` must pass `VITE_DESKTOP_DOWNLOAD_URL` instead; the README names only the compose spelling |

The image's own guarantees are the security headers and the SPA fallback shape.
The CSP is same-origin closed with one relaxation for inline style, at
[`apps/worker/nginx.conf:27`](../../../apps/worker/nginx.conf) `add_header Content-Security-Policy `,
the permissions policy allows the microphone for self only and denies camera and
geolocation, at
[`apps/worker/nginx.conf:26`](../../../apps/worker/nginx.conf) `add_header Permissions-Policy `,
hashed assets are cached hard and 404 rather than falling through to `index.html`,
at [`apps/worker/nginx.conf:88`](../../../apps/worker/nginx.conf) `location /assets/ {`,
and everything else falls back to the SPA, at
[`apps/worker/nginx.conf:111`](../../../apps/worker/nginx.conf) `try_files $uri $uri/ /index.html;`.
The voice gateway is proxied with upgrade headers and a one-hour read timeout, at
[`apps/worker/nginx.conf:67`](../../../apps/worker/nginx.conf) `location /voice/ {`.

### 7.4 Development server

| variable | default | read at | effect |
|---|---|---|---|
| `BOLTRIG_KERNEL_URL` | `http://localhost:8000` | [`apps/worker/vite.config.ts:397`](../../../apps/worker/vite.config.ts) `const kernel = process.env.BOLTRIG_KERNEL_URL ?? ` | proxy target for `/v1`, `/healthz`, `/readyz` |
| `BOLTRIG_CHANNEL_GATEWAY_URL` | `http://localhost:8091` | [`apps/worker/vite.config.ts:401`](../../../apps/worker/vite.config.ts) `const gateway = process.env.BOLTRIG_CHANNEL_GATEWAY_URL ?? ` | proxy target for `/voice`, with the prefix stripped, mirroring nginx |
| `BOLTRIG_DEV_ALLOWED_HOSTS` | empty | [`apps/worker/vite.config.ts:442`](../../../apps/worker/vite.config.ts) `...(process.env.BOLTRIG_DEV_ALLOWED_HOSTS ?? ` | named hosts are added to Vite's DNS-rebinding defence. Wildcarding is deliberately refused because the dev server carries a write route |
| `BOLTRIG_BENCH_TOKEN` | unset | [`apps/worker/vite.config.ts:78`](../../../apps/worker/vite.config.ts) `const token = process.env.BOLTRIG_BENCH_TOKEN ?? ` | when unset the guard is NOT installed and the bench is open; when set, every request is token-gated before any other middleware |

The dev server binds 1420 and preview binds 4180, both `strictPort`. Three
dev-only write routes exist and none of them ship: `/__bench-presets`,
`/__bench-tts` and `/__bench-clips`, all declared `apply: "serve"`.

### 7.5 Desktop build

`build:desktop` and `dev:desktop` run a pre-build gate first, at
[`apps/worker/package.json:12`](../../../apps/worker/package.json) `"build:desktop": "node scripts/require-desktop-origin.mjs && tsc && vite build",`.
The gate demands BOTH `VITE_API_BASE` and `BOLTRIG_DESKTOP_API_ORIGIN`, demands
HTTPS unless the host is loopback, demands a bare canonical origin with no
userinfo, query, fragment or path, and demands that the two match EXACTLY, at
[`apps/worker/scripts/require-desktop-origin.mjs:44`](../../../apps/worker/scripts/require-desktop-origin.mjs) `throw new Error("desktop frontend and native API origins must match exactly");`.

The desktop webview CSP is stricter than the web one and is a different document:
it allows connections only to `self` and the two product domains, and it does NOT
carry `unsafe-inline` for style, at
[`apps/worker/src-tauri/tauri.conf.json:28`](../../../apps/worker/src-tauri/tauri.conf.json) `"csp": "default-src 'self'; connect-src 'self' https://boltrig.ai`.

### 7.6 Subpath mounting

The console can be served under a host path behind a stripping proxy. The mount is
DERIVED from the document rather than declared, at
[`apps/worker/src/apiOrigin.ts:27`](../../../apps/worker/src/apiOrigin.ts) `export function mountPrefix(): string {`:
a trailing slash, an `/index.html` suffix or an extensionless final segment all
mean a mount; a final segment containing a dot means root. The extensionless case
exists because a host framework can 308-strip the trailing slash before its proxy
runs.

## 8. PROCESS

### 8.1 Bring the Worker up locally

1. Build the SDK once, then install the Worker from its frozen lockfile, then run
   the dev server with a kernel URL. The README gives the exact sequence at
   [`apps/worker/README.md:18`](../../../apps/worker/README.md) `cd sdks/web && pnpm install --frozen-lockfile && pnpm build`.
2. For the packaged web surface, `docker compose up -d ui` and open the published
   port, at [`apps/worker/README.md:54`](../../../apps/worker/README.md) `docker compose up -d ui`.
3. For live voice, configure one enabled `voice` channel, issue its show-once
   channel-scoped gateway token from the channel detail, place it in the gateway's
   read-only token file, and start both profiles, at
   [`apps/worker/README.md:68`](../../../apps/worker/README.md) `docker compose --profile channels up -d ui channel-gateway`.

### 8.2 The quality gate, in dependency order

`make worker-quality` is the whole gate and it depends on `worker-structure`,
which depends on `worker-install`, at
[`Makefile:241`](../../../Makefile) `worker-quality: worker-structure ## Audit, structure, typecheck, test, and build the Worker web payload`.
The steps are, in order: frozen install plus an esbuild rebuild
([`Makefile:233`](../../../Makefile) `worker-install: lockfile-policy ## Install Worker from its frozen pnpm lockfile`),
the structure checker's own seeded tests followed by the live-tree scan
([`Makefile:237`](../../../Makefile) `worker-structure: worker-install ## Enforce Worker TS/TSX structure and Git-backed expiring debt ratchets`),
`pnpm audit --audit-level=high`, `tsc --noEmit`, `vitest run` and `vite build`.
CI runs exactly that one target for the web payload, at
[`.github/workflows/ci.yml:84`](../../../.github/workflows/ci.yml) `run: make worker-quality`.

The structural gate measures every `.ts` and `.tsx` file under `apps/worker/src`
against five limits, at
[`apps/worker/scripts/check-structure.mjs:25`](../../../apps/worker/scripts/check-structure.mjs) `export const LIMITS = Object.freeze({`:
400 file lines, 80 function lines, five parameters, cyclomatic complexity 15,
nesting depth four. It refuses to pass on a corpus of fewer than 100 source files,
at [`apps/worker/scripts/check-structure.mjs:23`](../../../apps/worker/scripts/check-structure.mjs) `const MINIMUM_SOURCE_FILES = 100;`,
which is the "a check that cannot fail" defence. Legacy violations are recorded
exactly, with an owner, a reason and an ISO expiry, in
`docs/refactoring/worker-structural-debt.json`, and the prior catalogue is loaded
from an immutable Git object rather than the working tree, at
[`.github/workflows/ci.yml:73`](../../../.github/workflows/ci.yml) `# contributor-controlled second working-tree file.`.

Measured state of that ratchet in the pinned tree: 61 exemption entries, all with
the same expiry, `2026-12-31`; 28 files exceed the 400-line limit and all 28 are
exempt; no exemption names a file that does not exist (bounded: parsed
`docs/refactoring/worker-structural-debt.json` and walked `apps/worker/src`,
2026-08-24, pinned tree).

### 8.3 The Familiar island

`make familiar-island` builds a second, single-file target and copies it into the
iOS bundle, at
[`Makefile:248`](../../../Makefile) `familiar-island: ## Build the Familiar island page and copy it into the iOS app bundle`.
`make familiar-island-check` rebuilds into a scratch directory and byte-compares
against the committed copy, at
[`Makefile:252`](../../../Makefile) `familiar-island-check: ## Refuse a committed Familiar island page that apps/worker/src no longer builds`.
The build is deterministic by construction and the single chunk is inlined into
the page and pinned by SHA-256 in the page's own CSP.

### 8.4 Visual evidence

`make visual-evidence` refuses a capture receipt that no longer describes
`apps/worker/src`, at
[`Makefile:130`](../../../Makefile) `visual-evidence: ## Refuse a capture receipt that no longer describes apps/worker/src`.
Captures themselves are produced by hand from `tests/visual/`; the shader bench is
a dev-only surface reached through the token-gated Vite plugin and writes its
settled presets to `tests/visual/presets.json` through a dev-only POST route.

### 8.5 Diagnose a broken surface

- **A blank page after a deploy.** Suspect a stale chunk. The error boundary
  reloads once per fingerprint and then shows an explicit "The update did not
  load" screen rather than looping.
- **A 403 from the dev server that reads like a firewall problem.** That is Vite's
  host check; add the name to `BOLTRIG_DEV_ALLOWED_HOSTS`.
- **Every request failing on the desktop build.** Check that both origin variables
  were set at build time and match; the gate refuses at build, but an OLD binary
  can carry an old origin.
- **Live turn frozen with no error.** The follow stream dropped. The continuity
  line and its Reconnect button are the recovery path; there is no automatic retry.
- **Voice fails immediately with a raw error string.** `getUserMedia` on a
  non-secure origin throws before any typed refusal exists; see RISK-1512.

## 9. Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
|---|---|---|
| Unknown route hash | fail-safe to `chat` | [`apps/worker/src/routes.ts:40`](../../../apps/worker/src/routes.ts) `return routes.has(candidate) ? candidate :` |
| Selection id longer than 256 chars, or a third hash segment | fail-closed, selection becomes null | [`apps/worker/src/routes.ts:55`](../../../apps/worker/src/routes.ts) `return id && id.length <= 256 ? id : null;` |
| Unknown settings section | cannot render, the map is total over the union | [`apps/worker/src/components/SettingsSurface.tsx:93`](../../../apps/worker/src/components/SettingsSurface.tsx) `const SETTINGS_PANES: Record<SettingsSection, SettingsPane> = {` |
| Desktop with no API origin | fail-closed before sign-in | [`apps/worker/src/components/AuthGate.tsx:136`](../../../apps/worker/src/components/AuthGate.tsx) `if (isDesktop && !configuredApiOrigin()) return <DesktopServerMissing />;` |
| Session probe failure of any kind other than the two typed 403 details | fail-closed to the sign-in screen | [`apps/worker/src/components/AuthGate.tsx:81`](../../../apps/worker/src/components/AuthGate.tsx) `unauthenticated` |
| Desktop session CSRF unavailable during a typed 403 | fail-closed to unauthenticated | [`apps/worker/src/components/AuthGate.tsx:74`](../../../apps/worker/src/components/AuthGate.tsx) `setState(` |
| A 401 on the four-hourly refresh | fail-OPEN, re-probes before evicting the session | [`apps/worker/src/components/AuthGate.tsx:95`](../../../apps/worker/src/components/AuthGate.tsx) `// Re-resolve after a possible shared-cookie rotation in another tab.` |
| Desktop device list unreachable during bridge inspection | fail-OPEN to ready, deliberately, so a transient failure cannot destroy a valid key | [`apps/worker/src/components/auth/useDesktopAccountBridge.ts:33`](../../../apps/worker/src/components/auth/useDesktopAccountBridge.ts) `// Account auth succeeded. A transient device-list failure must not turn` |
| Desktop native response envelope malformed in any way | fail-closed, one opaque reason | [`apps/worker/src/desktopApiTransport.ts:27`](../../../apps/worker/src/desktopApiTransport.ts) `throw new Error(` |
| Desktop request to a non-`/v1` path or a foreign origin | fail-closed before the native call | [`apps/worker/src/desktopApiTransport.ts:130`](../../../apps/worker/src/desktopApiTransport.ts) `url.origin !== configured` |
| Follow-stream cursor regression or malformed frame | fail-closed, the whole stream ends and the reconnect affordance appears | [`sdks/web/src/client.ts:571`](../../../sdks/web/src/client.ts) `if (sawFrame && frame.cursor < cursor) {` |
| No active run on reattach (HTTP 409) | fail-safe, returns an idle result and NOT an error | [`sdks/web/src/client.ts:551`](../../../sdks/web/src/client.ts) `if (response.status === 409) {` |
| Governed route answers `pending_human` with no approval id | fail-closed to the `unavailable` finalization state, never to applied | [`apps/worker/src/components/ExactApprovalFinalizer.tsx:112`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `if (!result.hitl_request_id) {` |
| Approval consumed elsewhere | fail-closed, never replayed, and the canonical refresh failure cannot regress it to waiting | [`apps/worker/src/components/ExactApprovalFinalizer.tsx:177`](../../../apps/worker/src/components/ExactApprovalFinalizer.tsx) `if (approval.status === ` |
| Voice call created but the gateway issued no media session | fail-closed before any media acquisition | [`apps/worker/src/components/VoiceCall.tsx:574`](../../../apps/worker/src/components/VoiceCall.tsx) `if (!result.media_token || !result.websocket_url) {` |
| Voice socket never becomes ready | fail-closed after fifteen seconds, releasing the microphone | [`apps/worker/src/components/VoiceCall.tsx:90`](../../../apps/worker/src/components/VoiceCall.tsx) `const VOICE_READY_TIMEOUT_MS = 15_000;` |
| Voice provider capacity refusal (close 4429) | fail-closed and terminal, with the text conversation explicitly unaffected | [`apps/worker/src/components/VoiceCall.tsx:1501`](../../../apps/worker/src/components/VoiceCall.tsx) `if (event.code === 4429) {` |
| Artifact materialisation cancelled in the native dialog | writes nothing and starts no browser download | [`apps/worker/src/desktop.ts:359`](../../../apps/worker/src/desktop.ts) `return handle === null` |
| Product-name cache holding an unknown value | fail-safe, discarded rather than rendered | [`apps/worker/src/productName.ts:30`](../../../apps/worker/src/productName.ts) `return value && KNOWN.has(value) ? value : null;` |
| `localStorage` unavailable in any writer | fail-open in-memory, the kernel stays authoritative | [`apps/worker/src/theme.ts:206`](../../../apps/worker/src/theme.ts) `localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(value));` |
| Dev bench with `BOLTRIG_BENCH_TOKEN` unset | fail-OPEN, the guard is not installed at all | [`apps/worker/vite.config.ts:79`](../../../apps/worker/vite.config.ts) `if (!token) return;` |

## 10. What is proven

### 10.1 The invariants that bind this area

Six `WRK-*` and thirty-six `SEC-WRK-*` invariants exist in `tests/invariants.yaml`.
The ones whose PROOF reads Worker source rather than kernel behaviour are:

| invariant | what it binds here | proving test |
|---|---|---|
| WRK-01 | one supported first-party client, the OpenWorker baseline attributed, `realtime_voice` a narrow amendment | [`tests/security/test_worker_surface_boundary.py:340`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_only_decision_is_landed_with_attribution():` |
| WRK-02 | Worker is the default edge presentation and a digest-pinned signed release image | [`tests/security/test_worker_surface_boundary.py:368`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_is_the_default_edge_presentation():` |
| WRK-03 | the built surface has a gating quality acceptance | [`tests/security/test_worker_surface_boundary.py:388`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_built_artifact_has_a_gating_build_acceptance():` |
| WRK-04 | audit anchor evidence is preserved rather than collapsed to a green label | [`tests/security/test_worker_surface_boundary.py:403`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_preserves_audit_anchor_evidence_and_labels_its_strength():` |
| WRK-05 | non-HTTP subsystems are ledgered across discover, configure, operate, observe, recover | [`tests/security/test_worker_surface_boundary.py:422`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_parity_includes_every_non_http_lifecycle_dimension():` |
| WRK-06 | every manifest field, fleet task, CLI command, native command and governed control has a closed lifecycle classification | `tests/security/test_worker_feature_ledger.py`, four tests |
| SEC-WRK-01 | the browser stays a thin cloud client, the desktop has exactly two bounded native seams | [`tests/security/test_worker_surface_boundary.py:58`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_ships_no_openworker_agent_server_or_provider_secret_path():` plus four more |
| SEC-WRK-05 | the browser edge is closed by default while still permitting same-origin voice, in BOTH the Caddy edge and this nginx image | [`tests/security/test_worker_surface_boundary.py:464`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_edge_allows_same_origin_voice_without_opening_browser_capabilities():` |
| SEC-WRK-13 | closed conversations are restore-only and live in Archived rather than Recents | [`tests/security/test_worker_surface_boundary.py:495`](../../../tests/security/test_worker_surface_boundary.py) `def test_worker_renders_closed_conversations_in_archived_as_restore_only():` |
| SEC-WRK-22 | parity is an exact backend-to-SDK-to-component ledger, not a route count | [`tests/security/test_worker_route_ledger.py:46`](../../../tests/security/test_worker_route_ledger.py) `def test_every_http_route_has_an_exact_worker_or_non_ui_classification():` |

**The nature of that proof matters and is stated here rather than assumed.** The
Worker-side assertions in `test_worker_surface_boundary.py` are SUBSTRING checks
over the TypeScript source read as text, for example
[`tests/security/test_worker_surface_boundary.py:209`](../../../tests/security/test_worker_surface_boundary.py) `assert "hasDesktopRuntime() ? <LocalChatView" in route`.
They prove that a named string is present in a named file. They do not execute the
component, and they do not check that the file is mounted by a route.

The corpus guard in that file is a genuine defence against the vacuous-negative
shape: negative assertions run only after the corpus is proven to have at least N
files, and the guard itself is shown failing in three seeded cases, at
[`tests/security/test_worker_surface_boundary.py:40`](../../../tests/security/test_worker_surface_boundary.py) `def test_the_corpus_guard_refuses_an_absent_or_truncated_source_tree(tmp_path):`.

### 10.2 The route ledger and its exact scope

The parity ledger is data, not heuristics: 306 HTTP routes must each be classified
as Worker-operated, indirect or non-UI, at
[`tests/worker_surface_ledger.py:856`](../../../tests/worker_surface_ledger.py) `EXPECTED_ROUTE_COUNT = 306`.
Measured in the pinned tree, `WORKER_ROUTES` holds 252 declarations across 66
source files (bounded: parsed every `_surface(` block in
`tests/worker_surface_ledger.py`, 2026-08-24, pinned tree).

The check each declaration must pass is that the named SDK method exists and the
named file contains the literal text `client.<method>`, at
[`tests/security/test_worker_route_ledger.py:76`](../../../tests/security/test_worker_route_ledger.py) `assert f"client.{surface.sdk_method}" in source.read_text(encoding="utf-8"), (`.
Nothing in that test asserts the file is reachable from a route. See RISK-1502.

### 10.3 The Worker's own suites

125 test files, 1,092 cases, run by `vitest` with no config file: each component
suite opts into a DOM by a per-file pragma, and 82 of the 125 files carry it
(bounded: `rg -c "@vitest-environment" tests src`, 2026-08-24, pinned tree). The
remaining files are pure-module tests that run in node.

Named proofs for the load-bearing behaviours in this spec:

| behaviour | test |
|---|---|
| reattach to the server-selected active run and refresh the durable transcript | [`apps/worker/tests/chatContinuity.test.tsx:491`](../../../apps/worker/tests/chatContinuity.test.tsx) `it("reattaches to the server-selected active run and refreshes the durable transcript", async () => {` |
| a dropped follow offers a CURSOR-PRESERVING reconnect | [`apps/worker/tests/chatContinuity.test.tsx:1118`](../../../apps/worker/tests/chatContinuity.test.tsx) `it("offers cursor-preserving reconnect when live follow drops", async () => {` |
| the voice socket resolves relative in the browser and against the configured origin on the desktop | [`apps/worker/tests/voiceCall.test.tsx:1315`](../../../apps/worker/tests/voiceCall.test.tsx) `it("dials the relative gateway URL on the document origin in the browser", async () => {` |
| a socket that never authenticates times out and releases the microphone | [`apps/worker/tests/voiceCall.test.tsx:1219`](../../../apps/worker/tests/voiceCall.test.tsx) `it("times out a socket that never becomes authenticated and reports released media", async () => {` |
| a capacity refusal releases media and explains itself | [`apps/worker/tests/voiceCall.test.tsx:988`](../../../apps/worker/tests/voiceCall.test.tsx) `it("releases media and explains a bounded-capacity refusal", async () => {` |
| the chunk-recovery reload cannot loop | [`apps/worker/tests/workerErrorBoundary.test.tsx:53`](../../../apps/worker/tests/workerErrorBoundary.test.tsx) `it("stops an automatic reload loop and leaves an explicit recovery action", () => {` |
| a re-pending approval keeps a fresh handle rather than stranding the request | [`apps/worker/tests/exactApprovalFinalizer.test.tsx:22`](../../../apps/worker/tests/exactApprovalFinalizer.test.tsx) `it("keeps a fresh exact approval handle when a stale resource snapshot re-pends", async () => {` |
| a desktop build with no server is named rather than offered sign-in | [`apps/worker/tests/authRecovery.test.tsx:195`](../../../apps/worker/tests/authRecovery.test.tsx) `it("names a desktop build with no configured server instead of offering sign-in", async () => {` |
| the `?theme=` override clamps the palette without writing a preference | [`apps/worker/tests/pageModes.test.tsx:48`](../../../apps/worker/tests/pageModes.test.tsx) `it("clamps the stamped palette without touching the saved preference", () => {` |
| a copied settings URL restores and follows history | [`apps/worker/tests/appSettingsNavigation.test.tsx:84`](../../../apps/worker/tests/appSettingsNavigation.test.tsx) `it("restores a copied settings URL and follows history hash changes", async () => {` |
| the shell rollout boundary keeps navigation, task history and Operations behind their own modules and chunks | [`apps/worker/tests/shellBoundary.test.ts:31`](../../../apps/worker/tests/shellBoundary.test.ts) `describe("shell rollout boundary", () => {` |

### 10.4 What is NOT proven by anything in the tree

- **No test asserts that a component is mounted by a route.** `shellBoundary.test.ts`
  checks that `AppRouteSurface` contains certain dynamic-import strings, which is
  the closest thing, and it names only ChatView, MobileSettings and SearchResults.
- **No end-to-end or browser-driver suite exists in this repository.** The visual
  harness under `tests/visual/` is a manual capture tool plus a manifest freshness
  check, not an assertion about rendered pixels.
- **No accessibility audit runs in the gate.** The CSS parity suites compute
  contrast ratios for a handful of hand-picked colour pairs; there is no axe or
  equivalent sweep.
- **The CSS parity suites assert literal declaration strings**, for example
  [`apps/worker/tests/chatRailParityCss.test.ts:29`](../../../apps/worker/tests/chatRailParityCss.test.ts) `expect(css).toContain("grid-template-columns: minmax(793px, 1fr) auto");`.
  They prove the stylesheet still contains a string, not that the surface renders
  that way.

### 10.5 The mechanical inventory, and what it measures

The per-module census this section's claims rest on is kept beside the spec rather
than inside it, at
[`docs/brownfield-spec/evidence/worker-ui-route-inventory.md`](../evidence/worker-ui-route-inventory.md):
the sixteen routes with the module each mounts, all 335 modules under
`apps/worker/src` with their line counts and the `client.<method>` calls each
makes, the SDK methods no module calls, and the modules with no importer. It is
generated by regex over the pinned tree and states its own three blind spots.

Two measurements from it that bound the rest of this section. **The Worker calls
248 of the SDK client's 258 public methods, from 98 of its 335 modules**; the
eight genuinely uncalled ones are `artifact`, `artifactDownloadUrl`, `getCall`,
`modelProfiles`, `refreshCallMedia`, `requestDeviceFileListLease`,
`searchConversations` and `spawn`. **Conversation search is the deliberate
absence**: the shell offers the command palette instead, and a test asserts the
sidebar never calls it, at
[`apps/worker/tests/consoleSidebar.test.tsx:107`](../../../apps/worker/tests/consoleSidebar.test.tsx) `expect(api.searchConversations).not.toHaveBeenCalled();`,
reinforced by a source-text assertion at
[`apps/worker/tests/shellBoundary.test.ts:47`](../../../apps/worker/tests/shellBoundary.test.ts) `expect(taskListSource).not.toContain("searchConversations");`.

## 11. RISKS

RISK-1500: The `automations` route mounts `RoutinesView`; `AutomationView.tsx`, at 2,870 lines the largest module in the Worker and the only home of workflow DAG, trigger, schedule-occurrence and delivery-receipt authoring, has NO importer in `apps/worker/src` and is rendered only by three test files (bounded: `rg -n "AutomationView" apps/worker/src apps/worker/tests` plus a repo-wide `rg -n "AutomationView"`, 2026-08-24, pinned tree). Its 548-line stylesheet is imported only by it, at [`apps/worker/src/components/AutomationView.tsx:77`](../../../apps/worker/src/components/AutomationView.tsx) `import "./AutomationViewParity.css";`.

RISK-1501: The `account` route renders the settings You pane, at [`apps/worker/src/components/shell/AppRouteSurface.tsx:98`](../../../apps/worker/src/components/shell/AppRouteSurface.tsx) `return <SettingsView section=`. `AccountView.tsx`, and with it AI-key management, developer tokens, sessions, two-factor management, notification routing, the personal agent, activity and export, the privacy-policy evidence card and the active-context switcher, has no importer in `apps/worker/src`, at [`apps/worker/src/components/AccountView.tsx:27`](../../../apps/worker/src/components/AccountView.tsx) `export function AccountView({ onContextChanged }: { onContextChanged?(): void }) {`.

RISK-1502: 39 SDK methods have NO call site in any component that a route mounts, including `mintToken`, `revokeToken`, `revokeSession`, `twoFactorDisable`, `meSessions`, `setAiKey` outside onboarding, `deleteAiKey`, `renameConversation`, `regenerateMessage`, `meExport`, `privacyPolicy`, `switchActiveOrg`, and the whole workflow-trigger family (bounded: for every `client.<m>(` appearing in the eleven unmounted modules, `rg -l "client.<m>\b" src` filtered against that module list, 2026-08-24, pinned tree). Fifty-eight of the 252 `WORKER_ROUTES` declarations name one of those unmounted files, and the ledger test cannot see this because it asserts only that the file contains the literal `client.<method>`, at [`tests/security/test_worker_route_ledger.py:76`](../../../tests/security/test_worker_route_ledger.py) `assert f"client.{surface.sdk_method}" in source.read_text(encoding="utf-8"), (`.

RISK-1503: `docs/WORKER-PARITY.md` claims the Task chat lifecycle includes rename and regenerate. No mounted surface offers either: `renameConversation` and `regenerateMessage` are called only from `ConversationControls.tsx`, which nothing in `src` imports (bounded: `rg -n "rename|regenerate" apps/worker/src` excluding that file returns only unrelated comment text, 2026-08-24, pinned tree). The ledger declares those routes against that file, at [`tests/worker_surface_ledger.py:149`](../../../tests/worker_surface_ledger.py) `"apps/worker/src/components/ConversationControls.tsx",`.

RISK-1504: `InboxHitl.tsx` exports `InboxQueue`, the dedicated approvals inbox, and has no importer in `apps/worker/src`; it is rendered only by two test files. Approvals are still answerable inline in chat and on the phone Today screen, so the capability is not lost, but the ledger's HITL rows point at the unmounted file, at [`tests/worker_surface_ledger.py:584`](../../../tests/worker_surface_ledger.py) `"apps/worker/src/components/InboxHitl.tsx",`.

RISK-1505: Five further modules have no importer at all: `CameraDiscoverySettings.tsx` (118 lines, not referenced even by a test), `settings/OvernightSection.tsx` (207 lines, superseded by `BehaviourSection` plus `OvernightToggle`), `jarvis/JarvisGauge.ts` (50 lines, test-only), `voiceTone.ts` (262 lines, test-only) and `voiceSpectrum.ts` (imported only by `voiceTone.ts`). With the modules above this is roughly 5,700 unreachable TypeScript lines out of 68,446 in `apps/worker/src` (bounded: a per-module importer sweep matching `from ".../<stem>"` and `import(".../<stem>")` across `apps/worker/src`, hand-checked for the two side-effect-import false positives, 2026-08-24, pinned tree).

RISK-1506: `docs/refactoring/ui-has-no-structural-gate.md` states that main moved the channel hooks onto `useControlMutation` with `onPendingDenied`. Neither identifier exists anywhere in the pinned tree except in that sentence (bounded: `rg -n "useControlMutation|onPendingDenied"` over the whole repository, 2026-08-24, pinned tree, one hit, in the document itself), at [`docs/refactoring/ui-has-no-structural-gate.md:76`](../../../docs/refactoring/ui-has-no-structural-gate.md) `moved both onto `.

RISK-1507: All 61 structural-debt exemptions share one expiry date, `2026-12-31`, so the entire ratchet lapses in a single event rather than in graduated steps, at [`docs/refactoring/worker-structural-debt.json:39`](../../../docs/refactoring/worker-structural-debt.json) `"expires": "2026-12-31"`. Twenty-eight files currently exceed the 400-line limit and all twenty-eight are exempt.

RISK-1508: The desktop webview CSP sets `style-src 'self'` with no `unsafe-inline`, at [`apps/worker/src-tauri/tauri.conf.json:28`](../../../apps/worker/src-tauri/tauri.conf.json) `"csp": "default-src 'self'; connect-src 'self' https://boltrig.ai`, while the web image's CSP does allow inline style, at [`apps/worker/nginx.conf:27`](../../../apps/worker/nginx.conf) `add_header Content-Security-Policy `. Twenty files in `apps/worker/src` use React inline `style={{...}}` props, including the routine canvas whose node positions are computed (bounded: `rg -c "style=\{\{" src` returns 20 files, 2026-08-24, pinned tree). Whether the Tauri webview actually blocks those attribute styles was NOT observed; the mismatch between the two policies is the finding.

RISK-1509: On the desktop, the entire local conversation corpus lives in one `localStorage` value capped at 8 MiB, at [`apps/worker/src/localAgentClient.ts:14`](../../../apps/worker/src/localAgentClient.ts) `const MAX_STORED_BYTES = 8 * 1024 * 1024;`, and a save that would exceed the cap THROWS rather than evicting, at [`apps/worker/src/localAgentClient.ts:171`](../../../apps/worker/src/localAgentClient.ts) `if (encodedBytes(encoded) > MAX_STORED_BYTES) {`. There is no export, no server copy and no eviction policy for a full store.

RISK-1510: Thirty-one guards of the form `typeof client.<method> === "function"` exist in `apps/worker/src` (bounded: `rg -o "typeof client\.[a-zA-Z]+ [!=]== \"function\"" src | wc -l`, 2026-08-24, pinned tree). The SDK is resolved from source through a tsconfig path alias and a Vite alias, so in any shipped build every one of those predicates is necessarily true and the typed-unavailable branch behind it is unreachable outside tests, at [`apps/worker/tsconfig.json:22`](../../../apps/worker/tsconfig.json) `"@wlilley93/boltrig-web-sdk": ["../../sdks/web/src/index.ts"]`.

RISK-1511: The Dockerfile comment asserts that published images ship Familiar and Jarvis only, at [`apps/worker/Dockerfile:33`](../../../apps/worker/Dockerfile) `# Published Worker images always ship the stock companion set (Familiar +`, while the registry registers four bodies unconditionally, at [`apps/worker/src/components/characters.ts:357`](../../../apps/worker/src/components/characters.ts) `registerCharacter(ULTRON);`. The comment is stale; the shipped set is four.

RISK-1512: Nothing in the Worker checks `isSecureContext` or the presence of `navigator.mediaDevices` before starting a call (bounded: `rg -n "isSecureContext|mediaDevices" src` returns one hit, the `getUserMedia` call itself, 2026-08-24, pinned tree). On an insecure origin the call fails with the browser's raw exception text rather than a typed refusal, which is the one place in the voice surface without a product-owned message.

RISK-1513: `apps/worker/tests/consoleDensityParityCss.test.ts` contains an assertion that cannot fail, at [`apps/worker/tests/consoleDensityParityCss.test.ts:30`](../../../apps/worker/tests/consoleDensityParityCss.test.ts) `expect(56 + 1).toBe(57);`. It stands inside a test whose other assertions are real, so the suite is not vacuous, but that line proves nothing about the stylesheet.

RISK-1514: The dev bench's token guard is not installed at all when `BOLTRIG_BENCH_TOKEN` is unset, at [`apps/worker/vite.config.ts:79`](../../../apps/worker/vite.config.ts) `if (!token) return;`, and the same dev server carries three unauthenticated write routes, one of which writes a file into the repository and one of which spawns `ssh` to another machine. This is dev-only by `apply: "serve"`, so it never reaches an image, but a dev server bound to a reachable address without the variable is an unauthenticated write and remote-execution surface on the developer's box.

RISK-1515: `SurfaceState` is declared five times in four shapes, and two of the five omit `not-found`, so a 404 from those surfaces is presented as a generic unavailability rather than a missing resource, at [`apps/worker/src/components/EvaluationsView.tsx:23`](../../../apps/worker/src/components/EvaluationsView.tsx) `type SurfaceState = ` and [`apps/worker/src/components/ChannelsView.tsx:28`](../../../apps/worker/src/components/ChannelsView.tsx) `type SurfaceState = `.

RISK-1516: `docs/WORKER-PARITY.md` carries a status date of 2026-07-30, at [`docs/WORKER-PARITY.md:3`](../../../docs/WORKER-PARITY.md) `**Status date:** 2026-07-30`, and is the document the Worker README points readers to for coverage. It is 25 days older than the referent and already disagrees with it in at least the two ways recorded above.

RISK-1517: The README instructs operators to set `BOLTRIG_DESKTOP_DOWNLOAD_URL` when building the web image, at [`apps/worker/README.md:58`](../../../apps/worker/README.md) `Set `. That name is honoured only through the compose arg mapping; a direct `docker build --build-arg` must use `VITE_DESKTOP_DOWNLOAD_URL`, at [`apps/worker/Dockerfile:9`](../../../apps/worker/Dockerfile) `ARG VITE_DESKTOP_DOWNLOAD_URL=""`.

RISK-1518: There is no ESLint configuration in `apps/worker` and `tsconfig.json` enables `strict` but not `noUnusedLocals`, `noUnusedParameters` or `noUncheckedIndexedAccess`, at [`apps/worker/tsconfig.json:10`](../../../apps/worker/tsconfig.json) `"strict": true,`. Nothing in the gate would have flagged the unreachable modules in RISK-1500 through RISK-1505, because each is a whole file rather than an unused symbol.

RISK-1519: Two security-relevant client behaviours are bound by no invariant in `tests/invariants.yaml`. The first is the non-enumerating sign-in failure message, at [`apps/worker/src/components/auth/LoginScreen.tsx:37`](../../../apps/worker/src/components/auth/LoginScreen.tsx) `} catch {`, whose single generic string is the only thing stopping the login form from distinguishing a wrong password from an unreachable server. SEC-AUTH-RECOVERY-01 covers the reset flow, not this one. The second is the deliberate fail-open in the desktop bridge, at [`apps/worker/src/components/auth/useDesktopAccountBridge.ts:33`](../../../apps/worker/src/components/auth/useDesktopAccountBridge.ts) `// Account auth succeeded. A transient device-list failure must not turn`: a bridge that answers ready on ANY thrown `devices()` call is correct for a network blip and is also the branch an attacker who can break that one call would want.

RISK-1520: The `identityStatus` degradation path treats a failed organisation, workspace or overview read as `unavailable` while still rendering the identity that `meSettings` returned, at [`apps/worker/src/components/WorkerGlobalContext.tsx:83`](../../../apps/worker/src/components/WorkerGlobalContext.tsx) `setIdentityStatus(`. The workspace label then falls back to a placeholder string, at [`apps/worker/src/components/WorkerGlobalContext.tsx:68`](../../../apps/worker/src/components/WorkerGlobalContext.tsx) `let workspace = `, so a person can be looking at a shell that names their user correctly while the scope indicator is a guess.

RISK-1521: The automations deep link cannot work in the shipped app and a BEHAVIOURAL test says it can. The mounted `RoutinesView` reads no hash selection at all (bounded: `rg -n "useRouteSelection|location.hash" apps/worker/src/components/RoutinesView.tsx apps/worker/src/components/routine/`, 2026-08-24, pinned tree, no hits), so the second segment of `#/automations/<workflowId>` is inert; the only `useRouteSelection("automations")` in the tree sits in the unmounted module, at [`apps/worker/src/components/AutomationView.tsx:183`](../../../apps/worker/src/components/AutomationView.tsx) `const [selectedWorkflowId, setSelectedWorkflowId] = useRouteSelection("automations");`, and the test that proves the behaviour sets the hash and then renders that component directly, at [`apps/worker/tests/resourceDeepLinks.test.tsx:211`](../../../apps/worker/tests/resourceDeepLinks.test.tsx) `render(<AutomationsView />);`. This is the sharpest form of RISK-1500: not merely dead code, but dead code whose green test reads in a report as coverage of a live route. The parking itself is deliberate and documented, at [`apps/worker/src/components/RoutinesView.tsx:11`](../../../apps/worker/src/components/RoutinesView.tsx) `/** V1 is intentionally conversational: one goal, one trigger, one run chat.`; the surviving coverage claim is not.

RISK-1522: One leg of SEC-WRK-13's proof reads a module the bundle does not import. The invariant's test asserts the restore affordance in `ConversationControls.tsx`, at [`tests/security/test_worker_surface_boundary.py:519`](../../../tests/security/test_worker_surface_boundary.py) `assert "Restore conversation" in controls`, and nothing under `apps/worker/src` imports that file (see RISK-1503). Its other assertions land on `TaskList.tsx`, `useTaskListModel.ts`, `ArchivedSection.tsx`, `ChatView.tsx` and the SDK, all of which are mounted, so the invariant is not vacuous. The finding is narrower and worth keeping separate from RISK-1503: a SECURITY invariant, not only a parity document, is partly anchored to code that cannot render.

## 12. OPEN QUESTIONS

1. **Are the unmounted account, automation and inbox surfaces a deliberate staging
   step or an accidental regression?** The tree contains no comment, decision or
   ledger entry marking them as withdrawn, and the parity documents still claim
   them. What would settle it: the commit that replaced the `account` route body
   with `<SettingsView section="you" />` and the one that replaced `AutomationsView`
   with `RoutinesView`, read together with their PR descriptions. That is history,
   which this corpus is not pinned to.
2. **Does the Tauri webview actually refuse the twenty files' inline styles?**
   Settled only by running the signed desktop build and reading its console, which
   this corpus does not do.
3. **What renders `#/runs` and `#/work` for a person who has never opened the
   command palette?** Nothing in the shipped nav links to them. Whether that is
   intended minimalism or an unfinished nav is a product question the tree does not
   answer.
4. **Is the four-hour session rotation interval aligned with the kernel's session
   lifetime?** The Worker's interval is a client constant; the kernel's expiry was
   not read for this spec. A mismatch would show as an avoidable sign-out.
5. **Which of the 42 stylesheets are still reachable?** `AutomationViewParity.css`
   demonstrably is not. A full CSS reachability sweep was not performed; only the
   modules that import a stylesheet were enumerated.
6. **Does `runEvents` have a mounted consumer?** It is called from
   `chat/ToolReceiptDetails.tsx`, which is inside the chat tree, but the exact
   condition under which that component renders was not traced to a user action.

## 13. Requirements table

| id | statement | status | evidence | invariant |
|---|---|---|---|---|
| BT-REQ-1500 | WorkerRoute is a closed set of sixteen ids and any hash naming none of them resolves to the chat route. | IMPLEMENTED | apps/worker/src/routes.ts:40 "return routes.has(candidate) ? candidate :"; apps/worker/tests/routes.test.ts:11 "keeps the task surface as the default" | - |
| BT-REQ-1501 | A route selection id is rejected unless it decodes to at most 256 characters and occupies exactly the second hash segment. | IMPLEMENTED | apps/worker/src/routes.ts:55 "return id && id.length <= 256 ? id : null;"; apps/worker/tests/routes.test.ts:35 "round-trips bounded selections for every durable Worker resource" | - |
| BT-REQ-1502 | Navigation is a window.location.hash write and every route listener is a hashchange handler; no router library and no history API are used. | IMPLEMENTED-UNTESTED | apps/worker/src/routes.ts:68 "window.location.hash = routeHash(route, selectionId);" (no test asserts the absence of a router; bounded: rg -n "react-router\|history.pushState" apps/worker/src returns nothing) | - |
| BT-REQ-1503 | Every route component and the command palette load as React.lazy chunks behind one Suspense boundary. | IMPLEMENTED | apps/worker/src/components/shell/AppRouteSurface.tsx:157 "function lazyNamed<"; apps/worker/tests/shellBoundary.test.ts:50 "keeps mobile settings and operational evidence behind route-time chunks" | - |
| BT-REQ-1504 | The primary navigation rail exposes five of the sixteen routes; the other eleven are reachable only by hash, palette or in-page link. | IMPLEMENTED | apps/worker/src/components/shell/ShellNav.tsx:5 "const primary: Array<{"; apps/worker/tests/consoleSidebar.test.tsx:173 "maps the console nav onto the real Worker routes" | - |
| BT-REQ-1505 | The command palette carries a destination row for all sixteen routes and every canonical settings section. | IMPLEMENTED | apps/worker/src/components/CommandPalette.tsx:48 "export const workerCommands: Command[] = ["; apps/worker/tests/commandPalette.test.tsx:88 "keeps every canonical settings section reachable from search" | - |
| BT-REQ-1506 | The chat route mounts LocalChatView under a Tauri runtime and ChatView otherwise, and the two lanes never fall through to one another. | IMPLEMENTED | apps/worker/src/components/shell/AppRouteSurface.tsx:71 "return hasDesktopRuntime() ? <LocalChatView"; tests/security/test_worker_surface_boundary.py:188 "test_browser_cloud_and_desktop_local_agent_routes_cannot_silently_cross" | SEC-WRK-01 |
| BT-REQ-1507 | The account route renders the settings You pane rather than an account view. | IMPLEMENTED | apps/worker/src/components/shell/AppRouteSurface.tsx:98 "return <SettingsView section=" | - |
| BT-REQ-1508 | AccountView and the nine account sections it composes have no importer in apps/worker/src and are rendered only by tests. | DEAD | apps/worker/src/components/AccountView.tsx:27 "export function AccountView({ onContextChanged }"; bounded: rg -n "AccountView" over the whole repository returns only that file, apps/worker/tests/accountOrganisationViews.test.tsx and tests/worker_surface_ledger.py | - |
| BT-REQ-1509 | AutomationView, the 2870-line workflow, trigger and schedule authoring surface, has no importer in apps/worker/src and is rendered only by tests. | DEAD | apps/worker/src/components/AutomationView.tsx:182 "export function AutomationsView() {"; bounded: rg -n "AutomationView" over the repository returns only that file, three worker test files and two ledger files | - |
| BT-REQ-1510 | InboxHitl, the dedicated approvals inbox, has no importer in apps/worker/src. | DEAD | apps/worker/src/components/InboxHitl.tsx:17 "export function InboxQueue() {"; bounded: rg -n "InboxHitl" over the repository returns only that file, two worker test files and tests/worker_surface_ledger.py | - |
| BT-REQ-1511 | ConversationControls has no importer, so conversation rename and message regenerate have no mounted affordance. | DEAD | apps/worker/src/components/ConversationControls.tsx:14 "export function ConversationControls({"; bounded: rg -n "rename\|regenerate" apps/worker/src excluding that file returns only unrelated comment text | - |
| BT-REQ-1512 | Five further modules are unreachable: CameraDiscoverySettings, settings/OvernightSection, jarvis/JarvisGauge, voiceTone and voiceSpectrum. | DEAD | apps/worker/src/components/settings/OvernightSection.tsx:48 "export function OvernightSection({ head = true }"; bounded: per-module importer sweep over apps/worker/src matching from and dynamic-import forms, hand-checked for the two side-effect-import false positives | - |
| BT-REQ-1513 | Thirty-nine SDK methods have no call site in any component a route mounts. | DEAD | tests/worker_surface_ledger.py:457 "apps/worker/src/components/AutomationView.tsx"; bounded: for every client.<m>( in the eleven unmounted modules, rg -l over apps/worker/src filtered against that module list | SEC-WRK-22 |
| BT-REQ-1514 | All backend access goes through one BoltrigClient instance; exactly one direct fetch exists and it is inert without VITE_SELF_HOSTED_TTS_ORIGIN. | IMPLEMENTED | apps/worker/src/client.ts:32 "export const client = new BoltrigClient({"; apps/worker/tests/client.test.ts:25 "uses the browser cookie session without an access-token path" | SEC-WRK-01 |
| BT-REQ-1515 | Interactive session authority is the httpOnly cookie plus a double-submit CSRF token sent only on mutating methods. | IMPLEMENTED | sdks/web/src/client.ts:368 "if (csrf && mutating.has(method)) headers.set("; apps/worker/tests/client.test.ts:25 "uses the browser cookie session without an access-token path" | - |
| BT-REQ-1516 | On the desktop shell the four session-issuing SDK calls are replaced by origin-pinned native commands while the rest of the surface is unchanged. | IMPLEMENTED | apps/worker/src/client.ts:41 "if (isDesktop) {"; apps/worker/tests/desktop.test.ts:144 "refuses cross-origin and non-API native requests before invoking Rust" | SEC-WRK-01 |
| BT-REQ-1517 | The desktop fetch shim refuses any URL whose origin is not the configured one or whose path is not under /v1, before invoking native code. | IMPLEMENTED | apps/worker/src/desktopApiTransport.ts:130 "url.origin !== configured"; apps/worker/tests/desktop.test.ts:144 "refuses cross-origin and non-API native requests before invoking Rust" | SEC-WRK-01 |
| BT-REQ-1518 | Every native response-envelope parse failure collapses to one opaque reason and no partial response is constructed. | IMPLEMENTED | apps/worker/src/desktopApiTransport.ts:27 "throw new Error("; apps/worker/tests/desktop.test.ts:153 "rejects malformed native response envelopes and pre-aborted requests" | SEC-WRK-01 |
| BT-REQ-1519 | A desktop build refuses to start unless VITE_API_BASE and BOLTRIG_DESKTOP_API_ORIGIN are both present, canonical, secure and identical. | IMPLEMENTED-UNTESTED | apps/worker/scripts/require-desktop-origin.mjs:44 "throw new Error(\"desktop frontend and native API origins must match exactly\");" (bounded: rg -n "require-desktop-origin" apps/worker/tests returns nothing) | - |
| BT-REQ-1520 | A desktop bundle with no configured API origin renders a named refusal instead of a sign-in form. | IMPLEMENTED | apps/worker/src/components/AuthGate.tsx:136 "if (isDesktop && !configuredApiOrigin()) return <DesktopServerMissing />;"; apps/worker/tests/authRecovery.test.tsx:195 "names a desktop build with no configured server instead of offering sign-in" | - |
| BT-REQ-1521 | The auth gate probes the existing session and routes only two typed 403 details to their own screens; every other failure becomes unauthenticated. | IMPLEMENTED | apps/worker/src/components/AuthGate.tsx:78 "if (detail === "; apps/worker/tests/authRecovery.test.tsx:195 "names a desktop build with no configured server instead of offering sign-in" | - |
| BT-REQ-1522 | The session is rotated every four hours and on every return to visibility, and a 401 re-probes the session before evicting it. | IMPLEMENTED-UNTESTED | apps/worker/src/components/AuthGate.tsx:104 "const timer = window.setInterval(rotate, 4 * 60 * 60 * 1000);" (bounded: rg -n "setInterval\|visibilitychange" apps/worker/tests returns no assertion on this timer) | - |
| BT-REQ-1523 | A failed sign-in reports one generic message that does not distinguish a wrong credential from an unreachable server. | IMPLEMENTED | apps/worker/src/components/auth/LoginScreen.tsx:28 "if (result.status === "; apps/worker/tests/authRecovery.test.tsx:204 "offers recovery from sign-in and keeps the request result generic" | - |
| BT-REQ-1524 | The desktop account bridge fails open to ready when the device list is temporarily unreachable, so a transient failure cannot destroy a valid local key. | IMPLEMENTED | apps/worker/src/components/auth/useDesktopAccountBridge.ts:33 "// Account auth succeeded. A transient device-list failure must not turn"; apps/worker/tests/authRecovery.test.tsx:166 "requires confirmation before replacing a different account's local key" | - |
| BT-REQ-1525 | Onboarding is gated on one kernel settings key equalling one integer version. | IMPLEMENTED | apps/worker/src/onboarding.ts:8 "return settings?.[ONBOARDING_SETTING_KEY] !== ONBOARDING_VERSION;"; apps/worker/tests/onboarding.test.tsx | - |
| BT-REQ-1526 | The live chat transport is server-sent events read from a fetch body; the only WebSocket in the Worker belongs to realtime voice. | IMPLEMENTED | sdks/web/src/client.ts:2633 "async function pumpSseFrames<T>("; apps/worker/src/components/VoiceCall.tsx:618 "socket = new WebSocket(websocketUrl(result.websocket_url));" | SEC-WRK-09 |
| BT-REQ-1527 | A chat send has exactly two outcomes: a 202 queue receipt with no stream, or a 200 SSE stream. | IMPLEMENTED | sdks/web/src/client.ts:2596 "if (response.status === 202) return (await parseResponse(response)) as ChatQueued;"; apps/worker/tests/chatContinuity.test.tsx:904 "attaches a follow when a send is queued behind a turn with no local stream" | SEC-WRK-09 |
| BT-REQ-1528 | The follow stream rejects a frame with a malformed cursor or no event, and rejects a cursor that regresses, ending the stream rather than accepting it. | IMPLEMENTED-UNTESTED | sdks/web/src/client.ts:571 "if (sawFrame && frame.cursor < cursor) {" (bounded: rg -n "cursor regressed\|Invalid chat follow frame" apps/worker/tests sdks returns no test) | SEC-WRK-09 |
| BT-REQ-1529 | A dropped live follow is recovered only by an explicit Reconnect control that replays from the last observed cursor; there is no automatic retry and no backoff. | IMPLEMENTED | apps/worker/src/components/ChatView.tsx:1244 "onClick={() => void reattach("; apps/worker/tests/chatContinuity.test.tsx:1118 "offers cursor-preserving reconnect when live follow drops" | SEC-WRK-09 |
| BT-REQ-1530 | A follow against a conversation with no active run returns an idle result carrying the unchanged cursor rather than raising an error. | IMPLEMENTED-UNTESTED | sdks/web/src/client.ts:551 "if (response.status === 409) {" (bounded: rg -n "409" apps/worker/tests returns no chat-follow assertion) | SEC-WRK-09 |
| BT-REQ-1531 | A truncated replay window is surfaced to the reader as an explicit continuity notice rather than silently dropped. | IMPLEMENTED | apps/worker/src/components/ChatView.tsx:676 "if (frame.replay_truncated) {"; apps/worker/tests/chatContinuity.test.tsx:602 "refreshes governed artifacts and surfaces rejected or withheld live activity" | SEC-WRK-09 |
| BT-REQ-1532 | A route generation counter fences every async chat continuation so an aborted stream cannot be read as a completed turn. | IMPLEMENTED | apps/worker/src/components/ChatView.tsx:180 "const conversationGenerationRef = useRef(0);"; apps/worker/tests/chatContinuity.test.tsx:1040 "keeps conversation B live when an aborted conversation A send settles late" | - |
| BT-REQ-1533 | The kernel creates the call before the browser asks for microphone permission. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:594 "stream = await navigator.mediaDevices.getUserMedia({"; apps/worker/tests/voiceCall.test.tsx:299 "keeps the typed unavailable notice after adopting its text conversation" | SEC-WRK-03 |
| BT-REQ-1534 | A realtime_unavailable call status adopts the text-continuation conversation and opens no socket and no microphone. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:483 "if (result.call.status === "; apps/worker/tests/voiceCall.test.tsx:299 "keeps the typed unavailable notice after adopting its text conversation" | SEC-WRK-03 |
| BT-REQ-1535 | The voice media bearer is delivered in the first WebSocket frame and never appears in the socket URL. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:692 "type: "; apps/worker/tests/voiceCall.test.tsx:1315 "dials the relative gateway URL on the document origin in the browser" | SEC-WRK-03 |
| BT-REQ-1536 | The voice socket URL is resolved against the document in the browser and against the configured API origin in the desktop shell. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:1439 "function websocketUrl(value: string): string {"; apps/worker/tests/voiceCall.test.tsx:1315 "dials the relative gateway URL on the document origin in the browser" | SEC-WRK-03 |
| BT-REQ-1537 | A voice session that does not become ready within fifteen seconds releases the microphone and reports the release. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:90 "const VOICE_READY_TIMEOUT_MS = 15_000;"; apps/worker/tests/voiceCall.test.tsx:1219 "times out a socket that never becomes authenticated and reports released media" | SEC-WRK-03 |
| BT-REQ-1538 | Voice close codes 4429, 4401 and 1013 map to distinct product messages and distinct terminal or reconnectable states. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:1500 "function socketCloseError(event: CloseEvent): VoiceConnectionError {"; apps/worker/tests/voiceCall.test.tsx:988 "releases media and explains a bounded-capacity refusal" | SEC-WRK-03 |
| BT-REQ-1539 | Voice reconnect is a user action that always mints a fresh session through reopenCall; a spent media bearer is never reused. | IMPLEMENTED | apps/worker/src/components/VoiceCall.tsx:506 "async function reconnect() {"; apps/worker/tests/voiceCall.test.tsx:1271 "still reports a dropped socket after reconnecting from a failed end" | SEC-WRK-03 |
| BT-REQ-1540 | Text-chat reply speech is opt-in and reaches the provider only through the governed voice.speak verb on the ordinary dispatch route. | IMPLEMENTED | apps/worker/src/components/chat/useReplySpeech.ts:205 "const result = await client.invoke({"; apps/worker/tests/consoleChat.test.tsx:511 "primes audio on submit and reads a newly completed reply once" | - |
| BT-REQ-1541 | Twenty-six modules share one exact-approval finalizer that clones the route input, re-reads the approval state before replay, and never treats consumed as applied. | IMPLEMENTED | apps/worker/src/components/ExactApprovalFinalizer.tsx:157 "async function continueExact() {"; apps/worker/tests/exactApprovalFinalizer.test.tsx:22 "keeps a fresh exact approval handle when a stale resource snapshot re-pends" | SEC-WRK-32 |
| BT-REQ-1542 | A governed response body carrying no run_id and a denied, error, unavailable or degraded status is decoded as a refusal and never as a success. | IMPLEMENTED-UNTESTED | apps/worker/src/components/ExactApprovalFinalizer.tsx:37 "export function governedRouteRefusal(" (bounded: rg -n "governedRouteRefusal" apps/worker/tests returns no direct test) | SEC-WRK-32 |
| BT-REQ-1543 | WorkerGlobalContext is the only React context in the application and carries identity plus a three-state load status. | IMPLEMENTED | apps/worker/src/components/WorkerGlobalContext.tsx:17 "export interface WorkerIdentity {"; apps/worker/tests/globalWorkerContext.test.tsx:171 "does not poll a global approval queue" | - |
| BT-REQ-1544 | There is no shared query cache and no store library; every route view owns its fetch, its load state and its staleness fencing. | IMPLEMENTED-UNTESTED | apps/worker/src/components/ParityViews.tsx:34 "type SurfaceState = " (bounded: apps/worker/package.json lists react, react-dom, react-markdown, remark-gfm and the web SDK as the only runtime dependencies) | - |
| BT-REQ-1545 | The per-surface load-state union is declared five separate times in two different shapes, and two of the five cannot express not-found. | IMPLEMENTED | apps/worker/src/components/EvaluationsView.tsx:23 "type SurfaceState = "; apps/worker/src/components/ChannelsView.tsx:28 "type SurfaceState = " | - |
| BT-REQ-1546 | Appearance is applied to the document element before React mounts, and a first run with no stored preference and no system hint is dark. | IMPLEMENTED | apps/worker/src/theme.ts:37 "theme: "; apps/worker/tests/appearance.test.ts:60 "gives a first-run visitor dark, without a stored preference or a system hint" | - |
| BT-REQ-1547 | The URL page modes theme and embed clamp the rendered palette and chrome for one page load and never write localStorage or kernel settings. | IMPLEMENTED | apps/worker/src/theme.ts:63 "export function forcedThemeOverride(): WorkerTheme \| null {"; apps/worker/tests/pageModes.test.tsx:48 "clamps the stamped palette without touching the saved preference" | - |
| BT-REQ-1548 | The console mount prefix is derived from the document pathname rather than declared, treating a directory, an index.html and an extensionless path as a mount. | IMPLEMENTED-UNTESTED | apps/worker/src/apiOrigin.ts:27 "export function mountPrefix(): string {" (bounded: rg -ln "mountPrefix" apps/worker/tests returns only pageModes.test.tsx, which imports it for theme assertions) | - |
| BT-REQ-1549 | The design token layer is three CSS files imported from the repository docs tree, and the image build copies exactly those three files. | IMPLEMENTED-UNTESTED | apps/worker/src/styles.css:1 "@import"; apps/worker/Dockerfile:32 "COPY docs/design/imported/tokens/colors.css" | - |
| BT-REQ-1550 | The structural gate measures every TypeScript file under apps/worker/src against five limits and refuses to pass on a corpus of fewer than 100 files. | IMPLEMENTED | apps/worker/scripts/check-structure.mjs:23 "const MINIMUM_SOURCE_FILES = 100;"; make worker-structure runs pnpm run test:structure before the live scan | NFR-MNT-07 |
| BT-REQ-1551 | All sixty-one structural-debt exemptions carry the same expiry date, so the whole ratchet lapses in one event. | IMPLEMENTED | docs/refactoring/worker-structural-debt.json:39 "\"expires\": \"2026-12-31\""; bounded: parsed the file, 61 entries, one distinct expiry, 28 files over the 400-line limit and all 28 exempt | NFR-MNT-07 |
| BT-REQ-1552 | The shipped web image serves a same-origin closed CSP, denies camera and geolocation, allows the microphone for self only, and 404s the retired Operator path. | IMPLEMENTED | apps/worker/nginx.conf:27 "add_header Content-Security-Policy "; tests/security/test_worker_surface_boundary.py:464 "test_worker_edge_allows_same_origin_voice_without_opening_browser_capabilities" | SEC-WRK-05 |
| BT-REQ-1553 | The desktop webview CSP forbids inline style while the web image CSP permits it, and twenty modules use React inline style props. | IMPLEMENTED | apps/worker/src-tauri/tauri.conf.json:28 "\"csp\": \"default-src 'self'; connect-src 'self' https://boltrig.ai"; bounded: rg -c "style=\{\{" apps/worker/src returns 20 files | - |
| BT-REQ-1554 | The parity route ledger proves only that a named source file contains the literal client method call, not that any route mounts that file. | IMPLEMENTED | tests/security/test_worker_route_ledger.py:76 "assert f\"client.{surface.sdk_method}\" in source.read_text(encoding=\"utf-8\"), (" | SEC-WRK-22 |
| BT-REQ-1555 | Desktop-local conversations are stored only in one localStorage value capped at 8 MiB, and a save that would exceed the cap throws rather than evicting. | IMPLEMENTED | apps/worker/src/localAgentClient.ts:171 "if (encodedBytes(encoded) > MAX_STORED_BYTES) {"; apps/worker/tests/localChatView.test.tsx | SEC-WRK-01 |
| BT-REQ-1556 | The desktop-local chat surface never calls the hosted chat route and its native events are projected into the same ChatEvent vocabulary as the cloud stream. | IMPLEMENTED | apps/worker/src/localAgentClient.ts:207 "export function localEventToChatEvent(event: LocalAgentEvent): ChatEvent \| null {"; tests/security/test_worker_surface_boundary.py:188 "test_browser_cloud_and_desktop_local_agent_routes_cannot_silently_cross" | SEC-WRK-01 |
| BT-REQ-1557 | Transcript markdown is rendered with remark-gfm only, with no raw-HTML plugin and no dangerouslySetInnerHTML anywhere in the source. | IMPLEMENTED-UNTESTED | apps/worker/src/components/chat/OrderedWorkTranscript.tsx:128 "<ReactMarkdown remarkPlugins={[remarkGfm]}>" (bounded: rg -n "rehype\|dangerouslySetInnerHTML" apps/worker/src returns nothing) | - |
| BT-REQ-1558 | Exactly three VITE_ variables are read anywhere in the source and no import.meta.env.DEV, MODE or PROD branch exists, so the shipped bundle has no dev-only path. | IMPLEMENTED | apps/worker/src/apiOrigin.ts:41 "export function configuredApiOrigin(): string {"; bounded: rg -o "import\.meta\.env\.[A-Z_]+" apps/worker/src returns three distinct names | - |
| BT-REQ-1559 | The development bench token guard is not installed when BOLTRIG_BENCH_TOKEN is unset, leaving three dev-only write routes unauthenticated on that server. | IMPLEMENTED | apps/worker/vite.config.ts:79 "if (!token) return;" | - |
| BT-REQ-1560 | Thirty-one SDK-method existence guards are unreachable in a shipped build because the SDK is resolved from source through a path alias. | DEAD | apps/worker/tsconfig.json:10 "\"@wlilley93/boltrig-web-sdk\": [\"../../sdks/web/src/index.ts\"]"; bounded: rg -o "typeof client\.[a-zA-Z]+ [!=]== \"function\"" apps/worker/src returns 31 hits | - |
| BT-REQ-1561 | The Worker quality gate is frozen install, structure, audit, typecheck, vitest and build; it contains no browser-driver stage and no accessibility sweep. | IMPLEMENTED | Makefile:241 "worker-quality: worker-structure"; bounded: rg -n "playwright\|puppeteer\|axe-core\|cypress" apps/worker/package.json Makefile returns nothing | WRK-03 |
| BT-REQ-1562 | The Familiar island is a second build target producing one deterministic self-contained HTML page whose inline script is pinned by SHA-256 in its own CSP. | IMPLEMENTED | apps/worker/familiar-island/vite.config.ts:28 "function inlineIsland(): Plugin {"; Makefile:252 "familiar-island-check:" | - |
| BT-REQ-1563 | The second hash segment of the automations route is inert because the mounted RoutinesView reads no route selection. | DEAD | apps/worker/src/components/AutomationView.tsx:183 "const [selectedWorkflowId, setSelectedWorkflowId] = useRouteSelection(\"automations\");"; bounded: rg -n "useRouteSelection|location.hash" over RoutinesView.tsx and components/routine/ returns nothing | - |
| BT-REQ-1564 | The Worker calls 248 of the SDK client's 258 public methods from 98 of its 335 modules, and eight SDK methods have no call site anywhere in the source. | IMPLEMENTED-UNTESTED | apps/worker/src/client.ts:32 "export const client = new BoltrigClient({"; full census in docs/brownfield-spec/evidence/worker-ui-route-inventory.md tables B and C; no test asserts the census (looked in apps/worker/tests/client.test.ts and tests/security/test_worker_route_ledger.py) | - |
| BT-REQ-1565 | Conversation search is absent from the shell by design and the sidebar is asserted never to call searchConversations. | IMPLEMENTED | apps/worker/tests/consoleSidebar.test.tsx:107 "expect(api.searchConversations).not.toHaveBeenCalled();"; apps/worker/tests/shellBoundary.test.ts:47 "expect(taskListSource).not.toContain(\"searchConversations\");" | - |
