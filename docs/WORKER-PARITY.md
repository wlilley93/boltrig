# Worker capability parity

**Status date:** 2026-07-30  
**Primary-surface decision:** [0021](decisions/0021-worker-primary-surface-and-realtime-voice.md)

Worker is Boltrig's only first-party browser surface. This ledger prevents the
client from implying that a visible control is backed by authority it does not
have.

## Parity rule

A Boltrig capability is covered by Worker only when:

1. the ordinary user lifecycle is available without leaving Worker;
2. every read is caller-scoped by the server;
3. every mutation uses the canonical kernel route or dispatcher;
4. pending approval, denial, degraded and unavailable states remain distinct;
5. secrets are accepted or shown only through their one-time contract; and
6. a focused contract or browser test proves the route and rendered state.

Raw event bodies, low-level configuration history and forensic diagnostics must
be represented in Worker or shown as an honest unavailable state. A missing
capability is not parity for an ordinary create, change, approve, revoke,
export, or recovery workflow.

## Surface ledger

| Boltrig family | Worker surface | Ordinary lifecycle | Authority / evidence |
|---|---|---|---|
| Task chat | New task and conversation history | send, stream, cancel, rename, regenerate, close, restore during the retention grace window, bounded reattach and serialized same-surface steer; preflight exact attachment limits and disclose the real model-context summary boundary | `/v1/chat`, owner-scoped conversation routes, shared structured-event normalizer; accepted non-text attachments are record-only while `text/*` reaches the model as untrusted data, an attachment-limit rejection restores the draft, the complete durable transcript remains visible after compaction, closed threads are read-only until their owner explicitly restores them, and Worker never exposes raw event payloads outside its bounded contract |
| Codex collaboration | Chat activity and Runs topology | render fleet delegation start/settle and durable child-work topology | Fleet subagents are live; Codex-native collaboration admission remains disabled pending the gates below |
| Familiar identity | Chat, Voice and Agents | structured genotype drives selected-subagent and capability-profile identity; root Chat and unbound voice indicators remain neutral | one versioned genotype is derived only from canonical `AgentCapability.name` and projected in discovery, actual selected-subagent events and voice participants. Agent cards consume it; phenotype/mood remains separate. No current/root identity is inferred. Voice resolves `agent_profile_id` tenant-side, rejects unknown, retired or non-realtime-capable profiles, and passes the bound identity/runtime to the gateway |
| Human decisions | Inbox | approval, question, clarification and escalation responses | `/v1/hitl`; owner questions use the dedicated answer route |
| Artifacts | Chat task rail | paged list, browser download and native user-chosen materialisation of recorded outputs, followed by Open/Reveal through the returned opaque handle | immutable owner/workspace-scoped metadata and byte routes; the canonical governed spawn seam records explicitly declared bounded outputs with server-owned provenance. Tauri receives bytes plus opaque handles, never an arbitrary path; stale handles are discarded and require another explicit save |
| Voice | Chat call control | create, join, list/recover recent calls, hold for approval, reconnect/reopen, end, transcript/event and usage receipt | scoped call routes and channel gateway; credentialed xAI/Tauri acceptance still required |
| Work | Work | cursor-page, filter and inspect parent/child/audit state in project, linear or board form; create canonical internal work, assign/unassign, apply approved legal status changes, and approved subtree reparenting | reads are tenant/department/active-workspace scoped; every write is a `control.work.*` dispatch, high-consequence changes bind the exact mutable snapshot, and active leases/in-flight rows are fenced. These controls change Boltrig's canonical work record only: no source-system writeback is claimed or attempted |
| Runs | Runs | cursor-page/search, cancel, execution/cost tree, durable subagent topology | scoped run, audit-tree and topology routes; Worker shows the events it can read and labels unavailable detail honestly |
| Agent profiles and permanent topology | Agents | list active and retired selectable profiles; create/update, retire and restore bounded profiles; author one Chief-of-Staff/department-head desired hierarchy and inspect its projection/startup evidence | capability rows remain explicitly “persistent profiles”, never live agents. Permanent hierarchy writes are closed, versioned high-consequence controls; they do not hot-apply, and profile/budget projection waits for the next manifest apply or redeploy. On restart `build_org` constructs the exact Chief and department identity, purpose, brief, runtime, model, skill, depth and cost policy. Startup observations prove construction only; runtime resolution/admission remains lazy and does not prove that a worker, endpoint or model cell is live |
| Model routing | Chat / Build / Operate | choose approved profiles, replacement-safe author endpoints, list active and retired endpoints, retire/restore without deleting configuration, bind active endpoints, inspect actual model receipts, and inspect the redacted process-start sensitive role and price table | exact-snapshot governed lifecycle controls preserve references; retired endpoints hard-fail runtime and new capability/fallback bindings, and stored fallback metadata never silently bypasses withdrawal. Worker labels the manifest default role inactive because no serving path consumes it, verifies whether the sensitive role is currently eligible, and names the price table's process-local cost-accountant boundary. The author-only endpoint detail returns its configured base URL so a complete replacement can be reviewed and edited; sealed provider keys, credential references and secret values never return. Policy mutation/rollback still requires a canonical versioned contract and process restart |
| Personal agent | Account | create/replace/invoke/delete and inspect a Codex-primary delegated agent | `/v1/me/agent`; acts on behalf of its owner; legacy deterministic configurations remain readable only for migration |
| Skills | Build | list active and archived definitions, replacement-safe create/update, archive/restore and bounded test-spawn with effective grants | complete author-gated projection retains every version and inheritance edge; archival is exact-snapshot governed, ordinary edits preserve status, archived skills and children of archived parents cannot be selected |
| Capability registry | Build | inspect active, archived and orphan nouns/verbs, replacement-safe create/update, archive/restore, and set bindings | complete author projections retain schemas, degraded/identity/idempotency modes and rate limits; archival retains definitions and bindings while runtime discovery, new binding and invocation fail closed. The reserved `control` noun and `control.*` verbs cannot be archived |
| Adapters and MCP | Build | inventory, generate inert source, inspect, activate/deactivate/delete ordinary adapters through exact requester-owned approval completion, register MCP consumers, explicitly probe them, inspect durable content-free probe history and last-known tool snapshots, govern activate/deactivate/retire/restore, replace an inactive server's complete configuration or credential mode, and delete an inactive or retired registration | generated adapters and MCP consumers are inert before review. Ordinary adapter lifecycle completion retains the exact action, route body and requester-visible adapter snapshot; form, selection and inventory changes invalidate stale intent before same-method replay. A generated adapter persists a bounded canonical executable projection—not the raw OpenAPI document—so boot, another replica, source inspection and approval reconstruct the same operation/schema generation while unused security schemes, examples, defaults, comments and extensions are not retained. Durable inactive state overrides stale replica-local instances. MCP credentials are named secret-store references and raw tokens are rejected. Reads never contact the external server. Probe is the only standalone MCP discovery action; it is bounded, approval-bound and persists only an allowlisted outcome code, timestamp, count and validated tool snapshot. Activation requires an existing reviewed snapshot, re-probes after approval and publishes only if the exact catalogue is unchanged. Configuration replacement invalidates all prior probe/publication evidence, advances a durable revision and requires a new probe. Update/delete approval binds the lifecycle generation, exact redacted-safe configuration and credential-configuration digest; stale probes, approvals and replica-local bindings fail closed. A probe never hot-publishes drift, inactive and retired snapshots remain visibly historical, and generic adapter lifecycle controls fail closed for MCP consumers. Replaced secret references are retained as opaque credential-store metadata because this lifecycle cannot prove that another resource does not share them; their identifiers never return to Worker |
| Automations | Automations | list/edit lossless DAG definitions, including explicit IF/ELSE branch arms and bounded typed `flow.loop` item/index bindings; save versions/tags, schedule/unschedule, trigger, execute, inspect runs/stats, archive and restore; bind authenticated webhooks or verified channels, enable/disable them, rotate webhook secrets and inspect delivery receipts. Existing `code.run` records remain visible and byte/semantically preserved but locked because code execution is disabled | canonical workflow, lifecycle and trigger-binding routes; archive preserves the definition, removes its schedule and blocks direct and indirect execution. Workflow source is read-only provenance: new authored definitions become `precreated`, edits preserve an existing `generated` or `learned` value, and authored requests cannot submit or forge it. The Worker serializer starts from every complete server step record, retains unknown fields and the original `params`/`with` form, and refuses to save malformed records it cannot safely represent. Loop bindings replace whole JSON values before ordinary governed dispatch; kernel schema validation, grants, HITL, idempotency and audit remain authoritative for every expanded action. Webhook secrets are hash-only and shown in a successful create/rotate response; secret-bearing approvals remain discoverable after navigation and the originating Worker surface explicitly finalizes the exact approved action (with run-backed calls held sealed until then), so an answer-side auto-resume cannot discard or leak the bearer. Source events remain nested untrusted input. Every webhook event re-authorizes the current delegator inside its captured grant ceiling, every channel event uses the currently verified sender, and revoked membership/identity fails closed |
| Integrations | Integrations | browse reviewed catalogue, inspect live connections, complete a certified versioned closed manual-secret contract, and revoke a connection through exact requester-owned approval completion | clean demo and manifest boots deterministically reconcile reviewed Jira, Runpod and xAI Voice definitions; certification covers the shipped adapter plus its closed credential-input contract, not tenant installation, activation, health or real-provider staging acceptance. Runtime availability remains derived from those tenant-owned records. Server catalogue entries override presentation metadata; secret fields are bounded, sealed immediately and never echoed, while account labels derive only from declared non-secret fields. Revocation retains only the safe connection snapshot and opaque approval id, invalidates selection and canonical-state changes, and replays the same SDK delete; secret setup values never enter that state. Uncertified previews and providers without a typed contract cannot request credentials. Tauri has a strict state-bound native return foundation, but provider-specific OAuth launch and exchange remain unavailable |
| Channels | Channels | connect/configure signed webhooks, voice, Slack Socket Mode, Telegram, Discord, Signal, WhatsApp and generic socket providers; select an initial/default target, author per-thread routes and bounded Member self-onboarding from caller-scoped catalogues; rotate write-only credential references, pair with a show-once code, bind/unbind, disable and disconnect; issue/dismiss a show-once channel-scoped gateway token; inspect safe owner-lease state plus bounded outbound delivery receipts and request an exact terminal-failure retry after repairing configuration | canonical channel administration plus authenticated gateway reconciliation exposes desired/observed revision and bounded heartbeat state. A durable tenant/channel lease elects exactly one token owner before resolved credentials, heartbeat, outbox or call links are available; standby gateways receive no provider credential. Worker exposes only the safe gateway label and lease expiry—not its private lease id, process liveness or provider certification. Delivery receipts expose only state, attempts, timestamps and a generic safe reason—never payload, destination, credentials, raw provider errors or gateway tokens—and retry is a governed exact-snapshot transition rather than arbitrary requeue. Secrets remain kernel-only references. Signal/WhatsApp pairing is explicitly `needs_action`; a configured socket remains `awaiting_gateway` until observed. The `msteams` value remains honestly a Teams-labelled generic HMAC webhook, not a Graph/Teams app, bot or OAuth integration |
| Knowledge | Knowledge | upload/index, browse, cited search, download original, erase, govern the bundled Cognee compiler and inspect external-provider availability | all mutations pass through governed Knowledge verbs. Supermemory and Mem0 remain visible but unavailable and cannot be enabled in this build because no credential-backed projection adapter exists; older persisted enabled rows are reconciled to unavailable rather than allowed to fail every compile |
| Memory | Memory | browse, recall, remember, mark facts useful or not useful, forget, ingest exact sources, inspect ingestion history, and open a durable exact-fact link | canonical memory verbs plus scoped projections, provenance and `memory.improve` feedback; exact-fact reads reauthorize tenant and owner scope and make hidden facts indistinguishable from missing facts |
| Evaluations | Evaluations | create/update skill or workflow fixtures, run, inspect exact targets/checks/verdict details and durable history, archive and restore fixtures | the target vocabulary is closed to `skill | workflow`; skills use the grant-capped spawner and workflows the governed interpreter under the caller ceiling and active workspace. Unknown legacy kinds execute nothing, and each run snapshots its target/detail independently of later fixture edits |
| Cost and budgets | Operate | scoped model/cost telemetry plus list/set/reset for tenant and department policies; exact current-window evidence, per-run isolation, and automatic UTC daily/monthly rollover; existing workflow rows remain inspectable but Worker does not author new inert workflow scopes | hard stops govern model-backed agent execution through the fleet spawner. Reservations return exact durable window receipts, so post-run true-up stays in the bucket originally charged even across a UTC boundary; reset generations prevent an older receipt from repopulating a cleared calendar bucket. A run budget without an exact run id fails closed and aggregate run usage is never invented. Pre-window run totals are retained by migration as non-current legacy data because they cannot honestly be attributed to a particular run. Workflow scopes, realtime voice provider usage, and direct paid adapter calls are still not charged |
| Audit and posture | Home / Operate | readiness, components/runtimes, bounded HITL-expiry, retention and password-reset notifier-attempt evidence, search, security stream, verify chains, export | maintenance receipts expose last attempt/success/failure, safe outcome, count and derived lag per opaque process/tenant; password-reset posture exposes configuration plus a recipient-free author/admin audit-tail attempt while non-authors receive restricted evidence. Neither kind claims liveness, complete replica inventory, a provider receipt or inbox delivery. Raw forensic bodies remain outside the browser contract |
| Global search | Cmd/Ctrl-K palette | retain local capability navigation while searching conversations, executions, Knowledge, Memory and safe Audit metadata; show partial denial/unavailability per source and open durable scoped destinations | canonical `/v1/search` composes each source's existing authority without cross-domain ranking or client-side scope joins; exact destinations reauthorize on open |
| Notification routing | Account | choose exact produced events and verified connected-channel destinations, enable/disable, queue a static test, inspect last delivery state | the server catalogue exposes only `approval`, `escalation`, `hitl_expired` and `work_status`, plus enabled socket channels bound to the caller. Test sends re-enter the dispatcher and existing durable outbox; `in_app`, email and arbitrary targets are not claimed |
| Account and privacy | Account | preferences/theme, bounded owner-filtered activity pages, explicit account-summary download, PAT mint/revoke, sessions, context switching | canonical `/v1/me` routes; PAT secret is show-once. The summary is not represented as a complete content/compliance export |
| AI keys | Account | list configured text/vision state, submit and remove organisation/workspace/user keys, and recover pending/approved/rejected/expired/consumed/invalidated/unavailable proposal state after navigation | set uses a purpose-built short-lived opaque proposal: Worker keeps plaintext out of React state, clears the uncontrolled input before awaiting, and the backend atomically envelope-seals it before creating approval. Inbox/audit/responses receive only routing metadata, modality, proposal identity and digest. The organisation text row is the main API default; the optional vision row is used for image turns, with text fallback when absent. Requester-only finalization reauthorizes current policy and approved resource snapshot, consumes once and removes staging; rejection, expiry, edit and drift clear it. Delete is non-secret and uses the shared exact finalizer (`SEC-WRK-33`) |
| Organisation | Organisation | policy, roster, workspace create/rename/settings/archive/reactivate, membership roles/permissions, user roles/scopes/status, scoped expiring invitations and provisioning | canonical role-enforced organisation/admin routes; invite tokens are shown once |
| Desktop devices | Settings | exact-code native enrollment, list/status/revoke, opaque-root register/revoke, recover orphaned local bindings/unreadable enrollment, and governed local read/staged-write/argv actions with owner-visible status/receipt reconciliation | action requests enter the dispatcher; a consumed non-self approval mints one signed lease; Tauri verifies before claim and uses only bound root-relative paths. The owner projection re-verifies device ownership and omits signed actions, paths/argv, approval/signature/claim material and arbitrary receipt fields. Exact pending inputs and bytes stay process-memory-only: React remounts recover them, but a renderer reload loses pending intent and JS-held bytes, while a native-process restart loses unread native buffers |
| Authentication | Auth gate / Account | invite acceptance, login, non-enumerating password-reset request/confirm, 2FA challenge/enrollment, forced password change, logout, and confirmed pre-auth local device cleanup in Tauri | reset bearers are hash-only, expiring and single-use; successful redemption revokes browser sessions and pending password-authenticated 2FA challenges. Delivery is an injected composition contract and mints nothing when absent. Operate shows redacted readiness and bounded attempt evidence, but notifier acceptance is not provider or inbox delivery. Interactive session authority remains in the httpOnly cookie plus CSRF in browser and desktop; the separately enrolled background device agent alone uses an origin-bound rotating keychain session |
| Locale and timezone defaults | Account | inspect the organisation-derived effective locale/timezone and replace either as a caller-owned preference | process-start manifest defaults are merged only when that caller has no stored override; the response identifies tenant defaults versus user overrides. Workflow schedules remain explicitly timezone-bound and do not silently inherit an account preference |
| Runtime add-ons | Integrations | list every registered extension and distinguish inactive, ready, missing, degraded, unavailable and unverified requirements | authenticated `/v1/addons` derives scope only from the principal and evaluates strict declarative requirements against persisted records and cached evidence; listing performs no provider probe or secret decryption and does not expose requirement references, environment names/values, credential metadata, harness text or evaluator exceptions. Installation, activation and configuration remain deployment or governed control-plane lifecycles |

