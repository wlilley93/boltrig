# Risk register

Every HIGH-severity finding the twenty area authors raised, put through three
independent panels briefed to REFUTE it. Each panel read a different lens: what
the code actually does, whether the path is reachable, and whether the statement
overclaims. Panels defaulted to refuted when uncertain. A finding is CONFIRMED
only when at least two of three panels could not break it.

    findings put to the panels      56
    CONFIRMED                       40
    REFUTED as stated               16
    split                           0
    panels returned                 24 of 24

Twenty-nine percent of the findings did not survive as written. That is the
point of the exercise, and it is why nothing in this corpus should be actioned
from an author's first pass alone. Read the REFUTED section too: almost every
refutation carries a narrower statement that IS true, and in two cases the
corrected version is worse than the original.

MEDIUM and LOW findings were not put to panels. They live in each area spec's
section 11 and carry exactly one author's reading.

---

## CONFIRMED

Survived three adversarial panels. Ordered by area.

### H02 (area 01, 2/3 stand)

On the no-manifest boot branch approval_timeout_seconds is never threaded, so
HITLManager.approval_timeout_seconds stays None, every gate-minted approval is
created with timeout_at None and NEVER expires; SEC-14's timeout half is
silently inert on that path.

Cited: `boltrig/api/bootstrap.py:455 "kernel = Kernel(store, counter=counter, event_relay=event_relay)"`

### H05 (area 02, 3/3 stand)

The production Host-validation guard compares the WHOLE allowlist to ["*"], so
BOLTRIG_ALLOWED_HOSTS="*,app.example.com" passes the fatal check while still
handing a wildcard entry to TrustedHostMiddleware.

Cited: `boltrig/kernel/web_security.py`

### H06 (area 03, 3/3 stand)

The durable Hatchet lane silently drops the claim-time lease token, so every
work item processed through the engine writes UNFENCED. run_once puts
lease_owner/lease_expires_at on the payload, but the registered task's
WorkItemInput does not carry those fields.

Cited: `boltrig/fleet/hatchet_tasks.py`

### H07 (area 03, 3/3 stand)

The test certifying that the lease token survives the durable boundary tests
json.loads(json.dumps(payload)) and calls that "exactly what Hatchet does". It
never constructs WorkItemInput, the object actually on the path, so the test
passes while the real path drops the field.

Cited: `tests (lease fencing test)`

### H09 (area 04, 3/3 stand)

Decision 0020's condition L3 is no longer satisfied: it requires the multi-
runtime ROUTING MECHANISM to stay live with at least one non-Codex governed
leaf re-wirable by configuration alone until production_ready is reached.

Cited: `docs/decisions/0020-retire-the-pi-lane.md`

### H12 (area 05, 3/3 stand)

The migration-parity test compares tables, columns, constraints, indexes and
sequences but never pg_policy or relrowsecurity, so the RLS divergence is
invisible to the exact gate written to catch bootstrap-versus-migration drift.

Cited: `tests migration parity`

### H13 (area 05, 3/3 stand)

Five revisions (0044, 0045, 0057, 0074, 0075) use unguarded DDL (bare CREATE
TABLE, bare CREATE INDEX, bare ADD COLUMN), so `alembic upgrade head` from
base against a schema.sql-bootstrapped database fails at 0044.

Cited: `migrations/versions/0044*, 0045*, 0057*, 0074*, 0075*`

### H15 (area 06, 3/3 stand)

docs/extension-contract.md documents the manifest mcp.consume entry as
`credential: ${LINEAR_MCP_TOKEN}`, but bind_mcp_credential raises
ControlConflict on that exact key and _register_consumed_mcp has no
try/except, so following the documented form crashes registration.

Cited: `docs/extension-contract.md and bind_mcp_credential`

### H16 (area 06, 3/3 stand)

local_whisper and pocket_voice pass an explicit
network_config={"allow_internal": True}, and an explicit constructor config
SUPERSEDES the process-wide manifest posture rather than merging, so an
operator's air_gapped or allow-list posture is silently overridden.

Cited: `boltrig/adapters/builtin local_whisper, pocket_voice`

### H17 (area 07, 3/3 stand)

