# Prod roll: rehearsed, staged, NOT executed - and one live trap

Date: 2026-07-25 15:15 UTC

## The trap, first, because it is live on a client tenant

`~/Projects/opbox-prod/boltrig-tenants/cv/compose.override.yml` already pins
`boltrig-kernel:0.3.8` and `boltrig-fleet:0.3.8`, but the CV containers are still
running `0.3.6` and the `cvboltrig` database is still at `0037_secure_input`.

`0.3.8` carries migration `0038` and its `EXPECTED_ALEMBIC_HEAD` is
`0038_workspace_members_tenant_key`. So **the next `docker compose up -d` on that
stack, for any reason at all, brings up a kernel that cannot become ready** until
`0038` has been applied. Verified directly against a restore of the CV database:
the image reports it expects `0038`, the database says `0037`.

It fails CLOSED (readyz 503) rather than silently, which is the good news. The bad
news is that a routine restart is now a de facto outage until someone runs the
migration. The same pin/DB mismatch does not exist on `app.boltrig.io`, which is
pinned and running `0.3.1`.

This is a coupled change and cannot be de-risked by doing half of it. The new code
does `ON CONFLICT (tenant_id, workspace_id, user_id)`; the old schema has no such
constraint. Migrating first breaks the RUNNING old code, whose
`ON CONFLICT (workspace_id, user_id)` no longer matches a constraint either.
Schema and code move together or not at all.

## Why I did not just finish it

Three things, together:

1. **Another agent session is actively working these boxes right now.** It cut
   `0.3.8` at 14:36, edited CV's override to pin it, and committed to `main` at
   15:07, one minute before my last commit. Two sessions performing a coupled
   schema+code roll on the same client tenant is the highest-collision operation
   available.
2. **I already caused an outage on this exact tenant today** by running alembic
   under a live kernel (RestartCount 38, roughly ten minutes of crash-loop). The
   recipe that came out of it is in
   `docs/findings/2026-07-25-prod-roll-0.3.1.md`.
3. Deploying to prod is one of the few acts the standing instructions reserve for
   explicit authorisation.

## What IS done

- Every fix is on `main` and `ci` + `security` are green on it.
- `0.3.8` **already contains both security fixes** - verified by inspecting the
  published image, not by inferring it from timestamps: `foreign_run_asserted`
  and `_owner_matches` are both present, and its `schema.sql` carries
  `PRIMARY KEY (tenant_id, workspace_id, user_id)`. So the roll that stack is
  half-way through does deliver them.
- The **dev stack is fully rolled and verified**: on `0038`, three-column key
  live, kernel and fleet healthy, `readyz: ready`, and the running image confirmed
  to contain both fences.
- The migration is **rehearsed against restores of both prod databases**:
  `0037 -> 0038`, 99 tables before and after, row counts intact, and idempotent
  across a downgrade/upgrade cycle.
- No `0.3.7` tag was published. I started building one, then stopped when I found
  `0.3.8` already existed; nothing reached the registry, so the tag space is clean.

## What is NOT in 0.3.8

`0.3.8` was cut at 14:36 from a commit before these landed:

- `d419adf` - the store/kernel/fleet sweep group (channel binding re-bind,
  idempotency claim race, approval-vs-throttle ordering, post-terminal fault)
- `b9f4904` - the console group (SSE multi-turn, queued ack, stale key data, chat
  loader race)
- `cf572fa` - **the migration fix**, which matters here: without it `0038` applies
  its schema change and then dies writing its own 33-character revision id into a
  `varchar(32)` column, leaving the schema changed and the version row at `0037`.

Both prod databases have `varchar(64)`, so they are not exposed to that. The dev
box was, which is how it was found. Any future stamped-from-`schema.sql`
deployment would be.

## The roll, per stack, when it is authorised

Rehearsed; run from `~/Projects/boltrig-main` on `jellytot-prod` (currently 35
commits behind `main` - update it first, or the alembic chain it runs is stale).

```
docker compose -p <project> stop kernel fleet-worker      # NEVER migrate under a live kernel
BOLTRIG_DATABASE_URL=... python -m alembic upgrade head   # 0037 -> 0038
docker compose -p <project> up -d kernel fleet-worker     # on the pinned image
# verify: readyz == ready, alembic_version == 0038, and the running image
# actually contains the fix (import the module, do not trust the tag)
```

`app.boltrig.io` additionally needs its override bumped off `0.3.1`; CV's is
already pinned and only needs the migration and the recreate.