### Background attempt evidence boundary

The fleet process owns HITL expiry and retention; the API process owns
`/readyz` and the authenticated Operate projection. They communicate only
through the bounded tenant-scoped receipt table. A receipt proves that one
opaque process instance completed one attempt and persisted its result. It
cannot prove that the process is still running, that every deployed replica
has published, or that a missing replica exists. If the database failure that
breaks a janitor attempt also prevents the evidence write, the visible result
is stale or unavailable evidence—not a fabricated failure receipt. The newest
four process receipts per tenant/job are retained, so this is deliberately not
a fleet inventory.

### Workflow editor semantic boundary

Worker can author `trigger.start`, `flow.branch`, `flow.loop`, `flow.end` and
caller-scoped governed actions. A direct child of `flow.branch` can select `IF / true`,
`ELSE / false`, or `Always`; the serialized top-level `branch` field is retained
on round-trip along with every unknown step field. Existing nonstandard branch
labels remain visible and preserved until deliberately changed to a supported
arm.

The displayed workflow source is immutable provenance, not an authoring field.
Worker and the shared SDK omit it from every upsert. The kernel assigns
`precreated` to a newly authored definition and preserves the source of an
existing definition, while its internal synthesis and learning paths remain the
only writers of `generated` and `learned`.

`code.run` remains outside Worker authoring. It does not execute code: the
interpreter returns `status: ok` with `output.executed: false` and the reason
that no sandbox is configured. Existing records remain visible, locked and
losslessly preserved.

