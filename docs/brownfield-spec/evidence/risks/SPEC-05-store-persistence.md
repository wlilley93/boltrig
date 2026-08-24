# Risks harvested from SPEC-05-store-persistence.md

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

---

RISK: The migration-parity test compares tables, columns, constraints, indexes and
sequences, but never `pg_policy` or `relrowsecurity`, so the divergence above is
invisible to the gate that exists to catch bootstrap-versus-Alembic drift. The
Alembic path ends with policies on 19 tables; the `schema.sql` path ends with
none; the test calls them identical.
[`tests/integration/test_migration_parity.py:87`](../../../tests/integration/test_migration_parity.py) `"_CATALOGUE_QUERIES = {"`.

---

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

---

RISK: `trajectory_events` rows are written with `expires_at = now + ttl_days` and
NOTHING ever deletes them. `expire_trajectories` has no caller outside its own two
implementations and `tests/test_trajectory.py` (bounded:
`rg -n "expire_trajectories" .`, 2026-08-24, pinned tree, three files). There is no
trajectory entry in the fleet worker's janitor set and no `trajectory` value in the
`background_job_receipts.job_name` CHECK. Turning `BOLTRIG_TRAJECTORY=1` on
therefore accumulates verbatim prompts and tool payloads forever behind an expiry
that is decorative.
[`boltrig/store/trajectory_postgres.py:121`](../../../boltrig/store/trajectory_postgres.py) `"async def expire_trajectories(self, *, now: datetime | None = None) -> int:"`.

---

RISK: `expire_trajectories` takes no tenant, so under RLS the class decorator binds
nothing and `_apply_guc` sets `app.tenant_id` to the empty string, meaning the
DELETE would match zero rows and report success. If the sweep is ever wired, it
will present as working and delete nothing, which is the exact shape of the 2026-07-31
janitor outage.
[`boltrig/store/tenant_scope.py:70`](../../../boltrig/store/tenant_scope.py) `"tenant_id = _tenant_of(candidate)"`.

---

