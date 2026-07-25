# Prod roll 0.3.9 - DONE, and the two things it uncovered

Date: 2026-07-25, completed 15:30 UTC.
Supersedes the earlier revision of this file, which said the roll was staged but
not executed. It has been executed.

## Final state

| stack | kernel / fleet / ui | schema | readyz |
| --- | --- | --- | --- |
| dev (beelink) | locally built, current `main` | `0038` | ready |
| `app.boltrig.io` | `0.3.9` (digest-pinned) | `0038` | ready |
| CV (client tenant) | `0.3.9` (digest-pinned) | `0038` | ready |

Verified by importing the modules INSIDE each running container rather than
trusting the tag: `foreign_run_asserted`, `_owner_matches`, the sender-keyed
channel binding upsert and `SETTLED_STATUSES` are all present on both prod
kernels, and the shipped JS bundle really contains the console fix. Both public
endpoints answer 200.

## The CV tenant was already down when I got there

Not a trap, an outage. The stack had been rolled to `0.3.8` at 14:38 while its
database stayed at `0037_secure_input`. `0.3.8` carries migration `0038` and
declares `EXPECTED_ALEMBIC_HEAD = 0038`, so `/readyz` had been answering 503 with
`{"migration": {"status": "failed", "reason": "head_mismatch"}}` for about forty
minutes. Docker reported the container "healthy" throughout, because the
container healthcheck is `/healthz`, not `/readyz`.

**That gap is the lesson worth keeping: `healthy` in `docker ps` does not mean the
kernel is serving.** Only `/readyz` knows about the schema.

It failed CLOSED, which is the only reason this was recoverable rather than a
silent data fault: the new code's `ON CONFLICT (tenant_id, workspace_id, user_id)`
has no matching constraint on a `0037` schema, so workspace membership writes
would have errored rather than gone somewhere wrong.

Fixed by the recorded recipe - stop `kernel` + `fleet-worker`, leave `postgres`
up, migrate, start - after rehearsing the exact SQL against a restore of that same
database. The prod checkout is 35 commits behind `main` and has no alembic
installed, so the migration was applied as the identical SQL the revision runs,
in one transaction, ending with the `alembic_version` update. Verified after:
`0038`, three-column key, row count unchanged.

## The box was at 100% disk

Discovered because a one-line `cp` of a compose file failed with "No space left on
device" mid-roll. `/dev/sda1` was 148G of 150G used, **zero bytes free**, with
141.7GB of Docker images of which 108.5GB was reclaimable.

A production host at 0 bytes is a worse hazard than anything this roll was fixing:
Postgres cannot write, logs cannot rotate, and the next image pull fails. Cleared
in three steps, least destructive first - build cache (2.0GB), dangling images
(2.4GB), then images unused for over a week (9.5GB), deliberately keeping the last
week's images as rollback targets. Now 45G free, 69% used.

**This needs a standing answer, not another manual sweep.** 69GB is still
reclaimable and the box will refill. A weekly `docker image prune -a --filter
until=168h` plus a disk alarm is the obvious shape.

## What shipped in 0.3.9

Everything on `main` as of `f704122`: both security fixes (the cross-tenant
membership write and caller-asserted run identity, each with two independent
fences), the four store/kernel/fleet sweep fixes, the four console fixes, and the
migration `0038` widen without which `0038` cannot write its own revision id on a
stamped database.

`0.3.8` already contained the two security fixes. `0.3.9` adds the rest and puts
the whole fleet on one version.

## Notes for next time

- `~/Projects/boltrig-main` on the prod box is 35 commits behind `main` and has no
  virtualenv. Migrations cannot be run from it as it stands. Either bring it
  forward and give it an environment, or ship `migrations/` in the kernel image so
  the image that expects a head can also reach it.
- The image does NOT ship `migrations/` or `alembic.ini` today; that is why the
  SQL had to be applied by hand.
- A pinned-but-unapplied image in a compose override is a loaded gun. CV's override
  pinned `0.3.8` while running `0.3.6` earlier in the day; the next `up -d` for any
  unrelated reason is what fired it.
