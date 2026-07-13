# Proposal: pinned Boltrig as a host-app agent runtime

Status: DESIGN / not implemented.

This records the transition plan for swapping the Opbox caged agent runtime for
a pinned Boltrig runtime while keeping the Opbox frontend and Opbox kernel as the
product authority. It also captures the reusable Boltrig platform work that will
help future repos embed Boltrig behind their own frontend, auth, billing, kernel,
and tool contracts.

## Short answer

This is moderate, not brutal, if Boltrig replaces only the **agent runtime** and
Opbox keeps the **frontend + kernel authority**.

Opbox already has the right seam: its current caged agent/chat services talk to
the Opbox kernel over MCP (`OPBOX_MCP_URL=http://kernel:8088/mcp`). Boltrig has
the same core pattern: the agent runtime gets only scoped MCP tools, and every
real action re-enters a kernel chokepoint.

The right framing is:

> Swap Hermes agent-chat/drainer for a pinned Boltrig runtime; keep Opbox kernel
> as the verb authority.

The wrong framing is:

> Replace Opbox kernel with Boltrig.

That would duplicate tenancy, authz, audit, DB ownership, frontend contracts, and
business-specific verbs.

## Product phase framing

Use three product phases. The lower-level chat/drainer milestones later in this
document sit inside these phases; they are not a competing phase model.

### Product Phase 1: Boltrig readiness and comms/profile groundwork

Phase 1 is the work this proposal and the communications gateway plan start:
make Boltrig ready to be embedded safely behind a host app.

Scope:

- Host-agent communications gateway contract.
- Agent roster/profile `Comms` or `Exposure` model.
- Surface/channel ownership model: one gateway of record per surface.
- Prompt/profile harvest and golden task fixtures.
- Opbox current-behavior characterization.
- Reusable auth bridge and queue-worker contract shape.
- Compatibility fixture plan for AG-UI, OpenAI-style clients, approvals, billing,
  permissions, and drainer behavior.

Non-goals:

- Do not remove Opbox frontend tabs yet.
- Do not swap the Opbox engine yet.
- Do not migrate workflow automation ownership.
- Do not make Boltrig the Opbox kernel.

Exit gate:

- Boltrig can describe Opbox chat/API/channel exposure and the pinned runtime
  profile without taking production traffic.
- The Opbox kernel boundary is documented well enough that Phase 2 UI work does
  not guess what the engine will later do.

### Product Phase 2: Opbox frontend consolidation and embedded Boltrig UI

Phase 2 is a product/UX cleanup inside Opbox while the existing engine remains
the production engine.

Target information architecture:

- Remove `Agents` as a top-level Opbox tab.
- Move agent-backed concepts into `Automations`, because the user-facing object
  is automation capability and worker execution, not a separate agent product.
- Keep personal/account settings in Settings, but make the AI/agent settings
  model match Boltrig's profile/exposure language.
- Embed or mirror the relevant Boltrig UI surfaces inside Opbox, using Opbox
  shell, auth, org/workspace context, permissions, and routing.
- Make Boltrig-style agent profiles, channels, comms exposure, and automation
  worker profiles visible without forcing users to leave Opbox.

Required frontend outcomes:

- Existing Opbox agent routes redirect or deep-link into the new Automations
  location.
- Existing users can still find agent-backed tasks, automations, approvals,
  settings, logs, and billing.
- Automations shows the execution profile, allowed tools/verbs, approvals,
  schedules, triggers, and channel/chat exposure in one coherent place.
- Settings shows personal/default AI configuration, notification preferences,
  and org-level defaults without duplicating Automations controls.
- The embedded Boltrig UI is functionally synced to Opbox state; Opbox remains
  the product shell and permission source.
- No engine cutover is hidden inside the UI change. The old agent services keep
  serving traffic until Phase 3 gates pass.

Exit gate:

- The Opbox frontend can express the target Boltrig-backed world without the
  Boltrig engine owning production traffic.
- Route redirects, permission gates, support docs, and user-visible terminology
  are settled before runtime behavior changes.

### Product Phase 3: engine and kernel cutover

Phase 3 is the actual swap: move selected Opbox agent execution from the current
Hermes/agent services to the pinned Boltrig stack.

This phase cannot be treated as a simple runtime toggle. The kernel path must be
specified end to end before production traffic moves:

- Opbox remains the product kernel and verb/data authority unless a later
  separate decision says otherwise.
- Boltrig receives only bounded execution credentials and scoped plugin/verb
  access.
- Every Opbox action still goes through Opbox MCP/kernel verbs.
- User, org, workspace, sensitivity, add-on, and role gates are preserved.
- Approval/HITL state has one owner and one verified responder path.
- Billing usage, audit ids, run ids, task ids, and frontend invocation ids
  correlate.
- Conversation, task, workflow, memory, RAG, document, attachment, and citation
  state ownership is explicit.
- The drainer migration is treated as a worker migration, not an automation
  engine migration.
- Rollback is a routing/env flip for each migrated surface or task class.

Exit gate:

- Chat cutover, approval continuation, selected drainer/task execution, billing,
  audit, observability, and rollback all pass parity fixtures before old services
  are retired.

## Current Opbox contract to preserve

Opbox's frontend does not call the agent runtime directly. The Next route
`/api/ai/kernel-chat` checks CSRF/session/org state, resolves the user's kernel
session bearer, budget-gates the turn, and proxies an unbuffered SSE request to:

- `POST <AGENT_CHAT_URL>/chat/stream`
- default `AGENT_CHAT_URL=http://agent-chat:8099`
- `authorization: Bearer <kernel session bearer>`
- `content-type: application/json`
- response `content-type: text/event-stream`

The companion approval route `/api/ai/kernel-chat/approve` performs the same
gates and proxies to:

- `POST <AGENT_CHAT_URL>/chat/approve`
- body shape: `{ threadId, toolId, approved }`
- streamed continuation response

The existing gateway also exposes OpenAI-compatible surfaces:

- `GET /v1/models`
- `POST /v1/chat/completions`

The current compose stack runs two agent-side responsibilities:

- `agent-chat`: serves chat and approval endpoints on `AGENT_CHAT_PORT=8099`.
- `drainer`: claims `agent.run` tasks through Opbox MCP and writes results back
  through kernel verbs.

The Boltrig integration should preserve this product contract first, then improve
internals behind it.

## Communications gateway ruling

Resolved by decision
[`0009-host-agent-communications-gateway.md`](../decisions/0009-host-agent-communications-gateway.md),
bound by the existing
[`0003-channel-gateway-ruling.md`](../decisions/0003-channel-gateway-ruling.md).
Boltrig's current Pi sidecar plus Bifrost path is a runtime/model path, not an
omnichannel communications gateway.

The distinction matters:

- **Pi sidecar** runs the agent in a sandbox and gives it scoped MCP tools.
- **Bifrost** is an OpenAI-compatible model gateway for provider routing,
  caching, and cost control.
- **Hermes gateway / Opbox agent-chat** is a communications facade: it accepts
  frontend or OpenAI-style chat requests, normalizes history, drives the runtime,
  streams AG-UI or OpenAI-compatible output, and hides runtime internals from
  clients.

Replacing Hermes with Boltrig therefore needs a comms gateway/facade layer in
front of Boltrig. Bifrost should not be treated as that layer. Bifrost sits below
the agent runtime; the comms gateway sits above it.

For the Opbox transition, the first comms target is narrow:

- preserve `POST /chat/stream`
- preserve `POST /chat/approve`
- preserve `GET /v1/models` and `POST /v1/chat/completions` if live clients still
  use them
- preserve Opbox auth, budget, billing, AG-UI events, approval continuation, and
  rollback behavior

For future repos, Boltrig should define a reusable **host communications gateway**
contract. It should be separate from Pi and Bifrost and should own channel
ingress/egress concerns: HTTP chat, OpenAI-compatible clients, AG-UI streams,
webhooks, future Slack/Teams/email/voice channels, channel identity mapping,
attachments, delivery retries, rate limits, signed inbound requests, and channel
specific rendering.

Decision 0009 narrows the Opbox cutover: build the HTTP chat/API compatibility
facade now, and leave true omnichannel to the existing decision 0003 hybrid
channel-gateway pattern.

## Runtime choice: Hermes or Pi?

Use **Pi/Boltrig for agent execution** and a **Boltrig host-agent facade** for
chat/API communication. Keep Hermes/current agent services only as legacy
rollback until parity is proven.

The pieces are not interchangeable:

- **Pi/Boltrig runtime:** executes the agent loop, uses scoped MCP tools, and
  remains the target runtime.
- **Bifrost:** routes model/provider calls; it is not a client or channel
  gateway.
