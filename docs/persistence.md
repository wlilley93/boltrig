# Persistence (the durable Store)

Nankle's kernel depends only on the `Store` protocol (`nankle/store/base.py`). Two
implementations satisfy it identically; the kernel cannot tell which it runs on.

| Store | Module | Use |
| --- | --- | --- |
| `InMemoryStore` | `nankle/store/memory.py` | dev, offline tests, single process (non-durable) |
| `PostgresStore` | `nankle/store/postgres.py` | production, durable (asyncpg, PostgreSQL 16) |

## Selection (the seam)

`nankle/api/bootstrap.py::build_store()` returns `PostgresStore` when
`DATABASE_URL` is set, else `InMemoryStore`. Nothing else in the system changes.
Because the asyncpg pool is loop-bound, the kernel is built inside the FastAPI
lifespan (on the serving loop), not at import.

```
DATABASE_URL=postgresql://user:pass@host:5432/nankle   # -> PostgresStore
# (unset)                                                # -> InMemoryStore
```

## Schema and migrations

`nankle/store/schema.sql` is the single source of truth for the schema. The DDL
is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`), and
`PostgresStore.connect(apply_schema=True)` applies it on every boot, so a fresh
database self-initialises and an existing one is left intact. The Docker Compose
`postgres` service also loads `schema.sql` on first boot.

Tenant isolation (SEC-08, K-22) is enforced in every query by `tenant_id`
scoping. For defence in depth a production deployment should additionally enable
PostgreSQL row-level security with a non-superuser role and a per-transaction
`app.tenant_id` GUC (see the header of `schema.sql`).

Alembic is listed as a dependency for when additive, ordered migrations are
needed (column adds, backfills). Until then the idempotent `schema.sql` apply is
the migration path; introduce Alembic by baselining it against the current
schema before the first breaking change.

## Verification

The Postgres path is proven by `tests/store/test_postgres_store.py` (skipped
unless `NANKLE_TEST_DATABASE_URL` is set; CI provides a Postgres service):
round-trip CRUD, grant denial + audit, audit-chain verification, budget
hard-stop, the `apply_manifest` async seed path, durability across a reconnect
(restart survival), and tenant isolation parametrised over both stores (SEC-08).
