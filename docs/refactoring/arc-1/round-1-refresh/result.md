# Round-1 resume — batch result (2026-08-24)

Worktree `boltrig-sweep`, branch `structural/arc-1-r1-resume`, base origin/main @ 35383663.
Scope per sign-off: store domain partials + 4 non-route god files (route cluster
awaiting the request-state-singleton ruling — applies next round).

## Per-file outcomes

| File | Before | After | Approach | Status |
|---|---|---|---|---|
| store/postgres.py | 1895 | 209 | 9 symmetric domain partials (hitl, audit_stream, run_records, conversations, memory_planes, tenancy, ai_configs, user_accounts, user_auth + 6 small domains folded into tenant_permissions/libraries/config_revisions/notifications/credential_references) | passing, exemption DELETED |
| store/memory.py | 1248 | 263 | same 9+6 lockstep partials | passing, exemption DELETED |
| fleet/spawn.py | 556 / spawn() 84 | 327 / 64 | SpawnLifecycleMixin (telemetry/terminal cluster) + _plan_and_reserve helper | passing, exemption DELETED |
| adapters/generator.py | 592 | 394 | runtime classes → generated_adapter.py; durable module-ref marker accepts both paths | passing, exemption DELETED |
| adapters/http_base.py | 441 | 367 | HttpErrorMappingMixin (status/transport mapping, backoff, parse) | passing, exemption DELETED |
| config/manifest.py | 888 | 124 | types → manifest_types.py; parsers → manifest_parse.py; chat cluster → manifest_chat.py; manifest.py = public surface | passing, exemption DELETED |

New files, all ≤400: hitl 190, audit_stream 302, run_records 400, conversations 391,
memory_planes 398, tenancy 347, ai_configs 105, user_accounts 287, user_auth 319,
tenant_permissions 38, libraries 102, config_revisions 51, notifications 137,
spawn_lifecycle 244, generated_adapter 218, http_errors 108, manifest_types 320,
manifest_parse 340, manifest_chat 185.

## Verification (all measured)

- Offline pytest: 4195+ passed, 47 skipped (final tree; grew across the round — no test removed).
- Postgres leg (`with_test_postgres.sh tests/store`): 364 passed, 1 skipped, run after every store unit.
- Invariant gate: PASS every commit (96+ declared, binding debt 0).
- Structural ratchet: PASS every commit; 6 exemptions deleted (34→28), ratchets lowered in the same changes.
- ruff: clean. mypy strict: 158 files, no issues.
- Claim inventory + RLS-exemption allowlist regenerated (moves re-bound).
- API surface diff vs origin/main: 236 routes in / 236 out, **zero added or removed**; the July round-1 baseline (72 routes) is feature-drift stale, superseded by `round-1b-routes.txt`.

## Incidental repairs (behaviour-preserving only)

- `record_inert_adapter` durable module-ref marker now accepts the historical AND new path (`GENERATED_ADAPTER_MODULES`) so pre-move rows still reconstruct.
- `list_orgs` mem twin moved with tenancy partial; RLS-exemption allowlist entry added with reason.
- Reachability call edge preserved via the original lazy import in `resolved_named_agents` (an aliased module-level import breaks the checker's call-edge resolution).

## Not done (explicit)

- Route-file hoist (channel/platform/access/memory_routes, app.py create_app 514) — blocked on the request-state-singleton pattern decision (user ruling recorded 2026-08-24: request-state singletons; execute next round).
- Worker TS debt (61 files) — deferred by ruling to its own round.
- The 28 remaining exemptions (identity, dispatch, access_routes, pump, codex infrastructure family, etc.).
- Deferred bug findings F-01..F-08 (docs/refactoring/deferred.md) — NORMAL-mode followups, deliberately not bundled.