- **Boltrig host-agent facade:** accepts Opbox/host chat protocols
  (`/chat/stream`, `/chat/approve`, optional `/v1`) and translates them to the
  runtime.
- **Hermes/current agent-chat:** remains the old path for rollback and reference.
  It is not the new engine unless a later decision deliberately reverses course.

So the chosen path is:

```text
Opbox frontend / clients
  -> Boltrig host-agent facade
    -> Pi/Boltrig runtime
      -> optional Bifrost model gateway
        -> Opbox kernel MCP verbs
```

For future external channels, do not put Slack/Teams/email/voice directly into
Pi. Follow decision 0003: thin kernel routes for webhook/request-response
channels, supervised sidecar for persistent channels, both re-entering the
kernel chokepoint.

## Target architecture

```text
Opbox frontend
  -> existing /api/ai/kernel-chat or agent endpoint
    -> boltrig-host-agent facade
      -> pinned Boltrig chat/runtime
        -> Pi/runtime + optional Bifrost model gateway
          -> Opbox kernel MCP tools
            -> Opbox verbs / DB / audit / authz
```

The Opbox kernel remains source of truth. It supplies verbs as MCP/plugin tools.
Boltrig plans, reasons, streams, and calls tools, but every side effect is still
an Opbox kernel verb.

## Two-track scope

### Reusable Boltrig platform prep

Build these as host-app features, not Opbox-only shortcuts:

1. **Host-agent facade pattern**

   Document and implement a thin facade model where Boltrig can sit behind a
   host app's existing chat API, auth, billing, event stream, and tool catalog.
   The facade owns protocol compatibility; Boltrig owns runtime execution.

2. **SSE event adapters**

   Add output adapters that map Boltrig-native chat/run events to host-native
   stream formats. The first concrete adapter should be AG-UI-compatible because
   Opbox already expects AG-UI-style events.

3. **Host communications gateway contract**

   Define the layer above Boltrig runtime and below host clients. It should
   normalize inbound chat/channel requests, preserve host auth and billing gates,
   translate runtime events to channel events, and expose compatibility surfaces
   such as AG-UI and OpenAI-compatible chat. This is separate from Bifrost, which
   is only a model/provider gateway.

4. **Approval continuation contract**

   Make pause/resume a stable runtime capability: mutating tool call pauses,
   host-readable approval event is emitted, host posts a decision to a resume
   endpoint, and the runtime streams the continuation.

5. **External MCP host-kernel mode**

   Harden MCP consumption for host kernels: dynamic tool discovery, allowlists,
   denial reporting, credential isolation, and tool-catalog drift checks.

6. **Pinned runtime profile**

   Define the package/deployment contract for a pinned Boltrig runtime: image or
   wheel ref, health checks, model-provider config, state config, and rollback
   knobs.

7. **Host-owned conversation mode**

   Allow Boltrig to keep runtime state while the host app remains the transcript,
   billing, and product source of truth.

8. **Worker/drainer profile**

   Add a queue-worker runtime profile for host apps: claim task through host
   verbs, execute via Boltrig, write result/failure through host verbs, never
   direct-write host storage.

9. **Terminal usage metadata**

   Emit normalized terminal run metadata so host apps can meter, bill, audit, and
   reconcile without parsing provider-specific responses.

### Reverse generalisation from Opbox to Boltrig

Resolved by decision
[`0010-opbox-generalisation-and-automation-engine-ownership.md`](../decisions/0010-opbox-generalisation-and-automation-engine-ownership.md).
Generalising from Opbox into Boltrig is allowed, but only at the level of
reusable contracts, fixtures, and adapters. Do not import Opbox's product
database or make Boltrig a hidden second Opbox workflow engine.

Generalise these Opbox patterns into Boltrig:

- host-agent communications facade
- prompt/profile fixture packs and golden tasks
- approval continuation
- queue worker/drainer profile
- external host-kernel MCP mode
- auth bridge that separates request-gate credentials from execution credentials
- billing/usage event contract
- tool catalog drift checks
- operator runbook and observability conventions

Do not generalise these as hard-coded Boltrig assumptions:

- Opbox workflow tables
- Opbox business objects and product-specific verbs
- Opbox frontend-owned conversation tables
- Opbox billing tables
- Opbox-specific workflow scheduler/resume internals

The automation boundary is exclusive: one workflow engine of record per workflow
domain. In the pinned-runtime migration, Opbox remains that engine. Boltrig may
replace `agent-chat` and later the `agent.run` drainer, but the drainer is only a
worker. It is not the workflow engine.

### Opbox-specific transition

Use those reusable pieces to replace Opbox's current Hermes-backed `agent-chat`
first, then replace the Opbox drainer after chat parity is proven.

Opbox remains authoritative for:

- frontend routes and product UI
- kernel verbs and permission semantics
- business records and Postgres tables
- audit as the authority for business actions
- session identity and user/org/workspace membership
- budget/cost ledger and provider credential policy
- human approval policy where Opbox already owns it

Boltrig owns:

- agent runtime loop
- model/tool orchestration
- runtime-only state
- stream-time planning and degradation behavior
- optional fleet/delegation mechanics if Opbox exposes task classes as tools

## Capability gaps against current Opbox agent

| Current Opbox capability | Boltrig support today | Gap | General Boltrig improvement | Opbox dependency |
| --- | --- | --- | --- | --- |
| `POST /chat/stream` AG-UI SSE endpoint | `/v1/chat` with Boltrig-native SSE events | Not drop-in for the frontend proxy | Host-agent facade plus AG-UI event adapter | Required for chat cutover |
| `POST /chat/approve` continuation | HITL primitives and approval routes exist | No Opbox-shaped `threadId`/`toolId` approval continuation | Stable approval continuation contract | Required for mutating verbs |
| Session bearer authorizes chat, bounded agent executes verbs | Principals, grants, and MCP run tokens exist | Needs Opbox session-to-agent bridge without handing human bearer to the loop | Host auth bridge pattern | Required for security parity |
| Cost-ledger tee reads terminal usage from SSE | Runtime events exist | Needs normalized terminal usage metadata | Terminal usage event schema | Required for billing parity |
| OpenAI-compatible `/v1/chat/completions` and `/v1/models` | Boltrig has model/runtime pieces | Needs facade compatibility if Opbox callers still use these surfaces | Optional OpenAI-compatible facade adapter | Required if legacy callers remain |
| Drainer claims `agent.run` tasks by MCP | Boltrig has workers/runtime primitives | Needs Opbox task-claim/writeback profile | Host worker/drainer profile | Required after chat parity |
| Opbox-owned transcript and billing | Boltrig stores native conversations | Needs mode where host owns product transcript | Host-owned conversation mode | Required to avoid dual-write |
| MCP tool consumption from Opbox kernel | MCP consumer adapter exists | Needs allowlists, drift checks, auth-header policy, and failure mapping | External MCP host-kernel mode | Required for production |
| Frontend approval card events | Boltrig emits HITL-related events | Needs event mapping to Opbox UI semantics | AG-UI plus approval event adapter | Required for no frontend redesign |
| Config-only rollback | Boltrig can run separately | Needs deployment profile with both runtimes live | Pinned runtime profile and routing flag | Required for rollout |
| Hermes-style communications gateway | Pi sidecar and Bifrost cover runtime/model traffic only | No omnichannel/API facade equivalent in Boltrig today | Host communications gateway contract | Required for OpenAI/AG-UI/client compatibility beyond native Boltrig |

## What a unified Boltrig AI API may lose

Using Boltrig as the unified AI API is strategically cleaner, but it can drop
practical behavior that Opbox users already rely on if we migrate only the
transport and not the agent contract.

Potential losses:

- **Opbox-tuned system behavior.** The current runtime tells the model it is an
  Opbox governed agent, that tools map 1:1 to audited kernel verbs, to gather data
  with read/list tools before acting, not to fabricate data, and to keep calling
  tools until the task is actually done. Losing that prompt changes behavior even
  if the same tools are available.
- **Hermes cage defaults.** The dev/demo Hermes profile enforces `toolsets:
  [todo]`, no platform connectors, and one kernel MCP server. A Boltrig unified
  API must preserve the equivalent "no native terminal/file/browser/web tools"
  posture unless a separate policy deliberately grants them.
- **Gateway compatibility details.** Hermes/OpenAI clients expect model listing,
  streaming/non-streaming chat-completions, finish reasons, `[DONE]` behavior,
  tool-call chunk shape, and stable model ids. The Boltrig facade must carry these
  if those clients remain live.
- **Context/model quirks.** Hermes gateway applies a runtime context-length
  override for models below Hermes's 64K floor. Boltrig/Bifrost has different
  quirks, including `max_completion_tokens` instead of legacy `max_tokens`. These
  need explicit compatibility handling.
