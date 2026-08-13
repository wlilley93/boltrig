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

> **CORRECTED 2026-08-06. Two of the three gaps below never existed, and the
> third was deferred because of one of them.** Docker was installed on the M4
> the whole time. What produced "no docker" was `which docker` run over
> non-interactive SSH, and a non-interactive shell does not source `.zprofile`,
> which is the only place `brew shellenv` puts `/opt/homebrew/bin` on PATH.
> Homebrew has been on that machine since 1 Aug and carries `colima`, `docker`,
> `docker-compose` and `lima`. The corrected state is in the next section; the
> original text is kept below so the mistake stays legible.
>
> **A `which` over SSH is a fact about PATH, not about the machine.** Every
> claim in the original section traces to that single reading. Probe with the
> login environment (`ssh host 'zsh -lc "which docker"'`) or with an absolute
> path, and treat a negative from a bare `which` as unproven rather than false.

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

## What the M4 actually has, measured 2026-08-06

| | state | note |
|---|---|---|
| colima | **running**, 0.10.3 | `default` profile, aarch64, macOS Virtualization.Framework, virtiofs |
| docker | **29.7.1** CLI, **29.4.0** server | socket at `~/.colima/default/docker.sock` |
| docker-compose | **5.3.1** | |
| uv | **0.12.2** | installed 2026-08-06, so `make relock` works |
| `.venv` | Python 3.12.13 | matches the 3.12 CI runs at all three job sites |
| `core.hooksPath` | **still unset** | now unblocked; gap 2's stated reason is gone |

Gap 3 is closed and gap 1 was never real, so **the only remaining item is
arming the hook**, and it should be armed with proof rather than on faith: run
`make python-quality` once and confirm `with_test_postgres.sh` really stands the
pgvector container up under colima. Arming a hook you have not watched pass is
the same error as declaring a gap you have not watched fail.

Two things the cutover has to work around, both measured on the same pass:

- **colima is provisioned at 4 CPU / 6GiB.** The stack is kernel, fleet-worker,
  worker-ui, redis, bifrost, hatchet engine, hatchet dashboard and postgres.
  Expect to `colima stop && colima start --cpu N --memory N` before it fits.
- **`127.0.0.1:5432` on the M4 is already taken**, by an `alpine/socat`
  container named `opbox-vm-relay` which also holds 8088 and 18000. A boltrig
  postgres that assumes the default port will either fail to bind or, worse,
  something will connect to the relay and reach an entirely different database.

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

Every worktree registration on the M4 pointed at a host-local path,
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

~~Seven dependabot PRs, #217 to #223. Every one was red for the two advisories
above rather than for anything in its own diff, so they should go green on a
rebase.~~

**Corrected and closed out 2026-08-06.** The prediction held for three of the
seven and was wrong about the other four, which failed on their own diffs.

Three went green and merged: **#217** python-minor-patch, **#220** site-minor-patch,
**#222** actions-minor-patch. #220 turned out to touch only `site/pnpm-lock.yaml`,
so it did not disturb the `brace-expansion` pins after all.

Four were impossible rather than stale, and are now bounded in
`.github/dependabot.yml` at the constraint that refuses them:

| PR | refused by |
|---|---|
| #218 websockets 17.0 | `cognee>=1.2.0 depends on websockets>=15.0.1,<16.0.0` |
| #219 + #221 mcp 2.0.0 | `browser-use==0.13.7 depends on mcp==1.26.0`, and the line they edit is the override closing PYSEC-2026-3481/3482/3483 |
| #223 node 26 alpine | `ui/Dockerfile` and five `node-version` lines in `ci.yml` all say 22 |

#219 and #221 were the same one-line diff twice, because
`deploy/browser-cli-overrides.txt` is reachable from the pip scans at both `/`
and `/deploy`. Both ecosystems carry the bound now; an ignore in one place only
halves the noise and fixes nothing.
