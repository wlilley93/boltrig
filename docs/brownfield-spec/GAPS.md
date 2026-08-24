# Gaps: where a silence in this corpus is not an absence in the system

Read this before treating anything here as complete. Two kinds of gap are
recorded: what the corpus could not settle, and what it never looked at.

## What was never looked at

Stated in `REFERENT.md` and repeated here because it is the most common way a
specification misleads:

- No deployed environment. The canary, CV and dev stacks were not queried. Every
  statement about runtime behaviour is derived from code and configuration.
- No test execution. A test named in this corpus exists and declares an
  invariant binding. It was not observed to pass.
- No container was started, no migration was run, no build was performed.
- Eleven sibling worktrees on eleven in-flight branches. Work that is real but
  unmerged is invisible here, including anything in the ten open pull requests.
- Third-party upstreams (Hatchet, Bifrost, Codex, signal-cli, the WhatsApp
  bridge, Cognee, Postgres) are described only at their seam and were not pinned.
- `apps/worker/` is 100,000 lines and was sampled, not read exhaustively. Its
  spec states its own bound at the top.

## What the authors could not settle

Each of these is a question the pinned tree cannot answer. Most need a decision
record, an operator, or a repository outside the referent.

### Area 01 The kernel dispatch chokepoint

1. Which of the three documented dispatch orders is INTENDED to be canonical:
   AGENTS.md's, dispatch.py's docstring, or docs/ARCHITECTURE.md's? Only a
   decision record naming one and amending the other two settles it; I can
   prove only what the code does.
2. Does anything outside the pinned tree consume the routing attribution keys
   in meta (capability, capability_binding_id, connection, source_operation,
   route_selected_by)? Settled by grepping the consuming repositories, which
   are outside this referent.
3. Is the tenant-scoped rate-limit bucket collapse intended? RateLimit.scope
   documents 'tenant' | 'verb' without saying 'tenant' means one bucket for
   ALL verbs, and no test asserts either behaviour (bounded: rg -n
   'scope="tenant"' tests/ finds fixtures using it, none asserting cross-verb
   sharing).
4. Is the full_access approval posture reachable in any shipped tenant, and by
   what UI? SEC-197 requires an interactive self-session with an exact
   confirmation token; whether any production manifest ships that route
   enabled is an ops question this tree cannot answer.
5. What retention applies to audit_log, security_log, idempotency_keys and
   run_effects in production? No DDL or janitor in this tree bounds their
   growth (bounded: only the audit-outbox drain is wired in
   boltrig/api/worker.py).
6. Does identity_mode: 'delegated' do anything anywhere? It is declared on
   Verb, stored in the verbs table, and dispatch never reads it (bounded: rg
   -n 'identity_mode' boltrig/ shows the model, the DDL and the registry write
   only).
7. Is boltrig/fleet/browser_executor.py's POST /v1/execute reachable from
   outside its own host network in any shipped deployment? It calls an adapter
   directly with a None credential, with no grant check, HITL gate, rate limit
   or audit row, guarded only by a fixed header value. Settled by the compose
   and Caddy configuration, which belongs to the deployment area.

### Area 02 The kernel HTTP surface

8. Does Starlette 1.6.0's TrustedHostMiddleware treat an allowlist CONTAINING
   '*' as allow-any? The guard in this tree only rejects the exact list ['*']
   and starlette is not vendored, so the consequence cannot be settled from
   the pinned tree. Settled by reading starlette/middleware/trustedhost.py at
   1.6.0.
9. Is the off-dispatch call/device/camera/channel-gateway family a deliberate
   carve-out or drift? No decision record authorising direct store writes was
   located. Settled by reading decision 0016 (desktop hands) and decision 0003
   (channels) end to end.
10. Does any deployed reverse proxy actually set X-Forwarded-Prefix, and is
   BOLTRIG_TRUST_FORWARDED_PREFIX set on any live stack? Not a tree fact;
   settled by reading the live Caddy and compose config for a tenant box.
11. Are the SSE routes ever measured through the full middleware stack? No
   test names both an SSE route and install_security (bounded: rg -ln
   'web_security|install_security' tests/ returned 5 files, none an SSE test).
   Settled by an integration test that streams /v1/runs/{id}/events through
   install_security.
12. What is the real _dev_principal blast radius on the beelink and canary
   stacks? The dev resolver defaults role to org-admin and grants to ['*'];
   whether any live stack sets BOLTRIG_DEV_AUTH=1 without a production signal
   is a deployment fact.
13. Does k.mcp.handle_user bucket rate limits the same way as the run-token
   path? Both call _dispatch with a RunToken, but the synthesised
   lease_id='user-request' token's bucketing was not read in prose. Settled by
   reading MCPServer._dispatch in full.
14. For the 133 GET routes, is department and workspace scoping pushed INTO
   the store query in every case, or does any handler load then filter? SEC-69
   proves it for the observability and work reads; the rest were checked only
   at the AST level.

### Area 03 The permanent fleet: hierarchy, spawn, budget