- **Rich legacy chat affordances.** RAG, citations, references, page context,
  attachments, structured object references, and custom UI rendering can regress
  if the unified API only reproduces plain text + tool calls.
- **Approval tone and denial handling.** Current chat denial is fed back to the
  model as a tool result so the assistant acknowledges and continues. A generic
  Boltrig pause/resume must preserve this, not just stop the run.
- **Tool-call pressure.** The current prompt biases the model to actually call
  tools rather than answer from memory. A more generic Boltrig prompt may become
  more conversational but less operational.
- **Provider/client assumptions.** OpenAI-compatible callers, Bifrost, Hermes,
  and Boltrig do not all agree on model ids, usage fields, function-name limits,
  streaming shape, and token-limit names.

The mitigation is to migrate the **agent contract**, not just the runtime.

## Prompt and behavior harvest

Yes: harvest the existing tweak/system prompts before migration. Treat them as
product behavior, not disposable implementation detail.

Harvest artifacts now live under
[`docs/prompts/opbox/`](../prompts/opbox/):

- [`opbox-host-agent-fixtures.yaml`](../prompts/opbox/opbox-host-agent-fixtures.yaml)
  records the current Opbox chat, drainer, approval, cage, context/RAG, object
  reference, and gateway-compatibility fixtures.
- [`golden-tasks.md`](../prompts/opbox/golden-tasks.md) records the parity tasks
  that should pass before any user traffic is routed to the Boltrig facade.

Harvest at least:

- Opbox runtime `SYSTEM_PROMPT` from `opbox-agent/runtime/src/loop.ts`.
- Hermes caged profile defaults from `opbox-agent/config.yaml.example`:
  toolsets, platforms, MCP server shape, turn caps, reasoning effort, streaming,
  and tool progress.
- Gateway compatibility behavior from `opbox-agent/gateway/app.py` and
  `gateway/README.md`: OpenAI surfaces, AG-UI surfaces, context-length override,
  model id, streaming event mapping, and caged-toolset construction.
- Frontend prompt/context behavior from the legacy rich chat path: RAG context,
  citations, references, page context, attachment handling, and structured object
  references.
- Drainer/task prompts and task payload conventions: `payload.goal`, checkpoint
  rationale, final answer shape, failure/requeue language, and autonomy wording.
- Approval wording: how denied actions are represented to the model, how mutating
  verbs are described to users, and how risk class is surfaced.

Store the harvested material as versioned prompt/profile fixtures for the
Boltrig facade:

- `opbox-chat-system`
- `opbox-drainer-system`
- `opbox-approval-resume`
- `opbox-tool-use-policy`
- `opbox-context-and-rag-policy`
- `opbox-object-reference-policy`

Acceptance criteria:

- Golden prompts show the old and new systems choose the same first tool for
  common Opbox tasks.
- Golden prompts show the new system refuses fabrication and gathers data through
  tools.
- Golden approval fixtures show denial and approval continuations match current
  user-visible behavior.
- Golden rich-chat fixtures show citations/references/page context/attachments
  are either preserved or intentionally left on the legacy route.
- Prompt/profile changes are separately versioned from runtime and model changes.

## Breakage-prevention checklist

The transition should be treated as a compatibility project before it is treated
as a runtime upgrade. The safest default is that every existing Opbox user path
keeps working because the frontend, kernel, workflow engine, auth, billing, and
business storage do not move.

### User-facing chat

- Preserve `/api/ai/kernel-chat` and `/api/ai/kernel-chat/approve` as the browser
  contract. Repoint `AGENT_CHAT_URL`; do not make the frontend learn Boltrig's
  native API during the first cutover.
- Preserve the SSE hygiene that prevents hanging streams: unbuffered
  `text/event-stream`, no proxy buffering, terminal `done`/failure event, and
  clean close on abort.
- Preserve frontend event names currently used by the chat hook:
  `text_delta`, `reasoning_delta`, tool start/result events,
  `tool_approval_requested`, `tool_approval_resolved`, and terminal usage/done.
- Preserve the write-approval card behavior: one pending mutating tool at a time,
  approval bound to `threadId` + `toolId`, and denial streamed back as a model
  continuation rather than silently dropping the turn.
- Keep the legacy rich chat route available until parity is proven for RAG,
  citations, references, page context, attachments, and the richer tool catalogue.

### Communications and channels

- Do not confuse Bifrost with the communications gateway. Bifrost may route model
  calls; it does not authenticate users, normalize channel sessions, handle
  channel webhooks, stream AG-UI, map OpenAI-compatible chunks, or own delivery
  retries.
- Keep Opbox's current frontend/proxy path as the primary communications gateway
  for the first cutover.
- If OpenWebUI, LobeChat, or other OpenAI-compatible clients are still live,
  preserve `/v1/models` and `/v1/chat/completions` in the Boltrig facade or keep
  the existing dev/demo gateway for those clients until replaced.
- Treat Slack/Teams/email/voice/webhook ingress as a later omnichannel phase
  unless a production caller is already using it. Each channel needs explicit
  identity mapping, signed inbound verification, rate limits, attachment policy,
  retry/idempotency, and rendering semantics.
- Keep outbound notifications and HITL delivery host-owned until Boltrig has a
  real channel gateway. The runtime may request a human decision; the host decides
  where and how that request is delivered.
- Communications migration is not globally all-or-nothing, but it is exclusive
  per channel/client surface. `AGENT_CHAT_URL`, `/v1` OpenAI-compatible clients,
  Slack, Teams, email, voice, and signed webhooks can migrate separately, but each
  surface must have one gateway of record for auth, identity, idempotency,
  delivery, retries, thread state, and audit.
- Do not let two owning gateways consume the same webhook subscription, socket
  stream, mailbox, phone number, OpenAI client route, or chat thread. Shadowing is
  allowed only when the shadow path cannot ack, send, retry, mutate, or own
  production state.

### Automations and workflows

- Non-agent automations should keep working if the Opbox frontend workflow engine,
  kernel verbs, cron-scheduler, and Hatchet/default runner behavior stay
  unchanged.
- Agent-backed automation steps keep working during early phases because the
  existing Hermes drainer remains deployed. They only move when the Boltrig
  drainer proves the same `agenttask` contract.
- Preserve the automation resume paths. Opbox currently has both Hatchet-driven
  workflow resume and a cron fail-open path hitting `/api/cron/workflows`; the
  agent runtime swap must not remove either.
- Preserve paused workflow semantics. If a workflow is waiting on an `agent_task`
  node, the replacement drainer must checkpoint or requeue so the workflow engine
  can resume exactly as before.
- Do not move workflow ownership into Boltrig. Boltrig may execute an agent step;
  Opbox remains the workflow state machine, scheduler, audit source, and retry
  authority.
- Do not run competing automation engines for the same workflow domain. If
  Boltrig ever becomes the automation engine, that is a later all-engine/domain
  migration with its own routing, state migration, and rollback plan.

### Kernel, orgs, users, and permissions

- The Opbox kernel remains the permission authority. Org membership, workspace
  membership, RLS, role/tier gates, add-on gates, ACLs, and sensitivity checks
  must all be enforced by kernel verbs, not reimplemented in Boltrig.
- Preserve the INV-3 boundary: a human session bearer gates chat access, but the
  model loop does not execute arbitrary MCP calls as that human bearer.
- Preserve separate seats:
  - chat execution uses a bounded chat-agent key, not the drainer key
  - drainer polling uses the agenttask-scoped drainer key
  - task execution uses the run-scoped bearer returned by `agenttask.claimNext`
- Every approval resume must re-check current authorization state, session
  validity, actor identity, workspace/org scope, and the pending tool id before
  the held verb executes.
- Do not rely on dev-identity behavior. Production must fail closed when bearer
  material is missing, invalid, expired, wrong scope, or wrong actor kind.

Phase 3 kernel acceptance matrix:

