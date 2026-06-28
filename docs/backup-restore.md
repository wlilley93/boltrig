# Backup and restore

Nankle's durable state lives in one PostgreSQL database (work items, registry,
audit, HITL, library metadata, budgets). Backing that up plus the library
artefacts restores the fleet (DoD item 7). Put backups on encrypted media (see
`DEPLOYMENT.md`).

## What to back up

1. **PostgreSQL** - the whole `nankle` database (the durable Store, S6).
2. **Library artefacts** - `libraries/` (skills, workflows, prompts) and
   `manifest.yaml`. These are data, version them in git or snapshot them.
3. **Secret store** - backed up by Vault/KMS itself, not here. The app DB holds
   only references (SEC-04).

## Backup

```bash
make backup                 # -> ./backups/nankle.dump (pg_dump custom format)
# or explicitly:
docker compose exec -T postgres pg_dump -U nankle -d nankle -Fc > backups/nankle.dump
```

Run it on a schedule (cron / a scheduled workflow) and copy the dump off-box to
encrypted storage. The custom format (`-Fc`) supports selective, parallel restore.

## Restore

```bash
make restore                # restores ./backups/nankle.dump into the postgres service
# or explicitly:
docker compose exec -T postgres pg_restore -U nankle -d nankle --clean --if-exists < backups/nankle.dump
```

Restore order for a full rebuild:

1. Bring up `postgres` (the idempotent `schema.sql` initialises an empty DB).
2. `make restore` to load the dump (`--clean --if-exists` replaces objects).
3. Restore `libraries/` + `manifest.yaml` from their snapshot.
4. Start `kernel` and `fleet-worker`.

## In-flight runs after restore

- Work items and the kanban come back with the database, so the board renders the
  restored state immediately.
- Blocking HITL pauses are durable (NFR-REL-01): a pending approval survives the
  restore and resumes on answer.
- Full durable run-resume of long/recursive runs is owned by Hatchet; restore its
  engine database alongside Nankle's so paused runs continue. Without Hatchet the
  local executor does not resume across a restart (it is the dev fallback).

## Verify a restore

```bash
make backup
docker compose down && docker volume rm $(docker compose config --volumes | head -1) 2>/dev/null || true
docker compose up -d postgres && sleep 5 && make restore
curl -s localhost:8000/v1/work -H 'x-nankle-tenant: <tenant>' -H 'x-nankle-role: org-admin'
# the restored work items should be listed
```