15. Does the Hatchet SDK strip unknown payload keys before or after
   input_validator parsing? model_dump() makes it moot for current code, but
   it decides whether the lease-token fix is a contract change or a body
   change. Settled by reading hatchet_sdk 1.33.x, which is not vendored in the
   pinned tree.
16. Is any deployment running with BOLTRIG_REQUIRE_DURABLE set? The repo ships
   no default and compose does not name it in the fleet-worker environment
   block, so production may be running the declared NON-durable fallback.
   Settled by reading a live .env, out of the pinned tree.
17. A tree parked with reason spawn_budget_exhausted has no recovery path
   short of manual database surgery. The park is proven reachable; what is
   unsettled is whether the intended operator answer is a counter reset, a new
   tree, or accepting the park. Settled by a decision record or a reset
   surface, neither found.
18. What is the intended relationship between WorkItem.depth and
   AgentCapability.max_depth? They are two counters with the same name and
   neither is ever compared to the other. Settled by a decision record; none
   found (bounded: rg -n "max_depth" docs/decisions/, zero hits).
19. Does acquire_agent_turn guarantee fairness across waiters, or can a
   BACKGROUND work-item turn starve indefinitely behind repeated FOREGROUND
   chat turns? The lane enum distinguishes them but the ordering policy lives
   in the store implementations, which this reading did not cover
   exhaustively.
20. Is there any operator surface to reset a tree's fanout counter? rg -n
   "fanout" boltrig/config/ boltrig/kernel/ returns five hits, all the
   unrelated HITL approval fanout, and the store exposes only
   try_increment_fanout.
21. Should the README's tier1-over-tier2 description be corrected, or is it
   deliberately aspirational? The programme decision doc, the FLT-PEER-01
   invariant and build_org all say flat; the README, docs/ARCHITECTURE.md and
   docs/architecture/engine-components.md all still say hierarchical.
22. SEC-165 (routing fails closed) and US-FLT-06 (an item completes through
   the org) are bound only by tests that construct the legacy
   ChiefOfStaff/DepartmentHead topology that build_org never composes. Is the
   flat lane's unroutable_agent park intended to be covered, or is the legacy
   binding considered sufficient?

### Area 04 The runtime protocol and the Codex lane

23. Under what authority was the multi-runtime routing seam removed? Decision
   0020 L3 forbids emptying the roster while production_ready is False, and it
   is still False; nothing in docs/decisions/ records a superseding order
   (bounded: rg -ni "_LEGACY_RUNTIME_KINDS|ENABLE_LEGACY_RUNTIMES" docs/).
   Settled by producing the ruling that discharged L3, or by re-instating the
   seam.
24. Is EngineRoute.CODEX_APP_SERVER reachable at all? The only rollout policy
   constructed anywhere in boltrig/ is generation 1 mode OFF, and the shadow
   caller hard-codes CodexCompatibility.INELIGIBLE. Settled by identifying the
   intended generation source, which the module itself defers to a later PR.
25. Does the Codex lane ever run under trusted posture (b) in a shipped
   deployment? I did not read cell_spawner.py, cell_slots.py or
   scripts/kernel-entrypoint.py, so I cannot say from opened code whether the
   privileged entrypoint actually hands the dropped API a spawner socket in
   docker-compose.yml. Settled by reading kernel-entrypoint.py against the
   kernel service.
26. What is the intended relationship between CODEX_SKILL_POLICY_VERSION and
   the binary pin? Both are "0.144.3" and both are checked only against their
   own literal. Settled by an author statement or a gate that compares them.
27. Is the output_schema path on turn/start used on the live path?
   CodexRuntime._run_phase never sets one, yet codex_phase_result_schema.py
   builds a strict phase-result schema. Settled by enumerating callers of
   phase_result_output_schema (I did not read codex_phase_result_parser.py).
28. Does anything consume AgentResult.new_work_items from the Codex lane? The
   field exists with US-EXE-04 caps documented, but CodexRuntime never
   populates it. Settled by a search over the department-head and pump areas
   that own the field.
29. Is the per-cell proxy's stream_idle_timeout_ms of 300000 deliberately
   equal to the upstream client's 300s read timeout, so both can expire
   together, or a coincidence? Settled by an author statement.
30. What happens to an in-flight cell when close_thread reports
   cleanup_failed? CodexRuntime suppresses the exception so the caller sees a
   normal result, while CodexAgentRuntime considered the cleanup failed.
   Settled by reading InitializedCodexCell.aclose and its monitor, which I
   enumerated but did not read line by line.

### Area 05 Persistence: the store layer and the migration ledger

31. Does any deployed database actually carry policies from the migrations
   without having run rls.sql? Settled per stack by SELECT relname,
   relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN
   ('artifacts','devices','budget_usage') compared against SELECT 1 FROM
   pg_roles WHERE rolname='boltrig_app'. Not answerable from the tree; it is a
   runtime fact.
