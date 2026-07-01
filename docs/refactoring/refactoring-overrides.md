---
tags:
  - claude
  - skills
  - local
  - refactoring
  - overrides
  - boltrig
created: "2026-07-01"
updated: "2026-07-01"
parent: refactoring
---
# Boltrig refactoring overrides

Per-project values for the agents-final refactoring + security suites. Boltrig is a
Python agent-orchestration kernel (FastAPI + asyncpg + Cognee), NOT the Opbox
Next.js/Prisma/Vitest default the templates assume. Every TS/npm/prisma default is
overridden here.

## Project identity

- **Name:** Boltrig
- **Repo root:** `/home/jellytot/Projects/boltrig`
- **Stack:** Python 3.14 / FastAPI / asyncpg (Postgres) / in-memory store / Cognee
- **Refactor docs root:** `docs/refactoring/`
- **Architecture specs glob:** `docs/ARCHITECTURE*.md`, `docs/SYSTEM-OVERVIEW.md`, `docs/invariants.md`
- **Engine doctrine (authoritative):** `AGENTS.md` (one chokepoint, policy-is-data, kernel imports nothing from fleet/sidecars, invariant gate)

## Commands

- **Test (full):** `.venv/bin/python -m pytest -q`
- **Test (per-module fast loop):** `.venv/bin/python -m pytest <path> -q`
- **Invariant gate:** `.venv/bin/python scripts/check_invariants.py`
- **Lint:** `.venv/bin/python -m ruff check .`
- **Type check:** none (no mypy configured; ruff is the static check)
- **Schema validate:** `psql` apply against `boltrig/store/schema.sql` + `rls.sql` (service-gated; offline suite uses the in-memory store)
- **Build:** no build step (interpreted); `pip install -e .` for the package
- **Install:** `.venv/bin/pip install -e ".[dev]"`

## Schema migration

- **Local migration:** apply `boltrig/store/schema.sql` + `rls.sql` to a Postgres (service-gated)
- **Prod migration:** out of scope for the arc (seam: ordered alembic set is scaffolded)
- **Rollback path:** schema is additive (`CREATE TABLE IF NOT EXISTS`); rollback = revert + re-apply

## Preflight tools

- **vibescan:** enabled (CVE/secret/SAST aggregation: bandit, pip-audit, semgrep, trivy)
- **vibeaudit:** enabled, `--provider claude-code`, scoped to `boltrig/` (skip the `command_injection` runner - Python FP-prone)
- **vibeclean:** enabled (atomization/complexity/duplication/slop; the deterministic structural source)
- **Security-Suite methodology:** enabled (dispatch the 13-section reasoning; Boltrig is multi-tenant + agents + SSO + secret-management - high-surface)
- **Project-specific SOC 2 audit:** none (no `scripts/audit-soc2-compliance.sh`); SOC 2 obligations are real but the ripgrep script is not yet authored. Treat as a gap, not proof of absence.
- **Additional project-specific scanners:** `bandit -r boltrig`, `pip-audit`, `semgrep --config p/python`

## Structural floor (STRUCTURAL_SWEEP)

Defaults apply except: Boltrig's `store/postgres.py` and `store/memory.py` are
deliberately wide (one method per SQL row-op / in-memory op, grouped by domain).
Splitting them across N tiny files trades readability for line-count and breaks the
"one store Protocol, two co-located impls" symmetry. They are the arc's Tier-3 god
files: decompose by DOMAIN SECTION (channels, memory, identity...) into a package
of partials, NOT by chopping at 400 lines.

## Drift detection

- **Module index source:** `AGENTS.md` (the doctrine) + `docs/ARCHITECTURE.md`
- **Architecture specs:** `docs/ARCHITECTURE*.md`, `docs/SYSTEM-OVERVIEW.md`, `docs/invariants.md`
- **Additional drift paths:** `tests/invariants.yaml` (the binding contract - a marker/declarable change is a structural event), `boltrig/store/schema.sql` + `rls.sql`
- **Snapshot location:** `docs/refactoring/arc-1/api-surface-snapshots/`

## Deploy

- **Deploy command:** out of scope (seam: Caddy + compose on the host)
- **Smoke check:** `.venv/bin/python -m pytest -q` green + invariant gate PASS = the offline done-bar

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