| Kernel area | Required decision before cutover |
| --- | --- |
| Auth bridge | Which credential gates the browser request, which credential enters the model loop, expiry, revocation, and actor-kind constraints |
| Plugin/verb catalog | Which Opbox kernel verbs are exposed as plugins/tools, their schemas, risk classes, drift detection, and allowlist policy |
| Org and workspace scope | How tenant, org, workspace, matter/project, and sensitivity scope are carried into every tool call |
| User permissions | How owner/admin/member/viewer, oversight, add-on gates, and deactivated users are denied |
| HITL | Who owns pending approval state, who may approve, how stale/duplicate/cross-thread approvals are refused |
| Idempotency | Tool call ids, approval ids, task ids, external channel ids, and retry keys for every side-effecting path |
| Workflow state | Whether the request is chat, automation worker, scheduled run, retry, or paused resume, and which engine owns state |
| Drainer contract | Claim, lease, checkpoint, requeue, failure, timeout, no-task idle, and run-scoped bearer semantics |
| Billing | Pre-stream budget gate, terminal usage event, approval continuation usage, missing-usage failure, and workspace attribution |
| Audit | Correlation across frontend invocation, Boltrig run, Opbox kernel audit row, tool call, task, and provider request |
| Data ownership | Conversations, documents, RAG chunks, references, files, memory, task payloads, and runtime-local state boundaries |
| Secrets | Provider keys, kernel bearers, adapter credentials, signing secrets, and tool definition scrubbing |
| Failure mapping | Denied, degraded, provider failure, MCP failure, timeout, cancellation, disconnect, retry, and rollback behavior |
| Observability | Dashboards, alerts, log redaction, runbook links, and support-safe trace ids |

### Billing, usage, and budgets

- Keep frontend pre-stream budget gating in place. Boltrig should not open a
  provider stream after the frontend route has denied spend.
- Emit terminal usage in the shape the existing cost-ledger tee can record.
- Record both initial chat turns and approval continuations; an approved write
  may trigger another model turn and must be billed.
- Reconcile model/provider, key source, workspace, user, and invocation id after
  the stream closes.
- Treat missing usage as a degraded/failing parity case, not an ignorable detail.

### Data and storage ownership

- Opbox keeps user-visible conversations, workflow runs, task state, business
  objects, audit, files, documents, matters, dashboards, and billing records.
- Boltrig may store runtime-local state needed to resume a turn, correlate a run,
  or debug a failure, but that state must not become the product source of truth.
- Avoid dual-write transcripts. If a projection is needed, make it explicit and
  rebuildable from Opbox source data.
- File and attachment handling must preserve Opbox permissions, storage backend,
  sensitivity labels, and untrusted-content treatment.

### Tool catalog and MCP

- Start with an allowlisted verb subset. Do not expose the whole Opbox tool
  catalogue to a new runtime on day one.
- Add a catalog drift check. If an Opbox verb's schema, risk class, authz class,
  or result shape changes, the facade should surface drift before production use.
- Tool definitions must be secret-scrubbed. Provider keys, bearer tokens,
  internal URLs, signing secrets, and raw credential references must not enter
  model-visible tool descriptions.
- Tool results are untrusted model input. Result summaries can be rendered to the
  UI; raw results should be bounded, scrubbed, and never treated as instructions.
- Denied or unavailable tools must map to clear model-visible and user-visible
  failure events without retry storms.

### Runtime behavior

- Match current loop semantics before improving them: tool call ordering, one
  pending approval at a time, denial continuation, terminal usage, and no
  duplicated final answer.
- Preserve cancellation and disconnect behavior. A dropped browser stream must
  not continue an unbounded model/tool run unless Opbox explicitly wants a
  durable background run.
- Preserve idempotency for tool calls and approvals. Double-clicking approve,
  replaying a request, or reconnecting a stream must not execute a write twice.
- Keep model/provider config pinned and observable. A model change can look like
  a runtime bug to users, so runtime migration and model migration should be
  separate flags.
- Keep network egress narrow: Opbox MCP endpoint plus approved model gateway.

### Observability and support

- Correlate frontend invocation id, Boltrig run id, Opbox task id, kernel audit
  id, model request id, and tool call id.
- Add dashboards for stream errors, tool denials, approval pauses, approval
  mismatches, task requeues, failed checkpoints, provider errors, and cost-ledger
  recording failures.
- Log keys only by stable fingerprint or scope label. Never log bearer values,
  provider keys, tool raw secrets, or uploaded file content.
- Keep enough structured failure data for support to answer: which org/workspace,
  which actor, which tool, which task/run, what failed, and whether it retried.

## Automation and drainer migration

Yes, automations can still work, but only if the migration keeps the current
division of responsibility:

- Opbox owns workflow definitions, schedules, workflow runs, timers, pause/resume,
  audit, and UI.
- The drainer owns only execution of queued `agent.run` work items.
- Boltrig replaces the drainer loop only after it can speak the same `agenttask`
  verbs with the same failure behavior.

### Current drainer contract to preserve

The replacement drainer must:

- poll `agenttask.claimNext` for the configured carrier verb, default
  `agent.run`
- use the standing drainer key only for claim/checkpoint/requeue
- use the per-task `runBearer` returned by `claimNext` for the task's work verbs
- treat missing `payload.goal` as `FAILED` plus `agenttask.requeue`
- checkpoint successful work as `DONE` with output and rationale
- checkpoint failed work as `FAILED` with `lastError`, then requeue when the
  current contract does
- respect the server-side lease and keep the runtime cap below that lease
- never mark a task `DONE` after a partial or failed model/tool run
- expose stats for polls, claims, last task, last poll time, and last error
- idle safely when no task is available

### Migration path for the drainer

1. Leave the existing drainer live while chat migrates.
2. Add a Boltrig drainer command that is env-compatible with the current service:
   `OPBOX_MCP_URL`, `OPBOX_AGENT_KEY`, `OPBOX_DRAIN_VERB`,
   `DRAIN_POLL_SECONDS`, model env, and runtime cap.
3. Test against fixtures and a throwaway task label before claiming real
   `agent.run` tasks.
4. Run a shadow/non-owning comparison where possible. If the kernel cannot offer
   non-owning claims, use a separate test label or cloned fixture tasks rather
   than competing with the production drainer.
5. Move one low-risk `agent.run` task class to Boltrig by label or routing flag.
6. Expand only after checkpoint/requeue/audit/cost behavior matches the current
   drainer.
7. Keep rollback as a service/env switch back to the existing drainer until a
   parity window passes.

This is not an automation-engine migration. The Boltrig drainer is a worker
inside Opbox's workflow/agenttask lifecycle. It must not schedule workflows,
resume workflows, own workflow definitions, or create a second task lifecycle.

## Wide risk register

| Area | What could break | Guardrail |
| --- | --- | --- |
| Frontend chat | Missing or renamed SSE events break rendering or approval cards | Fixture-test byte-level event sequences before routing users |
| SSE/proxying | Streams hang behind Caddy/Next buffering | Preserve no-buffer headers and close every run with terminal event |
| Approval | Double approval or wrong tool id executes a write | Consume pending approval before execution; bind to thread/tool/actor |
| Permissions | Agent sees or calls verbs a user/workspace should not reach | Kernel-enforced bearer scopes plus allowlist tests |
| Org/workspace isolation | Cross-workspace data leaks through tool calls or cached state | Include org/workspace in every token, cache key, log, and audit check |
| Automations | Paused workflow never resumes after agent task | Preserve checkpoint/requeue and cron/Hatchet resume paths |
| Drainer | Lease expires while model run continues | Runtime cap below lease; failed checkpoint/requeue on timeout |
| Billing | Usage missing from approval continuations or failed streams | Terminal usage schema and reconciliation job/check |
| RAG/context | Legacy chat features disappear on kernel-chat cutover | Keep legacy route until RAG/citation/reference parity is tested |
| Attachments/files | Model receives unauthorized or unsafe file content | Host-owned file access; text extraction through Opbox permissions only |
| Comms gateway | Bifrost is mistaken for Hermes-style channel/API gateway | Add host comms facade; keep Opbox proxy/gateway surfaces until parity |
| OpenAI clients | OpenWebUI/LobeChat lose `/v1` compatibility | Preserve `/v1/models` and `/v1/chat/completions` or keep old gateway |
| Omnichannel ingress | Slack/Teams/email/webhooks map to wrong user/org or retry writes | Defer until explicit channel identity, signing, idempotency, and permissions exist |
| Tool schemas | Opbox verb schema drift causes bad model calls | Catalog snapshot, drift check, and schema compatibility tests |
| Secrets | Tool definitions or logs leak keys/bearers | Secret scrubber tests and redacted structured logging |
| Model behavior | New runtime/model changes responses unexpectedly | Pin runtime and model separately; evaluate with golden tasks |
| Idempotency | Retry executes a mutating verb twice | Idempotency keys for tool calls and approval continuation |
| Observability | Support cannot trace a failure | Correlation ids across frontend, Boltrig, kernel, provider, and task |
| Rollback | Cutover requires rebuild or migration reversal | Keep old services deployed and route by env/flag |

## Difficulty estimate

### Proof of concept: 2-4 days

- Run a pinned Boltrig runtime beside Opbox.
- Point it at the Opbox kernel MCP endpoint.
- Expose a small compatibility facade that accepts the Opbox frontend's existing
  chat request and returns the expected SSE stream.