32. Is the app role a Postgres superuser on every live stack? The tree asserts
   it only for the beelink
   (tests/security/test_rls_covers_explicit_transactions.py:9). Settled by
   SELECT rolname, rolsuper, rolbypassrls FROM pg_roles per stack. If any
   stack is non-superuser, the unconditional FORCE-RLS migrations are already
   an outage there.
33. Has `alembic upgrade head` from base ever been run against a schema.sql-
   bootstrapped database past revision 0043? The 2026-07-25 rehearsal ended at
   0037_secure_input, before 0044 introduced the first non-idempotent CREATE.
   Settled by restoring a schema.sql-only dump into a scratch database and
   running the chain.
34. How many credential_refs rows are still sealed under the v1 unsalted
   SHA-256 derivation, or still plaintext? Not answerable statically because
   the envelope carries no key id by design. Settled by counting rows whose
   data lacks the sealed marker plus an instrumented decrypt recording which
   MultiFernet member succeeded.
35. Is mcp_servers.credential populated on any live stack? Settled by SELECT
   count(*) FROM mcp_servers WHERE credential IS NOT NULL per tenant. Nothing
   in the tree writes or reads that column, so a non-zero count means material
   nothing seals.
36. What is the intended sweeper for idempotency_keys and trajectory_events?
   Neither appears in the background_job_receipts.job_name CHECK set and
   nothing in the tree names one. Settled by a decision record or a new job
   name in that CHECK.
37. Does InMemoryStore satisfy isinstance(store, Store) at runtime? Store is
   @runtime_checkable and I did not execute the check (no test runs allowed).
   Settled by importing both and asserting; a gap would be a parity hole the
   AST diff cannot see if it lives on a contract fragment neither backend
   implements.
38. The task brief named an 'in-memory / sqlite / Postgres backend split', but
   no SQLite store exists. aiosqlite is a dev-only dependency with zero
   importers (bounded: rg over boltrig/, tests/, apps/, services/,
   libraries/), and every SQLite mention in the tree is the Codex CLI's own
   state file. Settled by removing the dependency or naming the store it was
   meant to serve.

### Area 06 Adapters, egress policy, and MCP consumption

39. Does any deployment set FISH_ENABLE_ASR=1? The code states that doing so
   silently takes voice.listen away from xai-voice at the next boot via last-
   registration-wins. Settled by reading the live manifests and env on the
   deployed stacks, which the pinned tree cannot answer.
40. Is AdapterLoader.load_module meant to stay? It is the only generic module-
   load path and nothing in the pinned tree calls it; manifest_apply
   reimplements the same catch-and-mark contract inline. Settled by a decision
   record or by deleting it and seeing whether a downstream bundle breaks.
41. What reads adapters.health? The column is written as UNKNOWN at
   registration while the live posture lives in the loader's in-memory dict.
   Settled by tracing every reader of the column across the API and frontend,
   outside this area's scope.
42. Should assert_no_metadata_egress be deleted or wired? It carries a
   documented fail-open fix for a bug it can no longer suffer because nothing
   calls it. Settled by an owner decision.
43. Does the mq_file seam family have any live consumer? It declares no verbs
   and its docstring calls the pieces 'deliberately thin SEAMS, not finished
   adapters'. Settled by tracing KafkaSeam / RabbitMqSeam /
   FileShareIngestSeam construction across the whole tree; I bounded my search
   to boltrig/adapters/.
44. Is the inbound_webhook helper reachable from a live ingress route? It
   defines no adapter class and exports verify_and_normalise; its caller is an
   ingress layer outside this area.
45. Should the adapters.runtime column comment (http | sql | mq | file |
   script) be widened to include 'mcp', which McpConsumerAdapter actually
   writes into it? There is no CHECK constraint so rows are accepted, but a
   reader treating the comment as the domain is wrong.
46. Do mcp_probe_receipts need retention or partitioning? Each probe writes a
   uuid-keyed row and the schema has no TTL, so a polling operator or scripted
   retry loop grows the table without bound.

### Area 07 Identity, authentication, seats and capabilities

47. Does any control-plane handler re-apply the SEC-102 privilege ceiling, or
   is _reject_escalation in access_routes.py the only enforcement? Settled by
   reading control.user.update and control.invitation.create in
   boltrig/config/control_operations.py and control_compat.py, which I read
   only at line 298.
48. Is there a janitor that expires or deletes stale user_sessions,
   personal_access_tokens or two_factor_challenges rows? My bounded rg for
   DELETE FROM found none, but a sweep could be an UPDATE ... SET revoked.
   Settled by reading boltrig/fleet/ janitors and kernel/hitl_expiry.py.
49. Does the channel principal path (credential_kind unset, therefore machine,
   actor_tier human) reach respond_to_hitl? If so the sole-author relief
   admits it exactly as it admits a PAT. Settled by tracing channel intake
   replies in boltrig/kernel/channel_* (area 09).
50. Is SamlVerifier used by any deployment overlay outside the pinned tree?
   Inside it, five references and none constructing it with a validator.
   Settled by a deployment inventory.