RISK: `idempotency_keys` has no retention. Completed rows persist with their
cached `result` JSONB forever; the table's only purge in the whole tree is the
one-off TRUNCATE inside migration 0024. On a busy tenant this is unbounded growth
holding cached verb outputs (bounded: `rg -n "idempotency_keys" boltrig/ scripts/ deploy/ tests/`,
2026-08-24, five hits, none a sweeper).
[`boltrig/store/schema.sql:653`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS idempotency_keys ("`.

---

RISK: Four tables the schema describes as immutable or append-only keep full
UPDATE and DELETE grants for `boltrig_app`, because the REVOKE list names only
four different tables. `conversation_summaries` ("no row is ever updated"),
`memory_events` ("append-only"), `agent_messages` ("Message envelopes are
immutable") and `workflow_trigger_deliveries` ("One immutable receipt") are all
rewritable by a compromised app role.
[`boltrig/store/rls.sql:41`](../../../boltrig/store/rls.sql) `"append_only text[] := ARRAY["`.

---

RISK: `mcp_servers.credential` is a nullable TEXT column named for credential
material with no writer and no reader anywhere in the tree. The current INSERT
names its columns explicitly and omits it; no UPDATE sets it (bounded:
`rg -n "mcp_servers" boltrig/ --glob '!*.sql'` plus a targeted scan of
`boltrig/store/mcp_*.py` for the column name, 2026-08-24). A column shaped like a
secret that nothing owns is a place a secret gets put later.
[`boltrig/store/schema.sql:1372`](../../../boltrig/store/schema.sql) `"credential  TEXT,"`.

---

RISK: `user_sessions.csrf_token` is stored in plaintext while every other bearer in
the identity group is a sha256. A read of the sessions table yields working CSRF
tokens for every live session. The column's own comment calls it a
"session-bound double-submit CSRF token", which is a lower-value secret than a
session cookie, but it is still the only unhashed bearer in the group.
[`boltrig/store/schema.sql:1761`](../../../boltrig/store/schema.sql) `"csrf_token    TEXT,                             -- session-bound double-submit CSRF token"`.

---

RISK: The `Store` Protocol in `base.py` does not declare the camera-binding and
camera-lease methods, yet `boltrig/kernel/camera_agent_routes.py` calls six of them
off `kernel.store`. A second backend written against the declared Protocol would
typecheck and then fail at runtime on the camera routes.
[`boltrig/kernel/camera_agent_routes.py:194`](../../../boltrig/kernel/camera_agent_routes.py) `"if not await kernel.store.upsert_camera_binding(binding):"`.

---

RISK: The knowledge repository claims the set of `_RlsPool` holders outside the
`PostgresStore` MRO is complete at two, but `PostgresTrajectoryStore` is a third
and was added later. The claim is stale rather than wrong in effect (the third
class IS decorated), but a reader trusting it would stop looking.
[`boltrig/knowledge/postgres_repository.py:36`](../../../boltrig/knowledge/postgres_repository.py) `"Checked the whole tree for others - every other _RlsPool user IS a PostgresStore"`.

---

RISK: `schema.sql`'s trajectory comment says the table has no `tenant_isolation`
policy "below" because the migration does not create one, but `rls.sql` DOES fence
`trajectory_events` and says it is correcting exactly that. The two comments
disagree about the live state of the fence on a table holding verbatim prompts.
[`boltrig/store/schema.sql:2841`](../../../boltrig/store/schema.sql) `"no tenant_isolation policy below -- the migration does not create one."`
versus
[`boltrig/store/rls.sql:129`](../../../boltrig/store/rls.sql) `"policy and this is where that is corrected."`.

---

RISK: The store layer cites `K-22` as the kernel invariant for tenant isolation in
both `schema.sql` and `rls.sql`, but `K-22` is not a declared id in
`tests/invariants.yaml`; only `K-2`, `K-5`, `K-9`, `K-13`, `K-19` and `K-20`
exist there (bounded: `grep -n "^  K-" tests/invariants.yaml`, 2026-08-24, six
matches). The isolation property is in fact bound, by `SEC-08`, `SEC-65` and
`SEC-188`, so nothing is unproven; the citation simply names an id no gate can
resolve, which is how a reader concludes a control is bound when it is bound
under a different name.
[`boltrig/store/rls.sql:1`](../../../boltrig/store/rls.sql) `"Boltrig RLS overlay (SEC-08 / K-22 / SEC-65)"`.

---

RISK: `migrations/env.py` falls back to `postgresql://localhost/boltrig` when no
URL variable is set, so a migration run with a typo'd or unexported variable
targets a local database silently instead of refusing.
[`migrations/env.py:28`](../../../migrations/env.py) `"or \"postgresql://localhost/boltrig\""`.

---

RISK: `audit_append` has no ON CONFLICT and no in-store retry, and the writer's
serialiser is a per-process asyncio lock. Across replicas the only guard is
`UNIQUE (tenant_id, seq)`, and a lost race is not retried inline; it is deferred to
the outbox. Under sustained multi-replica write pressure the chain advances
through the janitor rather than the hot path, which is correct but is a throughput
cliff nothing measures.
[`boltrig/kernel/audit.py:321`](../../../boltrig/kernel/audit.py) `"One lock per tenant; for a multi-process deployment the Postgres"`.

---

RISK: `artifacts.content` is a `BYTEA` column capped at 100 MB per row with no
retention and no external storage, in the same database as the audit chain. A
tenant generating artifacts grows the primary database and every `pg_dump` with it.
[`boltrig/store/schema.sql:2765`](../../../boltrig/store/schema.sql) `"CONSTRAINT artifact_size_bounded CHECK ("`.

---

RISK: `credential_refs.expires_at` exists "for rotation alerts" and nothing in the
store reads it. An expired credential reference is never surfaced by the store
layer (bounded: `rg -n "expires_at" boltrig/store/credential_references.py boltrig/store/postgres.py`
around the credential methods, 2026-08-24; it is written on upsert and read by no
query).
[`boltrig/store/schema.sql:719`](../../../boltrig/store/schema.sql) `"expires_at  TIMESTAMPTZ,                            -- for rotation alerts (US-COST-04)"`.
