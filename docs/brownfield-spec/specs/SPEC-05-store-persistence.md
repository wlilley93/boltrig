---
area: "05 Persistence: the store layer and the migration ledger"
id-block: BT-REQ-0500 to BT-REQ-0599
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec-05-store
date: 2026-08-24
---

# SPEC-05: Persistence, the store layer and the migration ledger

## Bound of this reading

`boltrig/store/` holds 101 Python modules totalling 20,349 lines
(`find boltrig/store -name '*.py' | wc -l`, `wc -l`, pinned tree, 2026-08-24).
I read in full: `base.py` (681L), `postgres.py` head and every CAS/credential/audit
method, `rls.sql` (221L), `rls_pool.py`, `tenant_scope.py`, `sealing.py`,
`credential_references.py`, `guarded_writes.py`, `idempotency.py`,
`idempotency_contract.py`, `budget_windows.py`, `budget_usage.py` (both halves),
`effect_ledger_postgres.py`, `trajectory.py`, `trajectory_postgres.py`,
`control_plane_reads.py`, `channel_dedup.py`, `audit_read_contract.py`,
`artifact_contract.py`, `provenance_contract.py`, and all 2,892 lines of
`boltrig/store/schema.sql`. `migrations/env.py`, `alembic.ini`, `baseline.sql`
headers and all 88 revision files' revision/down_revision graph were read; I read
the bodies of 0001, 0020, 0022, 0024, 0041, 0042, 0043, 0044, 0045, 0057, 0063,
0068, 0074, 0075, 0077 (both), 0081, 0082, 0084, 0085 and 0086 in full and
machine-scanned the remainder for destructive operations, idempotency guards and
RLS policy creation.

Modules I sampled at top-level-definition depth only, without reading every
method body: `memory.py` (1,248L, read init + credential + purge paths),
`observability_reads.py`, `capabilities.py`, `capability_routing.py`,
`channels.py`, `channel_outbox.py` (read the claim path), `integrations.py`,
`integration_atomic.py`, `mcp_*` (7 modules), `workflow_schedules_*`,
`workflow_triggers.py`, `device_*`, `camera_*`, `agent_*` (9 modules),
`ai_key_proposals_*`, `model_endpoints_*`, `authored_definitions_*`,
`work_mutations.py`, `rows.py`, `background_jobs.py` (read the PG half),
`birth_profiles.py` (read the PG half). Statements about those modules in this
spec are grounded in the exact lines cited and nowhere else.

I did not run any test, migration, container or database. Every claim below is
static.

## 2. Purpose

The persistence area owns everything Boltrig writes down: one `Store` Protocol
that the kernel is the sole consumer of, two concrete backends behind it
(an in-process dictionary store and an asyncpg PostgreSQL store), the 138-table
PostgreSQL catalogue those backends read and write, the opt-in row-level-security
overlay that fences that catalogue by tenant at the database, and the 88-revision
Alembic ledger that is the authoritative way a deployed catalogue moves forward.
Its job is to make "the kernel depends on this Protocol, never on a concrete DB"
[`boltrig/store/base.py:3`](../../../boltrig/store/base.py) `"kernel depends on this Protocol, never on a concrete DB"`
true in both directions: swapping the backend changes nothing above it, and
changing the schema is an ordered, replayable, verifiable act rather than a
process restart.

## 3. Boundaries

**Owns.** `boltrig/store/**` (the Protocol, both backends, the SQL bootstrap, the
RLS overlay, the at-rest sealing seam), `migrations/**` (env, baseline, 88
revisions), `alembic.ini`, and the deployment-time migration gate
`scripts/roll-migrate-stack.sh`.

**Does not own.** The audit chaining policy (the store only appends rows the
`AuditWriter` hands it, and the seq/hash are computed by the caller:
[`boltrig/kernel/audit.py:355`](../../../boltrig/kernel/audit.py) `"await self._store.audit_append(event)"`).
The knowledge fabric's own repository, which holds its own pool outside the
`PostgresStore` MRO:
[`boltrig/knowledge/postgres_repository.py:38`](../../../boltrig/knowledge/postgres_repository.py) `"@bind_tenant_on_store_methods"`.
The pgvector memory engine's schema application path
(`boltrig/memory/pgvector.py`), though the `vector` extension and the
`memory_vectors` tables are declared in this area's `schema.sql`.

**Forbidden imports, and the rule.** The store layer may not import
`boltrig.config`. The rule is stated in-source and is a stack-boundary rule
(SEC-54), which is why the production-signal check is duplicated inside the store:
[`boltrig/store/sealing.py:80`](../../../boltrig/store/sealing.py) `"store layer may NOT import boltrig.config (SEC-54 stack boundary"`.
Concretely `_production_signal` in `sealing.py` mirrors
`boltrig.config.environment.production_signal` by hand and the two must be kept
in lockstep.

**The one deliberate reach upward.** `postgres.py` imports
`boltrig.models` and `boltrig.models.errors` only; there is no import of
`boltrig.kernel`, `boltrig.api` or `boltrig.fleet` anywhere in
`boltrig/store/` (bounded: `rg -n "^from boltrig\.(kernel|api|fleet|config)" boltrig/store/`,
2026-08-24, pinned tree, no matches).

**The store is not the trajectory store.** The verbatim turn record is a separate
object with its own Protocol and its own two implementations, deliberately not
mixed into `Store`:
[`boltrig/store/trajectory.py:15`](../../../boltrig/store/trajectory.py) `"A STANDALONE STORE, NOT A MIXIN ON ``Store``"`,
because "every holder of a `Store` incidentally holds a handle to the unscrubbed
prompts" would be the alternative
[`boltrig/store/trajectory.py:21`](../../../boltrig/store/trajectory.py) `"incidentally holds a handle to"`.

## 4. Objects and contracts

### 4.1 The `Store` Protocol

`Store` is a `@runtime_checkable` Protocol assembled from 23 contract fragments
plus roughly 180 methods declared inline:
[`boltrig/store/base.py:101`](../../../boltrig/store/base.py) `"class Store(BudgetPolicyContract, PermanentFleetStoreContract"`.
The fragments are:

`BudgetPolicyContract`, `PermanentFleetStoreContract`, `BirthProfileStoreContract`,
`BackgroundJobStoreContract`, `AuditReadContract`, `IdempotencyStoreContract`,
`GuardedWritesContract`, `CapabilityStoreContract`, `RealtimeCallStoreContract`
(which itself composes `ArtifactStoreContract`, `IntegrationStoreContract` and
`DeviceStoreContract`:
[`boltrig/store/realtime_call_contract.py:14`](../../../boltrig/store/realtime_call_contract.py) `"ArtifactStoreContract, IntegrationStoreContract, DeviceStoreContract, Protocol"`),
`PasswordResetStoreContract`, `WorkflowTriggerStoreContract`,
`WorkflowScheduleStoreContract`, `AuthoredDefinitionStoreContract`,
`CapabilityRoutingStoreContract`, `EvalCaseStoreContract`,
`ExecutionSearchContract`, `CredentialReferenceContract`,
`AiKeyProposalStoreContract`, `ChannelGatewayStateContract`,
`ConversationStoreContract`, `AgentMailboxStoreContract`,
`McpLifecycleStoreContract`, `ModelEndpointStoreContract`.

**The declared surface is smaller than the implemented surface.** `Store` does
not declare the camera methods, yet both backends implement them and routes call
them off `kernel.store`:
[`boltrig/store/camera_pg.py:9`](../../../boltrig/store/camera_pg.py) `"async def upsert_camera_binding(self, binding):"`
and
[`boltrig/kernel/camera_agent_routes.py:232`](../../../boltrig/kernel/camera_agent_routes.py) `"claimed = await kernel.store.claim_camera_lease("`.
`ProvenanceStoreContract` is likewise defined and implemented but is not a base
of `Store` (bounded: `rg -n "camera|Provenance" boltrig/store/base.py`, no matches,
2026-08-24, pinned tree). A reimplementer following `base.py` alone would ship a
store the camera routes crash on.

### 4.2 Backend composition

Both backends are one class assembled from per-domain mixins. The graph is
nested, not flat, and the nesting is load-bearing to read:

```
PostgresStore                                   postgres.py:134
  EffectLedgerStorePG, ControlPlaneReadsPG, DistillationReadsPG,
  BudgetPolicyPG, BudgetUsagePG,
  WorkItemReadsPG -> ExecutionSearchPG,
  IdempotencyStorePG, GuardedWritesPG, PermanentFleetStorePG,
  BirthProfileStorePG, BackgroundJobStorePG,
  ChannelStorePG -> ChannelGatewayStatePG,
  CapabilityStorePG, ObservabilityReadsPG, ChannelDedupStorePG,
  ChannelOutboxStorePG -> RealtimeCallStorePG -> (ArtifactStorePG,
                          IntegrationStorePG, DeviceStorePG, CameraStorePG),
  PasswordResetStorePG, WorkflowTriggerStorePG, WorkflowScheduleStorePG,
  AuthoredDefinitionStorePG,
  CapabilityRoutingStorePG -> ProvenanceStorePG,
  EvalCaseStorePG, CredentialReferencePresencePG, AiKeyProposalStorePG,
  McpLifecycleStorePG, ModelEndpointStorePG, ConversationQueueStorePG,
  ConversationBindingStorePG,
  AgentMailboxStorePG -> (AgentRegistryStorePG, AgentTurnStorePG,
                          AgentMessageStorePG, AgentDeliveryClaimStorePG,
                          AgentDeliverySettleStorePG)
```

[`boltrig/store/postgres.py:134`](../../../boltrig/store/postgres.py) `"class PostgresStore("`,
[`boltrig/store/realtime_calls.py:58`](../../../boltrig/store/realtime_calls.py) `"class RealtimeCallStorePG(ArtifactStorePG, IntegrationStorePG, DeviceStorePG, CameraStorePG):"`.

`InMemoryStore` mirrors it exactly, minus `ControlPlaneReadsPG` (it defines
`list_orgs` directly) and minus `AgentDeliveryClaim/Settle` (folded into
`AgentMailboxStoreMem`):
[`boltrig/store/memory.py:107`](../../../boltrig/store/memory.py) `"class InMemoryStore("`.

**Measured parity of the public method surface.** An AST diff over every class in
`boltrig/store/` whose name ends `PG` or contains `Postgres` versus every class
whose name contains `Memory` yields 401 public PG methods, 396 public memory
methods, and exactly five methods present on Postgres and absent on memory:
`connect`, `close`, `readiness_snapshot`, `apply_rls`, `with_tenant`. Zero
methods exist on memory and not on Postgres (bounded: AST scan of
`boltrig/store/*.py`, 2026-08-24, pinned tree). All five are connection-lifecycle
or deployment-probe methods with no in-memory analogue.

### 4.3 The three connection-shaped objects

`PostgresStore.__init__` takes an `asyncpg.Pool` and one boolean,
`_assume_app_role`, set only by `connect()` when RLS is requested AND the
`boltrig_app` role exists:
[`boltrig/store/postgres.py:185`](../../../boltrig/store/postgres.py) `"store._assume_app_role = bool(await conn.fetchval("`.

`_RlsPool` is a facade over the pool: `fetch`/`fetchrow`/`execute` each open a
transaction, set `app.tenant_id` and optionally `SET LOCAL ROLE boltrig_app`,
then run the statement. `acquire()` and `close()` pass through unfenced, by
design:
[`boltrig/store/rls_pool.py:63`](../../../boltrig/store/rls_pool.py) `"async def _scoped(self, op: str, query: str, *args):"`,
[`boltrig/store/rls_pool.py:78`](../../../boltrig/store/rls_pool.py) `"def acquire(self):"`.

`with_tenant(tenant_id)` is an async context manager yielding a connection inside
a transaction with the role switched and the GUC set, for callers that need one
explicit transaction:
[`boltrig/store/postgres.py:218`](../../../boltrig/store/postgres.py) `"async def with_tenant(self, tenant_id: str):"`.

### 4.4 The sealed credential envelope

`{"sealed": "v1", "ct": "<fernet token>"}`, where `ct` is a Fernet token over
canonical JSON of the reference dict:
[`boltrig/store/sealing.py:75`](../../../boltrig/store/sealing.py) `"SEALED_VERSION = \"v1\""`,
[`boltrig/store/sealing.py:196`](../../../boltrig/store/sealing.py) `"payload = json.dumps(ref, sort_keys=True, separators=(\",\", \":\"))"`.
Key derivation is scrypt over a FIXED salt (`n=2**14, r=8, p=1, dklen=32`):
[`boltrig/store/sealing.py:111`](../../../boltrig/store/sealing.py) `"_SCRYPT_SALT = b\"boltrig.store.sealing.v2\""`.
A single unsalted SHA-256 derivation ("v1") is retained for DECRYPT ONLY and is
tried by `MultiFernet` after v2:
[`boltrig/store/sealing.py:118`](../../../boltrig/store/sealing.py) `"The ORIGINAL derivation: a single unsalted SHA-256."`,
[`boltrig/store/sealing.py:161`](../../../boltrig/store/sealing.py) `"fernets = [_passphrase_to_fernet_v2(key), _passphrase_to_fernet_v1(key)]"`.
The envelope carries no key id; the migration to v2 is lazy, on rewrite only, and
the source says so plainly: "until a row IS rewritten it remains v1"
[`boltrig/store/sealing.py:33`](../../../boltrig/store/sealing.py) `"migrates rows as they are rewritten - but until a"`.

## 5. Control flow

### 5.1 Opening the store (the boot path)

1. `build_store()` reads `DATABASE_URL`. Absent, it returns `InMemoryStore()`;
   present, it constructs a `PostgresStore` with `apply_schema=False` and
   `rls=is_truthy(BOLTRIG_RLS)`:
   [`boltrig/api/bootstrap.py:100`](../../../boltrig/api/bootstrap.py) `"return await PostgresStore.connect(settings.database_url, apply_schema=False, rls=rls)"`.
   **Failure branch:** a malformed DSN raises out of `asyncpg.create_pool`; the
   process does not start. A `postgresql+asyncpg://` DSN is normalised first:
   [`boltrig/store/postgres.py:117`](../../../boltrig/store/postgres.py) `"def normalize_dsn(dsn: str) -> str:"`.
2. `create_pool(..., init=_init_conn, min_size=1, max_size=10)`. `_init_conn`
   registers a JSONB codec so dict/list parameters round-trip:
   [`boltrig/store/postgres.py:128`](../../../boltrig/store/postgres.py) `"async def _init_conn(conn: asyncpg.Connection) -> None:"`.
   **Failure branch:** connection refusal raises; readiness never gets a store.
3. If `apply_schema` (never true from the runtime path), execute `schema.sql`
   verbatim:
   [`boltrig/store/postgres.py:178`](../../../boltrig/store/postgres.py) `"await conn.execute(_SCHEMA.read_text(encoding=\"utf-8\"))"`.
   The docstring states the rule: "Production application wiring always passes
   ``False`` and relies on Alembic, so a process restart can never mutate or
   silently advance the catalogue"
   [`boltrig/store/postgres.py:170`](../../../boltrig/store/postgres.py) `"process restart can never mutate or silently advance the catalogue."`.