51. What enforces an invitation's expires_at at CREATION time? Both consumers
   refuse an expired invitation, but whether one can be created with no expiry
   at all is unsettled. Settled by reading control.invitation.create.
52. Does the Bifrost virtual key carry a TTL or rotation schedule of its own,
   or does it live until the seat is re-minted or revoked? Settled by reading
   bifrost_user_admin.ensure_virtual_key's HTTP bodies, which I sampled but
   did not read line by line.
53. Where is a capability mapping-pack binding set to 'proposed', and which
   route approves it? load_packs only parses and validates; the caller is
   outside the files I read. Stated as a gap, not an absence claim.

### Area 08 Memory planes, the Knowledge extension, and distillation

54. Does memory.bundle reach any model? No caller exists beyond the HTTP route
   and the adapter (bounded rg across boltrig/, apps/, sdks/, libraries/,
   ios/); decision 0029 declares this an open seam. Settled by finding a
   prompt-assembly call site.
55. Is MEM-ENG-03's erasure half ever executed in CI? The three live Cognee
   tests are declared service-gated in the invariant file itself. Settled by a
   CI job setting BOLTRIG_COGNEE_LIVE=1, or by an offline double for
   cognee.forget.
56. What actually happens to a semantic slot after a cross-process partial-
   unique-index violation? Reasoned from the code, not observed. Settled by a
   two-writer test against the disposable Postgres container.
57. Is _compensate reachable in practice? It is called only from
   _commit_accepted and no test node asserts the compensated state (bounded:
   the seven tests in tests/security/test_typed_memory.py).
58. Does anything consume
   QueuedMemoryProjectionFanout.projection_delivery_posture()? Not searched
   beyond boltrig/memory/. Settled by an rg across boltrig/kernel/ and apps/.
59. What is the intended lifetime of knowledge_projection_outbox? Migration
   0034 created it with a pending index, implying a durable projection worker
   that was never built. Settled by a decision record.
60. Should memory.forget be high-consequence? It is low with an explicit
   compliance-right rationale while knowledge.asset.erase is high; the
   asymmetry is argued on one side only. Settled by a ruling.
61. Does the sidecar's _model_args fallback allow an arbitrary HF repo
   download when a gate incumbent_model contains a slash and is not an adapter
   directory? The charset is constrained and the caller is a governed verb,
   but mlx_lm.load's network behaviour was not read.

### Area 09 Workflows, work items, skills and the YAML libraries

62. Is a multi-tenant, single-worker deployment supported? If it is, the one-
   tenant workflow scheduler is an outage class. Settled by reading the
   deploy/ manifests for a worker running against a store holding more than
   one tenant_id.
63. Was the cron path's bypass of control.workflow.trigger's HITL gate (it
   calls WorkflowLibrary.trigger directly rather than kernel.invoke) a
   deliberate decision? FR-WFL-20 covers re-authorisation but says nothing
   about per-occurrence consequence gating. Settled by a decision record
   naming the scheduled-occurrence approval posture.
64. How long may a task sit queued before the context envelope's carried
   grants are stale? Depends on the Hatchet queue retention and retry policy,
   which lives outside this area. Settled by the HatchetExecutor configuration
   and the engine task TTL.
65. Should libraries/workflows/ be loaded, deleted, or explicitly labelled?
   Today it is data no path reads, containing at least one file that cannot be
   persisted. Settled by a product decision, not a code reading.
66. Does any tenant hold a _boltrig_routine workflow authored before the
   routine contract existed? That is the only way the workflow list route's
   raising routine projection can fire. Settled by a query against a live
   store, deliberately not performed in this pass.
67. Is WorkflowLibrary.match's waiver still live? Its docstring says it
   retires on expiry without an answer, but no expiry DATE is recorded in the
   source. Settled by reading the expiry clause in the VJS order itself.
68. Is code.run intended to become executable? The interpreter records intent
   and a script length but runs nothing. Whether a sandbox is planned decides
   whether it is a SEAM or permanently DEAD. Settled by a decision record
   naming the sandbox.
69. Should the 28 DAG-parity tests (error strategies, retry, OR-join, multi-
   case branch, parallel loops, approval branch handles) be bound to an
   invariant id? They carry none today, so make invariants cannot notice a
   regression. Settled by whether the invariant register is meant to cover
   authored control-flow semantics or only cross-cutting doctrine.

### Area 10 Model catalogue, routing, and the sensitive-to-local rule

