# Proposal: Boltrig v2 control plane

Status: IMPLEMENTATION STARTED.

This is the v2 plan for using Boltrig as the durable control plane around the
chosen stack: Herdr, Mastra, Hatchet, Rivet AgentOS, OpenCode, Browser CLI,
Mem0, Bifrost, Langfuse, and MCP through the kernel.

## Chosen stack

| Category | Choice | Boltrig responsibility |
| --- | --- | --- |
| Browser interface / operator cockpit | Herdr | Primary operator surface, panes/tabs/sessions, live agent visibility |
| Agent orchestration framework | Mastra | Agent graph semantics, phase/agent planning, workflow composition |
| Durable workflow execution | Hatchet | Durable state, retries, pause/resume, child task fan-out |
| Agent runtime / sandbox | Rivet AgentOS | Isolated runtime boundary for non-coding/tool agents |
| Coding agent | OpenCode | Code edits, repo navigation, shell/tool use under scoped policy |
| Browser automation | Browser CLI | Governed browser tasks and page automation |
| Memory | Mem0 | Semantic memory, scoped recall, governed write-back |
| Model routing | Bifrost | Provider/model selection, cache policy, routing telemetry |
| Observability | Langfuse | Model/run traces, latency, token and cost analytics |
| Tool protocol | MCP -> Kernel | All tools enter through the governed kernel chokepoint |

## Target shape

```text
Herdr cockpit
  -> Boltrig API / MCP
    -> kernel policy: grants, HITL, budgets, audit
    -> Mastra orchestration contract
    -> Hatchet durable execution
    -> runtime adapters
       -> OpenCode for coding agents
       -> Rivet AgentOS for sandboxed tool agents
       -> script for deterministic jobs
    -> host-control adapters
       -> Herdr panes/tabs/sessions
       -> RunPod start/stop/health
    -> browser automation
       -> Browser CLI
    -> memory adapter
       -> Mem0
    -> model gateway
       -> Bifrost / vLLM / hosted APIs
    -> observability
       -> Langfuse + audit log
```

## Ownership and overlap rules

| Concern | Owner | Secondary / overlap | Rule |
| --- | --- | --- | --- |
| Live operator view | Herdr | `/console` static page | Herdr owns panes/tabs/sessions; `/console` is a companion status/action surface. |
| Agent graph shape | Mastra | Hatchet | Mastra plans phases, agents, routing, and prompts; Hatchet persists execution. |
| Durable state | Hatchet | Mastra | Hatchet owns retries, waits, child tasks, concurrency, and resume state. |
| Sandbox/runtime | Rivet AgentOS | OpenCode, Browser CLI | Rivet isolates tool/browser/dev-server agents; OpenCode remains the coding process. |
| Code work | OpenCode | Rivet AgentOS | OpenCode edits repos and runs coding tools under scoped policy. |
| Browser work | Browser CLI | Rivet AgentOS | Browser CLI drives pages; Rivet supplies the sandbox where needed. |
| Operational memory | Mem0 | Cognee | Mem0 is default recall; Cognee enriches graph/corpus memory. |
| Memory authority | Kernel ledger | Mem0, Cognee, native engines | Backends are projections; the kernel ledger owns scope, provenance, erasure, and audit. |
| Model routing | Bifrost | Langfuse | Bifrost chooses providers/models and cache/failover policy. |
| Observability | Langfuse | Bifrost, audit log | Langfuse owns traces/evals; Bifrost metrics inform routing; audit remains compliance truth. |
| Tool protocol | MCP -> Kernel | Mastra/OpenCode/Browser CLI tools | Tools are exposed to agents as clients, never as direct ungoverned side doors. |

## Current Compatibility Stack

The current runnable repo still contains legacy/compatibility seams while the v2
adapters are being bound:

| Concern | Current runnable path | V2 target |
| --- | --- | --- |
| General runtime defaults | Hermes-compatible runtime names | Mastra plan -> Hatchet -> Rivet/OpenCode workers |
| Sandboxed tool agents | Pi sidecar compatibility path | Rivet AgentOS |
| Durable phased workflows | In-repo Ultracode workflow contract | Mastra graph compiled to Hatchet tasks |
| Operational memory | Local/native store-backed memory | Mem0 primary projection |
| Deep memory | Cognee optional engine | Cognee secondary graph/corpus projection |
| Observability | Audit-derived model telemetry | Langfuse traces plus audit compliance log |

Compatibility seams are allowed to stay runnable, but they are not allowed to
own new v2 responsibilities. New work should bind the v2 target behind the same
kernel contracts rather than expanding the legacy path.

This is not a literal nested process chain. Boltrig coordinates services through
thin seams. Herdr is the operator cockpit, Mastra owns the agent-orchestration
shape, Hatchet owns durable execution, Rivet AgentOS owns the sandbox boundary,
OpenCode remains the coding runtime, Mem0 is the semantic-memory provider,
Bifrost routes models, Langfuse observes model/runtime behaviour, Cognee remains
available for graph enrichment, and the kernel remains the one governed
chokepoint for verbs and credentials.

## Implemented in this pass

- `opencode` is now a fleet runtime kind.
- `OpenCodeRuntime` runs `opencode run --format json`.
- OpenCode can attach to a warm `opencode serve` URL by using the model
  endpoint `base_url`.
- OpenCode auto-approval is explicit opt-in, not the default.
- OpenCode runtime failure degrades instead of crashing the fleet.
- OpenCode now gets scoped Boltrig MCP connection details through
  `BOLTRIG_MCP_URL`, `BOLTRIG_MCP_TOKEN`, and `BOLTRIG_MCP_SERVER_NAME` when an
  MCP URL is configured; the token is redacted from captured output and revoked
  after the run.
- `boltrig opencode-plugin install --dir .opencode` writes a project-local
  OpenCode plugin that consumes that scoped MCP handoff and exposes
  `boltrig_mcp_status`, `boltrig_mcp_list`, and `boltrig_mcp_call` tools without
  mutating global OpenCode config or embedding tokens.
- Timed-out OpenCode child processes are terminated before the runtime returns,
  so a stale process cannot keep editing after its scoped MCP token is revoked.
- Spawned child contexts preserve the parent workspace, IP address, and
  user-agent so MCP-originated audit rows keep the same provenance depth.
- `GET /v1/platform/status` exposes authenticated, redacted status snapshots for
  Herdr/OpenCode/RunPod style components without polluting run SSE streams.
- The sample manifest includes an `opencode-ornith` endpoint and
  `opencode-worker` capability.
- Compose-backed OpenCode runs use `BOLTRIG_OPENCODE_HOME` so config, data,
  state, and any project-local plugin cache live in the stack volume rather than
  a developer user's OpenCode home.
- `herdr` is now a builtin governed adapter with snapshot/list/read/create/split
  and pane-run verbs.
- Compose-backed Herdr control uses `BOLTRIG_HERDR_HOME` so Herdr config,
  sockets/logs/state, and sessions are stack-owned and never depend on a
  developer user's Herdr profile.
- Compose-backed Browser CLI uses `BOLTRIG_BROWSER_CLI_HOME` so Browser Use auth,
  session, cache, and profile state stay in the stack volume instead of a
  developer browser profile.
- The fleet image now ships `browser-use==0.13.3` in an isolated hash-locked tool
  venv with `/usr/local/bin/browser-use` as the compose default binary path.
- Platform status now reports Herdr, OpenCode, and Browser CLI as first-party
  stack tools with stack-owned state posture, without returning state roots,
  binary paths, browser auth/session data, tokens, credentials, or user profile
  locations.
- The production doctor now rejects personal Herdr/OpenCode/Browser CLI state
  roots and missing/personal CLI paths; the operator contract is documented in
  `docs/guide/herdr-opencode-stack-state.md`.
- `runpod` is now a builtin governed adapter for pod list/get/start/stop/restart
  using the documented Runpod REST API.