A PAT can answer the approval gate it itself raised. approval_response_block
tries the sole-author relief BEFORE the credential-class check, so on a
single-author tenant credential_kind is never consulted, and
resolve_pat_principal stamps actor_tier=human.

Cited: `boltrig/kernel/hitl_response_auth.py:206 "if await _sole_active_author(store, tenant_id, subject):"`

### H19 (area 07, 3/3 stand)

POST /v1/me/tokens is reachable by a PAT principal, so a token can mint
further tokens with the same effective scope. There is no
is_interactive_credential check and no rate limit.

Cited: `boltrig/kernel/account_profile_routes.py POST /v1/me/tokens`

### H20 (area 07, 3/3 stand)

boltrig set-password rotates a credential without revoking any session. The
in-band change-password route and the reset CTE both revoke; the host-boundary
command does not, so an attacker's live session survives the very action taken
to evict them.

Cited: `boltrig/api/cli.py set-password`

### H21 (area 08, 3/3 stand)

PgVectorMemoryEngine's docstring claims recall is "backed by an ANN index at
scale" but no HNSW/IVFFlat index exists anywhere in the tree, and recall
SELECTs every in-scope row into Python before scoring.

Cited: `boltrig/memory/pgvector.py:137 "rows = await conn.fetch("`

### H22 (area 08, 3/3 stand)

Production Knowledge always embeds with the deterministic HashingEmbedder: the
embedder is a constructor-only seam with no manifest or env path, so the
README's "pgvector embeddings" are lexical feature hashes, not semantic
embeddings.

Cited: `boltrig/knowledge embedder seam`

### H23 (area 08, 3/3 stand)

The candidate-review path does not compensate a failed engine write, unlike
the propose path: the candidate is already active and the previous version
already superseded, so the ledger and the engine diverge.

Cited: `boltrig/knowledge candidate review path`

### H24 (area 08, 3/3 stand)

The shipped nightly workflow specifies adapter_kind: craft while the craft
gate is fail-closed, so following the runbook burns a full LoRA training pass
every night before the gate refuses.

Cited: `libraries/workflows nightly distillation`

### H26 (area 10, 2/3 stand)

Two production model-egress paths never reach the router: the Cognee knowledge
compiler and the realtime voice profile resolver both send tenant content to
an external provider without consulting data_class.

Cited: `cognee compiler and realtime voice profile resolver`

### H29 (area 11, 3/3 stand)

The dev_egress_loopback manifest key is unreachable: FleetManifest.extra is
built from a closed fourteen-name tuple that omits it, so
manifest.section("dev_egress_loopback") always returns {} and the court-
permitted egress path is dead.

Cited: `boltrig/config/manifest.py FleetManifest.extra tuple`

### H30 (area 11, 2/3 stand)

The API serving process reads the manifest file THREE times, not once as
CODEX-COMPOSITION-1 states: the composition snapshot, a second typed read in
chat_factory at lifespan inside a bare except: pass, and a third elsewhere.

Cited: `boltrig/api composition and chat_factory`

### H31 (area 11, 3/3 stand)

The shipped example manifest declares hitl.approval_timeout_seconds: 3600, one
twenty-fourth of the code floor of 86400, and the code's own comment records
that the one-hour window was the proximate cause of an incident.

Cited: `manifest.example.yaml hitl.approval_timeout_seconds`

### H32 (area 11, 3/3 stand)

genesis.sh mints POSTGRES_PASSWORD, BOLTRIG_AUDIT_HMAC_KEY and the device
lease seed, but never BOLTRIG_SEAL_KEY, and sets no production signal. Every
credential_refs row on a genesis-provisioned box is therefore sealed with a
fallback.

Cited: `genesis.sh`

### H33 (area 12, 3/3 stand)

/v1/audit/verify reports anchor_intact true, and folds it into the combined
intact verdict, on a tenant that has never been anchored at all: verify_latest
returns (True, None) when no anchor row exists.

Cited: `audit verify_latest`

### H34 (area 13, 3/3 stand)

boltrig audit-verify exists and is tested but is scheduled by nothing: no
compose service, healthcheck, Makefile target, deploy unit or genesis phase
invokes it, so the tamper-evidence chain is re-derived only when an operator
remembers.

