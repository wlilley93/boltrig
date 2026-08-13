# Codex App Server integration map

- Status: implementation plan; architecture accepted by decision 0012
- Date: 2026-07-15
- Initial protocol target: `codex-cli 0.144.3`, stable App Server API
- Implementation state: thin domain/application/port contracts implemented;
  runtime adapter and cutover not yet implemented

## Purpose

This document is the file-by-file plan for replacing OpenCode and Herdr with a
thin Codex App Server integration while making Boltrig the durable workflow and
governance control plane.

The non-negotiable ownership rule is:

```text
Boltrig controls authority and workflow.
Codex controls execution.
Opbox controls real-world domain effects.
```

This plan does not authorize a broad rewrite. Existing HTTP compatibility,
kernel authorization, Postgres tenant isolation, HITL, audit, and store parity
remain binding.

## Baseline and verified facts

The Beelink host was inspected read-only. Its Codex cache contained:

```text
/var/lib/boltrig/codex/packages/standalone/releases/
  0.135.0-x86_64-unknown-linux-musl
  0.136.0-x86_64-unknown-linux-musl
  0.137.0-x86_64-unknown-linux-musl
  0.142.5-x86_64-unknown-linux-musl
  0.143.0-x86_64-unknown-linux-musl
  0.144.3-x86_64-unknown-linux-musl
```

The selected binary reported `codex-cli 0.144.3`. It was not installed on the
service `PATH`. Production must package that exact binary, verify its checksum,
and generate the protocol schema from the packaged artifact. A developer cache
is evidence for planning, not a production dependency.

The verified production pin tuple is:

```text
codex-cli version: 0.144.3
target: x86_64-unknown-linux-musl
binary sha256: 37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b
canonical stable-v2 schema sha256:
66ab7534f29e1ee7c065eb15c799d5f6e93fdd1d0ba86c262c3842a6a8f3d0c8
canonical 267-file stable bundle sha256:
0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810
experimentalApi: false
transport: stdio or private same-host Unix socket
```

Schema JSON must be key-sorted and compacted before hashing because generated
definition ordering is not byte-order deterministic. Readiness compares both
the binary and canonical stable-v2 schema digests.

The probe used the developer's current ChatGPT login only to establish protocol
behavior. Production must use a private stack-owned `CODEX_HOME` with mode
`0700`; it must not reuse a developer CLI directory or any personal login state.

The stable schema was generated without `--experimental` using:

```text
codex app-server generate-json-schema --out <temporary-directory>
```

The following 0.144.3 behavior is verified from that schema and the official
App Server documentation:

| Area | Verified surface | Integration consequence |
| --- | --- | --- |
| Protocol | Bidirectional JSON-RPC 2.0 with the `jsonrpc` member omitted on the wire | Use a typed, bounded protocol client; do not reuse a generic client that requires the member |
| Handshake | One `initialize` request followed by `initialized`; pre-initialize and repeated initialize calls fail | Supervisor readiness must prove the handshake, not only process existence |
| Client identity | `initialize.clientInfo` identifies the integration to upstream compliance logs | Use a stable Boltrig client name/version and confirm enterprise client registration before production |
| Transport | stdio JSONL; WebSocket-over-private-Unix-socket; TCP WebSocket is experimental | Use stdio per cell or a private same-host Unix socket; no unauthenticated remote listener |
| Backpressure | A full WebSocket ingress queue returns error `-32001`, `Server overloaded; retry later.` | Retry only safe requests with exponential backoff and jitter; never duplicate a turn blindly |
| Threads | `thread/start`, `thread/resume`, `thread/fork`, read/list/archive and related notifications | Persist Boltrig-to-Codex thread bindings and make resume explicit |
| Skills | `skills/list` reports path, scope, and effective enablement; repository skills are discovered from `.agents/skills` independently of project trust | Attest the complete enabled set before starting a thread; isolated `CODEX_HOME` alone is not a skill boundary |
| Turns | `turn/start`, `turn/steer`, `turn/interrupt`, started/completed notifications | Map chat send, steer, and Stop to real turn lifecycle operations |
| Events | Thread, turn, item, text delta, command, file-change, MCP progress, plan, token, warning, and completion events | Normalize and durably record lifecycle events; raw events are not authority |
| Approvals | Server requests for command execution, file change, and permission elevation include thread/turn/item/approval correlation | Bridge them to Boltrig approval state; never auto-accept from prompt content |
| Dynamic tools | `item/tool/call` requests contain call, thread, turn, namespace, tool, and arguments | MCP remains the selected governed domain-tool route; dynamic tools are not a bypass |
| Native subagents | Stable item schemas expose collab-agent calls, subagent activity, child source, and `parentThreadId` | Boltrig may observe native subagents but does not schedule them as Hatchet children |
| Native subagent control | No client method directly spawns or independently schedules a subagent | Request bounded delegation through profile/instructions and let Codex orchestrate it |
| Schema generation | JSON Schema and TypeScript outputs are version-specific | Check generated stable schema and digest into the repository and fail CI on drift |
| Experimental API | Requires `experimentalApi` at initialize and separately generated fields | Keep disabled in v1 unless explicitly approved |
| Authentication | Stable login start supports API key, ChatGPT, and device code; account state can report Agent Identity | Do not claim that Boltrig can mint an upstream Codex/ChatGPT user |

Official references:

- <https://learn.chatgpt.com/docs/app-server.md>
- <https://learn.chatgpt.com/docs/agent-configuration/subagents.md>

## Target stack

