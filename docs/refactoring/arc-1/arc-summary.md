# Arc-1 summary

**Status:** round-1 resumed and closed 2026-08-24 (store pair + 4 god files
under floor; 6 exemptions deleted). Route cluster ruled (request-state
singletons) and queued for round 2. Worker TS deferred to its own round.

## Baseline (arc start, 2026-07-01)

| Metric | Value |
|---|---|
| In-scope files | 110 |
| Functions | 1040 |
| Package LOC | ~17,200 |
| Files over floor (>400) | 8 |
| Tests passing | 195 (22 skipped) |
| Invariant gate | 96/96, debt 0 |
| API routes (baseline) | 72 |

## 2026-08-23 refresh (7 weeks of drift)

831 Python files / ~156k LOC; 34 exempted files; god files GREW during the arc
(postgres 1482→1895, app.py 511→742, channel_routes 255→620). Worker TS gate
now exists with 61 debt files. Security re-baselined: deterministic wave clean
(0 real findings after triage — semgrep 5 = FPs/by-design, bandit 55×B608 =
bound-placeholder idiom), adversarial drift review found 0 CRITICAL/HIGH and
8 findings routed to `docs/refactoring/deferred.md` (F-01..F-08). Full detail:
`round-1-refresh/findings.md`.

## Floor-passing progress

| Round | Files passing floor | % | Notes |
|---|---|---|---|
| 0 (baseline) | 102/110 | 92.7% | 8 god files + scattered over-floor fns |
| 1 (Jul) | 102/110 | 92.7% | channel store domain extracted (template proven) |
| 1-resume (2026-08-24) | 823/831 | 99.0% | store pair + spawn + generator + http_base + manifest under floor; exemptions 34→28; API surface 236/236 unchanged; offline pytest 4195+ green; PG leg 364 green; invariant gate green every commit |

Largest remaining exempted files (round 2 candidates): store/base.py 681
(Protocol), api/auth_routes.py 855 (register fn 516 — route cluster),
kernel/dispatch.py 750, kernel/app.py 742 (create_app 514 — route cluster),
fleet/pump.py 699, cell_spawner 676, codex_trusted_proxy_provider 675,
access_routes 671.

## What "done" means for this arc

Unchanged: every in-scope file under the 400-LOC floor and every function
under the function floor (or exempted with reason), API surface diff clean,
invariant gate green, no behaviour change bundled with structural commits.

## Round 2 (queued)

1. Route-cluster hoist under the RULED pattern (request-state singletons set
   at create_app; module-level handlers): channel_routes (620) →
   platform_routes → access_routes → memory_routes → app.py create_app (514).
   auth_routes.py 855 (register_auth_routes fn 516) rides the same pattern.
2. Worker TS debt round (61 files, own gate).
3. Remaining Tier-2: dispatch.py invoke fns (129/126), interpreter.py
   run_workflow_definition (275), identity/sessions.py build_session_resolver
   (124), pgvector recall (83), desktop _verb_specs (119).
