# Round-1 refresh findings — deterministic + adversarial wave, 2026-08-23

Worktree `boltrig-sweep` @ origin/main (35383663). Re-baseline after 7 weeks of
drift on arc-1 (started 2026-07-01 at 110 files / ~17.2k LOC; now 831 Python
files / ~156k LOC + 335 worker TS files / ~69.5k LOC).

## Drift (why this refresh exists)

| Metric | Arc start (2026-07-01) | Now (2026-08-23) |
|---|---|---|
| Python files in `boltrig/` | 110 | 831 |
| Python LOC | ~17,200 | ~156,000 |
| Files > 400 LOC (raw) | 8 | 28 (18,028 LOC) |
| Structural exemptions | 8 god files | 34 files (26 over file-floor + 8 fn-only) |
| Worker TS debt files | n/a (gate newer) | 61 |
| Tests | 195 passed | 4084 passed / 22 skipped (2026-08-16 check leg) |

God files GREW during the arc: `store/postgres.py` 1482→1895,
`kernel/app.py` 511→742, `kernel/channel_routes.py` 255→620,
`kernel/dispatch.py` (new to exemptions) 750, `api/auth_routes.py` 855
(`register_auth_routes` fn = 516 lines), `config/manifest.py` 888.
Exemptions carry owner + reason + ISO expiry 2026-12-31 and the ratchet gate
(`scripts/check_structure.py`) PASSES — debt is tracked, not lost, but the
arc's "every file under floor" goal is now ~9x the scoped work.

## Deterministic wave (all artefacts in this directory)

| Tool | Result |
|---|---|
| ruff check . | 0 violations |
| pip-audit (venv) | 0 known vulnerabilities |
| gitleaks (files-only) | 0 findings |
| bandit -r boltrig | 136: 81 LOW (B101/B105/B110 noise class) + 55 MEDIUM B608 |
| semgrep p/python | 5 findings |
| scripts/check_structure.py | PASS (all ratchets match source) |

## Triage (read-only verification of every non-LOW finding)

**Semgrep 5 = 0 real.** `cell_spawner.py:435` os-exec is the product's core
verb (privileged spawner exec'ing the PINNED codex binary; argv[0] pinned at
cell_spawner.py:151, policy from container env, sole route via serve_spawner;
BY-DESIGN — the invariant to protect is the argv[0] pin). The 4 warnings
(file-permissions ×3, logger-credential-leak) are false positives on `0o700`
constants and the literal word "credentials" in a log message that only ever
sees run_ids.

**Bandit B608 sample (8/55) = 0 real.** All use the two house idioms:
constant SQL-fragment interpolation + `$n` placeholders with bound args.
`store/postgres.py` itself has 0 B608s now; the hits live in
`fleet/infrastructure/postgres_*` (33) and other store modules (22). 47 sites
unread; same idiom class throughout. July's postgres.py:428 FP triage
generalises.

## Adversarial review (drift-scoped: 003886f7..35383663, the week since the 2026-08-16 hardening oneshot)

No CRITICAL/HIGH. Chokepoint held, kernel/fleet import boundary held (zero
kernel→fleet/sidecars imports at HEAD), no credential leaks, no SSE contract
violations, no error-path internals leaks, tenant fencing correct in the new
stores. Findings routed to `docs/refactoring/deferred.md` (F-01..F-08).

## Verdict

Security posture is clean at the deterministic layer; the two adversarial
MEDIUMs are durability bugs (fail-closed, silent) — NORMAL-mode followups,
not sweep blockers. The sweep's binding constraint is structural scale, not
security.
