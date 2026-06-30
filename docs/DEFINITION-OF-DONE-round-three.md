# Definition of Done - Round Three (authoring studios, admin, observability, eval, personal agents, memory)

Status against the Round Three DoD (S12). Markers: **done** (implemented + bound
to a test or a runnable check), **seam** (the code path is real; a live external
leg - a service, credentials, a model, or paid CI - is needed to exercise it end
to end).

The Round Three cross-cutting rules hold throughout: C1 the manifest stays the
source of truth (edits round-trip); C2 authoring writes versioned data, never
code; C3 every authoring/admin action is RBAC-gated and audited; C4 every action
still passes the single kernel chokepoint under the author's grants; C5 every
view is scope-filtered to the caller. The kernel dispatch sequence is unchanged -
Round Three adds routes, services, data, and UI only.

## Authoring writes versioned data, not code (C1, C2)

- [x] **done** Skills, nouns, verbs, bindings, adapters and workflows are authored
  through `/v1` routes that persist library/manifest data and record a
  `ConfigRevision`; nothing is code-generated into the running image.
  `boltrig/kernel/platform_routes.py`, `boltrig/config/admin.py`,
  `boltrig/models/platform.py`.
- [x] **done** Admin config edits round-trip: an org-setting change versions,
  rolls back, and re-exports to a loadable manifest (C1).
  `tests/integration/test_round_three_studios.py::test_admin_config_round_trips`
  (FR-ADM-02).
- [x] **done** A workflow authored live registers on the durable engine and a
  trigger reports `durable=true, engine=hatchet`; offline it falls back to the
  non-durable local executor (P9).
  `tests/integration/test_round_three_studios.py::test_workflow_live_durable_registration`
  (FR-WFS-04).
- [x] **done** An AI-generated adapter is inert until a named reviewer activates
  it: generate returns `activated=false` and the verbs are not discoverable;
  activation binds them and they appear in `/v1/capabilities` (SEC-22).
  `tests/integration/test_round_three_studios.py::test_adapter_studio_review_gate`
  (FR-ADS-02).

## Authoring is RBAC-gated and audited (C3)

- [x] **done** A non-author role is denied (403); an author role may write and the
  write is audited with the actor.
  `tests/security/test_round_three.py::test_authoring_requires_role_and_is_audited`
  (SEC-32). `boltrig/identity/rbac.py` (`AUTHOR_ROLES`, `can_author`).

## No authoring path escalates authority (C4)

- [x] **done** A skill test-spawn runs under the author's grants as a ceiling: a
  scoped author cannot grant the child a verb they lack; an org-admin can - the
  contrast proves the cap is real.
  `tests/security/test_round_three.py::test_test_spawn_cannot_escalate` (SEC-29).
  `boltrig/fleet/spawn.py` (`grant_ceiling`, `effective_grants`).
- [x] **done** The evaluation harness spawns through the chokepoint under the
  initiator's grants and never grants the target a forbidden verb.
  `tests/security/test_round_three.py::test_eval_runs_without_escalation`
  (FR-EVAL-02). `boltrig/fleet/eval.py`.
- [x] **done** A personal agent acts only with the owner's delegated authority,
  is capped to the owner's grants, and is audited on-behalf-of the owner.
  `tests/security/test_round_three.py::test_personal_agent_is_delegated_only`
  (SEC-30).

## Every view is scope-filtered (C5)

- [x] **done** Audit search and the runs list show only the caller's department
  scope; an org-admin sees the tenant.
  `tests/security/test_round_three.py::test_audit_and_runs_are_scope_filtered`
  (SEC-33, FR-OBS-02). Cost, audit-export and runs share the same scope filter.

## Memory is optional and scope-isolated

- [x] **done** Memory is off by default in the manifest and routes through the
  sensitive (on-box) embedding endpoint when enabled. A user's query returns
  their own and org-scoped items but never another user's.
  `tests/security/test_round_three.py::test_memory_scope_isolation` (SEC-31).
  `boltrig/identity/rbac.py` (`memory_owner_scopes`).

## Observability and cost

- [x] **done** Cost rollups, an audit search (filterable by actor/verb), an audit
  export, and a runs list are exposed behind the scope filter (FR-OBS-01/02).
  `boltrig/kernel/platform_routes.py`.

## Operational maturity

- [x] **done** An Alembic baseline (`0001_baseline`) replays `store/schema.sql`,
  so `alembic upgrade head` on a fresh database equals the bootstrap schema
  (FR-OPS-01). Verified offline: `alembic upgrade head --sql` emits 28 `CREATE
  TABLE` statements including all Round Three tables. `alembic.ini`,
  `migrations/env.py`, `migrations/versions/0001_baseline.py`.
- [x] **done** The manifest carries the Round Three sections
  (`evaluation`, `notifications`, `personal_agents`, `memory`) so the whole round
  is configured as data (C1). `manifest.example.yaml`.
- [ ] **seam** A required CI gate runs the suite + the invariant gate + lint on
  every push (FR-OPS-02). The workflow exists; GitHub Actions billing is disabled
  on the account, so the gate cannot run hosted. It runs clean locally (see
  below). Clearing billing is a Principal action.

## The UI surfaces (FR-*-UI)

- [x] **done** Authoring studios (Skill, Router, Adapter, Workflow), an Admin
  Console (config sections with history, rollback, manifest export, and
  credential-refs-only), Insight (cost, scope-filtered audit/runs, export), an
  Eval panel, and a per-user panel (personal agent, notifications, memory) are
  built over the new routes, with author/admin tabs shown only to author/admin
  identities and the server enforcing in all cases. `ui/src/panels/*`,
  `ui/src/api/client.ts`. Build green: `npm run build` (`tsc && vite build`).

## Governance ratchet

- [x] **done** Every new guarantee is bound to a test and declared in the
  catalogue; the binding gate passes at debt 0.
  `python scripts/check_invariants.py` -> `declared=52 marked=52 bound_tests=70
  binding_debt=0 RESULT: PASS`. New ids this round: SEC-29, SEC-30, SEC-31,
  SEC-32, SEC-33, FR-OBS-02, FR-EVAL-02, FR-ADM-02, FR-WFS-04, FR-ADS-02. No
  `K-*` ids were invented.
- [x] **done** Full offline suite green: `python -m pytest -q` -> 96 passed, 14
  skipped. Lint clean: `ruff check boltrig/ tests/ --select F,E9`.

## Summary

Round Three is complete offline and bound at binding-debt 0. The two open legs
are environmental, not code: a live Hatchet engine to exercise durable resume
end to end (the durability property itself is proven via the Postgres path), and
hosted CI (billing-blocked, a Principal action). Both are inherited seams, not
new gaps.