`flow.loop` has a closed authoring and execution contract:

- A loop declares exactly one source: literal `items` or an `items_from`
  reference to an ancestor's `$step.output...` value. The selected sequence is
  stable, capped at 100 entries, limited to 256 KiB of canonical JSON and
  represented in the checkpoint by count plus digest. Excess entries are
  recorded and never dispatched.
- Its body is the maximal self-contained descendant subgraph. Nested loops are
  refused, a mixed external/body descendant is skipped as ambiguous, and an
  empty source dispatches the body zero times.
- A body step may declare up to 32 `loop_bindings` from an existing top-level
  parameter name to the closed source `item` or `index`. Binding replaces the
  whole typed JSON value. There is no interpolation, expression evaluation or
  arbitrary code.
- The complete contract is validated before any body action dispatch and before
  an authored definition is saved. Expanded step ids are deterministic
  (`step__0`, `step__1`, ...), so checkpoint replay, idempotency keys and HITL
  requests remain distinct per iteration; authored ids ending `__<number>` are
  reserved to prevent aliasing that namespace. Every bound action still passes
  through the kernel's ordinary schema, grant, approval and audit path.
- Worker exposes the loop source and body bindings, validates the same graph
  constraints before save, and retains unknown legacy definition and step
  fields. Full `code.run` support still requires a governed sandbox contract.

### Exact route and callsite evidence

The family table is backed by an exact executable ledger in
`tests/worker_surface_ledger.py`. At this status date it freezes 256
non-HEAD/OPTIONS HTTP method/path rows:

- 222 routes name the shared-SDK method and real Worker source that calls it;
- 4 redundant/helper routes name both their SDK method and the richer Worker
  method that supersedes it; and
- 30 routes have an explicit non-UI classification: 17 service-native
  machine/infrastructure boundaries, 2 external-ingress routes, 1 service
  probe, 1 internal-composition route, 1 superseded legacy route, 1 advanced
  compatibility route and 7 infrastructure-only routes. That group contains raw
  configuration/history/rollback/credential controls and the raw run-event
  stream. The Worker keeps these out of its browser contract until a typed
  configuration apply contract or bounded redacted event projection exists.

