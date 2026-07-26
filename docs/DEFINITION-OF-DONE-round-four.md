# Definition of Done - Round Four (settings, account & access management)

Status against the Round Four DoD (S R4 Ch.8). Markers: **done** (implemented +
bound to a test or a runnable check), **seam** (the code path is real; a live
external leg - an IdP, a model, a running client, or paid CI - is needed to
exercise it end to end).

The Round-Three cross-cutting rules still hold: C1 the manifest stays the source
of truth, C2 authoring writes versioned data, C3 every action is RBAC-gated and
audited, C4 actions pass the chokepoint, C5 views are scope-filtered. The kernel
dispatch sequence is unchanged (NFR-MNT-01): `dispatch.py`, `grants.py` and
`registry.py` are untouched this round - Round Four adds routes, data, identity,
and one MCP entry path only.

## 1. Provisioning

- [x] **done** An unmapped, un-invited identity is denied; an invited identity is
  provisioned with its intended role/scope (the invitation is consumed); a mapped
  identity is provisioned from its group with the source group recorded.
  `boltrig/identity/provisioning.py`,
  `tests/security/test_round_four.py::test_invitations_do_not_bypass_idp`
  (SEC-35, US-USR-01/02/04).
- [x] **done** An admin can view the directory, adjust a user's role/scope, and
  deactivate a user - which revokes access at once (a deactivated user's grants
  become empty and their tokens stop working).
  `boltrig/kernel/access_routes.py` (`/v1/admin/users`),
  `tests/security/test_round_four.py::test_pat_never_escalates_and_dies_with_user`
  (US-USR-03).
- [ ] **seam** Just-in-time provisioning on a real SSO login. The OIDC resolver
  provisions when given a store (`build_principal_resolver(..., store=...)`), proven
  with a stub verifier; a live IdP issuing tokens is the external leg.

## 2. Authoring (committed RTR)

- [x] **done** Nouns, verbs and bindings are authored through `/v1/nouns`,
  `/v1/verbs`, `/v1/verbs/{id}/binding` (Round Three), versioned and round-tripping;
  a newly authored verb is discoverable caller-scoped and invocable only under
  grants (the discovery + grant guarantees are bound by SEC-07 and the Round Three
  studio tests).
- [x] **done** A verb authored with a destructive / outbound name defaults to
  high-consequence, so the HITL gate engages by default; an explicit choice is
  honoured. `boltrig/kernel/platform_routes/` (`safe_consequence`),
  `tests/security/test_round_four.py::test_authored_verbs_safe_by_default`
  (SEC-39, US-RTR-02/04).

## 3. Headless

- [x] **done** A personal access token scoped to a subset of the user's grants
  drives `/v1/invoke` and the user-authenticated `/v1/mcp` face, cannot exceed the
  user, and revokes immediately; the secret is shown once and stored only as a
  hash. `boltrig/identity/tokens.py`, the PAT-aware principal dependency and the
  user-MCP path in `boltrig/kernel/app.py` + `boltrig/kernel/mcp.py`,
  `tests/security/test_round_four.py::test_pat_never_escalates_and_dies_with_user`,
  `::test_headless_parity_no_weak_path` (SEC-34, SEC-37, US-HEAD-01/02/04).
- [x] **done** Connection details and copy-paste client snippets are available in
  Settings. `/v1/me/connections`, the Developer & Connections section of
  the settings surface (SET-41/HEAD-03; the single `SettingsPanel.tsx` has since been split up).

## 4. Mobile

- [x] **done** The site is responsive across phone/tablet/desktop breakpoints:
  panels and two-column layouts reflow to a single column, the tab nav wraps, no
  horizontal scroll of primary content, touch targets are sized; the Chat surface
  (which had no CSS) gained a full responsive stylesheet; the UI carries WCAG 2.1
  AA touches (focus-visible outlines, contrast, reduced-motion). `ui/src/styles.css`,
  `ui/src/appearance.ts` (US-MOB-01..04, NFR-A11Y-01, NFR-MOB-01).
- [ ] **seam** A formal WCAG 2.1 AA audit and on-device testing across real phones
  are an external verification leg; the code targets the standard.

## 5. Settings

- [x] **done** All sections are RBAC-gated (per-user for the account sections,
  org-admin for the organisation section), persisted, validated and audited; every
  UI setting has an API equivalent with identical authorization (SET-03); org
  config edits version, roll back and export to a manifest (the Round Three Admin
  Console, hosted here). `boltrig/kernel/access_routes.py`,
  the settings surface (since split out of a single `SettingsPanel.tsx`),
  `tests/security/test_round_four.py::test_settings_changes_are_authz_checked_and_audited`
  (SEC-36, SET-00..03).
- [x] **done** No unauthenticated path exposes tokens or connection details; mobile
  and web follow the same auth rules.
  `tests/security/test_round_four.py::test_no_unauthenticated_access_to_tokens`
  (SEC-38).

## 6. Security & governance

- [x] **done** SEC-34..39 are bound to tests with catalogue entries;
  `python scripts/check_invariants.py` passes at binding-debt 0
  (`declared=58 bound_tests=76 binding_debt=0 PASS`). A diff confirms the kernel
  dispatch sequence is unchanged (NFR-MNT-01).
- [x] **done** Full offline suite green: `python -m pytest -q` -> 102 passed, 14
  skipped. Lint clean: `ruff check boltrig/ tests/ --select F,E9`.

## Operational

- [x] **done** Ordered Alembic migration `0002_round_four` chains from the baseline
  (single head) and brings an existing database to the Round Four schema; a fresh
  database gets the tables from the baseline replay of `schema.sql`. Offline
  `alembic upgrade head --sql` emits the new tables.

## Summary

Round Four is complete offline and bound at binding-debt 0. The open legs are
environmental, not code: a live IdP to exercise SSO provisioning end to end, a
formal accessibility audit / on-device pass, and hosted CI (billing-blocked, a
Principal action). This closes the functional requirement rounds (One to Four);
the next phase is the security-refinement consolidation driven by the two security
specs (tasks R4-Security Batch 1 + Batch 2) and Round Five (memory).
