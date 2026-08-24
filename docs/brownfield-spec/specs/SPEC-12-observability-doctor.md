---
area: 12 Observability, readiness, doctor and log safety
id-block: BT-REQ-1200 to BT-REQ-1299
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: spec-area-12
date: 2026-08-24
---

# SPEC-12 Observability, readiness, doctor and log safety

## Search bound declared up front

Every file named in this area's scope was opened and read end to end: the twelve
modules under `boltrig/observability/`, `boltrig/log_safety.py`,
`boltrig/text_envelope.py`, the five doctor modules
(`boltrig/api/doctor.py`, `doctor_backups.py`, `doctor_codex.py`,
`doctor_edge.py`, `doctor_stack_state.py`), the five readiness modules
(`readiness.py`, `readiness_control.py`, `readiness_dependencies.py`,
`background_readiness.py`, `codex_readiness.py`), `boltrig/api/boot_guards.py`,
`boltrig/api/fleet_health.py`, `boltrig/api/logging_config.py`,
`boltrig/api/audit_verify.py` and `boltrig/kernel/audit.py`.

Files OUTSIDE the scope were read only far enough to settle a boundary question
and are cited as such: `boltrig/kernel/health_routes.py`,
`boltrig/adapters/loader.py` (health snapshot), `boltrig/kernel/pii.py`,
`boltrig/kernel/run_access.py` (tree scoping), `boltrig/kernel/security_events.py`
(anchor read side), `boltrig/kernel/platform_routes/observability.py`,
`audit_search.py`, `platform_status.py`, `backup_status.py`,
`boltrig/fleet/model_gateway.py` (gateway posture), `boltrig/fleet/spawn.py`
(sink call order), `boltrig/store/postgres.py` (audit read shapes),
`boltrig/store/schema.sql`, `scripts/check_health_claims.py`,
`scripts/verify-deployment.sh`, `scripts/validate_release_runtime.py`,
`docker-compose.yml`, `Makefile`, `.env.example` and `tests/invariants.yaml`.
Nothing about those files is claimed beyond the lines cited.

Absence claims in this document each carry their own `rg` bound inline.

## 2. Purpose

This subsystem is the whole of what Boltrig says about itself: the records it
emits, the redaction that keeps credentials out of them, and the three
independent verdicts an operator or an orchestrator reads before trusting the
stack. Those verdicts are deliberately layered: `boltrig doctor` answers "is this
CONFIGURATION deployable" with no dependency I/O, `/healthz` answers "is this
PROCESS alive" from cached state only, and `/readyz` answers "can this deployment
SERVE" by probing every enabled dependency and failing closed. The audit chain is
the compliance record of record; every other surface here is a projection over it
or a bounded, content-free receipt that says in its own field names exactly how
little it proves.

## 3. Boundaries

**What this area owns.**

- Record emission and redaction: the audit writer's scrub, the log-injection
  helper, the untrusted-input envelope, and the one declared logging config.
- The doctor: static, I/O-free configuration checks and their exit code.
- Readiness and liveness: `/readyz`'s bounded probes, `/healthz`'s cached
  posture, `boltrig fleet-health` for the listener-less worker, and the two boot
  guards that abort rather than warn.
- The read side of the audit chain: `verify_chain`, key epochs, the
  `audit-verify` CLI, and the projections built from audit rows
  (`observability/tree.py`, `observability/model_telemetry.py`).
- The authenticated platform-status projections under `boltrig/observability/`.

**What it must not touch.**

- `boltrig/log_safety.py` imports NOTHING from the rest of the package by
  deliberate rule, so that adapters and kernel can share one copy:
  [`boltrig/log_safety.py:16`](../../../boltrig/log_safety.py)
  `"This module has NO imports from the rest of the package"`.
- `boltrig/text_envelope.py` is "a neutral low-level helper with no fleet or
  kernel dependencies", so the kernel never imports the fleet to envelope a span:
  [`boltrig/text_envelope.py:1`](../../../boltrig/text_envelope.py)
  `"The canonical untrusted-input envelope"`.
- `boltrig/api/doctor_edge.py` returns raw tuples specifically so it does not
  import the doctor report types:
  [`boltrig/api/doctor_edge.py:16`](../../../boltrig/api/doctor_edge.py)
  `"without importing the doctor report types"`.
- The gateway readiness posture lives in the gateway module, not in
  `readiness.py`, because `readiness.py` was at the 400-line structure ratchet:
  [`boltrig/fleet/model_gateway.py:147`](../../../boltrig/fleet/model_gateway.py)
  `"Lives here rather than in api/readiness.py"`.
- The doctor performs NO dependency I/O by contract:
  [`boltrig/api/doctor.py:1`](../../../boltrig/api/doctor.py)
  `"Static production-readiness checks with no dependency I/O."` It does read the
  local filesystem for the browser CLI (see RISK 12-R7).
- `/healthz` must never await live adapter I/O:
  [`boltrig/adapters/loader.py:95`](../../../boltrig/adapters/loader.py)
  `"must never await live adapter"`.

**What does NOT exist here.** There is no Prometheus exporter, no OpenTelemetry
instrumentation, no statsd client, and no `/metrics` route anywhere in the tree.
Bounded: `rg -n "prometheus|opentelemetry|statsd|/metrics" -i --glob '*.py'
--glob '*.yml' --glob '*.toml'` over the pinned tree on 2026-08-24 returned zero
files. Every quantitative figure Boltrig reports (cost, tokens, latency,
per-model call counts) is reconstructed at read time from audit rows.

## 4. Objects and contracts

### 4.1 `AuditEvent` (the record of record)

Fields, all as declared at
[`boltrig/models/audit.py:57`](../../../boltrig/models/audit.py)
`"class AuditEvent:"`: `tenant_id`, `ts`, `actor`, `action_type`, `status`,
`run_id`, `parent_run_id`, `actor_tier`, `depth`, `noun`, `verb`,
`target_adapter`, `on_behalf_of`, `latency_ms`, `tokens_used`, `cost_micros`,
`skills_loaded`, `detail`, then the nullable Opbox-depth enrichment
(`ip_address`, `user_agent`, `resource`, `resource_id`, `workspace_id`), then the
three chain fields `seq` / `prev_hash` / `hash` which "are not set by callers"
([`boltrig/models/audit.py:88`](../../../boltrig/models/audit.py)
`"filled by the audit writer (K-19)"`).

`ActionType` is a closed five-value enum: `tool_call`, `workflow_trigger`,
`agent_spawn`, `hitl`, `model_call`
([`boltrig/models/audit.py:20`](../../../boltrig/models/audit.py)
`"TOOL_CALL = \"tool_call\""`).

Lifecycle: a caller constructs an event with no chain fields; `AuditWriter.write`
scrubs, assigns `seq = head + 1`, sets `prev_hash`, computes `hash`, and appends;
on an append fault the three chain fields are reset to None and the payload goes
to the outbox for the janitor to re-chain later
([`boltrig/kernel/audit.py:360`](../../../boltrig/kernel/audit.py)
`"event.seq = None"`).

### 4.2 `DoctorCheck` / `DoctorReport`

`DoctorCheck` is a frozen `(name, status, message, hint)`
([`boltrig/api/doctor.py:44`](../../../boltrig/api/doctor.py)
`"class DoctorCheck:"`). `status` is one of the three literals `ok`, `warn`,
`fail`; no enum constrains it, the writers use string literals. `DoctorReport`
carries `production: bool` and the tuple of checks, and derives
`failed = any(c.status == "fail")` and `exit_code = 1 if failed else 0`
([`boltrig/api/doctor.py:62`](../../../boltrig/api/doctor.py)
`"return 1 if self.failed else 0"`). A `warn` therefore NEVER changes the exit
code; the `--production` flag is what promotes deploy blockers to `fail`.

Sibling check shapes deliberately do not import `DoctorCheck`: `doctor_edge` and
`doctor_backups` return `tuple[str, str, str, str]`
([`boltrig/api/doctor_backups.py:11`](../../../boltrig/api/doctor_backups.py)
`"DoctorResult = tuple[str, str, str, str]"`), and `doctor_stack_state` returns
its own frozen `StackStateCheck`
([`boltrig/api/doctor_stack_state.py:16`](../../../boltrig/api/doctor_stack_state.py)
`"class StackStateCheck:"`). `run_doctor` splices all three into one list.

### 4.3 Readiness check dict

Every readiness leaf is a dict built by one of two identical `_check` helpers
([`boltrig/api/readiness.py:100`](../../../boltrig/api/readiness.py)
`"def _check(status: str, *, required: bool"` and
[`boltrig/api/readiness_dependencies.py:13`](../../../boltrig/api/readiness_dependencies.py)
`"def _check("`): `{"status", "required", optional "reason", plus extras}`.
Observed `status` values across the module: `ok`, `failed`, `disabled`,
`unchecked`, `test_only`, `unknown`. The aggregate is
`ready = all(not item["required"] or item["status"] == "ok" ...)`
([`boltrig/api/readiness.py:202`](../../../boltrig/api/readiness.py)
`"ready = all(not item[\"required\"]"`), so ONLY `required` checks can hold traffic
and only the exact string `ok` passes.

### 4.4 `ObservabilitySink` protocol

Two methods: `record_spawn(...)` and `status_snapshot()`
([`boltrig/observability/langfuse_sink.py:25`](../../../boltrig/observability/langfuse_sink.py)
`"class ObservabilitySink(Protocol):"`). Two implementations:
`NoopObservabilitySink(reason=...)` and `LangfuseObservabilitySink(client)` with
six mutable counters (`attempt_count`, `success_count`, `failure_count`,
`last_attempt_at`, `last_success_at`, `last_failure_at`), all `init=False`
([`boltrig/observability/langfuse_sink.py:147`](../../../boltrig/observability/langfuse_sink.py)
`"attempt_count: int = field(default=0, init=False)"`). The counters are
PROCESS-LOCAL: they live on the one spawner instance and die with the process.

### 4.5 `BackgroundJobReceipt`

A frozen dataclass with eight validated fields plus a fixed
`receipt_kind="attempt_history_not_liveness"`
([`boltrig/models/background_jobs.py:70`](../../../boltrig/models/background_jobs.py)
`"receipt_kind: str = \"attempt_history_not_liveness\""`). `__post_init__` refuses
an unknown job name, a process identity not matching `^bjp_[a-f0-9]{24}$`, an
interval outside 1..604800, naive timestamps, a success/failure later than the
latest attempt, and a shape mismatch between `last_outcome` and the timestamps
([`boltrig/models/background_jobs.py:96`](../../../boltrig/models/background_jobs.py)
`"successful background job receipt has invalid shape"`). The registered job set
is a tuple of eight names; adding a name is what puts a loop on `/readyz` and is
explicitly NOT backward compatible
([`boltrig/models/background_jobs.py:24`](../../../boltrig/models/background_jobs.py)
`"name is NOT backward compatible"`).

### 4.6 The evidence-kind vocabulary

Four constants exist purely so a projection cannot be misread as liveness. They
are contract, not decoration:

| constant | value | source |
| --- | --- | --- |
| `BACKGROUND_JOB_EVIDENCE_KIND` | `bounded_attempt_receipt_not_liveness` | [`boltrig/observability/background_jobs.py:20`](../../../boltrig/observability/background_jobs.py) `"BACKGROUND_JOB_EVIDENCE_KIND ="` |
| `MEMORY_PROJECTION_EVIDENCE_KIND` | `bounded_status_receipts_not_queue_or_worker_liveness` | [`boltrig/observability/memory_projection_delivery.py:14`](../../../boltrig/observability/memory_projection_delivery.py) `"bounded_status_receipts_not_queue_or_worker_liveness"` |
| langfuse `evidence_kind` | `process_local_attempt_counters_not_sink_health` | [`boltrig/observability/langfuse_status.py:35`](../../../boltrig/observability/langfuse_status.py) `"process_local_attempt_counters_not_sink_health"` |
| codex `evidence_kind` | `process_composition_not_runtime_liveness` | [`boltrig/observability/codex_admission.py:61`](../../../boltrig/observability/codex_admission.py) `"process_composition_not_runtime_liveness"` |

Backup evidence carries the same discipline as three fixed fields:
`evidence_kind: shared_success_marker`, `liveness_claimed: False`, and
`restore_readiness: unavailable_no_restore_drill_receipt`
([`boltrig/observability/backup_status.py:27`](../../../boltrig/observability/backup_status.py)
`"unavailable_no_restore_drill_receipt"`).

## 5. Control flow

### 5.1 Writing one audit record (`AuditWriter.write`)

1. **Scrub `detail`.** Every key and every value is walked.
   [`boltrig/kernel/audit.py:344`](../../../boltrig/kernel/audit.py)
   `"event.detail = _scrub(event.detail)"`.
   A string value that `pii.contains_secret` matches is replaced entire by
   `{"_scrubbed": True, "digest": <sha256[:16]>, "size": n}` because "a SECRET
   taints its whole context"
   ([`boltrig/kernel/audit.py:208`](../../../boltrig/kernel/audit.py)
   `"digest = hashlib.sha256(v.encode()).hexdigest()[:16]"`). A string matching
   only `pii.contains_identity` has the matched SPAN substituted and the rest is
   kept legible, truncated to 256 chars
   ([`boltrig/kernel/audit.py:215`](../../../boltrig/kernel/audit.py)
   `"return pii.redact_identity(v)[:_PREVIEW_LEN]"`). Dicts recurse; lists and
   tuples recurse element-wise
   ([`boltrig/kernel/audit.py:219`](../../../boltrig/kernel/audit.py)
   `"if isinstance(v, (list, tuple)):"`). A KEY is scrubbed too, collapsing to
   the stable marker `[scrubbed:<kind>]` rather than to a dict, because the known
   consumer reads keys by name
   ([`boltrig/kernel/audit.py:196`](../../../boltrig/kernel/audit.py)
   `"return f\"[scrubbed:{kind}]\""`).
   FAILURE BRANCH: none; `_scrub` cannot raise on any value type (`return v` is
   the fallthrough at
   [`boltrig/kernel/audit.py:221`](../../../boltrig/kernel/audit.py)
   `"return v"`).
2. **Scrub `user_agent`.** The raw attacker-controlled header is collapsed to
   `[scrubbed:<kind>]` on a secret, identity-redacted otherwise, and truncated,
   staying a string so the column shape does not change.
   [`boltrig/kernel/audit.py:345`](../../../boltrig/kernel/audit.py)
   `"event.user_agent = _scrub_free_text("`.
3. **Take the per-tenant lock.** One `asyncio.Lock` per tenant serialises
   read-head then append so two concurrent writes cannot both claim `seq=N+1`.
   [`boltrig/kernel/audit.py:347`](../../../boltrig/kernel/audit.py)
   `"async with self._lock(event.tenant_id):"`. For multi-process deployments the
   Postgres `UNIQUE (tenant_id, seq)` is the backstop
   ([`boltrig/store/schema.sql:574`](../../../boltrig/store/schema.sql)
   `"UNIQUE (tenant_id, seq)"`).
