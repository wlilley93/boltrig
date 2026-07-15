# Definition of Done - Boltrig browser console

This document began as the completion ledger for items 1-6 in
`requirements-frontend-experience.md`. That R10-R13 arc established structured run
events, a run drawer, a workflow run canvas, a capability-aware home, registry
visualisation, and the first grouped navigation. Those milestones remain historical
facts; the current console has since replaced the old three-plane information
architecture with a five-zone product shell and broadened the operational surfaces.

**Snapshot:** current uncommitted working tree, 2026-07-15.

**Verification status:** the final whole-tree `make quality` and independent browser
acceptance run for this snapshot pass. Hosted release and credentialed seam evidence
remain separate, as recorded below.

## 1. Product definition

The console is done for a release candidate when a logged-in operator can understand
what is happening, do permitted work, inspect consequences, and recover context
without the browser inventing state or bypassing the kernel. Its primary information
architecture is:

| Zone | Release-candidate experience |
|---|---|
| **Home** | A scoped operational pulse over runtime/component status, recent runs, work in flight, pending decisions, cost/budget pressure, degraded activity, and recent model routing. Every summary links to its owning surface. |
| **Chat** | Persistent scoped conversations with structured streaming, tool and sub-agent activity, inline questions/HITL, stop/reconnect behavior, and conversation management. Structured events are rendered as events, not rewritten as fictional prose. |
| **Runs** | Search/filter over visible work-backed runs plus a global deep-linked inspector for summary, live timeline, execution tree, tools, approvals when present, and bounded audit context. Out-of-scope and unknown ids are indistinguishable. |
| **Build** | Agents, Workflows, Registry, Integrations/Studio, Memory, and Evaluations. Authoring uses caller-scoped discovery and real contracts. Unsupported workflow/code capabilities are not advertised. |
| **Operate** | Hierarchical Work queue, explicit Approvals/requests, Audit & costs, deep Health/readiness, Channels, and Admin. Role gating improves navigation; the server remains authoritative. |

Settings is a utility page outside the five operating zones. The global
`Cmd/Ctrl-K` palette and run inspector remain mounted outside the animated deck so
they are reachable from every surface and retain stable focus/deep-link behavior.

## 2. Interaction definition

The browser-console slice is implementation-complete only when all of these are true:

1. **Truthful data.** Loading, empty, error, forbidden, and non-enumerating not-found
   states are distinct. A panel never substitutes mock success for an unavailable
   endpoint and never promotes a client-side draft to published server state.
2. **Scoped discovery.** Registry, workflow, routing, agent, and integration choices
   come from caller-scoped capabilities and bindings. Noun filters are sent to the
   server. An agent does not request author-only history merely to hide it afterward.
3. **Governed writes.** Mutating authoring and administration HTTP paths resolve to
   `control.*` verbs through the dispatch chokepoint. Compatibility response helpers
   may shape data but may not become a direct store-mutation path.
4. **Safe consequence.** Destructive and high-consequence actions use a two-step
   arm/confirm pattern. Approval, clarification, escalation, and question cards require
   an explicit response; no preselected default can approve work accidentally.
5. **Work context.** Work queue list/project/board modes preserve hierarchy and expose
   owner, source, status, convergence, deep-link detail, children, and bounded audit
   history. Runs and work items cross-link where the server provides identifiers.
6. **Run context.** Any surfaced run id can open the same inspector. SSE reconnects
   from the last observed event, stop is explicit, and absent tool/approval tabs do not
   claim data that was never observed.
7. **Authoring truthfulness.** Workflow Studio exposes only safe control nodes and real
   discovered verbs. The “Ask user” node uses the governed chat contract. Generated
   adapters require review before activation; MCP registration accepts public metadata
   only and keeps credentials server-side.
8. **Memory provenance.** Remembering captures structured owner scope, source kind,
   source reference, and relationships. Forget/erase is explicitly confirmed and can
   target the exact source reference rather than a broad, ambiguous deletion.
9. **Accessibility and resilience.** Keyboard navigation, visible focus, focus traps,
   Escape dismissal, labels, status text, reduced motion, contrast, font scaling, and
   mobile/tablet/desktop layouts survive the supported acceptance flows.
10. **Authority remains server-side.** Dev identity controls are visibly development
    only. Hidden navigation is not authorization, and direct URLs cannot widen scope.

## 3. Surface completion ledger

| Surface | Current working-tree behavior | Final evidence required |
|---|---|---|
| Shell/navigation | Five primary zones, responsive collapsible rail, role-aware sub-navigation, utility Settings, appearance controls, stable hash routes | Desktop/tablet/mobile screenshots and keyboard smoke |
| Command palette | Global navigation and scoped quick access via `Cmd/Ctrl-K` | Keyboard open/search/select/close Playwright flow |
| Home | Real console-overview operational pulse and scoped links | Empty/error/degraded/success unit coverage and browser smoke |
| Chat | Structured turn renderer, tools/sub-agents, inline HITL/questions, stop and conversation context | Stream/reconnect/stop/conversation Playwright scenarios |
| Runs/run inspector | Scoped list/filter, deep links, event stream, audit tree, contextual tabs, non-enumerating missing state | Real-kernel run and child-run inspection scenarios |
| Work queue | Hierarchy, view modes, filters, deep-linked detail, children, audit trail | Scoped 404, hierarchy, filter, and navigation scenarios |
| Approvals/requests | Type/urgency filtering, blocking-first presentation, type-specific endpoints, explicit select then confirm | Approval, rejection, clarification/question, and tamper/failure scenarios |
| Registry/router | Caller-scoped noun/verb/binding view and server noun filtering | Role/scope and filter regression coverage |
| Workflows | Real workflow list/stats/runs, safe node taxonomy, governed publish/schedule/trigger paths, truthful Chat handoff | Draft/publish/run, destructive confirm, and live-run scenarios |
| Integrations/Studio | Skills, router authoring, adapter source/review/activation, bounded MCP registration, workflow authoring | Two-person adapter activation and no-credential-browser-payload scenarios |
| Memory | Browse/remember/forget/erase with structured provenance and arm/confirm | Scope/provenance/erasure regression coverage |
| Audit & costs | Scoped audit search, attributable spend/budgets, run links, bounded details | Filter/export/budget boundary and forbidden-state scenarios |
| Health/Admin/Channels | Readiness and dependency posture plus role-gated governed administration | Fail-closed readiness and role/scope browser scenarios |

