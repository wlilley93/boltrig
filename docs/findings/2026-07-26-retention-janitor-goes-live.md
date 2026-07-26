# Wiring retention makes the next deploy delete data

Date: 2026-07-26. Read this before rolling any tenant past `904e34b`.

## What changed

`run_retention_forever` had **zero callers**. No compose service, no Makefile target,
no deploy unit, no `__main__` - only a docstring telling the reader to schedule it
themselves, which nothing ever did. So `purge_closed_conversations` had never been
called in any deployment, while `docs/security-conformance.md` recorded DATA-07 and
PRIV-04 as BUILT and SEC-74 claimed a deleted conversation no longer sat in Postgres
indefinitely.

The fleet worker now starts it, on `BOLTRIG_RETENTION_INTERVAL` (default 3600s), with
the window from `privacy.retention_days` (default 30).

## The consequence, stated plainly

**On the first sweep after a roll, every tenant hard-deletes its entire backlog of
closed conversations older than the window, in one pass.** The rows and their messages
go; the audit log does not (it is exempt by design, SEC-16). This is the behaviour
three records already claimed, and it is what right-to-erasure requires. It is also
irreversible, and on a box that has been accumulating since it was provisioned the
first sweep is much larger than every sweep after it.

That asymmetry is the whole reason this note exists. Steady-state the janitor deletes
a day's worth of aged threads. The first run deletes everything that aged while
nothing was running.

## Before rolling a tenant

1. **Count the backlog first.** On the tenant's database:

   ```sql
   SELECT count(*) FROM conversations
   WHERE status = 'CLOSED' AND updated_at < now() - interval '30 days';
   ```

   Substitute the tenant's own `privacy.retention_days` if the manifest sets one.

2. **Take a backup that predates the first sweep** and verify it restores. The
   backup sidecar exists (SEC-71); use it. The audit chain will not help here - it
   records that actions happened, not conversation bodies.

3. **If the count is large or surprising**, roll with `BOLTRIG_RETENTION_INTERVAL=0`
   first. That is a deliberate, logged "off" (the worker says which it did at boot),
   not the silence the janitor lived in before. Then review the backlog with whoever
   owns the tenant's data and turn it on.

## What was deliberately NOT done

The janitor is **on by default**, not opt-in. Shipping it default-off would have
recreated the exact defect: a mechanism that exists, is tested, and never runs, with
the compliance table still reading BUILT. The honest position is that erasure runs and
the operator is told what the first run means - which is this note.

No tenant has been rolled onto this. Deploying it deletes real client data, so it
needs an explicit decision per box, not a green gate.