- Prove one read verb and one harmless write verb work end to end.

### Internal alpha: 1-2 weeks

- Add the auth/session bridge from Opbox session to bounded run/agent token.
- Import or discover the Opbox verb catalogue.
- Map Boltrig chat events to the Opbox AG-UI stream shape.
- Add approval pause/resume parity for mutating verbs.
- Replace the agent task drainer path for a limited task class.
- Add regression tests for auth scope, MCP tool visibility, HITL/approval
  surfacing, run cancellation, usage metadata, and degradation.

### Production swap: 3-6 weeks

- Cutover and rollback plan.
- Observability parity.
- Cost/accounting parity.
- Backups and state ownership.
- Failure-mode testing.
- Security review of the token bridge, tool definitions, provider-key handling,
  approval continuation, queue draining, and egress posture.

## Public contracts

### HTTP

The Opbox facade should preserve:

- `GET /health`
- `POST /chat/stream`
- `POST /chat/approve`
- `GET /v1/models` if any callers still depend on it
- `POST /v1/chat/completions` if any callers still depend on it

### Environment

Preserve existing Opbox env names where practical:

- `OPBOX_MCP_URL`
- `OPBOX_AGENT_KEY`
- `AGENT_CHAT_PORT`
- `LLM_PROVIDER`
- `GLM_URL`
- `GLM_API_KEY`
- `ZAI_MODEL`
- `AGENT_MODEL`

Add Boltrig-specific knobs without forcing Opbox frontend changes:

- `AGENT_RUNTIME=boltrig`
- `BOLTRIG_RUNTIME_REF=<image-or-wheel-version>`
- `BOLTRIG_STATE_DSN=<optional-runtime-state-dsn>`
- `BOLTRIG_EVENT_FORMAT=agui`
- `BOLTRIG_HOST_MCP_ALLOWLIST=<comma-separated-tool-prefixes-or-ids>`

### Events

For Opbox chat, the facade must emit the same broad stream behavior the frontend
already consumes:

- run start
- assistant text start/content/end
- tool call start/args/end
- tool result
- approval requested for mutating verbs
- terminal done event with usage metadata
- run finished or failed

Boltrig-native events should remain available for native Boltrig clients, but
host apps should not have to adopt them during a migration.

### MCP

All Opbox business actions must go through Opbox MCP or kernel APIs. The runtime
must not receive Opbox database credentials and must not direct-write Opbox
business tables.

Production MCP consumption must include:

- tool allowlist or generated catalog
- scoped bearer or run token
- expiry and revocation behavior
- clear denial/error mapping
- tool definition secret scrubbing
- catalog drift detection

## Migration execution plan

The product transition has three phases:

1. **Phase 1 - Boltrig readiness:** comms/profile model, host facade contracts,
   fixtures, prompt/profile harvest, and kernel-boundary specification.
2. **Phase 2 - Opbox frontend consolidation:** remove the standalone Opbox
   Agents tab, move agent-backed work into Automations, align Settings, and
   embed or mirror the relevant Boltrig UI inside Opbox without changing the
   engine.
3. **Phase 3 - engine/kernel cutover:** move selected chat and worker/drainer
   execution to pinned Boltrig after the kernel path is specified end to end.

Within that product framing, the engine cutover has four technical workstreams,
and their cutover order is strict:

1. **Foundation:** characterize current Opbox behavior, harvest prompt/profile
   fixtures, and build reusable Boltrig host-agent primitives.
2. **Chat:** replace only the `agent-chat` surface behind `AGENT_CHAT_URL`.
3. **Drainer:** migrate selected `agent.run` work after chat parity is stable.
4. **Retirement:** remove Hermes/current agent services only after rollback,
   observability, billing, approval, automation, and rich-chat decisions are
   proven.

Do not run these as parallel cutovers. Chat can be tested while the old drainer
continues. The drainer can be shadowed while old chat remains available. Hermes
retirement comes last.

Phase 2 frontend consolidation may happen before the engine cutover, but it must
not secretly route production work to the new runtime. It should make Opbox look
and behave like the target Boltrig-backed product while still using the current
engine, so Phase 3 changes behavior behind already-settled surfaces.

### Routing and rollback

Use routing flags, not rebuilds:

- Local/dev: point `AGENT_CHAT_URL` at the Boltrig facade.
- Canary: route one workspace or internal org to Boltrig.
- Expansion: route by workspace/org/user cohort, then by task class for drainer.
- Rollback: repoint `AGENT_CHAT_URL` or runtime flag to the existing
  `agent-chat`; repoint drainer service/env to the existing worker.

Rollback must be exercised at each phase before expanding traffic. A rollback
must not require database reversal, manual transcript repair, or task surgery.

### State handling

- Do not cut over active streams. Let existing streams finish on the runtime that
  started them; route only new turns to Boltrig.
- Do not migrate pending approvals during the first cutover. Pending approvals
  created by the old runtime resume on the old runtime. Boltrig owns only
  approvals it created.
- Do not dual-write user-visible conversation history. Opbox remains source of
  truth; Boltrig runtime state is resumable execution state only.
- If Boltrig durable state is enabled, define retention, backup, erasure, and
  tenant/workspace partitioning before production.
- Existing queued `agent.run` tasks remain with the old drainer until a task
  class is explicitly routed to Boltrig.
- Shadow/comparison workers must not compete for production claims unless the
  kernel offers an explicit non-owning claim/read mode. Otherwise use a test
  label or cloned fixture tasks.

### Engine-swap milestone map

These are engineering milestones inside Product Phase 3. They are numbered `E`
to avoid confusion with the three product phases.

| Milestone | Owns traffic? | User-facing? | Main rollback | Must not break |
| --- | --- | --- | --- | --- |
| E0 Characterize | No | No | None | Existing fixtures prove current behavior |
| E1 Facade primitives | No | No | Disable new service | Native Boltrig `/v1/chat` and Opbox old paths |
| E2 Chat POC | Dev/canary chat only | Yes, limited | `AGENT_CHAT_URL` back to old service | Auth, SSE, billing, approval, audit |
| E3 Chat alpha | Selected chat traffic | Yes | Runtime/workspace flag back to old service | Permissions, RAG/context decisions, prompt behavior |
| E4 Drainer shadow/canary | Selected task labels only | Indirectly | Drainer service/env back to old worker | Workflows, leases, requeues, checkpoints |
| E5 Production/retire | Gradual default | Yes | Keep old services through parity window | Everything above plus support/ops |

### Migration stop conditions

Do not expand traffic if any of these are true:

- Missing or invalid bearer does not fail closed.
- A mutating chat tool can execute without approval where current behavior would
  pause.
- A stale, duplicated, or mismatched approval can execute a write.
- Billing cannot record terminal usage for initial turns and approval
  continuations.
- Cross-workspace, insufficient-role, add-on-gated, or sensitivity-gated fixtures
  differ from current behavior.
- Existing automations show stuck paused runs, rising requeue loops, false
  `DONE`, or audit gaps.
- Prompt golden tasks show the model answering from memory instead of using tools.
- Tool definitions or stream events expose bearer/provider secret material.
- Rollback has not been tested for the current scope.

## Remaining gaps to close

The broad plan is now covered, but these items are still missing implementation
or explicit product decisions:

| Gap | Why it matters | Needed before |
| --- | --- | --- |
| Characterization fixtures are not built yet | We need current byte/shape behavior before replacing it | Product Phase 1 / E2 |
| Golden prompt/eval harness is not built yet | Prompt harvest exists, but parity needs executable checks | Product Phase 1 / E2 |
| Live `/v1` client inventory is not complete | OpenWebUI/LobeChat/API clients may depend on OpenAI-compatible behavior | Product Phase 1 / E2-E3 |
| Exact auth bridge contract is not implemented | Must keep human bearer as gate and bounded chat/drainer/run bearers as execution credentials | Product Phase 1 before Phase 3 |
| Dedicated chat-agent key provisioning needs confirmation | The drainer key can be agenttask-scoped and wrong for chat work verbs | Product Phase 3 / E3 |
| Approval state ownership needs rollout policy | Pending approvals cannot be safely moved mid-flight without a state migrator | Product Phase 1 before Phase 3 |
| Runtime state store policy is undecided | Durable Boltrig state needs retention, backup, erasure, tenant partitioning | Product Phase 3 / E3 |
| Rich chat parity decision is still product-scoped | RAG, citations, references, attachments, and object cards may stay on legacy route or move | Product Phase 2 before Phase 3 |
| Admin/per-conversation system prompt overrides need mapping | Opbox supports workspace/platform and per-chat prompt controls | Product Phase 2 before Phase 3 |
| Scheduled task and manual agent-task prompt handling need mapping | Prompt injection scans, prompt length caps, retry overrides, and task payload shape must remain | Product Phase 3 / E4 |
| Tool catalog drift checker is not implemented | Opbox verb schema/risk/authz changes can silently break model calls | Product Phase 3 / E3 |
| Provider function-call limits need policy | Large tool catalogs may exceed provider limits; capping must be deterministic and safe | Product Phase 3 / E3 |
| Idempotency keys need explicit shape | Approvals, retries, and tool calls must not duplicate writes | Product Phase 3 / E3-E4 |
| Drainer shadow mode depends on kernel support | If no non-owning claim exists, shadow must use labels/fixtures instead | Product Phase 3 / E4 |
| Observability dashboards and alert thresholds are not defined | Support needs run/task/tool/provider/billing correlation and stop signals | Product Phase 3 / E3-E4 |
| Load, cost, and latency testing are not defined | Runtime/model changes can regress cost and responsiveness | Product Phase 3 / E3 |
| Supply-chain pinning/SBOM/admission checks need packaging | Pinned runtime means image/wheel digest, deps, and provenance | Product Phase 3 / E3 |
| Operator runbook is missing | Cutover/rollback/on-call steps must be executable under incident pressure | Product Phase 3 / E5 |
| Security review is not done | Token bridge, egress, logs, secrets, approval resume, and tool catalog need review | Product Phase 3 / E3-E4 |
| User-visible change policy is undecided | If model behavior or rich chat behavior changes, users/support need a known position | Product Phase 2 before Phase 3 |

## Actionable backlog

Use this as the implementation queue. Do not skip the E0 items; they are what
make the later code changes measurable instead of vibes-based.

### E0 backlog: prove current behavior

- [ ] `OPBOX-BOLT-00`: Capture `/chat/stream` SSE fixtures for text-only,
  read-tool, approval-paused write, model failure, and MCP failure turns.
- [ ] `OPBOX-BOLT-01`: Capture `/chat/approve` fixtures for approved, denied,
  wrong `toolId`, missing pending state, stale thread, and missing bearer.
- [ ] `OPBOX-BOLT-02`: Inventory live `/v1/models` and
  `/v1/chat/completions` callers: OpenWebUI, LobeChat, internal clients, tests,
  or none.
- [ ] `OPBOX-BOLT-03`: Capture drainer fixtures for empty queue, missing
  `payload.goal`, successful task, model failure, tool failure, timeout, requeue,
  and duplicate/expired lease.
- [ ] `OPBOX-BOLT-04`: Build permission fixtures for owner/admin/member/viewer,
  workspace membership, oversight, add-on gates, sensitivity gates, and
  cross-workspace denial.
- [ ] `OPBOX-BOLT-05`: Build workflow fixtures for scheduled trigger, manual
  trigger, delay resume, agent-task node, failed agent task, retry, and stuck
  paused-run detection.
- [ ] `OPBOX-BOLT-06`: Convert
  [`docs/prompts/opbox/golden-tasks.md`](../prompts/opbox/golden-tasks.md) into
  an executable prompt/eval harness.
- [ ] `OPBOX-BOLT-07`: Capture billing fixtures for initial turn, approval
  continuation, stream failure, provider failure, and missing usage.
- [ ] `OPBOX-BOLT-08`: Record current prompt/profile hashes from
  [`docs/prompts/opbox/opbox-host-agent-fixtures.yaml`](../prompts/opbox/opbox-host-agent-fixtures.yaml)
  so prompt changes are visible separately from model/runtime changes.

E0 is complete only when a deliberately wrong bearer, wrong workspace, wrong
approval id, missing usage event, and wrong prompt/tool behavior all fail tests.

### E1 backlog: reusable Boltrig primitives

- [ ] `OPBOX-BOLT-10`: Add host-agent facade package/service skeleton with
  health endpoint and pinned runtime reference.
- [ ] `OPBOX-BOLT-11`: Add AG-UI adapter tests for text, reasoning, tool start,
  tool result, approval requested/resolved, error, terminal usage, and stream
  close.
- [ ] `OPBOX-BOLT-12`: Add OpenAI-compatible adapter tests for `/v1/models`,
  non-streaming chat completions, streaming chunks, tool-call deltas, finish
  reasons, usage, and `[DONE]`.
- [ ] `OPBOX-BOLT-13`: Add normalized terminal usage event schema that the Opbox
  cost-ledger tee can read without provider-specific parsing.
- [ ] `OPBOX-BOLT-14`: Add approval continuation contract: pending state,
  one-action-at-a-time behavior, duplicate/stale/mismatched refusal, approval
  resume, and denial resume.
- [ ] `OPBOX-BOLT-15`: Add auth bridge interface separating request gate bearer
  from execution bearer.
- [ ] `OPBOX-BOLT-16`: Add host-worker/drainer interface for
  claim/checkpoint/requeue without Opbox-specific names baked into the generic
  primitive.
- [ ] `OPBOX-BOLT-17`: Add pinned runtime profile validation: image/wheel digest,
  model config, state config, egress allowlist, and rollback flag.

### Product Phase 2 backlog: Opbox frontend consolidation

- [ ] `OPBOX-BOLT-64`: Write the Opbox frontend IA migration spec: remove
  `Agents` as a top-level tab, move agent-backed concepts into `Automations`,
  and define redirects/deep links for every current agent route.
- [ ] `OPBOX-BOLT-65`: Define the Automations target surface: schedules,
  triggers, worker/agent execution profile, allowed verbs, approvals, channel
  exposure, run history, billing, and logs in one place.
- [ ] `OPBOX-BOLT-66`: Define the Settings target surface: personal AI defaults,
  notification preferences, org defaults, and no duplicate editor for automation
  worker profiles.
- [ ] `OPBOX-BOLT-67`: Define how Boltrig UI surfaces are embedded or mirrored
  inside Opbox: shell, routing, auth/session propagation, org/workspace context,
  role gates, CSS/theme constraints, telemetry, and support links.
- [ ] `OPBOX-BOLT-68`: Add frontend parity fixtures for the UI migration:
  existing agent links, automation discovery, approval cards, settings, billing,
  workspace switch, org/user permission denial, and support/debug paths.
- [ ] `OPBOX-BOLT-69`: Confirm Phase 2 does not change runtime ownership:
  existing Hermes/current agent services still serve production chat and drainer
  traffic until Product Phase 3 gates pass.
- [ ] `OPBOX-BOLT-70`: Write the Phase 3 kernel cutover spec from the acceptance
  matrix: auth bridge, plugin/verb catalog, org/workspace/user permissions,
  HITL, idempotency, workflow state, drainer contract, billing, audit, data
  ownership, secrets, failure mapping, observability, and rollback.

### E2 backlog: chat POC

- [ ] `OPBOX-BOLT-20`: Run Boltrig facade beside Opbox and route only local/dev
  `AGENT_CHAT_URL` to it.
- [ ] `OPBOX-BOLT-21`: Connect to `OPBOX_MCP_URL=http://kernel:8088/mcp` with a
  bounded chat-agent execution key.
- [ ] `OPBOX-BOLT-22`: Allowlist one read verb family and one harmless
  approval-gated write verb.
- [ ] `OPBOX-BOLT-23`: Prove frontend chat works without UI changes for text,
  tool call, approval pause, approval resume, denial resume, error, and terminal
  usage.
- [ ] `OPBOX-BOLT-24`: Prove rollback by repointing `AGENT_CHAT_URL` back to the
  existing service while leaving Opbox data untouched.
- [ ] `OPBOX-BOLT-25`: Leave current drainer and workflows untouched.

### E3 backlog: chat alpha parity

- [ ] `OPBOX-BOLT-30`: Implement production auth bridge:
  human/session bearer validates access; bounded chat-agent bearer executes
  verbs; no human bearer enters the model loop as broad authority.
- [ ] `OPBOX-BOLT-31`: Confirm dedicated `OPBOX_CHAT_AGENT_KEY` provisioning and
  scope; do not reuse the agenttask-only drainer key for chat work verbs.
- [ ] `OPBOX-BOLT-32`: Implement tool catalog cache or generated catalog with
  schema/risk/authz drift checks.
- [ ] `OPBOX-BOLT-33`: Implement deterministic provider tool-limit policy for
  large Opbox verb catalogs.
- [ ] `OPBOX-BOLT-34`: Map admin/workspace/per-conversation system prompt
  overrides into the Boltrig facade prompt stack.
- [ ] `OPBOX-BOLT-35`: Decide rich chat parity: keep legacy route for
  RAG/citations/references/page context/attachments/object cards, or migrate
  those features explicitly.