4. **Chain.** `seq = head_seq + 1`, `prev_hash = <stored head hash>`, `ts`
   defaulted, then `hash = HMAC-SHA256(_HMAC_KEY, _canonical(event))`.
   [`boltrig/kernel/audit.py:353`](../../../boltrig/kernel/audit.py)
   `"digest = hmac.new(_HMAC_KEY, _canonical(event).encode()"`.
   `_canonical` folds the five Opbox-depth fields in ONLY when non-None, keeping
   the change strictly additive for pre-enrichment rows
   ([`boltrig/kernel/audit.py:144`](../../../boltrig/kernel/audit.py)
   `"if val is not None:"`).
5. **Append.** `store.audit_append(event)`.
   FAILURE BRANCH: any exception from steps 3 to 5 resets `seq`/`prev_hash`/
   `hash` to None, builds an outbox payload carrying only the exception TYPE
   ([`boltrig/kernel/audit.py:290`](../../../boltrig/kernel/audit.py)
   `"\"append_error\": type(exc).__name__,"`), enqueues it
   ([`boltrig/kernel/audit.py:364`](../../../boltrig/kernel/audit.py)
   `"await self._store.audit_outbox_enqueue("`) and logs a WARNING. Only if the
   OUTBOX write itself fails does `write` raise; that is the genuinely-unaudited
   case, and the dispatch-side `finally` catches it and logs it with every
   caller-chosen value passed through `log_safe`
   ([`boltrig/kernel/dispatch.py:483`](../../../boltrig/kernel/dispatch.py)
   `"\"effectful but UNAUDITED (SEC-16)\", log_safe(noun), log_safe(verb),"`).
6. **`write_now` is the janitor's primitive** and has no deferral branch at all,
   so the outbox drain cannot fork a second outbox row
   ([`boltrig/kernel/audit.py:375`](../../../boltrig/kernel/audit.py)
   `"Scrub, chain, and append with NO deferral"`).

### 5.2 Verifying the chain (`verify_chain`)

1. Resolve retired key epochs ONCE per verification, so the bound cannot move
   mid-scan. [`boltrig/kernel/audit.py:260`](../../../boltrig/kernel/audit.py)
   `"epochs = _retired_epochs()"`.
2. Page ASCENDING through `store.audit_scan(tenant, after, page)`; an empty page
   means the whole chain verified.
   [`boltrig/kernel/audit.py:262`](../../../boltrig/kernel/audit.py)
   `"events = await scan(tenant_id, after, page)"`.
3. For each row pick EXACTLY ONE key: the first epoch whose boundary the row
   predates, else the live key. Never "try them all", so a retired key can only
   vouch for the range it sealed.
   [`boltrig/kernel/audit.py:84`](../../../boltrig/kernel/audit.py)
   `"if seq < boundary:"`.
4. Compare `e.prev_hash != prev or e.hash != expected`; return
   `(False, e.seq)` at the FIRST bad row.
   [`boltrig/kernel/audit.py:268`](../../../boltrig/kernel/audit.py)
   `"if e.prev_hash != prev or e.hash != expected:"`.
   FAILURE BRANCH: because it returns at the first bad row, one unrepairable
   break makes every later row permanently unchecked; `start_after`/`seed_prev`
   exist for exactly that, and the seed is mandatory rather than optional
   ([`boltrig/kernel/audit.py:249`](../../../boltrig/kernel/audit.py)
   `"is not optional decoration"`).
5. A page whose last `seq` does not advance the cursor returns `(False, seq)`
   rather than looping forever.
   [`boltrig/kernel/audit.py:272`](../../../boltrig/kernel/audit.py)
   `"a misbehaving scan page must never loop forever"`.

A malformed `BOLTRIG_AUDIT_HMAC_RETIRED` entry is IGNORED, which is the fail-safe
direction: the row falls through to the current key and fails honestly, never a
silent accept ([`boltrig/kernel/audit.py:59`](../../../boltrig/kernel/audit.py)
`"Ignoring a malformed entry is the fail-safe"`).

### 5.3 `boltrig audit-verify`

1. Require `DATABASE_URL` or `BOLTRIG_DATABASE_URL`, else exit **2**.
   [`boltrig/api/audit_verify.py:35`](../../../boltrig/api/audit_verify.py)
   `"cannot verify, and cannot call that success"`.
2. Connect the Postgres store with `apply_schema=False`; an unreachable store is
   also exit **2**
   ([`boltrig/api/audit_verify.py:47`](../../../boltrig/api/audit_verify.py)
   `"return 2, f\"store unreachable:"`).
3. With `--from-seq N > 1`, read row `N-1` via `audit_scan(tenant, N-2, 1)` to
   seed `prev`; if that row does not exist, exit **2** rather than verify a
   segment against a None seed
   ([`boltrig/api/audit_verify.py:60`](../../../boltrig/api/audit_verify.py)
   `"to seed the segment from"`). The skipped range is PRINTED, "because skipping
   is exactly how a real break gets missed"
   ([`boltrig/api/audit_verify.py:98`](../../../boltrig/api/audit_verify.py)
   `"skipping is exactly how a real break gets missed"`).
4. Exit **0** on a verifying chain, **1** on a first bad seq, naming the seq and
   the registered epoch boundaries
   ([`boltrig/api/audit_verify.py:82`](../../../boltrig/api/audit_verify.py)
   `"AUDIT CHAIN DOES NOT VERIFY for tenant="`).

### 5.4 `run_doctor` (the ordered check pipeline)

`run_doctor(env, manifest_path, production)` at
[`boltrig/api/doctor.py:100`](../../../boltrig/api/doctor.py)
`"def run_doctor("`, in this exact order:

1. `prod = production or _production_signal(env)`; the signal is
   `BOLTRIG_PRODUCTION` truthy, or `ENV`/`BOLTRIG_ENV`/`APP_ENV` in
   `{prod, production, staging}`
   ([`boltrig/api/doctor.py:161`](../../../boltrig/api/doctor.py)
   `"in _PROD_NAMES for k in (\"ENV\", \"BOLTRIG_ENV\", \"APP_ENV\")"`).
2. `_check_datastores`: `database_url`, optional `postgres_tls`,
   `postgres_password`, `redis_url`, `audit_hmac_key`, `secret_store`.
3. `_check_auth`: `dev_auth`, `oidc`, `cf_access`, optional `cf_default_role`,
   `auth_mode`, optional `session_cookie_secure`.
4. `_check_edge` (delegated): `allowed_hosts`, `cors_origins`, optional
   `desktop_cors_origin`, optional `body_cap`, optional `tls_domain`.
5. `_check_manifest`: loads the manifest or records why it could not.
   FAILURE BRANCH: `manifest_path is None` records a bare `warn` regardless of
   production and returns None, skipping every manifest-dependent check below
   ([`boltrig/api/doctor.py:374`](../../../boltrig/api/doctor.py)
   `"No manifest path was provided; manifest checks skipped."`). A path that does
   not exist is `fail` under production, `warn` otherwise. A load exception is
   always `fail` and reflects the exception type and message.
6. `_check_runtime`: warns per retired runtime name still enabled in the manifest
   ([`boltrig/api/doctor.py:361`](../../../boltrig/api/doctor.py)
   `"f\"retired_runtime_{kind}\","`). The retired set is
   `pi hermes openai claude-api opencode rivet rivet_agentos rivet-agentos`
   ([`boltrig/api/doctor.py:328`](../../../boltrig/api/doctor.py)
   `"_RETIRED_RUNTIMES = frozenset("`).
7. Manifest-gated block, only when a manifest loaded: `_check_stack_tool_state`,
   `_check_model_posture`, `_check_memory_posture`, then `codex_release_check`.
8. `backup_checks` (always, manifest or not).
9. `_check_durable_engine` (always).

The CLI prints either `format_report` or `to_json` and returns
`report.exit_code` ([`boltrig/api/cli.py:293`](../../../boltrig/api/cli.py)
`"print(report.to_json() if args.json else format_report(report))"`).

### 5.5 `/readyz` (`ReadinessService.check`)

1. **Cache hit.** If a snapshot is younger than `BOLTRIG_READINESS_CACHE_TTL`
   (default 1.0s, clamped 0.1..5.0) return a deep copy without probing.
   [`boltrig/api/readiness.py:161`](../../../boltrig/api/readiness.py)
   `"if cached is not None and loop.time() - cached[0] < cache_ttl:"`.
2. **Coalesce.** Otherwise take `self._cache_lock` and re-check, so concurrent
   unauthenticated probes cannot amplify into unbounded dependency probes.
   [`boltrig/api/readiness.py:166`](../../../boltrig/api/readiness.py)
   `"async with self._cache_lock:"`.
3. **Database + migration.** Required when production OR `DATABASE_URL` is set.
   Probe is `store.readiness_snapshot()` unless injected; a store without that
   method is `wrong_store`; a probe exception is `probe_failed` for both checks;
   the head must equal the packaged head EXACTLY and as the only applied head
   ([`boltrig/api/readiness_dependencies.py:130`](../../../boltrig/api/readiness_dependencies.py)
   `"head_ok = tuple(heads) == (expected_head,)"`). The packaged head constant is
   `0086_conversation_addressing`
   ([`boltrig/api/readiness.py:27`](../../../boltrig/api/readiness.py)
   `"EXPECTED_ALEMBIC_HEAD = \"0086_conversation_addressing\""`), which matches the
   Alembic head revision on disk
   ([`migrations/versions/0086_conversation_addressing.py:24`](../../../migrations/versions/0086_conversation_addressing.py)
   `"revision = \"0086_conversation_addressing\""`).
4. **Redis.** Not required when unconfigured and not production. Under
   production a non-shared event relay is an immediate `wrong_backend` failure
   ([`boltrig/api/readiness.py:238`](../../../boltrig/api/readiness.py)
   `"if production and not self._kernel.events.shared:"`), then a bounded PING,
   then the relay's own capability probe.
   FAILURE BRANCH: `probe_failed` on the PING, `capability_failed` when the PING
   succeeded and the relay capability probe did not.
5. **Control plane.** `kernel.loader.peek(tenant, "control")`, `describe()` for
   the live verb set, per-verb `get_verb` + `get_binding`, the adapter record's
   `activated` flag, and the five collaborators
   `{store, loader, registry, admin, workflows}`
   ([`boltrig/api/readiness_control.py:47`](../../../boltrig/api/readiness_control.py)
   `"required_collaborators = {\"store\", \"loader\", \"registry\", \"admin\", \"workflows\"}"`).
   Reasons are ordered `not_registered`, `probe_failed`,
   `incomplete_registration`, `incomplete_persistence`, `invalid_bindings`,
   `inactive_adapter`, `collaborators_unavailable`.
6. **Stack tools and model gateway** (one call). The status provider snapshot is
   read under the readiness timeout; ANY exception there yields `probe_failed`
   for stack tools plus a gateway verdict derived from posture
   ([`boltrig/api/readiness.py:268`](../../../boltrig/api/readiness.py)
   `"failed = _check(\"failed\", required=True, reason=\"probe_failed\")"`).
   The required tool set is `{browser-cli}` only when the manifest declares
   automation ([`boltrig/api/readiness.py:55`](../../../boltrig/api/readiness.py)
   `"return _STACK_TOOL_IDS if needs_browser_cli(manifest) else frozenset()"`);
   with no manifest it falls back to `BOLTRIG_REQUIRE_STACK_TOOL_HEALTH` then to
   `browser_automation_wanted()`.
7. **Live stack-tool receipt**, only when tools are required, posture is ok, and
   (production or `BOLTRIG_REQUIRE_STACK_TOOL_HEALTH`). Requires `REDIS_URL` and
   a derivable receipt signing key, then reads the fleet receipt under the
   timeout. Any reason outside the admitted set
   `{missing, malformed, stale, future, degraded, unauthenticated, unavailable}`
   is coerced to `unavailable`, so no probe detail leaks
   ([`boltrig/api/readiness.py:354`](../../../boltrig/api/readiness.py)
   `"safe_reason = ("`).
8. **Model gateway.** `gateway_posture(env)` returns `enabled` only when a health
   flag or health URL is set; a configured-but-unprobed gateway returns
   `unchecked`, never `disabled`, and stays not-required
   ([`boltrig/fleet/model_gateway.py:184`](../../../boltrig/fleet/model_gateway.py)
   `"return (\"unchecked\", \"configured_but_health_check_disabled\")"`). When armed,
   the `bifrost` component must be `status == ok` AND carry
   `metadata.live_health == "ok"`.
9. **Hatchet.** Enabled by `BOLTRIG_HATCHET_HEALTH`, `BOLTRIG_REQUIRE_DURABLE`,
   or a configured `HATCHET_CLIENT_TOKEN`
   ([`boltrig/api/readiness.py:373`](../../../boltrig/api/readiness.py)
   `"is_truthy(env.get(\"BOLTRIG_HATCHET_HEALTH\"))"`). A non-durable executor or a
   missing `aio_get_engine_version` is `durable_executor_unavailable`.
10. **Codex runtime.** Release-mode posture first (`invalid_release_mode`,
    `release_mode_conflict`, `core_release_mode`), then whether Codex is
    requested at all, then the static admission posture. Development returns
    `test_only` and not required; production returns `ok` only if the posture is
    ready ([`boltrig/api/codex_readiness.py:88`](../../../boltrig/api/codex_readiness.py)
    `"ready = posture[\"status\"] == \"ready\""`).
11. **Password-reset delivery.** Required only under
    `BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY`; the projection always carries
    `provider_delivery_proven=False`
    ([`boltrig/api/readiness_dependencies.py:73`](../../../boltrig/api/readiness_dependencies.py)
    `"provider_delivery_proven=False,"`).
12. **Background jobs.** Eight optional `<job>_janitor` entries, all
    `required: False`; a read failure or timeout returns
    `attempt_evidence_unavailable` for every job rather than failing readiness
    ([`boltrig/api/background_readiness.py:43`](../../../boltrig/api/background_readiness.py)
    `"return _unavailable_checks()"`).
13. **Aggregate and cache.** `ready` iff no required check is non-`ok`; the route
    maps that to 200 or 503
    ([`boltrig/kernel/health_routes.py:66`](../../../boltrig/kernel/health_routes.py)
    `"status_code=200 if report.get(\"status\") == \"ready\" else 503,"`).

### 5.6 `/healthz`

One step: read the CACHED adapter posture and return
`{"status": "ok", "adapters": {...}}`
([`boltrig/kernel/health_routes.py:35`](../../../boltrig/kernel/health_routes.py)
`"\"status\": \"ok\","`). `health_snapshot()` never awaits adapter I/O; when the
cache is older than `REFRESH_INTERVAL_S = 30.0` it schedules ONE background
re-probe off the request path
([`boltrig/adapters/loader.py:108`](../../../boltrig/adapters/loader.py)
`"self._refresh_task = loop.create_task(self.refresh_health())"`), and each probe
in that refresh is cut off at `PROBE_TIMEOUT_S = 2.5` and recorded `down`
([`boltrig/adapters/loader.py:86`](../../../boltrig/adapters/loader.py)
`"self._health[key] = await asyncio.wait_for(adapter.health(), probe_timeout_s)"`).
FAILURE BRANCH: there is none. The top-level `status` is a literal.