Cited: `boltrig/api/audit_verify.py and the deploy layer`

### H36 (area 13, 3/3 stand)

boltrig initiate, set-password and mint-token are bound to NO invariant id.
These are the host-boundary commands that can act as somebody else, and the D6
attribution rule they exist to satisfy has tests but no binding.

Cited: `tests/invariants.yaml and boltrig/api/cli.py`

### H37 (area 14, 3/3 stand)

The desktop-hands registry is kernel-global with no tenant partition, so on a
multi-tenant deployment with the add-on enabled any authenticated principal
polling the pull surface claims window and app-launch commands queued for
another tenant.

Cited: `desktop hands registry`

### H38 (area 14, 3/3 stand)

No invariant in tests/invariants.yaml binds the camera lease plane or the
sensing consent surface, although the camera plane is the exact shape SEC-
WRK-07 binds for device leases and sensing is a consent gate.

Cited: `tests/invariants.yaml camera and sensing`

### H39 (area 15, 3/3 stand)

The automations route mounts RoutinesView; AutomationView.tsx, at 2870 lines
the largest Worker module and the only home of workflow DAG, trigger,
schedule-occurrence and delivery-receipt authoring, has no importer in src.

Cited: `apps/worker/src AutomationView.tsx`

### H42 (area 15, 3/3 stand)

docs/WORKER-PARITY.md claims the Task chat lifecycle includes rename and
regenerate, but renameConversation and regenerateMessage are called only from
ConversationControls.tsx, which nothing in src imports.

Cited: `docs/WORKER-PARITY.md and ConversationControls.tsx`

### H43 (area 16, 3/3 stand)

Both SDK packages ship complete test suites (38 node:test cases in sdks/node,
78 in sdks/web) that no Makefile target and no CI workflow ever runs; the only
mention of sdks in either is an existence check on one lockfile.

Cited: `Makefile, .github/workflows, sdks/`

### H44 (area 16, 3/3 stand)

The marketing site ships an authenticated operations console at /console that
accepts a pasted bearer and posts it cross-origin to an operator-supplied API
base, on a statically exported site with no in-repo CSP.

Cited: `site/ console route`

### H45 (area 17, 3/3 stand)

The WhatsApp adapter's POST /inbound listener has no authentication, and
compose points the bridge at it across the shared sandbox network, so any
container on that network can forge an inbound WhatsApp message naming any
sender.

Cited: `services/channel_gateway whatsapp adapter POST /inbound`

### H46 (area 17, 3/3 stand)

The generic (custom-surface) adapter's JSON-lines TCP seam has no
authentication of its own, and the sender field it accepts selects which
Principal the message acts as. Anything able to open the listener can
impersonate any paired member.

Cited: `services/channel_gateway generic adapter TCP seam`

### H47 (area 17, 3/3 stand)

The vendored WhatsApp bridge gates POST /send on a Host header, which is a
DNS-rebinding defence and not authentication, so any container on the sandbox
network can send arbitrary WhatsApp messages as the linked account.

Cited: `deploy whatsapp bridge POST /send`

### H48 (area 17, 3/3 stand)

The Worker nginx edge proxies the ENTIRE gateway under /voice/, not just the
media WebSocket, so /voice/status returns the tenant's channel ids, live
adapter set and per-channel observations to any unauthenticated caller.

Cited: `apps/worker nginx config /voice/`

### H50 (area 18, 3/3 stand)

The per-phone token is minted unscoped, so it carries the owner's entire grant
allow set for 90 days on a device, where the app calls at most about thirty
routes: the client sends only {name, ttl_days}.

Cited: `ios token mint call`

### H51 (area 18, 3/3 stand)

Sign-out is fail-open: the revoke call is try? and the Keychain is cleared
regardless, so a failed revocation leaves a live token the phone has forgotten
and the person gets no signal. Only the success path is tested.

Cited: `ios sign-out path`

### H52 (area 19, 3/3 stand)

The container-hardening deploy-lint asserts the six anchor properties on only
kernel and fleet-worker, so browser-executor, hatchet-worker, channel-gateway
and whatsapp-bridge could each silently drop read_only, cap_drop or
pids_limit.