- [ ] `OPBOX-BOLT-36`: Add runtime-state policy: tenant/workspace partitioning,
  retention, erasure, backup, restore, and incident inspection.
- [ ] `OPBOX-BOLT-37`: Add idempotency shape for tool calls and approval
  continuations.
- [ ] `OPBOX-BOLT-38`: Add observability correlation: frontend invocation id,
  Boltrig run id, thread id, tool id, kernel audit id, provider request id, and
  billing invocation id.
- [ ] `OPBOX-BOLT-39`: Run prompt golden tasks and permission fixtures against
  old runtime and Boltrig facade; record accepted diffs.

### E4 backlog: drainer migration

- [ ] `OPBOX-BOLT-40`: Implement Boltrig drainer command/service compatible with
  current env: `OPBOX_MCP_URL`, `OPBOX_AGENT_KEY`, `OPBOX_DRAIN_VERB`,
  `DRAIN_POLL_SECONDS`, model env, and runtime cap.
- [ ] `OPBOX-BOLT-41`: Preserve drainer credential split: standing drainer key
  claims/checkpoints/requeues; per-task `runBearer` executes work verbs.
- [ ] `OPBOX-BOLT-42`: Implement lease-aware timeout behavior below the kernel
  lease; timeout means `FAILED` plus requeue, never false `DONE`.
- [ ] `OPBOX-BOLT-43`: Choose shadow strategy: non-owning claim if the kernel
  supports it, otherwise separate test label or cloned fixture tasks.
- [ ] `OPBOX-BOLT-44`: Canary one low-risk task class by label/routing flag.
- [ ] `OPBOX-BOLT-45`: Verify scheduled workflows, manual workflows, delay
  resumes, agent-task nodes, retries, failed tasks, and stuck-run alerts.
- [ ] `OPBOX-BOLT-46`: Prove rollback by switching the drainer service/env back
  to the current worker without task surgery.

### E5 backlog: production and retirement

- [ ] `OPBOX-BOLT-50`: Write operator runbook for deploy, canary, rollback,
  incident triage, stuck approvals, stuck workflows, rising requeues, billing
  mismatch, and provider failure.
- [ ] `OPBOX-BOLT-51`: Add dashboards and alerts for stream failures, approval
  mismatches, tool denials, auth failures, provider failures, missing usage,
  task requeues, failed checkpoints, and audit gaps.
- [ ] `OPBOX-BOLT-52`: Complete security review of token bridge, execution
  credentials, egress, provider secrets, logs, approval resume, MCP catalog,
  state retention, and drainer behavior.
- [ ] `OPBOX-BOLT-53`: Complete supply-chain packaging: pinned image/wheel,
  dependency lock, SBOM, vulnerability scan, provenance, and admission checks.
- [ ] `OPBOX-BOLT-54`: Run load/cost/latency tests against representative chat
  and drainer workloads.
- [ ] `OPBOX-BOLT-55`: Write user/support-facing change note for any accepted
  behavior differences.
- [ ] `OPBOX-BOLT-56`: Retire old Hermes/current agent services only after a
  parity window with tested rollback and no unresolved stop condition.
- [ ] `OPBOX-BOLT-57`: Record the automation-engine ownership boundary in the
  runbook: Opbox owns workflow scheduling/state/resume during this migration;
  Boltrig owns only the selected agent runtime/worker execution surfaces.
- [ ] `OPBOX-BOLT-58`: Record the communications ownership boundary in the
  runbook: one gateway of record per channel/client surface, with explicit
  rollback and no double-owning webhook/socket/mailbox/client route.

### Reverse-generalisation backlog

- [ ] `OPBOX-BOLT-60`: Extract generic Boltrig contracts from the Opbox harvest:
  host-agent facade, approval continuation, worker/drainer profile,
  prompt/profile fixtures, billing usage event, and auth bridge.
- [ ] `OPBOX-BOLT-61`: Keep Opbox-specific objects out of the generic contracts;
  use adapters for Opbox matter/document/form/table/workflow semantics.
- [ ] `OPBOX-BOLT-62`: Document the automation-engine split rule in Boltrig
  architecture: worker/drainer migration is allowed; competing workflow engines
  for the same domain are not.
- [ ] `OPBOX-BOLT-63`: If a future full Boltrig automation-engine migration is
  desired, write a separate engine-migration plan that moves whole workflow
  domains, including state migration, scheduler authority, rollback, and audit
  reconciliation.

## Engine-swap transition milestones

These milestones run inside Product Phase 3 after Product Phase 1 groundwork and
Product Phase 2 frontend consolidation have made the target surfaces explicit.

### E0: characterize existing Opbox behavior

- Capture fixture streams for `/chat/stream` and `/chat/approve`.
- Record required event names, terminal usage shape, failure shapes, and auth
  behavior.
- Record drainer behavior: claim, execute, writeback, failure, retry, and
  no-task idle behavior.
- Identify whether `/v1/chat/completions` and `/v1/models` are still required by
  live callers.
- Capture a permission matrix for owner/admin/member/viewer, workspace access,
  oversight access, sensitivity gates, and out-of-workspace denial.
- Capture workflow automation fixtures for scheduled trigger, manual trigger,
  delay pause/resume, agent-task node, failed agent task, and retried agent task.
- Capture billing fixtures for initial turn, approval continuation, provider
  failure, and missing-usage failure.
- Harvest prompt/profile fixtures: system prompt, tool-use policy, approval
  resume wording, drainer goal handling, RAG/context policy, attachment policy,
  object-reference policy, model/client quirks, and Hermes cage defaults.

Exit criteria:

- Compatibility fixtures exist.
- Required endpoints and event semantics are known.
- Rollback path to existing `agent-chat` is confirmed.
- Permission and automation fixtures fail against a deliberately wrong bearer or
  wrong workspace, proving the tests catch the dangerous class of bug.
- Prompt/profile fixtures exist and are versioned separately from the Boltrig
  runtime and model configuration.

### E1: build reusable host-agent facade primitives

- Add the host-agent facade skeleton.
- Add the host-agent communications gateway contract from decision 0009:
  protocol compatibility above the runtime, no business policy, no model-provider
  routing, and no channel identity ownership.
- Add AG-UI event adapter tests.
- Add normalized terminal usage metadata.
- Add approval pause/resume contract tests.
- Add pinned runtime profile docs/config validation.
- Add an auth bridge interface that separates request gating from execution
  credentials so host apps can enforce their own "human gates, agent executes"
  policy.
- Add a queue-worker interface that can express claim/checkpoint/requeue without
  depending on Opbox names.

Exit criteria:

- A Boltrig runtime can be wrapped without changing native `/v1/chat`.
- The gateway/facade can expose host-compatible `/chat/stream`, `/chat/approve`,
  `/v1/models`, and `/v1/chat/completions` surfaces without using Bifrost as the
  client-facing gateway.
- Adapter tests prove event mapping for text, tools, approval, terminal usage,
  success, and failure.
- The same facade primitives can represent both interactive chat and queued work
  without sharing broad credentials.

### E2: Opbox chat-only proof of concept

- Deploy Boltrig beside Opbox.
- Point the facade at `OPBOX_MCP_URL=http://kernel:8088/mcp`.
- Route one dev workspace or local stack through the Boltrig-backed
  `AGENT_CHAT_URL`.
- Allow only a small read verb set plus one harmless write verb.
- Keep the existing Opbox drainer on Hermes.

Exit criteria:

- Opbox frontend works without broad redesign.
- A read tool call succeeds through Opbox MCP.
- A harmless write pauses if approval is required, resumes after approval, and
  records Opbox audit.
- Out-of-scope verbs fail closed.
- Existing workflow automations and the existing drainer remain untouched.

### E3: chat alpha parity

- Add the Opbox session-to-bounded-agent bridge.
- Add tool catalog cache or generated catalog with drift check.
- Add approval continuation parity for mutating verbs.
- Add billing usage metadata parity.
- Add cancellation and degraded model/MCP behavior.
- Run both runtimes with a config flag or org/workspace routing flag.
- Preserve separate chat and drainer credentials. Do not let the chat surface
  accidentally run under the agenttask-only drainer key or a broad human bearer.
- Verify RAG/context/reference/attachment behavior before routing users who rely
  on the richer legacy chat route.

Exit criteria:

- Missing or invalid bearer returns 401/inert behavior.
- Terminal usage can be recorded by the existing frontend billing tee.
- Tool definitions and tool results do not leak secrets.
- Rollback is a config flip, not a rebuild.
- Owner/admin/member/viewer and cross-workspace permission fixtures match the
  current runtime.