### 5.7 `boltrig fleet-health`

1. No `REDIS_URL`: exit **0** printing `NOT CHECKED`, unless
   `BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT` is set, which makes it exit **1**
   ([`boltrig/api/fleet_health.py:60`](../../../boltrig/api/fleet_health.py)
   `"if env.get(_REQUIRE_ENV):"`).
2. No usable receipt signing key (absent or placeholder audit HMAC key): the same
   two-branch NOT CHECKED / required split
   ([`boltrig/api/fleet_health.py:83`](../../../boltrig/api/fleet_health.py)
   `"return 0, ("`).
3. Resolve the tenant from the manifest, falling back to the default tenant; a
   broken manifest is "the worker's problem, not ours"
   ([`boltrig/api/fleet_health.py:51`](../../../boltrig/api/fleet_health.py)
   `"a broken manifest is the worker's problem"`).
4. Read the fleet receipt with a 3.0s timeout and the configured TTL. Exit **0**
   only on `ok`; otherwise exit **1** naming the reason and the tenant
   ([`boltrig/api/fleet_health.py:98`](../../../boltrig/api/fleet_health.py)
   `"return 1, f\"fleet receipt {reason} (tenant={tenant})\""`).

### 5.8 Boot guards

Called from the composition root, twice for the audit key
([`boltrig/api/bootstrap.py:419`](../../../boltrig/api/bootstrap.py)
`"refuse_default_audit_key_in_prod()"` and
[`boltrig/api/bootstrap.py:510`](../../../boltrig/api/bootstrap.py)
`"# K-19: a default audit key in prod is fatal"`), and once for dev auth from
INSIDE the dev-auth branch of resolver selection
([`boltrig/api/auth_selection.py:112`](../../../boltrig/api/auth_selection.py)
`"refuse_dev_auth_in_prod()"`).

1. `refuse_dev_auth_in_prod`: raises `RuntimeError` if `production_signal(env)`
   is not None ([`boltrig/api/boot_guards.py:32`](../../../boltrig/api/boot_guards.py)
   `"raise RuntimeError("`). It does NOT itself test whether dev auth is on; its
   caller establishes that.
2. `refuse_default_audit_key_in_prod`: raises when a production signal is present
   AND `is_placeholder_secret(key)`
   ([`boltrig/api/boot_guards.py:58`](../../../boltrig/api/boot_guards.py)
   `"if signal is not None and is_placeholder_secret(key):"`). With NO production
   signal and a placeholder key it logs a WARNING every boot instead, because
   "nothing sets a production signal by default"
   ([`boltrig/api/boot_guards.py:71`](../../../boltrig/api/boot_guards.py)
   `"log.warning("`).

### 5.9 Emitting a Langfuse mirror event

1. The audit row is written FIRST and unconditionally
   ([`boltrig/fleet/spawn.py:490`](../../../boltrig/fleet/spawn.py)
   `"await self._kernel.audit.write(event)"`).
2. `record_spawn` builds a metadata-only payload: tenant/run/parent/workspace ids,
   capability, runtime, status, tier, depth, at most 20 skills, an allow-listed
   `model_route` subset `{provider, model, runtime, profile, tier}`, and
   token/cost usage. No prompt, no output, no URL, no key
   ([`boltrig/observability/langfuse_sink.py:22`](../../../boltrig/observability/langfuse_sink.py)
   `"_ROUTE_KEYS = {\"provider\", \"model\", \"runtime\", \"profile\", \"tier\"}"`).
3. The emit is bounded at 0.25s and every exception increments `failure_count`
   and returns None
   ([`boltrig/observability/langfuse_sink.py:183`](../../../boltrig/observability/langfuse_sink.py)
   `"await asyncio.wait_for(self._emit(payload), timeout=self.timeout_s)"`).
4. The caller ALSO wraps the whole call in a bare `except Exception: pass`
   ([`boltrig/fleet/spawn.py:504`](../../../boltrig/fleet/spawn.py)
   `"except Exception:"`), so a sink that raises outside its own guard still
   cannot fail a spawn.

## 6. Data

### 6.1 `audit_log`