Cited: `deploy lint container hardening`

### H53 (area 20, 3/3 stand)

The whole pre-push gate layer is opt-in and unarmed: core.hooksPath is unset
in the pinned checkout and nothing in the repo sets it, while the Makefile
tells the reader 'or just push - the pre-push hook runs it'.

Cited: `.githooks/pre-push:81 and Makefile:223`

### H55 (area 20, 3/3 stand)

The invariant catalogue may under-declare its own bindings without failing:
drift is checked catalogue-to-marker only, and 361 of the 1836 real marker-
backed pairs are absent from the catalogue while the gate reports debt 0.

Cited: `scripts/check_invariants.py and tests/invariants.yaml`

### H56 (area 20, 2/3 stand)

The founding ruling that makes the whole governance layer binding, and that is
cited as the canonical source of every K-* id, has never existed as a file in
this repository's history and is allow-listed rather than reconstructed.

Cited: `docs/decisions/0002-nankle-consolidation-ruling.md and the citation allow-list`

---

## REFUTED AS STATED

These did NOT survive. The claim as written is wrong, overstated, or rests on
an unreproduced count. Where a panel could state the narrower true version it
is given, and THAT is what should be believed.

### H01 (area 01, 3/3 refute)

**Claim as written, refuted:**

The rate-limit counter key is built from the caller's SPELLING while the limit
comes from the source operation's binding, so the same binding addressed as
its capability name and as its source-operation id gets two independent
buckets and a caller holding both grants takes double the configured
throughput on one destination.

**What is actually true:**

Only when a binding sets `rate_limit.scope == "verb"` (the non-default; in
this tree just boltrig/knowledge/adapter.py:221) does the counter key carry
the caller's spelling while the limit comes from the source operation's
binding, giving a capability-addressed call and a source-operation-addressed
call two independent buckets on one destination (a version-pinned spelling
would be a third). Under the default `scope == "tenant"`
(boltrig/models/registry.py:91, used by every other shipped binding) the key
is the bare tenant id and both spellings share one bucket, so no throughput
doubling occurs.

### H03 (area 02, 3/3 refute)

**Claim as written, refuted:**

68 of the 161 state-changing routes never reach kernel.invoke or
dispatch_control_route, against a doctrine that names one chokepoint and
forbids side doors; ten whole modules (calls, devices, camera, channel
gateway, channel inbound) contain zero dispatcher calls and write to the store
by name.

**What is actually true:**

A large share of the kernel's state-changing HTTP routes do not call
kernel.invoke or dispatch_control_route, and ten modules (call_routes,
call_gateway_routes, camera_agent_routes, device_agent_routes, device_routes,
channel_inventory_routes, channel_gateway_outbox/reconcile/session_routes,
channel_inbound_routes) contain zero dispatcher calls and write through named
store methods. That is a governance-surface observation, not a demonstrated
doctrine breach: AGENTS.md scopes the chokepoint to external actions and to
capabilities reaching the network/DB/credential, these are first-party
platform routes carrying principal auth, ownership/RBAC checks, intake rate
limits and audit rows, decision 0003 rules the channel intake path terminates
at the seam via the queued work item, and the external egress they front
(channel.send, device.*, camera.*) does dispatch. The 68-of-161 count is an
unreproduced AST census, not a verified fact.

### H04 (area 02, 3/3 refute)

**Claim as written, refuted:**

POST /v1/ai-keys/activate reads raw key material out of the store on an HTTP
route and provisions the external Bifrost gateway with no dispatch, no HITL
gate, no rate limit and no audit row, against the rule that credentials are
resolved inside the kernel.

**What is actually true:**

POST /v1/ai-keys/activate (boltrig/kernel/ai_key_routes.py:320, NOT
ai_key_proposal_routes.py) re-provisions an already-approved, already-stored
AI key into the external Bifrost gateway with no dispatch, no fresh HITL
approval, no rate limit and no audit row, gated only by the same
`_authorize_ai_key` RBAC check as the set route. It cannot introduce new key
material, and the material is loaded kernel-side through the sealed
credential_refs seam, so this is a missing-audit / missing-re-approval gap on
a reconcile path, not a breach of "credentials are resolved inside the
kernel". The other caller of the same helper, `_finalize_approved`, is fully
governed: it dispatches control.ai_key.set with the approval id and writes an
audit row.