- Approval continuation works after a fresh HTTP request and refuses stale,
  mismatched, duplicate, or cross-thread approvals.

### E4: drainer shadow mode

- Add a Boltrig worker profile compatible with the current Opbox drainer env.
- Claim `agent.run` tasks through Opbox MCP in a non-owning or shadow mode where
  possible.
- Compare planned actions, final results, failures, latency, and audit outputs
  against the existing drainer.
- Start with one low-risk task class.
- Preserve run-scoped `runBearer` execution. The standing drainer key may claim
  and checkpoint; it must not become the work-verb credential when `runBearer` is
  present.
- Preserve lease behavior: runtime cap below lease, timeout checkpoints as
  failed, and no false `DONE` on partial execution.

Exit criteria:

- Boltrig can claim, execute, write result, write failure, and idle safely.
- Existing Opbox business tables are touched only through kernel verbs.
- Drainer rollback is a service/env switch.
- Scheduled automations, paused workflow resumes, and agent-task nodes all pass
  with the Boltrig drainer in the selected scope.
- Requeue rates, failed checkpoints, and task latency stay within an agreed
  parity window.

### E5: production cutover

- Cut over chat before drainer.
- Roll out by workspace/org/task class.
- Keep Hermes-backed services available through a parity window.
- Retire Hermes only after observed parity for chat, approval, billing, audit,
  degraded behavior, and selected drainer tasks.
- Do not retire the old drainer until workflow automation fixtures and production
  telemetry show no stuck paused runs, no rising requeue loop, and no audit gaps.

Exit criteria:

- Production traffic runs on pinned Boltrig for selected scopes.
- Rollback has been tested.
- Observability and billing reconcile.
- Security review findings are closed or explicitly accepted.

## Test and acceptance plan

Required characterization tests:

- Existing Opbox `/chat/stream` stream starts, emits text/tool/final events, and
  closes.
- Existing Opbox `/chat/approve` resumes a paused mutating tool call.
- Unauthorized or missing session bearer fails closed.
- Existing drainer claim/writeback/failure behavior is captured.
- Existing automation flows cover scheduled trigger, manual trigger, delay
  resume, agent-task node, failed agent task, and retry.
- Existing permission behavior is captured for roles, workspace membership,
  oversight, sensitivity gates, add-on gates, and cross-workspace denial.

Required Boltrig/facade tests:

- AG-UI adapter maps Boltrig text, tool call, tool result, approval, usage,
  finish, failure, and cancellation events.
- Approval continuation cannot approve the wrong tool id.
- Approval continuation cannot be self-approved if the host policy forbids it.
- Bounded token cannot call tools outside the allowlist.
- Tool definitions and stream events do not expose provider keys or bearer
  values.
- Tool results are treated as untrusted model input.
- Degraded MCP/model failures produce clear terminal failure events.
- Dropped streams do not duplicate final assistant summaries.
- Request-gating credentials and execution credentials cannot be confused.
- Runtime state is partitioned by org, workspace, user/thread, and task id.
- Catalog drift fails safe when a tool schema, risk class, or authz class changes.

Required Opbox integration tests:

- Frontend kernel-chat path works against the Boltrig facade without broad UI
  changes.
- Mutating verb approval card appears and resumes the stream.
- Billing tee records terminal usage.
- Kernel audit records every side-effecting business action.
- Drainer shadow mode can claim, execute, write back, fail, retry, and idle.
- Config rollback restores the existing Opbox agent path.
- Existing workflow automations continue while chat is on Boltrig and drainer is
  still Hermes.
- Selected workflow automations continue when their `agent.run` task class moves
  to the Boltrig drainer.
- Cross-workspace and insufficient-role attempts are denied through the kernel
  and are not retried by the runtime as a different actor.

## Decisions and defaults

- Optimize for production transition, not only a demo.
- Chat cutover happens before drainer cutover.
- Opbox remains source of truth for business data, transcript, billing, audit,
  auth, and approval policy.
- Boltrig owns runtime loop, model/tool orchestration, runtime state, and
  degradation behavior.
- Use a separate pinned Boltrig service plus small facade for the first
  integration.
- Use dynamic MCP discovery for the proof of concept; use generated or cached
  catalog with drift checks before production.
- Avoid dual-write transcripts. Opbox stores user-facing conversation records;
  Boltrig stores only runtime state that Opbox does not need as product source of
  truth.
- Preserve provider-key boundaries: model/provider secrets come from deployment
  environment or secret manager, not from MCP tool definitions or per-run kernel
  payloads.

## Non-goals for the first cutover

- Do not replace the Opbox kernel.
- Do not replace the Opbox workflow automation engine, workflow builder, cron
  scheduler, or Hatchet integration.
- Do not run Opbox and Boltrig as competing automation engines for the same
  workflow domain.
- Do not move Opbox business tables, workflow tables, audit tables, billing
  tables, file storage, or conversation source-of-truth tables into Boltrig.
- Do not expose all Opbox verbs to Boltrig by default.
- Do not merge chat and drainer credentials.
- Do not switch models/providers at the same time as switching runtimes unless
  the change is separately flagged and evaluated.
- Do not retire the legacy rich chat path until RAG, citations, references,
  page-context, and attachment behavior have explicit parity decisions.
- Do not let shadow or comparison workers compete for production `agent.run`
  claims unless the kernel has an explicit non-owning claim/read mode.
- Do not build Slack/Teams/email/voice omnichannel support into the Opbox chat
  facade. Those channels follow decision 0003 and need their own verified channel
  bindings and sidecar/kernel termination path.
- Do not run two owning communications gateways for the same channel/client
  surface. Use explicit routing or non-owning shadow mode only.

## Release gates

Before routing any user chat to Boltrig:

- `/chat/stream` and `/chat/approve` fixture tests pass.
- Decision 0009 is satisfied: client protocol compatibility lives in the
  host-agent gateway/facade, while Bifrost remains model/provider routing only.
- Decision 0009 ownership is satisfied: the selected chat/API surface has one
  gateway of record and rollback routing is tested.
- Opbox prompt/profile harvest is complete, and golden task fixtures show the new
  runtime preserves tool-use bias, no-fabrication behavior, approval continuation,
  and any intentionally retained rich-chat behavior.
- Session bearer missing/invalid/expired cases fail closed.
- Chat-agent execution key is separate from the human bearer and drainer key.
- One read verb and one approval-gated write verb work through Opbox MCP.
- Billing terminal usage records for the initial turn and approval continuation.
- Rollback to the existing `agent-chat` path has been tested.

Before routing any automation/drainer work to Boltrig:

- Existing chat parity is stable.
- Decision 0010 is satisfied: Opbox remains the workflow engine of record, and
  the Boltrig drainer is only a worker over the Opbox `agenttask` lifecycle.
- `agenttask.claimNext`, `agenttask.checkpoint`, and `agenttask.requeue` behavior
  matches the current drainer under success, failure, timeout, and empty-queue
  cases.
- Run-scoped bearer execution is proven.
- Scheduled workflows, manual workflows, delay resumes, and agent-task nodes pass
  in the selected scope.
- No stuck paused workflow, rising requeue loop, false `DONE`, or audit gap is
  observed during the shadow/parity window.

Before retiring Hermes/current agent services:

- Rollback has been exercised after Boltrig has processed real traffic.
- Observability can correlate frontend invocation, Boltrig run, kernel audit,
  provider request, and `agenttask` ids.
- Security review covers token boundaries, tool catalog exposure, approval
  resume, egress, provider secrets, logging, and data retention.
- Product owners explicitly accept any differences in model behavior, RAG
  behavior, tool availability, or UI rendering.

## Security constraints

- Opbox kernel remains the only authority for Opbox business actions.
- Boltrig calls Opbox only through MCP/tools, never by direct DB writes.
- No human bearer is handed directly to the agent loop as broad authority.
- Tool definitions must not leak secrets or secret references.
- Egress should be restricted to the Opbox kernel MCP endpoint and approved model
  endpoints/gateways.
- Provider keys should not cross the agent boundary via MCP.
- Tool result content remains untrusted model input.
- Every side-effecting business action remains audited by Opbox kernel.
- Approval continuation must bind the decision to the paused thread, tool id,
  actor, and current authorization state.

## Final verdict

Feasible and strategically clean as a runtime swap. Treat Boltrig as the caged
agent engine and Opbox as the product/kernel authority.

Do not start by replacing the Opbox kernel. Start by making Boltrig a better
host-app runtime: facade adapters, approval continuation, external MCP hardening,
pinned packaging, host-owned conversation mode, and worker/drainer profile. Then
use those pieces to replace Opbox `agent-chat`, prove parity, and only then move
the drainer.