“Current working-tree behavior” is not a substitute for the final evidence column.

## 4. Architecture definition

- **The kernel does not learn about the UI.** Panels call stable HTTP/discovery/event
  contracts; policy, grants, HITL, credentials, idempotency, and audit stay below the
  browser boundary.
- **One writer rule.** The dispatch chokepoint remains the governed write path. The UI
  can retain drafts for editing, but only an accepted server mutation changes shared
  state.
- **Structured streaming.** Tool, result, sub-agent, workflow-step, question, HITL,
  and model activity remain typed records. The shared renderers may summarize layout,
  not alter their meaning.
- **Scoped deep links.** Hash routes can identify a surface, work item, workflow, or
  run. Authorization is resolved on the server; a not-found experience does not reveal
  whether an inaccessible resource exists.
- **Dependency discipline.** React Flow remains justified for graph-shaped authoring
  and run views. The bespoke router, small UI kit, and lazy-loaded heavy panels avoid a
  second framework or global state dependency.
- **Performance discipline.** Chat/Markdown and Studio/React Flow stay split from the
  initial shell. The build budget is a gate, not a warning to ignore.

## 5. Gate definition

The front end is not independently “green” if the kernel contract beneath it is red.
The release-candidate acceptance command is `make quality`, which includes:

- Postgres-backed Python tests with coverage, invariants, structure, Ruff, and strict
  mypy;
- UI dependency audit, typecheck, unit coverage, production build, and Chromium
  Playwright against the real in-memory kernel;
- site dependency audit, strict lint, unit coverage, and production build;
- Compose/release configuration, production-doctor fixture, migration parity, and
  source security gates.

Frontend-specific acceptance must additionally exercise:

- Home, Chat, Runs, Build, and Operate at desktop, tablet, and mobile widths;
- keyboard-only primary navigation, command palette, modal/drawer focus, and Escape;
- destructive arm/confirm and approval select/confirm flows;
- Chat stop/reconnect/conversation management;
- work/run deep links and non-enumerating out-of-scope states;
- workflow draft/publish/run and adapter review/activation;
- accessible names, contrast/reduced-motion settings, and bundle budget.

## 6. Honest external seams

These are not browser placeholders, but their end-to-end activation is deployment
work. The UI must render bounded unavailable/degraded states until the environment is
provided:

- a live Hatchet engine for durable multi-worker and resumed execution;
- a real OIDC IdP and production login/session/2FA/de-provisioning policy;
- live model gateway/provider credentials and an on-box sensitive-model route;
- third-party adapter/MCP services with server-held credentials;
- live Mem0/Cognee/pgvector projections selected by the deployment;
- the sandboxed Pi runtime and stack-owned tool receipts, including reasoning/event
  streaming where enabled;
- Cloudflare/Azure/TLS/network/monitoring configuration and off-box backup credentials;
- hosted branch protection, release signing identity, registry, and admission policy.

`make live-check` records the integration legs that can be exercised. Credential-based
skips must be reported as skips; they are neither an offline failure nor proof that the
seam is live.

## 7. Verification record

Populate after implementation stops changing. Keep command output with the release
evidence and update counts rather than carrying them forward from an earlier arc.

| Field | Result |
|---|---|
| Candidate branch / SHA | `chokepoint/g2-ai-keys-2026-07-13` / `52820b2` plus the user-owned uncommitted working tree |
| UI typecheck / unit coverage / build | PASS: 43 files / 205 tests; production build; initial entry 358.52 kB (98.30 kB gzip) |
| Real-kernel Playwright | PASS: 18/18, including approval, adapter activation, modal stacking, deep links, and six axe surfaces |
| Manual desktop/tablet/mobile + keyboard/a11y smoke | PASS: desktop, 834x1112, and 390x844; palette/run focus ownership; non-enumerating run state; no browser console warnings/errors |
| Full `make quality` | PASS: backend 780 passed / 11 skipped at 80.70%; UI, site, Compose, doctor, migration, and source-security gates passed |
| `make live-check` pass/skip ledger | 4 passed, 15 skipped for absent deployment credentials/services; skips are listed in the captured run output |

## 8. Historical R10-R13 foundation

The original six-item ledger closed a narrower front-end experience arc:

1. dispatch/spawn event backbone with run-keyed credential-free events;
2. hash router and global run drawer;
3. workflow live-run canvas driven by `workflow_step` events;
4. capability-aware Home;
5. noun/verb/binding registry canvas;
6. grouped navigation, Dev console, and run-filtered insight.

That work remains the foundation. The current five-zone IA, global inspector/palette,
operational Home, Runs explorer, hierarchical Work queue, explicit approval handling,
broader Studio, Health, and governed admin surfaces supersede the old claim that the
product is adequately described by three planes or six backlog items.