`tests/security/test_worker_route_ledger.py` fails when a backend route is added
without a declaration, a named SDK method or component disappears, a component
stops calling its declared method, or a public SDK method loses its Worker
callsite without an explicit classification.

The eight current public SDK methods without direct `client.*` Worker callsites
are intentional and pinned:

| SDK method | Classification | Worker treatment |
|---|---|---|
| `artifact` | superseded read | paged `artifacts` rows already contain the complete immutable detail |
| `artifactDownloadUrl` | internal helper | called inside `downloadArtifact`, which Chat uses |
| `cost` | superseded read | `consoleOverview` contains the same scoped totals plus status breakdown |
| `getCall` | superseded read | `calls` and `currentCall` already return the complete call record |
| `health` | service probe | load-balancer liveness is not a user lifecycle; Operate uses deep readiness |
| `refreshCallMedia` | compatibility helper | Worker recovery uses `reopenCall` and receives a fresh media session |
| `spawn` | advanced compatibility | ordinary delegation uses chat, personal-agent and bounded test-spawn flows |
| `submitIntegrationSecret` | unsupported contract | hidden until a provider has a certified typed secret contract |

### Cross-cutting primary-surface status

Exact route coverage does not by itself prove that Worker is a complete primary
experience. Worker now keeps the server-derived actor, role, organisation,
workspace and canonical pending-decision count visible throughout the shell.
It provides accessible Cmd/Ctrl-K capability navigation, and selected runs,
work items, agents, knowledge assets, memory facts, workflows and evaluation cases have
bounded canonical hash links that survive refresh and browser history. The
palette also performs canonical federated search across conversations,
executions, Knowledge, Memory and safe Audit metadata after two characters.
Results stay grouped by source, declare truncation or per-source failure, and
use re-authorized durable destinations; source-local scores never imply a
universal relevance order.

Conversation history/search, Inbox, Runs, Agents, Automations, Knowledge and
Memory distinguish initial loading, canonical empty, denied, not-found and
unavailable states instead of treating an empty array as proof. A transient
refresh failure retains previously authorized rows with an explicit stale
notice and retry; an authority denial clears them. Exact Work, Knowledge and
workflow selections use current-id plus request-sequence guards so an older
response cannot render beneath a newer durable URL. At compact widths, the
desktop task rail becomes a keyboard-trapped, inert-when-closed Task details
sheet, keeping artifacts and conversation restore/rename/regenerate/close
available without hiding the live voice transcript.

The remaining cross-cutting work is deliberately narrower:

- Worker shows the canonical pending-decision count globally. It does not claim
  an unread count because Boltrig has no durable decision read-receipt model;
- real-kernel Chromium now exercises the built shell, a governed chat turn,
  capability-palette keyboard focus/wrap, canonical Inbox approval and pending
  count convergence, and every initial route under Axe. It does not yet exercise
  a dropped/reloaded SSE turn, reject/question/timeout resume, connector delivery,
  artifact byte download or the full destructive lifecycle matrix; and
- browser tests do not prove Tauri commands, native save/folder dialogs, real
  media/WebRTC, external OAuth return navigation, OS keychain persistence,
  clipboard one-time-secret handling or updater/signature behavior. The macOS
  bundle now declares its narrowly worded microphone purpose in the Tauri
  `Info.plist`, but these behaviors still require packaged-native and
  credentialed-provider acceptance.

These are presentation and acceptance gaps, not permission to add alternate
backend paths. Their implementations must keep using the same SDK, kernel routes
and native command boundary named above.

## Non-HTTP completeness audit

HTTP route coverage is necessary but not sufficient for a primary surface. A
runtime or manifest feature is complete only when Worker can truthfully
**discover**, **configure**, **operate**, **observe** and **recover** it, or when
the lifecycle is explicitly deployment-only. The classifications below are:
`UI gap` (a complete backend contract is not surfaced), `contract gap` (Boltrig
itself cannot yet supply the lifecycle), and `deployment-only` (an intentional
former-client or infrastructure boundary).

`tests/worker_feature_ledger.py` is the executable source ledger behind this
table. Its `WRK-06` gate enumerates every top-level and nested typed manifest
field, accepted extra section, named serving loop, CLI command, Tauri
command/native plugin and retained internal seam across
discover/configure/operate/observe/recover. Adding a field or command without an
explicit lifecycle classification fails the gate; a covered parent section
therefore cannot conceal a parsed-but-inert child policy.

