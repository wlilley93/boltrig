# Goal: close G3 and let two agent cells run at once

## The goal statement

**Make it safe for two mutually distrusting agent cells to run concurrently in the Boltrig kernel,
so the trusted Codex lane can serve more than one tenant at a time.**

Done means, precisely:

1. Each Codex cell runs under its own uid, holding no capabilities, unable to reach any sibling's
   uid or climb back to the API's.
2. A hostile cell that holds full write access to everything its own uid can reach **cannot obtain
   another cell's bearer**, including by rewriting that cell's `config.toml`. Proved by an
   adversarial test with two live cells, not by argument.
3. `config_toml_protected` is True and the provider no longer refuses a second concurrent cell.
4. Every step is inside [2026] VJS-CC-VJS 7: `CAP_SETUID` and `CAP_SETGID` only, never `CAP_CHOWN`,
   never `CAP_SETPCAP`, never `CAP_SYS_ADMIN`; `no_new_privileges` and `read_only` retained.

**Not in this goal**, deliberately: `production_ready` (a separate application under VJS-CC-VJS 4
F9), the PR8 write/effects phase, and the prod cutover (approved, scheduled separately).

## Why this is the goal

The session goal is a Codex runtime "trustworthy enough that a team can rely on it". Two of three
parts are done: Codex is the runtime, and the kernel genuinely governs it. The third part is this.
Today a single shared uid means [2026] VJS-CC-VJS 5's finding stands: hostile cell A obtains cell B's
cross-tenant bearer with no race and no defect in the attestation logic, held shut only by a runtime
refusal to start a second cell. That refusal is the last thing standing between the lane and a
multi-tenant vulnerability, and it is also the thing preventing a team from using it.

## The one rule that governs how it is built

**Prove, do not assert.** Six times in the preceding session the posture of this lane was stated
more strongly than the evidence supported, and every correction came from running something rather
than reasoning: a wire capture, an exit code, a re-read of a directive, an adversarial test that
found a path traversal in freshly written code. Anything claimed here is claimed because it was
observed. Where it was only read, it says so.

## The work, in dependency order

| # | Directive | What it is | Gate |
|---|---|---|---|
| 1 | J2 | per-cell-slot tmpfs (`uid=`/`gid=`/`mode=0700`) + a uid allocator that never reuses a uid between concurrent cells | unit |
| 2 | J1 | route `CodexCellSupervisor` through the spawner when per-cell mode is available; fall back to the in-process spawn when it is not | unit |
| 3 | J5 | the cell asserts its own `/proc` state before it is handed any credential | unit |
| 4 | J1 | enact: `user: "0:0"` + `cap_add: [SETUID, SETGID]` in compose, `ENTRYPOINT` at `kernel-entrypoint.py` | image build |
| 5 | J10 | startup boundary assertion: uids actually distinct, never reused, fail closed | unit + live |
| 6 | J11 | record the uid-0 necessity at the grant site, citing the judgment | doc |
| 7 | J7 | adversarial test in the REAL supervisor: a spawned cell tries to setuid back, sideways, and to execve an image setuid binary | live |
| 8 | J9 | **the gate.** Two live cells, hostile A with full write access to everything its uid can reach, must not obtain B's bearer by the `config.toml` vector | live |
| 9 | - | flip `config_toml_protected` to True and lift the single-cell refusal | live |

Nothing after step 4 may be skipped, and step 9 depends on step 8 passing on its own terms.
`production_ready` stays False throughout, under J13.

## Standing constraints

- One writer: the main loop applies and verifies; `make check` is the net.
- `.venv/bin/python`, never bare `pytest`. `make check` exit 137 is the OOM killer under load.
- 400 lines per file, 80 per function.
- No em dashes anywhere, in code comments or prose.