- `boltrig-ultracode-run` is now registered on the durable task seam. It
  validates phased workflow specs, runs phase agents through `Spawner.spawn`,
  and checkpoints completed phases before later phases run.
- `boltrig-ultracode-agent` is now a separate pure-data child task body.
  Ultracode parent runs fan out phase-agent payloads through that seam, record
  child step boundaries in the local executor, and replay completed phase or
  agent checkpoints rather than repeating work after a restart.
- The live Hatchet path calls the registered `boltrig-ultracode-agent` workflow
  object's public `aio_run` surface from inside the durable parent. The installed
  SDK routes that through its active durable context; if the workflow object is
  absent in a test double, the pure child body runs inline.
- A service-gated live test now exercises `boltrig-ultracode-run` on a real
  Hatchet worker with a shared Postgres store and asserts child/phase
  checkpoints plus child spawn audit rows. It is skipped in the offline suite
  unless `HATCHET_CLIENT_TOKEN` and `DATABASE_URL` are set.
- Ultracode workers now receive compact scoped memory through the governed
  `memory.recall` chokepoint when granted. That path uses the configured primary
  projection, so Mem0-backed recall is used when enabled; unconfigured dev
  stacks keep a direct store fallback. Ultracode still filters owner scopes plus
  provenance keys for workspace, repo, branch, file path, and run type, wraps
  recall as untrusted data in the prompt, excludes sensitive memory unless the
  run is sensitive, and writes generated run summaries back through
  `memory.remember` when granted.
- Bifrost/model profiles are now config-only provider/model/base-url selections.
  A run may set `model_profile`/`ai_profile` such as `code`, `deep`, or `fast`;
  standard data routes through that profile, while sensitive data ignores the
  profile and stays on the local residency endpoint.
- `apply_manifest` exports `runtimes.gateway.model_profiles` into the runtime
  environment when the process has not explicitly set `BOLTRIG_MODEL_PROFILES`.
  The example deployment includes `fast`, `code`, `deep`, `cheap`, and `local`
  presets.
- `GET /v1/model/telemetry` exposes authenticated, scope-filtered model/provider
  telemetry aggregated from audit rows: provider, model, runtime, optional
  profile, calls, tokens, cost, latency, last seen, and status counts. It never
  returns provider URLs, API keys, tokens, or credentials.
- `GET /v1/platform/status` now includes a safe Bifrost/model-gateway snapshot:
  configured/inert posture, cache TTL, profile count, and explicit
  `live_health=not_polled`, without returning gateway URLs, API keys, tokens, or
  credentials.
- Model-gateway status can now perform optional live health polling when
  `BOLTRIG_MODEL_GATEWAY_HEALTH=1` or an internal
  `BOLTRIG_MODEL_GATEWAY_HEALTH_URL` is set. The probe is internal-host-only,
  short-timeout, fail-safe, and extracts only coarse provider/cache counts; it
  never returns gateway URLs, provider keys, tokens, credentials, or raw payloads.
- `GET /v1/console/overview` now exposes the first backend console snapshot for
  desktop, mobile, and TUI clients. It aggregates redacted platform status,
  scoped model telemetry, cost, budgets, recent run summaries, and pending
  approval summaries without returning raw audit detail, transcripts, provider
  URLs, API keys, tokens, or credentials.
- The static site now has `/console`, a responsive operator surface that polls
  `/v1/console/overview`, shows platform/runtime state, spend, approvals, model
  usage, recent activity, and budget burn-down, and stores the API base and
  bearer token only in browser session storage.
- `/console` now has a dedicated model-gateway panel that renders the redacted
  `bifrost` status row: live health, profile/provider counts, cache hit rate,
  hits, and misses. It consumes only sanitized platform metadata.
- The `/console` approval panel can now answer pending HITL requests by POSTing
  to `/v1/hitl/{request_id}/respond` and refreshing the overview.