| Non-HTTP subsystem | Discover / configure | Operate / observe / recover | Classification and exact boundary |
|---|---|---|---|
| Durable fleet hierarchy, Chief of Staff and departments | Worker has a typed desired topology/editor, exact desired generation, safe-boundary profile/budget projection state and startup observations; flat non-ephemeral capability rows are labelled persistent profiles | On worker restart `build_org` now consumes both tier-1 and tier-2 identity, purpose, brief, runtime, model endpoint, supported-skill, depth and cost policy into lazy permanent runtime profiles. Each reasoning call uses the process-owned resolver with authored runtime/model policy pinned against caller overrides, reserves tenant/department budget, writes a redacted `model_call` audit row and falls back deterministically on a typed unavailable result. Routing/decomposition explicitly uses the read-only Codex phase: authored skills govern child selection and do not expose incidental tools to the head call. A named Codex endpoint whose model differs from the one process-composed into the supervised provider is refused rather than misreported. Startup records construction only: they do not probe an endpoint, admit a cell or prove process/model liveness | **Partial; safe dev/test runtime seam complete, production activation remains gated.** `boltrig/fleet/permanent_runtime.py`, `boltrig/fleet/runtime_resolver.py` and `boltrig/fleet/pump.py:710` own the live seam. Desired edits still require manifest apply/redeploy; hot reconcile and a current-worker heartbeat remain open. Trusted Codex remains off by default, rejects every production/staging signal and keeps `production_ready=false`; production admission must be completed separately |
| Codex provider and model-policy wiring in durable fleet processes | Worker can author a `runtime: codex` profile; API Chat/platform/direct spawn, agent-bound verbs, the standalone fleet pump, default Hatchet pump and Ultracode tasks all receive their process's one trusted-Codex configuration and configured sensitive/local endpoint role from one process-owned manifest snapshot | A source invariant rejects a packaged `build_spawner` call that omits either policy, and the same snapshot seeds API authentication, kernel policy and durable-fleet construction so a file change cannot split their routing. Missing Codex configuration remains typed unavailable, and missing sensitive routing remains a refusal rather than standard-provider fallback. Operate compares redacted effective-manifest, active-add-on, trusted-Codex and sensitive-role identities for retained API/fleet/Hatchet startup receipts against the latest API startup reference. Permanent CoS/head reasoning now resolves through that same process-owned resolver with authored runtime/model policy pinned, read-only routing/decomposition, metering and deterministic typed fallback. Startup evidence still never proves runtime admission or liveness | **Provider/model-policy composition, permanent runtime binding and startup comparison closed for safe dev/test; production admission and live-replica evidence remain gated.** `CODEX-COMPOSITION-1`, `SEC-WRK-27` and `SEC-WRK-30` cover the seams without re-enabling legacy runtimes. The API receipt is a comparison reference, not desired state; Worker must not infer a successful model call, current liveness or complete replica parity from it |
| Effective model roles and pricing | Worker projects an author-scoped opaque process-policy generation, current validity of the sensitive/local endpoint role, the per-model input/output price table and their exact serving boundary. The parsed tenant default role is explicitly inactive because no serving path consumes it | The sensitive role reaches every spawner and `models.prices` reaches the process-local cost accountant at boot. The projection contains no base URL, credential or provider topology, and it never calls stored endpoint inventory “effective policy.” Changes still require a process restart | **Observation closed; mutation/recovery contract gap remains.** A versioned, exact-snapshot governed replacement/rollback contract is still required before Worker may author these process policies |
| Spawn rules and classification | Worker inventories the exact effective process-start or latest persisted revision, projects every closed rule field, detects every reachable top-priority tie and provides a no-side-effect tag simulator | Preview input is explicitly untrusted: it cannot classify a task, authorize or execute a spawn, reserve budget or enter an execution receipt. Rules affect governed spawns only when a trusted server caller supplies explicit intent tags; ordinary Worker Chat still supplies none | **Observation/analysis closed; trusted-classification and authoring/recovery contract gaps remain.** Versioned rule mutation stays unavailable until Boltrig defines a canonical classification source and exact-snapshot governed authoring contract |
| Prompts, skills and department briefs | Worker has a complete governed skill prompt-fragment lifecycle and bounded test-spawn. Skill save/archive/restore retain exact typed inputs and finalize approved changes through their original SDK routes. Permanent purpose/brief fields are typed, closed and versioned in the hierarchy editor, with explicit restart and liveness language | Skill prompts are merged into child tasks. After restart, each permanent Chief/head purpose and brief is prepended as operator-authored prompt policy, subordinate to kernel authority, only when that profile reasons. Resolution or admission failure produces a typed degraded result and the existing deterministic route/decompose fallback; prompt text is not written to the permanent runtime audit row | **Authoring and safe dev/test runtime consumption closed; production Codex admission remains gated.** `apps/worker/src/components/build/SkillsBuild.tsx` owns skill authoring, `PermanentFleetTopology.tsx` owns hierarchy authoring/evidence, and `boltrig/fleet/permanent_runtime.py` owns permanent prompt consumption |
| HITL, approval and escalation policy | Inbox completes decisions and author identities see the redacted process-start blocking-verb list, timeout and opaque generation. Operate shows bounded expiry-janitor attempt receipts. Primary/notification channel and escalation chain are shown as inactive stored fields | Blocking verbs and approval timeout are read at kernel boot; timeout expiry is a worker janitor. Its receipts retain only safe attempt history per opaque process/tenant and cannot prove current liveness or replica coverage. `primary_channel`, `notify_via` and `escalation_chain` still have no serving consumer, so Worker never implies delivery or escalation. Changes require process restart | **Policy and janitor observation closed; mutation/routing-consumer contract gaps remain.** Versioned governed policy replacement and actual notification/escalation execution remain to build |
| Privacy, retention and compliance recovery | Account projects the exact process-start privacy policy and its coverage boundary; Operate shows bounded retention-janitor receipts. Account export remains labelled a summary, not a compliance archive | Only `privacy.retention_days` has a live consumer, and only for hard-erasing closed conversation messages. Last attempt/success/failure, safe count and derived lag are projected per opaque process/tenant, but are not liveness or proof of complete coverage. PII redaction, redact fields and residency are explicitly inactive because they do not govern every model, adapter, store or derived-data boundary | **Observation closed; enforcement/recovery contract gaps remain.** Complete erasure/export and redaction/residency enforcement still require the gates in `docs/proposals/policy-as-data-wiring-gates.md` |
| Network and egress policy | Operate shows the redacted policy consumed by the live `web.fetch` adapter: air-gap enabled state, proxy/CA configured state, allow/block entry counts, SSRF/redirect posture and direct-versus-proxy DNS handling. It never returns raw proxy, CA, domain or endpoint values | Manifest air-gap, allow/block domains, proxy and CA bundle now govern `web.fetch`; malformed CA configuration fails at adapter construction. Direct requests retain audited-IP pinning, while proxy resolution is explicitly delegated to the configured proxy. Browser, external MCP, other HTTP adapters, model providers and embeddings are listed as separate/partial/provider-owned surfaces because the manifest policy does not govern them | **Observation and `web.fetch` enforcement complete; deployment-only mutation and cross-surface enforcement gaps remain (`SEC-WRK-35`).** Changes require process restart. `boltrig/observability/network_policy.py` owns the redacted coverage contract; the backend must not call it a universal egress firewall |
| Authentication trust policy | Operate shows the effective process-start mode and whether the manifest/process generic-OIDC trios are configured and active, without returning issuer, audience or JWKS values | A complete manifest trio now selects generic OIDC when no higher-priority explicit session/Cloudflare deployment mode is selected. On the generic-OIDC path, a partial trio or disagreement with a simultaneously configured process trio refuses boot. Role mappings remain tenant policy | **Generic OIDC consumption and redacted observation closed; redirect/token UX remains deployment/provider work.** Trust changes require restart; session and Cloudflare Access stay explicit process modes |
| Runtime add-ons | Worker inventories the API process's registered add-ons, activation state and sanitized requirement readiness. Operate also compares the opaque active-add-on set identity in each retained API/fleet/Hatchet startup receipt with the latest API startup reference | Package installation, entry-point registration and `BOLTRIG_ADDONS` activation still happen only at process boot. Worker cannot activate, upgrade, roll back or restart packages. Receipts expire and are atomically pruned to the newest 32 per process kind, with reads hard-limited to 96 rows; absence cannot enumerate replicas and a reference match cannot prove that a process is still running | **Deployment-only lifecycle; bounded startup comparison implemented.** `boltrig/config/birth_profile.py` and `GET /v1/birth-profile` expose only opaque per-boot identities and explicit missing/stale/mismatch states. The latest API receipt is a reference, not authoritative desired state, heartbeat or complete replica inventory |
| Capability invocation | Build now discovers only the current caller-scoped registry and generates typed fields for a bounded closed JSON-Schema subset; the user cannot enter a noun, verb, raw params/context, approval id or credential value. Discovery also reports the verb's kernel-owned replay mode | Every generated submission uses canonical `POST /v1/invoke`. Completed, pending-human, denied, unavailable, degraded and error receipts remain distinct. A direct high-consequence pause is checked through the requester-owned, params-free approval-state projection and continues only with the exact component-held noun/verb/typed params and internal approval id; edits invalidate it, while rejection/expiry remain terminal receipts. Cacheable attempts retain one idempotency key across approval and ambiguous transport replay; disabled/unreported modes do not claim safe retry. Result payloads are projected through declared output fields only; secret, binary, composite, open-map, reserved-name and unsupported schemas remain visibly unavailable with the exact reason | **Worker safe subset complete; schema-specific surfaces still required outside it.** The compiler/projector is `sdks/web/src/capabilityInvocation.ts`; caller-only finalization is `boltrig/kernel/invoke_finalization.py`; the ordinary surface is `apps/worker/src/components/build/CapabilityRunner.tsx`; the canonical dispatcher remains the only executor. This deliberately does not turn arbitrary registry JSON Schema into a credential or raw-JSON console |
| Direct Worker mutation approval finalization | Inbox decides direct HTTP mutations. Every classified fixed control owns its completion path: the generic capability runner; Work, Memory and Knowledge changes; workflow save/schedule/lifecycle/dispatch and trigger controls; channel connect/configure/disconnect/bind/unbind/test-send; evaluation fixture lifecycle; account notifications; directory roles/status/scope; invitations; organisation policy; workspace lifecycle/membership; budgets; agent profiles; model-endpoint authoring/lifecycle; permanent-fleet hierarchy; authored nouns/verbs/bindings; skill authoring/lifecycle; ordinary adapter lifecycle; integration revocation; and non-secret AI-key deletion all retain and finalize their exact caller-held requests. Secret-bearing AI-key set, workflow webhook secrets and channel pairing codes use separate one-time lanes; delivery and workflow-occurrence retries remain snapshot-bound | A direct request with no run is deliberately assigned to the caller resume lane; the answer bridge has no durable run to re-enter. Non-secret controls share one finalizer retaining only cloned typed route input plus internal approval id. If an approved request re-pends because the resource fingerprint changed, the shared controller keeps the fresh handle and never retries the spent one. Purpose-specific secret lanes seal or defer creation before approval, recover only requester-owned safe intent, and reveal a value once. Snapshot recovery binds the approval to the exact mutable receipt. Every implemented lane keeps terminal and unavailable outcomes distinct and never infers success from pending or ambiguous consumption | **Closed for every listed fixed control (`SEC-WRK-32`, `SEC-WRK-33`).** `ExactApprovalFinalizer.tsx` owns the generic lane; Adapters, Integrations, Automation, Channels and Evaluations close their complete surfaces; `AiKeyManagement.tsx`, workflow-trigger finalization and channel-pair finalization own one-time contracts. Backend reauthorization and current-snapshot checks remain authoritative |
| Worker live-event vocabulary | Chat and Runs share typed message, reasoning, tool, subagent, approval/question, workflow, routing, steer, artifact and terminal events | The browser projector now admits only a reviewed field-by-field vocabulary. Live artifacts trigger a scoped artifact-list refresh, rejected declarations are surfaced, and an unknown or malformed internal frame becomes a content-free `event_unavailable` notice rather than reflecting its type or payload. The shared SDK explicitly consumes every admitted kind, so Ultracode/runtime frames cannot silently become ordinary Chat contracts | **Complete public event boundary (`SEC-WRK-31`).** The durable run relay may remain richer for governed audit use without expanding the Worker browser contract |
| Channel-to-agent exposure | Channels composes initial/default-target and per-thread-route controls from a backend-owned, caller-scoped catalogue of the chief of staff, visible permanent departments and active workspace-visible workflows. Constrained self-onboarding is a typed Member-only control with visible-department checkboxes and a bounded welcome. The synchronized advanced JSON remains only for lossless unrelated/legacy policy fields | Governed connect/configure rejects targets outside the canonical runtime contract and rejects an over-broad onboarding role/scope. Desired departments distinguish `restart_required` from startup construction evidence and never claim runtime liveness. Existing unknown targets remain visible as `stale_or_unsupported` until repaired. `workflow:<id>` targets execute before fleet routing; arbitrary agent/capability pinning remains explicitly unsupported | **Contract complete for supported channel addressing and onboarding (`SEC-178`, `SEC-180`).** This deliberately does not claim arbitrary ephemeral-agent pinning or permanent-runtime liveness |
| Codex rollout and runtime admission | Operate projects whether the execution-neutral OFF scaffold is composed, its bounded generation, shadow-decision state, legacy-only root route, inactive assignment admission, unavailable canary decision, trusted-provider dev posture and the two production-readiness constants | The projection is read-only and never admits or probes a cell. Native runtime configuration and runtime classes remain `production_ready=false`; durable per-cell preflight receipts and cell liveness are unavailable. Activation/emergency rollback remains server-owned deployment policy | **Observation complete; production activation gap intentionally remains.** `boltrig/observability/codex_admission.py` is the redacted contract. A durable fenced admission state, canary/rollback authority, current per-cell preflight receipts and deployment acceptance remain required before production can leave OFF |
| Langfuse trace mirror | Operate shows whether this API process's spawner has an enabled or disabled sink plus content-free attempt/success/failure counters and last outcome timestamps | The audit log remains authoritative. The projection includes no prompts, outputs, identities, route connection data, host or keys, and reading it never probes Langfuse | **Partial process evidence.** Sink health, provider acknowledgement, delivery lag, durable history and complete fleet/Hatchet replica coverage remain deployment-owned |
| Memory projection delivery | Memory and Operate expose canonical fact/source state plus bounded opaque remember/forget delivery receipts. The receipt records enqueue count, provider-operation attempts, the persisted attempt cap, safe failure class, receipt age and first-attempt wait without returning fact ids, projection ids, backend references, targets, content or raw errors | Provider delivery retries are capped inside the original task invocation and resume from persisted attempts after redelivery; a terminal duplicate is a no-op. Enqueue is attempted once because a thrown response cannot distinguish rejection from acceptance. Receipt age is not engine queue lag, and receipts prove neither queue depth nor worker liveness | **Observation and bounded automatic retry complete; governed recovery contract gap remains (`SEC-WRK-36`).** Manual replay is unavailable because the status receipt does not retain the original projection payload, and Boltrig cannot safely reconstruct it from a truncated fact label or a completed erasure |
| Scheduled workflows and worker janitors | Worker authors canonical schedule desired state and renders observed occurrence/recovery state. Operate shows bounded retention and HITL-expiry attempt receipts; anchor and all janitor intervals remain environment settings | The fleet process reconciles schedules only against a durable executor, re-authorizes the captured human and current workspace/grants at every tick, bounds catch-up, and atomically claims each logical occurrence. Retention and HITL receipts preserve safe last-attempt/success/failure/count/lag evidence per opaque process/tenant. They are not heartbeats and cannot enumerate replicas. Audit-anchor evidence remains the signed chain artifact rather than a loop-health receipt | **Core scheduling and two janitor observation paths complete; process liveness and audit-anchor loop health remain deployment concerns.** Scheduling is `boltrig/workflows/scheduler.py`, receipts are `boltrig/observability/background_jobs.py`, fleet composition is `boltrig/api/worker.py`, and Worker rendering is `OperationsView.tsx` |
| Audit anchors | Worker requests integrity verification and preserves the latest bounded anchor id, sequence range, time and evidence kind | Worker distinguishes an intact-but-unanchored chain, the local development fallback and externally signed evidence; denial and verification unavailability remain distinct. Interval/manual anchor control remains operational | **Worker observation complete; deployment-only trigger.** The complete response is `boltrig/kernel/platform_routes/observability.py:302`, the shared type is `sdks/web/src/types.ts:1852`, and the evidence UI is `apps/worker/src/components/OperationsView.tsx:247` |
| Backup and disaster recovery | Operate shows the scheduled sidecar's safe last-success marker, server-derived age and fresh/stale/missing/invalid state | A dedicated named volume contains only the atomic epoch marker; the kernel cannot read backup artifacts. The marker proves one complete backup command succeeded within the configured interval+grace, not sidecar liveness, off-box copy, encryption, replica coverage or restore readiness. Configuration and destructive restore remain infrastructure operations | **Freshness observation closed; restore-drill/off-box/encryption evidence gaps remain.** A full restore still requires libraries/manifest, secret-store recovery and the Hatchet database |

