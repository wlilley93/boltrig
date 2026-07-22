# Boltrig engine components

The definitive catalogue of every component that makes up the Boltrig engine, written for the owner first and engineers second. Plain language leads, precise detail follows. Every claim below was verified against the code in this repository (paths are repo-relative), and every maturity call is honest: where something is a stub or a stand-in, it says so.

**How to read the maturity labels**

| Label | Meaning |
| --- | --- |
| production-grade | Real logic, on the live serving path, pinned by binding tests |
| wired-but-thin | Real and reachable, but its full value needs an external service, a key, or config that is absent by default |
| scaffold/stub | Exists as code but is either a placeholder, never invoked in serving, or explicitly non-durable |

**What "governed by" means.** Boltrig keeps a catalogue of binding invariants in `tests/invariants.yaml` (98 declared ids at the time of writing, each bound to at least one real pytest test; `scripts/check_invariants.py` refuses unbound claims and undeclared markers, and the debt count may only ever fall). When a component lists invariant ids, those are the guarantees the test suite pins to it.

**The one-sentence picture.** Boltrig is a thin, policy-owning kernel that forces every action an organisation's AI agents take through one fixed, audited path, with a fleet of agents above it, a memory system beside it, and everything organisation-specific supplied as data (the manifest), not code.

A metaphor that holds up throughout: the kernel is the security desk in a building's only lobby. Every visitor (a chat message, a webhook, an MCP tool call) must pass the same desk, show the same credentials, sign the same ledger, and sometimes wait for a manager's signature, no matter which door they came in through. The fleet is the staff upstairs; the store is the filing room; the manifest is the building's rulebook.

---

## Part 1: The kernel

### 1.1 Dispatch chokepoint (the ten-step gate)

**One line.** The single ordered path every side-effecting action runs, with no second path.

**Plain language.** Think of an airport security lane that every passenger walks through in the same order: identity, ticket, scanner, and so on. The chokepoint is that lane for actions. Whether an action arrives from chat, a webhook, the REST API, or an agent's tool call, it runs the exact same ten checks in the exact same order, and the last step (writing the audit record) happens no matter what, even when the action was refused.

The ten steps, as implemented in `Dispatcher._invoke_inner` and the surrounding `invoke`:

1. Resolve the verb and its binding (unknown verb fails closed)
2. Validate the input parameters against the verb's JSON Schema
3. Check grants (caller grants AND the tenant ceiling)
4. Consequence/HITL gate (a high-consequence verb pauses for a human; cannot be bypassed)
5. Rate limit
6. Idempotency replay (a repeated key returns the prior result, no re-execution)
7. Resolve the credential (inside the kernel only) and execute the adapter or agent
8. Validate the output against the verb's output schema
9. Record the idempotent result
10. Audit, always, in a `finally` block (allowed, denied, degraded, and crashed calls all get a row)

The dispatcher also publishes paired `tool_call`/`tool_result` (and `hitl`) events onto the run's event stream as a pure side channel: a relay failure never breaks a call. When a backend is unavailable, a verb with a declared degraded mode returns a marked degraded output instead of crashing (graceful degradation, P9).

**Key files.** `boltrig/kernel/dispatch.py`; wired together in `boltrig/kernel/__init__.py` (`Kernel.__init__` constructs the dispatcher with all its collaborators).

**Public surface.** Not directly HTTP; it backs `POST /v1/invoke`, every MCP `tools/call`, every memory/control/skill/workflow verb, and every agent tool call.

**Governed by.** K-13 (fail-closed), SEC-21 (schema before side effect), SEC-07 (grants), SEC-14 (HITL cannot be bypassed), FR-KER-05 (rate limits), SEC-15 (idempotent replay), SEC-16 (every action audited), SEC-26 and SEC-37 (chokepoint parity from MCP and headless paths), P9 (degradation), FR-EVT-01/02 (paired tool events as a side channel).

**Maturity.** Production-grade. This is the most heavily tested object in the repository. One honest caveat: budgets are enforced at agent spawn time, not per verb call - the dispatcher holds no `CostAccountant`; cost accounting lives in the fleet spawn path via `Kernel.cost` (see 1.9).

### 1.2 Registry and discovery

**One line.** The noun/verb/binding catalogue, populated from adapter self-descriptions, with caller-scoped discovery.

**Plain language.** A vending machine's button panel. Each adapter arrives and declares its buttons (verbs) with their shapes (schemas) and blast radius (consequence). The registry upserts them as data; no kernel code changes when a new integration arrives. Discovery is a one-way mirror: you only see the buttons your grants let you press.

**Key files.** `boltrig/kernel/registry.py` (`KernelRegistry`, `register_adapter_verbs`); the verb vocabulary lives in `boltrig/models/registry.py`.

**Public surface.** `GET /v1/capabilities` (scoped discovery), `POST /v1/nouns`, `POST /v1/verbs`, `POST /v1/verbs/{verb_id}/binding` (authoring, admin-gated), `GET /v1/capabilities/changelog`.

**Governed by.** US-KER-05 (discovery is caller-scoped), SEC-32 (authoring is RBAC-gated and audited), SEC-39 (an authored verb with a destructive name defaults to high consequence).

**Maturity.** Production-grade.

### 1.3 Grants and RBAC

**One line.** Who may press which button: caller grants intersected with the tenant ceiling, deny dominates, fail closed.

**Plain language.** Two locks on every door. The first lock is the caller's own keyring (the union of their loaded skills' tool grants, or their role's scope). The second is the building-wide master rule (the tenant permission ceiling). You need both. An explicit deny beats any allow; an empty keyring opens nothing; a look-alike key cut with confusable Unicode characters never turns either lock (matching is NFKC-normalised over a safe charset).

**Key files.** `boltrig/kernel/grants.py` (`GrantChecker`), `boltrig/models/grants.py` (`GrantSet` semantics), `boltrig/identity/rbac.py` (IdP group to role and scope, scope to `GrantSet` ceiling, role precedence with superadmin/admin/member console tiers).

**Public surface.** None of its own; enforced at step 3 of every dispatch and inside discovery.

**Governed by.** K-2 (ceiling caps grants by intersection), K-5 (deny dominates), K-9 (wildcards match the noun namespace, not bare prefixes), K-13 (empty grants deny everything), SEC-07, SEC-62 (confusable ids never match), US-IAM-02 (department row isolation).

**Maturity.** Production-grade.

### 1.4 HITL manager (human-in-the-loop)

**One line.** Creates and resolves the approval, clarification, and escalation requests that pause high-consequence actions.

**Plain language.** The counter-signature book. When an agent asks to do something with real blast radius (send an email, delete a ticket, change config), the kernel writes a request in the book and refuses to proceed. A human answers it; the approval is bound to that one verb and is spent on use, so it cannot be replayed or reused for a different action, and the requester cannot sign their own slip.