4. If `rls`, probe `pg_roles` once for `boltrig_app` and wrap the pool in
   `_RlsPool(pool, assume_role=...)`:
   [`boltrig/store/postgres.py:186`](../../../boltrig/store/postgres.py) `"SELECT 1 FROM pg_roles WHERE rolname = 'boltrig_app'"`.
   **Failure branch:** the role does not exist, so `assume_role` is False and the
   `SET LOCAL ROLE` is skipped. The GUC is still set, but under an owning
   superuser the policies do nothing (see 9.2). This is a silent degradation to
   "labelled but unenforced".

### 5.2 A tenant-scoped read or write (RLS on)

1. The class decorator `@bind_tenant_on_store_methods` wrapped every public
   tenant-carrying coroutine at import time:
   [`boltrig/store/postgres.py:133`](../../../boltrig/store/postgres.py) `"@bind_tenant_on_store_methods"`.
   It skips names starting `_`, skips `with_tenant`, and skips any method with
   fewer than two parameters:
   [`boltrig/store/tenant_scope.py:132`](../../../boltrig/store/tenant_scope.py) `"if name.startswith(\"_\") or name == \"with_tenant\":"`.
2. On call, the wrapper reads the FIRST positional argument (or the first
   parameter by name from kwargs), extracts a tenant from a `str` or from
   `.tenant_id`, and sets the `_current_tenant` contextvar for the call:
   [`boltrig/store/tenant_scope.py:70`](../../../boltrig/store/tenant_scope.py) `"tenant_id = _tenant_of(candidate)"`.
   **Failure branch:** no discoverable tenant leaves the contextvar untouched, so
   the call inherits whatever the request context set, or `''`. The source is
   explicit that this "only ever narrows"
   [`boltrig/store/tenant_scope.py:52`](../../../boltrig/store/tenant_scope.py) `"so this only ever narrows."`.
3. The method body calls `self._pool.fetch/fetchrow/execute`. Under `_RlsPool`
   that opens a transaction, runs `SET LOCAL ROLE boltrig_app` when armed, then
   `select set_config('app.tenant_id', $1, true)` with the bound tenant or `''`:
   [`boltrig/store/rls_pool.py:38`](../../../boltrig/store/rls_pool.py) `"_current_tenant.get() or \"\""`.
   **Failure branch:** an empty GUC makes every `tenant_id = current_setting(...)`
   predicate false, so reads return zero rows and writes violate `WITH CHECK`.
   That is fail-closed by construction and is stated as such:
   [`boltrig/store/rls_pool.py:27`](../../../boltrig/store/rls_pool.py) `"An unset tenant becomes"`.
4. Methods holding their own transaction bypass `_scoped` and must call
   `bind_conn_to_tenant(conn, tenant_id, pool=self._pool)` explicitly, which does
   the role switch and the GUC with the tenant passed EXPLICITLY, not read from
   the contextvar:
   [`boltrig/store/tenant_scope.py:117`](../../../boltrig/store/tenant_scope.py) `"await conn.execute(\"SELECT set_config('app.tenant_id', $1, true)\", tenant_id)"`.

### 5.3 A credential reference write and read

1. Caller hands `set_credential_ref(tenant_id, cred_id, ref: dict)` a plain dict,
   which may contain inline secret material (TOTP base32, an AI key, a legacy
   channel signing secret):
   [`boltrig/store/sealing.py:4`](../../../boltrig/store/sealing.py) `"three writers (TOTP enrolment, per-org AI keys, legacy channel"`.
2. `seal_ref(ref)` is applied at the store seam before the INSERT. Already-sealed
   envelopes are returned unchanged (idempotent), so a read-modify-write never
   double-seals:
   [`boltrig/store/sealing.py:191`](../../../boltrig/store/sealing.py) `"an already-sealed envelope is returned unchanged"`.
3. `_active_fernets()` resolves `BOLTRIG_SEAL_KEY` (+ optional
   `BOLTRIG_SEAL_KEY_PREVIOUS`). **Failure branch:** unset or equal to the
   in-source `dev-insecure-seal-key` under a production signal raises
   `RuntimeError` naming the signal, never the key:
   [`boltrig/store/sealing.py:173`](../../../boltrig/store/sealing.py) `"if signal is not None and (not key or key == _DEV_SEAL_KEY):"`.
4. The row is upserted with the sealed envelope in `data` and the non-secret
   `store`/`ref` metadata in typed columns:
   [`boltrig/store/postgres.py:809`](../../../boltrig/store/postgres.py) `"cred_id, tenant_id, ref.get(\"store\", \"env\"), ref.get(\"ref\", \"\"), seal_ref(ref),"`.
5. `get_credential_ref` unseals transparently. A row whose `data` is NULL falls
   back to the `{store, ref}` pair:
   [`boltrig/store/postgres.py:796`](../../../boltrig/store/postgres.py) `"return unseal_ref(row[\"data\"])"`.
   **Failure branch:** a tampered or wrong-key envelope raises
   `CredentialResolution` and the error carries no ciphertext and no key hint:
   [`boltrig/store/sealing.py:216`](../../../boltrig/store/sealing.py) `"\"sealed credential reference cannot be unsealed (wrong key or tampered row)\""`.
   A legacy plaintext row without the marker is returned verbatim, which is the
   read-compatibility path and also the honest limit of the "no plaintext at
   rest" claim until every row is rewritten.
6. `has_credential_ref` is a presence probe that never selects the encrypted
   column:
   [`boltrig/store/credential_references.py:60`](../../../boltrig/store/credential_references.py) `"\"SELECT 1 FROM credential_refs WHERE tenant_id=$1 AND id=$2\","`.

### 5.4 The audit append (store side)

1. `AuditWriter.write` scrubs, takes a per-tenant in-process asyncio lock, calls
   `audit_head` to get `(seq, prev_hash)`, computes the HMAC, and calls
   `audit_append`:
   [`boltrig/kernel/audit.py:348`](../../../boltrig/kernel/audit.py) `"head_seq, prev_hash = await self._store.audit_head(event.tenant_id)"`.
2. `audit_head` is `ORDER BY seq DESC LIMIT 1`, returning `(0, None)` on an empty
   chain:
   [`boltrig/store/postgres.py:630`](../../../boltrig/store/postgres.py) `"async def audit_head(self, tenant_id):"`.
3. `audit_append` is a plain INSERT of 26 columns. There is no ON CONFLICT and no
   retry inside the store:
   [`boltrig/store/postgres.py:639`](../../../boltrig/store/postgres.py) `"async def audit_append(self, e: AuditEvent):"`.
   The only cross-process serialiser is the table's `UNIQUE (tenant_id, seq)`:
   [`boltrig/store/schema.sql:574`](../../../boltrig/store/schema.sql) `"UNIQUE (tenant_id, seq)"`.
   **Failure branch:** a second replica losing the seq race raises a unique
   violation, which the writer catches and defers to `audit_outbox`, clearing
   seq/prev_hash/hash first so the janitor re-chains against the then-current
   head:
   [`boltrig/kernel/audit.py:358`](../../../boltrig/kernel/audit.py) `"re-derives seq/prev_hash/hash at drain time against the head as of"`.
4. `audit_outbox_enqueue` writes the scrubbed payload as JSONB on the SAME
   tenant-bound connection the faulted append used:
   [`boltrig/store/postgres.py:656`](../../../boltrig/store/postgres.py) `"Rides the same tenant-scoped connection the faulted append was using"`.
   **Failure branch:** if the outbox write itself fails, the exception propagates
   and the dispatch-side guard treats it as a governance incident. That is the
   genuinely unaudited case.

### 5.5 Applying a migration on roll

1. `stage_migrations()` copies `alembic.ini`, `migrations/` and
   `roll-migrate-stack.sh` to `/tmp/roll-mig` on the target host over scp. It is a
   FILE, not a heredoc, because a heredoc once arrived empty and the gate no-opped
   while returning 0:
   [`scripts/roll-migrate-stack.sh:11`](../../../scripts/roll-migrate-stack.sh) `"WHY THIS IS A FILE AND NOT A HEREDOC INSIDE roll-release.sh."`.
2. The gate reads the TARGET IMAGE's `EXPECTED_ALEMBIC_HEAD` by running the image:
   [`scripts/roll-migrate-stack.sh:48`](../../../scripts/roll-migrate-stack.sh) `"WANT=$(docker run --rm \"$IMG\" \\"`.
   **Failure branch:** an empty result exits 1 with "could not read
   EXPECTED_ALEMBIC_HEAD from the target image".
3. `DATABASE_URL` is read out of the running kernel container into a shell
   variable and never interpolated into an ssh command line:
   [`scripts/roll-migrate-stack.sh:52`](../../../scripts/roll-migrate-stack.sh) `"DBURL=$(docker exec \"$C\" printenv DATABASE_URL 2>/dev/null)"`.
4. `alembic current` is parsed by SHAPE (a four-digit-prefixed token) rather than
   `tail -1`, so a banner change cannot be read as a revision:
   [`scripts/roll-migrate-stack.sh:65`](../../../scripts/roll-migrate-stack.sh) `"| awk 'match($0,/[0-9]{4}_[a-z0-9_]+/)"`.
5. If HAVE equals WANT, exit 0 with nothing applied. Otherwise run
   `alembic upgrade '<WANT>'` inside a throwaway container joined to the stack's
   own compose network, with `/tmp/roll-mig` mounted read-only:
   [`scripts/roll-migrate-stack.sh:78`](../../../scripts/roll-migrate-stack.sh) `"run \"python -m alembic upgrade '$WANT'\""`.
   It migrates to the IMAGE's head, not `head`, because the repo can be ahead of
   the release being rolled:
   [`scripts/roll-migrate-stack.sh:19`](../../../scripts/roll-migrate-stack.sh) `"WHY IT MIGRATES TO THE IMAGE'S HEAD, NOT `upgrade head`."`.
6. Re-read the head. **Failure branch:** if it still differs, abort non-zero and
   say that a database found AHEAD of its image is a rollback needing a human and
   a verified dump:
   [`scripts/roll-migrate-stack.sh:83`](../../../scripts/roll-migrate-stack.sh) `"If the database is AHEAD, this is a rollback: it needs a human and a"`.
7. `migrate_stack` dies on a non-zero gate and nothing is deployed for that stack:
   [`scripts/roll-release.sh:234`](../../../scripts/roll-release.sh) `"|| die \"migration gate failed for $P - NOTHING was deployed for this stack\""`.

### 5.6 The Alembic environment

`migrations/env.py` resolves the URL from `DATABASE_URL`, then
`BOLTRIG_DATABASE_URL`, then `BOLTRIG_TEST_DATABASE_URL`, then a hard default of
`postgresql://localhost/boltrig`:
[`migrations/env.py:25`](../../../migrations/env.py) `"os.environ.get(\"DATABASE_URL\")"`.
Any `postgresql+<driver>://` scheme is rewritten to `postgresql+psycopg://`
because the baseline is a multi-statement bootstrap asyncpg cannot execute as one
prepared operation:
[`migrations/env.py:32`](../../../migrations/env.py) `"def _sync_url() -> str:"`,
[`migrations/env.py:9`](../../../migrations/env.py) `"hash-locked psycopg driver because the"`.
**Failure branch:** with no env var set, migrations silently target
`postgresql://localhost/boltrig`. There is no guard that refuses an unset URL.

## 6. Data

### 6.1 The catalogue at a glance

`boltrig/store/schema.sql` declares **138 tables** and 108 indexes across 2,892
lines, with 57 `REFERENCES` clauses (bounded: `grep -c` on the pinned file,
2026-08-24). It opens by requiring pgvector:
[`boltrig/store/schema.sql:12`](../../../boltrig/store/schema.sql) `"CREATE EXTENSION IF NOT EXISTS vector;"`.
`migrations/baseline.sql` declares 27 tables and is frozen (see 6.6).

Universal conventions, stated at the top of the file and held throughout:
"All tables carry tenant_id, created_at, updated_at. Timestamps are
timezone-aware (UTC)"
[`boltrig/store/schema.sql:2`](../../../boltrig/store/schema.sql) `"All tables carry tenant_id, created_at, updated_at."`.
Four tables break the `tenant_id` half deliberately: `organisations` (its `id` IS
the tenant id), `identity_orgs` (keyed by normalised email), and the two
pre-tenant lookups below. Many tables also omit `updated_at` (for example
`audit_log`, `memory_items`, `channels`), so the header is aspirational rather
than exact.

### 6.2 Table inventory by domain

Line numbers are `boltrig/store/schema.sql`. "AO" marks a table the schema or the
RLS overlay describes as append-only. "R" marks a row whose retention is bounded
by something in the tree; "none" means nothing in the tree deletes it.

**Registry and capability routing.**
`nouns` (17), `verbs` (28), `verb_bindings` (46), `provider_connections` (73),
`source_operations` (101), `capability_bindings` (123), `routing_policies` (162),
`entity_provenance` (187), `adapters` (225), `integration_catalogue` (244),
`integration_connections` (266), `skills` (298), `agent_capabilities` (314),
`workflow_definitions` (350), `model_endpoints` (373). Retention: none; these are
control-plane desired state. `agent_capabilities` deliberately has NO primary key
so two workspaces can each own a "researcher", with a coalesced unique index
instead:
[`boltrig/store/schema.sql:341`](../../../boltrig/store/schema.sql) `"There is deliberately NO primary key"`.
`entity_provenance`'s unique index IS the idempotency, and `workspace_id` is
coalesced into it because Postgres treats NULLs as distinct:
[`boltrig/store/schema.sql:205`](../../../boltrig/store/schema.sql) `"THIS INDEX IS THE IDEMPOTENCY."`.

**Work and execution.**
`work_items` (392), `run_checkpoints` (435), `fanout_counters` (448),
`run_cancel_requests` (462), `workflow_run_records` (2168), `run_effects` (2874).
`work_items` carries the lease pair (`lease_owner`, `lease_expires_at`), an
`attempts` counter, a `degraded` flag and a terminal `result` JSONB. Retention:
none. `run_effects` is the durable undo ledger, `(tenant_id, run_id, seq)` keyed,
with `inverse_verb NULL` meaning `not_undoable` recorded honestly:
[`boltrig/store/schema.sql:2872`](../../../boltrig/store/schema.sql) `"inverse NULL = not_undoable (recorded honestly, never omitted)"`.

**HITL.** `hitl_requests` (473), `hitl_responses` (510). `hitl_requests` carries
the SEC-14 binding columns (`verb`, `requested_by`, `requested_on_behalf_of`,
`request_fingerprint`, `action_digest`) and the SEC-181 secure-input pair
(`secure`, `secure_purpose`) where the answer is sealed and never recorded:
[`boltrig/store/schema.sql:493`](../../../boltrig/store/schema.sql) `"secure-input question (answer is sealed, never recorded)"`.
Retention: expiry flips status to `timed_out`; rows are never deleted.