### H08 (area 03, 3/3 refute)

**Claim as written, refuted:**

Recursion depth is not enforced on the pump lane or the chat lane at all: both
build InvocationContext without a depth argument, so it defaults to 0 and a
delegated child is always depth 1 against a max_depth of 2 or more.

**What is actually true:**

Depth is enforced, at the spawn chokepoint:
boltrig/fleet/spawn_policy.py:120-127 raises DepthExceeded when parent depth +
1 exceeds the capability/spawn-rule max_depth, and
boltrig/fleet/spawn_policy.py:166 stamps the child's depth so nested spawns
consume the budget. The accurate, narrower point is about propagation rather
than enforcement: boltrig/fleet/authority.py:74 does not carry
`WorkItem.depth` into the InvocationContext, so every pump-executed work item
re-roots the spawn depth budget at 0, and a chain of follow-on work items
therefore never exhausts max_depth. Separately,
boltrig/fleet/work_follow_ons.py:47 writes children through
`store.create_work_item`, which does not apply the MAX_GOVERNED_WORK_DEPTH=32
cap that `governed_create_work` (boltrig/store/work_mutations.py:94,161)
applies.

### H10 (area 04, 2/3 refute)

**Claim as written, refuted:**

G3 is open and mitigated only by refusing a second concurrent cell:
config.toml carries auth.command and lives in a CODEX_HOME the cell uid owns,
so under the shared-uid posture a sibling can rewrite it.

**What is actually true:**

G3 is recorded open only under the shared-uid posture, which the trusted Codex
lane can only enter with BOLTRIG_CODEX_TRUSTED=1 (default off), no production
signal, and production_ready False. It is mitigated by more than the
concurrency refusal: alongside refusing a second live cell while
config_toml_protected is False, auth.command and auth.args are pinned on argv
(VJS-CC-VJS 6 H5), a surface a sibling cannot rewrite. Under per-cell uids
config_toml_protected is True, the sibling is refused by the kernel, and the
concurrency refusal lifts.

### H11 (area 05, 3/3 refute)

**Claim as written, refuted:**

Fourteen migrations enable FORCE ROW LEVEL SECURITY and create
tenant_isolation policies unconditionally, so every Alembic-migrated database
is fenced on about 19 tables whether or not the operator opted into RLS,
diverging from a schema.sql bootstrap.

**What is actually true:**

Thirteen migrations (0041, 0042, 0043, 0044, 0045, 0056, 0058, 0059, 0061,
0062, 0063, 0068, 0074) enable and FORCE row level security and create
tenant_isolation policies unconditionally, fencing 19 tables on every Alembic-
migrated database whether or not the operator opted into RLS - diverging from
the schema.sql bootstrap, whose overlay boltrig/store/rls.sql:4 declares opt-
in and which boltrig/store/postgres.py:207 does not run by default. The
fourteenth file that mentions FORCE RLS, 0022_schema_parity.py:187-198, is not
part of this: it applies RLS to its five tables only when
`nouns.relrowsecurity` is already true, which is the opt-in-respecting pattern
the other thirteen omit.

### H14 (area 06, 2/3 refute)

**Claim as written, refuted:**

HttpAdapter.health() builds a plain unguarded, unpinned httpx client against
base_url and the loader calls it on a 30 second background cadence, so a
generated adapter whose OpenAPI servers[0].url points at internal space gets a
recurring unauthenticated internal GET.

**What is actually true:**

HttpAdapter.health() does build an unguarded, unpinned, unauthenticated httpx
client against base_url, and GeneratedAdapter neither overrides it nor puts it
behind the SEC-22 review gate, so an inert generated adapter whose OpenAPI
servers[0].url points at internal space is probed with a plain GET. But the
probe is demand-driven, not a background cadence: it fires only when a caller
reaches AdapterLoader.health_snapshot() (GET /healthz, or the integrations
page) or the explicit control-plane refresh routes, throttled to at most one
probe per 30 seconds. Nothing in the shipped stack polls /healthz on a timer
since the compose healthcheck moved to /readyz on 2026-07-26, and /readyz
never touches the loader's adapter health.