70. Is kind == 'local' or data_class == 'sensitive' the intended residency
   predicate? The router uses the latter, the control-plane verb and the
   /v1/model-policy projection use the former, and doctor uses the latter plus
   a host heuristic. No decision record names kind (bounded: rg -ni 'local
   kind|kind == .local' docs/decisions/ returns nothing).
71. Was the Cognee knowledge-compilation path deliberately excluded from
   SEC-12? The distill path got an explicit SEC-12 companion rule in
   tests/invariants.yaml, which shows the question was asked at least once;
   nothing equivalent exists for knowledge compilation.
72. Does the pinned maximhq/bifrost image enforce admin authentication? The
   transport sends no authorization header when BOLTRIG_BIFROST_MANAGEMENT_KEY
   is empty, which is the default. Settled by reading that image's config
   defaults, which I did not do (no docker in this run).
73. Is ModelEndpoint.fallback ever traversed by anything? The router
   explicitly refuses to follow it and I found only validation and reference-
   graph readers (bounded: rg -n '\.fallback' boltrig/). If nothing will ever
   traverse it, it is a dead field that still carries approval weight.
74. What should price a run whose capability declares no model_endpoint at
   all? _true_up_cost leaves the price key as None and the tier default
   applies; whether that is intended for the scoped-AI and automatic-Codex
   lanes, which are the normal hosted lanes, is undocumented.
75. Does any Worker surface show the operator that models.default is inert?
   The API reports serving_state 'inactive_no_consumer'; whether apps/worker
   renders that is outside my read bound.
76. Register residue I deliberately did not fix: BT-REQ-1010's evidence in
   requirements.tsv cites boltrig/config/manifest.py:592 where the anchor is
   at 591 (off by one, anchor still verbatim and unique). The spec markdown is
   corrected; the TSV was left alone because the contract forbids rewriting a
   file nineteen agents are appending to concurrently.

### Area 11 Configuration: the manifest, the environment, and release mode

77. Was the omission of dev_egress_loopback from the extra allow-list a
   regression or has the feature never been reachable from a manifest? git log
   -S 'dev_egress_loopback' -- boltrig/config/manifest.py over the full
   history would settle it; this reading is pinned to one commit and did not
   walk history.
78. Does the API's routine ChatService ever carry attachments or paginate a
   conversation? If it cannot, the divergent caps are inert rather than a
   policy hole. Settling it needs the chat and workflow areas: trace
   run_workflow_body(..., routine_chat=...) to every ChatService method it
   reaches.
79. The mastra section is retained in extra but no reader was found (bounded:
   rg -n 'section(\"mastra\")|\bmastra\b' boltrig/, 2026-08-24, returns only
   the allow-list tuple). Is it retained for a future adapter bind or is it
   residue?
80. evaluation, notifications and personal_agents are in the extra allow-list
   and present in the template, but no .section() call names them. Which
   accessor do their subsystems use? Confirming requires the eval,
   notification and personal-agent areas.
81. What should happen when BOLTRIG_MANIFEST names a path that does not exist?
   Today _find skips it silently and falls through to /app/manifest.yaml,
   manifest.yaml and then manifest.example.yaml. Whether an explicit-but-
   missing value should be a hard failure is a product decision.
82. Under Compose, a missing host manifest.yaml makes Docker create a
   DIRECTORY at /app/manifest.yaml; os.path.exists answers True for a
   directory, so _find_manifest would select it and open() would raise
   IsADirectoryError out of composition. Reasoned from code plus documented
   bind-mount behaviour, NOT observed; running a container would settle it and
   the contract forbids that here.
83. Is any deployed tenant's manifest.yaml still carrying
   approval_timeout_seconds: 3600 inherited from the template? Only inspection
   of the live stacks would answer it, and no deployed environment was read.
84. Five of the sixty-three rows appended to registers/requirements.tsv carry
   a line number one or two lines stale relative to the corrected spec (BT-
   REQ-1105, 1115, 1116, 1118, 1134); every anchor in them is verbatim and
   exact. The register may not be rewritten while other agents append, so the
   drift is recorded rather than fixed.

### Area 12 Observability, readiness, doctor and log safety

85. Is /v1/audit/verify or boltrig audit-verify ever actually invoked? No
   cron, timer, compose entry, Makefile target or script in the pinned tree
   calls either (bounded rg over docker-compose.yml, deploy/, scripts/,
   Makefile). Settled by reading a live deployment's scheduler.
86. Does any deployment set BOLTRIG_AUDIT_HMAC_RETIRED? The mechanism, tests
   and docstrings exist but no manifest, compose file or .env.example line
   sets it. Settled by reading a live deployment's environment.
87. What writes the backup freshness marker, and is that write atomic?
   backup_status only reads BOLTRIG_BACKUP_HEALTH_FILE; the writer is
   scripts/backup.sh in the profile-gated sidecar, which is another area's
   scope.
88. Is EXPECTED_ALEMBIC_HEAD graph-checked against Alembic or only string-
   compared? The invariant text claims graph-checked; the test requires a
   database fixture and running it was forbidden here. Settled by reading
   tests/integration/test_migration_parity.py.
89. Does any status-provider component other than bifrost carry a
   metadata.live_health key? Readiness reads that key by hard-coded component
   id. Settled by reading boltrig/fleet/stack_tool_status.py.
90. Is the SecurityEvent stream scrubbed by the same code path as AuditEvent?
   kernel/audit.py scrubs for AuditEvent; the security writer in
   kernel/security_events.py was read only for the anchor.
91. What is the retention policy for audit_log in a real deployment? The table
   has no retention mechanism in this tree and the retention janitor is
   explicitly forbidden from touching it.

### Area 13 Process composition, bootstrap and the CLI surfaces

92. Does the hatchet-worker service actually reach ctx.aio_wait_for and
   consume the approval event the API pushes? Decision 0018 reserved that path
   as untested. Settled by a live Hatchet run that pauses, is approved through
   the API, and reaches CONSUMED with the engine wait as the only trigger.
93. Is the memory-projection fanout executor registered anywhere other than
   the API process? wire_memory_projection_executor is called only from
   _build_platform_services and the fleet worker never calls it. Settled by
   tracing which process delivers a queued memory projection in a Hatchet-live
   deployment.
94. Should manifest_generation on a birth receipt describe the manifest the
   kernel was SEEDED with (the raw snapshot) or the desired-state OVERLAY it
   currently digests? All three processes are internally consistent, so no
   drift is visible between them, but the intent is stated nowhere I read.
95. Does boltrig worker's always-zero exit code matter to any supervisor?
   Compose runs python -m boltrig.api.worker directly rather than through the
   CLI, so the CLI path may be operator-only. Settled by checking deployment
   units outside this repo.
96. Is boltrig/api/ deliberately outside the architecture gate, or an
   omission? The gate names domain, ports, application, models and kernel and
   says nothing about the composition root. Settled by the gate owner stating
   whether boltrig.api is intended to be unconstrained.
97. Should hitl.set_resume_notifier refuse a second registration? It stores a
   single callable, so a second wire_hitl_resume in one process REPLACES the
   first and silently loses legs. No production process calls it twice, but an
   embedder or a test that does would lose the held-write leg without a
   signal.

### Area 14 Presence, devices, camera, emotion and the Familiar

98. "The membrane" names no Familiar concept in the pinned tree: rg -ni
   "membrane", 2026-08-24, returns zero hits in familiar/, in either copy of
   familiar.frag and in boltrig/. Every hit is Ultron's body or Jarvis's
   lattice. Settled by confirming whether the brief meant Ultron's membrane or
   a term used outside this repository.
99. Does anything produce FamiliarState v2? The contract, its sanitizer and
   its unit tests exist in sdks/web; bounded rg finds no producer and no
   consumer. Settled by a producer in another repository or a decision
   retiring the contract.
100. Is boltrig/camera/ intended to be wired, retired, or kept as the
   reference model for a future platform layer? It has a complete
   CameraBackend protocol with no implementation in-tree and no decision
   record among the 41 in docs/decisions/.
101. What sets devices.presence back to offline, and what ever sets locked?
   Nothing observed writes either after creation. Settled by a heartbeat
   expiry rule or by dropping the column to the two values actually written.
102. Are the sensing daemons (camerad, capture_policy.py, presence.py) in
   scope for this repository? They are cited by path but live in
   ~/Projects/companion-observer, so every behavioural claim about them here
   is a claim about a SEAM. Settled by vendoring them or by stating they are a
   separate product.
103. Does the deferred Unreal premium backend exist anywhere? Decision 0025
   names boltrig-familiar unreal/FamiliarUE/ and pins an editor MCP to
   127.0.0.1:8765; nothing in this tree references it.
104. What re-issues a device session after a 24 hour lapse without a human? By
   construction nothing can, since rotate_session authenticates first and
   enrollment demands actor_tier human. Whether that is the intended permanent
   posture for an unattended host is not recorded anywhere.

### Area 15 The worker UI: the primary surface

105. Are the unmounted account, automation, inbox and conversation-control
   surfaces a deliberate staging step or an accidental regression? The tree
   carries no comment, decision or ledger entry marking them withdrawn, and
   the parity documents still claim them. Only the commits that replaced the
   account and automations route bodies would settle it, and this corpus is
   not pinned to history.
106. Does the Tauri webview actually refuse the twenty modules' inline style
   attributes under its stricter CSP? Settled only by running the signed
   desktop build and reading its console, which this corpus does not do.
107. What links a person to #/runs, #/work, #/home, #/channels, #/evaluations,
   #/memory or #/account if they never open the command palette? Nothing in
   the shipped navigation does. Whether that is intended minimalism or an
   unfinished nav is a product question the tree does not answer.
108. Is the Worker's four-hour session rotation interval aligned with the
   kernel's session lifetime? The interval is a client constant; the kernel
   expiry was not read for this area. A mismatch would present as an avoidable
   sign-out.
109. Which of the 42 stylesheets are still reachable? AutomationViewParity.css
   demonstrably is not. A full CSS reachability sweep was not performed; only
   the modules that import a stylesheet were enumerated.
110. Does runEvents have a mounted consumer? It is called from
   chat/ToolReceiptDetails.tsx, inside the chat tree, but the exact user
   action that renders that component was not traced.
111. Do the shader, renderer and tuning modules under canvas/, familiar/,
   jarvis/, ultron/ and colossus/ contain further unreachable code? They were
   read only at their registration surface, since area 14 owns the Familiar
   Stage.
112. Is the absence of any end-to-end, browser-driver or accessibility stage
   in the Worker gate a deliberate scope decision? tests/visual/ is a manual
   capture tool plus a manifest freshness check, and no axe-equivalent sweep
   exists anywhere in the gate.

### Area 16 The SDKs and the marketing site

113. REGISTER DUPLICATION, needs the orchestrator: docs/brownfield-
   spec/registers/requirements.tsv now holds TWO copies of BT-REQ-1600..1699
   (200 rows). A harvester appended a snapshot of my table at lines 1338-1437
   before I appended mine at 1638-1737; only my area is duplicated. I did not
   rewrite the file, per the contract's append-only rule. Dedupe by id keeping
   the LAST occurrence: the later block carries the corrected statements
   (eight not nine SDK-only methods, twenty one not twenty ChatEvent members,
   25 not 26 refused schema keywords, corrected test-file evidence).
114. Is @wlilley93/boltrig-web-sdk@0.2.0 actually published? PUBLISHING.md
   logs a receipt for 0.1.0 only while package.json reads 0.2.0. Settled by
   querying the GitHub Packages registry, which this reading must not do.
115. Is there a stability promise at all? Neither package carries a CHANGELOG,
   a semver policy or a deprecation process (bounded: find . -iname
   CHANGELOG*, one hit, the starter's vault note). Settled by an owner
   statement, not by the tree.
116. Does any consumer outside this repository import the web SDK? The seven
   subpath exports exist and the package is public-scoped, but no file in the
   tree imports a subpath. Settled by registry download stats or by naming the
   consumers.
117. Does the site's /console page exist deliberately or is it a development
   leftover? It is linked from the persistent header as the product's "Open
   console" while two other CTAs point at app.boltrig.ai. Settled by an owner
   decision.
118. Who copies site/ build output to /srv/boltrig-marketing, and with what
   check? No script in the tree does it; the host Caddy is deliberately
   outside the repository.
119. Was sdks/node meant to stay private:true? Decision 0038 calls it "the
   third-party plugin path", which a private unpublished package cannot serve.
120. Should the web SDK's chat-event union declare `replay`? The kernel emits
   it and docs/addons.md promises it; adding it is a contract change and
   therefore an owner call.

### Area 17 The channel gateway, messaging bridges and calls

121. Does any deployment actually run two channel-gateway replicas? The per-
   channel lease makes a second replica safe for ownership, but the process-
   local MCP registry makes its token useless against a different API replica.
   Settled by the production compose overlays and replica counts, which are
   outside the pinned tree.
122. Is /voice/ reachable unauthenticated in the shipped production edge, or
   does Caddy gate it upstream? deploy/Caddyfile.example mentions the voice
   proxy only in a comment while the Worker nginx image proxies the whole
   prefix. Settled by the live Caddy config of a deployed stack.
123. What sweeps channel_outbox, channel_gateway_status and
   realtime_call_events in a long-lived tenant? No janitor exists in the tree
   (bounded rg over boltrig/); only channel_deliveries is swept. Settled by an
   operator statement or a retention job outside the tree.
124. Is the one-hour gateway token TTL operated by hand today? The README says
   token placement is an operator action and names no automation. Settled by
   the runbook of a stack that actually runs the channels profile.
125. Does the msteams provider have any consumer? It is a webhook-transport
   provider with a Teams label and no adapter of its own. Settled by finding a
   tenant with an msteams channel row, which cannot be done from the tree.
126. Was the voice channel's static speaker config ever bound to a real
   Principal in a shipped deployment? The non-browser voice path attributes
   every utterance to one configured external user id, which is only
   meaningful for a single-speaker physical box. Settled by a live channel
   row.

### Area 18 The iOS companion application

127. Does the app compile and pass at commit 19bcae7f? The last recorded run
   predates two merged PRs and says 94 tests; the tree has 95 methods and
   README says 94. Settled by one xcodebuild test on the M4 with signing on.
128. Can the phone's Approve button actually approve on a single-human tenant?
   The sole-author relief is gated on an interactive credential kind and a PAT
   is kind 'pat', so the phone may be refused exactly where the web is
   allowed. Settled by reading boltrig/kernel/hitl_response_auth.py:165-265 or
   a live run with a pending approval.
129. Is LinkedDevice.liveWindow of 20 s correct against the desktop's real
   heartbeat? The comment says the desktop polls every 3 s; I did not verify
   that in apps/worker/src-tauri. Settled by grepping the Tauri presence
   interval.
130. SessionStore builds several URLSessions from one shared ephemeral
   configuration and never invalidates them, so signInSession and the
   password-reset session share cookie storage. I could show no leak, only
   that nothing forces the cookie out. Settled by a test that signs in,
   cancels, and asserts the next session sends no cookie.
131. Does release(_:) ever draw a frame at the wrong presentation? It queues a
   minimised state after clearing the owner, apply is a no-op unless isReady,
   and the next claimant immediately pushes its own state. Settled by
   capturing the island's own log while switching tabs on a device.
132. The 20.6 MB WebContent figure, the 1.0 s ready time and the frame rates
   were all measured on a simulator and are explicitly a floor. No device
   measurement exists in the tree. Settled by running on a real iPhone with
   Instruments.
133. Does GET /v1/me/settings really return active_workspace_id at the root?
   Account.decode reads it there and no view under ios/Boltrig/Views/ ever
   uses it. Settled by reading the response builder in
   boltrig/kernel/account_profile_routes.py.

### Area 19 Deployment topology, the release train and recovery

134. Does deploy/compose.opbox-link.yml keep the kernel on the sandbox
   network? Its two-entry networks list depends on Compose's service-level
   merge rule; rendering base plus that overlay and reading the kernel's
   network set would settle it.
135. Is the .dockerignore '!docs/' re-inclusion real in practice? The
   reasoning follows Docker's last-matching-pattern rule with parent-path
   matching, but a plain-progress build's transferred context size would
   settle it.
136. What actually happens to make release-validate with RELEASE_PROFILES=
   empty? Compose's default omission of inactive-profile services is the
   premise; rendering the release model with and without the profile flag
   would settle it.
137. Which of the fifteen services actually restart after a host reboot?
   unless-stopped is declared on all fifteen, but the answer also needs the
   Docker daemon enabled at boot and no hand-stopped container; nothing in the
   tree asserts either.
138. Is deploy/wheelhouse ever populated on the release runners? The workflow
   build step passes no wheelhouse and the directory is git-ignored, so signed
   images are presumably built through the network branch; only the workflow
   text was read.
139. Does the ui service's sandbox membership matter outside the channels
   profile? Its only sandbox peer is channel-gateway for the /voice proxy, and
   the secure overlay's internal sandbox does not remove ui's default-network
   egress.
140. What is the intended posture for ui and backup under the hardening
   anchor? Both are first-party and neither merges it, and unlike signal-cli
   neither carries a comment saying why.
141. Which stack does scripts/roll-release.sh still serve? It hard-codes a
   canary project name and tenant path shape while both deployment documents
   call it non-production; whether it is still executed is a fact about the
   estate, not this tree.

### Area 20 Governance: invariants, gates, decisions and the court

142. Is make iac-scan red today on the AVD-DS-0002 acceptance that expired
   2026-08-15? Settled only by running the pinned aquasec/trivy:0.72.0 config
   scan, which this pass is forbidden to do.
143. Is core.hooksPath armed on the machine currently holding the pen? It is
   unset in the pinned checkout and the phased plan records it as deliberately
   unset on the beelink as of 2026-08-18.
144. Is apps/worker/tests/visual/manifest.test.ts green at this commit? Its
   source-digest assertion at line 1048 recomputes a git ls-files digest; the
   make target is absent from CI but the vitest it wraps is run by worker-
   quality, so the phased plan's 'no CI workflow runs it' may be wrong about
   the substance.
145. Are the six K-* ids declared here the same six the doctrine's Appendix A
   defines? The agent-kernel-doctrine repository is present in no form: no
   submodule, no vendored copy, no Appendix A file.
146. Which of the two 0030 decisions is the real 0030, and does either
   supersede the other? Both are dated 2026-08-18, both accepted, neither
   names the other.
147. Are the five orders marked implementation_status OPEN open in fact, or
   merely unannotated? No gate reads that field, and fifteen of the twenty-
   four orders declare no status at all.
148. Does enforce_admins remain false on main? Both governance documents say
   so and record the tightening condition as met, but the setting lives on
   GitHub and nothing in the tree can read it.
149. REGISTER NOTE, not a Boltrig question: the BT-REQ-2000 to 2099 block was
   already present in registers/requirements.tsv when I went to append,
   harvested from an earlier draft of my table. Ids, statements, statuses and
   invariants are byte-identical to mine; 29 of 100 evidence cells carry pre-
   repair anchors. I did NOT append a second time, because the register is
   append-only and duplicate ids would be permanent. The spec's own table is
   the authoritative evidence column.

## Structural gaps found by the corpus itself

- **The doctrine is cited and not pinned.** Boltrig declares
  `agent-kernel-doctrine` the sole source of K-1..K-30 and binds six of those
  thirty ids. No gate, hook or workflow references that repository, and no
  commit of it is recorded anywhere in this tree. The two can drift apart
  silently in either direction.
- **Two decision numbers are used twice.** `0023` names both
  `refuse-model-judged-approvals` and `sleep-distillation-and-the-adapter-seam`;
  `0030` names both `agents-tab-built-on-web-sdk` and `familiar-modes-and-dials`.
  A reference to "decision 0023" is therefore ambiguous and nothing detects it.
- **48.8 percent of requirement rows bind no invariant.** Binding debt zero
  means every declared invariant has a test. It does not mean every behaviour
  has an invariant, and nearly half do not.
- **25 percent of rows are IMPLEMENTED-UNTESTED.** Reachable behaviour for which
  an author looked for a test and found none.