```text
Boltrig browser console and API
    |
    v
Boltrig control plane
  - identity and workspace policy
  - profile and skill catalogue
  - authority and approvals
  - root-run and phase ledger
  - retry, cancellation, audit, synthesis
    |
    v
Hatchet phase-job transport
    |
    v
Codex supervisor
    |
    +--> isolated Codex App Server cell
            |
            +--> one root phase thread
                    |
                    +--> native Codex subagents
                    |
                    +--> short-lived Boltrig MCP grant
                              |
                              v
                    Boltrig kernel chokepoint
                              |
                              v
                    governed Opbox adapter
                              |
                              v
                    Opbox data and domain effects
```

Postgres is canonical for runs, phases, approvals, audit, bindings, and the work
ledger. Redis carries ephemeral coordination, normalized event delivery, and
immediate grant revocation. Hatchet executes durable jobs but does not own the
workflow state machine. The Codex supervisor owns cells and processes but does
not own authority.

## Domain model

The canonical work hierarchy is:

```text
root run -> phase -> work item -> assignment -> result -> verification
```

Required durable records are:

- **root run**: tenant, workspace, initiating principal, objective, profile,
  policy generation, status, cancellation, and synthesis
- **phase**: bounded objective, dependencies, read/write mode, retry policy,
  selected profile and skill versions, and terminal outcome
- **work item**: a meaningful deliverable or approval boundary, not a model
  thought or tool call
- **assignment**: lease, attempt, worker/cell identity, start/expiry, and
  replacement relationship
- **result**: structured findings, evidence, blockers, handoffs, output digest,
  cost, and normalized status
- **verification**: verifier identity, checks, evidence, decision, and reason
- **Codex binding**: root, phase, assignment, thread, turn, item, and parent
  thread identifiers
- **runtime cell**: supervisor, isolated state/workspace references, CLI/schema
  version, lifecycle, and health; never credentials
- **grant lease**: opaque token hash or JTI, scope, expiry, revocation, current
  policy generation, and audit correlation

A Kanban board, chat activity view, and native subagent display are projections
of this state.

## Authority model

Selecting a skill never grants authority. The effective grant is:

```text
current parent grant
  intersect profile ceiling
  intersect selected-skill requirements
  intersect current workspace and data policy
  intersect current approval state
```

The result is deny-dominant and recomputed:

1. when the phase is assigned;
2. when a Codex thread or turn resumes;
3. when `tools/list` is requested;
4. for every `tools/call`;
5. after any approval, user, membership, workspace, or policy change.

Queued payloads carry identity and requested-scope references, not an
authoritative serialized grant. Prompts, memory, skill bodies, messages, tool
results, and App Server events are untrusted data and cannot change the model,
sandbox, approval mode, or authority.

## File-by-file cutover map

### New thin modules

| File | Responsibility |
| --- | --- |
| `boltrig/fleet/codex_protocol.py` | Exact-version request, response, notification, and error types; validates the omitted `jsonrpc` wire convention, IDs, and schema version |
| `boltrig/fleet/codex_app_server.py` | Initialize handshake, request correlation, bounded queues, stdio/private-socket transport, timeout, disconnect, and protocol-error handling |
| `boltrig/fleet/codex_supervisor.py` | Starts and stops isolated cells, owns stack state/workspaces, enforces resource limits, and reconciles process death |
| `boltrig/fleet/codex_runtime.py` | Runtime adapter that starts/resumes a bounded phase and returns a structured `AgentResult` compatibility response |
| `boltrig/fleet/codex_events.py` | Translates App Server events to normalized Boltrig lifecycle events and retains Codex correlation IDs |
| `boltrig/fleet/codex_profiles.py` | Materializes versioned static profiles, model/sandbox policy, native-subagent caps, and permitted skill catalogues |
| `boltrig/fleet/work_ledger.py` | Idempotent root/phase/work/assignment/result/verification state machine and projections |
| `boltrig/fleet/hatchet_codex.py` | Registers one durable Hatchet job per meaningful Boltrig phase; no job per Codex subagent |
| `boltrig/kernel/run_grants.py` | Issues, validates, expires, and revokes opaque run/phase MCP leases with current-policy generation checks |
| `boltrig/adapters/builtin/opbox.py` | Governed Opbox adapter with allowlist, catalogue digest, dynamic credential resolution, failure mapping, and audit correlation |
| `boltrig/models/execution.py` | Ledger, binding, runtime-cell, grant-lease, and normalized execution-status records |
| `migrations/versions/0026_codex_execution_ledger.py` | Additive ledger, binding, profile, runtime-cell, event, and grant-lease schema plus RLS |
| `schemas/codex/0.144.3/` | Generated stable App Server schemas and recorded digest |
| `deploy/codex-supervisor.Dockerfile` | Exact CLI/checksum pin, non-root supervisor, minimal runtime, and stack-owned state |

Keep each module below the repository's structural limits. Generated schemas are
exempt from hand-authored LOC rules but remain versioned artifacts.

### Runtime, profile, and authority changes

| Existing file | Required change |
| --- | --- |
| `boltrig/fleet/runtime.py:106-117,382-456` | Preserve `run()` compatibility; add a phase-lifecycle protocol and Codex factory; remove OpenCode only at cutover |
| `boltrig/fleet/runtime_resolver.py:120-137,167-178` | Resolve Codex profile/cell; replace broad credential exception swallowing with explicit resolved/unavailable/forbidden/misconfigured states; prohibit production ambient fallback |
| `boltrig/fleet/spawn.py:62-164,205-225,324-400` | Become a compatibility facade over phase execution; stop treating every invocation as a Boltrig-created subagent; stop deriving authority from skills |
| `boltrig/fleet/spawn_skills.py:43-96,130-155` | Treat tool declarations as requirements only and expose progressive skill catalogue metadata |
| `boltrig/models/libraries.py:47-74` | Add profile/version references and deprecate authority-bearing `Skill.tool_grants` semantics |
| `boltrig/models/grants.py:66-110` | Retain deny-dominant intersection and add an explicit full effective-authority calculation |
| `boltrig/models/context.py:17-45` | Carry root, phase, assignment, grant-lease, and policy-generation IDs; never credentials |
| `boltrig/models/identity.py` | Associate an internal Codex execution principal with an existing Boltrig user without claiming upstream account creation |
| `boltrig/models/tenancy.py:40-116` | Reuse Organisation, OrgMember, Workspace, and WorkspaceMember as the product identity and workspace-policy boundary |