The primary-surface backlog must close every `UI gap`, and must keep each
`contract gap` visibly unavailable until the canonical backend exists. A flat
agent profile, saved cron string, parsed policy field, generic readiness card or
raw JSON editor is not evidence that the corresponding lifecycle is operational.

## Intentionally unavailable in the browser

- raw run-event payload and tool argument/result forensics;
- configuration version history, diff and rollback;
- credential-reference inventory and low-level runtime diagnosis; and
- migration, RLS and deployment administration.

These are advanced inspection or recovery controls. Worker shows them as
unavailable until the corresponding typed contract exists.

## Product capabilities that are not yet complete anywhere

Worker cannot provide an honest ordinary lifecycle when Boltrig itself has no
canonical contract for one. The remaining product-level gaps are:

- production Codex-native collaboration and the canonical execution projection.
  `CodexAgentRuntime.production_ready` remains false, production admission
  remains OFF, and the admitted read-only/kernel-tools profiles retain zero
  native-subagent limits. Worker therefore renders Boltrig child runs, not a
  Codex-native agent tree. The root/phase/work/assignment/result/verification
  records described in
  `docs/proposals/codex-app-server-integration-map.md` also have no public
  projection yet. A first-class Execution Inspector still needs phase DAGs,
  assignment/cell/attempt history, policy/model/skill pins, native-agent
  topology, exact steer/interrupt/resume/retry state, structured evidence,
  findings, blockers, handoffs and verifier outcomes;