- This proposal now records the chosen Boltrig v2 stack. The existing Ultracode
  runner remains a compatibility implementation until the Mastra/Rivet/Mem0/
  Langfuse adapters are built behind the same kernel boundaries.
- Memory fanout now has a kernel-led projection seam and per-backend projection
  status ledger. `memory.remember` commits the canonical fact before any backend
  write, then records per-projection `pending` -> `written`/`failed`;
  `memory.recall` uses the primary projection when it supports recall and labels
  the source of every returned fact; `memory.forget` records
  `deleted`/`delete_failed` per projection without making a backend authoritative.
  Fanout can now run inline or through the existing Hatchet/local executor as
  `boltrig-memory-projection` tasks.
- `browser-cli` is now a builtin governed adapter for Browser Use CLI. It exposes
  narrow browser verbs for diagnostics, auth status, page info, opening public
  HTTP(S) tabs, and named remote daemon start/stop; arbitrary Python execution is
  not exposed as a default kernel verb.
- Browser CLI child processes now receive a scrubbed stack environment rather
  than inherited service env. Provider keys and personal `BROWSER_USE_*`
  variables are stripped; Browser Use cloud/profile values flow only from
  explicit `BOLTRIG_BROWSER_CLOUD_*` stack handoff variables when
  `BOLTRIG_BROWSER_CLOUD_POLICY=stack`.
- A thin Mastra-plan compiler now accepts the `boltrig.mastra.v1` contract
  (`phases`, `steps`, or graph `nodes`/`edges`) and compiles it into the existing
  durable phased workflow payload. `boltrig-ultracode-run` can now receive
  `mastra_plan` directly while preserving Hatchet checkpoints, child-agent fanout,
  memory injection, and the spawner policy path.
- `rivet_agentos` is now a fleet runtime kind. `RivetAgentOSRuntime` sends one
  task to a configured AgentOS HTTP endpoint with a run-scoped MCP token, pinned
  model metadata, workspace context, and tool names only; it revokes the token
  after the call and degrades safely when AgentOS is absent.

## Still seams

- Bifrost is wired as the existing model gateway seam plus config-only profiles.
  Live model telemetry is available through the API, and optional internal
  gateway health polling feeds `/v1/platform/status`. Provider health dashboards
  and gateway-specific cache telemetry beyond coarse counts are still pending.
- Mastra now has a thin plan-contract compiler into the existing durable runner,
  but a live Mastra SDK/runtime adapter is still pending.
- Rivet AgentOS now has a runtime seam and `rivet-worker` capability, but a live
  AgentOS service image/deployment and richer sandbox policy are still pending.
- The OpenCode MCP handoff is implemented as scoped runtime environment plus a
  project-local OpenCode plugin. Native `opencode mcp add --url ... --header ...`
  config registration is deliberately not mutated per run.
- Mem0 is selected as the primary semantic-memory projection and Cognee remains
  the optional graph/corpus enrichment projection. The live adapter and queued
  task seams exist; production still needs deployment-specific Mem0/Cognee
  credentials, package installation, and service health checks. Ultracode recall
  now enters through `memory.recall`, so configured Mem0 projections are used
  before the compatibility store fallback.
- Langfuse now has an optional best-effort sink on agent-spawn telemetry. It
  runs after the append-only audit row is persisted, times out/fails closed, and
  emits only bounded metadata. `/v1/model/telemetry` remains audit-derived; a
  production Langfuse deployment still needs credentials, package installation,
  and live smoke tests.
- Browser CLI now has a governed adapter seam plus shipped CLI, stack-owned
  state, doctor checks, and an explicit Browser Use cloud profile handoff
  policy. Richer click/type/extract actions still need a deployment pass.
- Herdr/OpenCode/Browser CLI child processes now receive minimal stack-owned
  environments instead of inherited service/user environments; scoped handoffs
  such as OpenCode's per-run MCP token are the explicit exception.
- The web/mobile console has its first static overview screen. Approval actions,
  workflow launch/retry/stop controls, artefact browsing, and memory context are
  still pending.