### Ledger, queue, chat, and cancellation changes

| Existing file | Required change |
| --- | --- |
| `boltrig/models/work.py:17-75` | Keep `WorkItem` as a compatibility/projection type; make the new ledger canonical |
| `boltrig/store/schema.sql:158-180,220-232` | Maintain bootstrap parity for ledger, bindings, grant leases, runtime cells, and durable event outbox |
| `boltrig/store/base.py` | Add atomic ledger transition, claim, binding, lease, normalized-event, and verification contracts |
| `boltrig/store/memory.py` | Implement the same contracts for offline tests with behavioral parity |
| `boltrig/store/postgres.py` | Implement transactions, exact claims, idempotency, tenant fencing, and RLS-backed queries |
| `boltrig/fleet/hatchet_app.py:91-220` | Queue IDs and requested scope, not serialized grants; resolve current authority at execution/resume |
| `boltrig/fleet/pump.py:216-301,372-381,408-438` | Remove tenant-wide grant reconstruction; refresh cancellation across in-flight boundaries; reconcile interrupt and terminal state |
| `boltrig/fleet/department_head.py:164-204` | Remove the missing grant ceiling; request governed phases instead of child-agent scheduling |
| `boltrig/fleet/chat.py:208-337,389-443,519-531,543-659` | Create durable root/phase records; map send, steer, and Stop to turn start/steer/interrupt |
| `boltrig/kernel/events.py:1-136` | Replace production in-memory relay with durable normalized events/outbox and Redis Stream delivery; retain memory relay for tests |
| `boltrig/kernel/access_routes.py:346-368` | Atomically record cancellation intent, revoke the grant, interrupt the turn, and audit reconciliation |
| `boltrig/kernel/app.py:408-439,672-702` | Preserve HTTP/chat/SSE compatibility and expose ledger projections through existing discovery patterns |

### MCP, approvals, and Opbox changes

| Existing file | Required change |
| --- | --- |
| `boltrig/kernel/mcp.py:40-81,174-220` | Replace process-local non-expiring tokens with durable lease validation and current-policy checks on list/call; retain `kernel.invoke` |
| `boltrig/adapters/mcp_consumer.py:25-110` | Remove instance-held long-lived tokens; require per-call credential resolution, endpoint allowlist, DNS/IP pinning, auth-header policy, and catalogue digest |
| `boltrig/api/bootstrap.py:203-220` | Register Opbox by credential reference and policy, never raw token material |
| `boltrig/kernel/approval_gate.py`, `boltrig/kernel/hitl.py`, and HITL store operations | Bind App Server command/file/permission requests to exact Boltrig approval objects and keep domain-effect approval authoritative |

### Manifest, readiness, deployment, and operator changes

| Existing file | Required change |
| --- | --- |
| `boltrig/config/manifest.py:33-42,626-660,772-859` | Remove Herdr builtin; add typed Codex/profile/cell/Opbox policy; reconcile/deactivate removed rows instead of upsert-only application |
| `boltrig/api/cli.py:76-84,146-151` | Remove `opencode-plugin`; add read-only schema, status, and canary commands |
| `boltrig/api/readiness.py:22-31,245-367` | Replace Herdr/OpenCode checks with supervisor, exact version/schema, cell canary, migration, grant broker, and optional Opbox-catalogue readiness |
| `boltrig/fleet/stack_tool_health.py:141-274` | Probe pinned Codex CLI, App Server handshake, and a bounded read-only cell |
| `boltrig/fleet/stack_tool_receipts.py:20-234` | Preserve signed tenant/deployment/freshness mechanics; version receipt for CLI, App Server, supervisor, and browser |
| `boltrig/fleet/stack_tool_status.py:27-194` | Replace legacy status metadata and keep paths, auth, prompts, and credentials redacted |
| `boltrig/api/doctor_stack_state.py:22-229` | Require isolated stack-owned Codex state and reject personal `.codex` homes or shared tenant roots |
| `boltrig/api/worker.py:58-73` | Publish supervisor/cell readiness rather than OpenCode heartbeat |
| `deploy/kernel.Dockerfile:53-80` | Remove Herdr |
| `deploy/fleet.Dockerfile:71-97` | Remove OpenCode; keep broad fleet duties separate from the Codex supervisor |
| `docker-compose.yml:94-142,390-391` | Remove legacy mounts/variables; add private supervisor service, state/socket volumes, healthcheck, limits, and network policy |
| `.env.example:149-153,202-209` | Replace legacy homes and receipt language with Codex supervisor/cell configuration |
| `manifest.example.yaml:23-27,71-79,94,157-164,216-221,372-375` | Replace Herdr/OpenCode/Mastra examples with Codex profiles, skills, and Opbox policy |
| `pyproject.toml:115` | Replace the strict-mypy OpenCode entry with every new hand-authored Codex boundary module |

### Documentation changes at implementation time

- `docs/DEPLOYMENT.md`
- `docs/PROD-CUTOVER-RUNBOOK.md`
- `docs/dependency-policy.md`
- `docs/guide/herdr-opencode-stack-state.md`
- `docs/invariants.md`
- `docs/proposals/boltrig-v2-control-plane.md`
- `docs/refactoring/structural-exemptions.json`