**Audit and security.** `audit_log` (542) **AO**, `audit_outbox` (590),
`security_log` (607) **AO**, `audit_rollup_anchors` (636), `config_revisions`
(763) **AO**, `execution_events` (2311) **AO**. `audit_log` and `security_log`
are per-tenant hash chains with `UNIQUE (tenant_id, seq)` and `prev_hash -> hash`.
The Opbox-depth enrichment columns are all nullable and backfilled NULL so a
pre-enrichment row still hashes identically:
[`boltrig/store/schema.sql:565`](../../../boltrig/store/schema.sql) `"the writer folds a field into the hash only when non-None"`.
`audit_outbox` deliberately stores NO chain fields:
[`boltrig/store/schema.sql:586`](../../../boltrig/store/schema.sql) `"Chain fields (seq/prev_hash/hash) are deliberately NOT"`.
Retention: audit and security are permanent and explicitly EXEMPT from the
retention purge (6.5). `audit_outbox` rows are deleted by the drain.

**Idempotency and cost.** `idempotency_keys` (653), `budgets` (673),
`budget_usage` (688). `budgets.spent_tokens`/`spent_micros` are marked legacy;
live usage lives in `budget_usage`, keyed `(tenant_id, scope_id, window_key)`
with CHECK constraints forcing non-negative accumulators:
[`boltrig/store/schema.sql:695`](../../../boltrig/store/schema.sql) `"spent_tokens       BIGINT NOT NULL DEFAULT 0 CHECK (spent_tokens >= 0),"`.
Retention: none for either. `idempotency_keys` has a `lease_expires_at` but no
sweeper (see RISKS).