- The Hatchet child-run bridge uses the public workflow-object `aio_run` surface.
  A service-gated live test exists, but this backend contract is not fully proven
  until that test is run in a reachable Hatchet + shared Postgres environment.

## Runtime rules

OpenCode is agentic. It can read files and run shell depending on its own
configuration. Therefore:

- Default OpenCode runtime runs without `--auto`.
- `--auto` requires `BOLTRIG_OPENCODE_AUTO=1` or `context.extra.opencode_auto`.
- Tool credentials are never sent as OpenCode arguments.
- Boltrig verb access is exposed through a scoped MCP handoff, following the
  kernel run-token pattern. Set `BOLTRIG_OPENCODE_MCP_URL` or `BOLTRIG_MCP_URL`, or pass
  `context.extra.opencode_mcp_url`, to enable it for OpenCode workers.
- A timed-out OpenCode worker is killed before Boltrig reports degraded status.
- Sensitive data must still use the existing sensitive endpoint routing guard.

## Status contract

`GET /v1/platform/status` is for console status, not execution telemetry.

Response shape:

```json
{
  "generated_at": "2026-07-09T12:00:00+00:00",
  "tenant_id": "acme",
  "workspace_id": null,
  "components": [
    {"id": "runpod", "kind": "gpu", "status": "ok", "message": "warm", "metadata": {}}
  ],
  "runtimes": [
    {"id": "opencode", "kind": "component", "status": "degraded", "message": "", "metadata": {}}
  ]
}
```

Only these statuses are preserved: `ok`, `degraded`, `down`, `unknown`.
Everything else becomes `unknown`. Metadata removes keys containing URL, token,
key, credential, password, bearer, auth, secret, or DSN.

## Model telemetry contract

`GET /v1/model/telemetry` is for console/provider visibility. It reconstructs a
bounded aggregate from the audit log rather than asking a provider directly.

Response shape:

```json
{
  "generated_at": "2026-07-09T12:00:00+00:00",
  "tenant_id": "acme",
  "workspace_id": "ws-1",
  "scope": "all",
  "models": [
    {
      "provider": "cerebras",
      "model": "qwen-3-coder",
      "runtime": "opencode",
      "profile": "deep",
      "calls": 2,
      "tokens": 125,
      "cost_micros": 250,
      "avg_latency_ms": 60.0,
      "last_seen": "2026-07-09T12:00:00+00:00",
      "statuses": {"ok": 1, "degraded": 1}
    }
  ]
}
```

Rows are scoped by the same department/workspace visibility rules as audit/cost
reads. URL/key/token/credential fields are not part of the response.

## Console overview contract

`GET /v1/console/overview` is the safe polling payload for operator clients.
It is not a transcript or event-stream endpoint; it returns bounded summaries
that are already suitable for a desktop screen, mobile screen, or Herdr-side
TUI.

Response shape:

```json
{
  "generated_at": "2026-07-09T12:00:00+00:00",
  "tenant_id": "acme",
  "workspace_id": "ws-1",
  "scope": "all",
  "platform": {
    "components": [
      {"id": "runpod", "kind": "gpu", "status": "ok", "message": "warm", "metadata": {}}
    ],
    "runtimes": [
      {"id": "opencode", "kind": "component", "status": "ok", "message": "", "metadata": {}}
    ]
  },
  "models": [],
  "cost": {
    "total_cost_micros": 250,
    "by_actor": {"opencode-worker": 250},
    "by_status": {"ok": 1}
  },
  "budgets": [],
  "recent_runs": [],
  "approvals": [],
  "counts": {"visible_events": 1, "recent_runs": 1, "pending_approvals": 0}
}
```

The route applies the same department/workspace visibility rules as audit and
model telemetry. It limits list payloads to 200 rows, redacts platform metadata
through the `/v1/platform/status` sanitizer, and does not expose audit `detail`
payloads.

## Memory topology

Boltrig v2 uses kernel-led memory fanout:

1. An agent calls `memory.remember` through MCP -> Kernel.
2. The kernel screens, scopes, audits, and commits the canonical memory event.
3. Projection workers write that same event to Mem0 and, when enabled, Cognee.
   Development can keep this inline; production can set
   `memory.fanout.execution: queued`.
4. Each projection has its own status (`pending`, `written`, `failed`,
   `deleted`, or `delete_failed`).
5. Ordinary recall reads Mem0 first; graph/corpus workflows can request Cognee
   explicitly.

This keeps Cognee useful without making it a second source of truth. It is dual
projection, not active-active memory. The generic projection status ledger,
Mem0/Cognee adapters, and queued task seam are in place; deployment wiring and
health proving remain.

## TODO list

1. Harden the OpenCode operator plugin.
   - Add a live OpenCode smoke test showing the plugin can list and call a
     granted Boltrig MCP tool through `/v1/mcp`.
   - Consider a typed JSON argument schema once OpenCode exposes a stable object
     schema helper for local plugin tools.
   - Keep avoiding per-run global OpenCode config writes.

2. Prove and then replace the current Ultracode compatibility runner.
   - Run and pass the service-gated live Hatchet integration test for
     `boltrig-ultracode-run` spawning `boltrig-ultracode-agent`.
   - Keep the current runner as the durable execution spine while Mastra owns the
     graph-shaped input contract.
   - Replace direct Ultracode submission paths with Mastra-plan submission once
     the operator UI and plugin surfaces are updated.
   - Preserve phase checkpoints and failed/degraded phase handling.

3. Harden memory projection deployment.
   - Add deployment health checks for configured Mem0 and Cognee projections.
   - Mirror governed memory events into Cognee where graph/corpus enrichment is enabled.
   - Keep the current owner-scope filters and untrusted prompt envelope.
   - Expand stored summaries into richer success/failure lessons.

4. Add Mastra/Rivet/Langfuse adapters and finish Browser CLI policy/actions.
   - Compile Mastra agent graphs into Hatchet durable tasks.
   - Prove non-coding tool agents through a live Rivet AgentOS deployment and
     then move default non-coding worker selection from Pi/script to `rivet-worker`.
   - Expand governed Browser CLI actions after the deployment sandbox policy is
     fixed; do not expose raw Python outside that policy.
   - Mirror model/runtime traces to Langfuse without weakening the audit log.

5. Expand console screens.
   - Keep using `/v1/console/overview` as the first polling contract.
   - Desktop: workflow graph, Herdr pane map, OpenCode workers, RunPod/model
     status, costs, approvals, artefacts, memory context.
   - Mobile: status, approve/deny, start/stop/retry, cost/balance, summaries.

6. Add Bifrost live provider health and richer telemetry.
   - Surface `/v1/model/telemetry` in the console.
   - Keep the current safe `/v1/platform/status` gateway live-health metadata
     visible in `/console`.
   - Extend gateway-specific cache/provider metrics where Bifrost exposes richer
     bounded data.
   - Keep provider changes config-only.

7. Add cutover fixtures.
   - Run the same golden tasks through old plugin orchestration and Boltrig v2.
   - Compare artefacts, patches, cost, failures, and operator visibility.

## Acceptance gate

Boltrig v2 is usable when a console-triggered workflow can:

- start or warm the model host,
- compile a Mastra phase/agent plan into the durable Hatchet workflow path,
- launch an OpenCode worker,
- show its status in Herdr and `/v1/platform/status`,
- run through a durable Hatchet workflow,
- run non-coding tool agents through the Rivet AgentOS runtime seam,
- send browser work through the governed Browser CLI adapter,
- recall/write scoped memory through Mem0,
- mirror governed memory events into Cognee when graph enrichment is enabled,
- emit model/runtime traces to Langfuse,
- retry a failed read-only worker safely,
- preserve run artefacts and costs,
- ask for approval before high-consequence actions,
- stop or idle the GPU without losing run state.