`docs/decisions/0010-opbox-generalisation-and-automation-engine-ownership.md`
and `docs/proposals/opbox-pinned-boltrig-agent-runtime.md` remain historical.
Decision 0012 explicitly supersedes their workflow-ownership conclusion; do not
rewrite them as though the earlier decision was never made.

## Exact legacy dependency inventory

### Active code and configuration

- `.env.example`
- `boltrig/adapters/builtin/herdr.py`
- `boltrig/api/cli.py`
- `boltrig/api/doctor_stack_state.py`
- `boltrig/api/readiness.py`
- `boltrig/api/worker.py`
- `boltrig/config/manifest.py`
- `boltrig/fleet/hatchet_app.py`
- `boltrig/fleet/hatchet_ultracode.py`
- `boltrig/fleet/mastra.py`
- `boltrig/fleet/opencode_plugin.py`
- `boltrig/fleet/opencode_runtime.py`
- `boltrig/fleet/runtime.py`
- `boltrig/fleet/runtime_resolver.py`
- `boltrig/fleet/stack_tool_health.py`
- `boltrig/fleet/stack_tool_receipts.py`
- `boltrig/fleet/stack_tool_status.py`
- `boltrig/fleet/ultracode.py`
- `boltrig/fleet/ultracode_memory.py`
- `deploy/fleet.Dockerfile`
- `deploy/kernel.Dockerfile`
- `docker-compose.yml`
- `manifest.example.yaml`
- `pyproject.toml`

Deployment-local `manifest.yaml` is ignored by Git but may contain the same
legacy stack, endpoint, capability, adapter, and tool-root configuration. The
cutover runbook must inspect and migrate it without printing secrets.

### Tests and invariant bindings

- `tests/adapters/test_herdr_adapter.py`
- `tests/deploy/test_compose_hardening.py`
- `tests/integration/test_fleet_spawn.py`
- `tests/integration/test_hatchet_live.py`
- `tests/integration/test_round_two_manifest.py`
- `tests/integration/test_ultracode_memory.py`
- `tests/integration/test_ultracode_run.py`
- `tests/invariants.yaml`
- `tests/security/test_console_overview.py`
- `tests/security/test_langfuse_sink.py`
- `tests/security/test_opencode_plugin.py`
- `tests/security/test_opencode_runtime.py`
- `tests/security/test_platform_status.py`
- `tests/unit/test_doctor.py`
- `tests/unit/test_mastra_compiler.py`
- `tests/unit/test_readiness.py`
- `tests/unit/test_stack_tool_health.py`
- `site/src/views/console/format.test.ts`
- `ui/tests/__characterization__/panels/OperationalPulse.test.tsx`

The live Hatchet test at `tests/integration/test_hatchet_live.py:218-289` does
not need a literal OpenCode reference to conflict with the target architecture:
it binds the current parent/child agent scheduler and must be replaced by a
one-phase-job/native-subagent test.

### Documentation and historical contracts

- `docs/DEPLOYMENT.md`
- `docs/HANDOVER-2026-07-02.md`
- `docs/PROD-CUTOVER-RUNBOOK.md`
- `docs/dependency-policy.md`
- `docs/guide/herdr-opencode-stack-state.md`
- `docs/invariants.md`
- `docs/proposals/boltrig-v2-control-plane.md`
- `docs/refactoring/structural-exemptions.json`
- `docs/decisions/0010-opbox-generalisation-and-automation-engine-ownership.md`
- `docs/proposals/opbox-pinned-boltrig-agent-runtime.md`

Historical handovers, audit rows, event payloads, workflow-run records, and
checkpoint provenance retain their original OpenCode, Herdr, Mastra, or
Ultracode labels.

### Registry and database rows

The data cutover must explicitly reconcile active rows because current manifest
application only upserts:

- OpenCode `model_endpoints`, including examples such as `opencode-ornith`
- OpenCode `agent_capabilities`, including examples such as `opencode-worker`
- `ai_configs` whose provider is `opencode`
- Herdr adapter, noun, verb, and binding rows
- active workflow definitions that compile or dispatch Mastra/Ultracode agents
- deployment configuration or checkpoints that are still eligible for resume

Do not delete immutable audit, event, result, or historical workflow records.
Use an explicit Alembic/data migration to deactivate active legacy registry
rows; removing YAML alone is insufficient.

## Legacy files removed after parity

Delete only in the final cutover PR:

- `boltrig/fleet/opencode_runtime.py`
- `boltrig/fleet/opencode_plugin.py`
- `boltrig/adapters/builtin/herdr.py`
- `boltrig/fleet/hatchet_ultracode.py`
- `boltrig/fleet/ultracode.py`
- `boltrig/fleet/mastra.py`

`boltrig/fleet/ultracode_memory.py` first becomes a historical compatibility
reader. New writes stop using Ultracode provenance; old records remain readable.

## Invariant migration

### Retain in substance

- deny-dominant, fail-closed grant intersection
- tenant and RLS isolation with current principal propagation
- every external action re-enters the kernel chokepoint
- exact HITL binding, single use, object authorization, and durable resume
- exact claim/lease, idempotency, retry/fanout caps, and honest degradation
- granted-only MCP discovery and execution
- paired audit, secret redaction, bounded observability, and tenant-scoped event
  streams
- memory, prompts, messages, skills, and workflows are data, not authority
- reviewed adapter activation, SSRF protection, and DNS/IP pinning
- cost reservation and true-up
- signed, fresh, deployment-bound readiness receipts

### Rename or replace

- `FR-HOST-09`, `FR-HOST-10`, `FR-HOST-12`, and `FR-HOST-14` become Codex
  stack-state, binary/schema pin, redacted-status, and minimal-environment
  guarantees.
