---
tags:
  - claude
  - skills
  - local
  - refactoring
  - overrides
  - boltrig
created: "2026-07-01"
updated: "2026-07-10"
parent: refactoring
---
# Boltrig refactoring overrides

Per-project values for the agents-final refactoring + security suites. Boltrig is a
Python agent-orchestration kernel (FastAPI + asyncpg + Cognee), NOT the Opbox
Next.js/Prisma/Vitest default the templates assume. Every TS/npm/prisma default is
overridden here.

## Project identity

- **Name:** Boltrig
- **Repo root:** `/path/to/boltrig`
- **Stack:** Python 3.12 production/CI target (3.14 early-warning) / FastAPI /
  asyncpg (Postgres) / in-memory store / pluggable memory projections
- **Refactor docs root:** `docs/refactoring/`
- **Architecture specs glob:** `docs/ARCHITECTURE*.md`, `docs/SYSTEM-OVERVIEW.md`, `docs/invariants.md`
- **Engine doctrine (authoritative):** `AGENTS.md` (one chokepoint, policy-is-data, kernel imports nothing from fleet/sidecars, invariant gate)

## Commands

- **Test (full):** `.venv/bin/python -m pytest -q`
- **Test (per-module fast loop):** `.venv/bin/python -m pytest <path> -q`
- **Invariant gate:** `.venv/bin/python scripts/check_invariants.py`
- **Lint:** `.venv/bin/python -m ruff check .`
- **Structural gate:** `.venv/bin/python scripts/check_structure.py` (also
  `make structure`, and part of `make python-quality` / `make quality`)
- **Type check:** `.venv/bin/python -m mypy` (strict, currently 49 source files;
  widen module-by-module under the 10/10 plan)
- **Schema validate:** `psql` apply against `boltrig/store/schema.sql` + `rls.sql` (service-gated; offline suite uses the in-memory store)
- **Build/release gate:** `make quality`; release images are built from the five
  Dockerfiles and published only by `.github/workflows/release.yml`
- **Install:** `.venv/bin/python -m pip install --require-hashes -r requirements-dev-lock.txt`

## Schema migration

- **Local migration:** `make migrate` (Alembic); `schema.sql` is fresh-bootstrap
  convenience only and `make migration-parity` checks catalogue parity
- **Prod migration:** the ordered Alembic chain is authoritative and runtime boot
  never replays the mutable bootstrap
- **Rollback path:** revision `0022_schema_parity` is irreversible; restore the
  verified pre-migration database snapshot and prior images together

## Preflight tools

- **vibescan:** enabled (CVE/secret/SAST aggregation: bandit, pip-audit, semgrep, trivy)
- **vibeaudit:** enabled, `--provider claude-code`, scoped to `boltrig/` (skip the `command_injection` runner - Python FP-prone)
- **vibeclean:** enabled (atomization/complexity/duplication/slop; the deterministic structural source)
- **Security-Suite methodology:** enabled (dispatch the 13-section reasoning; Boltrig is multi-tenant + agents + SSO + secret-management - high-surface)
- **Project-specific SOC 2 audit:** none (no `scripts/audit-soc2-compliance.sh`); SOC 2 obligations are real but the ripgrep script is not yet authored. Treat as a gap, not proof of absence.
- **Additional project-specific scanners:** `bandit -r boltrig`, `pip-audit`, `semgrep --config p/python`

## Structural floor (STRUCTURAL_SWEEP)

Defaults apply. ~~`store/postgres.py` and `store/memory.py` remain Tier-3
debt~~ **RESOLVED 2026-08-24 (round-1-resume): both stores under floor**
(postgres 209, memory 263) via 15 symmetric domain partials; exemptions
deleted. Remaining Tier-3 debt heads to round 2: the route cluster
(channel/platform/access/memory_routes + app.py create_app + auth_routes
register fn) under the RULED request-state-singleton pattern, then
dispatch/pump/cell_spawner. Any temporary over-floor exception must
be explicit in `docs/refactoring/structural-exemptions.json` with its current
file-line, largest-function, and individual over-limit-function baselines plus a
reason, owner, and ISO expiry. The stdlib-only gate scans `boltrig/**/*.py`,
rejects files over 400 physical lines or decorator-inclusive functions/methods
over an 80-line source span, and fails on new, grown, stale, malformed,
missing-file, or expired exemptions. Every recorded metric must exactly match
the current source, so an improvement lowers its ratchet in the same change;
raising one requires an explicit governance review.

The Worker has the same enforceable floor through `make worker-structure`, a
required prerequisite of `worker-quality` and therefore of CI. The gate uses the
already pinned TypeScript compiler to scan every `.ts`/`.tsx` file under
`apps/worker/src`: 400 physical file lines, 80 function lines, five parameters,
cyclomatic complexity 15, and nesting depth four. Existing debt lives in
`docs/refactoring/worker-structural-debt.json` with exact per-file and
per-function metrics, owner, reason and ISO expiry. New, grown, stale-high,
missing, malformed, duplicate-key or expired debt fails the build; an empty or
truncated scan fails rather than reporting green.

## Drift detection

- **Module index source:** `AGENTS.md` (the doctrine) + `docs/ARCHITECTURE.md`
- **Architecture specs:** `docs/ARCHITECTURE*.md`, `docs/SYSTEM-OVERVIEW.md`, `docs/invariants.md`
- **Additional drift paths:** `tests/invariants.yaml` (the binding contract - a marker/declarable change is a structural event), `boltrig/store/schema.sql` + `rls.sql`
- **Snapshot location:** `docs/refactoring/arc-1/api-surface-snapshots/`

## Deploy

- **Deploy command:** `make secure-up` (or the equivalent externally terminated
  TLS deployment) after production doctor, migration, and backup gates
- **Smoke check:** `make quality`; opt-in credentials/services add `make live-check`

## Learnings

### 2026-07-01: invariant gate is load-bearing, not a lint

`tests/invariants.yaml` binds every security/correctness claim to a pytest marker +
declares every marker. Binding debt must stay 0. Any structural change that moves or
renames a test MUST re-bind it in the yaml or the gate (`scripts/check_invariants.py`)
fails. Encoded in: S3 per-file inner loop + S4 round close-checklist.

### 2026-07-01: the store pair is symmetric by design

`store/base.py` (Protocol) + `store/memory.py` + `store/postgres.py` are a
symmetric trio. A method added to one MUST land on all three or the Protocol is
violated. Encoded in: Tier-3 god-file decomposition plan for the store package.
