# Arc-1 plan: structural sweep over `boltrig/`

Generated 2026-07-01 from `inventory.tsv` + `pre-arc/atomize.json` +
`pre-arc/findings.md`. This is the S1 arc plan; per the suite it is **reviewed
before round-1 dispatch** (the most expensive call in the suite, gated on sign-off).

## Scope + baseline

- 110 in-scope Python files (`boltrig/`), 1040 functions, ~17.2k LOC.
- Structural floor (defaults, see overrides): file ≤400, fn ≤80, cc ≤15, nest ≤4, params ≤5.
- Baseline: **8 files over the file floor, 55 functions over the function floor.**
- API surface baseline: 72 routes (`api-surface-snapshots/round-1-routes.txt`). The
  S4 acceptance gate diffs against this every round — **no route may appear/disappear/change signature** without an explicit intent flag.
- Test baseline: 195 passed, 22 skipped, invariant gate 96/96 (debt 0). The gate
  (`tests/invariants.yaml` + `scripts/check_invariants.py`) is load-bearing: any
  moved/renamed test MUST be re-bound or the build fails.

## Doctrine constraints (from AGENTS.md — non-negotiable)

1. ONE chokepoint, policy-is-data, kernel imports nothing from `fleet/` or sidecars.
2. The store trio (`base` Protocol + `memory` + `postgres`) is symmetric: a method
   added/changed on one MUST land on all three.
3. Behaviour-preserving only. Real bugs found while atomizing → `deferred.md`, not
   inline fixes. Structural commits must not bundle behaviour changes.
4. Public API surface (route signatures, exported types/fns) is frozen for the arc.
5. One commit per file (Tier 1/2) or per extracted unit (Tier 3). Offline pytest +
   invariant gate green at every commit.

## Tier dispatch

### Tier 3 (god files, 1 agent:1 file, multi-commit) — Round 1 priority

The two `store/*` files are split **in lockstep by domain section** (channels,
memory, identity, hitl, budgets, eval, ...): each domain becomes a partial in a new
`store/pg/` + `store/memory/` package, re-exported from the original module so the
Protocol + callers are untouched. The route-registration god-functions become
module-level handlers (STR-002). Order (god files that block downstream first):

1. `kernel/platform_routes.py` (576, cc69) + `kernel/app.py` create_app (511) —
   the route-hoist pattern. **Defines the round-1 template; do this first.**
2. `store/postgres.py` (1482) + `store/memory.py` (579) — domain partials, lockstep.
3. `fleet/spawn.py` (565), `adapters/generator.py` (535), `config/manifest.py` (580),
   `adapters/http_base.py` (444).

### Tier 2 (medium 200–400 LOC single-concern, batch 5–10:1) — Round 2

The remaining ~moderate files already under the file floor but with over-floor
functions: `workflows/interpreter.py`, `memory/pgvector.py`, `kernel/dispatch.py`,
`kernel/access_routes.py`, `memory/adapter.py`, `skills/schema.py`, etc. Pure
function-extraction shrinks.

### Tier 1 (small files, batch 20+:1) — Round 2/3

The 102 files under the floor with isolated over-floor fns or slop. Sweep last.

## Phasing (projected 3 rounds)

| Round | Phase | Files | Wall-clock est. | Token est. |
|---|---|---|---|---|
| 1 | Tier-3 god files (route hoist + store domain partials) | 8 | ~1 session each, serial (one-writer) | moderate |
| 2 | Tier-2 function extraction | ~15 | batched | low |
| 3 | Tier-1 sweep + close | rest | batched | low |

Round 1 is serial by the one-writer rule (apply + compile + test + commit per file).
Independent Tier-2/3 files can be authored by read-only agent seats and integrated
serially.

## Pre-arc gate (characterization)

The package is already well-tested (195 tests, invariant-gate-bound). Coverage gaps:
the deterministic wave did not produce a coverage map (no `--coverage` JSON wired
for the Python suite). **Decision:** the invariant-gate binding + the existing
security tests cover the load-bearing behaviour of every god file targeted in
round 1 (chokepoint, routes, stores, spawn). Proceed without a separate
characterization pass; flag any split that touches an untested code path as
`split-without-test` in its result.md for manual review before commit. (Override
`ARC.SKIP_CHARACTERIZATION_GATE` effectively true, with the manual-review carve-out.)

## Round-1 acceptance (S4 close-checklist, specialised)

- [ ] Offline pytest green (195+, never shrinking) at every per-file commit.
- [ ] Invariant gate 96/96, binding debt 0, after every commit.
- [ ] API surface diff vs `round-1-routes.txt`: 72 in, 72 out, signatures unchanged.
- [ ] The store trio stays symmetric (every domain partial lands on base+memory+postgres).
- [ ] No behaviour change bundled with a structural commit (deferred.md holds the rest).
- [ ] `ruff check .` clean.
- [ ] arc-summary.md updated with floor-passing %.

## Risk callouts

- **Store split is the highest-risk move.** Both stores are wide and load-bearing.
  Mitigation: domain-by-domain, re-export from the original module so import paths
  don't change, full test run after each domain.
- **Route hoist changes call sites only inside the register fn** — low blast radius,
  but the dev-principal dependency wiring must be preserved exactly.
- **`create_app` decomposition** touches the app factory every route registers
  through; do it after the route files are hoisted, not before.

## First beat (unblocks the round)

Hoist `kernel/channel_routes.py` (the smallest route file, just written, 255/cc57)
to module-level handlers as the round-1 TEMPLATE, prove the pattern green, then
apply it to `platform_routes` + `access_routes`. Channels is the safest first
because its tests are fresh and comprehensive (14 channel tests).