- `FR-RUN-10` through `FR-RUN-18` become Codex lifecycle, protocol, genuine
  interrupt, expiring grant, isolated-cell, and no-ambient-credential
  guarantees.
- `SEC-27` becomes the guarantee that Codex receives only an expiring,
  run-scoped MCP capability.
- `FR-OPS-03` becomes supervisor, App Server, cell-canary, and grant-broker
  readiness.

Do not manufacture Codex equivalents for Herdr pane verbs.

### Add

- full effective-authority intersection is recomputed for every tool call
- no prompt, message, skill, memory, or tool output can change authority,
  sandbox, model policy, or approval state
- grant expiry and revocation are immediate across processes
- Codex IDs are bound to one tenant, workspace, root, phase, and assignment
- Boltrig does not schedule native Codex subagents and v1 has no peer mailbox
- binary/schema mismatch fails closed
- ledger transitions are atomic and idempotent
- Stop revokes admission and interrupts the exact active turn
- no new domain effect begins after revocation
- every Opbox effect carries correlated Boltrig and Opbox audit identifiers
- App Server events are untrusted data, not control commands

## Security blockers found in the current implementation

The following are blockers for approval-gated write phases, not optional cleanup.

> **Re-triaged 2026-07-17 against the tree at `6abe103`, and the list did not survive
> contact with the code.** Of the original 13: two were already fixed on the day this
> list was written, two were wrong as written, one was not a separate blocker, four are
> design forks rather than defects, one is dead path, and four were genuinely live. The
> item this list framed hardest (2) is false, and the real privilege escalation (4) was
> partly obscured behind it. Statuses below are the re-triage; each is argued from the
> code, not inherited from this document's original framing. The lesson is recorded
> rather than smoothed over: a security list is evidence, not gospel, and acting on an
> unverified one wastes effort on phantoms while the real defect sits underneath.

