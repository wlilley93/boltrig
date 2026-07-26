# The fleet worker gets a health signal that can go red

Date: 2026-07-26. Both tenants rolled to fleet `0.4.4`, digest-pinned.

## Final state

| stack | kernel | fleet | readyz | fleet healthcheck |
| --- | --- | --- | --- | --- |
| `app.boltrig.io` | `0.4.3` | `0.4.4` | ready | `fleet receipt ok` |
| CV (client tenant) | `0.4.3` | `0.4.4` | ready | `fleet receipt ok` |

Fleet digest `sha256:332295e2…`, confirmed in the registry with `buildx
imagetools inspect`, not from the push exit code. The kernel is deliberately NOT
rolled: nothing in this batch changes kernel runtime, and a rebuild with no delta
is risk for nothing.

## What was wrong

The fleet worker's container healthcheck was `python -c "import boltrig"`. It
proves an interpreter can import a module. It passes in a container whose pump
died on boot, whose database is unreachable and whose tools never came up. It
could not go red for any outage an operator cares about.

This was known and recorded as debt rather than fixed, on the stated grounds that
`python -m boltrig.api.worker` exposes no endpoint to probe. That grounds was
half right. There is no endpoint, but there IS evidence: every heartbeat the
worker signs a short-lived receipt into Redis naming which tools probed ok, and
the kernel's `/readyz` already consumes it. The readiness surface existed for
months; nothing on the worker side ever read it back.

## What now runs

`boltrig fleet-health` reads that receipt and exits non-zero when it is missing,
stale, forged, for another tenant, or degraded.

Proven **on production**, in the running container, not only in tests:

| condition | result |
| --- | --- |
| normal | `fleet receipt ok (tenant=default)` exit 0 |
| wrong signing key (forged or rotated) | `fleet receipt missing` exit 1 |
| Redis unreachable | `fleet receipt unavailable` exit 1 |

Freshness is the half that makes it a liveness check too: the publisher writes
under a 30s TTL and reheartbeats every TTL/3, so a receipt that is merely PRESENT
but not fresh means the heartbeat loop stopped, and the probe fails it.

Where the heartbeat is legitimately disabled - no `REDIS_URL`, or a placeholder
audit key, which is the designed dev posture and is rejected on purpose - it
exits 0 saying **NOT CHECKED** rather than a bare green. A probe that is
permanently red on every offline deployment teaches operators to ignore it, which
is the failure this exists to remove. `BOLTRIG_FLEET_HEALTH_REQUIRE_RECEIPT=1`
makes it fatal for a deployment that considers the heartbeat mandatory.

That discharges the last entry in `docs/refactoring/health-claim-exemptions.json`.
The file is now empty and the ratchet test asserts it stays that way.

## start_period was a guess, and it was wrong

Set at 20s. Measured on this box: container start 09:23:47 to "delegation pump
live" 09:24:23 is **36 seconds** of kernel build and org assembly before the
heartbeat task is even created, and the first receipt lands a probe-and-publish
cycle after that. The probe would have been failing for the whole of a normal
boot. Now 90s, from the measurement.

## Two defects found on the way

**The health-claims gate only understood readiness reached over HTTP,** so the
honest probe failed it and the only route to green would have been to re-add the
waiver I had just discharged. It now admits a command form, with both halves
derived: the subcommand must actually be dispatched by `boltrig/api/cli.py`, and
the module behind it must read the same evidence the `/readyz` HANDLER reads.
Seeded and measured - `boltrig version`, `boltrig worker`, `boltrig doctor`,
`boltrig chat`, a renamed subcommand, the original `import boltrig`, and the real
probe with its receipt reads deleted all FAIL; only the real probe passes.

Two wrong versions of that rule were built first, and both were caught by seeding
rather than by reading: resolving the subcommand from a 400-character text window
read past the end of a short branch into the next one, and taking the evidence
set from the whole FILE serving `/readyz` pulled in 69 symbols including `Store`,
which let `boltrig worker` - a command that would block forever as a healthcheck -
count as consulting readiness.

**The ledger schema fixture had never once built what a deployment builds.** CI
went red on nine `relation "channels" does not exist` errors. `ddl()` claimed to
build "the execution-ledger schema exactly as a deployment builds it" and
replayed the chain from 0026; `0035_channel_durability` alters `channels`, created
at 0019, so against an empty database it had ALWAYS failed. It stayed invisible
because a long-lived local test database already had the table, and in CI the
outcome depended on whether `test_migration_parity.py` happened to be ordered
first. `pytest-randomly` - installed for exactly this - dealt a different order on
its first real outing and found it. Now the whole chain replays, which is what the
docstring always claimed. See `73c2215`.

## Process notes worth keeping

- **`make gate-status | tail` masks the exit code,** so `make gate-status && git
  push` is inert when piped. I pushed over an unproven `main` because of it. Use
  `set -o pipefail`, or do not pipe the guard. This is the third form of the same
  masked-exit-code mistake recorded in three days.
- **A 64-hex test key is indistinguishable from a real one.** I wrote one as a
  fixture and gitleaks stopped it, correctly. The fixture is now obviously a
  fixture; the literal survives in history at `fdbe6f6`, so it is named exactly in
  `.gitleaks.toml`, path and value, suppressing nothing else.
- **`git stash` in this tree is dangerous.** Another session works in the same
  `.git`; a stash swept up their in-flight Dockerfile work. It popped back clean,
  but there was no reason to stash at all - gitleaks reads its config from the
  working tree.

## Not carried

`boltrig-ui` stays at `0.3.9`: no console change, so nothing to roll and no
`sessionVersion` bump needed. The kernel stays at `0.4.3`.