### H18 (area 07, 3/3 refute)

**Claim as written, refuted:**

Two independence rules exist for one concept and only the unreachable one is
strict. DeviceLeaseIssuer.materialize refuses outright when the respondent is
in the requester set, with no relief arm at all, proving the stricter rule was
reachable and was not applied to HITL.

**What is actually true:**

DeviceLeaseIssuer.materialize (boltrig/device_leases.py:114-136) applies an
unconditional respondent-independence check with no sole-author and no
development-posture relief, while the HITL approval gate one layer up
(hitl_response_auth.approval_response_block) carries both. The consequence is
a layer inconsistency in the other direction from the one claimed: on a
single-author tenant the HITL approval can be self-answered under the
sole_author relief but the device lease can then never be issued, so device-
action verbs deadlock there. The device-lease rule is reachable production
code (registered by api/device_bootstrap.py whenever a lease-signing key is
configured), not an unreachable one.

### H25 (area 09, 3/3 refute)

**Claim as written, refuted:**

The only status-transition guard for work items, and the only caller of the
status compare-and-swap, live in WorkItemStore.transition which nothing calls;
the pump and five other fleet modules write status with a plain update.

**What is actually true:**

WorkItemStore is never instantiated, so its _TRANSITIONS guard and its call to
transition_work_item_status (the CAS's only caller) are dead code. The
executor path writes status with a plain update_work_item and no legality
check - the pump plus chat_turn_execution and department_head. Two other
enforcement points do exist and are live: the governed control.work.status
path validates against its own MANUAL_STATUS_TRANSITIONS matrix under a row
lock (boltrig/store/work_mutations.py), and hitl_expiry settles items through
the payload-carrying status CAS transition_work_item_settled.

### H27 (area 10, 3/3 refute)

**Claim as written, refuted:**

Post-run cost is priced from capability.model_endpoint's model rather than the
model that actually served, so every automatic-Codex and scoped-AI run misses
its configured per-model rate and falls back to the cost default.

**What is actually true:**

Post-run cost derives its price key from capability.model_endpoint's stored
model rather than the model that actually served, even though the served model
is available as model_route['model'] at the same call site. Whenever the two
differ - automatic Codex composing codex_config['model_id'] over a
differently-named endpoint, or the scoped-AI lane's binding.model_id - the run
is priced on the wrong key: either another model's configured rate, or, when
the capability declares no endpoint or an unpriced one, the cost-tier default
the manifest warns systematically over-bills.

### H28 (area 10, 3/3 refute)

**Claim as written, refuted:**

The SEC-43 sensitive-memory guard is a name-set membership test that its own
constructor satisfies by default (local_endpoints defaults to
{sensitive_endpoint}, and build_memory_adapter always includes the embedding
endpoint).

**What is actually true:**

The SEC-43 runtime residency check is a name-set membership test
(adapter_writes.py:73) that never verifies the endpoint's real data_class or
locality, and it is inert under the default construction (adapter.py:73,
local_endpoints defaults to {sensitive_endpoint}) and whenever a manifest
omits local_endpoints (adapter.py:302's fallback list contains the embedding
endpoint by construction). It is not unconditionally vacuous: an explicit
manifest local_endpoints list that excludes the configured embedding_endpoint
does trip it. Binding those names to genuinely sensitive endpoints is done
only by the pre-deploy doctor check _check_memory_posture
(api/doctor.py:477-492), not at runtime.

### H35 (area 13, 2/3 refute)

**Claim as written, refuted:**

The audit-key boot guard fails OPEN when nothing sets a production signal, and
the shipped compose sets none, so a deployment following the documented `cp
.env.example .env` warns once per boot and then runs a hash chain with a
development key.

**What is actually true:**

The audit-key boot guard warns rather than aborts when nothing sets a
production signal, and the shipped compose sets none (docker-
compose.yml:605-606 emit empty BOLTRIG_ENV/BOLTRIG_PRODUCTION). A deployment
that follows README.md:130 (`cp .env.example .env` then `make up`), without
editing secrets and without running genesis.sh, gets BOLTRIG_AUDIT_HMAC_KEY as
the EMPTY STRING - .env.example:51 ships it deliberately blank - so the audit
chain is keyed with empty bytes, not with the in-source `dev-insecure-audit-
key` (audit.py:28 only falls back to that when the variable is absent). The
warning fires at least twice per API boot, from bootstrap.py:419 and
bootstrap.py:510. The other documented path, genesis.sh, mints a strong key at
genesis.sh:104 and is not affected.

### H40 (area 15, 2/3 refute)

**Claim as written, refuted:**

The account route renders SettingsView section=you; AccountView.tsx and with
it AI-key management, developer tokens, sessions, two-factor management,
notification routing, the personal agent and activity/export are unreachable.

**What is actually true:**

The account route renders SettingsView section="you", and AccountView.tsx has
no importer in src, so its panes cannot be opened: AI-key management,
developer tokens, sessions, the voluntary two-factor management pane
(including disable), notification-route EDITING, the personal agent and
activity/export. Two qualifiers: two-factor ENROLMENT is still reachable ,
AuthGate.tsx:147 renders auth/AccountRequirementScreens.tsx's
EnrollmentRequiredScreen, which calls
twoFactorEnrollBegin/twoFactorVerifyEnroll, when the org requires 2FA ,  and
the mounted You pane does read and display notification routes via
client.meNotifications with every control disabled, so routing is visible but
not changeable.

### H41 (area 15, 3/3 refute)

**Claim as written, refuted:**

Thirty-nine SDK methods have no call site in any component a route mounts, and
58 of the 252 WORKER_ROUTES declarations name one of eleven unmounted files.
The parity ledger cannot see this because its only check is that the file
exists.

**What is actually true:**

39 SDK methods have call sites only in Worker files that no mounted route
reaches, and 58 of the 252 WORKER_ROUTES declarations name one of TEN such
files (not eleven), 21 of them AutomationView.tsx. The parity ledger cannot
see this not because its only check is file existence ,
tests/security/test_worker_route_ledger.py also asserts the named source
actually contains `client.<sdk_method>`, and a companion test asserts every
SDK method is called somewhere in apps/worker/src ,  but because no check asks
whether the file that carries the call site is reachable from a route the
shell mounts.

### H49 (area 18, 3/3 refute)

**Claim as written, refuted:**

Nothing automated verifies the iOS area at all: no CI workflow, no Makefile
target and no invariant reaches the Swift tree, so the only gate is a person
running xcodebuild test on the one Mac.

**What is actually true:**

No automated gate compiles, tests or lints the Swift tree: no CI workflow or
Makefile target invokes xcodebuild, and the 94 XCTest cases plus the
ios/scripts/sync-provider-catalogue.sh drift pin (enforced only inside
ios/BoltrigTests/OnboardingTests.swift) run solely when a person runs
xcodebuild test on the one Mac. The iOS directory is not entirely unverified,
though: `make familiar-island-check`, which runs in CI inside the worker-build
job via `make worker-quality`, rebuilds the Familiar island page and byte-
compares it against the committed copy in
ios/Boltrig/Resources/FamiliarIsland/, failing the build if that bundled
resource is stale.

### H54 (area 20, 3/3 refute)

**Claim as written, refuted:**

Two gates state in their own docstrings that they are wired into a target CI
runs; neither is a prerequisite of quality or python-quality and no workflow
run line names either, so they execute only in the unarmed hook.

**What is actually true:**

One gate overclaims and both are unrun:
scripts/check_continuity_projection.py:30 states it is "Wired into `make
check`, whose target list is the one CI runs", which is false ,  Makefile:223
says `check` is NOT what CI enforces. scripts/check_codex_pin_health.py:45
claims only "Wired into `make check`", which is accurate and asserts nothing
about CI. Neither target is a prerequisite of `quality` (Makefile:389) or
`python-quality` (Makefile:228) and no workflow run line names either, so both
execute only at .githooks/pre-push:159-160, in the unarmed hook.