**Credentials and permissions.** `credential_refs` (713), `tenant_permissions`
(728). `credential_refs.data` is the only column in the catalogue that holds
encrypted secret material:
[`boltrig/store/schema.sql:713`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS credential_refs ("`,
[`boltrig/store/schema.sql:707`](../../../boltrig/store/schema.sql) `"Secret references only - never plaintext secrets at rest (SEC-04, FR-SEC-02)."`.
Retention: `expires_at` is for rotation ALERTS only; nothing deletes on it.
Run-scoped secure-input refs (`run:<run_id>:<purpose>`) are deleted wholesale by
`delete_credential_refs_for_run`, which uses `strpos(...) = 1` rather than LIKE so
there are no wildcards to escape:
[`boltrig/store/postgres.py:822`](../../../boltrig/store/postgres.py) `"\"DELETE FROM credential_refs WHERE tenant_id=$1 AND strpos(id, $2) = 1\","`.

**Conversations.** `conversations` (738), `conversation_messages` (1426),
`conversation_steer_queue` (1447), `conversation_summaries` (1475) **AO**.
`conversation_summaries` is documented INSERT-only: "a re-compaction appends a new
row covering more messages; no row is ever updated"
[`boltrig/store/schema.sql:1472`](../../../boltrig/store/schema.sql) `"appends a new row covering more messages; no row is ever updated"`,
and the code matches (INSERT, SELECT, and DELETE only from the purge; bounded:
`rg -n "conversation_summaries" boltrig/store/*.py`, 4 hits, 2026-08-24).
Retention: hard purge at `privacy.retention_days` for CLOSED threads (6.5).

**Channels.** `channels` (971), `channel_gateway_status` (989),
`channel_gateway_leases` (1005), `channel_bindings` (1020), `channel_pairings`
(1036), `channel_deliveries` (1056), `channel_outbox` (1202). `channels` has a
bare `TEXT PRIMARY KEY` id and is RLS-excluded: the inbound path resolves the
tenant from the unguessable channel id before any tenant is bound:
[`boltrig/store/schema.sql:968`](../../../boltrig/store/schema.sql) `"This table is DELIBERATELY RLS-EXCLUDED (like personal_access_tokens):"`.
`channel_deliveries` is the replay-dedup marker with `expires_at`, evicted
opportunistically on the next write, not by a janitor:
[`boltrig/store/channel_dedup.py:37`](../../../boltrig/store/channel_dedup.py) `"\"DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()\","`.

**Workflow triggers and schedules.** `workflow_triggers` (1070),
`workflow_trigger_deliveries` (1105), `workflow_schedules` (1127),
`workflow_schedule_occurrences` (1157). `workflow_triggers` enforces a shape CHECK:
a webhook trigger must have a 64-hex `secret_hash` and no channel; a channel
trigger must have a channel and no secret:
[`boltrig/store/schema.sql:1087`](../../../boltrig/store/schema.sql) `"CONSTRAINT workflow_trigger_shape CHECK ("`.
`workflow_schedule_occurrences` enforces a lease shape CHECK so a `claimed` row
must carry both lease columns and a non-claimed row must carry neither:
[`boltrig/store/schema.sql:1183`](../../../boltrig/store/schema.sql) `"CONSTRAINT workflow_schedule_occurrence_lease_shape CHECK ("`.
Retention: none.

**Realtime, devices, cameras.** `realtime_calls` (1223), `realtime_call_events`
(1253), `device_enrollments` (1271), `devices` (1280), `device_roots` (1300),
`device_leases` (1313), `camera_bindings` (2796), `camera_leases` (2816). Every
bearer here is digest-only and CHECK-constrained to 64 hex:
[`boltrig/store/schema.sql:1278`](../../../boltrig/store/schema.sql) `"CHECK (authorization_code_hash ~ '^[0-9a-f]{64}$')"`.
`realtime_calls.media_token_hash` is cleared atomically on the first successful
gateway claim:
[`boltrig/store/schema.sql:1222`](../../../boltrig/store/schema.sql) `"digest and is cleared atomically on the first successful gateway claim."`.
`device_leases` and `camera_leases` are FK'd to `hitl_requests` ON DELETE RESTRICT
and unique on `approval_id`, so one approval can authorise exactly one lease.
Retention: none; `expires_at` gates use, not deletion.

**Memory.** `memory_items` (1349), `memory_facts` (1999), `memory_events` (2040)
**AO**, `memory_ingestions` (2059), `memory_erasures` (2074),
`memory_projection_statuses` (2088), `memory_vectors` (2140),
`memory_vector_edges` (2156). `memory_facts` carries the typed-plane state machine
with two partial unique indexes enforcing one active row per slot for
`semantic` and `procedural` kinds:
[`boltrig/store/schema.sql:2028`](../../../boltrig/store/schema.sql) `"CREATE UNIQUE INDEX IF NOT EXISTS one_active_semantic_fact_per_slot"`.
`memory_vectors.embedding` is `vector(256)`, pinned to `HashingEmbedder.DEFAULT_DIM`:
[`boltrig/store/schema.sql:2137`](../../../boltrig/store/schema.sql) `"embedding dimension (256) matches HashingEmbedder's DEFAULT_DIM"`.
Retention: `memory_erasures` is a ledger of erasure requests; facts hard-erase.

**Named-agent federation.** `named_agents` (1492), `agent_turn_leases` (1542),
`agent_turn_waiters` (1558), `agent_sessions` (1569), `agent_messages` (1578)
**AO by prose**, `agent_message_deliveries` (1599), `agent_session_summaries`
(1616). `agent_messages` CHECKs `sender <> recipient`, a kind in
`ask|tell|reply`, and `octet_length(content) BETWEEN 1 AND 32768`:
[`boltrig/store/schema.sql:1591`](../../../boltrig/store/schema.sql) `"CHECK (sender <> recipient), CHECK (kind IN ('ask','tell','reply')),"`.
The design separates immutable envelope from mutable delivery state so a lease
transition never rewrites authored content:
[`boltrig/store/schema.sql:1490`](../../../boltrig/store/schema.sql) `"Message envelopes are immutable. Claim/retry state lives separately"`.

**Identity and tenancy.** `users` (1638), `personal_access_tokens` (1659),
`user_invitations` (1680), `user_credentials` (1711), `password_reset_tokens`
(1723), `user_settings` (1738), `user_sessions` (1751), `user_totp` (1780),
`user_recovery_codes` (1793), `two_factor_challenges` (1806), `organisations`
(1826), `workspaces` (1842), `org_members` (1865), `workspace_members` (1876),
`identity_orgs` (1911), `role_mappings` (530). `workspace_members` has
`tenant_id` in the PRIMARY KEY specifically because every org provisions the same
`ws_default` id, so a two-column key collides across orgs by construction:
[`boltrig/store/schema.sql:1886`](../../../boltrig/store/schema.sql) `"collides across orgs BY CONSTRUCTION: one org's membership upsert would"`.
Retention: none anywhere in this group. `two_factor_challenges` and
`password_reset_tokens` carry `expires_at` and are deleted on use, not on expiry.

**AI keys.** `ai_configs` (1928), `ai_key_secret_proposals` (1945).
`ai_configs` has NO plaintext key column, only `credential_ref`:
[`boltrig/store/schema.sql:1924`](../../../boltrig/store/schema.sql) `"THE RAW KEY IS NEVER STORED HERE (no plaintext key column)"`.
`ai_key_secret_proposals` is bounded to at most 15 minutes and has a state-shape
CHECK tying `status` to whether `secret_ref` and `consumed_at` are set:
[`boltrig/store/schema.sql:1978`](../../../boltrig/store/schema.sql) `"CONSTRAINT ai_key_secret_proposal_state_shape CHECK ("`.

**Execution ledger and grants.** `execution_root_runs` (2179) through
`capability_attestation_entries` (2600): 24 tables covering phases, work items,
assignments, results, verifications, commands, events, an outbox, runtime
identities, three Codex binding tables, root engine decisions, grant leases and
their cancellation sets, model-proxy grants and their four cancellation sets, and
capability attestation sets and entries. All keyed on
`(tenant_id, workspace_id, root_run_id, ...)` and all carrying
`engine_owner TEXT NOT NULL DEFAULT 'boltrig'`. Bearers are digests only
(`grant_leases.token_digest`, `model_proxy_grants.bearer_digest`).

**Knowledge fabric.** `knowledge_uploads` (2624) through
`knowledge_projection_outbox` (2735): 13 tables. Originals live outside Postgres;
`knowledge_blobs.object_key` names them.
`knowledge_segments.search_vector` is a STORED generated tsvector with a GIN
index:
[`boltrig/store/schema.sql:2679`](../../../boltrig/store/schema.sql) `"search_vector TSVECTOR GENERATED ALWAYS AS"`.

**Artifacts.** `artifacts` (2747). Bytes live INLINE in a `content BYTEA` column
with a CHECK that `octet_length(content) = size` and `size BETWEEN 0 AND
104857600` (100 MB):
[`boltrig/store/schema.sql:2766`](../../../boltrig/store/schema.sql) `"size BETWEEN 0 AND 104857600 AND octet_length(content)=size"`.
The name is CHECK-constrained against path traversal and control characters; the
digest must be 64 hex; the revision chain is enforced by
`(revision=1) = (previous_revision_id IS NULL)` plus a UNIQUE on
`previous_revision_id`. Retention: none.

**Trajectory.** `trajectory_events` (2843). Verbatim prompts, contexts, reasoning,
messages, tool calls, tool results and errors, with `expires_at` and an expiry
index. Deliberately NOT part of the audit hash chain:
[`boltrig/store/schema.sql:2839`](../../../boltrig/store/schema.sql) `"records: opt-in, expiring, purgeable, and deliberately NOT part of the audit"`.

**Operational receipts.** `permanent_fleet_observations` (779),
`birth_profile_receipts` (804), `background_job_receipts` (857), `eval_cases`
(915), `eval_runs` (927), `notification_prefs` (941), `personal_agents` (955),
`mcp_servers` (1367), `mcp_probe_receipts` (1398). These carry the heaviest CHECK
constraints in the catalogue. `birth_profile_receipts` forces every identity to a
prefixed 24-hex shape and forces `expires_at <= observed_at + interval '1 hour'`:
[`boltrig/store/schema.sql:848`](../../../boltrig/store/schema.sql) `"AND expires_at <= observed_at + interval '1 hour'"`.
`background_job_receipts` CHECKs the job name against a closed set of eight and
ties `last_outcome` to which timestamp equals `last_attempt_at`:
[`boltrig/store/schema.sql:860`](../../../boltrig/store/schema.sql) `"CHECK (job_name IN ('hitl_expiry','retention','distillation',"`,
[`boltrig/store/schema.sql:897`](../../../boltrig/store/schema.sql) `"CONSTRAINT background_job_outcome_shape CHECK ("`.
Both are bounded in row count by an in-transaction advisory lock plus a prune:
[`boltrig/store/background_jobs.py:295`](../../../boltrig/store/background_jobs.py) `"SELECT pg_advisory_xact_lock("`.

### 6.3 Columns holding credential or secret material

| table.column | what it holds | protection | line |
| --- | --- | --- | --- |
| `credential_refs.data` | the ONLY inline secret material at rest | Fernet envelope, scrypt-derived key from `BOLTRIG_SEAL_KEY`, kernel-held | 713 |
| `user_credentials.password_hash` | argon2id PHC string | one-way; kept in its own table so it cannot ride a user view/export | 1711 |
| `personal_access_tokens.token_hash` | sha256 of the PAT | one-way; unique index; RLS-EXCLUDED table | 1659 |
| `user_sessions.token_hash` | sha256 of the session cookie secret | one-way; partial unique index | 1751 |
| `user_sessions.csrf_token` | the session-bound double-submit CSRF token | **stored in plaintext**; no hash, no digest | 1751 |
| `user_recovery_codes.code_hash` | sha256 of a one-time recovery code | one-way; single-use via `used_at` | 1793 |
| `two_factor_challenges.token_hash` | sha256 of the pre-session challenge | one-way; short-lived; deleted on use | 1806 |
| `user_totp.secret_ref` | id into `credential_refs` | the base32 secret is SEALED elsewhere, never here | 1780 |
| `password_reset_tokens.token_hash` | sha256, CHECK'd to 64 hex | one-way; one row per identity so a new token invalidates the old | 1723 |
| `user_invitations.token_hash` | sha256 of a single-use invite token | one-way; unique index where non-null | 1680 |
| `channels.credential_ref` | reference only | RLS-excluded table; material lives in `credential_refs` | 971 |
| `channel_pairings.code_hash` | hash of a one-time pairing code | one-way; TTL + attempt lockout | 1036 |
| `workflow_triggers.secret_hash` | sha256 of the webhook bearer, CHECK'd 64 hex | one-way; shown once | 1070 |
| `realtime_calls.media_token_hash` | sha256 of the media bearer | one-way; cleared on first claim | 1223 |
| `device_enrollments.authorization_code_hash` | sha256, CHECK'd 64 hex | one-way; `consumed_at` single-use | 1271 |
| `devices.session_token_hash` | sha256, CHECK'd 64 hex | one-way; unique per tenant | 1280 |
| `device_leases.claim_token_hash`, `camera_leases.claim_token_hash` | sha256, CHECK'd 64 hex | one-way | 1313, 2816 |
| `ai_configs.credential_ref` | reference only | no plaintext key column exists | 1928 |
| `ai_key_secret_proposals.secret_ref`, `.secret_digest` | ref into sealed store, plus a sha256 | state CHECK forces `secret_ref` NULL once consumed | 1945 |
| `integration_connections.credential_ref`, `provider_connections.credential_ref` | reference only | material lives in `credential_refs` | 266, 73 |
| `grant_leases.token_digest`, `model_proxy_grants.bearer_digest` | digests | one-way | 2431, 2494 |
| `mcp_servers.credential` | legacy nullable TEXT | **no writer and no reader in the tree** (see RISKS) | 1367 |

Non-secret but sensitive at rest, with no encryption: `artifacts.content` (raw
bytes), `conversation_messages.content`, `knowledge_segments.text`,
`trajectory_events.payload` (verbatim prompts and tool payloads),
`memory_facts.content`. Only `credential_refs.data` is encrypted; nothing else in
the catalogue is.

### 6.4 Row-level security overlay

`rls.sql` is OPT-IN and is not part of the `schema.sql` boot:
[`boltrig/store/rls.sql:4`](../../../boltrig/store/rls.sql) `"OPT-IN. This is NOT part of the default schema.sql boot."`.
Three things it does:

1. Creates `boltrig_app` as `NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
   NOCREATEROLE` and grants it DML on all tables and sequences:
   [`boltrig/store/rls.sql:23`](../../../boltrig/store/rls.sql) `"CREATE ROLE boltrig_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;"`.
2. REVOKEs `UPDATE, DELETE` from exactly four append-only tables:
   `audit_log`, `security_log`, `config_revisions`, `execution_events`:
   [`boltrig/store/rls.sql:41`](../../../boltrig/store/rls.sql) `"append_only text[] := ARRAY["`.
3. Enables and FORCEs row security with one `tenant_isolation` policy per table
   over a hand-maintained list of 134 tables, plus `organisations` handled
   separately on `id`:
   [`boltrig/store/rls.sql:193`](../../../boltrig/store/rls.sql) `"'USING (tenant_id = current_setting(''app.tenant_id'', true)) '"`,
   [`boltrig/store/rls.sql:216`](../../../boltrig/store/rls.sql) `"CREATE POLICY tenant_isolation ON organisations"`.

**The exclusion set is exactly four tables, and I verified it by set difference.**
Sorting the 138 `CREATE TABLE` names in `schema.sql` against the quoted names in
the `rls.sql` scoped array plus the `organisations` block leaves exactly:
`channels`, `identity_orgs`, `organisations` (handled separately), and
`personal_access_tokens`. No schema table is unfenced and unexcused (bounded:
`comm -23` over both sorted name sets, 2026-08-24, pinned tree). The three real
exclusions are each resolved by an unguessable key BEFORE a tenant is bound, and
the same set is pinned as `DOCUMENTED_RLS_EXCLUSIONS` in the drift guard:
[`tests/security/test_rls_fence_coverage.py:52`](../../../tests/security/test_rls_fence_coverage.py) `"DOCUMENTED_RLS_EXCLUSIONS = frozenset("`.

**Fourteen migrations also create policies, unconditionally.** 0041, 0042, 0043,
0044, 0045, 0056, 0058, 0059, 0061, 0062, 0063, 0068 and 0074 each run
`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY
tenant_isolation` on the tables they add, with no guard on whether the deployment
opted into RLS:
[`migrations/versions/0044_artifacts.py:63`](../../../migrations/versions/0044_artifacts.py) `"ALTER TABLE artifacts FORCE ROW LEVEL SECURITY;"`,
[`migrations/versions/0041_realtime_calls.py:65`](../../../migrations/versions/0041_realtime_calls.py) `"EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);"`.
0022 is the exception: it is conditional on `nouns` already having row security:
[`migrations/versions/0022_schema_parity.py:196`](../../../migrations/versions/0022_schema_parity.py) `"IF COALESCE(rls_was_enabled, false) THEN"`.
The consequence is in RISKS.

### 6.5 Retention, by table

The only retention machinery in the tree is the conversation purge and the
opportunistic dedup eviction.

- `conversations`, `conversation_messages`, `conversation_summaries`: hard-deleted
  when `status='closed'` and `updated_at <= now - retention_days`, default 30
  days, from `privacy.retention_days` in the manifest:
  [`boltrig/fleet/retention.py:57`](../../../boltrig/fleet/retention.py) `"DEFAULT_RETENTION_DAYS = 30"`,
  [`boltrig/store/postgres.py:993`](../../../boltrig/store/postgres.py) `"\"\"\"SELECT id FROM conversations"`.
  Executed in ONE transaction with `FOR UPDATE`, children first, so a crash
  mid-purge cannot strand a conversation whose messages are already gone:
  [`boltrig/store/postgres.py:987`](../../../boltrig/store/postgres.py) `"One atomic transaction: a crash mid-purge cannot strand a conversation"`.
- `audit_log`: EXEMPT and never purged. Erasing the chain would break `verify()`:
  [`boltrig/fleet/retention.py:10`](../../../boltrig/fleet/retention.py) `"The audit log is EXEMPT and never purged here"`.
- `channel_deliveries`: TTL rows evicted on the next `record_channel_delivery`
  write for that tenant, not by a janitor.
- `background_job_receipts`, `birth_profile_receipts`, `mcp_probe_receipts`:
  bounded by an in-transaction prune to a per-key cap.
- `audit_outbox`: rows deleted by the drain on success.
- **Everything else: no retention at all.** Notably `idempotency_keys`,
  `trajectory_events`, `two_factor_challenges`, `password_reset_tokens`,
  `channel_pairings`, `device_enrollments`, `work_items`, `artifacts`,
  `run_effects`, `workflow_trigger_deliveries` (bounded: `rg -n "purge|DELETE FROM"`
  across `boltrig/store/` and `boltrig/fleet/`, 2026-08-24, pinned tree; the only
  scheduled deleters are the retention janitor and the audit-outbox drain).

The retention janitor was, for its whole existence until 2026-07-26, wired into
nothing, and the module says so at length:
[`boltrig/fleet/retention.py:31`](../../../boltrig/fleet/retention.py) `"``purge_closed_conversations`` had never once been called"`.
It is now started by the fleet worker on `BOLTRIG_RETENTION_INTERVAL`:
[`boltrig/api/worker.py:156`](../../../boltrig/api/worker.py) `"def _start_retention_janitor("`.

### 6.6 The migration ledger

**Head is `0086_conversation_addressing`.** The packaged constant agrees:
[`boltrig/api/readiness.py:27`](../../../boltrig/api/readiness.py) `"EXPECTED_ALEMBIC_HEAD = \"0086_conversation_addressing\""`,
and a test graph-checks the constant against `ScriptDirectory.get_current_head()`:
[`tests/integration/test_migration_parity.py:43`](../../../tests/integration/test_migration_parity.py) `"assert script.get_current_head() == EXPECTED_ALEMBIC_HEAD"`.

**88 revision files, 86 numbers, one merge.** The chain is linear 0001..0076,
then forks:

```
0076_typed_memory_ledger
  |-- 0077_trajectory -> 0078_scoped_integration_connections ----.
  '-- 0077_audit_outbox -> 0078_capability_presentation_fields   |
                        -> 0079_capability_routing_shard         |
                        -> 0080_probe_tool_count_bound ----------'
                                                                 v
                        0081_merge_capability_and_integration_scope
                        -> 0082 -> 0083 -> 0084 -> 0085 -> 0086 (head)
```

0081 is a MERGE revision with a two-element `down_revision` tuple and empty
upgrade/downgrade bodies:
[`migrations/versions/0081_merge_capability_and_integration_scope.py:36`](../../../migrations/versions/0081_merge_capability_and_integration_scope.py) `"down_revision = ("`.
Its docstring states why a merge and not a re-parent: both chains were already
published, and renumbering would strand any database stamped with an old id:
[`migrations/versions/0081_merge_capability_and_integration_scope.py:14`](../../../migrations/versions/0081_merge_capability_and_integration_scope.py) `"THIS IS A MERGE REVISION, NOT A RE-PARENT, and that is the whole point."`.

**The baseline is frozen by hash.** `0001_baseline` executes
`migrations/baseline.sql`, a file the revision points at by relative path and
which must never be re-pointed at the mutable bootstrap:
[`migrations/versions/0001_baseline.py:25`](../../../migrations/versions/0001_baseline.py) `"_SCHEMA = Path(__file__).resolve().parents[1] / \"baseline.sql\""`.
A test asserts its sha256 is
`eef6f12d1c1a6b754f3aab5aa70ed73e7c168d98322f6b94be51c3e2565b0eef` AND that the
revision text does not mention `store/schema.sql`:
[`tests/integration/test_migration_parity.py:24`](../../../tests/integration/test_migration_parity.py) `"BASELINE_SHA256 = \"eef6f12d1c1a6b754f3aab5aa70ed73e7c168d98322f6b94be51c3e2565b0eef\""`.
`0001_baseline.downgrade()` raises: the baseline is the floor.

**Three revisions are irreversible** (bounded: scan of every `downgrade()` body in
`migrations/versions/`, 2026-08-24): `0001_baseline`, `0022_schema_parity`
("reconciles objects that may predate Alembic; destructive downgrade is unsafe"),
and `0024_bound_idempotency` ("invalidates unsafe replay rows"):
[`migrations/versions/0022_schema_parity.py:225`](../../../migrations/versions/0022_schema_parity.py) `"raise NotImplementedError("`.

**Data-destroying upgrade steps.** Only two revisions destroy data outright:
0022 drops `users.updated_at` and converts `users.groups` JSONB to TEXT[]; 0024
TRUNCATEs `idempotency_keys` because old rows are not safely attributable:
[`migrations/versions/0024_bound_idempotency.py:26`](../../../migrations/versions/0024_bound_idempotency.py) `"TRUNCATE TABLE idempotency_keys;"`.
0040 drops the `workflow_promotions` table. 0063 rewrites `mcp_servers.status`
values. 0061 zeroes `budgets.spent_*` after migrating them into `budget_usage`.

**Parity is measured, not asserted.** `test_alembic_head_matches_bootstrap_schema`
applies the offline `alembic upgrade head --sql` output into one throwaway schema
and `schema.sql` into another, then compares five catalogue projections: tables,
columns (with type, notnull, default), constraints (with `pg_get_constraintdef`),
indexes (with `indexdef`) and sequences:
[`tests/integration/test_migration_parity.py:87`](../../../tests/integration/test_migration_parity.py) `"_CATALOGUE_QUERIES = {"`.
It does NOT compare `pg_policy` or `relrowsecurity` (see RISKS).

**Upgrade from a data-bearing RLS database is exercised.**
`test_data_bearing_rls_database_upgrades_from_previous_head` creates a real
database, migrates to `0021`, seeds three users across two tenants, applies
`rls.sql`, then migrates to head and asserts the rows survived, the `groups`
conversion is correct, `users.updated_at` is gone, twenty named tables are
FORCE-RLS'd with a `tenant_isolation` policy, and `alembic_version` equals the
packaged head:
[`tests/integration/test_migration_parity.py:189`](../../../tests/integration/test_migration_parity.py) `"async def test_data_bearing_rls_database_upgrades_from_previous_head() -> None:"`.

## 7. Configuration surface

| variable | default | read at | what breaks if wrong |
| --- | --- | --- | --- |
| `DATABASE_URL` | unset | [`boltrig/config/settings.py:106`](../../../boltrig/config/settings.py) `"database_url=e.get(\"DATABASE_URL\") or None,"`, [`migrations/env.py:25`](../../../migrations/env.py) `"os.environ.get(\"DATABASE_URL\")"` | unset means the process silently runs on `InMemoryStore` and every migration targets `postgresql://localhost/boltrig` |
| `BOLTRIG_DATABASE_URL` | unset | [`migrations/env.py:26`](../../../migrations/env.py) `"or os.environ.get(\"BOLTRIG_DATABASE_URL\")"`, [`boltrig/api/audit_verify.py:33`](../../../boltrig/api/audit_verify.py) `"dsn = os.environ.get(\"DATABASE_URL\") or os.environ.get(\"BOLTRIG_DATABASE_URL\")"` | second fallback for the Alembic URL, and the fallback DSN for the `audit-verify` CLI subcommand, which returns exit code 2 rather than 0 when neither variable is set ([`boltrig/api/audit_verify.py:35`](../../../boltrig/api/audit_verify.py) `"no DATABASE_URL: cannot verify, and cannot call that success"`). It is NOT Alembic-only (bounded: `grep -rn "BOLTRIG_DATABASE_URL" boltrig/ migrations/ tests/ scripts/ apps/ services/`, 2026-08-24, pinned tree, three hits: `boltrig/api/audit_verify.py`, `migrations/env.py`, `tests/unit/test_audit_verify_cli.py`) |
| `BOLTRIG_TEST_DATABASE_URL` | unset | [`migrations/env.py:27`](../../../migrations/env.py) `"or os.environ.get(\"BOLTRIG_TEST_DATABASE_URL\")"`, [`tests/conftest.py:44`](../../../tests/conftest.py) `"\"BOLTRIG_TEST_DATABASE_URL\","` | absent, every Postgres leg skips (bounded: `grep -rl "BOLTRIG_TEST_DATABASE_URL" tests/`, 2026-08-24, pinned tree, 42 files) and `tests/conftest.py` ends the run NON-ZERO unless `BOLTRIG_ALLOW_UNVERIFIED_POSTGRES` is set |
| `BOLTRIG_RLS` | unset (off) | [`boltrig/api/bootstrap.py:98`](../../../boltrig/api/bootstrap.py) `"rls = is_truthy(os.environ.get(\"BOLTRIG_RLS\"))"` | on without `rls.sql` applied: the GUC is set and no policy exists, so nothing changes. `rls.sql` applied without the flag: FORCE RLS with a null GUC yields ZERO rows, which is an outage. The order is not reorderable and `.env.example` says so |
| `BOLTRIG_SEAL_KEY` | in-source `dev-insecure-seal-key` | [`boltrig/store/sealing.py:171`](../../../boltrig/store/sealing.py) `"key = e.get(\"BOLTRIG_SEAL_KEY\")"` | unset or default under a production signal is FATAL at the first seal/unseal; wrong value makes every sealed row unreadable and `get_credential_ref` raise `CredentialResolution` |
| `BOLTRIG_SEAL_KEY_PREVIOUS` | unset | [`boltrig/store/sealing.py:180`](../../../boltrig/store/sealing.py) `"e.get(\"BOLTRIG_SEAL_KEY_PREVIOUS\") or None"` | decrypt-only during rotation; dropping it before every row is rewritten strands v1/previous-key rows |
| `BOLTRIG_PRODUCTION`, `ENV`, `BOLTRIG_ENV`, `APP_ENV` | unset | [`boltrig/store/sealing.py:89`](../../../boltrig/store/sealing.py) `"if (env.get(\"BOLTRIG_PRODUCTION\") or \"\").strip().lower() in _TRUE_VALUES:"`, [`boltrig/store/sealing.py:91`](../../../boltrig/store/sealing.py) `"for name in (\"ENV\", \"BOLTRIG_ENV\", \"APP_ENV\"):"` | these are what arm the seal-key fatality; a production deployment that sets none of them seals with the public dev key |
| `BOLTRIG_RETENTION_INTERVAL` | 3600.0 seconds | [`boltrig/fleet/retention.py:62`](../../../boltrig/fleet/retention.py) `"INTERVAL_ENV = \"BOLTRIG_RETENTION_INTERVAL\""` | `<= 0` disables the janitor and the worker logs which it did; malformed falls back to the default ([`boltrig/fleet/retention.py:76`](../../../boltrig/fleet/retention.py) `"is not a number; using the default"`) |
| `privacy.retention_days` (manifest) | 30 | [`boltrig/fleet/retention.py:161`](../../../boltrig/fleet/retention.py) `"def retention_days_from_manifest(manifest: Any) -> int:"` | sets the conversation purge cutoff; a manifest with no privacy section keeps 30 ([`boltrig/fleet/retention.py:169`](../../../boltrig/fleet/retention.py) `"return int(days) if days else DEFAULT_RETENTION_DAYS"`) |
| `BOLTRIG_TRAJECTORY` | unset (off) | [`boltrig/kernel/trajectory.py:103`](../../../boltrig/kernel/trajectory.py) `"_is_truthy(os.environ.get(\"BOLTRIG_TRAJECTORY\")) if enabled is None else enabled"` | on, verbatim prompts and tool payloads land in `trajectory_events` with a 14-day `expires_at` that nothing ever sweeps |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `boltrig` / required / `boltrig` | [`docker-compose.yml:47`](../../../docker-compose.yml) `"POSTGRES_USER: ${POSTGRES_USER:-boltrig}"`, [`docker-compose.yml:51`](../../../docker-compose.yml) `"POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD (see .env.example)}"`, [`docker-compose.yml:52`](../../../docker-compose.yml) `"POSTGRES_DB: ${POSTGRES_DB:-boltrig}"` | the stack refuses to start with no `POSTGRES_PASSWORD`; the created role is the initdb SUPERUSER, which is what makes the non-RLS default path work at all |
| `BACKUP_*` (`BACKUP_DIR`, `BACKUP_KEEP`, `BACKUP_DATABASES`, `BACKUP_REMOTE`, `BACKUP_PASSPHRASE`, `BACKUP_STATE_DIR`, `BACKUP_HEALTH_FILE`) | `/backups`, 7, `$PGDATABASE`, unset, unset, unset, `$BACKUP_DIR/.last-success` | [`scripts/backup.sh:29`](../../../scripts/backup.sh) `"BACKUP_DIR=\"${BACKUP_DIR:-/backups}\""` | `BACKUP_REMOTE` set with a broken rclone exits non-zero, never silent ([`scripts/backup.sh:125`](../../../scripts/backup.sh) `"set but rclone not found (install rclone or bake it into the sidecar image)"`); `BACKUP_STATE_DIR` without `BACKUP_PASSPHRASE` is a hard error ([`scripts/backup.sh:60`](../../../scripts/backup.sh) `"BACKUP_STATE_DIR contains sensitive state and requires BACKUP_PASSPHRASE"`) |

Manifest key that changes the catalogue's shape: none. The schema is not
manifest-driven.

## 8. PROCESS

### 8.1 Fresh box, first boot

The compose stack mounts `schema.sql` as an initdb hook, so a brand-new volume
gets all 138 tables at first Postgres start:
[`docker-compose.yml:61`](../../../docker-compose.yml) `"- ./boltrig/store/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro"`.
`genesis.sh` relies on exactly that and skips migration on a clean box:
[`genesis.sh:137`](../../../genesis.sh) `"A fresh volume loads boltrig/store/schema.sql on first boot (all tables), so no"`.
The consequence, which the file does not state, is that a clean box has NO
`alembic_version` row at all until someone runs the chain.

### 8.2 Upgrading a provisioned box

`make migrate` runs `alembic upgrade head` from the checkout:
[`Makefile:481`](../../../Makefile) `"$(PY) -m alembic upgrade head"`.
The release path does not use that target; `scripts/roll-release.sh` stages the
chain and calls `roll-migrate-stack.sh` per stack, which migrates to the target
IMAGE's head (5.5). The documented pre-flight, in order:

1. Stop writers or enter a maintenance window.
2. `pg_dump -Fc` off-box and verify with `pg_restore --list`.
3. Rehearse `alembic upgrade head` plus smoke tests against a restored copy.
4. Record `alembic current` and confirm it advances to the expected head.
5. Retain the prior images until the smoke is complete.

[`docs/DEPLOYMENT.md:716`](../../../docs/DEPLOYMENT.md) `"Before every production migration:"`.

**Never migrate under a running kernel.** Doing so on the CV stack killed it,
the kernel rebooted, re-registered adapters from the old image's manifest,
rewrote every verb row, and then crash-looped because the database was newer than
the code:
[`docs/findings/2026-07-25-prod-roll-0.3.1.md:37`](../../../docs/findings/2026-07-25-prod-roll-0.3.1.md) `"**1. NEVER migrate under a running kernel.**"`.
The order is: stop `kernel` and `fleet-worker`, leave `postgres` up, migrate,
then start on the matching image.

**Migrating a never-tracked database.** Both production stacks were once
bootstrapped from an initdb `schema.sql` and had no `alembic_version` at all; the
recorded procedure is to run the chain from base against a RESTORED COPY first,
assert table count, `alembic_version` and row survival, then boot the new image
against the scratch DB and hit `/readyz`, and only then repeat live:
[`docs/findings/2026-07-25-prod-roll-0.3.1.md:22`](../../../docs/findings/2026-07-25-prod-roll-0.3.1.md) `"So `alembic upgrade head` from base is the RIGHT path for"`.

**Validate the manifest with the candidate image too.** A thorough schema
pre-flight still let a deploy crash-loop on a manifest field; the answer is
`docker run --rm -v manifest:/m.yaml:ro <image> boltrig config-validate /m.yaml`:
[`boltrig/api/config_validate.py:17`](../../../boltrig/api/config_validate.py) `"boltrig config-validate /m.yaml"`.

### 8.3 Turning RLS on

Three steps, in this order and no other:

1. `BOLTRIG_RLS=1` and restart, so the app binds the GUC on every call.
2. Then apply the overlay as the table owner: `store.apply_rls()`
   ([`boltrig/store/postgres.py:207`](../../../boltrig/store/postgres.py) `"async def apply_rls(self) -> None:"`).
3. Then connect the app as `boltrig_app` (which needs
   `ALTER ROLE boltrig_app LOGIN PASSWORD ...`, since the role is created NOLOGIN).

Doing 2 before 1 takes the stack DOWN:
[`.env.example:393`](../../../.env.example) `"Doing 2 before 1 takes the stack DOWN rather than making it safe"`.
Rollback is to drop the policies, not to unset the flag.

### 8.4 Backup and restore

`make backup` runs `pg_dump -Fc` through the compose exec; `make restore` runs
`pg_restore --clean --if-exists`:
[`Makefile:485`](../../../Makefile) `"$(COMPOSE) exec -T postgres pg_dump -U $(PG_USER) -d $(PG_DB) -Fc > $(BACKUP)"`.
`make backup-schedule` starts the profile-gated sidecar looping
`scripts/backup.sh`, which dumps every configured database, VERIFIES each archive
parses with `pg_restore`, optionally encrypts with openssl AES-256, writes a
sha256 sidecar per artifact, and uploads the recovery-set manifest LAST so a
partial upload cannot look complete:
[`scripts/backup.sh:8`](../../../scripts/backup.sh) `"gets a SHA-256 sidecar and a recovery-set manifest is uploaded LAST"`.
`make recovery-verify` verifies one encrypted recovery set without decrypting or
restoring it; `make recovery-rehearsal` exercises dump/restore inside a
disposable Postgres container:
[`Makefile:353`](../../../Makefile) `"recovery-rehearsal: ## Exercise pg_dump/restore only inside a disposable PostgreSQL container"`.

### 8.5 Diagnosing

- Applied head, from the database rather than from a tool's exit code:
  `select version_num from alembic_version`. That framing is the runbook's:
  [`docs/ACTIVATE-SENSING-RUNBOOK.md:129`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md) `"the database's own report, not alembic's exit code"`.
- `PostgresStore.readiness_snapshot()` returns `(alive, tuple_of_heads)` and
  deliberately reads OUTSIDE the tenant fence, because `SELECT 1` and
  `alembic_version` are global catalogue facts:
  [`boltrig/store/postgres.py:196`](../../../boltrig/store/postgres.py) `"This deployment-level probe intentionally bypasses tenant RLS"`.
  `/readyz` fails closed with `head_mismatch` when it differs from the packaged
  constant.
- `make migration-parity` runs the parity test against a disposable Postgres:
  [`Makefile:344`](../../../Makefile) `"scripts/with_test_postgres.sh $(PY) -m pytest -q tests/integration/test_migration_parity.py"`.

### 8.6 Running the store tests

Both backends run the same contract assertions through one parametrised fixture;
the Postgres leg TRUNCATEs a hand-listed table set and skips without a DSN:
[`tests/store/test_store_parity.py:134`](../../../tests/store/test_store_parity.py) `"await store._pool.execute(f\"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE\")"`.
A missing `BOLTRIG_TEST_DATABASE_URL` is now BLOCKING, not a silent skip, and the
conftest says why: a Postgres-only foreign-key defect lived through green local
suite after green local suite:
[`tests/conftest.py:24`](../../../tests/conftest.py) `"still ended \"N passed\" in green. A Postgres-only foreign-key defect lived"`.

## 9. Failure modes and fail-open / fail-closed posture

**9.1 Null tenant GUC. FAIL-CLOSED.** `current_setting('app.tenant_id', true)`
returns NULL when unset, so `tenant_id = NULL` is never true and the policy
matches zero rows for reads and rejects every insert via `WITH CHECK`:
[`boltrig/store/rls.sql:12`](../../../boltrig/store/rls.sql) `"A null GUC makes the policy predicate NULL -> never true -> zero rows"`.
`_apply_guc` coerces an unbound contextvar to `''` rather than leaving the GUC
unset, which lands in the same place.

**9.2 Missing role switch. FAIL-OPEN, and this actually happened.** The GUC alone
does nothing when the connecting role is a superuser, because a superuser bypasses
RLS even under FORCE. Twenty-two explicit-transaction call sites omitted
`SET LOCAL ROLE boltrig_app`, five of them carrying a comment claiming they were
scoped:
[`boltrig/store/tenant_scope.py:99`](../../../boltrig/store/tenant_scope.py) `"THE ROLE SWITCH IS THE WHOLE MECHANISM, AND 22 SITES OMITTED IT."`.
The guard is an AST sweep that keys on the ROLE SWITCH, not on the presence of the
GUC, with a closed eight-entry exemption list:
[`tests/security/test_rls_covers_explicit_transactions.py:62`](../../../tests/security/test_rls_covers_explicit_transactions.py) `"_BINDERS = (\"bind_conn_to_tenant\", \"_bind_tenant\", \"_apply_guc\", \"SET LOCAL ROLE\")"`.

**9.3 A discovery query under the fence. FAIL-CLOSED, and that WAS the outage.**
`list_orgs()` has no tenant to bind. Under RLS it ran unbound, the `organisations`
policy matched nothing, and it returned zero rows, so the anchor and HITL-expiry
janitors iterated an empty list for nine hours, wrote no receipt, logged nothing
and returned 0:
[`boltrig/store/control_plane_reads.py:17`](../../../boltrig/store/control_plane_reads.py) `"So each sweep iterated an empty list, did nothing, wrote no receipt"`.
The resolution is a deliberate exemption on an unfenced `acquire()` connection,
with the caller set PINNED to three modules by a test:
[`tests/security/test_rls_exemptions.py:35`](../../../tests/security/test_rls_exemptions.py) `"EXEMPT_READ_CALLERS = {"`.
That test also fails on a STALE entry (a permitted caller that no longer calls),
which is the rarer half of the guard.

**9.4 Contextvar / argument disagreement. FAIL-CLOSED on read, LOUD on write.**
The fence used to read a contextvar while every method took the tenant as an
argument: 318 tenant-carrying coroutines against 51 `set_current_tenant` sites.
Enabling RLS killed the kernel at boot on `model_endpoints`, and the source is
explicit that the write is the LUCKY case because "an unbound READ returns ZERO
ROWS silently":
[`boltrig/store/tenant_scope.py:47`](../../../boltrig/store/tenant_scope.py) `"That WRITE is the lucky case - an unbound READ returns ZERO ROWS silently."`.
`bind_tenant_on_store_methods` closes it by construction, and the honest limit is
stated: it cannot catch a caller passing the WRONG tenant, only a missing or wrong
WHERE clause.

**9.5 Audit append failure. FAIL-DEFERRED, then fail-loud.** A faulted append does
not drop the event; the scrubbed, chain-field-free payload goes to `audit_outbox`
and the janitor re-chains it. Only a failure of the OUTBOX write raises:
[`boltrig/kernel/audit.py:337`](../../../boltrig/kernel/audit.py) `"DURABLE DEFERRAL (SEC-16 audit-always, 2026-08-16): an append fault is"`.

**9.6 Seal key missing in production. FAIL-CLOSED, lazily.** The check runs at the
first seal or unseal, not at import, so the store layer stays import-safe; the
failure is a `RuntimeError` naming the SIGNAL, never the key:
[`boltrig/store/sealing.py:51`](../../../boltrig/store/sealing.py) `"The check runs lazily at first seal/unseal so"`.

**9.7 Wrong or rotated seal key on read. FAIL-CLOSED.** `unseal_ref` raises
`CredentialResolution` on `InvalidToken`, `KeyError`, `AttributeError` or
`ValueError`, and on a payload that is not a dict.

**9.8 Legacy unsealed rows. FAIL-OPEN by design.** A row with no `sealed` marker
is returned verbatim, so pre-sealing plaintext keeps working. Re-sealing is lazy,
on write only. The "no plaintext at rest" claim is therefore true of every row
WRITTEN since sealing landed and not necessarily of rows that predate it.

**9.9 Idempotency claim losing the insert/re-read race. FAIL-CLOSED, and LOUD.**
`ON CONFLICT DO NOTHING` takes no lock on the conflicting row, so a concurrent
release can delete it between the INSERT and the `FOR UPDATE` re-read. The PG
implementation retries three times, and on exhausting them answers IN_PROGRESS
while logging a warning that names the exact consequence: a workflow interpreter
catching the resulting conflict re-invokes with NO key, silently dropping the
guarantee:
[`boltrig/store/idempotency.py:198`](../../../boltrig/store/idempotency.py) `"idempotency claim for key %r lost the insert/re-read race"`.
The memory twin has no such window because its claim never awaits between read
and write.

**9.10 Work-item lease loss. SINGLE-WRITER, NOT EXACTLY-ONCE.** The store makes
the RECORD single-writer via `update_work_item_if_leased`, and `base.py` refuses
to let that be upgraded in prose: "a worker that lost its lease is still RUNNING
... Anything relying on a step running once must be idempotent in its own right":
[`boltrig/store/base.py:146`](../../../boltrig/store/base.py) `"D9, the honest limit: this makes the RECORD single-writer."`.

**9.11 Concurrent claims. FAIL-SAFE.** `claim_work_item` and
`claim_channel_outbox` both use `FOR UPDATE SKIP LOCKED` inside a single
statement, so concurrent claimers neither block nor double-claim:
[`boltrig/store/postgres.py:459`](../../../boltrig/store/postgres.py) `"ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"`.
`claim_channel_outbox` additionally re-imposes order in a CTE because Postgres
defines no ordering for `RETURNING`, which had been presenting as a one-in-ten
"flake" and was user-visible message reordering on Slack and Discord:
[`boltrig/store/channel_outbox.py:203`](../../../boltrig/store/channel_outbox.py) `"NOT order the result: Postgres defines no ordering for RETURNING"`.

**9.12 Budget reserve. ALL-OR-NOTHING.** Every scope is locked `FOR UPDATE` in
sorted `scope_id` order so overlapping reserves cannot deadlock, each hard stop is
re-checked under the lock, and the first refusal aborts with nothing debited:
[`boltrig/store/budget_usage.py:295`](../../../boltrig/store/budget_usage.py) `"\"\"\"Lock policies in stable order and debit all metered scopes or none.\"\"\""`.
A scope with no budget row is unmetered and is a no-op, not a refusal.

**9.13 Workflow run records. FAIL-OPEN, deliberately.** Observability-only rows;
a write failure is swallowed by the route so it can never break execution:
[`boltrig/store/schema.sql:2166`](../../../boltrig/store/schema.sql) `"a write failure is swallowed by the route so it can NEVER"`.
`record_workflow_run` is `ON CONFLICT DO NOTHING` so a re-record never bumps
`started_at` forward.

**9.14 Retention sweep failure. FAIL-OPEN, deliberately.** A bad sweep is logged
and the loop continues; cancellation propagates:
[`boltrig/fleet/retention.py:135`](../../../boltrig/fleet/retention.py) `"except Exception:  # a bad sweep never kills the janitor (P9)"`.

**9.15 In-memory store cannot see three classes of Postgres error.** Measured, not
inferred:
(a) foreign keys, because it enforces none, which let a
`channel_deliveries.channel_id REFERENCES channels(id)` violation pass everywhere
except the `[postgres]` leg;
(b) result ORDERING, because a Python list preserves insertion order where
`RETURNING` does not;
(c) CHECK constraints, noted in the background-job test as "The in-memory store
has no constraint, so unit tests passed throughout":
[`docs/GOAL-trustworthy-gate.md:109`](../../../docs/GOAL-trustworthy-gate.md) `"**Defects the dark gate was hiding.** Two, both Postgres-only"`,
[`tests/security/test_background_job_health.py:283`](../../../tests/security/test_background_job_health.py) `"The in-memory store has no constraint, so unit tests passed throughout"`.
To that measured list I add, from reading: RLS itself, unique-index violations,
advisory locks, `FOR UPDATE SKIP LOCKED` semantics, and the sealing round-trip
through JSONB, none of which the dict store can exercise.

## 10. What is proven

| invariant | what it binds here | named tests |
| --- | --- | --- |
| `FR-OPS-01` | Alembic is authoritative; immutable baseline + head produce the same catalogue as `schema.sql` | `tests/integration/test_migration_parity.py::test_alembic_baseline_is_immutable`, `::test_alembic_head_matches_bootstrap_schema`, `::test_data_bearing_rls_database_upgrades_from_previous_head`, `tests/unit/test_bootstrap_store.py::test_runtime_store_never_replays_mutable_bootstrap` |
| `FR-OPS-03` | `/readyz` requires `alembic_version` exactly equal to the packaged head, and the constant is graph-checked | `tests/integration/test_migration_parity.py::test_packaged_readiness_head_matches_alembic_head`, `tests/unit/test_readiness.py::test_readyz_requires_postgres_redis_and_migration_head_in_production` |
| `SEC-08` | tenant isolation on both stores, fail-closed | `tests/store/test_postgres_store.py::test_cross_tenant_fails_closed`, `tests/security/test_tenant_isolation.py::*` |
| `SEC-65` | DB-enforced isolation: FORCE RLS, non-bypassing role, zero rows on a null GUC, and the live wiring binds per statement | `tests/integration/test_rls.py::test_rls_enforces_tenant_isolation_and_fails_closed`, `::test_rls_binds_the_STORE_not_just_a_hand_rolled_connection`, `::test_the_control_plane_enumeration_still_sees_tenants_UNDER_rls`, `::test_an_explicit_transaction_is_fenced_AND_still_works_under_rls`, `tests/unit/test_rls_pool.py::test_rls_pool_sets_tenant_guc_before_each_statement`, `::test_rls_pool_is_fail_closed_when_no_tenant_bound` |
| `SEC-188` | no tenant table drifts outside the fence, measured against a live catalogue | `tests/security/test_rls_fence_coverage.py::test_every_tenant_table_is_rls_fenced_or_documented_excluded` |
| `SEC-169` | no plaintext credential material rests in the store; wrong key fails closed; production guard is fatal | store-seam sealing, `tests/security/test_ai_keys.py`, `tests/store/test_ai_config.py` |
| `SEC-15` | idempotent replay is tenant/actor/workspace/request bound; one atomic owner; expired claims reclaimable | `tests/kernel/test_idempotency.py::*`, `tests/store/test_postgres_store.py::test_claim_survives_a_release_between_the_insert_and_the_reread` |
| `SEC-16` | every action audited, hash-chained, append-only, contiguous under concurrency | `tests/kernel/test_audit_chain.py::test_concurrent_writes_keep_a_contiguous_verifiable_chain`, `tests/store/test_postgres_store.py::test_pg_audit_chain_verifies` |
| `SEC-74` | closed conversations hard-purged past retention, audit exempt, janitor actually started | `tests/store/test_retention_purge.py::test_closed_conversation_body_is_hard_purged_after_retention`, `::test_retention_purge_is_tenant_scoped`, `::test_restore_racing_retention_never_resurrects_a_purged_row`, `::test_purge_runs_select_and_deletes_in_one_transaction` |
| `SEC-66` | channel intake replay dedup is atomic and TTL-bounded | `tests/store/test_channel_durability.py` |
| store parity (unbound to a K-id) | one contract, two backends | `tests/store/test_store_parity.py` (2,636 lines), plus nine dedicated `*_store_parity.py` modules for artifacts, devices, invitations, password reset, provenance, run effects, workflow triggers, workflow schedules and birth profiles |

Also proven, and worth naming because they are guards on the guards:
`tests/security/test_rls_exemptions.py` pins BOTH that no unlisted module calls
an exempt read AND that every listed caller still calls it;
`tests/unit/test_rls_pool.py` scans module SOURCE for pool statements and requires
every class in that file to bind the GUC, which is why `trajectory.py` splits the
in-memory store out of the Postgres one:
[`boltrig/store/trajectory.py:4`](../../../boltrig/store/trajectory.py) `"the RLS invariant in"`.

## 11. RISKS

RISK: Fourteen migrations turn on FORCE ROW LEVEL SECURITY unconditionally, so
every Alembic-migrated database has ~19 tables fenced whether or not the operator
opted into RLS, while the default posture documented in `rls.sql` is "connects as
the table owner and relies on the SQL-level WHERE tenant_id filter". It works only
because the compose `POSTGRES_USER` is the initdb superuser and a superuser
bypasses RLS; a deployment that hardens by connecting as a non-superuser owner
without running `rls.sql` and without `BOLTRIG_RLS=1` gets zero rows from
`artifacts`, `devices`, `integration_connections`, `budget_usage`,
`password_reset_tokens` and thirteen others.
[`migrations/versions/0044_artifacts.py:63`](../../../migrations/versions/0044_artifacts.py) `"ALTER TABLE artifacts FORCE ROW LEVEL SECURITY;"`
versus
[`boltrig/store/rls.sql:5`](../../../boltrig/store/rls.sql) `"connects as the table owner and relies on the SQL-level"`.

RISK: The migration-parity test compares tables, columns, constraints, indexes and
sequences, but never `pg_policy` or `relrowsecurity`, so the divergence above is
invisible to the gate that exists to catch bootstrap-versus-Alembic drift. The
Alembic path ends with policies on 19 tables; the `schema.sql` path ends with
none; the test calls them identical.
[`tests/integration/test_migration_parity.py:87`](../../../tests/integration/test_migration_parity.py) `"_CATALOGUE_QUERIES = {"`.

RISK: Five revisions are not idempotent, so `alembic upgrade head` from base
against a `schema.sql`-bootstrapped database (the shape both production stacks
were in on 2026-07-25) fails at the first of them. 0044 uses bare
`CREATE TABLE artifacts` and three bare `CREATE INDEX`; 0045 bare
`CREATE TABLE password_reset_tokens` and a bare unique index; 0057 seven bare
`ADD COLUMN`; 0074 bare `CREATE TABLE conversation_steer_queue`; 0075 four bare
`ADD COLUMN` and a bare unique index. The recorded doctrine says the opposite:
"Every migration is written `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT
EXISTS` precisely so it can run against a schema.sql-bootstrapped database".
[`migrations/versions/0044_artifacts.py:17`](../../../migrations/versions/0044_artifacts.py) `"CREATE TABLE artifacts ("`
versus
[`docs/findings/2026-07-25-prod-roll-0.3.1.md:20`](../../../docs/findings/2026-07-25-prod-roll-0.3.1.md) `"Every migration is written `CREATE TABLE IF NOT"`.

RISK: `trajectory_events` rows are written with `expires_at = now + ttl_days` and
NOTHING ever deletes them. `expire_trajectories` has no caller outside its own two
implementations and `tests/test_trajectory.py` (bounded:
`rg -n "expire_trajectories" .`, 2026-08-24, pinned tree, three files). There is no
trajectory entry in the fleet worker's janitor set and no `trajectory` value in the
`background_job_receipts.job_name` CHECK. Turning `BOLTRIG_TRAJECTORY=1` on
therefore accumulates verbatim prompts and tool payloads forever behind an expiry
that is decorative.
[`boltrig/store/trajectory_postgres.py:121`](../../../boltrig/store/trajectory_postgres.py) `"async def expire_trajectories(self, *, now: datetime | None = None) -> int:"`.

RISK: `expire_trajectories` takes no tenant, so under RLS the class decorator binds
nothing and `_apply_guc` sets `app.tenant_id` to the empty string, meaning the
DELETE would match zero rows and report success. If the sweep is ever wired, it
will present as working and delete nothing, which is the exact shape of the 2026-07-31
janitor outage.
[`boltrig/store/tenant_scope.py:70`](../../../boltrig/store/tenant_scope.py) `"tenant_id = _tenant_of(candidate)"`.

RISK: `idempotency_keys` has no retention. Completed rows persist with their
cached `result` JSONB forever; the table's only purge in the whole tree is the
one-off TRUNCATE inside migration 0024. On a busy tenant this is unbounded growth
holding cached verb outputs (bounded: `rg -n "idempotency_keys" boltrig/ scripts/ deploy/ tests/`,
2026-08-24, five hits, none a sweeper).
[`boltrig/store/schema.sql:653`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS idempotency_keys ("`.

RISK: Four tables the schema describes as immutable or append-only keep full
UPDATE and DELETE grants for `boltrig_app`, because the REVOKE list names only
four different tables. `conversation_summaries` ("no row is ever updated"),
`memory_events` ("append-only"), `agent_messages` ("Message envelopes are
immutable") and `workflow_trigger_deliveries` ("One immutable receipt") are all
rewritable by a compromised app role.
[`boltrig/store/rls.sql:41`](../../../boltrig/store/rls.sql) `"append_only text[] := ARRAY["`.

RISK: `mcp_servers.credential` is a nullable TEXT column named for credential
material with no writer and no reader anywhere in the tree. The current INSERT
names its columns explicitly and omits it; no UPDATE sets it (bounded:
`rg -n "mcp_servers" boltrig/ --glob '!*.sql'` plus a targeted scan of
`boltrig/store/mcp_*.py` for the column name, 2026-08-24). A column shaped like a
secret that nothing owns is a place a secret gets put later.
[`boltrig/store/schema.sql:1372`](../../../boltrig/store/schema.sql) `"credential  TEXT,"`.

RISK: `user_sessions.csrf_token` is stored in plaintext while every other bearer in
the identity group is a sha256. A read of the sessions table yields working CSRF
tokens for every live session. The column's own comment calls it a
"session-bound double-submit CSRF token", which is a lower-value secret than a
session cookie, but it is still the only unhashed bearer in the group.
[`boltrig/store/schema.sql:1761`](../../../boltrig/store/schema.sql) `"csrf_token    TEXT,                             -- session-bound double-submit CSRF token"`.

RISK: The `Store` Protocol in `base.py` does not declare the camera-binding and
camera-lease methods, yet `boltrig/kernel/camera_agent_routes.py` calls six of them
off `kernel.store`. A second backend written against the declared Protocol would
typecheck and then fail at runtime on the camera routes.
[`boltrig/kernel/camera_agent_routes.py:194`](../../../boltrig/kernel/camera_agent_routes.py) `"if not await kernel.store.upsert_camera_binding(binding):"`.

RISK: The knowledge repository claims the set of `_RlsPool` holders outside the
`PostgresStore` MRO is complete at two, but `PostgresTrajectoryStore` is a third
and was added later. The claim is stale rather than wrong in effect (the third
class IS decorated), but a reader trusting it would stop looking.
[`boltrig/knowledge/postgres_repository.py:36`](../../../boltrig/knowledge/postgres_repository.py) `"Checked the whole tree for others - every other _RlsPool user IS a PostgresStore"`.

RISK: `schema.sql`'s trajectory comment says the table has no `tenant_isolation`
policy "below" because the migration does not create one, but `rls.sql` DOES fence
`trajectory_events` and says it is correcting exactly that. The two comments
disagree about the live state of the fence on a table holding verbatim prompts.
[`boltrig/store/schema.sql:2841`](../../../boltrig/store/schema.sql) `"no tenant_isolation policy below -- the migration does not create one."`
versus
[`boltrig/store/rls.sql:129`](../../../boltrig/store/rls.sql) `"policy and this is where that is corrected."`.

RISK: The store layer cites `K-22` as the kernel invariant for tenant isolation in
both `schema.sql` and `rls.sql`, but `K-22` is not a declared id in
`tests/invariants.yaml`; only `K-2`, `K-5`, `K-9`, `K-13`, `K-19` and `K-20`
exist there (bounded: `grep -n "^  K-" tests/invariants.yaml`, 2026-08-24, six
matches). The isolation property is in fact bound, by `SEC-08`, `SEC-65` and
`SEC-188`, so nothing is unproven; the citation simply names an id no gate can
resolve, which is how a reader concludes a control is bound when it is bound
under a different name.
[`boltrig/store/rls.sql:1`](../../../boltrig/store/rls.sql) `"Boltrig RLS overlay (SEC-08 / K-22 / SEC-65)"`.

RISK: `migrations/env.py` falls back to `postgresql://localhost/boltrig` when no
URL variable is set, so a migration run with a typo'd or unexported variable
targets a local database silently instead of refusing.
[`migrations/env.py:28`](../../../migrations/env.py) `"or \"postgresql://localhost/boltrig\""`.

RISK: `audit_append` has no ON CONFLICT and no in-store retry, and the writer's
serialiser is a per-process asyncio lock. Across replicas the only guard is
`UNIQUE (tenant_id, seq)`, and a lost race is not retried inline; it is deferred to
the outbox. Under sustained multi-replica write pressure the chain advances
through the janitor rather than the hot path, which is correct but is a throughput
cliff nothing measures.
[`boltrig/kernel/audit.py:321`](../../../boltrig/kernel/audit.py) `"One lock per tenant; for a multi-process deployment the Postgres"`.

RISK: `artifacts.content` is a `BYTEA` column capped at 100 MB per row with no
retention and no external storage, in the same database as the audit chain. A
tenant generating artifacts grows the primary database and every `pg_dump` with it.
[`boltrig/store/schema.sql:2765`](../../../boltrig/store/schema.sql) `"CONSTRAINT artifact_size_bounded CHECK ("`.

RISK: `credential_refs.expires_at` exists "for rotation alerts" and nothing in the
store reads it. An expired credential reference is never surfaced by the store
layer (bounded: `rg -n "expires_at" boltrig/store/credential_references.py boltrig/store/postgres.py`
around the credential methods, 2026-08-24; it is written on upsert and read by no
query).
[`boltrig/store/schema.sql:719`](../../../boltrig/store/schema.sql) `"expires_at  TIMESTAMPTZ,                            -- for rotation alerts (US-COST-04)"`.

## 12. OPEN QUESTIONS

1. **Does any deployed database actually carry policies from the migrations
   without having run `rls.sql`?** Settled by running, on each stack,
   `SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN ('artifacts','devices','budget_usage')`
   and comparing with `SELECT 1 FROM pg_roles WHERE rolname='boltrig_app'`. I could
   not settle it from the tree because it is a runtime fact.
2. **Is the app role a superuser on every live stack?** The tree asserts it for the
   beelink only
   ([`tests/security/test_rls_covers_explicit_transactions.py:9`](../../../tests/security/test_rls_covers_explicit_transactions.py) `"Confirmed on the beelink: ``boltrig`` is ``rolsuper=t rolbypassrls=t``"`).
   Settled by `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles` per stack.
3. **Has `alembic upgrade head` from base ever been run against a
   `schema.sql`-bootstrapped database at a revision past 0043?** The 2026-07-25
   rehearsal ended at `0037_secure_input`, before 0044 introduced the first
   non-idempotent CREATE. Settled by restoring a schema.sql-only dump and running
   the chain in a scratch database.
4. **How many `credential_refs` rows are still sealed under the v1 (unsalted
   SHA-256) derivation, or still plaintext?** Not answerable statically; the
   envelope carries no key id by design. Settled by counting rows whose `data`
   lacks the `sealed` marker, plus an instrumented decrypt that records which
   `MultiFernet` member succeeded.
5. **Is `mcp_servers.credential` populated on any live stack?** Settled by
   `SELECT count(*) FROM mcp_servers WHERE credential IS NOT NULL` per tenant. If
   it is, the column is holding material nothing seals.
6. **What is the intended sweeper for `idempotency_keys` and
   `trajectory_events`?** Nothing in the tree names one, and neither appears in
   the `background_job_receipts.job_name` CHECK set. Settled by a decision record
   or a new job name in that CHECK.
7. **Does `InMemoryStore` satisfy `isinstance(store, Store)` at runtime?** `Store`
   is `@runtime_checkable`, and I did not execute the check. Settled by importing
   both and asserting; a missing method would be a real parity hole the AST diff
   would not catch if it lives on a contract fragment neither backend implements.
8. **My task brief named an "in-memory / sqlite / Postgres backend split", but no
   SQLite store exists.** `aiosqlite` is a dev-only dependency with no importer
   anywhere (bounded: `rg -n "aiosqlite|import sqlite3" boltrig/ tests/ apps/ services/ libraries/`,
   2026-08-24, zero matches); every SQLite mention in the tree is the Codex CLI's
   own state file. Settled by removing the dependency or by naming the store that
   was meant to use it.

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0500 | The kernel reaches durable state only through the `Store` Protocol, never a concrete database. | IMPLEMENTED | `boltrig/store/base.py:3` "kernel depends on this Protocol, never on a concrete DB" | - |
| BT-REQ-0501 | Two backends satisfy `Store`: `InMemoryStore` and `PostgresStore`, differing only in the five connection-lifecycle methods. | IMPLEMENTED | `boltrig/store/postgres.py:134` `"class PostgresStore("`; the AST diff of section 4.2; test `tests/store/test_store_parity.py` | - |
| BT-REQ-0502 | Every store method is tenant-scoped: an id lookup is always qualified by `tenant_id`. | IMPLEMENTED | `boltrig/store/base.py:5` `"Tenant isolation (SEC-08) is a"` | SEC-08 |
| BT-REQ-0503 | Runtime store construction never applies `schema.sql`; `apply_schema` is False from every production path. | IMPLEMENTED | `boltrig/api/bootstrap.py:100` "apply_schema=False, rls=rls" | FR-OPS-01 |
| BT-REQ-0504 | `PostgresStore` is composed from per-domain mixins so no single module holds the whole method surface. | IMPLEMENTED | `boltrig/store/postgres.py:153` "Domain methods live in partial mixins" | - |
| BT-REQ-0505 | The `Store` Protocol does not declare the camera-binding or camera-lease methods that routes call off `kernel.store`. | IMPLEMENTED-UNTESTED | `boltrig/kernel/camera_agent_routes.py:194` "kernel.store.upsert_camera_binding(binding)"; no camera name in `boltrig/store/base.py` | - |
| BT-REQ-0506 | `schema.sql` declares 138 tables and requires the pgvector extension before any `vector` column. | IMPLEMENTED | `boltrig/store/schema.sql:12` "CREATE EXTENSION IF NOT EXISTS vector;" | - |
| BT-REQ-0507 | `schema.sql` is the fresh-database bootstrap only and is mounted as a Postgres initdb hook. | IMPLEMENTED | `docker-compose.yml:61` "docker-entrypoint-initdb.d/01-schema.sql:ro" | FR-OPS-01 |
| BT-REQ-0508 | Alembic is the authoritative upgrade path and its head is `0086_conversation_addressing`. | IMPLEMENTED | `boltrig/api/readiness.py:27` `"EXPECTED_ALEMBIC_HEAD = \"0086_conversation_addressing\""` | FR-OPS-03 |
| BT-REQ-0509 | The packaged readiness head is graph-checked against the Alembic revision tree. | IMPLEMENTED | `tests/integration/test_migration_parity.py:43` "script.get_current_head() == EXPECTED_ALEMBIC_HEAD" | FR-OPS-03 |
| BT-REQ-0510 | The Alembic baseline is immutable, pinned by sha256, and never reads the mutable bootstrap. | IMPLEMENTED | `tests/integration/test_migration_parity.py:24` `"BASELINE_SHA256 = \"eef6f12d1c1a6b754f3aab5aa70ed73e7c168d98322f6b94be51c3e2565b0eef\""` | FR-OPS-01 |
| BT-REQ-0511 | The revision graph forked at 0076 and is rejoined by the schema-free merge revision 0081, leaving exactly one head. | IMPLEMENTED | `migrations/versions/0081_merge_capability_and_integration_scope.py:36` "down_revision = (" | FR-OPS-01 |
| BT-REQ-0512 | Revisions 0001, 0022 and 0024 raise on downgrade; rollback past them is a restore, not a migration. | IMPLEMENTED | `migrations/versions/0022_schema_parity.py:225` "raise NotImplementedError(" | FR-OPS-01 |
| BT-REQ-0513 | The Alembic head and the `schema.sql` bootstrap produce identical table, column, constraint, index and sequence catalogues. | IMPLEMENTED | `tests/integration/test_migration_parity.py:156` "test_alembic_head_matches_bootstrap_schema" | FR-OPS-01 |
| BT-REQ-0514 | The parity check does not compare row-security state or policies, so an RLS divergence between the two paths passes it. | IMPLEMENTED-UNTESTED | `tests/integration/test_migration_parity.py:87` "_CATALOGUE_QUERIES = {" | - |
| BT-REQ-0515 | A data-bearing RLS database upgrades from 0021 to head with rows preserved and the fence extended. | IMPLEMENTED | `tests/integration/test_migration_parity.py:189` "test_data_bearing_rls_database_upgrades_from_previous_head" | FR-OPS-01, SEC-65 |
| BT-REQ-0516 | Alembic resolves its URL from `DATABASE_URL`, then `BOLTRIG_DATABASE_URL`, then `BOLTRIG_TEST_DATABASE_URL`, and otherwise falls back to a localhost DSN. | IMPLEMENTED-UNTESTED | `migrations/env.py:25` `"os.environ.get(\"DATABASE_URL\")"` | - |
| BT-REQ-0517 | Online migrations run on the psycopg driver because the baseline is a multi-statement bootstrap asyncpg cannot execute. | IMPLEMENTED | `migrations/env.py:38` `"return f\"postgresql+psycopg://{rest}\""` | - |
| BT-REQ-0518 | The roll gate migrates each stack to the head its TARGET IMAGE asserts, never to the checkout's head. | IMPLEMENTED-UNTESTED | `scripts/roll-migrate-stack.sh:78` "python -m alembic upgrade '$WANT'" | - |
| BT-REQ-0519 | A database found ahead of its image aborts the roll non-zero and nothing is deployed for that stack. | IMPLEMENTED-UNTESTED | `scripts/roll-release.sh:234` "NOTHING was deployed for this stack" | - |
| BT-REQ-0520 | Five revisions (0044, 0045, 0057, 0074, 0075) use unguarded DDL and cannot run against a schema.sql-bootstrapped database. | IMPLEMENTED-UNTESTED | `migrations/versions/0044_artifacts.py:17` "CREATE TABLE artifacts (" | - |
| BT-REQ-0521 | The RLS overlay is opt-in and is not part of the default `schema.sql` boot. | IMPLEMENTED | `boltrig/store/rls.sql:4` "OPT-IN. This is NOT part of the default schema.sql boot." | SEC-65 |
| BT-REQ-0522 | Under the overlay every tenant table carries a `tenant_isolation` policy with FORCE row security, gating reads by USING and writes by WITH CHECK. | IMPLEMENTED | `boltrig/store/rls.sql:192` "CREATE POLICY tenant_isolation ON %I" | SEC-65 |
| BT-REQ-0523 | An unset `app.tenant_id` yields zero rows and refuses every insert; the fence is fail-closed, never wide open. | IMPLEMENTED | `tests/unit/test_rls_pool.py::test_rls_pool_is_fail_closed_when_no_tenant_bound` | SEC-65 |
| BT-REQ-0524 | Exactly four tables sit outside the fence: `channels`, `identity_orgs`, `personal_access_tokens`, and `organisations` which is fenced on `id` instead. | IMPLEMENTED | `tests/security/test_rls_fence_coverage.py:52` "DOCUMENTED_RLS_EXCLUSIONS = frozenset(" | SEC-188 |
| BT-REQ-0525 | Every table carrying a `tenant_id` column is either fenced or in the documented exclusion set, measured against a live catalogue. | IMPLEMENTED | `tests/security/test_rls_fence_coverage.py::test_every_tenant_table_is_rls_fenced_or_documented_excluded` | SEC-188 |
| BT-REQ-0526 | The policies bind only when the connection drops to the non-bypassing `boltrig_app` role; setting the GUC alone does nothing under a superuser. | IMPLEMENTED | `boltrig/store/rls_pool.py:30` "WITHOUT IT THE POLICIES DO NOTHING" | SEC-65 |
| BT-REQ-0527 | Every public tenant-carrying coroutine binds the GUC from its own first argument, so fence and WHERE clause cannot drift. | IMPLEMENTED | `boltrig/store/tenant_scope.py:120` "def bind_tenant_on_store_methods(cls):" | SEC-65 |
| BT-REQ-0528 | Every method holding its own transaction binds the tenant explicitly or is one of eight declared exemptions. | IMPLEMENTED | `tests/security/test_rls_covers_explicit_transactions.py::test_an_explicit_transaction_binds_the_tenant_or_is_a_declared_exemption` | SEC-65 |
| BT-REQ-0529 | `list_orgs` is the sole RLS-exempt read, reachable only from three named fleet janitors, and the caller set fails the build in both directions. | IMPLEMENTED | `tests/security/test_rls_exemptions.py:35` "EXEMPT_READ_CALLERS = {" | SEC-65 |
| BT-REQ-0530 | `readiness_snapshot` deliberately reads outside the fence because `SELECT 1` and `alembic_version` are global catalogue facts. | IMPLEMENTED | `boltrig/store/postgres.py:196` "intentionally bypasses tenant RLS" | FR-OPS-03 |
| BT-REQ-0531 | The overlay revokes UPDATE and DELETE from `audit_log`, `security_log`, `config_revisions` and `execution_events`. | IMPLEMENTED | `boltrig/store/rls.sql:41` "append_only text[] := ARRAY[" | SEC-16 |
| BT-REQ-0532 | Four tables documented as immutable or append-only (`conversation_summaries`, `memory_events`, `agent_messages`, `workflow_trigger_deliveries`) keep full DML grants. | IMPLEMENTED-UNTESTED | `boltrig/store/rls.sql:41` "append_only text[] := ARRAY[" | - |
| BT-REQ-0533 | Fourteen migrations enable FORCE row security unconditionally, so a migrated database is fenced on ~19 tables whether or not `rls.sql` was ever run. | IMPLEMENTED-UNTESTED | `migrations/versions/0041_realtime_calls.py:65` "ALTER TABLE %I FORCE ROW LEVEL SECURITY" | - |
| BT-REQ-0534 | Every dict written through `set_credential_ref` rests as a versioned Fernet envelope; `credential_refs.data` never holds plaintext written after sealing landed. | IMPLEMENTED | `boltrig/store/postgres.py:809` "seal_ref(ref)" | SEC-169 |
| BT-REQ-0535 | The sealing key is derived with scrypt over a fixed salt; the original unsalted SHA-256 derivation is retained for decrypt only. | IMPLEMENTED | `boltrig/store/sealing.py:161` "fernets = [_passphrase_to_fernet_v2(key), _passphrase_to_fernet_v1(key)]" | SEC-169 |
| BT-REQ-0536 | A missing or default `BOLTRIG_SEAL_KEY` under a production signal is fatal, and the error names the signal, never the key. | IMPLEMENTED | `boltrig/store/sealing.py:174` "raise RuntimeError(" | SEC-169 |
| BT-REQ-0537 | Unsealing a tampered or wrong-key envelope fails closed with `CredentialResolution` and leaks no ciphertext. | IMPLEMENTED | `boltrig/store/sealing.py:216` "sealed credential reference cannot be unsealed" | SEC-169 |
| BT-REQ-0538 | A legacy row without the sealed marker is returned verbatim and is re-sealed only when the row is next written. | IMPLEMENTED | `boltrig/store/sealing.py:209` "if not is_sealed(ref):" | SEC-169 |
| BT-REQ-0539 | `has_credential_ref` answers presence without selecting or unsealing the encrypted column. | IMPLEMENTED | `boltrig/store/credential_references.py:60` "SELECT 1 FROM credential_refs WHERE tenant_id=$1 AND id=$2" | - |
| BT-REQ-0540 | Run-scoped secure-input credential rows are deleted by an exact `run:<run_id>:` prefix match using `strpos`, not LIKE. | IMPLEMENTED | `boltrig/store/postgres.py:822` "strpos(id, $2) = 1" | SEC-181 |
| BT-REQ-0541 | Password credentials live in their own table as an argon2id PHC string, apart from the user identity row. | IMPLEMENTED | `boltrig/store/schema.sql:1714` "password_hash TEXT NOT NULL,          -- argon2id PHC string" | - |
| BT-REQ-0542 | Every other bearer in the identity group rests as a sha256 digest: PAT, session, recovery code, 2FA challenge, password reset, invitation. | IMPLEMENTED | `boltrig/store/schema.sql:1726` "token_hash  TEXT NOT NULL," | - |
| BT-REQ-0543 | `user_sessions.csrf_token` is stored in plaintext, the only unhashed bearer in the identity group. | IMPLEMENTED-UNTESTED | `boltrig/store/schema.sql:1761` "csrf_token    TEXT," | - |
| BT-REQ-0544 | The TOTP shared secret is never stored on the enrolment row; only a `secret_ref` into the sealed store is. | IMPLEMENTED | `boltrig/store/schema.sql:1783` "secret_ref  TEXT NOT NULL,          -- id into credential_refs" | - |
| BT-REQ-0545 | `ai_configs` has no plaintext key column; a row carries only a `credential_ref` into the sealed store. | IMPLEMENTED | `boltrig/store/schema.sql:1934` "credential_ref TEXT NOT NULL,          -- id into credential_refs" | SEC-169 |
| BT-REQ-0546 | An AI-key proposal expires within 15 minutes and a database CHECK ties its status to whether `secret_ref` and `consumed_at` are set. | IMPLEMENTED | `boltrig/store/schema.sql:1978` "CONSTRAINT ai_key_secret_proposal_state_shape CHECK (" | - |
| BT-REQ-0547 | `mcp_servers.credential` is a credential-shaped column with no writer and no reader in the tree. | DEAD | `boltrig/store/schema.sql:1372` "credential  TEXT," | - |
| BT-REQ-0548 | `audit_log` and `security_log` are separate per-tenant hash chains, each unique on `(tenant_id, seq)` with `prev_hash` chaining to `hash`. | IMPLEMENTED | `boltrig/store/schema.sql:574` `"UNIQUE (tenant_id, seq)"` for `audit_log` and `boltrig/store/schema.sql:625` `"UNIQUE (tenant_id, seq)"` for `security_log` | SEC-16 |
| BT-REQ-0549 | `audit_append` is a plain INSERT; cross-process ordering rests on the unique constraint, not on a store-side lock or retry. | IMPLEMENTED | `boltrig/store/postgres.py:639` "async def audit_append(self, e: AuditEvent):" | SEC-16 |
| BT-REQ-0550 | A faulted audit append defers its scrubbed payload to `audit_outbox` with no chain fields, and the janitor re-chains it at drain. | IMPLEMENTED | `boltrig/store/schema.sql:586` "Chain fields (seq/prev_hash/hash) are deliberately NOT" | SEC-16 |
| BT-REQ-0551 | Audit rollup anchors are per tenant and optional workspace, with `workspace_id IS NULL` selecting the org-wide stream rather than any stream. | IMPLEMENTED | `boltrig/store/postgres.py:763` "WHERE tenant_id=$1 AND workspace_id IS NOT DISTINCT FROM $2" | - |
| BT-REQ-0552 | An idempotency claim is bound to actor, delegation, workspace, noun, verb and canonical request hash; any mismatch returns MISMATCH. | IMPLEMENTED | `boltrig/store/idempotency.py:186` "if _pg_bound(row) != bound:" | SEC-15 |
| BT-REQ-0553 | An idempotency claim retries the insert up to three times when the conflicting row is released under it, then answers IN_PROGRESS and logs a warning. | IMPLEMENTED | `boltrig/store/idempotency.py:141` "_CLAIM_ATTEMPTS = 3" | SEC-15 |
| BT-REQ-0554 | An idempotency release deletes a row in either `claimed` or `executing` state so a transient failure does not park the key as a permanent conflict. | IMPLEMENTED | `boltrig/store/idempotency.py:260` "AND status IN ('claimed','executing') AND owner_token=$3" | SEC-15 |
| BT-REQ-0555 | `idempotency_keys` has no retention sweep anywhere in the tree; completed rows and their cached results persist indefinitely. | IMPLEMENTED-UNTESTED | `boltrig/store/schema.sql:653` "CREATE TABLE IF NOT EXISTS idempotency_keys (" | - |
| BT-REQ-0556 | A work-item write on a claimed row succeeds only if the row still carries the lease the caller was given at claim, evaluated in the same statement. | IMPLEMENTED | `boltrig/store/postgres.py:407` "AND lease_owner IS NOT DISTINCT FROM $24" | - |
| BT-REQ-0557 | The lease fence makes the work-item RECORD single-writer and explicitly does not make execution exactly-once. | IMPLEMENTED | `boltrig/store/base.py:146` "this makes the RECORD single-writer" | - |
| BT-REQ-0558 | `claim_work_item` is one statement using `FOR UPDATE SKIP LOCKED`, reclaims expired leases, and increments `attempts` per claim. | IMPLEMENTED | `boltrig/store/postgres.py:459` "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED" | - |
| BT-REQ-0559 | Work-item status transitions are compare-and-set on the expected status, so a losing writer fails rather than overwriting the winner. | IMPLEMENTED | `boltrig/store/postgres.py:425` "WHERE tenant_id=$1 AND id=$2 AND status=$3 RETURNING id" | - |
| BT-REQ-0560 | `try_increment_fanout` applies the whole increment or none, and refuses an over-cap first increment up front. | IMPLEMENTED | `boltrig/store/postgres.py:470` "if n > cap:" | - |
| BT-REQ-0561 | A run-cancel request is an idempotent marker row; a repeat never overwrites the original requester. | IMPLEMENTED | `boltrig/store/postgres.py:514` "ON CONFLICT (tenant_id, run_id) DO NOTHING" | - |
| BT-REQ-0562 | A multi-scope budget reserve locks every scope FOR UPDATE in sorted order and debits all or none. | IMPLEMENTED | `boltrig/store/budget_usage.py:305` "for scope_id in sorted(aggregate):" | FR-COST-05 |
| BT-REQ-0563 | Budget window identity is derived, never stored raw: a run window keys on a sha256 prefix of the run id and calendar windows key on the UTC boundary. | IMPLEMENTED | `boltrig/store/budget_windows.py:38` `"digest = hashlib.sha256(identity.encode(\"utf-8\")).hexdigest()[:32]"` | - |
| BT-REQ-0564 | Closed conversations, their messages and their derived summaries are hard-deleted past the retention cutoff in one transaction. | IMPLEMENTED | `tests/store/test_retention_purge.py::test_purge_runs_select_and_deletes_in_one_transaction` | SEC-74 |
| BT-REQ-0565 | The audit log is exempt from the retention purge and is never touched by it. | IMPLEMENTED | `boltrig/fleet/retention.py:10` "The audit log is EXEMPT and never purged here" | SEC-74 |
| BT-REQ-0566 | The retention janitor is started by the fleet worker on `BOLTRIG_RETENTION_INTERVAL`, and a value of zero or less disables it. | IMPLEMENTED | `boltrig/fleet/retention.py:62` `"INTERVAL_ENV = \"BOLTRIG_RETENTION_INTERVAL\""` | SEC-74 |
| BT-REQ-0567 | Channel delivery dedup is an atomic record-and-check, TTL-bounded, with expired markers evicted opportunistically on write rather than by a janitor. | IMPLEMENTED | `boltrig/store/channel_dedup.py:37` "DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()" | SEC-66 |
| BT-REQ-0568 | The channel outbox claim re-imposes oldest-first order in a CTE because Postgres defines no ordering for RETURNING. | IMPLEMENTED | `boltrig/store/channel_outbox.py:224` "SELECT * FROM claimed ORDER BY created_at, id" | - |
| BT-REQ-0569 | Artifact bytes are content-addressed and validated at write: exact `bytes`, length equal to `size`, and a constant-time digest comparison. | IMPLEMENTED | `boltrig/store/artifacts.py:27` "if not hmac.compare_digest(observed, artifact.digest):" | - |
| BT-REQ-0570 | The artifact row enforces a safe name, a sha256 digest, a 100 MB size ceiling matching the stored bytes, and a revision chain rooted at revision 1. | IMPLEMENTED | `boltrig/store/schema.sql:2766` "size BETWEEN 0 AND 104857600 AND octet_length(content)=size" | - |
| BT-REQ-0571 | A run effect's sequence is assigned inside the INSERT, so two concurrent recorders cannot both claim it. | IMPLEMENTED | `boltrig/store/effect_ledger_postgres.py:43` "COALESCE(MAX(seq),0)+1," | - |
| BT-REQ-0572 | Settling a run effect is a compare-and-set on the expected status, so an inverse can never execute twice. | IMPLEMENTED | `boltrig/store/effect_ledger_postgres.py:85` "WHERE tenant_id=$1 AND run_id=$2 AND seq=$3 AND status=$4" | - |
| BT-REQ-0573 | The trajectory stream is a standalone store, not a mixin on `Store`, so no holder of a `Store` incidentally holds the unscrubbed prompts. | IMPLEMENTED | `boltrig/store/trajectory.py:15` "A STANDALONE STORE, NOT A MIXIN ON ``Store``" | - |
| BT-REQ-0574 | The trajectory sequence is assigned by the database in the same statement as the insert, never read-then-incremented in Python. | IMPLEMENTED | `boltrig/store/trajectory_postgres.py:53` "(SELECT COALESCE(MAX(seq), 0) + 1" | - |
| BT-REQ-0575 | `expire_trajectories` has no production caller, so `trajectory_events.expires_at` is written and never acted on. | DEAD | `boltrig/store/trajectory_postgres.py:121` `"async def expire_trajectories(self, *, now:"` | - |
| BT-REQ-0576 | `entity_provenance` mints and resolves opaque record refs with an idempotent unique index, but has no production caller and is a recorded deferral. | SCAFFOLDED | `docs/refactoring/unwired-claims-allow.json:111` "BLOCKER caller: the model-facing capability read" | - |
| BT-REQ-0577 | Background-job and birth-profile receipts are row-count bounded by an in-transaction advisory lock plus a prune, so concurrent boots cannot leave the cap exceeded. | IMPLEMENTED | `boltrig/store/birth_profiles.py:92` "SELECT pg_advisory_xact_lock(" | - |
| BT-REQ-0578 | List reads are clamped server-side: work pages to 500, memory lists to 200, observability pages to 10,000, audit search offset to 10,000. | IMPLEMENTED | `boltrig/store/base.py:74` "MAX_WORK_PAGE = 500" | SEC-69 |
| BT-REQ-0579 | The knowledge repository is a second holder of the RLS pool outside the `PostgresStore` MRO and carries its own tenant-binding decorator. | IMPLEMENTED | `boltrig/knowledge/postgres_repository.py:38` "@bind_tenant_on_store_methods" | SEC-65 |
| BT-REQ-0580 | The in-memory store enforces no foreign key, no CHECK constraint and no RLS, so those defect classes are visible only on the Postgres leg. | IMPLEMENTED | `docs/GOAL-trustworthy-gate.md:113` "The in-memory store enforces no FK, so it passed everywhere" | - |
| BT-REQ-0581 | A missing `BOLTRIG_TEST_DATABASE_URL` ends the test run non-zero rather than silently skipping the Postgres legs. | IMPLEMENTED | `tests/conftest.py:44` `"\"BOLTRIG_TEST_DATABASE_URL\","` | - |
| BT-REQ-0582 | No SQLite store backend exists; `aiosqlite` is a dev dependency with no importer in the tree. | DEAD | `pyproject.toml:47` `"\"aiosqlite>=0.20\","` | - |
| BT-REQ-0583 | Backups are `pg_dump -Fc`, each archive is verified parseable by `pg_restore` before upload, and the recovery-set manifest is uploaded last. | IMPLEMENTED-UNTESTED | `scripts/backup.sh:8` "a recovery-set manifest is uploaded LAST" | - |
| BT-REQ-0584 | `credential_refs.expires_at` is written for rotation alerts and read by no store query. | IMPLEMENTED-UNTESTED | `boltrig/store/schema.sql:719` "for rotation alerts (US-COST-04)" | - |
| BT-REQ-0585 | `agent_capabilities` deliberately has no primary key and is unique on `(tenant_id, coalesce(workspace_id,''), name)` so two workspaces may each own the same profile name. | IMPLEMENTED | `boltrig/store/schema.sql:341` "There is deliberately NO primary key" | - |
| BT-REQ-0586 | `workspace_members` carries `tenant_id` in its primary key because workspace ids collide across orgs by construction. | IMPLEMENTED | `boltrig/store/schema.sql:1886` "collides across orgs BY CONSTRUCTION" | - |
| BT-REQ-0587 | `identity_orgs` is a pre-tenant membership index holding no secret and no business data, and is never the authority for an access decision. | IMPLEMENTED | `boltrig/store/schema.sql:1906` "It is NOT an authority: every" | SEC-08 |
| BT-REQ-0588 | `K-22`, the tenant-isolation kernel invariant cited by `schema.sql` and `rls.sql`, is not a declared id in `tests/invariants.yaml`, so no test is bound to it by that name. | IMPLEMENTED-UNTESTED | `boltrig/store/rls.sql:1` "Boltrig RLS overlay (SEC-08 / K-22 / SEC-65)" | - |