- a complete asynchronous compliance/data archive spanning message bodies,
  knowledge originals, memory, artifacts, voice and audit evidence;
- autonomous workload-identity bootstrap for the now-canonical socket-channel
  gateway. Typed desired/observed provisioning and durable single-owner
  election are implemented for Slack, Telegram, Discord, Signal, WhatsApp and
  generic socket providers. Worker issues a show-once scoped token and the
  gateway can hot-load a rotated mounted token file, but placing that file is
  still an operator/deployment action. The MCP run-token registry is
  process-local, so multi-API-replica deployments also require sticky routing
  to the minting replica or a reviewed shared registry. Signal/WhatsApp retain
  their external pairing ceremony;
- a shared web/native Familiar phenotype and emotion-state contract. Worker
  renders canonical identity genotypes and live activity, but the richer
  Wayland phenotype, gesture/mood and voice-amplitude experience is still an
  external/local consumer rather than a scoped cross-replica projection;
- serving consumers for the remaining parsed-only policy fields and complete
  cost enforcement: escalation chains, privacy redaction/residency/field rules,
  workflow budgets, realtime voice and direct paid adapters. Spawn rules
  are now enforced for governed spawns that carry explicit intent tags, with a
  typed result/audit/event receipt that Worker labels on delegated activity;
  ordinary Worker Chat does not invent or accept a server-trusted
  classification, so it supplies no tags and keeps existing routing. Advanced
  rule authoring remains unavailable until Boltrig defines a canonical
  classification source. The exact
  matrix and required gates are in
  `docs/proposals/policy-as-data-wiring-gates.md`;
- typed provider OAuth exchange, kernel HTTPS callback and account selection for
  each certified OAuth integration. The native shell now registers one fixed
  custom scheme, correlates an exact expiring in-memory state and accepts only a
  kernel-brokered opaque result handle or denial. It rejects provider codes and
  tokens. No authorization page is launched until a reviewed kernel exchange
  and provider allowlist exist, and no production provider is inferred certified
  merely because the native return foundation or manual-secret contract exists;
- a first-class approval-policy/delegation model, decision-basis reads and
  no-side-effect dry-run execution;
- time-bucketed and provider-reconciled cost history;
- governed recovery for poison-terminal memory projection deliveries.
  `memory-projection-delivery` retains bounded content-free attempt evidence,
  but no replay is possible because the executor-owned original payload is not
  retained;
- a safe projection and recovery contract for the process-start memory engine
  and provider fan-out. Worker owns fact, recall, feedback and ingestion
  lifecycles, but it cannot currently identify the effective
  `local | vector | pgvector | cognee` engine, inspect its credential/readiness
  boundary, or repair provider configuration;
- credential-backed Supermemory and Mem0 Knowledge projection adapters. Their
  catalogue rows are deliberately unavailable until such an adapter can bind
  credentials, report health, compile/erase derived data and recover without
  becoming canonical authority;
- canonical built-in adapter-schema reconciliation. A code upgrade can leave a
  tenant's persisted verb definitions behind the installed built-in adapter
  implementation; the existing resync script is a deployment repair, not
  durable drift evidence or an exact-snapshot governed recovery action.
Those are backend/product contracts, not missing presentation work. Worker must
continue to label their current narrower substitutes exactly.

## Primary-surface experience debt

All classified fixed direct controls now have a requester-owned completion
lane. Adapter activate/deactivate/delete and integration revocation retain
secret-free exact snapshots, invalidate stale intent and replay only their
original SDK methods after approval.

The following controls reach canonical typed routes and are functional, but
they are not yet the neat ordinary-user experience expected of the primary
surface:

- organisation/user/workspace scopes, settings and permissions still use JSON
  object editors;
- work parent/owner selection and audit-run filtering still expect opaque ids;
- evaluation targets, inputs and assertions still expose references and JSON;
- workflow parameters and loop bindings still use JSON object editors;
- advanced channel routing/onboarding policy is one complete JSON editor; and
- local command execution asks for an argv JSON array.

These are presentation amendments, not authority gaps: guided pickers and
schema-derived forms must serialize to the same exact SDK bodies, invalidate
pending approvals when edited and leave kernel validation authoritative.

## Chat continuity boundary

Worker reattaches through
`GET /v1/conversations/{conversation_id}/events?follow=1&since={cursor}`.
The authorized server selects the conversation's active run; a browser cannot
provide a run id. Every replayed or live relay event crosses the same bounded
chat projection as `/v1/chat`, so tool argument and result values remain on the
separately authorized server run surface. Cursor frames report when the
bounded replay window has truncated earlier live activity.

