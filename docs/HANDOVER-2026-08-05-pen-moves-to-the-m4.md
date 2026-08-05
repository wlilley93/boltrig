# Handover, 2026-08-05: the pen moves to the M4 Mac

The M4 (`mac-m4` / `mac-mini-m4-pro`, `~/Projects/boltrig`) is now the one writer for
this repo. The beelink is a reader. This note records what that machine can and
cannot do today, because two of the three gaps make the local gate net silently
weaker rather than loudly broken.

## What landed today, and why main moved five commits

Both are security, both were found by a sweep rather than by a failing test.

**`9fd5a49` SEC-195, opt-in channel boundary policy.** Committed 2026-08-02 and
never pushed: `boltrig/kernel/channel_policy.py` and
`tests/security/test_channel_policy.py` existed on one disk and no remote for
three days. Two opt-in fail-closed controls at channel intake. `allowed_chats`
absent keeps historical behaviour; present means allowlist mode, and an unknown,
missing **or malformed** allowlist is refused rather than read as no policy.
`thread_ceilings` stamps a per-thread `GrantSet` on the durable work item at
intake, and `authority.context_for` intersects it **again** at execution, so an
edited item can never widen the principal's grants.

**`75d2da6` and `bace197`, the CI unblock.** Every open PR was red on six checks
and none of it was any branch's diff. Two advisories published after main last
ran green on 2026-08-03:

| red check | actual cause |
|---|---|
| `site-build-test-lint` | GHSA-rgw5-rvv9-x895, `brace-expansion` |
| `Source security` | PYSEC-2026-3552, `cryptography` |
| `Container (kernel)`, `Container (fleet)` | CVE-2026-69247, the same cryptography, found by trivy inside the built image |
| `Security gate`, `quality` | aggregates that only require the others |

Two causes wearing six masks. **If CI goes red on a job your diff does not
reach, check when it last passed before checking what you changed.**

`GHSA-mh99-v99m-4gvg` is no longer suppressed. Its recorded grounds were "1.x
ends at 1.1.16 and 2.x at 2.1.2, the fix ships only in 5.0.8"; both halves became
false when 1.1.18 and 2.1.4 shipped. Gone from `ignoreGhsas` and from
`accepted-advisories.json`, which drops from 8 acceptances to 7.

## The three gaps on the M4, in the order they bite

**1. No docker, so `make python-quality` cannot run at all.** It shells out to
`scripts/with_test_postgres.sh`, which stands up a disposable pgvector container.
Without it, conftest ends the run non-zero rather than skipping quietly, which is
the right behaviour but means the full suite is unavailable. That leg is 211
tests: the RLS fence, store parity, migration parity and tenancy. A green run
without it is not a green run, and this repo has already lost a Postgres-only
foreign-key defect to exactly that gap.

**2. `core.hooksPath` is unset, so the pre-push gate is not armed.** The fix is
one command, `git config core.hooksPath .githooks`, and the hook is tracked in
the repo. **Do not run it before docker exists.** The hook's main gate is
`python-quality`, so on a docker-less box it would fail every push, and a hook
that cannot pass teaches `--no-verify`, which then survives the day docker
arrives. Docker first, then the config line.

**3. No `uv`, so `make relock` cannot run.** Needed to take a dependency fix. And
when you do: `--upgrade-package <name>`, never a blanket `UPGRADE=--upgrade`. A
security fix whose diff is four hundred unrelated bumps is one nobody reviews.

`.venv` is Python 3.12.13 and present.

## Audit every lock file, not the ones you remember

`make python-audit` reads **three** graphs. After rebuilding
`requirements-lock.txt` and `requirements-dev-lock.txt` today the audit still
reported the old cryptography, because it also runs pip_audit over
`deploy/browser-cli-requirements.txt`, compiled separately from its own `.in`
with its own overrides. Grep the target for every file it reads before believing
a clean result.

## Two stacks now exist, and only one of them is yours

The beelink is still running the full stack, healthy, and **it has not been
touched**: kernel, fleet-worker, worker-ui, redis, bifrost, hatchet engine and
dashboard, and `boltrig-postgres-1` holding 15MB of live data.

The dumps in `_migration/` were taken 2026-08-05 11:17, and the newest
`work_items.created_at` in the beelink database is 2026-07-25. **The dumps are
current with respect to real activity**, so the migration is not racing anything.
That was measured, not assumed.

Until the beelink stack is stopped, two systems can serve the same tenants from
different data. Decide which is authoritative and shut the other down;
do not leave both up.

## Housekeeping done on both machines

Every worktree registration on the M4 pointed at a `/home/jellytot/...` path,
because the tree was copied wholesale off the beelink including
`.git/worktrees/*`. All 29 were dead there. This is not cosmetic: a dead
registration still claims its branch and **refuses `git branch -f`**, which is
how it surfaced on the beelink, as an unrelated-looking refusal on a push.
`git worktree prune` cleared them; the M4 now lists one worktree, its own.

Also removed after verifying each was redundant, with archives kept:

| what | how it was verified |
|---|---|
| local `refactor/20260802-channel-policy` | its diff hashes identical to the merged `9fd5a49` |
| two `worktree-agent-*` codex branches | every file on main; the one absent test targets a `materialize_helper` mechanism main replaced |
| the `other-agent WIP` stash | main carries all ten of its test cases verbatim |

Archives in `~/Backups` on the beelink: `m4-boltrig-uncommitted-20260805.tgz`
(the M4's own WIP, taken before anything was touched),
`m4-boltrig-superseded-20260805.tgz`, `boltrig-agent-worktree-scratch-20260805.tgz`,
`boltrig-superseded-codex-lane-20260805.tgz`.

The M4's nine uncommitted files were checksummed before and after the
fast-forward and are byte-identical: the two audio adapters, `docker-compose.vm.yml`,
`run-ui-8080.sh`, the two Dockerfiles, `ui/vite.config.ts`, `_migration/` and the
disabled beelink-only override.

## Still open

Seven dependabot PRs, #217 to #223. Every one was red for the two advisories
above rather than for anything in its own diff, so they should go green on a
rebase. #220 is the site group and may supersede the `brace-expansion` pins
raised today.