**Key files.** `boltrig/kernel/hitl.py` (`HITLManager`: `create`, `answer`, `consume_if_approved` via the store's atomic compare-and-swap `consume_hitl`); the respond route in `boltrig/kernel/app.py` rejects agent and self-approval.

**Public surface.** `GET /v1/hitl`, `POST /v1/hitl/{request_id}/respond`. Pause events also stream inline into chat.

**Governed by.** SEC-14 (blocking verbs pause, approval is verb-bound, single-use, and human), NFR-REL-01 (a blocking pause is durable in Postgres, surviving restart), FR-CONV-04 (inline HITL events in chat).

**Maturity.** Production-grade for the gate and records. Durable resume of a paused run across restarts is proven at the Postgres store level; the fully durable resume loop in production is Hatchet's job (see 2.12).

### 1.5 Credentials vault

**One line.** Secrets are resolved only inside the kernel, at call time, from an external secret store; the database holds references only.

**Plain language.** A locked key cabinet behind the security desk. Agents never hold keys. When a verb executes, the desk fetches the right key, hands it to exactly one adapter call, and takes it back. The key never appears in logs, results, or memory; the audit writer actively refuses to persist anything shaped like one.

**Key files.** `boltrig/kernel/credentials.py` (`CredentialResolver`, `SecretStore` protocol, `EnvSecretStore`); `Credential` in `boltrig/adapters/base.py` suppresses its material in `repr` and `str`.

**Public surface.** `GET /v1/admin/credentials` (references only, admin-gated). Never any route that returns material.

**Governed by.** SEC-05 (resolved material never enters the audit log), K-20 (bounded observability), SEC-27 (no tool credential is ever sent to the Pi gateway).

**Maturity.** Production-grade design; the only shipped `SecretStore` is env-backed (`EnvSecretStore`). Vault/KMS backends are declared seams, not implementations.

### 1.6 Audit chain

**One line.** Every action writes exactly one append-only row, hash-chained per tenant, so tampering is detectable.

**Plain language.** A ledger where each line includes a fingerprint of the line before it. Tear a page out, reorder two lines, or change a word, and re-deriving the fingerprints exposes it. The writer also scrubs: details are screened for secrets and identity, storing a digest plus a bounded 256-character preview instead of raw content.

**Key files.** `boltrig/kernel/audit.py` (`AuditWriter`, HMAC over a canonical serialisation, key from `BOLTRIG_AUDIT_HMAC_KEY`); `boltrig/models/audit.py` (`AuditEvent`, `ActionType`).

**Public surface.** `GET /v1/audit/search`, `POST /v1/audit/export`, `GET /v1/audit/tree/{run_id}`, `GET /v1/runs` (all scope-filtered).

**Governed by.** SEC-16 (every action, allowed or denied, audited, hash-chained, append-only, contiguous under concurrency), K-19 (tamper-evident), K-20 and SEC-05 (scrubbing), SEC-33/FR-OBS-02 (scope-filtered insight).

**Maturity.** Production-grade. The default HMAC key is a marked dev value; bootstrap refuses to start with it when a production signal is present.

### 1.7 Idempotency

**One line.** A repeated idempotency key returns the recorded prior result instead of re-executing a side-effecting verb.

**Plain language.** A receipt system for retries. If the network hiccups and a client sends "create this invoice" twice with the same receipt number, the second request gets the first result back; the invoice is not created twice.

**Key files.** Steps 6 and 9 of `boltrig/kernel/dispatch.py`; `idempotency_get`/`idempotency_put` on the store (`boltrig/store/base.py`, both implementations).

**Public surface.** The `idempotency_key` parameter on `POST /v1/invoke` and internal dispatch calls.

**Governed by.** SEC-15 (repeated key never re-executes; distinct key executes again), tenant-separated in the store parity suite.

**Maturity.** Production-grade.

### 1.8 Rate limits

**One line.** Per-verb, per-tenant fixed-window counters enforced in the kernel before any outbound call.

**Plain language.** A turnstile that only lets so many people through per minute. The counter lives in Redis in production and in memory for dev/tests, behind one `Counter` protocol; if the counting backend goes down, the kernel degrades gracefully rather than crashing.

**Key files.** `boltrig/kernel/ratelimit.py` (`RateLimiter`, `Counter` protocol, `InMemoryCounter`; Redis is the production backend). Limits arrive as data on each verb binding (`VerbSpec.rate_limit`, including limits derived from OpenAPI `x-ratelimit` extensions).

**Public surface.** None; enforced at step 5 of dispatch, surfacing as HTTP 429 with retry-after.

**Governed by.** FR-KER-05 (enforced at the kernel), P9 (degraded mode when the backend is down).

**Maturity.** Production-grade.

### 1.9 Budget and cost

**One line.** Token and cost ceilings per scope; a hard-stop budget refuses to commit a call that would exceed it, a soft one records overage and alerts.

**Plain language.** A prepaid card per department. Before an agent run starts, the engine checks the card can cover the estimate; a hard-stop card declines, a soft card lets it through but flags the overspend. At 80 percent usage an alert fires pre-emptively. Cost is attributed into audit rows so the execution tree can total spend per run.

**Key files.** `boltrig/kernel/cost.py` (`CostAccountant.reserve`, alert at `_ALERT_FRACTION = 0.8`); budgets are seeded from manifest hierarchy tiers by `apply_manifest`.

**Public surface.** `GET /v1/cost`, `GET /v1/budgets`.

**Governed by.** FR-COST-02 (hard stop halts before exceeding; soft records overage only).

**Maturity.** Wired-but-thin in one specific sense: `reserve` is called only from the fleet spawner (`boltrig/fleet/spawn.py`, via `Kernel.cost`) with tenant and department scopes. The dispatcher holds no `CostAccountant`, so there is no per-verb budget check at the chokepoint, and the workflow/agent-type scopes described in the docstring are not passed at enforcement time.

### 1.10 Egress guard

**One line.** One shared SSRF defence every outbound HTTP adapter runs before any network call.

**Plain language.** The building's outbound mailroom checks every parcel's destination address. Anything addressed to the building's own internals is refused: private, loopback, and link-local addresses, the cloud metadata endpoint 169.254.169.254 (the classic route to stolen cloud identity tokens), and any domain outside the allowlist or inside the blocklist. The check is on resolved IPs, not just names, so a public name pointing at internal space (DNS rebinding) is still refused, and adapters must not follow redirects blindly.

**Key files.** `boltrig/adapters/egress.py` (`assert_egress_allowed`, `is_blocked_ip`, `resolve_host`); consumed by `boltrig/adapters/http_base.py`, `web_fetch.py`, and `mcp_consumer.py`. The policy data is the manifest `network` section (air gap, allow/block domains).

**Public surface.** None; a pure decision function.

**Governed by.** SEC-52 (web.fetch SSRF-guarded and NetworkConfig-enforced), SEC-61 (shared guard blocks metadata for every HTTP adapter), SEC-53 (internet access is a governed verb).

**Maturity.** Production-grade, fully testable offline.

### 1.11 PII and secret screening

**One line.** Deterministic, model-free scanning that redacts personal data before it leaves the boundary and hard-blocks secrets from ever being recorded.

**Plain language.** Two filters at the exit door. The first blurs personal details (emails, card numbers, SSNs, phones, IPs) before content goes to an external model: redaction by default, upgradeable to "route to a local model" via the model router. The second is stricter: anything that looks like an API key, bearer token, or password is not redacted but refused outright, so it can never enter the audit log or the memory system.

**Key files.** `boltrig/kernel/pii.py` (`_PATTERNS` for PII, `_SECRET_PATTERNS` and `contains_secret` for the hard block); consumed by the audit writer and the memory adapter.

**Public surface.** None; invoked at the boundaries.

**Governed by.** SEC-13 (PII detected and redacted before leaving), K-20 (audit scrubbing), SEC-42 (secrets never become memory), SEC-05.

**Maturity.** Production-grade for what it is: conservative regex patterns, explicitly meant to be tuned per deployment, not a trained classifier.

### 1.12 HTTP front door and web hardening

**One line.** The FastAPI app: authenticate, build a context, call the same kernel, with edge hardening stamped on every response.

**Plain language.** The lobby itself. The HTTP layer holds no policy; it works out who you are, packages your request, and hands it to the one desk. Around it, a hardening layer adds security headers (HSTS, nosniff, frame-deny, strict CSP), an explicit CORS allowlist (same-origin by default, never a wildcard with credentials), Host validation, and a request-body size cap.

**Key files.** `boltrig/kernel/app.py` (`create_app`, the `Principal` shape, the canonical error envelope, the lifespan that builds the kernel on the serving loop); `boltrig/kernel/web_security.py` (all middleware); route modules registered at the end of `app.py` (platform, access, memory, channel).

**Public surface.** The core inline routes: `GET /healthz`, `POST /v1/invoke`, `POST /v1/mcp`, `POST /v1/chat` (SSE), `GET /v1/conversations` and `/{id}`, `GET /v1/capabilities`, `POST /v1/spawn`, `GET /v1/hitl`, `POST /v1/hitl/{id}/respond`, `GET /v1/work` and `/{id}`, `GET /v1/audit/tree/{run_id}`, `GET /v1/runs/{run_id}/events` (SSE). Plus everything in sections 1.13 to 1.16.

**Governed by.** SEC-58 (headers, Host, body cap), SEC-01 (auth), SEC-56/FR-EVT-03 (tenant-scoped run events), US-IAM-02, SEC-33.

**Maturity.** Production-grade.

### 1.13 Channel gateway and channel routes

**One line.** External messaging channels become governed intake: verified signature, kernel-authoritative identity, then the one chokepoint — with a severed gateway terminating the socket class, durable dedup/outbox, and tiered addressing.

**Plain language.** A mailbox on the outside wall with a very suspicious mailroom behind it. An inbound webhook is only accepted if its HMAC signature verifies and its timestamp is inside the replay window. The tenant comes from the verified channel record, never the payload. The sender is mapped to an internal identity through a tenant-scoped binding row; an unknown sender is denied fail-closed, or walked through a pairing flow (short one-time codes, hashed at rest, TTL-bounded, lockout after repeated wrong guesses). The resulting message becomes a normal governed work item. Outbound replies go through `channel.send`, a high-consequence verb, so a human gate applies by default.

Phase 2 (the socket class) landed: the severed `services/channel_gateway` daemon — the one message edge, policy-free — holds the persistent platform connections the stateless kernel must not, owning no policy/grants/persistent credential. It signs normalized inbound messages into the SAME intake route with the connect-time secret (one intake path) and pumps the durable `channel_outbox` over a run-scoped token minted through the MCP seam (claim/ack/fail-with-backoff). Replay dedup is store-backed (`channel_deliveries`, atomic record-and-check; messages with no platform id are content-hashed inside a 5-minute window), so it holds across workers and restarts. Intake stamps ADDRESSING on the work item: a target slug (the tier-1 chief of staff by default; a named tier-2 subagent/run when the sender or the channel's chat→target config mapping addresses one) plus the reply route, and notifications (HITL approvals, escalations, run completion) enqueue back to the user's bound surface and originating thread per `notification_prefs` (user- and department-scoped). Platform adapters wired with round-trip proofs against fake platform servers: Slack (Socket Mode), Telegram (long-poll), Discord (WS gateway), Signal (signal-cli sibling), WhatsApp (vendored MIT Baileys bridge, sibling Node image) — all derived from the MIT-licensed Hermes gateway adapters with attribution; live-platform verification is the operator's step (`services/channel_gateway/README.md`). The reference "custom interface" adapter (JSON-lines over localhost TCP, plus `clients/custom_surface.py`) is the seam the desktop-familiar, hey-nabu, and site front-ends target; the boltrig UI stays a first-party head on the kernel API (SSE relay), never a gateway channel.

**Key files.** `boltrig/kernel/channel_principal.py` (`resolve_channel_principal` — renamed from `channel_gateway.py` when the daemon took the gateway name), `boltrig/kernel/channel_routes.py` (ingress + management + pairing + addressing), `boltrig/kernel/channel_gateway_routes.py` (session mint + outbox links), `boltrig/kernel/channel_notify.py` (notification round-trip), `boltrig/adapters/builtin/inbound_webhook.py` (`verify_and_normalise`, durable dedup), `boltrig/adapters/builtin/channel_send.py`, `boltrig/models/channels.py`, `boltrig/store/channels.py`, `boltrig/store/channel_dedup.py`, `boltrig/store/channel_outbox.py`, `services/channel_gateway/`. Decision record: `docs/decisions/0003-channel-gateway-ruling.md`.

**Public surface.** `GET/POST /v1/channels`, `PATCH/DELETE /v1/channels/{id}`, `POST /v1/channels/{id}/inbound` (signature-authenticated ingress), `POST /v1/channels/{id}/pair`, `GET/POST /v1/channels/{id}/bindings`, `DELETE /v1/channels/{id}/bindings/{binding_id}`, `POST /v1/channels/gateway/session` (admin), `POST /v1/channels/gateway/outbox/claim` + `.../outbox/{id}/ack|fail` (run-scoped token).

**Governed by.** SEC-01 (the channel gateway, inbound, and governance test batteries), SEC-63 (replay window), SEC-39 (channel.send is high consequence and tenant-scoped), SEC-05 (secrets and pairing codes hashed at rest), SEC-175 (durable replay dedup), SEC-176 (outbox single-winner CAS), SEC-177 (gateway token auth + generic-adapter round trip), SEC-178 (addressing is routing data, not authority), SEC-179 (notification round-trip), SEC-28 (gateway severability).

**Maturity.** Production-grade for the webhook/request-response class; Phase-2 skeleton landed for the socket class (generic adapter end-to-end, durable dedup/outbox/addressing wired; platform ports pending). Note the intake honesty in 8.2: a channel-created work item currently has nothing pumping it onward (the delegation pump gap), and the run-completion notification seam (`channel_notify.notify_work_item_result`) awaits its pump call site.

### 1.14 MCP server face

**One line.** Granted verbs advertised as MCP tools; every `tools/call` runs the unchanged chokepoint.

**Plain language.** A standard wall socket for AI tools. Any MCP-speaking client (the Pi gateway, Claude Code, another agent) plugs in and sees a tool list, but the socket is wired straight back into the one security desk: the tool list shows only what that connection's token is scoped to, and every call runs all ten steps, including the human gate. A run-scoped token (the run's skill grants intersected with the tenant ceiling) is minted per agent run and revoked when it ends.

**Key files.** `boltrig/kernel/mcp.py` (`McpFace`: `issue_run_token`, `revoke`, `handle` for run tokens, `handle_user` for console principals; JSON-RPC 2.0 `initialize`/`tools/list`/`tools/call`).

**Public surface.** `POST /v1/mcp` (run token via the `x-boltrig-mcp-token` header, or an authenticated principal), `POST /v1/mcp/servers` (register an external server to consume, see 6.3).

**Governed by.** FR-MCP-01 (granted verbs with schemas as tools), FR-MCP-02 and SEC-23 (run-scoped exposure, out-of-scope denied), SEC-26 (chokepoint parity including the HITL gate), SEC-37 (headless parity).

**Maturity.** Production-grade.

### 1.15 Identity and auth

**One line.** Token verification, IdP-group to role mapping, JIT provisioning, personal access tokens, and delegated identity, all fail-closed.

**Plain language.** The ID-checking booth, with four kinds of ID accepted. (a) OIDC: a real JWT verified against the issuer's published keys, with a pinned algorithm allowlist, expiry required, and an ID token refused where an access token is expected. (b) Cloudflare Access: the edge authenticates the person, the kernel independently verifies the signed assertion and maps the verified email to a role; an authenticated but unmapped email is denied. (c) Personal access tokens: stored only as hashes, bounded expiry, and their authority is the intersection of the token's declared scope and the owner's current grants, re-checked every call, so a deactivated user's tokens die with them. (d) SAML: a declared seam that refuses to run without a real validator plugged in. A separate dev resolver trusts headers for local work and hard-refuses to start when any production signal is present. Delegation (acting as a user downstream via OAuth 2.0 token exchange, RFC 8693) is a seam with the decision logic in place. Invitations pre-stage a role but grant nothing until a real SSO login consumes them once.

**Key files.** `boltrig/identity/auth.py` (`OidcVerifier`, `SamlVerifier`, `build_principal_resolver`, `build_cf_access_resolver`), `rbac.py`, `tokens.py` (PAT), `provisioning.py` (JIT users, current grants), `delegation.py` (OBO seam); resolver selection in `boltrig/api/bootstrap.py` (`select_principal_resolver`).

**Public surface.** No auth routes of its own (the IdP owns login); it is the dependency on every route. Self-service and admin surfaces: `GET/PUT /v1/me/settings`, `GET /v1/me/activity`, `GET /v1/me/export`, `GET/POST/DELETE /v1/me/tokens`, `GET /v1/me/connections`, `GET/DELETE /v1/me/sessions`, `GET/PUT /v1/me/notifications`, `GET /v1/me/agent`, `DELETE /v1/me/conversations/{id}`, `GET/PATCH /v1/admin/users`, `GET/POST/DELETE /v1/admin/invitations`.

**Governed by.** SEC-01 (invalid/missing bearer rejected, valid token scoped, the full CF Access battery), SEC-59 (JWT algorithm allowlist, access-token-only, expiry required), SEC-60 (dev auth impossible in production), SEC-34 (PAT never escalates, dies with the user), SEC-35 (invitations do not bypass the IdP), SEC-36 (settings writes RBAC-checked and audited), SEC-38, SEC-30 (personal agents are delegated-only), SEC-65 (auth binds the tenant before the first RLS read).

**Maturity.** OIDC and CF Access are production-grade; PAT, provisioning, and invitations are production-grade; SAML is a scaffold seam (raises `NotImplementedError` without an injected validator); delegation's token exchanger is a seam awaiting a concrete implementation.

### 1.16 Control plane (governed config)

**One line.** Live config amendment as governed kernel verbs, with versioned history and rollback.

**Plain language.** Changing the rulebook is itself an action that goes through the security desk. Editing a workflow, capability, or model endpoint is a `control.*` verb: grant-checked, HITL-gateable (config mutation is high blast, so consequence is high), and audited, rather than a quiet database write. Alongside it, an admin config service versions every section change as a revision, exports a manifest round-trip, and can roll back. Department and agent profiles are re-read live per call, so a change takes effect without restarting the router.

**Key files.** `boltrig/config/control_plane.py` (`ControlPlaneAdapter`: `control.workflow.upsert`, `control.capability.upsert`, `control.model_endpoint.upsert`), `boltrig/config/admin.py` (`AdminConfig`, `ConfigRevision`).

**Public surface.** `GET/PUT /v1/admin/config/{section}`, `GET /v1/admin/config/{section}/history`, `POST /v1/admin/config/{section}/rollback`, `POST /v1/admin/config/export`; the `control.*` verbs via any dispatch surface.

**Governed by.** SEC-51 (config writes are kernel verbs: grant-checked, audited, HITL-gateable), FR-ADM-02 (round-trip and rollback), FR-CTL-01 (profile config takes effect live).

**Maturity.** Production-grade.

---

## Part 2: The fleet

### 2.1 ChiefOfStaff

**One line.** The tier-1 router that names which department should own a work item.

**Plain language.** A head of the front office who reads each incoming item and says "that's for engineering" or "that's marketing". It can ask a reasoning model, and falls back to deterministic routing by source channel and intent keywords when no model is available. A live `departments_provider` means an admin's org change takes effect on the very next call.

**Key files.** `boltrig/fleet/chief_of_staff.py` (`ChiefOfStaff`, `Department`).

**Public surface.** None; a library class.

**Governed by.** FR-CTL-01 (live department reload).

**Maturity.** Scaffold, honestly: the class is never constructed anywhere in the serving path (only in tests). The live chat path reuses the string "chief-of-staff" as an actor label and calls the spawner directly, and the fleet worker (see 8.2) never polls it. Real routing code, no caller.

### 2.2 DepartmentHead

**One line.** The tier-2 agent that decomposes a routed item into sub-tasks and spawns a worker per sub-task, with fan-out caps.

**Plain language.** A department manager who breaks a job into pieces and hands each piece to a temp worker, but with hard limits: at most 8 children per step, a running spawn budget, at most 16 new items per step. Hitting a cap does not blow through it; it files an escalation for a human instead.

**Key files.** `boltrig/fleet/department_head.py` (`DepartmentHead`, `_extract_subtasks`, `_escalate`).

**Public surface.** None; a library class.

**Governed by.** No binding invariant pins it (its docstring cites US-FLT-02/US-EXE-04, which are not declared ids in `tests/invariants.yaml`).

**Maturity.** Scaffold: never constructed in serving or in tests. The fan-out caps exist as code that nothing invokes.

### 2.3 Spawner

**One line.** Where routing becomes execution: compose skills, validate context, pick the cheapest capable runtime, enforce depth and budget, run, audit.

**Plain language.** The staffing agency. Given a task and a list of skills, it assembles the full skill packet (each skill plus its `extends` ancestors, merged parent-first), checks the job comes with everything the skills require (JSON Schema context validation), hires the cheapest capable worker profile, refuses if the org chart is already too deep or the budget card declines, caps the child's authority at the parent's (grant ceiling intersection, so a child can never out-rank its parent), routes the model choice through the sensitive-data guard and the gateway, runs the runtime, and writes an `AGENT_SPAWN` audit row. It also announces the sub-agent on the parent's event stream.

**Key files.** `boltrig/fleet/spawn.py` (`Spawner.spawn`, `build_spawner`, `make_app_spawner`, `make_agent_invoker`, `_resolve_skill_chain`, `_select_capability`).

**Public surface.** `POST /v1/spawn`; also the kernel's `agent_invoker` for agent-bound verbs, and the chat turn executor's engine.

**Governed by.** US-FLT-04 (cheapest capable runtime), FR-EXE-03 (depth bound), FR-COST-02 (budget), SEC-12 (sensitive spawn blocked from hosted capability), SEC-29/SEC-30 (no escalation via grant ceiling), FR-SKILL-02 (context requirements).

**Maturity.** Production-grade, and the true workhorse of the live path. Note: a plain chat turn spawns with an empty skills list, so no skill composition happens on ordinary chat; the cheapest capability wins.

### 2.4 Runtime family (script, hermes, claude-api, pi)

**One line.** The interchangeable reasoning backends a capability names; all degrade to a marked non-crash result without keys.

**Plain language.** Four kinds of worker you can hire, all wearing the same uniform (`Runtime` protocol, returning `AgentResult`). Script is the deterministic no-model fallback: it literally echoes the task back (zero tokens, zero cost). Hermes and Claude-API are single-shot model calls (OpenAI-shaped and Anthropic respectively): no tool loop, one completion. Pi is the only multi-step, tool-calling lane (see 2.5). The honest and load-bearing behaviour: without an API key or endpoint, every non-script runtime returns a degraded result with a reason (`no_api_key`, `no_endpoint`, `no_sidecar`) rather than crashing, and the script runtime is a literal echo. In a keyless environment, "the agent replied" therefore means "the engine echoed", which is why degraded honesty is first on the plan (Part 10). Every runtime prepends the kernel-composed system prompt so the governance cage cannot be stripped. Decision 0012 gate: Codex is the only target agent runtime and script stays the deterministic fallback, so every other lane (hermes, openai, claude-api, pi, opencode, rivet) is staged-cutover rollback residue reachable only when `BOLTRIG_ENABLE_LEGACY_RUNTIMES` is set (default OFF); with the flag unset a legacy lane request returns the typed unavailable result (`runtime_unavailable`, degrade-marked under the requested lane's name) instead of reaching the lane.

**Key files.** `boltrig/fleet/runtime.py` (`Runtime`, `ScriptRuntime`, `HermesRuntime`, `ClaudeApiRuntime`, `build_runtime`), `boltrig/fleet/result.py` (`AgentResult`, where even a degraded run is `ok=True` with `output["_degraded"]` set).

**Public surface.** None directly; selected by capability data (`AgentCapability.runtime`).

**Governed by.** FR-RUN-01 (pi resolves via `build_runtime`), FR-RUN-05 and P9 (degrade, never crash), US-FLT-04, US-WFL-02 (reasoning runtime else deterministic fallback).

**Maturity.** Wired-but-thin toward the real backends (single-shot, degrade to echo without keys); production-grade on the degrade path itself.

### 2.5 PiRuntime and the Pi gateway service

**One line.** The one agentic, tool-calling lane, run in a severed sandboxed process that reaches tools only through the kernel's MCP socket.

**Plain language.** The one worker allowed to use power tools, kept in a locked workshop. The kernel-side `PiRuntime` mints a run-scoped MCP token, posts the job to the gateway over HTTP, streams its events back, and revokes the token afterwards. The gateway (a standalone FastAPI service, deliberately outside the `boltrig` package) receives only a model key and that token: no filesystem, no processes, no tool credentials, network egress restricted to the kernel and the model. Inside, it runs a loop: ask the model, execute any tool calls through `tools/call` on the kernel MCP face (so every tool call passes the full ten-step gate, including the human gate, which pauses the loop), feed results back, repeat up to `max_steps`. Honesty: this loop is a first-party stand-in written so the service works with no external Pi package; its own docstring marks `run_loop` as the integration point where a real third-party agent loop would replace the body. Offline it degrades to listing the tools it would have had.

**Key files.** `boltrig/fleet/pi_runtime.py` (`PiRuntime`, `build_request`); `services/pi_sidecar/app.py` (`run_loop`, `McpClient`, the FastAPI app).

**Public surface.** Gateway: `GET /health`, `POST /run` (streaming ndjson). It consumes `POST /v1/mcp` with the `x-boltrig-mcp-token` header. Compose keeps it on the `sandbox` network only, with no published port.

**Governed by.** FR-RUN-02 and SEC-27 (only the scoped MCP connection and model, no tool credentials), FR-RUN-03 (every tool call passes the chokepoint), FR-RUN-05 (degrades without the gateway), SEC-24 and SEC-48 (sandbox declared and enforced in the deploy manifests), SEC-28 (kernel and models import nothing from Pi or the gateway), SEC-23/FR-MCP-02.

**Maturity.** Wired-but-thin: the transport, sandboxing contract, token scoping, and degrade paths are real and tested; the reasoning loop is a home-grown stand-in, not the real Pi library.

### 2.6 Chat orchestrator and SSE event relay

**One line.** A chat turn becomes a governed work item and a spawned run whose live events stream back over SSE and are persisted.

**Plain language.** The reception phone line with a live intercom. When a message arrives, the service checks you may use this thread (owner-scoped; only org-admin and compliance may read others'), persists your message, mints a run id, and starts the turn in the background while forwarding every event from the relay to your browser as it happens: text deltas, tool calls, sub-agent announcements, inline approval cards. When the run ends, the assistant message (with the full event list) is persisted, so a dropped client can re-attach to the same run and replay what it missed. The relay itself is an in-memory, single-process fan-out with a 500-event backlog per stream, by design a thin stand-in for Redis pub/sub in a multi-replica deployment. Publishers: the chat executor, the spawner, the dispatch chokepoint, and (relayed) the Pi gateway.

**Key files.** `boltrig/fleet/chat.py` (`ChatService`, `build_turn_executor`, `sse`), `boltrig/kernel/events.py` (`EventRelay`).

**Public surface.** `POST /v1/chat` (SSE, `data: {json}` frames), `GET /v1/conversations`, `GET /v1/conversations/{id}`, `GET /v1/runs/{run_id}/events?follow=0|1` (tenant-scoped snapshot or follow; unknown run is 404).

**Governed by.** FR-CONV-04 (events stream into the turn and are recorded), FR-CONV-06 and SEC-25 (conversation confidentiality), FR-EVT-01/02/03/04, SEC-55 (run-keyed and credential-free), SEC-56 (tenant-scoped run events).

**Maturity.** Production-grade streaming and persistence; honest caveat that on a plain keyless turn the entire "assistant reply" is one `text_delta` carrying the degraded spawn summary, and the relay is single-process.

### 2.7 Continuity

**One line.** Deterministic, append-only composition of the conversation's own history into the task before each spawn.

**Plain language.** The worker re-reads the whole thread before answering, but mechanically: a plain labelled transcript, concatenated the same way every time, where turn N's rendering is always a prefix of turn N+1's (which keeps a gateway's prompt cache warm). It composes only the caller's own tenant-and-conversation-scoped messages and adds no authority.

**Key files.** `boltrig/fleet/continuity.py` (`compose_turn_task`, `render_transcript`, `continuity_enabled`; `BOLTRIG_CONTINUITY=0` disables).

**Public surface.** None; called by the chat turn executor.

**Governed by.** SEC-46 (deterministic, append-only, no authority), SEC-49 (scope-safe).

**Maturity.** Production-grade and live.

### 2.8 Prompt stack

**One line.** The layered system prompt: a non-overridable governance floor, then tier character, then an optional department slant.

**Plain language.** Every worker's briefing card, printed top-down: house rules first (the cage no input can strip, because every runtime and the gateway place it above user content), then the voice for the rank (chief of staff, department head, or worker), then a department flavour. A human caller gets no system prompt at all.

**Key files.** `boltrig/fleet/prompt_stack.py` (`GOVERNANCE_FLOOR`, `TIER_CHARACTER`, `compose_system_prompt`); prompt data also under `libraries/prompts/`.

**Public surface.** None; consumed by every runtime and by the gateway request builder.

**Governed by.** No binding invariant id; exercised by `tests/unit/test_prompt_stack.py` without invariant markers.

**Maturity.** Production-grade composition on the live path; the content is three hardcoded strings.

### 2.9 Model router (sensitive to local)

**One line.** Sensitive data may only go to a local model endpoint; a misroute is blocked and audited, never quietly allowed.

**Plain language.** A customs rule for data: anything stamped "sensitive" must not leave the building. If the chosen model endpoint is hosted, the router swaps in the configured local endpoint; if none exists, it refuses the call outright and writes an audit row saying why.

**Key files.** `boltrig/fleet/model_router.py` (`select_model_endpoint`); endpoints and `sensitive_endpoint` come from the manifest `models` section.

**Public surface.** None; runs inside every spawn.

**Governed by.** SEC-12 (blocked and audited, routes to local, spawn blocks sensitive on hosted), SEC-43 (sensitive memory stays local).

**Maturity.** Production-grade, fail-closed, on the live path.

### 2.10 Model gateway seam

**One line.** A conversation-pinned binding that re-points model calls at an external cost-aware gateway (Bifrost), inert until configured.

**Plain language.** An optional switchboard between workers and model providers that can cache and meter calls. Boltrig's part is the plug: it pins each conversation to one model for its whole life (so caching works and answers stay consistent) and re-points the endpoint's base URL at the gateway, but only for standard data; sensitive traffic is never re-routed (residency preserved). With no gateway URL set, the seam does nothing at all.

**Key files.** `boltrig/fleet/model_gateway.py` (`ModelGateway`, `apply_gateway`, env `BOLTRIG_MODEL_GATEWAY_URL`); `boltrig/fleet/model_gateway_status.py` (safe platform-status snapshot); the `bifrost` compose service (profile-gated, internal port 8080, default loopback admin port 8081).

**Public surface.** `GET /v1/platform/status` includes a redacted `bifrost` / `model-gateway` snapshot: configured or inert, cache TTL, profile count, and live-health posture. Optional live polling is internal-host-only and returns only coarse health/cache/provider counts. It never returns gateway URLs or credentials.

**Governed by.** SEC-47 (binds per conversation, never re-routes sensitive, inert when unset), FR-GW-01 (wired into the stack so activation is one env line plus keys), FR-GW-03 (safe operator status), FR-GW-04 (bounded internal live health).

**Maturity.** Wired-but-thin: fully inert by default, tested binding logic, safe status reporting exists, and optional live health polling is bounded. Rich cache/provider metrics still depend on the external gateway.

### 2.11 Eval harness

**One line.** Runs an eval case through the real spawn path under the initiator's own grants and scores what was actually called.

**Plain language.** A driving test on real roads with the learner's own licence: the eval spawns the target skill exactly as production would, capped at the tester's authority so a test can never escalate, then reads the audit trail to check which verbs were called (`must_call`, `must_not_call`), that forbidden grants were absent, and that the output matched.

**Key files.** `boltrig/fleet/eval.py` (`EvalRunner.run_case`).

**Public surface.** `POST /v1/eval/cases`, `POST /v1/eval/run`, `GET /v1/eval/runs`.

**Governed by.** FR-EVAL-02 (runs through the chokepoint under a defined scope), SEC-29 (test spawns cannot escalate).

**Maturity.** Wired-but-thin but genuinely reachable and on a serving path (unlike 2.1/2.2); offline it scores against the script runtime.

### 2.12 Workers and executors (LocalDurableExecutor, HatchetExecutor, hatchet_app)

**One line.** The durability seam: Hatchet wraps steps durably in production; a loudly non-durable local executor stands in offline.

**Plain language.** Two kinds of job board. The production one (Hatchet) writes every run down so a crashed process resumes where it left off. The dev one is a whiteboard: `LocalDurableExecutor` runs the step and notes it in an in-memory Python list; its own docstring says it does not persist, retry, or resume across a restart, and `durable = False`. Which one you get is decided at boot: if the Hatchet SDK imports and a client constructs, `HatchetExecutor`; otherwise the local fallback. Honesty on the production half too: `HatchetExecutor.run_step` awaits the function directly — the installed hatchet-sdk (1.33.x) exposes no public durable child-step API on `DurableContext` (only durable waits/sleeps and a private memo), so a step is not its own engine-durable unit today. What the workflow-run path guarantees instead (hatchet_app `run_workflow_body` wires BOTH seams): the engine retries the whole durable task on a crash, checkpoints replay every completed step without re-dispatching it, and a deterministic per-step idempotency key replays the recorded kernel result for a step that completed but whose checkpoint write was lost. Only a genuinely in-flight step re-executes, with standard at-least-once engine-retry semantics. The remaining seam is per-step engine durability: if a future SDK adds durable child steps, `HatchetExecutor.run_step` is the single method to upgrade.

**Key files.** `boltrig/fleet/workers.py` (`LocalDurableExecutor`, `HatchetExecutor`, `register_workers`), `boltrig/fleet/hatchet_app.py` (`build_hatchet_app`, `ping`, `hitl_demo`, `approve`), `boltrig/fleet/hatchet_worker.py` (the worker entrypoint against a live engine).

**Public surface.** Python interface only (`new_run_id`, `run_step`); `python -m boltrig.fleet.hatchet_worker` serves workflows against a live Hatchet engine.

**Governed by.** FR-WFS-04 (a registered workflow becomes a live durable run), NFR-REL-01 (durable HITL pause survives restart, proven at the Postgres store), live-engine coverage in `tests/integration/test_hatchet_live.py`.

**Maturity.** `LocalDurableExecutor` is a deliberate non-durable stub; `HatchetExecutor` is wired-but-thin; the Hatchet app and worker are real integration code that activates only with the SDK and engine present.

### 2.13 Work intake and queue

**One line.** Source-agnostic normalisation of raw payloads into one `WorkItem` shape, with confidence scoring and a write-back seam for discovered work.

**Plain language.** The inbox clerk. Whatever arrives (a webhook body, a queue payload), it is flattened into the same work-item form: intent, source, constraints, a confidence score that decides whether the job runs convergent (known shrinking steps) or divergent (explore first). A `QueueAdapter` protocol defines poll-and-write-back so real sources (Jira, Monday) follow the same shape as the in-memory reference.

**Key files.** `boltrig/work/normalise.py`, `boltrig/work/queue.py` (`QueueAdapter`, `InternalQueueAdapter`, `score_confidence`), `boltrig/work/store.py` (`WorkItemStore` with transitions and discovered-work write-back).

**Public surface.** `GET /v1/work`, `GET /v1/work/{id}` (kanban and detail, scope-filtered); the channel ingress route calls `normalise` directly.

**Governed by.** US-IAM-02 (scope-filtered listing), SEC-01 (signed inbound creates a governed work item).

**Maturity.** Production-grade normalisation; the honest gap is downstream, not here: after intake, nothing pumps pending items to routing (see 8.2 and Part 10).

### 2.14 Skills system (loader, schema, shelf)

**One line.** Skills are pure data (prompt fragment, tool grants, context requirements) composed at spawn, plus a governed browsable shelf.

**Plain language.** Laminated recipe cards, not employees. A skill carries instructions (the prompt fragment), a wish-list of tools, and a checklist the job must satisfy. Cards inherit (`extends`, parent-first). Two ways to use them: loaded eagerly by id at spawn, or browsed on the shelf: `skill.search` returns lightweight descriptions only (never the body, progressive disclosure), `skill.describe` shows selection metadata, `skill.load` composes the inheritance-merged body bound to the job's context. Crucially, a loaded skill's `tool_grants` are returned as data, not granted, so a skill can never escalate its holder.

**Key files.** `boltrig/skills/loader.py`, `boltrig/skills/schema.py`, `boltrig/skills/shelf.py` (`SkillShelfAdapter`); skill data under `libraries/skills/`.

**Public surface.** `GET/POST /v1/skills`, `POST /v1/skills/{id}/test-spawn`; the `skill.search`/`skill.describe`/`skill.load` verbs via dispatch.

**Governed by.** FR-SKILL-01 (descriptions only, filtered), FR-SKILL-02 (composed body bound and validated against context requirements), SEC-57 (shelf is governed; load does not escalate), SEC-29 (test-spawn under initiator grants).

**Maturity.** Production-grade.

---

## Part 3: Memory

### 3.1 Memory engine protocol

**One line.** The engine-agnostic contract: remember, recall, improve, forget, health, over scoped facts and explicit edges.

**Plain language.** The job description any memory backend must fill, so backends are swappable data. A fact carries who owns it (`user:<id>`, `department:<name>`, or `org`), what kind it is, its provenance, and explicit links to related facts; recall takes the caller's allowed scopes and a mode (plain similarity, or graph completion that walks links up to a hop limit).

**Key files.** `boltrig/memory/engine.py` (`MemoryEngine` protocol, `EngineFact`, `RecallHit`).

**Public surface.** None; the interface behind the adapter.

**Governed by.** The contract that SEC-40/41/44 are enforced against.

**Maturity.** Production-grade interface (pure contract).

### 3.2 Memory adapter (the isolation boundary)

**One line.** The kernel-side gate for all memory verbs: scope checks, injection screening, secret hard-block, residency, edge pruning, least-privilege audit.

**Plain language.** The archivist at the records room door, running five checks before anything is filed: you may only file into a drawer you own; content is screened for prompt-injection and malware markers; anything that looks like an API key is refused outright (a poisoned or leaky note is rejected, never filed); sensitive material must be processed by the local machine, not a hosted one; and links pointing out of your drawers are cut. On the way out, recalled hits are re-filtered to your drawers (defence in depth, in case an engine misbehaves), and the ledger records that you searched and how many hits you got, never what the facts said.

**Key files.** `boltrig/memory/adapter.py` (`MemoryAdapter`, `screen_content`, `permitted_scopes`, `build_memory_adapter`); registered as a normal kernel adapter, so every memory verb runs the ten-step gate.

**Public surface.** The `memory.remember|recall|improve|forget` verbs; HTTP at `POST /v1/memory/recall|remember|forget|ingest`, `GET /v1/memory/facts|ingestions` (`boltrig/kernel/memory_routes.py`). There is no HTTP route for `memory.improve`; it exists as a verb only.

**Governed by.** SEC-40 (kernel is the isolation boundary at ingestion and retrieval, multi-hop included), SEC-41 (memory is data, never authority), SEC-42 (poison and secrets rejected fail-closed), SEC-43 (sensitive memory stays local), SEC-44 (complete, ledgered erasure), SEC-45 (recall audited without leaking contents), SEC-31.

**Maturity.** Production-grade. The injection screen is a fixed marker list (heuristic, not a classifier).

### 3.3 LocalMemoryEngine

**One line.** The in-process keyword engine: token-overlap similarity plus scope-bounded graph walks.

**Plain language.** A card index in the archivist's own desk. Matching is by shared words, and following links never leaves your allowed drawers. Fine for dev and offline tests; its own docstring says it is not a production knowledge graph.

**Key files.** `boltrig/memory/local.py` (`LocalMemoryEngine`). Selected when the manifest `memory.engine` is unset or unrecognised.

**Governed by.** SEC-40 (scope-bounded), SEC-44 (forget removes the node, derived relationship nodes, and dangling edges).

**Maturity.** Deliberate dev scaffold, complete against the contract, in-memory only.

### 3.4 VectorMemoryEngine

**One line.** In-process vector recall: embeds facts and queries, ranks by cosine, graph mode seeds by similarity then walks in-scope edges.

**Key files.** `boltrig/memory/vector.py` (`VectorMemoryEngine`). Selected by `memory.engine: vector`.

**Governed by.** SEC-40 (multi-hop scope-bounded), MEM-VEC-01 (cosine ranking, and the in-process and pgvector engines agree).

**Maturity.** Wired and functional, in-memory only; semantic quality depends on the embedder (3.7): the default is hashing, not a model.

### 3.5 PgVectorMemoryEngine

**One line.** The durable production engine: the same vector semantics persisted in Postgres with the pgvector extension, isolation enforced in SQL.

**Plain language.** The same archive moved into a fireproof records hall. The clever part is structural: node reads are SQL-filtered to your scopes and an edge only loads if both of its endpoints are in scope, so a cross-drawer walk is impossible by construction, not by politeness. Similarity uses pgvector's native distance operator; forgetting resolves everything derived from the target and deletes it.

**Key files.** `boltrig/memory/pgvector.py` (`PgVectorMemoryEngine`, tables `memory_vectors` and `memory_vector_edges`, `vector(256)`). Selected by `memory.engine: pgvector`; DSN from config or `DATABASE_URL`.

**Governed by.** SEC-40, MEM-VEC-01, SEC-44 (pgvector forget is complete).

**Maturity.** Production-grade and durable, with the same embedder caveat as 3.4.

### 3.6 CogneeEngine

**One line.** The intended adopted graph engine; today a confirmed stub.

**Plain language.** A reserved parking space with the name painted on, no car in it. Selecting `engine: cognee` in the manifest boots, but every operation (`remember`, `recall`, `improve`, `forget`) raises `NotImplementedError` after checking the `cognee` package would even import, and `health()` returns the literal string `"down"`.

**Key files.** `boltrig/memory/cognee.py` (`CogneeEngine`, `_require_cognee`).

**Governed by.** Named in SEC-42's description ("never persisted into any engine (Cognee or native)") but not independently pinned.

**Maturity.** Scaffold/stub, verified: four `NotImplementedError` raises and a hardcoded down health.

### 3.7 Embeddings

**One line.** Two embedders behind one protocol: deterministic feature hashing by default, an OpenAI-compatible model embedder as the production seam.

**Plain language.** Two ways to give a note a "position" so similar notes sit near each other. The default is a mathematical trick (hash each word into a signed bucket, normalise): stable across processes, zero network, but lexical, so "car" and "automobile" do not land near each other. The real one calls a model's `/embeddings` endpoint (refusing redirects so an API key cannot be exfiltrated) and only activates when the manifest names both a base URL and a model.

**Key files.** `boltrig/memory/embeddings.py` (`HashingEmbedder`, `ModelEmbedder`, `build_embedder`, `cosine`, `DEFAULT_DIM = 256`).

**Governed by.** MEM-VEC-01 (cosine ranking behaviour).

**Maturity.** Hashing: production-grade code, non-semantic dev default. Model: wired-but-thin (selectable, but no default or test path uses it).

### 3.8 Cognify ingestion pipeline

**One line.** Turns transcripts and documents into scoped, provenance-tagged memory, screening each item and committing through the chokepoint.

**Plain language.** The scanning bench that feeds the archive: each chunk is screened (a run whose every item fails is marked rejected), then filed via the `memory.remember` verb through the kernel, so ingestion inherits every guard in 3.2. `cognify_conversation` bridges chat: it files a conversation's messages with provenance back to the thread. Honest scope note: this is chunk-and-screen only; there is no entity or relationship extraction in this codebase (that job was deferred to the Cognee adoption, 3.6).

**Key files.** `boltrig/memory/cognify.py` (`cognify`, `cognify_conversation`; `MemoryIngestion` lifecycle screening -> cognifying -> done/rejected).

**Public surface.** `POST /v1/memory/ingest`.

**Governed by.** Reinforces SEC-40 and SEC-42 at ingestion (no dedicated ingestion id).

**Maturity.** Wired and functional but thin on extraction.

### 3.9 Erasure ledger

**One line.** Every right-to-be-forgotten operation is recorded: who asked, what was targeted, engine-confirmed, with a fact count.

**Plain language.** The shredding log. When something is forgotten, the ledger records the request and confirms the engine really removed the node and everything derived from it; the audit row records the erasure without contents.

**Key files.** `boltrig/models/memory.py` (`MemoryErasure`); written by `MemoryAdapter._forget`.

**Public surface.** Produced by `POST /v1/memory/forget`.

**Governed by.** SEC-44 (complete, engine-confirmed, ledgered, audited).

**Maturity.** Production-grade for the local/vector/pgvector engines; unreachable under Cognee (whose `forget` raises first).

---

## Part 4: Workflows

### 4.1 Workflow interpreter

**One line.** Executes a stored workflow definition's steps in dependency order, each step a durable boundary through the kernel, skipping descendants of failures.

**Plain language.** A recipe robot that respects the recipe's arrows. It sorts steps so parents run first (a cyclic or orphaned step is reported unrunnable, never silently dropped), dispatches each step's `noun.verb` action through the full ten-step gate under the caller's own grants (a step can neither escalate nor bypass governance), pauses cleanly on a human gate, and if a step fails, everything downstream of it is skipped fail-closed. Each step emits a `workflow_step` event (running/ok/failed/skipped) on the run's stream so the step events, their tool events, and the audit all cohere on one run id.

**Key files.** `boltrig/workflows/interpreter.py` (`run_workflow_definition`, `_topological_order`).

**Public surface.** `POST /v1/workflows/{wf_id}/execute` (via `WorkflowLibrary.execute`).

**Governed by.** FR-CTL-02 (dependency order, per-step durable boundary, skip descendants), SEC-50 (no escalation past caller grants), FR-EVT-04 (per-step events).

**Maturity.** Production-grade; the primary real execution path for data-defined workflows.

### 4.2 Workflow library

**One line.** Storage and selection facade: register, get, intent-match, trigger (durable enqueue), execute.

**Plain language.** The recipe binder. Recipes are data rows (`source` precreated, generated, or learned); one precreated recipe ships (`libraries/workflows/onboard-employee.yaml`, a 4-step onboarding DAG). `match` picks the recipe whose intent tags best overlap a request. Honesty: `match` has no serving-path caller anywhere in the package; workflows run only when someone names them by id.

**Key files.** `boltrig/workflows/library.py` (`WorkflowLibrary`); constructed at boot with the store, the executor from `register_workers`, and the kernel.

**Public surface.** `GET /v1/workflows` and `/{wf_id}`, `POST /v1/workflows`, `POST /v1/workflows/{wf_id}/trigger`, `/execute`, `/schedule`, `GET /v1/workflows/{wf_id}/runs`.

**Governed by.** FR-WFS-04 (a registered workflow becomes a live durable run).

**Maturity.** Production-grade for register/get/trigger/execute; `match` is tested but unwired (scaffold in the serving sense).

### 4.3 Workflow generator and learning

**One line.** Deterministic and reasoned synthesis of new workflows, plus the (currently dormant) learning entrypoint.

**Plain language.** The recipe writer and the flywheel. `generate_workflow` writes the same fixed five-stage pipeline for any task (understand, plan, execute, verify, report), no model needed, same input same output. `generate_workflow_reasoned` asks a runtime to propose steps and compiles them, falling back to the deterministic pipeline on any failure. `learn_from_success` is the flywheel edge: re-save a succeeded generated workflow as `source='learned'` so matching finds it next time. Honesty, verified twice over: `learn_from_success` is never called anywhere in the repository (not in serving code, not even in tests; it is exported dead code), and neither synthesis function has a non-test caller. The output-becomes-input loop exists as functions with no wire. `schedule_spec` (cron plus IANA timezone validation) is the one wired piece.

**Key files.** `boltrig/workflows/generator.py` (`generate_workflow`, `generate_workflow_reasoned`, `learn_from_success`, `schedule_spec`).

**Public surface.** `POST /v1/workflows/{wf_id}/schedule` only.

**Governed by.** US-WFL-02 (reasoned when a runtime is present, deterministic fallback offline). The learning and scheduling story ids in docstrings (US-WFL-03/05) are not declared invariants.

**Maturity.** `schedule_spec` production-grade; synthesis wired-but-thin (no serving caller); `learn_from_success` scaffold/dead.

---

## Part 5: The store

### 5.1 Store protocol

**One line.** The single persistence seam: one Protocol of roughly 90 tenant-scoped methods that the kernel depends on instead of any database.

**Plain language.** The filing room's service window. The kernel never walks into the stacks itself; it asks at the window, and every request form has the tenant's name printed on it by construction. Two clerks can staff the window (memory or Postgres) and the kernel cannot tell the difference. The contract covers the registry, permissions, libraries (adapters, skills, capabilities, workflows, model endpoints), work items, HITL (including atomic single-use consume), the audit chain, budgets, idempotency, credential references, config revisions, evals, channels (with pairing lockout compare-and-swap), memory facts/ingestions/erasures, users/PATs/invitations/settings/sessions, and conversations.

**Key files.** `boltrig/store/base.py` (`Store` protocol), `boltrig/store/__init__.py` (lazy Postgres import).

**Governed by.** SEC-08 (tenant isolation by contract), plus everything the parity suite pins.

**Maturity.** Production-grade, and the widest interface in the codebase.

### 5.2 InMemoryStore

**One line.** The dict-backed reference implementation for dev, tests, and offline runs.

**Key files.** `boltrig/store/memory.py` (`InMemoryStore`), channel methods in `boltrig/store/channels.py`. Default when `DATABASE_URL` is unset. Carries the sync seed helpers `apply_manifest` uses.

**Governed by.** The same contract tests as Postgres where parametrised.

**Maturity.** Production-grade as a reference; not durable by definition.

### 5.3 PostgresStore

**One line.** The asyncpg-backed durable implementation of the same protocol, with optional DB-enforced row-level security.

**Plain language.** The fireproof filing room. Same window, same forms, but everything survives a power cut, and with RLS on, the shelves themselves refuse to hand a clerk another tenant's folder even if the clerk asks nicely: every statement runs with the tenant bound to a connection variable, and an unbound tenant sees zero rows (fail-closed).

**Key files.** `boltrig/store/postgres.py` (`PostgresStore`, `connect(dsn, apply_schema, rls)`, `_RlsPool` binding `app.tenant_id` before each statement).

**Governed by.** SEC-08, SEC-65 (FORCE RLS, WITH CHECK on writes, unset GUC yields zero rows, auth binds the tenant before the first read), NFR-REL-01 (a blocking HITL pause survives restart and resumes).

**Maturity.** Production-grade; its unique behaviours (RLS, durability) run only in CI or a real deployment (tests skip cleanly offline).

### 5.4 Schema, RLS overlay, and migrations

**One line.** One idempotent schema (about 40 tables), an opt-in least-privilege RLS overlay, and a linear Alembic chain for production changes.

**Detail.** `boltrig/store/schema.sql` is the first-boot loader (mounted into the Postgres container's init dir). `boltrig/store/rls.sql` creates a `boltrig_app` role (no superuser, no RLS bypass, DML only) and one `tenant_isolation` policy per scoped table; it deliberately excludes `personal_access_tokens` and `channels` because both must be resolved cross-tenant before a tenant is bound. Migrations: `migrations/versions/0001_baseline` through `0004_extension_contract`, run via `make migrate`. RLS activates with `BOLTRIG_RLS=1`.

**Governed by.** SEC-65, SEC-08.

**Maturity.** Production-grade schema; RLS is genuine defence in depth but explicitly opt-in.

### 5.5 Parity testing

**One line.** One contract suite runs against both store implementations so they cannot drift apart on the behaviours most prone to it.

**Plain language.** The same exam given to both clerks. Honest coverage note: the shared parametrised suite asserts 4 behaviours identical across both backends (idempotency, audit ordering, single-use HITL consume, fact ordering), chosen as the drift-prone ones; the other roughly 86 protocol methods are exercised against the in-memory store only, with a further 8-plus Postgres-gated tests (durability, RLS, manifest seeding) that skip silently without `BOLTRIG_TEST_DATABASE_URL`.

**Key files.** `tests/store/test_store_parity.py`, `tests/store/test_postgres_store.py`.

**Governed by.** SEC-14, SEC-15, SEC-16, SEC-33, SEC-08, NFR-REL-01.

**Maturity.** Wired-but-thin: real and running, but narrow relative to the protocol's width.

---

## Part 6: Adapters

### 6.1 Adapter contract, loader, and describe() registration

**One line.** One Protocol every integration implements; adapters self-describe their verbs as data and hot-load without a kernel restart.

**Plain language.** Every appliance plugs into the same socket. An adapter exposes `describe()` (its verbs with schemas, consequence, rate limits, degraded modes) and `execute()`; registering it upserts nouns, verbs, and bindings as data, so a new integration changes zero kernel code. The loader keys live instances by tenant and adapter id, hot-replaces them, and never crashes on a bad module (records it down instead). Credentials are typed so their material cannot appear in a repr or log line.

**Key files.** `boltrig/adapters/base.py` (`Adapter`, `VerbSpec`, `Credential`, `Result`, `ErrorClass`), `boltrig/adapters/loader.py` (`AdapterLoader`), `boltrig/kernel/registry.py` (registration).

**Governed by.** SEC-54 (foundation layers never depend upward), P1 (policy as data), FR-EXT-01 (a manifest-declared `module_ref` adapter loads at boot: extend from outside, no core edit).

**Maturity.** Production-grade.

### 6.2 The builtin adapter set

**One line.** The shipped integrations, from a fully offline reference to real HTTP/SQL connectors and honest seams.

| Adapter | File (under `boltrig/adapters/builtin/`) | What it is | Maturity |
| --- | --- | --- | --- |
| memory-tickets | `memory_tickets.py` | In-process ticketing, no creds or network; the air-gapped reference | production-grade |
| jira | `jira.py` | Jira Cloud REST v3 tickets (create/read/update/search/comment) | production-grade code, needs creds |
| ms-graph | `ms_graph.py` | Microsoft Graph: documents, email, calendar, chat, directory | production-grade code, needs creds |
| crm-sql | `crm_sql.py` | SQL CRM contacts, read-scoped by default | production-grade code, needs creds |
| web | `web_fetch.py` | `web.fetch`: governed internet access, SSRF-guarded, HITL-gated | production-grade |
| channel-send | `channel_send.py` | `channel.send`: governed outbound egress, high consequence | production-grade |
| mq/file seams | `mq_file.py` | Kafka/RabbitMQ/file-share ingest seams; degrade to unavailable | honest seams, not adapters |
| inbound webhook | `inbound_webhook.py` | HMAC verify + normalise helper for channel ingress | production-grade helper |

Also registered at boot but living elsewhere: the control-plane adapter (1.16), the skill shelf (2.14), the memory adapter (3.2), and consumed MCP servers (6.3).

**Governed by.** SEC-52/53 (web.fetch), SEC-39 (channel.send), SEC-61 (shared egress guard across all HTTP adapters).

### 6.3 MCP consumer adapter

**One line.** An external MCP server consumed as an adapter: its tools register as verbs, inert until a named human review activates them.

**Plain language.** Plugging in someone else's toolbox. The consumer connects, lists the foreign server's tools, and maps each to a verb, but the whole toolbox stays sealed (describes nothing, executes nothing) until a named reviewer activates it. Outbound calls run the shared egress guard and never follow redirects into internal space. Servers declared in the manifest's `mcp.consume` register inert at boot.

**Key files.** `boltrig/adapters/mcp_consumer.py` (`McpConsumerAdapter`, `review_and_activate`).

**Public surface.** `POST /v1/mcp/servers`; then normal verbs after review.

**Governed by.** FR-MCP-03 (tools register as verbs), SEC-22 (inert until reviewed), FR-EXT-02 (manifest-declared servers register inert), SEC-61.

**Maturity.** Wired-but-thin to solid: real JSON-RPC round trip and a genuine review gate.

### 6.4 Adapter generator

**One line.** Deterministic, offline, no-LLM transformation of an OpenAPI document into a working but inert HTTP adapter.

**Plain language.** A machine that reads an appliance's manual and builds the plug for it. From an OpenAPI spec (2.0 or 3.0, dict, URL, path, JSON or YAML) it derives verb ids, noun ids, merged input/output schemas, consequence (GET low, mutating high), rate limits from vendor extensions, and pagination, and can render human-reviewable Python source. Like every generated thing here, it refuses to execute until a named review activates it.

**Key files.** `boltrig/adapters/generator.py` (`generate_adapter_from_spec`, `GeneratedAdapter`, `render_source`).

**Public surface.** `POST /v1/adapters/generate`, `GET /v1/adapters/{id}/source`, `POST /v1/adapters/{id}/activate`, `GET /v1/adapters`.

**Governed by.** US-ADP-01 (verbs derived from OpenAPI), SEC-22 (inert until reviewed), FR-ADS-02 (binds only after a named review).

**Maturity.** Production-grade and notably complete (full ref resolution with cycle breaking, deterministic output).

---

## Part 7: Config

### 7.1 The manifest (policy as data)

**One line.** One typed, env-interpolated YAML document per tenant that seeds the whole engine: the literal mechanism behind "one image, many tenants".

**Plain language.** The building's rulebook, and the only thing that changes between customers. Sections: identity (IdP mappings to roles and scopes), models (endpoints, the default, the sensitive/local endpoint), hierarchy (tier 1 and tier 2 profiles with runtimes, depth, skills, budgets), ephemeral runtimes, spawn rules, adapters (with credential references), HITL policy (blocking verbs, escalation chain, timeouts), network (air gap, allow/block domains), privacy (redaction, residency, retention), plus runtimes/mcp/chat/evaluation/notifications/personal_agents/memory blocks. `${ENV}` and `${VAR:-default}` interpolate at load. `apply_manifest` seeds, in order: model endpoints, capabilities, budgets, the tenant permission ceiling, credential refs and adapter bindings, then imports and registers adapters (builtins or external `module_ref` modules).

**Key files.** `boltrig/config/manifest.py` (`load_manifest`, `apply_manifest`, the frozen `FleetManifest` tree); `manifest.yaml`, `manifest.example.yaml`.

**Governed by.** FR-EXT-01, K-2 (ceiling), FR-COST-02 (budgets), SEC-24 (gateway sandbox declared restrictive in the manifest).

**Maturity.** Production-grade parsing and seeding; policy-as-data is real.

### 7.2 The hierarchy and the "parsed but unwired" honesty

**One line.** The org-chart config is genuinely wired for capabilities and budgets; several other parsed policy fields have no consumer at enforcement time.

**Verified detail.** Tier profiles ARE consumed: they seed `AgentCapability` and `Budget` rows, and `cost_tier`/`max_depth` have many downstream consumers. But the following parse into the typed manifest and are then consulted by nothing outside the parser: `spawn_rules` (declared match-pattern to runtime/skills routing, zero consumers), `hitl.escalation_chain`, `privacy.data_residency`, `privacy.retention_days`, `privacy.redact_fields`, `locale_default`, `timezone_default`. And budget enforcement is confined to the spawn path (1.9). So the honest statement is: hierarchy wired, spawn rules and the privacy/escalation details parsed but unwired.

**Key files.** `boltrig/config/manifest.py`; enforcement sites (or their absence) across `boltrig/fleet/spawn.py` and `boltrig/kernel/`.

**Maturity.** Wired-but-thin as a whole, with the specific dead fields named above.

### 7.3 Env settings

**One line.** Process-level wiring (database, Redis, secret store, audit key, auth mode) read once at boot, deliberately separate from tenant policy.

**Plain language.** The difference between the building's plumbing and the tenant's rulebook. Settings cover `DATABASE_URL`, Redis, the secret store choice, the audit HMAC key, proxy/CA/air-gap, the OIDC trio, dev auth, and the Cloudflare Access group. Selection is fail-closed: with CF Access configured you get that resolver; with OIDC, that; dev header-trust only when explicitly enabled, and it refuses to start under any production signal, as does the default audit key.

**Key files.** `boltrig/config/settings.py` (`Settings`, `load_settings`), `boltrig/api/bootstrap.py` (`select_principal_resolver`).

**Governed by.** SEC-60 (dev auth impossible in production), SEC-01.

**Maturity.** Production-grade.

---

## Part 8: Platform

### 8.1 Bootstrap

**One line.** The single wiring point: choose the store, locate the manifest, construct the kernel, seed everything, attach the fleet.

**Plain language.** The building superintendent's opening routine. `build_store()` picks Postgres (with opt-in RLS) or memory. `build_kernel_async()` finds a manifest (`BOLTRIG_MANIFEST`, then `/app/manifest.yaml`, `manifest.yaml`, `manifest.example.yaml`), builds the `Kernel`, seeds from it, and registers the memory adapter, control plane, skill shelf, channel-send, web.fetch, consumed MCP servers, and the skills directory, then sets the spawner-backed agent invoker. No manifest at all boots a minimal demo tenant. The FastAPI lifespan builds the kernel on the serving event loop so pool resources bind correctly.

**Key files.** `boltrig/api/bootstrap.py`; `boltrig/kernel/app.py` (`create_app` lifespan).

**Governed by.** FR-EXT-01/02, SEC-01, SEC-58.

**Maturity.** Production-grade.

### 8.2 Entry points: API server and fleet worker

**One line.** Two processes: uvicorn serving the kernel app, and a fleet worker meant to run the permanent tier.

**Plain language and honesty.** The API entry (`uvicorn boltrig.api.asgi:app`) is real and full. The fleet worker (`python -m boltrig.api.worker`) builds a kernel and registers executors, but its docstring promises more than its body delivers: it says the Chief of Staff polls the work item store and routes pending items to department heads, while the actual loop is `while True: await asyncio.sleep(5)`, a keepalive. Consequence: work items created by channel intake (1.13) sit in the queue with nothing pumping them onward. This is the delegation pump gap in Part 10.

**Key files.** `boltrig/api/asgi.py`, `boltrig/api/worker.py`, `boltrig/api/cli.py`.

**Maturity.** API entry production-grade; fleet worker scaffold (a keepalive standing where the pump should be).

### 8.3 Docker-compose topology

**One line.** Ten services, two networks, hardened first-party containers, optional lanes profile-gated.

| Service | Image / build | Ports | Role |
| --- | --- | --- | --- |
| postgres | pgvector/pgvector:pg16 | internal only | durable state + pgvector; schema mounted into init |
| redis | redis:7 | internal only | rate-limit counters, ephemeral |
| kernel | deploy/kernel.Dockerfile | 8000 | the API, on `default` + `sandbox` networks |
| fleet-worker | deploy/fleet.Dockerfile | none | `python -m boltrig.api.worker` |
| hatchet-engine | hatchet-lite (optional) | 7077 grpc, 8888 api | durable execution backbone |
| hatchet-dashboard | hatchet-dashboard | 8889 | Hatchet UI |
| ui | ui/Dockerfile (nginx) | 8080 | the React console, proxying `/v1/` to the kernel |
| bifrost | maximhq/bifrost (profile `gateway`) | 8080 | the model gateway seam's target |
| local-model | vllm/vllm-openai (profile `local`) | 8001 | on-box inference for sensitive data |
| pi_sidecar | services/pi_sidecar/Dockerfile | expose 8090, `sandbox` network only | the sandboxed agent loop |

First-party containers run read-only rootfs, all capabilities dropped, no-new-privileges, resource caps, non-root. The secure overlay (`deploy/compose.secure.yml`) adds a Caddy edge and flips the `sandbox` network to internal, making the gateway's egress restriction a matter of infrastructure, not documentation.

**Governed by.** SEC-64 (containers hardened, enforced so it cannot silently regress), SEC-48 (gateway egress enforced in manifests), SEC-24, FR-GW-01.

**Maturity.** Production-grade topology; Hatchet, Bifrost, and local-model are explicitly optional external lanes.

### 8.4 The UI console

**One line.** A thin React 18 + TypeScript + Vite single-page app over the kernel API, with SSE streaming and React Flow canvases.

**Plain language.** The reception screens: routing, kanban, approvals, chat, memory, admin, evals, the studios, and registry/workflow canvases, all talking to the same `/v1/` API everyone else uses (nginx proxies it to the kernel in containers). A dev identity bar sets trust headers that only the dev resolver honours.

**Key files.** `ui/src/` (panels, `router.ts`, `api/client.ts`), `ui/nginx.conf`. The separate `site/` directory is the Next.js marketing site, unrelated to the console.

**Maturity.** Production-grade thin client by its own description.

### 8.5 Observability tree

**One line.** Reconstructs the full execution tree of a run (agents, children, workflows, per-node status and aggregated cost) from the audit log alone.

**Plain language.** Because every action wrote exactly one ledger line with its run and parent-run ids, you can rebuild the whole family tree of any run after the fact, even for a crashed one: who spawned whom, how deep, what each node did, and what it all cost, totalled up the tree.

**Key files.** `boltrig/observability/tree.py` (`build_tree`).

**Public surface.** `GET /v1/audit/tree/{run_id}`.

**Governed by.** Rides on SEC-16's guarantee that the audit log is complete.

**Maturity.** Production-grade.

---

## Part 9: How a single action flows

The whole engine in one trace. A user types "create a ticket for the login bug" into the console chat.

1. **Arrive.** The browser POSTs to `/v1/chat`. Middleware stamps security headers and checks Host and body size. The principal resolver verifies the bearer (OIDC) or the CF Access assertion and produces a Principal: tenant, subject, role, grants. Nothing about identity came from the request body.
2. **Thread.** `ChatService.handle_turn` checks the caller may use this conversation, persists the user message, mints a fresh `run_id`, and starts streaming SSE frames back, beginning with `message_start`.
3. **Become work.** The turn executor creates a governed `WorkItem` (source `chat`, id = run id, `on_behalf_of` the user) and an `InvocationContext` at tier 1. Continuity composes the conversation's own prior turns into the task, deterministically.
4. **Spawn.** `Spawner.spawn` runs its pipeline: resolve and merge skills (none on a plain chat turn), validate context, pick the cheapest capable capability, check recursion depth, reserve budget against the tenant and department cards, intersect the child's grants with the parent's ceiling, route the model through the sensitive-to-local guard and (if configured) the gateway, and write an `AGENT_SPAWN` audit row.
5. **Reason.** The selected runtime runs with the composed system prompt (governance floor first). If it is the Pi lane, the kernel mints a run-scoped MCP token and streams the job to the sandboxed gateway, which loops: model, tool calls, model.
6. **Chokepoint.** Every tool call the run makes (say `ticket.create`) comes back through `POST /v1/mcp` `tools/call` and runs the ten steps of `Dispatcher.invoke`: resolve the verb and binding, validate params, check grants, hit the HITL gate (if `ticket.create` were high consequence, a `PendingHuman` pauses here and an approval card streams inline into the chat), rate limit, idempotency replay, resolve the Jira credential inside the kernel, execute the adapter, validate output, record the idempotent result.
7. **Audit.** In the same logical step, win or lose, one audit row is written, hash-chained to the previous row, scrubbed of anything secret-shaped, attributing the adapter, the actor, the depth, the latency, and the status. Paired `tool_call`/`tool_result` events were emitted onto the run stream as a side channel that can never break the call.
8. **Return.** The runtime's result surfaces as the spawn summary; the executor publishes it as a `text_delta`; `message_end` closes the stream; the assistant message, with the full event list and any pending approval id, is persisted. `GET /v1/audit/tree/{run_id}` can now reconstruct everything that just happened, with costs totalled up the tree.

The same trace holds for every other front door. A webhook enters at `/v1/channels/{id}/inbound` (signature-verified, sender bound to an internal identity, normalised to a WorkItem) and a headless client enters via a PAT or MCP; all of them converge on steps 4 to 8 because there is no second path.

---

## Part 10: What changes next

The approved engine plan closes the gap between the governance shell (largely production-grade, as the catalogue above shows) and the intelligence inside it (largely thin or dormant). Four thrusts, each pointed at findings documented above:

**1. Degraded honesty.** Today a keyless or endpoint-less run returns an echo or a degraded summary that reads like an answer (2.4, 2.6): `AgentResult` marks degradation internally (`output["_degraded"]`) but the chat surface presents it as a normal reply. The plan makes degradation visible end to end: label degraded turns honestly in the stream and the UI, so "the engine could not reason" is never dressed as "the agent replied".

**2. Durable tasks re-entering the chokepoint.** Partially landed: `boltrig-workflow-run` now runs every step through `kernel.invoke` inside an `executor.run_step` boundary WITH checkpoint-resume and per-step idempotency keys (2.12), so a durably resumed run re-enters the chokepoint per step and never re-executes completed work. What remains: `HatchetExecutor.run_step` still awaits functions directly — the SDK exposes no durable child-step API — so per-step ENGINE durability (each step its own retriable Hatchet unit) is the open seam, closed either by an SDK upgrade or by registering one Hatchet task per step.

**3. The delegation pump.** Intake works (1.13, 2.13) and the org chart exists as code (2.1, 2.2), but the fleet worker's loop is a keepalive and neither ChiefOfStaff nor DepartmentHead is ever invoked in serving (8.2). The plan wires the pump: the worker polls pending work items, the ChiefOfStaff routes them, DepartmentHeads decompose and fan out under their caps, and the manifest's currently-dead `spawn_rules` (7.2) get their consumer.

**4. The learning loop.** The flywheel edge exists as dead code: `learn_from_success` is never called, `WorkflowLibrary.match` has no serving caller, and synthesis never runs on a miss (4.2, 4.3). The plan closes the loop: on intent, match a stored workflow; on a miss, synthesise one (reasoned when a runtime is present, deterministic otherwise, US-WFL-02); on success, re-save it as learned so the next match finds it. Output finally becomes input.

Everything in this plan lands inside the shell already built: no new path around the chokepoint, no new authority outside grants, every new wire audited like every old one.