The default relay retains 500 events per stream and 256 closed streams. The HTTP
cursor accepts `0..2^63-1`; the web SDK accepts JavaScript safe integers
(`0..2^53-1`). Development and offline tests use the in-memory backend.
Production refuses to boot without `REDIS_URL`: Redis Streams hold bounded
replay/live completion, active-run truth and the per-conversation hand-off lock,
so reconnect and steer admission continue across API/worker replicas. The
shipped Compose stack enables Redis AOF; an external Redis service must provide
equivalent persistence and availability. `BOLTRIG_EVENT_RELAY_NAMESPACE` must
match across replicas and should differ between deployments sharing a Redis
database. Same-surface follow-up text is never injected into a running runtime
directly: it uses `/v1/chat` and the canonical durable steer queue.

Redis carries the bounded raw run-event window, not only redacted Worker frames.
Its AOF therefore inherits the confidentiality of tool inputs/results: keep
Redis private, require authenticated TLS (`rediss://`) for an external service,
encrypt its storage/backup layer, and grant the Boltrig principal the Stream,
transaction, key and expiry commands exercised by `/readyz`. A namespace
separates keys; it is not an authorization boundary. The shipped local Redis
publishes no host port, but its AOF volume still relies on host-volume encryption.

## Gates that still block production-primary status

- **Codex-native subagents:** stable V1 collaboration is now the only typed
  dynamic-surface exception. The proxy pins its exact namespace and calls,
  prevalidates model/effort overrides, enforces a cell-lifetime total, binds
  live thread/depth caps through TOML, receipt and argv, terminates a phase on
  lifetime expiry, requires tree drain before root completion and projects
  structured descendant events durably. The exact pinned 0.144.3 binary now
  initializes with the stable V1 feature and live thread/depth argv pins.
  Production admission nevertheless remains zero until a real model-backed
  native spawn/tree-cleanup acceptance proves bearer revocation, and production
  cell config protection and preflight evidence are complete. Boltrig-owned
  fleet subagents continue to work.
- **Multi-replica relay:** real two-client Redis continuity, renewable locks,
  ownership CAS, cursor-gap/tombstone handling, capability readiness and
  fail-closed production composition now pass. The relay API is still
  synchronous and can block an async serving loop for its bounded Redis timeout,
  and Redis ownership is not a formal PostgreSQL fencing token across the
  message-write boundary. Production scale-out still requires async/executor
  isolation, a database-backed fenced admission state and restart/AOF fault
  acceptance.
- **Desktop actions:** the dispatcher, single-lease approval path, signed Tauri
  polling, pinned-verifier check, safe root-relative I/O/argv execution,
  receipt/session rotation, orphaned-root cleanup, unreadable-enrollment reset
  and React controls are implemented and covered by focused tests. A bounded
  owner route now recovers durable lease status and allowlisted receipt summaries
  after navigation or reload; exact pending inputs and bytes never enter browser
  storage. They survive React remounts only in renderer memory. A renderer reload
  loses an unfinalized pending intent and any JS-held read bytes; not-yet-retrieved
  local bytes are recoverable only while the native process still holds that lease
  buffer. An expired claimed receipt window is shown as unknown outcome, never as
  proof that the native action did not run. Production also needs a
  packaged-app acceptance run against the real OS keychain, folder/save dialogs
  and a staged device.
- **Desktop distribution:** Settings projects whether the binary contains a
  complete signed-release configuration, checks only its compiled HTTPS
  endpoint, retains the exact checked release in native memory, verifies the
  package natively, installs it and allows restart only after native installer
  success. A browser or build missing either the endpoint or public verification
  key stays explicitly unavailable; the webview cannot provide release trust, a
  package URL, signature or bytes. Cross-platform packaged update acceptance and
  publishing remain release gates.
- **Legacy desktop hands:** the opt-in Hyprland-oriented `desktop.*` window and
  application verbs remain governed by the kernel, but their host pull executor
  is a separate add-on and is not implemented by the cross-platform Worker
  device lease runner. A deployment must install and test that executor before
  advertising the verbs.
- **Artifact production:** the immutable memory/Postgres store and scoped
  list/detail/download routes are implemented, with no upload endpoint. A bounded
  canonical runtime-result seam now records explicitly declared artifact bytes
  with server-owned scope and provenance; free-form model text is never inferred
  as a file and no caller-supplied native/server path is accepted. Desktop save
  cancellation is terminal and never falls through to a browser download; the
  main webview has no direct dialog permission.
- **Connectors:** each integration remains non-connectable until its live adapter
  and auth contract pass certification. Presentation metadata is not
  certification.
- **Password-reset delivery:** request, one-use redemption, audit and Worker UI
  are implemented. `/readyz` can require both an injected notifier and its
  bounded redacted probe, and Operate exposes configuration plus recipient-free
  author/admin evidence from the latest bounded audit tail. A notifier accepting
  an attempt is not a provider receipt or inbox-delivery proof. A production
  deployment must still compose a reviewed provider adapter and credentials,
  then pass real staging delivery/bounce acceptance. Without a notifier the
  route deliberately returns the generic response and mints no bearer; there is
  no console or log fallback.
- **Realtime voice:** concurrent calls now use isolated, bounded provider/audio
  sessions and fail explicitly when the configured pool is full. Credentialed
  provider staging and Tauri media acceptance remain required. The macOS bundle
  includes `NSMicrophoneUsageDescription`; an actual signed/notarized package
  must still prove the permission and media lifecycle.
- **OAuth and native return:** Tauri registers `boltrig-worker://oauth/callback`,
  denies raw callback reads through the command surface and accepts only the
  exact active in-memory integration/state plus a kernel-brokered opaque result
  or `access_denied`. Browser and unregistered builds are explicit unavailable
  states. The kernel still lacks the reviewed provider callback/exchange and
  authorization-origin allowlist, so Worker deliberately opens no authorization
  URL and assumes no connection. Native arm/take/cancel primitives therefore
  have no production UI callsite and are classified as contract gaps rather
  than Worker lifecycle coverage. Packaged scheme registration and return
  acceptance remain release gates.
- **Authentication variants:** first-party session/invite/2FA/recovery is the
  Worker-native flow, and Cloudflare Access can remain an upstream gate. A
  generic OIDC deployment still needs an explicit browser redirect/token
  handoff contract; Worker must not fall back to a password form that the
  configured resolver cannot accept.
- **Hatchet:** webhook/channel admission, event idempotency, HITL sealing and
  handoff to the configured durable workflow task are covered in-process. The
  live durable engine still needs service-backed acceptance for scheduled,
  externally triggered and recursive production runs; local execution remains
  the explicitly degraded fallback.
- **Cutover:** accessibility, browser/Tauri acceptance, security gates, signed
  image validation and an operational soak must pass before the Worker-primary
  compose overlay becomes the ordinary production route.

The release must keep these states visible as unavailable, uncertified or
degraded. It must not turn absence of evidence into a green status.