1. ~~`boltrig/fleet/runtime_resolver.py:127-137` catches all AI-credential
   resolution errors and returns no key, permitting downstream ambient fallback.~~
   **ALREADY FIXED** by `2c7b5d3` ("fix(runtime): forbid ambient AI credentials in
   production"), landed 2026-07-15, the same day this list was written. The resolver now
   re-raises `CredentialResolution` when `production_signal()` is set, and additionally
   refuses a default (unscoped) resolution in production. The bare `return None, None`
   survives only outside production, which is the intended dev affordance. Not a blocker.
2. ~~`boltrig/fleet/spawn.py:121-126` currently creates child authority from
   selected skill grants and intersects it only when an optional ceiling is
   supplied.~~ **WRONG AS WRITTEN.** `spawn.py:121-123` intersects against
   `context.grants` UNCONDITIONALLY (`GrantSet.of(allow=...).intersect(context.grants)`),
   and `GrantSet.intersect` can only narrow, so the child is always bounded by its
   parent. The ceiling is an ADDITIONAL narrowing, not the only one. This item was
   groping toward a real defect by the wrong mechanism: the actual problem was never
   spawn, it was what `context.grants` CONTAINED when the pump built it. See 4.
3. ~~`boltrig/fleet/department_head.py:178-184` calls spawn without that ceiling.~~
   **NOT A SEPARATE BLOCKER; merged into 4 and FIXED (`929a274`).** True as a fact, but
   the missing ceiling was only exploitable because of the tenant-wide context behind it.
4. `boltrig/fleet/pump.py:372-381` reconstructs durable execution with
   tenant-wide permissions instead of the current user/profile/workspace
   intersection. **CONFIRMED LIVE, the most severe item on this list, now FIXED
   (`929a274`, SEC-164/165).** The pump was the only spawn caller that both put
   tenant-wide grants in the context and omitted the ceiling; chat, spawn, eval,
   personal, skills and ultracode all already capped to the caller (SEC-78, SEC-139,
   SEC-29). `_context_for` now resolves the principal via `effective_grants_for_request`,
   `on_behalf_of=None` fails closed, and `_head_for` parks instead of mis-routing.
5. `boltrig/fleet/hatchet_app.py:129-169` serializes effective grants into queued
   input, so stale authority may survive revocation or membership changes.
   **LIVE but over-severity as written.** `dispatch.py:382-383` re-reads
   `get_tenant_permissions` fresh from the store on EVERY call and rejects anything
   outside the current tenant ceiling before consulting `context.grants`, so a
   tenant-level revocation is immediate even for an already-queued envelope, and
   envelope grants can only be stale in the NARROWING direction. The real residual is
   user-level revocation and workspace membership, which nothing re-derives on dequeue.
   Note the sequencing: fixing 4 makes 5 matter MORE, not less, because before 4 there
   was no user-level narrowing in the envelope to go stale. Mild design fork
   (re-resolve on dequeue vs a queue-time snapshot with a TTL).
6. ~~`boltrig/kernel/mcp.py:58-81` stores non-expiring tokens in one process;~~
   revocation is neither durable nor horizontally consistent. **HALF FIXED; the
   "non-expiring" clause is FALSE.** `0b862fd` ("fix(mcp): hash and expire run-scoped
   tokens") landed 2026-07-15, also the day this list was written: tokens are stored
   SHA-256 hashed, `ttl_seconds` is bounded to 1..3600 (default 300), and `_lookup`
   evicts on expiry. The surviving half is real: `self._tokens` is per-process, so
   `revoke()` on one replica does not revoke on another, bounded by the TTL. Design
   fork, and the same shared-state decision as 8, not two separate ones.
7. `boltrig/fleet/chat.py:519-531` closes the SSE stream on Stop but does not
   interrupt the active runtime. **LIVE, but this is an IMPLEMENTED INVARIANT, not an
   oversight.** The docstring states the cooperative-never-hard-kill rule explicitly and
   `pump.py:260-262` repeats it as "D3, FORBIDDEN: no mid-step hard kill". This
   document's own "Add" section demands that Stop "interrupts the exact active turn",
   which CONTRADICTS D3. That is a request to reverse a recorded decision, so it needs a
   court ruling, not a code fix. Flagged as a contradiction in this document rather than
   as an implementation defect.
8. `boltrig/kernel/events.py:1-16` uses an in-memory execution relay that loses
   reconnectable state across process restart. **LIVE and explicitly by design** (the
   module says so, and the `TenantEventRelay` swap seam already exists). The consequence
   is availability and UX, not authority or confidentiality: the durable record is
   `ConversationMessage.events` plus the audit trail. **This does not belong on a
   security-blocker list.** Same shared-state decision as 6.
9. Manifest application upserts registry records but does not deactivate rows
   omitted from the new manifest, leaving legacy capabilities active. **CONFIRMED
   LIVE.** `config/manifest.py:772-859` is upsert-only and there is no deactivation pass;
   `agent_capabilities` has no `is_active` column at all, so removing a capability from
   the manifest and redeploying does not remove it and it stays selectable forever.
   Blast radius is capped because `set_tenant_permissions` IS fully replaced, but a
   legacy capability still routes to a legacy adapter within that ceiling. NOT
   mechanical: it needs a migration plus a decision on whether manifest application is
   declarative (deactivate omitted) or additive (today). Cheap court matter.
10. `boltrig/adapters/mcp_consumer.py` retains static token material on the
    adapter and does not make the per-call credential the authoritative source.
    **CONFIRMED LIVE, and UNDERSOLD here.** The `credential` parameter is accepted by
    `execute()` and then never referenced in the body: the only auth material is
    `self._token`, set once at construction. So the per-call credential is not merely
    "not authoritative", it has NO effect whatsoever, and credential rotation and
    per-run scoping are silently inert on this path. `self._token or ""` also sends an
    empty bearer rather than failing closed when unset. **FIXED (`33af0b4`, SEC-167).**
    Not mechanical after all: nothing provisioned a credential for these adapters
    (`build_mcp_consumer` took the token as a raw registration param and no
    `set_credential_ref`/`_adapter_cred` mapping existed), so `resolve_for_adapter`
    returned `None` and a naive fail-closed would have broken every MCP call.
    Registration now goes through the credential seam, mirroring `manifest.py`'s
    existing `set_credential_ref` + `bind_adapter_credential`; `self._token` is deleted
    outright so no back door remains. Manifest `mcp.consume` entries move from
    `credential: ${ENV}` (raw material) to `credential_ref: KEY` (a secret-store key),
    and raw material is now refused loudly. Also fixed en route: the SSRF branch did
    `raise AdapterError(...)`, which is a `TypeError` since `AdapterError` is a plain
    dataclass, so SEC-61 failed closed by the wrong route and no `except AdapterError`
    could have caught it. Now carried via `_McpFailure` and converted at the `execute`
    boundary, mirroring `http_base._HttpFailure`.
11. `boltrig/fleet/ultracode.py:280-365` and
    `boltrig/fleet/hatchet_ultracode.py:10-128` schedule individual phase agents,
    directly competing with Codex native-subagent orchestration. **NOT A SECURITY ISSUE.**
    The code is well-behaved (`ultracode.py:228` passes `grant_ceiling=context.grants`,
    `:289-290` enforces the tenant fence). "Competes with Codex" is an
    architecture-strategy claim, and nothing competes today: `codex_runtime_config_toml.py`
    already sets `multi_agent: False` and `max_depth = 1`. Court matter, and it should not
    be on this list.
12. Cancellation checks in `boltrig/fleet/pump.py:216-301` do not refresh the
    cancellation marker after the in-flight head execution boundary before
    terminal handling. **CONFIRMED LIVE, and UNDERSOLD here.** The stated consequence is
    a mislabelled terminal state. The real one is worse: between the boundary and the
    terminal write the pump runs `persist_new_work_items` (which CREATES new work items
    the pump then claims and executes) and `_maybe_learn` (which promotes the run's
    workflow into the reusable library). So a cancelled run can spawn fresh downstream
    work and mutate the flywheel, violating this document's own "no new domain effect
    begins after revocation". **FIXED (`1d7c86a`, SEC-166):** boundary 2 re-reads the
    marker after the step and before the persist/learn block. D3 intact (the step is
    never interrupted; this is a cooperative check at a boundary already crossed).
    Semantics: the completed head outcome is RECORDED, its downstream effects are
    SUPPRESSED, since the invariant is "no new domain effect BEGINS after revocation",
    not "pretend the completed step never ran". Residual: a cancel landing between
    boundary 2 and the terminal write still uses a stale value (now a millisecond window
    of local writes rather than a whole in-flight call); closing it needs a
    compare-and-set on the terminal write, a separate design question.
13. Codex still discovers repository `.agents/skills` while project-local
    `.codex` config, hooks, and rules are disabled for an untrusted project.
    Directly pointing a cell at an unsanitized checkout would bypass Boltrig's
    selected-skill catalogue even with an isolated `HOME` and `CODEX_HOME`.
    **PARTLY MITIGATED, core claim UNVERIFIED, and DEAD PATH today.**
    `bounded_filesystem.py:13` already strips `.agents` (and `.codex`, `.git`, ...) via
    `CONTROL_NAMES` during capture, and the generated config sets
    `project_doc_max_bytes = 0`, `project_root_markers = []`, `hooks: False`. The
    scenario is the NON-projected path, but `codex_cell_supervisor.py:286` always passes
    a constructed layout as cwd, never a caller-supplied path. Whether Codex 0.144.3
    discovers `.agents/skills` from cwd independently of trust is an upstream-binary
    behaviour claim that cannot be settled from this tree and needs an empirical check
    against the pinned CLI. Also: nothing in production constructs the Codex cell
    supervisor or app server at all, so this is unreachable today.

Read-only Codex protocol work may proceed behind a disabled feature flag while
these are fixed. No Opbox or repository write capability may be enabled first.

### Issues found during the 2026-07-17 re-triage that were NOT on this list

- `boltrig/fleet/chat.py:588-592` uses the same tenant-wide `grants=perms.grants`
  pattern the pump did, and is rescued ONLY by the ceiling at `:627`. The invariant is
  enforced by convention across six call sites rather than by construction. Consider
  making the context helpers take a required principal so the safe thing is the only
  expressible thing. Same class of latent bug, currently not exploitable.
- `boltrig/adapters/mcp_consumer.py:108` sends `self._token or ""`, failing open into an
  unauthenticated request rather than refusing. **FIXED with 10 (`33af0b4`).**
- `AdapterError` is a plain dataclass, so `raise AdapterError(...)` is a `TypeError`
  rather than a refusal. `mcp_consumer` was the only such raise site and is **FIXED
  (`33af0b4`)**. The latent trap remains for anyone who writes a new one: the correct
  pattern is an exception carrier converted at the `execute` boundary
  (`http_base._HttpFailure`, `mcp_consumer._McpFailure`). Making `AdapterError` itself
  un-raisable-by-mistake (or a real exception) is unexamined.
- `boltrig/models/grants.py:126` calls `_matches(p, pattern.rstrip(".*"))`. `rstrip`
  takes a CHARACTER SET, not a suffix, so it strips any trailing run of `.` and `*`.
  `"ticket.*"` happens to give `"ticket"`, and no breaking input was found, so this is
  "worth five minutes" rather than a finding. Flagged because it sits on the deny path,
  where a false negative fails open.
- `boltrig/fleet/pump.py` `_head_for` fell open to an arbitrary head on an unroutable
  department while `principal_scope` still claimed the original. FIXED with 4 (SEC-165).

## Product and security decisions required

Resolve and record these before the named gate:

| Decision | Required before | Recommended default |
| --- | --- | --- |
| Upstream Codex authentication: shared service identity, per-org identity, or user OAuth | production canary | Service-controlled API identity initially; never imply automatic ChatGPT-user minting |
| Agent Identity provisioning support | any design that promises one Codex identity per organisation user | Treat as unavailable until supported provisioning is confirmed |
| Cell cardinality and lifetime | supervisor implementation | One process/cell lease per active phase; durable isolated state only where thread continuity needs it |
| Thread reuse, fork, and phase boundaries | lifecycle schema | One root thread per bounded phase; explicit resume; fork only for intentional branch/rollback workflows |
| Stable versus experimental App Server API | protocol pin | Stable only for v1 |
| Model, effort, sandbox, and approval ceilings per profile | profile activation | Server-owned immutable profile values; read-only first |
| Local Codex approval versus Boltrig/Opbox domain approval | write phase | Boltrig/Opbox remain authoritative; local approval cannot imply domain approval |
| Opbox catalogue allowlist, digest, auth exchange, and response classification | Opbox adapter | Pinned reviewed catalogue plus per-call credential exchange |
| Canonical conversation transcript | chat cutover | Boltrig owns user-facing transcript and normalized events; Codex history is execution state |
| Raw App Server event retention | event-store migration | Normalize by default; retain bounded encrypted raw payload only for diagnosed incidents |
| Cancellation commit barrier | write phase | No new call after revocation; reconcile calls accepted before the barrier |
| Repository workspace strategy | first write phase | Disposable read-only checkout first; approval-gated patch workspace later |
| CLI update cadence and compatibility window | production pin | Explicit scheduled upgrade PR with regenerated schema and canary, never floating latest |
| App Server `clientInfo.name` and enterprise compliance registration | production canary | Stable Boltrig client identity; confirm registration requirements with OpenAI |
| Observation-window length before legacy deletion | default cutover | Set operationally before canary; deletion cannot occur without completing it |

## Staged implementation plan

### PR 1 - Decision and protocol contract

- land decision 0012 and this map
- package or fetch the exact approved CLI in CI
- generate and check in stable 0.144.3 schemas and digest
- add schema-regeneration and compatibility checks

Gate: the packaged binary reports the expected version and regenerates a
byte-equivalent normalized stable schema.

### PR 2 - App Server client and supervisor

- add protocol, transport, supervisor, and runtime modules
- start with stdio and a read-only disposable cell
- create a sanitized workspace projection that excludes repository skill and
  project-control layers, use isolated `HOME` and `CODEX_HOME`, materialize only
  digest-pinned selected skills, disable unselected bundled skills, and fail
  closed unless `skills/list` exactly matches the assignment allowlist
- add fake-server tests for malformed frames, wrong IDs, duplicate responses,
  pre-initialize use, timeout, process exit, and bounded queues
- keep the feature disabled in production

Gate: initialize, thread start, turn start, event stream, completion, shutdown,
and crash cleanup pass with the exact binary and no MCP tools.

### PR 3 - Read-only phase lifecycle

- add root/phase-to-thread/turn bindings
- normalize events
- support start, resume, steer, interrupt, and restart reconciliation
- preserve existing chat and SSE interfaces

Gate: a read-only phase survives API reconnect and worker restart without a
duplicate turn, and Stop interrupts the exact active turn.

### PR 4 - Expiring grant broker and authority correction

- add durable grant leases, expiry, cross-process revocation, and policy
  generation
- remove ambient credential fallback
- stop skills from granting authority
- remove tenant-wide durable grant reconstruction and missing ceilings

Gate: expiry, revocation, membership change, approval change, duplicate token,
multi-process, and cancellation races all fail closed.

### PR 5 - Static profiles and skill catalogue

- add versioned profiles and profile ceilings
- expose progressive skill catalogue metadata
- copy only selected skill versions into a cell
- bind model, effort, sandbox, native-subagent caps, and MCP server policy

Gate: adversarial prompts, skills, memory, messages, and App Server config fields
cannot widen authority or alter the server-owned execution policy.

### PR 6 - Canonical work ledger

- add Alembic migration and schema bootstrap parity
- implement memory/Postgres store contracts
- make Hatchet a dispatcher/projection of phase assignments
- queue identity and requested scope rather than grants
- add result and verification records

Gate: store parity, RLS isolation, atomic transition property tests,
idempotency, exact claim/lease, retry, replacement-worker, and restore tests pass.

### PR 7 - Bounded native subagents in read-only phases

- configure approved custom agents and selected skill catalogue
- set thread and depth limits
- observe native subagent activity and parent relationships
- retain one Boltrig phase assignment regardless of Codex internal fanout

Gate: multiple native subagents remain bounded by the root phase profile, create
no Hatchet child-agent tasks, cannot exceed authority, and produce one structured
phase result.

### PR 8 - Approval-gated write phases and Opbox

- add the dedicated governed Opbox adapter
- implement per-call credential exchange, catalogue drift, audit correlation,
  and output redaction
- bridge command/file/permission requests to exact Boltrig approvals
- add disposable write workspace and verified patch/result flow

Gate: approval binding and single-use, SSRF/egress, credential non-disclosure,
catalogue drift, cancellation barrier, idempotency, and correlated Opbox audit
tests pass. No post-revocation domain call may begin.

### PR 9 - Deployment, readiness, and canary

- add the supervisor image/service and private transport
- replace readiness, doctor, status, receipts, environment, and manifest examples
- run shadow read-only traffic, then an internal tenant canary
- verify backup/restore and previous-release deployment

Gate: production doctor fixture, secure compose validation, readiness fail-closed,
fresh signed receipt, process-loss recovery, grant-broker loss, migration-head,
and restore drill pass.

### PR 10 - Default cutover and legacy removal

- route new complete workflow domains to Codex
- retain original-engine ownership for every in-flight root run
- complete the observation window
- explicitly deactivate legacy registry rows through migration
- remove OpenCode, Herdr, Ultracode scheduling, and Mastra compilation
- replace tests, invariants, docs, and status surfaces

Gate: `make quality`, invariant debt zero, migration/schema parity, security
gates, no active legacy rows, and no legacy source reference outside approved
historical allowlists.

## Cutover and rollback criteria

### Advance from shadow to canary only when

- exact-version protocol integration is green against the packaged binary;
- read-only lifecycle, genuine interrupt, and restart reconciliation pass;
- ledger and audit correlation have no unexplained gaps;
- no durable Opbox or parent credential reaches a Codex cell;
- authority is re-evaluated at every MCP call;
- production readiness fails closed when the supervisor, schema, grant broker,
  migration head, or required Opbox catalogue is missing.

### Advance from canary to default only when

- a complete workflow domain can run without split ownership;
- approval-gated writes, idempotent replay, HITL resume, cancellation, and
  replacement-worker recovery pass under fault injection;
- Postgres RLS and cross-tenant tests pass;
- normalized events are reconnectable and ordered enough to reconstruct the
  ledger projection;
- cost and token use are bounded by the profile;
- backup restore into a fresh database has been demonstrated;
- operators have exercised the rollback command and previous signed release.

### Abort or roll back immediately on

- any cross-tenant or cross-workspace visibility;
- any authority widening, stale approval, or accepted call after revocation;
- any uncorrelated Opbox effect or missing terminal audit event;
- duplicate domain effects or divergent canonical ledger state;
- cancellation that reports success while the turn continues admitting work;
- schema/binary drift, personal Codex state use, or remote unauthenticated
  listener exposure;
- unexplained loss, duplication, or reordering that prevents correct lifecycle
  reconstruction;
- readiness reporting healthy while a required dependency is unavailable.

### Rollback mechanics

1. Stop routing new roots to Codex at the workflow-domain boundary.
2. Revoke all affected run grants and prevent new Codex assignments.
3. Allow in-flight roots to finish under their original engine or cancel them
   explicitly; never migrate half of a run.
4. Reconcile every accepted tool call, result, approval, and audit event before
   declaring rollback complete.
5. Deploy the previous signed release and restore configuration routing.
6. Preserve new immutable audit and ledger rows for diagnosis; do not rewrite
   history.
7. Restore the database only for a proven data-corruption case, using the tested
   backup and a written reconciliation plan.

Legacy source may be deleted only after the agreed observation window, zero
unexplained ledger/audit divergence, successful fault and restore drills, and a
recorded go/no-go decision. Before deletion, rollback is a routing and release
operation. After deletion, rollback requires the previous signed artifact and,
where necessary, its compatible database snapshot.

## Definition of complete

The migration is complete only when:

- Boltrig is the sole durable workflow and authority source for migrated domains;
- Codex App Server is the sole general reasoning/subagent runtime;
- Opbox is the sole owner of its data and real-world effects;
- no OpenCode, Herdr, Mastra, or Ultracode runtime remains active;
- historical legacy records remain readable and honestly labelled;
- every security and correctness guarantee is bound in
  `tests/invariants.yaml` with zero invariant debt;
- local and CI quality gates, production doctor, backup restore, and staged
  rollback drills are green.