[`boltrig/store/schema.sql:542`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS audit_log ("`. Columns: `id BIGSERIAL PK`,
`tenant_id`, `seq BIGINT`, `ts TIMESTAMPTZ`, `run_id`, `parent_run_id`, `actor`,
`actor_tier`, `depth INT`, `action_type`, `noun`, `verb`, `target_adapter`,
`on_behalf_of`, `status`, `latency_ms INT`, `tokens_used INT`,
`cost_micros BIGINT`, `skills_loaded JSONB`, `detail JSONB`, then the five
nullable enrichment columns `ip_address` / `user_agent` / `resource` /
`resource_id` / `workspace_id`, then `prev_hash` and `hash NOT NULL`.
Constraint: `UNIQUE (tenant_id, seq)`.
Indexes: `audit_ts_idx (tenant_id, ts)`, `audit_run_idx (run_id)`,
`audit_ws_idx (tenant_id, workspace_id)`, `audit_actor_idx (tenant_id, actor)`,
`audit_actor_page_idx (tenant_id, actor, seq DESC)`,
`audit_behalf_page_idx (tenant_id, on_behalf_of, seq DESC)`
([`boltrig/store/schema.sql:576`](../../../boltrig/store/schema.sql)
`"CREATE INDEX IF NOT EXISTS audit_ts_idx"`).

Retention: NONE. The retention janitor hard-deletes closed conversations and
"never touches the tamper-evident audit log (audit is exempt)"
([`tests/invariants.yaml:1349`](../../../tests/invariants.yaml)
`"never touches the tamper-evident audit log"`). Encryption at rest is the
deployment's, not the writer's; the writer's protection is the scrub plus the
HMAC chain.

Read shapes:
- `audit_query(tenant, run_id=None, limit=200)` is a TAIL read:
  `ORDER BY seq DESC LIMIT n`, returned reversed to ascending
  ([`boltrig/store/postgres.py:694`](../../../boltrig/store/postgres.py)
  `"ORDER BY seq DESC LIMIT $2"`).
- `audit_scan(tenant, after_seq, limit)` is the ASCENDING verification seam
  ([`boltrig/store/postgres.py:706`](../../../boltrig/store/postgres.py)
  `"WHERE tenant_id=$1 AND seq>$2 ORDER BY seq LIMIT $3"`).
- `audit_query_scoped` and `audit_search_page` push the department/workspace
  predicate into the query under a clamped page
  ([`boltrig/store/audit_read_contract.py:16`](../../../boltrig/store/audit_read_contract.py)
  `"MAX_AUDIT_SEARCH_PAGE = 500"`; offset capped at 10,000).

The distinction matters and is stated in the tree: view contracts use
`audit_query`; "integrity verification deliberately continues to use
`audit_scan` / `security_scan` over each complete hash chain"
([`boltrig/store/audit_read_contract.py:3`](../../../boltrig/store/audit_read_contract.py)
`"Integrity verification deliberately continues"`).

### 6.2 `audit_outbox`

[`boltrig/store/schema.sql:590`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS audit_outbox ("`: `id`, `tenant_id`,
`payload JSONB`, `append_error`, `attempts INT DEFAULT 0`,
`next_retry_at TIMESTAMPTZ DEFAULT now()`, `created_at`. One index on
`next_retry_at`. The payload carries the already-scrubbed event with chain fields
nulled; the janitor rehydrates with `audit_event_from_payload`, which drops
unknown keys and ignores chain fields on purpose
([`boltrig/kernel/audit.py:299`](../../../boltrig/kernel/audit.py)
`"Chain fields are ignored on purpose"`).

### 6.3 `security_log`

A SEPARATE hash-chained stream for signals, same chaining shape, kept apart "so
signals never dilute the action trail"
([`boltrig/store/schema.sql:605`](../../../boltrig/store/schema.sql)
`"signals never dilute the action trail"`). Event types are a closed enum
including `login_failure`, `rate_limit_trip`, `permission_denied`,
`mcp_auth_failure`, `host_boundary_credential`
([`boltrig/models/audit.py:33`](../../../boltrig/models/audit.py)
`"LOGIN_FAILURE = \"login_failure\""`).

### 6.4 `background_job_receipts`

[`boltrig/store/schema.sql:857`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS background_job_receipts ("`. Primary key
`(tenant_id, job_name, process_instance_identity)`. The SQL restates every model
invariant as a CHECK: the eight-name job set, the
`^bjp_[a-f0-9]{24}$` identity regex, the 1..604800 interval, the 0..1000000 item
count, the fixed `receipt_kind`, the timestamp-ordering constraint
`background_job_timestamp_shape`, and the outcome-shape constraint
`background_job_outcome_shape`
([`boltrig/store/schema.sql:892`](../../../boltrig/store/schema.sql)
`"CONSTRAINT background_job_timestamp_shape CHECK ("`). Index
`(tenant_id, job_name, last_attempt_at DESC)`.

Retention is a hard per-job cap: `BACKGROUND_JOB_RECEIPTS_PER_JOB = 4` rows per
job, pruned on every write
([`boltrig/store/background_jobs.py:326`](../../../boltrig/store/background_jobs.py)
`"BACKGROUND_JOB_RECEIPTS_PER_JOB,"`), and reads are capped at
`8 * 4 = 32` rows
([`boltrig/models/background_jobs.py:47`](../../../boltrig/models/background_jobs.py)
`"BACKGROUND_JOB_MAX_RETURNED_RECEIPTS = ("`).

The readiness read binds the tenant to the connection explicitly, because
"`/readyz` has no caller principal by design"
([`boltrig/store/background_jobs.py:333`](../../../boltrig/store/background_jobs.py)
`"/readyz has no caller principal by design"`), and it skips rows whose job name
this build does not know rather than failing the whole read
([`boltrig/store/background_jobs.py:348`](../../../boltrig/store/background_jobs.py)
`"return _receipts_skipping_unknown(rows)"`).

### 6.5 `memory_projection_statuses`

[`boltrig/store/schema.sql:2088`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS memory_projection_statuses ("`, with CHECK
constraints on enqueue attempts, operation attempts and failure code, and an
index on `(tenant_id, fact_id, projection_id)`. The projection reads at most 51
rows and returns at most 50 with an explicit `truncated` flag
([`boltrig/observability/memory_projection_delivery.py:12`](../../../boltrig/observability/memory_projection_delivery.py)
`"_READ_LIMIT = MAX_MEMORY_PROJECTION_RECEIPTS + 1"`).

Identifiers in the receipt are opaque per-tenant digests, never the row id:
`sha256(f"{tenant_id}:{value}")[:20]` prefixed `mpr_` / `mp_`
([`boltrig/observability/memory_projection_delivery.py:18`](../../../boltrig/observability/memory_projection_delivery.py)
`"digest = hashlib.sha256(f\"{tenant_id}:{value}\".encode()).hexdigest()[:20]"`).

### 6.6 The backup freshness marker

Not a table: one file whose entire content is an ASCII epoch integer, at most 32
bytes, read with `marker.read(33)` so an oversized file is detectable
([`boltrig/observability/backup_status.py:39`](../../../boltrig/observability/backup_status.py)
`"raw = marker.read(33)"`). States: `unconfigured`, `configuration_invalid`,
`never_observed`, `unavailable` (OSError), `invalid_marker` (too long,
non-ascii, non-digit, or in the future), `fresh`, `stale`.

### 6.7 Migrations

The readiness head constant is the only migration-coupled datum in this area and
it is graph-checked against Alembic by
`tests/integration/test_migration_parity.py::test_packaged_readiness_head_matches_alembic_head`
([`tests/invariants.yaml:2001`](../../../tests/invariants.yaml)
`"test_packaged_readiness_head_matches_alembic_head"`).

## 7. Configuration surface

Every variable below changes this subsystem's behaviour. "Breaks" states the
observed consequence of a wrong value, from the code.

### 7.1 Records and redaction

| var | default | effect | wrong value breaks |
| --- | --- | --- | --- |
| `BOLTRIG_AUDIT_HMAC_KEY` | in-source `dev-insecure-audit-key` ([`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `"\"dev-insecure-audit-key\""`) | keys the audit and security chains and derives the fleet receipt signing key | a placeholder under a production signal is a FATAL boot refusal; without a signal it is a per-boot WARNING and a forgeable chain; changing it without recording an epoch makes every prior row fail verification |
| `BOLTRIG_AUDIT_HMAC_RETIRED` | unset | `"<seq>:<key>[,<seq>:<key>]"` epochs used for VERIFICATION only ([`boltrig/kernel/audit.py:49`](../../../boltrig/kernel/audit.py) `"BOLTRIG_AUDIT_HMAC_RETIRED=\"<retired_at_seq>:<key>"`) | a malformed entry is silently ignored and its rows then fail under the live key; a MISSING boundary after a rotation makes the whole chain report broken |
| `BOLTRIG_LOG_LEVEL` | `INFO` ([`boltrig/api/logging_config.py:32`](../../../boltrig/api/logging_config.py) `"DEFAULT_LEVEL = \"INFO\""`) | root log level for every boltrig process | an unparseable name falls back to INFO rather than silencing; the variable is documented NOWHERE outside its own module (bounded: `rg -n "BOLTRIG_LOG_LEVEL" .` over the pinned tree returns only `boltrig/api/logging_config.py` and `tests/unit/test_logging_is_configured.py`) |
| `BOLTRIG_LANGFUSE_ENABLED` / `LANGFUSE_ENABLED` | unset (disabled) | arms the mirror ([`boltrig/observability/langfuse_sink.py:247`](../../../boltrig/observability/langfuse_sink.py) `"env.get(\"BOLTRIG_LANGFUSE_ENABLED\") or env.get(\"LANGFUSE_ENABLED\")"`) | falsy leaves a no-op sink reporting `disabled_by_config` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | unset | required pair when enabled | either missing yields a no-op sink with reason `missing_keys`, never an error |
| `LANGFUSE_HOST` | unset | optional client host | absent means the SDK default |

### 7.2 Doctor

| var | default | effect |
| --- | --- | --- |
| `BOLTRIG_PRODUCTION`, `ENV`, `BOLTRIG_ENV`, `APP_ENV` | unset | promote warnings to deploy-blocking failures |
| `DATABASE_URL`, `POSTGRES_PASSWORD`, `REDIS_URL`, `SECRET_STORE` | unset / `env` | datastore checks; `SECRET_STORE=env` warns under production |
| `BOLTRIG_DEV_AUTH`, `OIDC_ISSUER`/`OIDC_AUDIENCE`/`OIDC_JWKS_URI`, `CF_ACCESS_TEAM_DOMAIN`/`CF_ACCESS_AUD`, `CF_ACCESS_DEFAULT_ROLE`, `BOLTRIG_AUTH_MODE`, `BOLTRIG_SESSION_COOKIE_SECURE` | unset | auth-posture checks; only an EXPLICIT falsy cookie-secure opt-out is flagged ([`boltrig/api/doctor.py:310`](../../../boltrig/api/doctor.py) `"if cookie_secure is not None and not is_truthy(cookie_secure):"`) |
| `BOLTRIG_ALLOWED_HOSTS`, `BOLTRIG_CORS_ORIGINS`, `BOLTRIG_MAX_BODY_BYTES`, `BOLTRIG_DOMAIN`, `BOLTRIG_RELEASE_MODE` | unset | edge checks; `BOLTRIG_MAX_BODY_BYTES` unset emits NO check at all |
| `AIR_GAPPED`, `BOLTRIG_MODEL_GATEWAY_URL` | unset | model-posture checks |
| `BACKUP_REMOTE`, `BACKUP_PASSPHRASE`, `BACKUP_DATABASES`, `POSTGRES_DB`, `PGDATABASE`, `HATCHET_DATABASE_URL`, `HATCHET_DATABASE_NAME`, `HATCHET_CLIENT_TOKEN`, `BOLTRIG_REQUIRE_DURABLE` | unset | backup storage and database-coverage checks |
| `BOLTRIG_BROWSER_CLI_HOME`, `BOLTRIG_BROWSER_CLI_BIN`, `PATH` | unset | stack-state checks; `PATH` is consulted by `shutil.which` ([`boltrig/api/doctor_stack_state.py:143`](../../../boltrig/api/doctor_stack_state.py) `"return shutil.which(command, path=env.get"`) |
| `BOLTRIG_CODEX_TRUSTED` | unset | with `BOLTRIG_RELEASE_MODE=core` this is a `conflict` FAIL |

### 7.3 Readiness, liveness and boot

| var | default | effect | wrong value breaks |
| --- | --- | --- | --- |
| `BOLTRIG_READINESS_TIMEOUT` | `0.75`, clamped 0.05..10.0 ([`boltrig/api/readiness.py:86`](../../../boltrig/api/readiness.py) `"float(env.get(\"BOLTRIG_READINESS_TIMEOUT\", \"0.75\"))"`) | per-probe bound | non-finite or unparseable silently falls back to 0.75; too low makes a healthy slow dependency read `probe_failed` |
| `BOLTRIG_READINESS_CACHE_TTL` | `1.0`, clamped 0.1..5.0 | snapshot reuse window | too high delays an orchestrator seeing a real outage by up to 5s |
| `DATABASE_URL` | unset | makes postgres+migration required even outside production | |
| `REDIS_URL` | unset | makes redis required; also gates the live stack-tool receipt and `fleet-health` | absent in production is `not_configured` FAIL |
| `BOLTRIG_REQUIRE_STACK_TOOL_HEALTH` | unset | forces the live browser receipt outside production, and (with no manifest) forces the tool to be required at all | |
| `BOLTRIG_STACK_TOOL_RECEIPT_TTL` | 30 (per `.env.example:251`) | freshness bound for the receipt | |
| `BOLTRIG_MODEL_GATEWAY_URL` | unset | puts the gateway in the request path; alone it yields `unchecked`, not `disabled` | |
| `BOLTRIG_MODEL_GATEWAY_HEALTH` / `BOLTRIG_MODEL_GATEWAY_HEALTH_URL` | unset | arms the gateway probe and makes it REQUIRED | an explicit `"0"` deliberately does not arm it ([`boltrig/fleet/model_gateway.py:156`](../../../boltrig/fleet/model_gateway.py) `"\"non-empty\" predicate because manifest export deliberately writes"`) |
| `BOLTRIG_HATCHET_HEALTH`, `BOLTRIG_REQUIRE_DURABLE`, `HATCHET_CLIENT_TOKEN` | unset | any one arms the required Hatchet probe | a configured-but-unreachable engine fails readiness closed rather than silently dropping to the local executor |
| `BOLTRIG_REQUIRE_PASSWORD_RESET_DELIVERY` | unset | promotes password-reset delivery to required | |
| `BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT` | unset | turns both `fleet-health` NOT CHECKED branches into exit 1 | |
| `BOLTRIG_TENANT_ID` | `default` | tenant `audit-verify` re-derives ([`boltrig/api/audit_verify.py:103`](../../../boltrig/api/audit_verify.py) `"default=os.environ.get(\"BOLTRIG_TENANT_ID\", \"default\"),"`) | a wrong tenant verifies an empty chain and exits 0 |
| `BOLTRIG_BACKUP_HEALTH_FILE`, `BACKUP_INTERVAL`, `BACKUP_HEALTH_GRACE` | unset / 86400 / 3600 | backup freshness projection ([`boltrig/kernel/platform_routes/backup_status.py:24`](../../../boltrig/kernel/platform_routes/backup_status.py) `"interval_seconds=_integer(\"BACKUP_INTERVAL\", 86_400),"`) | a non-integer becomes `-1`, which the projection classifies `configuration_invalid` |

## 8. PROCESS

This is the half of the spec that says what a human or an agent DOES. Every
procedure below is grounded in a Makefile target, a script, a compose block or a
runbook in the pinned tree.

### 8.1 Pre-cutover: run the doctor, and run it in the right place

```
make doctor                    # ARGS="--production" for deploy-blocking posture
```
[`Makefile:477`](../../../Makefile) `"doctor: ## Static readiness checks"`, which
expands to
`python -m boltrig.api.cli doctor --env-file .env --manifest manifest.yaml`
([`Makefile:478`](../../../Makefile) `"cli doctor --env-file .env --manifest"`).

The runbook step is "`boltrig doctor --production` reports zero" failures
([`docs/PROD-CUTOVER-RUNBOOK.md:86`](../../../docs/PROD-CUTOVER-RUNBOOK.md)
`"boltrig doctor --production` reports zero"`).

CRITICAL PROCESS CAVEAT, stated in the deployment guide: a host-side doctor run
describes THAT HOST, not the release image, because the stack-tool checks resolve
binaries through the local `PATH`. The release-image run is the evidence:
[`docs/DEPLOYMENT.md:654`](../../../docs/DEPLOYMENT.md)
`"host-side `boltrig doctor --production` remains a useful diagnostic, but its CLI"`.
The image-context run is `make release-validate`, which builds an ephemeral image
from the signed kernel/fleet image and runs
`python -m boltrig.api.cli doctor --env-file /dev/stdin --manifest <mounted> --production`
inside it, with the operator env piped on stdin so it never lands in a layer
([`scripts/validate_release_runtime.py:199`](../../../scripts/validate_release_runtime.py)
`"\"doctor\","`).

Reading the output: `format_report` prints `[FAIL]`/`[WARN]`/`[OK ]` per check
plus an optional `hint:` line, ending with a `Summary: N fail, M warn, T checks`
line ([`boltrig/api/doctor.py:140`](../../../boltrig/api/doctor.py)
`"f\"Summary: {failed} fail, {warned} warn"`). `--json` emits the same content
sorted and indented for a gate to parse. ONLY `fail` moves the exit code.

**What a red doctor result means operationally**, by check family:

| check | red means | operator action |
| --- | --- | --- |
| `database_url`, `postgres_password`, `redis_url` | the deployment has no durable state or no shared counters configured | fill the value before starting anything; these are not runtime-recoverable |
| `audit_hmac_key` | the audit chain would be keyed by a public constant or a short key | mint a key BEFORE first boot; minting it later costs verification of every prior row unless an epoch is recorded |
| `dev_auth` | a header-trusting auth bypass is reachable in production | unset `BOLTRIG_DEV_AUTH`; boot will refuse anyway (5.8) |
| `auth_mode` | nothing authenticates; the kernel will deny every request | configure OIDC, CF Access, or session auth |
| `allowed_hosts`, `cors_origins`, `desktop_cors_origin` | host header or browser origin is unbounded, or a packaged desktop build cannot talk to its own kernel | set explicit values; never `*` |
| `manifest` | the tenant manifest is absent or unloadable; EVERY manifest-gated check silently did not run | fix the manifest and re-run; a green run with a warn on `manifest` proves much less than it looks |
| `retired_runtime_*` | a provisioned tenant still asks for a runtime this image cannot serve, so its capabilities degrade | delete the `runtimes.<kind>` block from the tenant manifest |
| `sensitive_endpoint`, `memory_residency` | sensitive or memory traffic is routed somewhere that is not a local sensitive endpoint | a data-residency stop-ship |
| `backup_*` | the recovery set does not cover the databases that exist, or is unencrypted / local-only | fix before cutover; in-flight durable runs cannot be recovered without the Hatchet database |
| `browser_cli_stack_home`, `browser_cli_stack_cli` | the stack would use an operator's personal browser state or a workstation binary | re-run inside the release image (`make release-validate`) before concluding anything |
| `codex_runtime` | a Codex runtime is requested under a production signal while its admission gates are closed | do not enable it; see 9.4 |

### 8.2 Bring-up and roll: readiness is the gate, not `docker ps`

The kernel container healthcheck consults READINESS, not liveness
([`docker-compose.yml:213`](../../../docker-compose.yml)
`"urlopen('http://localhost:8000/readyz')"`), and the compose comment records
exactly why and what it was rehearsed against: forcing the schema head to 0037
made the container UNHEALTHY while `/healthz` kept answering 200
([`docker-compose.yml:196`](../../../docker-compose.yml)
`"schema head forced to 0037 -> health UNHEALTHY, while /healthz kept"`).
`start_period` is 60s because readiness waits on Postgres, Redis, the control
plane and the Hatchet probe.

The fleet worker, which serves no HTTP, uses
`python -m boltrig.api.cli fleet-health`
([`docker-compose.yml:320`](../../../docker-compose.yml)
`"python -m boltrig.api.cli fleet-health || exit 1"`).

After a roll, the finishing procedure is `scripts/verify-deployment.sh`:
container running, then `/readyz` READY from INSIDE the container, then an
assertion that named `module:attribute` symbols exist in the running image.
"A roll is not finished when the container is up"
([`scripts/verify-deployment.sh:12`](../../../scripts/verify-deployment.sh)
`"The rule this encodes: a roll is not finished when the container is up."`).
Its readiness step prints the names of every non-`ok`, non-`disabled` check from
the 503 body, which is the fastest triage available
([`scripts/verify-deployment.sh:65`](../../../scripts/verify-deployment.sh)
`"bad = [k for k, v in"`).

### 8.3 Diagnosing a 503

Read the `checks` object. The reason codes are deliberately coarse and carry no
deployment detail, so the mapping from reason to action is the operator's manual:

| check.reason | what to look at |
| --- | --- |
| `not_configured` | the corresponding env var is empty in the RUNNING container, not in your `.env` |
| `probe_failed` | the dependency was reachable-ish but the bounded probe did not complete inside `BOLTRIG_READINESS_TIMEOUT` |
| `wrong_store` | the process is not running on the Postgres store |
| `wrong_backend` | production with a process-local event relay: `REDIS_URL` is not reaching the relay factory |
| `head_mismatch` | the applied Alembic head is not `EXPECTED_ALEMBIC_HEAD`, or more than one head is applied. This is the 40-minute outage class |
| `capability_failed` | Redis answered PING but the relay's stream/transaction capabilities did not verify |
| `incomplete_registration` / `incomplete_persistence` / `invalid_bindings` / `inactive_adapter` / `collaborators_unavailable` | the control adapter is not fully wired; compare `registered` / `persisted` / `expected` in the same object |
| `posture_failed` | a required stack tool is absent from the status snapshot or not `ok` |
| `fleet_receipt_missing` / `_stale` / `_unauthenticated` / `_degraded` / `_unavailable` | the fleet worker's heartbeat is not reaching this kernel, or is signed with a different key |
| `fleet_receipt_not_configured` / `fleet_receipt_auth_not_configured` | `REDIS_URL` or the audit HMAC key is missing on the KERNEL side |
| `durable_executor_unavailable` | Hatchet was armed but no durable executor with `aio_get_engine_version` is composed |
| `release_mode_conflict` / `invalid_release_mode` | `BOLTRIG_RELEASE_MODE` is not exactly `core` or `full`, or `core` coexists with `BOLTRIG_CODEX_TRUSTED` |

### 8.4 Verifying the audit chain on a schedule

```
boltrig audit-verify [--tenant T] [--from-seq N]
```
Exit 0 verifies, 1 does not, 2 could not look. Exit 2 is deliberately not 0
([`boltrig/api/audit_verify.py:20`](../../../boltrig/api/audit_verify.py)
`"Exit 2 is deliberately NOT 0."`). The subcommand exists because
"until 2026-07-30 NOTHING READ IT", and a chain had been failing for six days
unnoticed ([`boltrig/api/audit_verify.py:5`](../../../boltrig/api/audit_verify.py)
`"until 2026-07-30 NOTHING READ IT"`).

Recovery procedure after an unrepairable break: use `--from-seq N` seeded from
row `N-1` so the rows written since the break can still speak for themselves; the
command PRINTS the skipped range every time, so a segment verification cannot be
mistaken for a whole-chain one
([`boltrig/kernel/audit.py:244`](../../../boltrig/kernel/audit.py)
`"left rows 368-405 unverifiable for good"`).

Rotation procedure implied by the code: record the OLD key in
`BOLTRIG_AUDIT_HMAC_RETIRED` as `<retired_at_seq>:<old_key>` BEFORE putting the
new key in `BOLTRIG_AUDIT_HMAC_KEY`, then restart (the write-side key is bound at
import). Skipping the epoch is what makes a sound chain report broken forever.

The authenticated equivalent is `GET /v1/audit/verify`, author-or-admin gated,
which reports `chain_intact`, `security_chain_intact` and `anchor_intact`
separately plus a combined `intact`
([`boltrig/kernel/platform_routes/observability.py:142`](../../../boltrig/kernel/platform_routes/observability.py)
`"\"intact\": bool(chain_ok and sec_ok and anchor_ok),"`).

### 8.5 The gates that keep these claims load-bearing

| target | what it forbids | file |
| --- | --- | --- |
| `make health-claims` | any first-party service whose healthcheck cannot go red for a real outage | [`Makefile:203`](../../../Makefile) `"health-claims: ## No service may report healthy while unable to serve"` |
| `make no-vacuous-greens` | any gate that reports a pass over a tree it never read | [`Makefile:199`](../../../Makefile) `"no-vacuous-greens: ## No gate reports a pass over a tree it never read"` |
| `make doctor-fixture` | the secure production-doctor fixture developing a failure | [`Makefile:340`](../../../Makefile) `"doctor-fixture: ## Prove the secure production-doctor fixture has no failures"` |
| `make migration-parity` | `EXPECTED_ALEMBIC_HEAD` drifting from the Alembic graph | [`Makefile:343`](../../../Makefile) `"migration-parity: ## Compare Alembic head with schema.sql"` |
| `make invariants` | a test claiming an invariant id the catalogue does not carry | (part of `python-quality`, [`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure"`) |

`check_health_claims.py` derives both halves rather than listing them: it parses
route registrations out of the source each service actually builds, so deleting
`/readyz` changes the verdict on the next run
([`scripts/check_health_claims.py:42`](../../../scripts/check_health_claims.py)
`"Both halves are DERIVED."`). For a healthcheck that runs a repo CLI subcommand
it resolves the subcommand through the CLI's dispatch and requires the module
behind it to read the same evidence the readiness ROUTE HANDLER reads
([`scripts/check_health_claims.py:31`](../../../scripts/check_health_claims.py)
`"resolve that subcommand through the CLI's dispatch"`). The waiver file is
EMPTY ([`docs/refactoring/health-claim-exemptions.json:26`](../../../docs/refactoring/health-claim-exemptions.json)
`"\"exemptions\": {}"`), and the gate explicitly declares what it does NOT check:
whether the readiness endpoint is honest, and whether the command exits non-zero
on bad evidence
([`scripts/check_health_claims.py:58`](../../../scripts/check_health_claims.py)
`"Structure can show a probe is WIRED TO the evidence"`).

### 8.6 Operating the optional observability mirror

Langfuse is off unless `BOLTRIG_LANGFUSE_ENABLED` is truthy AND both keys are
present. There is no error path: a misconfiguration yields a no-op sink whose
REASON is visible at `GET /v1/platform/status` under `langfuse_delivery.reason`
(`disabled_by_config`, `missing_keys`, `package_unavailable`,
`client_initialization_failed`). Note before reading those counters: they are
process-local to ONE api spawner
([`boltrig/observability/langfuse_status.py:36`](../../../boltrig/observability/langfuse_status.py)
`"api_spawner_only_not_replica_inventory"`), and `delivery_lag` is hard-wired
`"unavailable"`. This surface answers "did this replica try", never "did the sink
receive".

## 9. Failure modes and fail-open / fail-closed posture

### 9.1 Fail-CLOSED (proven from the code)

| guard | closes how |
| --- | --- |
| `/readyz` aggregate | any required check that is not exactly `ok` yields 503 ([`boltrig/api/readiness.py:202`](../../../boltrig/api/readiness.py) `"ready = all(not item[\"required\"]"`) |
| status-provider exception | stack tools become `failed/required` rather than absent ([`boltrig/api/readiness.py:268`](../../../boltrig/api/readiness.py) `"failed = _check(\"failed\", required=True, reason=\"probe_failed\")"`) |
| control-plane probe exception | `probe_failed`, required ([`boltrig/api/readiness_control.py:22`](../../../boltrig/api/readiness_control.py) `"return {\"status\": \"failed\", \"required\": True, \"reason\": \"probe_failed\"}"`) |
| fleet receipt with an unrecognised reason | coerced to `unavailable` and still a failure |
| production with a non-shared event relay | immediate `wrong_backend` failure before any probe |
| dev auth under a production signal | boot `RuntimeError` |
| placeholder audit key under a production signal | boot `RuntimeError` |
| Codex under a production signal with closed gates | readiness `failed/required` and doctor `fail` |
| `audit-verify` with no DSN or an unreachable store | exit 2, never 0 |
| `audit-verify` segment with no seeding row | exit 2, never a segment verified against a None seed |
| a malformed retired-key epoch | ignored, so the row falls through to the live key and fails honestly |
| a marker file over 32 bytes or non-numeric | `invalid_marker`, never parsed |

### 9.2 Fail-OPEN, deliberately and declared

| guard | opens how | declared where |
| --- | --- | --- |
| `/healthz` | always 200 with `status: ok` regardless of adapter posture | FR-OPS-05: it is a liveness probe and must not flap on a slow backend |
| `boltrig fleet-health` with no `REDIS_URL` or an unusable key | exit 0 printing `NOT CHECKED` | [`boltrig/api/fleet_health.py:26`](../../../boltrig/api/fleet_health.py) `"it is the one case where a green here means \"could not look\""` |
| background-job checks | `required: False` always; they can never hold traffic | [`boltrig/observability/background_jobs.py:122`](../../../boltrig/observability/background_jobs.py) `"It never gates traffic and never"` |
| background-receipt read failure | every job reports `unknown` with `attempt_evidence_unavailable` | [`boltrig/api/background_readiness.py:36`](../../../boltrig/api/background_readiness.py) `"without making traffic depend on it"` |
| `record_background_attempt` write failure | logged at WARNING and swallowed, "can never change the janitor outcome" | [`boltrig/observability/background_jobs.py:40`](../../../boltrig/observability/background_jobs.py) `"Best-effort evidence write that can never change"` |
| Langfuse emit failure or timeout | counted and swallowed, twice over | FR-OBS-13 |
| audit append failure | deferred to the outbox; the action is NOT rolled back | [`boltrig/kernel/audit.py:337`](../../../boltrig/kernel/audit.py) `"an append fault is"` |
| `verify_latest` with no anchor | `(True, None)`, so `/v1/audit/verify` reports `anchor_intact: true` over a tenant that has never been anchored | [`boltrig/kernel/security_events.py:278`](../../../boltrig/kernel/security_events.py) `"return (True, None)"` |
| a placeholder audit key with NO production signal | WARNING every boot, no refusal | [`boltrig/api/boot_guards.py:64`](../../../boltrig/api/boot_guards.py) `"if is_placeholder_secret(key):"` |
| `network_policy` adapter probe exception | `web_fetch` becomes None and `status` becomes `unavailable`, never an error | [`boltrig/observability/network_policy.py:64`](../../../boltrig/observability/network_policy.py) `"except Exception:"` |
| `memory_projection_delivery` store exception | `status: unavailable` with an empty receipt list | [`boltrig/observability/memory_projection_delivery.py:140`](../../../boltrig/observability/memory_projection_delivery.py) `"rows = []"` |
| `background_job_platform_fields` store exception | `evidence_status: unavailable`, empty list | [`boltrig/observability/background_jobs.py:175`](../../../boltrig/observability/background_jobs.py) `"except Exception:"` |
| doctor `hatchet` | can only ever be `ok` or `warn`; never `fail` | [`boltrig/api/doctor.py:509`](../../../boltrig/api/doctor.py) `"Hatchet live engine wiring is absent; local fallback only."` |
| doctor with no `BOLTRIG_MAX_BODY_BYTES` | emits no `body_cap` check at all | [`boltrig/api/doctor_edge.py:54`](../../../boltrig/api/doctor_edge.py) `"max_body = env.get(\"BOLTRIG_MAX_BODY_BYTES\")"` |

### 9.3 Is any health check vacuous?

Three candidates were examined against the definition "cannot fail, or reports on
a different referent than the one it names".

**`/healthz` cannot fail, and this is intended.** Its top-level `status` is the
literal `"ok"`
([`boltrig/kernel/health_routes.py:35`](../../../boltrig/kernel/health_routes.py)
`"\"status\": \"ok\","`). Every adapter can be `down` and the response is still 200
`ok`; the adapter posture rides alongside as data. That is FR-OPS-05's design
(a liveness probe must not flap a live kernel), and the repository has already
removed its only decision-bearing consumer: no compose or deploy file points a
healthcheck at it. Bounded: `rg -n "healthz" docker-compose.yml deploy/ scripts/`
on the pinned tree finds it only in prose comments, a Caddy route
([`deploy/Caddyfile.example:31`](../../../deploy/Caddyfile.example)
`"handle /healthz {"`), and two shell wait-loops
([`scripts/dev-up.sh:21`](../../../scripts/dev-up.sh)
`"curl -fsS -m3 http://127.0.0.1:8000/healthz"`). VERDICT: not a defect, but it
is a green that means only "the process answered", and `scripts/dev-up.sh` and
`scripts/activate-sensing.sh` both treat it as a bring-up gate, which is the
weaker claim.

**`boltrig fleet-health` can return a green that means "could not look".** With
no `REDIS_URL` or a placeholder audit key it exits 0 and PRINTS `NOT CHECKED`
([`boltrig/api/fleet_health.py:63`](../../../boltrig/api/fleet_health.py)
`"NOT CHECKED: no REDIS_URL, so the heartbeat is disabled and no receipt "`).
Docker records only the exit code, so a container healthcheck reading that green
learns nothing. This is the honest answer to an impossible question, it is
declared in the module docstring, an env var (`BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT`)
converts it to a failure, and both branches are bound tests under FR-OPS-05.
VERDICT: declared and bounded, not vacuous, but see RISK 12-R1.

**The Codex admission check cannot PASS.** `codex_release_posture()` computes
`ready = runtime_ready and config_ready and not blockers`
([`boltrig/observability/codex_admission.py:33`](../../../boltrig/observability/codex_admission.py)
`"ready = runtime_ready and config_ready and not blockers"`) over three values
that are constants in this build: `CodexAgentRuntime.production_ready = False`
([`boltrig/fleet/infrastructure/codex_agent_runtime.py:61`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
`"production_ready = False"`), `CODEX_RUNTIME_CONFIG_PRODUCTION_READY = False`
([`boltrig/fleet/infrastructure/codex_runtime_config.py:42`](../../../boltrig/fleet/infrastructure/codex_runtime_config.py)
`"CODEX_RUNTIME_CONFIG_PRODUCTION_READY = False"`), and a seven-element
`QUARANTINED_PREFLIGHT_BLOCKERS`
([`boltrig/fleet/infrastructure/codex_preflight_receipt.py:21`](../../../boltrig/fleet/infrastructure/codex_preflight_receipt.py)
`"QUARANTINED_PREFLIGHT_BLOCKERS = ("`). So the doctor branch
`"Codex production admission is enabled."`
([`boltrig/api/doctor_codex.py:51`](../../../boltrig/api/doctor_codex.py)
`"return (\"ok\", \"codex_runtime\", \"Codex production admission is enabled.\", \"\")"`)
and the readiness `ok` branch are both UNREACHABLE at this commit. This is
deliberate and the code says so in the same breath: "A two-line constant flip
must never turn a quarantined receipt into a production attestation"
([`boltrig/observability/codex_admission.py:30`](../../../boltrig/observability/codex_admission.py)
`"A two-line constant flip must never turn a quarantined receipt"`).
VERDICT: a gate that cannot currently pass, by design, with the design recorded.

**One check that reports on a referent adjacent to the one it names.** The
readiness `stack_tools` entry is `required: True` unconditionally, but when the
required tool set is empty the membership test and the `all(...)` over an empty
set are both vacuously true, so the check reports `ok` with `expected: 0,
registered: 0` ([`boltrig/api/readiness.py:297`](../../../boltrig/api/readiness.py)
`"expected=len(required_tools),"`). It is not fully unfalsifiable, because a
status-provider exception still fails it, and the `expected: 0` field names what
it actually measured. Recorded as an observation, not a finding.

### 9.4 The doctor's own blind spots, from its own code

- With no manifest, seven check families never run and the ONLY trace is one
  `warn`. The exit code is unchanged, so a CI run that lost `manifest.yaml` is a
  materially weaker run that looks the same. That is not hypothetical: the
  manifest the CLI defaults to is gitignored and absent in CI, which the doctor
  test file records as the cause of five StopIteration errors
  ([`tests/unit/test_doctor.py:14`](../../../tests/unit/test_doctor.py)
  `"gitignored"`).
- `_check_durable_engine` accepts a Hatchet DSN merely for HAVING a password
  ([`boltrig/api/doctor.py:516`](../../../boltrig/api/doctor.py)
  `"return bool(urlsplit(dsn).password"`), which is a
  proxy for "wiring is present", not for "the engine is reachable".
- No doctor check reads `BOLTRIG_AUDIT_HMAC_RETIRED`, so a rotation performed
  without recording an epoch passes the doctor cleanly and only surfaces at the
  next `audit-verify`. Bounded: `rg -n "HMAC_RETIRED" boltrig/api/` returns no
  hits on the pinned tree.

## 10. What is proven

### 10.1 Invariants that bind this area

| id | what it binds here | catalogue line |
| --- | --- | --- |
| `SEC-16` | every action, allowed or denied, is audited, hash-chained and append-only | [`tests/invariants.yaml:930`](../../../tests/invariants.yaml) `"SEC-16:"` |
| `K-19` | the chain is tamper-evident, and a default audit key under a prod signal is refused at worker boot | [`tests/invariants.yaml:803`](../../../tests/invariants.yaml) `"K-19:"` |
| `K-20` | the writer scrubs secrets and identity out of `detail` | [`tests/invariants.yaml:808`](../../../tests/invariants.yaml) `"K-20:"` |
| `SEC-168` | verification re-derives the ENTIRE chain, never a tail window | [`tests/invariants.yaml:2163`](../../../tests/invariants.yaml) `"SEC-168:"` |
| `SEC-33` / `FR-OBS-02` | cost, audit, runs and the execution tree are scope-filtered; hidden nodes are pruned and out-of-scope roots are indistinguishable 404s | [`tests/invariants.yaml:513`](../../../tests/invariants.yaml) `"FR-OBS-02:"` |
| `FR-OBS-08` / `FR-OBS-09` / `FR-OBS-10` | platform status is authenticated, bounded, redacted, and publishes no run events | [`tests/invariants.yaml:521`](../../../tests/invariants.yaml) `"FR-OBS-08:"` |
| `FR-OBS-11` | model telemetry is authenticated, scoped, bounded, audit-derived and credential-free | [`tests/invariants.yaml:533`](../../../tests/invariants.yaml) `"FR-OBS-11:"` |
| `FR-OBS-13` | Langfuse is optional, runs after audit persistence, never blocks a spawn, and emits metadata only | [`tests/invariants.yaml:545`](../../../tests/invariants.yaml) `"FR-OBS-13:"` |
| `FR-OPS-03` | `/healthz` stays liveness while unauthenticated `/readyz` is a bounded, redacted, fail-closed deep gate | [`tests/invariants.yaml:1980`](../../../tests/invariants.yaml) `"FR-OPS-03:"` |
| `FR-OPS-05` | `/healthz` answers from cached state; `boltrig fleet-health` gives a listener-less process the same separation | [`tests/invariants.yaml:2007`](../../../tests/invariants.yaml) `"FR-OPS-05:"` |
| `SEC-60` | dev auth is impossible in production | [`tests/invariants.yaml:1246`](../../../tests/invariants.yaml) `"SEC-60:"` |
| `SEC-71` | production doctor refuses unencrypted or incomplete durable recovery configuration | [`tests/invariants.yaml:1319`](../../../tests/invariants.yaml) `"SEC-71:"` |
| `SEC-72` | untrusted input is structurally enveloped and a breakout attempt is neutralised | [`tests/invariants.yaml:1340`](../../../tests/invariants.yaml) `"SEC-72:"` |
| `SEC-69` | observability audit reads push scope into the store under a clamped page | [`tests/invariants.yaml:1292`](../../../tests/invariants.yaml) `"SEC-69:"` |
| `FR-RUN-01` | doctor reports an enabled retired manifest runtime block | [`tests/invariants.yaml:839`](../../../tests/invariants.yaml) `"FR-RUN-01:"` |
| `FR-HOST-11` | production doctor rejects developer-user Browser CLI state or a personal binary | [`tests/invariants.yaml:661`](../../../tests/invariants.yaml) `"FR-HOST-11:"` |
| `SEC-WRK-34` | background-job receipts are bounded, opaque and explicitly not liveness | [`tests/invariants.yaml:2686`](../../../tests/invariants.yaml) `"SEC-WRK-34:"` |
| `SEC-WRK-35` | the network-policy projection is redacted and marks every separate surface | [`tests/invariants.yaml:2696`](../../../tests/invariants.yaml) `"SEC-WRK-35:"` |
| `SEC-WRK-36` | memory-projection receipts are opaque, content-free, and claim no queue depth or worker liveness | [`tests/invariants.yaml:2703`](../../../tests/invariants.yaml) `"SEC-WRK-36:"` |

### 10.2 Named tests that exercise this area

- Chain and scrub: `tests/kernel/test_audit_chain.py::test_chain_verifies_and_detects_tampering`,
  `::test_every_action_is_audited`, `::test_denied_actions_are_also_audited`,
  `::test_concurrent_writes_keep_a_contiguous_verifiable_chain`,
  `::test_a_chain_longer_than_the_old_window_verifies_ok`,
  `::test_tampering_below_the_old_window_is_still_caught`;
  `tests/security/test_credential_isolation.py::test_audit_scrubs_secret_in_detail`;
  `tests/security/test_audit_identity_scrub.py::test_dict_keys_are_scrubbed_not_copied_verbatim`,
  `::test_a_secret_still_digests_the_whole_value`,
  `::test_false_positives_survive_the_audit_scrub_legibly`.
- Key epochs: `tests/security/test_audit_key_epochs.py::test_a_rotated_chain_still_verifies_across_the_boundary`,
  `::test_a_retired_key_cannot_vouch_for_a_row_after_its_boundary`,
  `::test_a_malformed_epoch_is_ignored_rather_than_trusted`,
  `::test_an_anchor_sealed_before_a_rotation_still_verifies_after_it`.
- Audit-verify CLI: `tests/unit/test_audit_verify_cli.py::test_cannot_look_is_exit_2_and_never_0`,
  `::test_a_segment_verifies_only_when_seeded_from_the_preceding_row`,
  `::test_a_segment_still_catches_tampering_inside_it`.
- Key provisioning: `tests/security/test_audit_key_provisioning.py::test_every_shipped_placeholder_is_fatal_under_a_production_signal`,
  `::test_every_shipped_placeholder_warns_without_a_production_signal`,
  `::test_a_placeholder_key_signs_no_readiness_receipt`,
  `::test_env_example_ships_no_audit_key_placeholder`,
  `::test_the_placeholder_predicate_is_shared_not_duplicated`.
- Log safety: `tests/security/test_log_and_regex_safety.py::test_log_safe_leaves_exactly_one_record`
  (7 hostile parametrisations), `::test_log_safe_bounds_length_and_says_that_it_did`,
  `::test_log_safe_passes_an_ordinary_value_through_untouched`,
  `::test_the_egress_refusal_record_cannot_be_forged`,
  `::test_no_egress_log_call_interpolates_a_raw_caller_value` (an AST walk that
  asserts the CALL COUNT as well as the sanitiser, so fixing one of a pair does
  not silence the alert).
- Logging config: `tests/unit/test_logging_is_configured.py::test_root_gets_a_real_handler_so_nothing_routes_through_lastresort`,
  `::test_info_actually_reaches_a_handler_and_is_formatted`,
  `::test_an_unreadable_level_falls_back_rather_than_silencing_the_process`,
  `::test_both_entrypoints_configure_logging_and_neither_rolls_its_own`.
- Liveness: `tests/unit/test_liveness.py::test_healthz_stays_prompt_and_200_when_an_adapter_health_hangs`,
  `::test_healthz_serves_cached_posture_without_reprobing`,
  `::test_health_snapshot_kicks_a_background_refresh_when_stale`,
  `::test_readyz_stays_bounded_and_fail_closed_with_a_hung_adapter`.
- Readiness: 20 tests in `tests/unit/test_readiness.py`, 16 of them marked
  `FR-OPS-03`, including `::test_readyz_requires_postgres_redis_and_migration_head_in_production`,
  `::test_readyz_rejects_a_process_local_relay_in_production`,
  `::test_readyz_requires_persisted_control_verbs_and_control_owned_bindings`,
  `::test_readyz_requires_control_runtime_collaborators`,
  `::test_readyz_rejects_untrustworthy_fleet_tool_receipts_in_production`,
  `::test_readyz_coalesces_concurrent_unauthenticated_probes`,
  `::test_readyz_route_returns_503_with_redacted_component_failures`.
- Fleet health: all nine tests in `tests/unit/test_fleet_health.py`, including
  `::test_no_redis_is_reported_as_not_checked_not_as_healthy`,
  `::test_a_receipt_that_is_merely_PRESENT_is_not_enough`,
  `::test_another_tenants_receipt_does_not_answer_for_this_one`.
- Doctor: 16 tests in `tests/unit/test_doctor.py`, including
  `::test_production_doctor_has_no_failures_for_secure_posture` (also a standalone
  Makefile target), `::test_production_doctor_flags_deploy_blockers`,
  `::test_production_doctor_fails_closed_on_ambiguous_or_unsafe_database_config`,
  `::test_doctor_refuses_a_codex_runtime_under_production_until_its_gates_open`.
- Projections: `tests/security/test_platform_status.py::test_platform_status_is_bounded_and_redacted`,
  `tests/security/test_background_job_health.py::test_readiness_is_optional_attempt_evidence_not_a_liveness_claim`,
  `tests/security/test_backup_status_projection.py::test_backup_status_rejects_missing_malformed_and_future_markers`,
  `tests/security/test_codex_admission_projection.py::test_two_constant_flips_cannot_promote_a_quarantined_receipt`,
  `tests/security/test_worker_network_policy.py::test_authenticated_projection_is_redacted_and_marks_every_separate_surface`,
  `tests/security/test_langfuse_sink.py::test_langfuse_payload_is_bounded_and_redacts_route_connection_data`.
- Tree scoping: `tests/security/test_audit_tree_scope.py` (5 tests, all bound to
  `FR-OBS-02` / `SEC-33`).

### 10.3 What is NOT bound to any invariant

Bounded: `rg -n "<test file>" tests/invariants.yaml` per file, pinned tree,
2026-08-24. The following have tests but no catalogue entry, so the ratchet does
not hold them:

- `tests/unit/test_logging_is_configured.py` (the whole logging contract).
- `tests/security/test_log_and_regex_safety.py` (log injection, CWE-117).
- `tests/unit/test_audit_verify_cli.py` (the exit-code contract of the only
  scheduled chain check).
- `tests/security/test_audit_key_epochs.py` (rotation without losing history).
- `tests/security/test_codex_admission_projection.py`.
- `tests/security/test_backup_status_projection.py`.
- `tests/security/test_identity_manifest_wiring.py` (the identity-policy
  projection).

None of these files carries a `pytest.mark.invariant` decorator either (bounded:
`rg -n "pytest.mark.invariant" <those files>` returns nothing), so the absence is
consistent on both sides rather than a catalogue omission.

## 11. RISKS

- **RISK 12-R1: a container healthcheck cannot see the difference between "the
  worker is fine" and "the worker could not look".** `boltrig fleet-health` exits
  0 for both, and Docker records only the exit code, so the NOT CHECKED string is
  invisible to the orchestrator.
  [`boltrig/api/fleet_health.py:63`](../../../boltrig/api/fleet_health.py)
  `"NOT CHECKED: no REDIS_URL, so the heartbeat is disabled and no receipt "`.
  Mitigated only by an operator setting `BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT`,
  which nothing in `docker-compose.yml` sets (bounded:
  `rg -n "BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT" docker-compose.yml deploy/`
  returns only the explanatory comment at
  [`docker-compose.yml:315`](../../../docker-compose.yml)
  `"red, which is how a signal gets ignored. BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT"`).
- **RISK 12-R2: `anchor_intact: true` over a tenant that has never been
  anchored.** `verify_latest` returns `(True, None)` when no anchor row exists,
  and `/v1/audit/verify` folds that into `intact`.
  [`boltrig/kernel/security_events.py:278`](../../../boltrig/kernel/security_events.py)
  `"return (True, None)"`. An operator reading `intact: true` on a deployment
  whose anchor job never ran learns nothing about the anchor.
- **RISK 12-R3: the anchor verification loads a million audit rows into memory
  on every call**, and does so through the TAIL read, while the anchor WRITE path
  was already converted to bounded ascending paging.
  [`boltrig/kernel/security_events.py:279`](../../../boltrig/kernel/security_events.py)
  `"events = await self._store.audit_query(tenant_id, limit=1_000_000)"`.
  The route is author-gated, so this is a footgun rather than an anonymous DoS.
- **RISK 12-R4: the execution tree is a TAIL view sold as a complete one.**
  `/v1/audit/tree/{run_id}` reads the newest 10,000 audit rows
  ([`boltrig/kernel/run_access.py:170`](../../../boltrig/kernel/run_access.py)
  `"audit_limit: int = 10_000,"`), so a root older than that window returns 404
  `unknown_run`, indistinguishable from a run that never existed. The
  architecture doc describes the same feature as reconstructing the tree "from
  the audit log alone" and "even for a crashed one"
  ([`docs/architecture/engine-components.md:849`](../../../docs/architecture/engine-components.md)
  `"you can rebuild the whole family tree of any run after the fact"`).
- **RISK 12-R5: the architecture doc names a dead function as the tree's key
  file.** `boltrig/observability/tree.py::build_tree` has no caller anywhere in
  the tree (bounded: `rg -n "build_tree" .` on the pinned tree returns exactly
  two hits, its own definition and the doc line), while the live route uses
  `tree_from_events` through `visible_audit_tree_events`.
  [`docs/architecture/engine-components.md:851`](../../../docs/architecture/engine-components.md)
  `` **Key files.** `boltrig/observability/tree.py` `` A reader following that citation reaches the UNSCOPED
  builder, which reads 10,000 rows for a tenant with no principal filtering
  ([`boltrig/observability/tree.py:83`](../../../boltrig/observability/tree.py)
  `"events = await store.audit_query(tenant_id, limit=10_000)"`).
- **RISK 12-R6: `refuse_dev_auth_in_prod` does not check dev auth.** Its body
  tests only the production signal
  ([`boltrig/api/boot_guards.py:30`](../../../boltrig/api/boot_guards.py)
  `"signal = production_signal(env)"`), and the precondition its name asserts is
  established entirely by its single caller
  ([`boltrig/api/auth_selection.py:111`](../../../boltrig/api/auth_selection.py)
  `"if settings.dev_auth:"`). Correct today; a second caller added anywhere else
  would abort a production boot that has no dev auth at all.
- **RISK 12-R7: the doctor's stack-tool checks measure the HOST the doctor runs
  on, not the image that will run.** `_bin_check` resolves through
  `shutil.which` against the passed `PATH`
  ([`boltrig/api/doctor_stack_state.py:143`](../../../boltrig/api/doctor_stack_state.py)
  `"return shutil.which(command, path=env.get"`), which contradicts the module
  header's "no dependency I/O" claim in spirit. The deployment guide says so
  explicitly and points at `make release-validate`
  ([`docs/DEPLOYMENT.md:655`](../../../docs/DEPLOYMENT.md)
  `"checks describe that host and must not be used as release-image evidence."`),
  but the CLI itself prints no such warning next to the green.
- **RISK 12-R8: `BOLTRIG_LOG_LEVEL` is undocumented outside its own module.**
  Bounded: `rg -n "BOLTRIG_LOG_LEVEL" .` on the pinned tree returns only
  `boltrig/api/logging_config.py` and its test. It is absent from
  `.env.example`, `docker-compose.yml` and `deploy/`, so the single knob that
  governs whether an incident is visible at all is discoverable only by reading
  source. [`boltrig/api/logging_config.py:33`](../../../boltrig/api/logging_config.py)
  `"ENV_VAR = \"BOLTRIG_LOG_LEVEL\""`.
- **RISK 12-R9: the doctor never checks the retired-key epochs.** A key rotated
  without recording `BOLTRIG_AUDIT_HMAC_RETIRED` passes `boltrig doctor
  --production` with a green `audit_hmac_key`, and the loss shows up only at the
  next `audit-verify`, which is not run by anything in this tree on a schedule
  (bounded: `rg -n "audit-verify" docker-compose.yml deploy/ scripts/` returns no
  cron, timer or compose entry). [`boltrig/api/doctor.py:238`](../../../boltrig/api/doctor.py)
  `"_add(checks, \"ok\", \"audit_hmac_key\", \"Audit HMAC key is non-placeholder.\")"`.
- **RISK 12-R10: the audit write key is bound at import.**
  [`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py)
  `"_HMAC_KEY = os.environ.get(\"BOLTRIG_AUDIT_HMAC_KEY\", \"dev-insecure-audit-key\")"`.
  The READ side re-reads epochs per verification, so a rotation is asymmetric: a
  running process keeps signing with the old key until restarted, while
  verification has already moved.
- **RISK 12-R11: dead code inside the doctor.** `_csv` is defined and never
  called; the module is not re-exported (bounded: `rg -n "_csv" boltrig/api/doctor.py`
  returns only the definition, and the only importers of the module take
  `format_report`, `load_env_file`, `run_doctor`).
  [`boltrig/api/doctor.py:154`](../../../boltrig/api/doctor.py)
  `"def _csv(value: str | None) -> list[str]:"`. `_check_runtime` likewise
  accepts `env` and `prod` and uses neither
  ([`boltrig/api/doctor.py:333`](../../../boltrig/api/doctor.py)
  `"def _check_runtime("`).
- **RISK 12-R12: the log-injection defence is enforced structurally for exactly
  one module.** The AST test walks `boltrig/adapters/egress.py` only
  ([`tests/security/test_log_and_regex_safety.py:129`](../../../tests/security/test_log_and_regex_safety.py)
  `"tree = ast.parse((root / \"boltrig/adapters/egress.py\").read_text"`), while
  `log_safe` has ten call sites across two modules (bounded:
  `rg -n "log_safe\(" --glob '*.py'` returns 10 across `boltrig/log_safety.py`,
  `boltrig/adapters/egress.py`, `boltrig/kernel/dispatch.py` and one test). A new
  `log.warning("... %s", untrusted)` anywhere else is caught by nothing in this
  tree.
- **RISK 12-R13: the shipped default audit key is a real string, not an
  absence.** With no production signal set, and compose emitting an empty
  `BOLTRIG_PRODUCTION`, a deployment can run a hash chain keyed by a public
  constant in this repository while `/v1/audit/verify` returns `intact: true`.
  The code says exactly this and answers it with a WARNING only
  ([`boltrig/api/boot_guards.py:68`](../../../boltrig/api/boot_guards.py)
  `"empty BOLTRIG_PRODUCTION), so a real deployment can reach here and run a"`).
- **RISK 12-R14: seven test files in this area bind to no invariant** (see
  10.3), including the entire logging contract and the log-injection defence.
  Under the contract's own rule, an unbound security requirement is itself a
  finding.
- **RISK 12-R15: `/v1/platform/status` is authenticated but not role-gated**,
  while its sibling integrity and changelog routes are author-or-admin gated
  ([`boltrig/kernel/platform_routes/observability.py:58`](../../../boltrig/kernel/platform_routes/observability.py)
  `"if not can_author_route(p):"`). Any tenant member therefore reads the
  identity mode, the codex rollout posture, the network-policy coverage map and
  every background-job receipt. The values are redacted by construction, so this
  is a disclosure-surface observation rather than a credential leak, and
  FR-OBS-08 asks only for "authenticated, never public health".

## 12. OPEN QUESTIONS

1. **Is `/v1/audit/verify` ever actually called?** No cron, timer, compose entry
   or script in the pinned tree invokes it or `boltrig audit-verify` (bounded:
   `rg -n "audit-verify|/v1/audit/verify" docker-compose.yml deploy/ scripts/
   Makefile` returns only prose in `scripts/check_fleet_drift.py` and the CLI
   help). SETTLED BY: the deployment's own crontab or scheduler, which is outside
   this tree.
2. **Does any deployment set `BOLTRIG_AUDIT_HMAC_RETIRED`?** The mechanism, the
   tests and the docstrings all exist; no manifest, compose file or `.env.example`
   line in the tree sets it (bounded: `rg -n "HMAC_RETIRED" . ` returns
   `boltrig/kernel/audit.py`, `tests/security/test_audit_key_epochs.py` and the
   `audit_verify` message). SETTLED BY: reading a live deployment's environment.
3. **What writes the backup freshness marker?** `backup_status` reads
   `BOLTRIG_BACKUP_HEALTH_FILE`, which compose maps to
   `/run/boltrig-backup-health/last-success`
   ([`docker-compose.yml:163`](../../../docker-compose.yml)
   `"BOLTRIG_BACKUP_HEALTH_FILE: /run/boltrig-backup-health/last-success"`). The
   writer is `scripts/backup.sh` inside the profile-gated sidecar, which is
   Area 15's scope; the exact atomicity of that write is not settled here.
   SETTLED BY: reading `scripts/backup.sh`.
4. **Is `EXPECTED_ALEMBIC_HEAD` graph-checked, or only string-compared?**
   `test_packaged_readiness_head_matches_alembic_head` is bound under FR-OPS-03
   and the invariant text says the head "is graph-checked against Alembic", but
   this spec did not open the test (it requires a database fixture and running it
   is forbidden here). SETTLED BY: reading
   `tests/integration/test_migration_parity.py`.
5. **Does the status provider that feeds `stack_tools` and `bifrost` report
   `live_health` for anything other than bifrost?** `_platform_checks` reads
   `components["bifrost"].metadata.live_health` by name
   ([`boltrig/api/readiness.py:311`](../../../boltrig/api/readiness.py)
   `"live = metadata.get(\"live_health\") if isinstance(metadata, Mapping) else None"`),
   which couples readiness to one hard-coded component id. Whether other
   components carry the same key was not settled. SETTLED BY: reading
   `boltrig/fleet/stack_tool_status.py`.
6. **Is the `detail` scrub applied to the SecurityEvent stream by the same
   code?** `kernel/audit.py` scrubs for `AuditEvent`; the security writer lives in
   `kernel/security_events.py` and was read only for the anchor. SETTLED BY:
   reading `SecurityEventWriter` in that module (Area 11's scope).
7. **What is the retention policy for `audit_log` in a real deployment?** The
   table has no retention mechanism in this tree and the retention janitor is
   explicitly forbidden from touching it. SETTLED BY: the deployment's own
   archival policy, which no code here expresses.

## 13. Requirements table

Statuses use the contract vocabulary. `invariant` is the binding id from
`tests/invariants.yaml`, or `-` where nothing binds it (every `-` on a security
or correctness row is recorded in RISKS 12-R14).

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1200 | Every kernel action writes exactly one audit row in the same logical step as its effect, chained to the previous row's hash per tenant. | IMPLEMENTED | `boltrig/kernel/audit.py:333` `"Scrub, chain, and append."` | SEC-16 |
| BT-REQ-1201 | The audit row hash is HMAC-SHA256 over a stable sorted-key JSON serialisation of the chain fields under the process audit key. | IMPLEMENTED | `boltrig/kernel/audit.py:353` `"digest = hmac.new(_HMAC_KEY, _canonical(event).encode()"` | K-19 |
| BT-REQ-1202 | The five Opbox-depth fields enter the canonical body only when non-None, so a pre-enrichment row canonicalises byte-for-byte as before. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:144` `"if val is not None:"` | K-19 |
| BT-REQ-1203 | A detail string matching a secret pattern is replaced entire by a sha256 digest, size and scrubbed marker. | IMPLEMENTED | `boltrig/kernel/audit.py:208` `"digest = hashlib.sha256(v.encode()).hexdigest()[:16]"` | K-20 |
| BT-REQ-1204 | A detail string matching only an identity pattern has the matched span substituted and the rest left legible. | IMPLEMENTED | `boltrig/kernel/audit.py:215` `"return pii.redact_identity(v)[:_PREVIEW_LEN]"` | K-20 |
| BT-REQ-1205 | A secret-bearing dict KEY collapses to the stable string marker and is never copied verbatim into the append-only store. | IMPLEMENTED | `boltrig/kernel/audit.py:196` `"return f\"[scrubbed:{kind}]\""` | K-20 |
| BT-REQ-1206 | The scrub recurses through nested dicts and through list and tuple values. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:219` `"if isinstance(v, (list, tuple)):"` | K-20 |
| BT-REQ-1207 | Every scrubbed string value is truncated to 256 characters. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:29` `"_PREVIEW_LEN = 256"` | K-20 |
| BT-REQ-1208 | The raw user_agent header is scrubbed to a bounded string before it enters the hash chain and stays a string so the column shape is unchanged. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:345` `"event.user_agent = _scrub_free_text("` | K-20 |
| BT-REQ-1209 | The chain step is serialised by one asyncio lock per tenant, with the Postgres UNIQUE(tenant_id, seq) as the multi-process backstop. | IMPLEMENTED | `boltrig/kernel/audit.py:347` `"async with self._lock(event.tenant_id):"` | SEC-16 |
| BT-REQ-1210 | An audit append fault defers the scrubbed payload to the audit outbox and returns the event with seq, prev_hash and hash set to None. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:364` `"await self._store.audit_outbox_enqueue("` | SEC-16 |
| BT-REQ-1211 | The outbox deferral marker records only the exception type name, never its message. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:290` `"\"append_error\": type(exc).__name__,"` | K-20 |
| BT-REQ-1212 | write_now has no deferral branch, so the outbox janitor cannot fork a second outbox row for an event that already has one. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:375` `"Scrub, chain, and append with NO deferral"` | SEC-16 |
| BT-REQ-1213 | Chain verification re-derives the entire per-tenant chain from seq 1 through the ascending scan seam, never a bounded tail window. | IMPLEMENTED | `boltrig/kernel/audit.py:262` `"events = await scan(tenant_id, after, page)"` | SEC-168 |
| BT-REQ-1214 | A scan page whose last seq does not advance the cursor terminates verification as a failure rather than looping forever. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:272` `"a misbehaving scan page must never loop forever"` | SEC-168 |
| BT-REQ-1215 | Exactly one key verifies each row: the first retired epoch whose boundary the row predates, otherwise the live key. | IMPLEMENTED | `boltrig/kernel/audit.py:84` `"if seq < boundary:"` | - |
| BT-REQ-1216 | A malformed retired-key epoch entry is ignored, so its rows fall through to the live key and fail honestly rather than being silently accepted. | IMPLEMENTED | `boltrig/kernel/audit.py:59` `"Ignoring a malformed entry is the fail-safe"` | - |
| BT-REQ-1217 | Retired epochs are parsed once per verification rather than at import, so a rotation is honoured on the read side without a restart. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:63` `"raw = os.environ.get(_RETIRED_ENV, \"\").strip()"` | - |
| BT-REQ-1218 | The write-side audit key is bound at module import, so rotating BOLTRIG_AUDIT_HMAC_KEY requires a process restart. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:28` `"_HMAC_KEY = os.environ.get(\"BOLTRIG_AUDIT_HMAC_KEY\""` | - |
| BT-REQ-1219 | The rollup anchor seals and verifies under key_in_force_at(seq_end), so write and read agree by construction across a rotation. | IMPLEMENTED | `boltrig/kernel/audit.py:89` `"def key_in_force_at(seq: int"` | - |
| BT-REQ-1220 | boltrig audit-verify exits 0 on a verifying chain, 1 on a bad row, and 2 when it could not look, never reporting success it did not establish. | IMPLEMENTED | `boltrig/api/audit_verify.py:20` `"Exit 2 is deliberately NOT 0."` | - |
| BT-REQ-1221 | A segment verification refuses to run when the seeding row before the segment does not exist, exiting 2 rather than seeding prev as None. | IMPLEMENTED | `boltrig/api/audit_verify.py:60` `"to seed the segment from"` | - |
| BT-REQ-1222 | A segment verification prints the skipped range on every run. | IMPLEMENTED | `boltrig/api/audit_verify.py:63` `"SEGMENT ONLY: rows 1..{from_seq - 1} were NOT CHECKED."` | - |
| BT-REQ-1223 | GET /v1/audit/verify is author-or-admin gated and reports chain, security-chain and anchor integrity as separate fields plus a combined verdict. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/observability.py:142` `"\"intact\": bool(chain_ok and sec_ok and anchor_ok),"` | SEC-33 |
| BT-REQ-1224 | verify_latest reports anchor_intact true when the tenant has no anchor row at all. | IMPLEMENTED-UNTESTED | `boltrig/kernel/security_events.py:278` `"return (True, None)"` | - |
| BT-REQ-1225 | The anchor verification path loads the newest one million audit rows into process memory on every call. | IMPLEMENTED-UNTESTED | `boltrig/kernel/security_events.py:279` `"events = await self._store.audit_query(tenant_id, limit=1_000_000)"` | - |
| BT-REQ-1226 | POST /v1/audit/export is author-gated, bounded at 100000 rows, and writes its own keys-only disclosure audit row. | IMPLEMENTED-UNTESTED | `boltrig/kernel/platform_routes/observability.py:154` `"await audit_authoring(k, p, \"audit.export\""` | SEC-33 |
| BT-REQ-1227 | audit_query is a tail read ordered by seq descending under a limit and returned ascending, distinct from the ascending audit_scan verification seam. | IMPLEMENTED | `boltrig/store/postgres.py:694` `"ORDER BY seq DESC LIMIT $2"` | SEC-69 |
| BT-REQ-1228 | The execution tree is assembled only from rows the caller may see, with a hidden parent link nulled rather than followed. | IMPLEMENTED | `boltrig/kernel/run_access.py:218` `"row = replace(row, parent_run_id=None)"` | FR-OBS-02 |
| BT-REQ-1229 | Tree assembly is cycle-guarded and depth-capped at 256, emitting a degraded marker rather than recursing. | IMPLEMENTED | `boltrig/observability/tree.py:60` `"if len(path) >= 256:"` | FR-OBS-02 |
| BT-REQ-1230 | The audit tree route reads at most the newest 10000 audit rows, so a root older than that window is an indistinguishable 404. | IMPLEMENTED-UNTESTED | `boltrig/kernel/run_access.py:170` `"audit_limit: int = 10_000,"` | - |
| BT-REQ-1231 | observability.tree.build_tree is unreachable from any code path in the tree. | DEAD | `boltrig/observability/tree.py:79` `"async def build_tree("` | - |
| BT-REQ-1232 | Model telemetry is aggregated from audit rows into provider/model/runtime/profile buckets and capped at 200 rows. | IMPLEMENTED | `boltrig/observability/model_telemetry.py:92` `"return rows[: max(0, min(limit, 200))]"` | FR-OBS-11 |
| BT-REQ-1233 | No metrics or trace exporter exists; every quantitative figure is reconstructed at read time from audit rows. | IMPLEMENTED | `boltrig/observability/model_telemetry.py:82` `"Aggregate provider/model usage from audit rows"` | FR-OBS-11 |
| BT-REQ-1234 | The Langfuse mirror runs only after the audit row is persisted and cannot block or fail a spawn. | IMPLEMENTED | `boltrig/fleet/spawn.py:490` `"await self._kernel.audit.write(event)"` | FR-OBS-13 |
| BT-REQ-1235 | A Langfuse emit is bounded by a 0.25 second timeout and every exception increments a failure counter and returns. | IMPLEMENTED | `boltrig/observability/langfuse_sink.py:183` `"await asyncio.wait_for(self._emit(payload), timeout=self.timeout_s)"` | FR-OBS-13 |
| BT-REQ-1236 | The Langfuse payload carries only allow-listed route keys and bounded metadata, never a prompt, output, URL or key. | IMPLEMENTED | `boltrig/observability/langfuse_sink.py:22` `"_ROUTE_KEYS = {\"provider\", \"model\", \"runtime\", \"profile\", \"tier\"}"` | FR-OBS-13 |
| BT-REQ-1237 | A misconfigured Langfuse sink degrades to a typed no-op carrying a reason, never an error. | IMPLEMENTED | `boltrig/observability/langfuse_sink.py:253` `"return NoopObservabilitySink(reason=\"missing_keys\")"` | FR-OBS-13 |
| BT-REQ-1238 | Langfuse delivery is projected as process-local attempt counters for one spawner and never as sink health or delivery lag. | IMPLEMENTED-UNTESTED | `boltrig/observability/langfuse_status.py:35` `"process_local_attempt_counters_not_sink_health"` | - |
| BT-REQ-1239 | An unrecognised sink_state or reason collapses the Langfuse projection to unavailable. | IMPLEMENTED-UNTESTED | `boltrig/observability/langfuse_status.py:63` `"if state not in _STATES or reason not in _REASONS:"` | - |
| BT-REQ-1240 | log_safe escapes every C0 and C1 control character, DEL, and the Unicode line separators so a caller-chosen value cannot forge a second log record. | IMPLEMENTED | `boltrig/log_safety.py:54` `"if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:"` | - |
| BT-REQ-1241 | log_safe truncates at 200 characters and states the original length rather than truncating silently. | IMPLEMENTED | `boltrig/log_safety.py:65` `"return f\"{rendered[:limit]}...[{len(rendered)} chars]\""` | - |
| BT-REQ-1242 | Both egress refusal log calls pass every format argument through log_safe, asserted structurally by an AST walk that also asserts the call count. | IMPLEMENTED | `tests/security/test_log_and_regex_safety.py:139` `"expected 2 egress log calls"` | - |
| BT-REQ-1243 | log_safety imports nothing from the rest of the package so kernel and adapters share one copy of the rule. | IMPLEMENTED-UNTESTED | `boltrig/log_safety.py:16` `"This module has NO imports from the rest of the package"` | - |
| BT-REQ-1244 | Untrusted spans are wrapped in a typed envelope whose literal untrusted delimiters are defanged inside the content. | IMPLEMENTED | `boltrig/text_envelope.py:56` `"body = _neutralise_untrusted_delimiters(content)"` | SEC-72 |
| BT-REQ-1245 | The envelope delimiter matcher tolerates zero-width, soft-hyphen and BOM gaps so an invisible character cannot forge a delimiter. | IMPLEMENTED | `boltrig/text_envelope.py:24` `"_TAG_GAP = r\"[\\s\\u00ad\\u200b-\\u200f\\u2060-\\u2064\\ufeff]*\""` | SEC-72 |
| BT-REQ-1246 | Envelope attribute values are stripped of angle brackets, quotes, CR and LF. | IMPLEMENTED-UNTESTED | `boltrig/text_envelope.py:31` `"_ATTR_UNSAFE_RE = re.compile(r'[<>\"\\r\\n]')"` | SEC-72 |
| BT-REQ-1247 | Every boltrig process installs one root logging handler with a formatter carrying timestamp, level name and logger name. | IMPLEMENTED | `boltrig/api/logging_config.py:56` `"logging.basicConfig(level=level, format=FORMAT, force=force)"` | - |
| BT-REQ-1248 | An unreadable BOLTRIG_LOG_LEVEL falls back to INFO rather than silencing the process. | IMPLEMENTED | `boltrig/api/logging_config.py:45` `"return level if isinstance(level, int) else logging.INFO"` | - |
| BT-REQ-1249 | Both the ASGI and worker entrypoints call configure_logging at import and neither calls basicConfig itself. | IMPLEMENTED | `boltrig/api/asgi.py:18` `"configure_logging()"` | - |
| BT-REQ-1250 | boltrig doctor performs static checks with no dependency I/O and exits 1 if and only if at least one check is fail. | IMPLEMENTED | `boltrig/api/doctor.py:62` `"return 1 if self.failed else 0"` | - |
| BT-REQ-1251 | Doctor production mode is inferred from BOLTRIG_PRODUCTION or from ENV, BOLTRIG_ENV or APP_ENV in prod, production or staging, or forced by --production. | IMPLEMENTED | `boltrig/api/doctor.py:161` `"in _PROD_NAMES for k in (\"ENV\", \"BOLTRIG_ENV\", \"APP_ENV\")"` | - |
| BT-REQ-1252 | Doctor fails any run whose DATABASE_URL contains a shipped placeholder fragment, in production or not. | IMPLEMENTED | `boltrig/api/doctor.py:196` `"DATABASE_URL still contains a placeholder."` | - |
| BT-REQ-1253 | Doctor fails a production run whose audit HMAC key is placeholder-like or shorter than 32 characters. | IMPLEMENTED | `boltrig/api/doctor.py:229` `"_weak(env.get(\"BOLTRIG_AUDIT_HMAC_KEY\"), min_len=32)"` | K-19 |
| BT-REQ-1254 | Doctor fails BOLTRIG_DEV_AUTH under a production signal. | IMPLEMENTED | `boltrig/api/doctor.py:263` `"BOLTRIG_DEV_AUTH is enabled in production mode."` | SEC-60 |
| BT-REQ-1255 | Doctor fails a wildcard or unset host allowlist under production and any wildcard CORS origin in any mode. | IMPLEMENTED | `boltrig/api/doctor_edge.py:34` `"BOLTRIG_CORS_ORIGINS contains '*'."` | - |
| BT-REQ-1256 | A full release mode with no exact packaged-desktop Tauri origin in BOLTRIG_CORS_ORIGINS fails. | IMPLEMENTED | `boltrig/api/doctor_edge.py:42` `"env.get(\"BOLTRIG_RELEASE_MODE\") == \"full\""` | IAC-005 |
| BT-REQ-1257 | Doctor warns for every retired runtime name a tenant manifest still enables. | IMPLEMENTED | `boltrig/api/doctor.py:361` `"f\"retired_runtime_{kind}\","` | FR-RUN-01 |
| BT-REQ-1258 | Doctor derives the application and Hatchet database names without reflecting any DSN credential and fails when the configured sources disagree. | IMPLEMENTED | `boltrig/api/doctor_backups.py:68` `"Database sources disagree: {sources}."` | SEC-71 |
| BT-REQ-1259 | Production doctor fails an unset BACKUP_REMOTE or an unset BACKUP_PASSPHRASE. | IMPLEMENTED | `boltrig/api/doctor_backups.py:106` `"BACKUP_PASSPHRASE is unset; Hatchet signing state"` | SEC-71 |
| BT-REQ-1260 | Production doctor fails a Browser CLI state root or binary that references a user home or personal tool state. | IMPLEMENTED | `boltrig/api/doctor_stack_state.py:120` `"points at a user-owned {tool} binary path."` | FR-HOST-11 |
| BT-REQ-1261 | One shared predicate decides whether a tenant needs the browser CLI, consumed by doctor, the fleet entrypoint and readiness. | IMPLEMENTED | `boltrig/api/doctor_stack_state.py:47` `"def needs_browser_cli(manifest: FleetManifest) -> bool:"` | FR-HOST-11 |
| BT-REQ-1262 | The doctor codex check fails under production whenever the static release posture is not ready. | IMPLEMENTED | `boltrig/api/doctor_codex.py:54` `"\"fail\" if production else \"warn\","` | IAC-005 |
| BT-REQ-1263 | Doctor never fails on Hatchet: an absent durable engine is at most a warning. | IMPLEMENTED-UNTESTED | `boltrig/api/doctor.py:509` `"Hatchet live engine wiring is absent; local fallback only."` | - |
| BT-REQ-1264 | With no manifest path, doctor records one warn and skips every manifest-gated check family without changing the exit code. | IMPLEMENTED-UNTESTED | `boltrig/api/doctor.py:374` `"No manifest path was provided; manifest checks skipped."` | - |
| BT-REQ-1265 | The doctor helper _csv is defined and never called. | DEAD | `boltrig/api/doctor.py:154` `"def _csv(value: str"` | - |
| BT-REQ-1266 | /healthz answers from the cached adapter posture without awaiting adapter I/O and its top-level status is the literal ok. | IMPLEMENTED | `boltrig/kernel/health_routes.py:35` `"\"status\": \"ok\","` | FR-OPS-05 |
| BT-REQ-1267 | A stale adapter-health cache schedules exactly one bounded background re-probe off the request path. | IMPLEMENTED | `boltrig/adapters/loader.py:108` `"self._refresh_task = loop.create_task(self.refresh_health())"` | FR-OPS-05 |
| BT-REQ-1268 | Each adapter health probe is cut off after 2.5 seconds and recorded down rather than hanging the caller. | IMPLEMENTED | `boltrig/adapters/loader.py:86` `"await asyncio.wait_for(adapter.health(), probe_timeout_s)"` | FR-OPS-05 |
| BT-REQ-1269 | /readyz is unauthenticated, coalesces concurrent probes under one lock, and serves a deep copy of a briefly cached redacted result. | IMPLEMENTED | `boltrig/api/readiness.py:166` `"async with self._cache_lock:"` | FR-OPS-03 |
| BT-REQ-1270 | /readyz returns 503 whenever any required check is not exactly ok. | IMPLEMENTED | `boltrig/kernel/health_routes.py:66` `"status_code=200 if report.get(\"status\") == \"ready\" else 503,"` | FR-OPS-03 |
| BT-REQ-1271 | Readiness requires the packaged Alembic head to be the only applied head, compared as an exact tuple. | IMPLEMENTED | `boltrig/api/readiness_dependencies.py:130` `"head_ok = tuple(heads) == (expected_head,)"` | FR-OPS-03 |
| BT-REQ-1272 | Production readiness refuses a process-local event relay with reason wrong_backend before any Redis probe runs. | IMPLEMENTED | `boltrig/api/readiness.py:238` `"if production and not self._kernel.events.shared:"` | FR-OPS-03 |
| BT-REQ-1273 | Control-plane readiness requires live registration, persisted verbs, control-owned bindings, an activated adapter record and five wired collaborators. | IMPLEMENTED | `boltrig/api/readiness_control.py:51` `"ready = ("` | FR-OPS-03 |
| BT-REQ-1274 | Readiness requires the browser stack tool only where the tenant manifest declares browser automation. | IMPLEMENTED | `boltrig/api/readiness.py:55` `"return _STACK_TOOL_IDS if needs_browser_cli(manifest) else frozenset()"` | FR-OPS-03 |
| BT-REQ-1275 | The live stack-tool check requires a fresh HMAC-authenticated fleet receipt and maps any unrecognised probe reason to unavailable. | IMPLEMENTED | `boltrig/api/readiness.py:354` `"safe_reason = ("` | FR-OPS-03 |
| BT-REQ-1276 | A configured but unprobed model gateway reports unchecked rather than disabled and remains not required. | IMPLEMENTED | `boltrig/fleet/model_gateway.py:184` `"return (\"unchecked\", \"configured_but_health_check_disabled\")"` | FR-OPS-03 |
| BT-REQ-1277 | Hatchet readiness is required only when the health flag, the durability flag or a client token is configured, and a configured-but-unreachable engine fails closed. | IMPLEMENTED | `boltrig/api/readiness.py:373` `"is_truthy(env.get(\"BOLTRIG_HATCHET_HEALTH\"))"` | FR-OPS-03 |
| BT-REQ-1278 | Password-reset delivery readiness is required only under its own flag and always reports provider_delivery_proven false. | IMPLEMENTED | `boltrig/api/readiness_dependencies.py:73` `"provider_delivery_proven=False,"` | FR-OPS-03 |
| BT-REQ-1279 | Background-job readiness entries are always not required and can never make readiness not_ready. | IMPLEMENTED | `boltrig/observability/background_jobs.py:150` `"\"required\": False,"` | SEC-WRK-34 |
| BT-REQ-1280 | An unreadable or timed-out background receipt read degrades every job to attempt_evidence_unavailable rather than failing readiness. | IMPLEMENTED-UNTESTED | `boltrig/api/background_readiness.py:43` `"return _unavailable_checks()"` | SEC-WRK-34 |
| BT-REQ-1281 | A background receipt row whose job name this build does not know is skipped rather than taking the whole readiness read down. | IMPLEMENTED-UNTESTED | `boltrig/store/background_jobs.py:348` `"return _receipts_skipping_unknown(rows)"` | SEC-WRK-34 |
| BT-REQ-1282 | A background attempt receipt write failure is logged at warning and swallowed so it can never change the janitor outcome. | IMPLEMENTED | `boltrig/observability/background_jobs.py:40` `"Best-effort evidence write that can never change"` | SEC-WRK-34 |
| BT-REQ-1283 | Boot aborts with a fatal RuntimeError when dev auth is selected under any production signal. | IMPLEMENTED | `boltrig/api/boot_guards.py:32` `"raise RuntimeError("` | SEC-60 |
| BT-REQ-1284 | Boot aborts with a fatal RuntimeError when the audit HMAC key is a known shipped placeholder under any production signal. | IMPLEMENTED | `boltrig/api/boot_guards.py:58` `"if signal is not None and is_placeholder_secret(key):"` | K-19 |
| BT-REQ-1285 | With no production signal a placeholder audit key logs a warning every boot and does not abort. | IMPLEMENTED | `boltrig/api/boot_guards.py:64` `"if is_placeholder_secret(key):"` | K-19 |
| BT-REQ-1286 | refuse_dev_auth_in_prod tests only the production signal; its dev-auth precondition is established by its single caller. | IMPLEMENTED-UNTESTED | `boltrig/api/boot_guards.py:30` `"signal = production_signal(env)"` | SEC-60 |
| BT-REQ-1287 | One placeholder predicate is shared by the doctor, the boot guard and the readiness receipt key so the three sites cannot disagree. | IMPLEMENTED | `boltrig/config/weak_secrets.py:52` `"def is_placeholder_secret(value: str"` | K-19 |
| BT-REQ-1288 | boltrig fleet-health exits 0 with an explicit NOT CHECKED message when the heartbeat is disabled by configuration and no receipt can exist. | IMPLEMENTED | `boltrig/api/fleet_health.py:63` `"NOT CHECKED: no REDIS_URL, so the heartbeat is disabled"` | FR-OPS-05 |
| BT-REQ-1289 | BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT converts both NOT CHECKED branches of fleet-health into exit 1. | IMPLEMENTED | `boltrig/api/fleet_health.py:60` `"if env.get(_REQUIRE_ENV):"` | FR-OPS-05 |
| BT-REQ-1290 | fleet-health treats a merely present receipt as insufficient: it must also be fresh within the configured TTL and authentic for this tenant. | IMPLEMENTED | `boltrig/api/fleet_health.py:93` `"await read_fleet_tool_receipt("` | FR-OPS-05 |
| BT-REQ-1291 | GET /v1/platform/status requires an authenticated principal and returns only bounded, redacted projections. | IMPLEMENTED | `boltrig/kernel/platform_routes/platform_status.py:105` `"@app.get(\"/v1/platform/status\")"` | FR-OBS-08 |
| BT-REQ-1292 | Any component metadata key containing a secret-like fragment is dropped and any http or https string value is nulled before projection. | IMPLEMENTED | `boltrig/kernel/platform_routes/platform_status.py:51` `"if any(part in name.lower() for part in _SECRET_KEY_PARTS):"` | FR-OBS-09 |
| BT-REQ-1293 | The network-policy projection returns no proxy URL, CA path, domain value or provider endpoint and names each surface's coverage limitation. | IMPLEMENTED | `boltrig/observability/network_policy.py:56` `"No proxy URL, CA path/content, domain value or provider endpoint is returned."` | SEC-WRK-35 |
| BT-REQ-1294 | The identity-policy projection returns a mode, a sha256 generation digest and no issuer, audience or JWKS value. | IMPLEMENTED-UNTESTED | `boltrig/observability/identity_policy.py:77` `"\"generation\": hashlib.sha256("` | - |
| BT-REQ-1295 | The Codex admission projection cannot report ready in this build because all three inputs are false or non-empty constants. | IMPLEMENTED | `boltrig/observability/codex_admission.py:33` `"ready = runtime_ready and config_ready and not blockers"` | - |
| BT-REQ-1296 | Memory-projection receipts carry opaque per-tenant digests, no content, at most 50 rows, and an explicit truncated flag. | IMPLEMENTED | `boltrig/observability/memory_projection_delivery.py:153` `"\"truncated\": len(rows) > MAX_MEMORY_PROJECTION_RECEIPTS,"` | SEC-WRK-36 |
| BT-REQ-1297 | GET /v1/backup/status reads only the sidecar's bounded atomic epoch marker, never a backup artifact, and never claims restore readiness. | IMPLEMENTED | `boltrig/observability/backup_status.py:18` `"Read only the sidecar's atomic epoch marker, never backup artifacts."` | SEC-71 |
| BT-REQ-1298 | A marker file over 32 bytes, non-ascii, non-digit or dated in the future is classified invalid_marker rather than parsed. | IMPLEMENTED | `boltrig/observability/backup_status.py:43` `"if len(raw) > 32 or not value.isascii() or not value.isdigit():"` | SEC-71 |
| BT-REQ-1299 | The health-claim gate fails any first-party service whose healthcheck probes liveness on an application that has a readiness route, and its waiver file is empty. | IMPLEMENTED-UNTESTED | `scripts/check_health_claims.py:26` `"registers a readiness path (/readyz, /ready, /readiness), the healthcheck is"` | - |
