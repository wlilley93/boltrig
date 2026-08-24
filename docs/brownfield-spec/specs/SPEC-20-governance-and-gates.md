---
area: 20 Governance: invariants, gates, decisions and the court
id-block: BT-REQ-2000 to BT-REQ-2099
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: spec-area-20
date: 2026-08-24
---

# SPEC-20 Governance: invariants, gates, decisions and the court

## Search bound declared up front

**Read end to end**: `.githooks/pre-push`, `.github/workflows/ci.yml`,
`.github/workflows/security.yml`, `scripts/gate-status.sh`,
`scripts/quality-gate.sh`, `scripts/govern.py`, `scripts/scan_guard.py`,
`scripts/check_no_vacuous_greens.py`, `scripts/check_invariants.py`,
`scripts/check_gate_coverage.py`, `scripts/check_order_directives.py`,
`scripts/check_override_locks.py`, `scripts/check_familiar_shader.sh`,
`scripts/check_brand_core.sh`, `docs/GOAL-trustworthy-gate.md`,
`docs/GOAL-claims-must-be-load-bearing.md`, `docs/security-gates.md`,
`docs/security-conformance.md`, `.vds/config.toml`,
`docs/refactoring/order-binding-exemptions.json`, `tests/conftest.py`, and the
Makefile's whole gate region (lines 1 to 240 and 355 to 494).

**Read by systematic sample**: `tests/invariants.yaml` (2838 lines) was not read
line by line. It was parsed twice mechanically, once with the gate's own reader
re-implemented read-only and once with an independent scan, and every count in
this document is a measurement from that parse, not a reading. Individual
descriptions are quoted only where cited. The remaining `scripts/check_*.py`
family (`architecture`, `structure`, `reachability`, `unwired_claims`,
`claim_inventory`, `prose_references`, `health_claims`, `commit_trailers`,
`continuity_projection`, `codex_pin_health`, `codex_protocol`,
`tracked_symlinks`, `secret_scan_history`, `user_authority`, `fleet_drift`,
`vds_ledgers`) was read as: full module docstring, every constant, and the exit
branches of `main()`. Bodies of pure-parsing helpers were skimmed.
`.github/workflows/release.yml` (63434 bytes) was read only in its `preflight`
job and its two workflow-success assertions; the rest belongs to the release
area. `.vds/proofs/` (794 files) was measured by aggregate, with two files read
in full. `docs/decisions/` (42 files) had every file's title and status line
read; four were read in depth.

**Read only far enough to settle a boundary question**, and nothing is claimed
about them beyond the lines cited: `README.md`, `AGENTS.md`, `pyproject.toml`,
`docs/invariants.md`, `docs/claim-inventory.tsv`, `.trivyignore.yaml`,
`docs/security/accepted-advisories.json`, `docs/CI-RED-2026-08-14.md`,
`docs/PROGRAM-2026-08-18-phased-plan.md`, `apps/worker/package.json`,
`apps/worker/tests/visual/manifest.test.ts`,
`apps/worker/tests/visual/sourceDigest.mjs`, `.vjs/bin/heavy-job.sh`.

Every absence claim below carries its own bound inline.

## 2. Purpose

This area is the machinery Boltrig uses to stop itself lying about itself. It has
three layers that are deliberately independent: a **binding-invariant catalogue**
that refuses a security claim no test pins, a **gate family** of roughly two dozen
scripts that refuse a record whose subject does not exist, and a **court** whose
orders are filed as data and whose directives must each be named by a test or
waived with an owner, a reason and an expiry. The layer above all three is a
posture, stated in two goal documents: a check that cannot fail, or that passes
because it could not look, is worse than no check, because it converts "nobody
verified this" into "somebody verified this".

## 3. Boundaries

**What this area owns.**

- The invariant catalogue `tests/invariants.yaml` and its gate
  `scripts/check_invariants.py`, plus the human map `docs/invariants.md`.
- Every `scripts/check_*.py` and `scripts/check_*.sh`, the shared refusal helper
  `scripts/scan_guard.py`, and the meta-sweep `scripts/check_no_vacuous_greens.py`.
- The Makefile's gate aggregates (`check`, `python-quality`, `quality`,
  `security-source`) and the two dispatch shims `scripts/quality-gate.sh` and
  `scripts/gate-status.sh`.
- `.githooks/pre-push` and the three workflow files under `.github/workflows/`,
  read as gate wiring rather than as release mechanics.
- The court record `.vjs/` (orders, permits, proofs, submissions, decision logs,
  convenings, the vendored canon citator) and the design-governance record
  `.vds/` (config, register, screens, ledgers, proofs, directions, reviews).
- The exemption ledgers under `docs/refactoring/` and the two goal documents.
- `docs/decisions/`, `docs/claim-inventory.tsv`, `docs/security-gates.md`,
  `docs/security-conformance.md`.

**What it must not touch.** No gate in this family imports from `boltrig/`
except `check_user_authority.py`, which imports `boltrig.identity.rbac`
([`scripts/check_user_authority.py:60`](../../../scripts/check_user_authority.py) `"from boltrig.identity.rbac import grants_for_scope"`) and is deliberately not a
CI gate. `scripts/validate_release_compose.py` imports `boltrig.release_mode` so
the admitted release modes have one definition, and the CI comment that used to
call the validators stdlib-only is corrected in place
([`.github/workflows/ci.yml:208`](../../../.github/workflows/ci.yml) `"not because the validators are stdlib-only"` is the
claim being retracted at lines 203 to 215).

**The forbidden import, and by what rule.** `scripts/check_architecture.py`
enforces inward-only layering for `boltrig.fleet.domain`,
`boltrig.fleet.ports`, `boltrig.fleet.application` and `boltrig.models`
([`scripts/check_architecture.py:30`](../../../scripts/check_architecture.py) `"_LAYER_IMPORTS = {"`), bound by `FR-ARC-01`. `boltrig.models` may import only
`boltrig.models` and the standard library
([`scripts/check_architecture.py:42`](../../../scripts/check_architecture.py) `"models": ("boltrig.models",),`). The kernel is gated by a deny-list
instead, because it composes every sibling package.

**The one authority this area does not hold.** The `K-*` invariant ids are
declared canonical to an external repository, and that repository is not here.
`tests/invariants.yaml:18-20` records the rule
(`"every K-* id below is the canonical invariant id from"`), and no submodule,
vendored copy or Appendix A file exists in the tree (bounded:
`cat .gitmodules` returns no such file; `find . -iname "*appendix-A*"` outside
`.git` returns nothing; `grep -rl agent-kernel-doctrine` outside `.git` matches
six prose files and no data file, 2026-08-24, pinned tree). SEAM, external
repository `agent-kernel-doctrine`.

## 4. Objects and contracts

### 4.1 The gate

A gate is a script with one job, an exit code, and a docstring that states what it
does NOT check. There are 26 files matching `scripts/check_*`:

| kind | count | names |
| --- | --- | --- |
| Python gate | 21 | architecture, claim_inventory, codex_pin_health, codex_protocol, commit_trailers, continuity_projection, fleet_drift, gate_coverage, health_claims, invariants, no_vacuous_greens, order_directives, override_locks, prose_references, reachability, secret_scan_history, structure, tracked_symlinks, unwired_claims, user_authority, vds_ledgers |
| Python selftest | 2 | commit_trailers_selftest, tracked_symlinks_selftest |
| Python, hyphenated name | 1 | check-release-age-exclusions.py |
| Shell gate | 2 | check_brand_core.sh, check_familiar_shader.sh |

Every gate returns 0 for pass and 1 for fail. Three return 2 for "could not ask":
`check_no_vacuous_greens.py` when it swept zero gates
([`scripts/check_no_vacuous_greens.py:140`](../../../scripts/check_no_vacuous_greens.py) `"ERROR: swept ZERO gates - the list is wrong"`), `check_user_authority.py` when
DSN or MANIFEST is unset, `gate-status.sh` when `gh` is absent or the ref does not
resolve, and both shell gates when the upstream tree they compare against is not
on the box
([`scripts/check_familiar_shader.sh:37`](../../../scripts/check_familiar_shader.sh) `"NOT CHECKED: no upstream $f at $upstream"`).

### 4.2 The invariant

A binding invariant is an id, a one-line description, and a list of pytest node
ids. Ground truth is the `@pytest.mark.invariant("X")` marker in `tests/`; the
catalogue is the declaration checked against it. The marker is registered in
[`pyproject.toml:143`](../../../pyproject.toml) `"invariant(id): a binding invariant (P-/SEC-/K-)"`.

Measured on the pinned tree by re-implementing the gate's reader read-only:

| quantity | value |
| --- | --- |
| declared invariant ids | 421 |
| duplicate declared ids | 0 |
| distinct marker ids found in `tests/` | 421 |
| unbound (declared, no marker) | 0 |
| undeclared (marker, no declaration) | 0 |
| catalogue drift (declared node id with no marker) | 0 |
| **binding debt** | **0** |
| declared test node ids | 1475 |
| real (id, node) marker pairs | 1836 |
| marker-backed node ids NOT written into the catalogue | 361 |
| `service_gated` node ids | 6, across 3 invariants |
| test modules scanned | 510 |

The `K-*` / Boltrig-local split, by id prefix:

| family | count | ids or note |
| --- | --- | --- |
| `K-*` (doctrine, canonical elsewhere) | 6 | K-2, K-5, K-9, K-13, K-19, K-20 |
| `P*` (SRS principle) | 1 | P9 |
| Boltrig-local | 414 | SEC 230, FR 87, US 26, NFR 15, DIS 10, MEM 8, EMO 7, WRK 6, CODEX 5, IAC 5, KNO 5, CONV 3, FLT 2, REL 2, CHAN 1, WL 1, DH 1 |

The three `service_gated` invariants are the Codex cell smoke pair under
[`tests/invariants.yaml:153`](../../../tests/invariants.yaml) `"SEC-159:"`, `MEM-ENG-03` behind the cognee live gate at
[`tests/invariants.yaml:1083`](../../../tests/invariants.yaml) `"MEM-ENG-03:"`, and `FR-WFL-17` behind `HATCHET_CLIENT_TOKEN` at
[`tests/invariants.yaml:1775`](../../../tests/invariants.yaml) `"FR-WFL-17:"`. `FR-WFL-17` has exactly one binding and it is
gated, so offline it reports `GATED`, not `ok`
([`scripts/check_invariants.py:190`](../../../scripts/check_invariants.py) `status = "GATED"`).

### 4.3 The order and its directives

An order is a YAML file in `.vjs/orders/` with `id`, `court`, `status`,
`holding`, a list of `directives` each carrying `id`, `actor` and `must`, an
optional `citation`, `forbidden`, `exceptions`, `supersedes`, `source_opinion`,
`runtime_summary`, `created_at`, `assent_source`, and optionally
`implementation_status` plus `implementation_note`.

Measured: **24 order files, all `status: binding`, carrying 163 directives**
between them, from 3 (the appellate order) to 11 (`ORG-WORKSPACE-TENANCY-001`).
Only 9 of the 24 carry an `implementation_status` field at all: 5 `OPEN`, 2
`DISCHARGED`, 1 `IMPLEMENTED`, 1 `PARTIAL`. The other 15 declare no
implementation state.

Two courts appear: `county` (23 files, prefix `2026-VJS-CC-BOLTRIG-`) and
`appeal` (1 file, `2026-VJS-CA-BOLTRIG-CODEX-APPROVAL-ROUTING-001`, citation
`[2026] VJS-APPEAL 1`, directives `A1` to `A3`). The county order of the same
name carries `D1` to `D6` and citation `[2026] VJS-COUNTY 12`.

### 4.4 The waiver

Four exemption ledgers share one shape: an object keyed by subject, each entry
carrying `owner`, `reason` and `expires` (ISO date). An entry that is blank,
unowned, or expired is itself a gate failure, in every one of them.

| ledger | entries | earliest expiry | expired at referent |
| --- | --- | --- | --- |
| `docs/refactoring/structural-exemptions.json` | 34 | 2026-10-31 | 0 |
| `docs/refactoring/order-binding-exemptions.json` | 15 | 2026-08-31 | 0 |
| `docs/refactoring/unwired-claims-allow.json` | 17 | 2026-09-30 | 0 |
| `docs/refactoring/worker-structural-debt.json` | 61 | 2026-12-31 | 0 |
| `docs/refactoring/health-claim-exemptions.json` | 0 | n/a | n/a |
| `docs/security/accepted-advisories.json` | 14 | 2026-09-11 | 0 |
| `.trivyignore.yaml` | 3 misconfig + 13 vuln | 2026-08-15 | **1** |

The single expired entry is `AVD-DS-0002` for `apps/worker/Dockerfile`
([`.trivyignore.yaml:26`](../../../.trivyignore.yaml) `"expired_at: 2026-08-15"`),
nine days before the referent commit's own date (`git log -1 --format=%ci` gives
`2026-08-24 07:57:22 +0100`). Its statement says so out loud: "Both move to
nginx-unprivileged as one piece of work, or this expires and iac-scan turns red on
both."

### 4.5 The decision record

`docs/decisions/` holds **42 markdown files**. There is no template, no index, no
README, and no gate. The only mechanical relationship anything has to them is
`scripts/check_prose_references.py`, which scans `docs/**/*.md` and therefore
requires the paths and citations INSIDE a decision to resolve; it says nothing
about the decision's number, status or existence (bounded: `grep -rn
"docs/decisions"` over `*.py`, `*.sh`, `Makefile`, `*.yml`, `*.toml` in the
pinned tree yields nine hits, of which four are `check_prose_references.py`
ALLOW entries, four are prose in `boltrig/` or `docker-compose.yml`, and one is a
test reading decision 0006's text; none enumerates the directory).

Numbering is a filename convention only, and it has drifted three ways:

- **0023 appears twice.** `0023-refuse-model-judged-approvals.md` (status
  "REFUSED, settled", occasion 2026-08-07) and
  `0023-sleep-distillation-and-the-adapter-seam.md` (status "accepted
  (2026-08-09); DIS-1..DIS-8 bound and green").
- **0030 appears twice.** `0030-agents-tab-built-on-web-sdk.md` and
  `0030-familiar-modes-and-dials.md`, both "accepted", both dated 2026-08-18.
- **0005 has never existed.** Bounded: `git log --all --diff-filter=A --name-only
  -- docs/decisions/` over the full 1708-commit history (this clone is not
  shallow, `.git/shallow` is absent) matches zero `0005` path.

Status vocabulary is uncontrolled. Twenty-nine records use `- Status: <word>`,
seven use `**Status:** <sentence>`, five use a bare `Status: <word>` line, and
`0004-spatial-deck-frontend.md` carries no status field at all (bounded: first
`Status` match per file across all 42, plus a targeted `grep -n "^status"` on
0004 returning nothing). Observed values include accepted, proposed, superseded,
in force, RULED, DONE, REFUSED, OPEN, decided and SUPERSEDED FOR BOLTRIG V2.

### 4.6 The VDS record

`.vds/config.toml` is "the one fixed anchor (VDS S-3(7))" and holds no design
value ([`.vds/config.toml:2`](../../../.vds/config.toml) `"This file holds NO design value (VDS S-2(2))"`). It declares:

- `jurisdiction_id = "boltrig"`, `repo_code = "BOLTRIG"`,
  `designpack = "none@0"`.
- a declared surface of five screen globs, all under
  `apps/worker/src/components/`.
- `governed_import_prefixes = ["./components/", "../components/", "./"]`; a
  reference outside those is counted and not enforced.
- `stylesheet = "apps/worker/src/styles.css"` as the system of record for what a
  token resolves to.
- `[governance] permit_required` over five path globs including `.vds/config.toml`
  itself, and `permit_exempt` over logs, permits and proofs.

Record counts on the pinned tree: register 65 `CMP-*.yaml`, screens 7
`SCR-*.yaml`, directions 42 `DIR-*.yaml`, reviews 6 `VRW-*.yaml`, ledgers 4
(`screens.yaml`, `routes.yaml`, `frames.yaml`, `figma.yaml`), logs 31, proofs 794.

### 4.7 The VJS record beyond orders

`.vjs/` holds 124 files: 24 orders, 33 filed submissions, 22 convenings, 21
permits, 20 decision logs, 1 proof, 2 scripts under `bin/`, and the vendored canon
citator. A permit is a self-issued front-door record scoped to paths, carrying
obligations (`decision_log`, `validation`), an `expires_at`, an `intent_digest`
and a `law_source` list of every order in force at issue time; its `meaning` field
states explicitly that it "cannot satisfy a check reserved to the Sovereign
(assent) or to a constituted bench (an order)"
([`.vjs/permits/PERMIT-1785316217.yaml:25`](../../../.vjs/permits/PERMIT-1785316217.yaml) `"NOT an external authority''s approval"`). `.vjs/bin/heavy-job.sh` is a
machine-wide memory lock installed by VJS, not by this repo, and is the guard the
pre-push hook looks for.

## 5. Control flow

The main path is the journey a change takes from an editor to a published
release. Each step names its failure branch.

**Step 1. The author runs a subset locally.** `make check` runs twelve targets
([`Makefile:223`](../../../Makefile) `"check: invariants lint architecture"`). Its own help text states that this is
NOT what CI enforces and names the seven `python-quality` targets it omits
(claims, commit-trailers, gate-coverage, health-claims, order-directives,
override-locks, prose-references). *Failure branch*: make stops at the first
non-zero target; nothing aggregates and nothing records.

**Step 2. The push is intercepted, if the hook is armed.** `.githooks/pre-push`
runs, in order: `codex-pin-health`, `continuity-projection`,
`visual-evidence`, `compose-validate PY=python3`, a merge-drift warning, then
`quality-gate` (which execs `make python-quality`)
([`.githooks/pre-push:159`](../../../.githooks/pre-push) `run_gate "codex pin health" codex-pin-health`). *Failure branch*: any gate returning non-zero
prints `push blocked` and exits 1. Exit code 75 from the heavy-job guard is
translated specially, because a gate refused for lack of memory did not fail, it
did not run
([`.githooks/pre-push:147`](../../../.githooks/pre-push) `"Nothing was tested, so nothing failed"`).

**Step 2a. The hook refuses an absolute hooks path.** If `core.hooksPath` starts
with `/`, the push is blocked outright, because an absolute path makes every
linked worktree run one directory's hooks
([`.githooks/pre-push:100`](../../../.githooks/pre-push) `"core.hooksPath is ABSOLUTE ($hooks_path)"`).

**Step 2b. The heavy-job guard is announced, not assumed.** If
`.vjs/bin/heavy-job.sh` is not executable the hook prints "gates run UNGUARDED"
and continues ([`.githooks/pre-push:126`](../../../.githooks/pre-push) `"NOTE: .vjs/bin/heavy-job.sh is absent"`). On the pinned
tree the file IS present at `.vjs/bin/heavy-job.sh`, 161 lines.

**Step 2c. The hook names what it did not run.** After a green pass it prints the
six CI jobs and three `test-and-gate` steps it does not cover
([`.githooks/pre-push:248`](../../../.githooks/pre-push) `"the gates ABOVE are green"`), then lists every root-level gitignored file that a
tracked test names, as a hint and explicitly not a gate.

**Step 3. CI runs two workflows on every push to main and every pull request.**
`ci.yml` declares six jobs; the desktop matrix expands to three, so eight job
runs. `security.yml` declares four jobs; CodeQL expands to three languages and
containers to four images, so nine job runs.

**Step 4. Two aggregator jobs collapse those into two branch-protection
contexts.** `ci.yml`'s `quality` job asserts five results are `success`
([`.github/workflows/ci.yml:237`](../../../.github/workflows/ci.yml) `test "${{ needs.test-and-gate.result }}" = success`), and
`security.yml`'s `security` job named "Security gate" asserts three
([`.github/workflows/security.yml:186`](../../../.github/workflows/security.yml) `test "$SOURCE_RESULT" = success`). Both carry `if: always()` so a skipped
dependency is still evaluated rather than skipping the aggregator. *Failure
branch*: `test` returns 1, the aggregator job fails, the required context is red.

**Step 5. `security.yml` refuses to cancel itself on main.**
`cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`
([`.github/workflows/security.yml:28`](../../../.github/workflows/security.yml) `"cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}"`),
because a cancelled run on a guarded ref leaves no successful evidence and nothing
can merge. The comment records this as condition precedent (a) of
`[2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001` Order 4.

**Step 6. An operator can ask whether main is actually green.**
`scripts/gate-status.sh` queries `gh run list`, filters to `push` events on the
exact sha, groups by `workflowName` and takes the latest per workflow. *Failure
branch*: no completed run is reported as "unproven, not green" and exits 1
([`scripts/gate-status.sh:80`](../../../scripts/gate-status.sh) `"has NO completed run - unproven, not green"`); `gh` absent exits 2.

**Step 7. A tag triggers release, which re-proves the whole workflows.**
`release.yml`'s preflight requires that the LATEST run of `ci.yml` and of
`security.yml` for the exact release commit is `completed` and `success`
([`.github/workflows/release.yml:188`](../../../.github/workflows/release.yml) `"require_successful_workflow ci.yml 'ci / quality'"`). *Failure branch*: no run
for that sha, or any non-success, exits 1 before a single image is built.

### 5.1 The gate wiring table

Derived by parsing the Makefile's rules and recipes read-only, then closing each
aggregate over its prerequisites. `q` = reachable from `make quality`, `pq` = from
`make python-quality`, `chk` = from `make check`, `hook` = invoked by
`.githooks/pre-push`, `CI` = reached by a workflow `run:` line.

| script | make target | q | pq | chk | hook | CI |
| --- | --- | --- | --- | --- | --- | --- |
| check_invariants.py | invariants | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_architecture.py | architecture | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_structure.py | structure | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_vds_ledgers.py | vds-ledgers | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_codex_protocol.py | codex-protocol | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_unwired_claims.py | unwired-claims | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_reachability.py | reachability | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_prose_references.py | prose-references | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_commit_trailers.py + selftest | commit-trailers | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_tracked_symlinks.py + selftest | tracked-symlinks | yes | yes | yes | via quality-gate | ci/test-and-gate |
| check_gate_coverage.py | gate-coverage | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_health_claims.py | health-claims | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_order_directives.py | order-directives | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_claim_inventory.py | claims | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_override_locks.py | override-locks | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_no_vacuous_greens.py | no-vacuous-greens | yes | yes | no | via quality-gate | ci/test-and-gate |
| check_secret_scan_history.py | secret-scan | yes | no | no | no | security/source-security |
| check-release-age-exclusions.py | lockfile-policy | yes | no | no | no | ci/worker-build, ci/site-build-test-lint |
| check_continuity_projection.py | continuity-projection | **no** | **no** | yes | **yes, directly** | **no** |
| check_codex_pin_health.py | codex-pin-health | **no** | **no** | yes | **yes, directly** | **no** |
| check_user_authority.py | user-authority | no | no | no | no | no (needs a live tenant DSN) |
| check_fleet_drift.py | fleet-drift | no | no | no | no | no (needs a live box over ssh) |
| check_brand_core.sh | **none** | no | no | no | no | no |
| check_familiar_shader.sh | **none** | no | no | no | no | no |

Two further targets sit in the hook and in no CI job: `visual-evidence`
([`Makefile:130`](../../../Makefile) `"visual-evidence: ## Refuse a capture receipt"`) and `compose-validate PY=python3` (the target
IS in CI, but with `PY=python`, and the hook runs it on a bare `python3`
deliberately, to test the interpreter axis).

### 5.2 What the orphan census can and cannot see

`check_gate_coverage.py` asserts three things and prints all three tables
([`scripts/check_gate_coverage.py:342`](../../../scripts/check_gate_coverage.py) `"if unvalidated or uncovered or orphan_checks:"`):

1. every compose manifest under `deploy/compose*.yml` plus the root
   `docker-compose.yml` is a `-f` input to some recipe invoking `$(COMPOSE)` with
   `config`. Six manifests exist; all six are validated by the
   `compose-validate` recipe.
2. every prerequisite of `quality` is invoked by a workflow `run:` line, directly
   or transitively through all of its own prerequisites. Eight components; all
   eight resolve (`security-source` transitively, via its five named components in
   `security/source-security`).
3. every `scripts/check_*.py` filename appears in some Makefile recipe
   ([`scripts/check_gate_coverage.py:266`](../../../scripts/check_gate_coverage.py) `for path in sorted((ROOT / "scripts").glob("check_*.py")):`). All 23
   do.

It does NOT ask: whether a gate in the Makefile is reached by CI (only whether
`quality`'s own prerequisites are), whether the pre-push hook covers CI (recorded
as still-open debt at
[`docs/CI-RED-2026-08-14.md:440`](../../../docs/CI-RED-2026-08-14.md) `"No gate asserts the hook covers CI"`), or whether a shell gate exists at all,
because its glob is `check_*.py`.

### 5.3 The invariant gate's own control flow

1. Scan every `tests/**/test_*.py` for `@pytest.mark.invariant("X")`, attributing
   each pending marker to the next `def test...` line. The scan is floored at 50
   modules through `require_scanned`
   ([`scripts/check_invariants.py:52`](../../../scripts/check_invariants.py) `"test modules under tests/", minimum=50`). *Failure branch*: fewer than
   50 modules exits 1 with "scanned nothing".
2. Parse `tests/invariants.yaml` with a stdlib indentation reader. A **repeated
   id raises `CatalogueError`** and exits 1, because PyYAML's own last-wins
   silently evicted `SEC-169` for four months
   ([`scripts/check_invariants.py:120`](../../../scripts/check_invariants.py) `"duplicate invariant id {current!r} in"`).
3. Compute `unbound` (declared with no marker), `undeclared` (marker not
   declared), and `drift` (a claimed node id no marker backs, or a
   `service_gated` id not among that invariant's own declared tests).
4. Print the coverage table with per-invariant status `ok`, `ok (n gated)`,
   `GATED` or `UNBOUND`, then the summary line
   `declared=.. marked=.. bound_tests=.. binding_debt=..`.
5. `debt = len(unbound) + len(undeclared)`. Any debt, or any drift, exits 1
   ([`scripts/check_invariants.py:232`](../../../scripts/check_invariants.py) `"RESULT: FAIL - binding debt must be zero (and may only decrease)."`).

**The asymmetry that matters.** Step 3 checks catalogue-to-marker in one
direction only. A node id that carries a marker but is absent from the
catalogue's `tests:` list is not drift and is not debt. Measured: **361 of the
1836 real (id, node) pairs are not written into the catalogue**, and the gate is
green. The catalogue therefore under-reports the true binding by about 20 percent
without failing.

### 5.4 The court-directive gate's control flow

1. Glob `.vjs/orders/*.yaml`, floored by `require_scanned`; glob `tests/**/*.py`
   for sources, also floored, with the path filter applied RELATIVE to the scan
   base so a checkout under a dot-named parent does not blank the scan
   ([`scripts/check_order_directives.py:164`](../../../scripts/check_order_directives.py) `part.startswith(".") or part in {"__pycache__"`).
2. Skip any order whose `status` is not `binding`
   ([`scripts/check_order_directives.py:222`](../../../scripts/check_order_directives.py) `if order["status"] != "binding":`). On the pinned tree this skips
   nothing: all 24 are binding.
3. For each order, build its key set: full id, citation, and the tail after
   `\d{4}-VJS-[A-Z]+-BOLTRIG-`.
4. For each directive id, require a test line matching that id as a whole word
   within `PROXIMITY_LINES = 2` of a line naming the order. The proximity is
   load-bearing: whole-file matching counted 57 bound where same-line-or-adjacent
   counts 36, and the gate's own test file cross-matched itself.
5. An unbound directive must have an entry keyed `<short>:<directive>` in
   `docs/refactoring/order-binding-exemptions.json` with owner, reason and a
   future ISO expiry. A malformed, expired, or *unused* entry is itself a failure
   ([`scripts/check_order_directives.py:257`](../../../scripts/check_order_directives.py) `"exemption names a directive that is bound or absent"`).
6. Any unbound directive or any waiver problem exits 1
   ([`scripts/check_order_directives.py:289`](../../../scripts/check_order_directives.py) `"RESULT: FAIL - a binding directive is enforced by nothing."`).

**Strict in one direction, loose in the other, stated as such**: the mention must
be in `tests/`, never in `boltrig/`, because a comment saying "D4 requires this"
is the claim and not the enforcement; and it does not try to judge whether the
test proves the directive, because "pretending otherwise would be this gate
committing the defect it exists to catch"
([`scripts/check_order_directives.py:34`](../../../scripts/check_order_directives.py) `"loose: it does not try to judge whether the test actually PROVES"`).

**The 15 live waivers** fall into six classes, each named in the entry's own
reason: three appellate directives with no engineering consequence
(`CODEX-APPROVAL-ROUTING-001:A1/A2/A3`), four Principal gates on a live cutover or
external credential (`AUDIT-DEPTH-001:D8`, `FIRST-PARTY-AUTH-001:D10`,
`ORG-WORKSPACE-TENANCY-001:D10`, `OPERATOR-SEAT-001:D8`), three that require a
`SELECT` on a remote tenant database (`HITL-NOTIFICATION-ROUTING-001:D4`,
`DEVELOPMENT-POSTURE-001:D7/D8`), one awaiting a released upstream artefact
(`SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001:D4`), one reserved to the Principal's own
act (`D7-DISCHARGE-001:V1`, expiring 2026-08-31, seven days after the referent
commit), and three whose subject was retired with the replacement still owed
(`UI-TEST-HARNESS-001:D1/D2/D3`, which record that the Worker has no browser
smoke test at all today).

### 5.5 The vacuous-green sweep

`check_no_vacuous_greens.py` runs every `scripts/check_*.py` (excluding the two
selftests and itself) inside a temporary tree that has the full `scripts/`
directory, the Makefile, `pyproject.toml`, and four EMPTY directories, and
requires each to refuse. The discriminator is not the exit code but the
vocabulary: exit 0 plus one of `OK`, `PASS`, `GREEN`, `clean` in the output is a
finding; exit 0 while saying it checked nothing is honest and is not flagged
([`scripts/check_no_vacuous_greens.py:106`](../../../scripts/check_no_vacuous_greens.py) `"THE DISCRIMINATOR. Exit 0 is not the test, the PASS WORD is."`).

Three gates are declared to have no empty-tree form, each with a reason in the
source ([`scripts/check_no_vacuous_greens.py:48`](../../../scripts/check_no_vacuous_greens.py) `"NO_EMPTY_TREE_FORM = {"`): `check_fleet_drift.py`,
`check_codex_pin_health.py`, `check_user_authority.py`. So 20 gates are
enumerated, 3 skipped, 17 swept. `--self-test` builds two synthetic gates, one
vacuous and one honest, proves the verdict function separates them, and then
requires the real corpus to be non-empty as a positive control.

`scripts/scan_guard.py::require_scanned` is the shared helper. It exits the
process rather than raising, so no caller can swallow it
([`scripts/scan_guard.py:19`](../../../scripts/scan_guard.py) `"This exits the process rather than raising"`). Adoption measured: six gates
import it (`check_gate_coverage`, `check_invariants`, `check_no_vacuous_greens`,
`check_order_directives`, `check_health_claims`, `check_unwired_claims`) out of
20 sweepable gates. The sweep's own docstring says "FIVE of the eighteen" and
"5 of 18", both now stale; the property is what is enforced, not the import, and
that is deliberate ("Mandating the import would be enforcing a spelling").

## 6. Data

### 6.1 `tests/invariants.yaml`

2838 lines. A controlled YAML subset parsed by an indentation reader, not by
PyYAML, so the gates ship stdlib-only. The declared shape is:

```
invariants:
  <ID>:
    description: <single-quoted one line>
    tests:
      - <path::test_name>
    service_gated:          # optional, must be a subset of tests
      - <path::test_name>
```

Single-quoted scalars are required because descriptions carry colons and hashes,
and a literal apostrophe is escaped by DOUBLING; the reader undoes that or "84 of
the 326 descriptions read back wrong"
([`scripts/check_invariants.py:76`](../../../scripts/check_invariants.py) `"escapes a literal apostrophe by DOUBLING it"`). `NFR-MNT-02` binds the reader
to a real YAML parser's answer, so the shortcut cannot diverge.

### 6.2 `docs/claim-inventory.tsv`

1790 data rows plus a header of six columns: `weight`, `classification`,
`source`, `location`, `subject`, `claim`. The file is a generated artefact
rebuilt by `make claim-inventory`; `make claims` regenerates it in memory and
requires **byte-identical** agreement, so it cannot be edited into compliance.

Distribution measured on the pinned tree:

| weight | classification | rows |
| --- | --- | --- |
| ORDINARY | NO-SUBJECT | 983 |
| LOAD-BEARING | SUBJECT-REACHED | 276 |
| **LOAD-BEARING** | **NO-SUBJECT** | **206** |
| ORDINARY | SUBJECT-REACHED | 130 |
| ORDINARY | SUBJECT-EXTERNAL | 107 |
| LOAD-BEARING | SUBJECT-EXTERNAL | 88 |
| any | SUBJECT-ABSENT | 0 |

The ratchet is the third row. `docs/refactoring/claim-inventory-baseline.json`
pins `load_bearing_no_subject: 206`, so the residue is exactly at par. A
`SUBJECT-ABSENT` row is an unconditional failure regardless of the baseline
([`scripts/check_claim_inventory.py:98`](../../../scripts/check_claim_inventory.py) `"the claim outlived its subject, or the"`); there are none.

### 6.3 The ratchets, and their inconsistent directions

| ratchet | pinned in | growth | shrink |
| --- | --- | --- | --- |
| binding debt | implicit 0 | FAIL | n/a, floor is 0 |
| structural file lines | structural-exemptions.json | FAIL | **FAIL** ("baseline is stale-high") |
| structural per-function lines | same, `over_limit_functions` | FAIL | **FAIL** |
| unreachable functions | reachability-roots.json, `unreachable_baseline: 139` | FAIL | note only |
| load-bearing no-subject claims | claim-inventory-baseline.json, `206` | FAIL | note only |
| worker TS structure | worker-structural-debt.json, 61 entries | FAIL | exact, per the gate |

Only the structure gate enforces the ratchet in both directions
([`scripts/check_structure.py:257`](../../../scripts/check_structure.py) `"baseline is stale-high: {path} is {measured} lines"`). Reachability and the
claim inventory print "Re-pin it in this change" and return 0
([`scripts/check_reachability.py:230`](../../../scripts/check_reachability.py) `"the count FELL, {baseline} -> {len(unreachable)}"`).

Fixed limits: `FILE_LINE_LIMIT = 400`, `FUNCTION_LINE_LIMIT = 80` for Python
([`scripts/check_structure.py:25`](../../../scripts/check_structure.py) `"FILE_LINE_LIMIT = 400"`); for the Worker, 400 file lines, 80 function lines,
5 parameters, complexity 15, nesting depth 4
(`docs/refactoring/worker-structural-debt.json`, `limits`). The largest exempted
Python file is `boltrig/store/postgres.py` at 1895 lines; the largest exempted
function is 516 lines in `boltrig/api/auth_routes.py`. Ten owner teams appear
across 34 exemptions, led by fleet-maintainers with 10.

### 6.4 Retention and encryption

None. Every record in this area is a plain committed file. `.vds/.gitignore`
allows exactly two ignored paths and says why
([`.vds/.gitignore:1`](../../../.vds/.gitignore) `"the record is committed, not scratch"`). No governance record is encrypted, no
governance record is pruned, and no migration touches this area (bounded: `ls
migrations/` contains no file naming invariants, orders, decisions or claims).

## 7. Configuration surface

| variable / key | default | what it changes | what breaks if wrong |
| --- | --- | --- | --- |
| `core.hooksPath` (git config) | **unset** | whether `.githooks/pre-push` runs at all | unset means no local gate; absolute means every linked worktree runs one tree's hooks, and the hook refuses to run under it |
| `SKIP_PUSH_GATES` | unset | `=1` skips every pre-push gate | a push with no local evidence, announced on stdout |
| `SKIP_QUALITY_GATE` | unset | `=1` skips only `python-quality` | the four cheap gates still run; the 324s suite does not |
| `BOLTRIG_BASE_REF` | `origin/main` | which ref the merge-drift warning compares against | a wrong ref makes the warning silent, and silence reads as agreement |
| `PY` | `.venv/bin/python` ([`Makefile:8`](../../../Makefile) `"PY ?= .venv/bin/python"`) | the interpreter every Python gate runs on | a venv with the package installed hides an import CI will reject; the hook runs `compose-validate PY=python3` for exactly this |
| `PNPM` | `corepack pnpm` | the JS package manager for worker and site gates | a non-corepack pnpm breaks the frozen-lockfile contract |
| `COMPOSE` | `docker compose` | how manifests are validated | gate-coverage keys on the literal `$(COMPOSE)` token in the recipe |
| `COVERAGE_MIN` | `82` | `--cov-fail-under` for the Python suite | lowering it silently weakens the only coverage floor |
| `COMPOSE_VALIDATE_ENV` | `.env.example` | the env file compose validation reads | pointing it at a real `.env` would validate a machine, not the repo |
| `TRIVY_CONFIG_IMAGE`, `GITLEAKS_IMAGE`, `ACTIONLINT_IMAGE` | digest-pinned | the scanners `security-source` runs | an unpinned tag makes the gate's verdict a fact about a mutable image |
| `BOLTRIG_QUALITY_VM` | `boltrig-vm` | the OrbStack machine the macOS path uses | a wrong name aborts with a named error rather than running on the host |
| `BOLTRIG_QUALITY_VM_PY` | `$HOME/boltrig-venv/bin/python` (unexpanded) | the in-VM interpreter | passed to make unexpanded it arrives as `OME/...`, so the shim resolves it inside the VM first |
| `BOLTRIG_ROOT` | the repo root | where the vacuous-green sweep looks for gates | pointing it elsewhere sweeps another tree |
| `WORKER_STRUCTURE_BASE_REF` | `pull_request.base.sha` or `github.event.before` | the immutable Git object the Worker debt catalogue is loaded from | a contributor-controlled second working-tree file would let a co-edited debt record pass |
| `FAMILIAR_UPSTREAM_DIR` | `$HOME/Projects/beelink-desktop/familiar` | where the shader drift gate finds upstream | absent means exit 2 "NOT CHECKED", never a green |
| `OPBOX_UPSTREAM_DIR` | `$HOME/Projects/opbox-build-main` | where the brand drift gate finds upstream | nine trees on the box carry an `opbox-mark.svg`; the default is pinned to the one on main |
| `CANON_REPO` | `$HOME/Projects/vibe-justice-system` | source for `make refresh-canon-citations` | only affects the refresh, never the gate: the gate reads the vendored `.vjs/canon-citations.txt` |
| `OPBOX_REPO` | `$HOME/Projects/opbox-prod` | source for `make refresh-opbox-surface` | as above |
| `DRIFT_HOST` | **empty** | the production host `fleet-drift` audits | deliberately unset so no production host is bundled |
| `DRIFT_PROJECT`, `DRIFT_COMPOSE`, `DRIFT_OVERLAY` | `boltrig`, `$HOME/Projects/boltrig-main/...`, `$HOME/Projects/opbox-prod/...` | which tenant drift is measured against | `fleet-drift` alone answers for one of two tenants; `fleet-drift-all` runs both |
| `DSN`, `MANIFEST` | unset | inputs to `check_user_authority.py` | unset exits 2, never 0 |
| `BOLTRIG_ALLOW_UNVERIFIED_POSTGRES` | unset | accepts a run with the Postgres surface skipped | set, a green run no longer proves RLS, store parity, migration parity or tenancy |
| `BOLTRIG_ALLOW_UNVERIFIED_RATELIMIT` | unset | accepts a run with the shared rate-limit surface skipped | set, the regression test for the headline RedisCounter defect is unverified |
| `.vds/config.toml` `[surface] screen_globs` | five globs | the entire VDS declared surface | a screen outside these globs is outside every proof |
| `.vds/config.toml` `designpack` | `none@0` | which designpack digest the proofs bind to | `none@0` means no design authority is pinned; `designpack.lock` records the digest of nothing |

## 8. PROCESS

### 8.1 How a new invariant is added

The procedure is written down, at
[`docs/invariants.md:468`](../../../docs/invariants.md) `"## How a new invariant is added"`:

1. Write the test and mark it `@pytest.mark.invariant("NEW-ID")`.
2. Declare it in `tests/invariants.yaml` with a description and node ids.
3. Document it in the table in `docs/invariants.md`.
4. Run `make invariants` (debt must stay 0) and `make test`.

Steps 1, 2 and 4 are mechanically enforced. **Step 3 is not.** Measured: 171 ids
appear in the `docs/invariants.md` table, all 171 are real declarations, and 250
of the 421 declared ids are absent from it. The document says this is by design
("the table below is the curated human-readable view", line 19), which makes step
3 of its own procedure a statement nobody follows for 59 percent of the
catalogue.

### 8.2 How a gate is added

There is no written procedure. The mechanical requirement is exactly one line,
imposed by `check_gate_coverage.py`: the script's filename must appear in some
Makefile recipe, or the build goes red. The rule is deliberately crude, because
"anything cleverer needs a list of which gates count, and that list is the thing
that goes stale"
([`scripts/check_gate_coverage.py:259`](../../../scripts/check_gate_coverage.py) `"The rule is deliberately crude"`). Being in a Makefile recipe does not put a
gate in CI, and nothing checks the difference.

The incident this rule exists for is recorded in the same docstring:
`check_reachability.py` "was written and merged on 2026-07-27 under a court
order, was correct, printed a clean report, and was wired into NO make target and
no workflow. It ran exactly once, by hand, on the day it was written."

### 8.3 How a decision is made, numbered and enforced

**Made**: `AGENTS.md` says a first-impression architecture, scope or doctrine
change means "stop and surface the decision with the trade-offs, do not land it
silently" ([`AGENTS.md:81`](../../../AGENTS.md) `"make the call, note it. First-impression"`). It does not say to write a record.

**Numbered**: by hand, in the filename. Nothing allocates, nothing checks, and
the result is 0005 missing, 0023 twice and 0030 twice.

**Enforced**: not at all as a class. Two individual decisions are pinned by
tests, and only because a court order cites them:
[`tests/security/test_order_record_directives.py:103`](../../../tests/security/test_order_record_directives.py) `_text("docs/decisions/0006-inline-chat-attachments.md")` reads decision 0006's text,
and decision 0023's sleep-distillation limb declares itself "Bound by: DIS-1..DIS-8
(`tests/invariants.yaml`)". Decision 0019 is bound in the other direction:
`docs/refactoring/unwired-claims-allow.json` waives `select_or_generate_workflow`
with `"blocker": "principal:PRINCIPAL-2026-07-27-ROUTE-BY-INTENT"` and a note that
on expiry without an answer "the order's ratio applies with no further order:
retire".

### 8.4 How a court order is filed and discharged

1. A submission is filed to `.vjs/submissions/filed/SUBMISSION-<timestamp>.yaml`.
2. A bench is convened, recorded in `.vjs/court/convenings/CONVENING-<court>-<timestamp>.yaml`.
3. The order is written to `.vjs/orders/<id>.yaml` with `status: binding`,
   a `holding`, numbered `directives`, and a `source_opinion` pointing at
   `docs/vjs/<id>-opinion.md`.
4. Each directive is discharged by naming BOTH the order and the directive id
   within two lines of each other, in a file under `tests/`.
5. What cannot be discharged that way is waived in
   `docs/refactoring/order-binding-exemptions.json` with owner, reason and expiry.
6. Acts taken on an order's authority are recorded in
   `.vjs/logs/decisions/LOG-<timestamp>.yaml`, carrying `decision`, `basis`
   (the order ids), `risk`, `reversibility`, `court_required` and `why`
   ([`.vjs/logs/decisions/LOG-2026-07-25-113350.yaml:6`](../../../.vjs/logs/decisions/LOG-2026-07-25-113350.yaml) `"Enabled branch protection on wlilley93/boltrig main"`).
7. When the order is satisfied, `implementation_status` and
   `implementation_note` are added to the order file. Nothing reads them.

**Federated citations.** Boltrig cites canon rulings it does not hold. Rule 5 of
`check_prose_references.py` resolves an order citation against this repo's own
register OR the vendored `.vjs/canon-citations.txt` (179 lines, 12 comment lines
and 167 citation ids). The file exists because the first cut read the canon
repository off the author's disk and "passed here and reddened main the moment CI
ran it"
([`scripts/check_prose_references.py:60`](../../../scripts/check_prose_references.py) `"WHY IT SCANS THE HISTORICAL RECORD"`;
the vendoring rationale is at lines 52 to 58).

### 8.5 How a gate is diagnosed when it goes red

- `make gate-status` asks the remote whether main is actually green, because
  branch protection carries `enforce_admins: false` and a bypassed push prints a
  line that "reads like routine chatter about checks not having finished yet"
  ([`scripts/gate-status.sh:12`](../../../scripts/gate-status.sh) `"That message reads like routine chatter"`).
- On macOS, `make quality-gate` runs the Python suite inside an OrbStack Linux
  machine, because 17 tests assert Linux kernel controls macOS does not implement
  (measured: 34 host failures, 1 in the VM). It verifies five preconditions in
  order, each with its own named error: `orb` on PATH, the machine exists, the
  repo path resolves identically inside it, an executable interpreter at the
  resolved path, and a usable docker socket.
- `docs/CI-RED-2026-08-14.md` is the worked post-mortem and is the canonical
  statement of the four axes on which a local green does not predict CI: different
  COMMIT (CI tests `refs/pull/N/merge`), different FILESYSTEM (gitignored files
  participate locally), different INTERPRETER (`PY=python` on a bare runner), and
  different PLATFORM (`windows-2025`). Two are now covered by the hook; two are
  not, and the hook prints which.

### 8.6 Recovery

There is no recovery procedure for this area beyond re-running the gate, because
every artefact is a committed file and every ratchet is a committed number.
The one recorded restoration path is `make refresh-canon-citations` and
`make refresh-opbox-surface`, both of which re-vendor a file from a sibling
checkout and are run deliberately, never by a gate.

## 9. Failure modes and fail-open / fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| any tree scan finding nothing | **fail-closed** | `require_scanned` exits 1 with "This is NOT 'nothing is wrong'" ([`scripts/scan_guard.py:44`](../../../scripts/scan_guard.py) `"This is NOT 'nothing is wrong'. The gate could not look"`) |
| a repeated invariant id | **fail-closed** | raises `CatalogueError`, exits 1, rather than last-wins |
| a commit-trailer scan finding zero trailers | **fail-closed** | exits 1: "A scan with nothing to check is a broken scan" ([`scripts/check_commit_trailers.py:190`](../../../scripts/check_commit_trailers.py) `"A scan with nothing to check is a broken scan"`) |
| a secret scan on a partial clone | **fail-closed** | `GIT_NO_LAZY_FETCH=1`, any promised missing object exits 1 |
| an expired or unowned waiver, in all four ledgers | **fail-closed** | each gate appends a problem and returns 1 |
| an unused waiver | **fail-closed** | `order-directives` reports "names a directive that is bound or absent" |
| a stale-high structural baseline | **fail-closed** | `_compare_exact` returns an error on `measured < baseline` |
| a fallen reachability or claim-residue count | **fail-OPEN** | prints "Re-pin it in this change" and returns 0 |
| a shell drift gate with no upstream | **fail-closed on the verdict, exit 2** | "NOT CHECKED ... rather than reporting an agreement it did not observe" |
| `codex-pin-health` with `BOLTRIG_CODEX_BINARY` unset | **fail-open by design** | reports satisfiability, never fatal, because "a check that cannot pass on an ordinary checkout is a check people learn to skip" |
| a pre-push gate refused for memory (exit 75) | **fail-closed, correctly labelled** | "Nothing was tested, so nothing failed" |
| a missing heavy-job guard | **fail-open, announced** | prints "gates run UNGUARDED" and continues |
| an unarmed `core.hooksPath` | **fail-open, silent** | nothing announces it; the Makefile help says "or just push - the pre-push hook runs it" |
| a merge-drift warning | **fail-open by decision** | "Blocking would refuse every push from a branch that main has merely moved past" |
| a failed `git fetch` before the drift check | **fail-open, announced** | "its silence is not evidence of anything" |
| a cancelled security run on main | **prevented** | `cancel-in-progress` is false on `refs/heads/main` |
| a CI job that is skipped rather than failed | **fail-closed** | both aggregators use `if: always()` and assert `= success`, so `skipped` and `cancelled` both fail the context |
| a release tag whose commit has no CI run | **fail-closed** | "has no workflow run for $RELEASE_COMMIT", exit 1 |
| a pytest run whose Postgres or fakeredis precondition is missing | **fail-closed** | `pytest_sessionfinish` rewrites exit status to TESTS_FAILED ([`tests/conftest.py:171`](../../../tests/conftest.py) `"session.exitstatus = pytest.ExitCode.TESTS_FAILED"`) |
| a product env var exported in the operator's shell | **stripped** | an autouse fixture deletes every `BOLTRIG_`/`POSTGRES_`/`HATCHET_`/`LLM_`/`BACKUP_`/`EMBEDDING_`/`PG` prefixed name outside an 11-entry keep-list |

**The two documented escape hatches into fail-open** are
`BOLTRIG_ALLOW_UNVERIFIED_POSTGRES` and `BOLTRIG_ALLOW_UNVERIFIED_RATELIMIT`.
Each converts a blocking unverified precondition into a yellow "NOT VERIFIED by
this run" line. That is the design: "declining is a decision on the record instead
of an accident" ([`tests/conftest.py:40`](../../../tests/conftest.py) `"Each has its own opt-out so declining is a"`).

**The unrecoverable fail-open** is `git push --no-verify` plus
`enforce_admins: false`. Together they mean a single admin can put a commit on
main with no local gate and no green required check, and the only notice is a
`remote: Bypassed rule violations` line. `scripts/gate-status.sh` exists solely
because four commits went onto a red main in ninety minutes that way.

## 10. What is proven

The gates are themselves bound. The `NFR-MNT-*` family is the gate family's own
invariant set:

| invariant | binds | test |
| --- | --- | --- |
| NFR-MNT-01 | the Python structural ratchet, both directions, exact baselines | `tests/unit/test_structure_gate.py` |
| NFR-MNT-02 | the catalogue parses as YAML, the stdlib reader agrees with a real parser, and a repeated id is refused | `tests/unit/test_invariant_catalogue.py::test_a_repeated_invariant_id_is_refused_rather_than_eaten` |
| NFR-MNT-03 | prose references resolve, and every binding court directive is bound or recorded | `tests/unit/test_claim_gates.py::test_every_reference_the_record_makes_still_resolves`, `::test_every_binding_court_directive_is_bound_or_recorded` |
| NFR-MNT-04 | every compose manifest is validated and every `quality` component runs in CI | `tests/unit/test_claim_gates.py::test_every_compose_manifest_and_release_component_is_actually_reached` |
| NFR-MNT-05 | no service reports healthy while unable to serve; a blank, unowned or expired health waiver is itself a failure | `tests/unit/test_claim_gates.py`, seven tests |
| NFR-MNT-06 | a gate cannot pass by looking at nothing, and no unwired-claims waiver outlives its owner | `tests/unit/test_claim_gates.py::test_a_scan_that_finds_nothing_is_a_failure_not_a_pass` |
| NFR-MNT-07 | the Worker TypeScript ratchet, with the base catalogue loaded from an immutable Git object | `tests/unit/test_worker_structure_gate.py` |
| NFR-MNT-08 | the VDS screen and route ledgers are required source-bound inputs, not advisory snapshots | `tests/unit/test_vds_ledger_gate.py` |
| FR-ARC-01 | inward-only thin-orchestration layering | `tests/unit/test_architecture_gate.py::test_thin_orchestration_layers_depend_inward_only` |

Three gates have their own hermetic seeded-failure suites rather than a pytest
binding: `scripts/check_commit_trailers_selftest.py` (203 lines, builds a
throwaway git repository per case), `scripts/check_tracked_symlinks_selftest.py`
(176 lines), and `check_no_vacuous_greens.py --self-test`. Both selftests run in
the same Makefile recipe as the gate they test.

Three gates are bound by nothing at all: `check_codex_pin_health.py`,
`check_brand_core.sh` and `check_familiar_shader.sh` (bounded:
`grep -rl <name> tests/` returns no file for any of the three, 2026-08-24, pinned
tree; `check_tracked_symlinks` and `check_commit_trailers` also return nothing but
each carries a sibling selftest).

Measured facts this document establishes without running anything:

- binding debt is 0, verified by an independent read-only re-implementation of
  the gate over 510 test modules;
- the claim residue is exactly at its pinned baseline of 206;
- all six compose manifests are `-f` inputs to a `config` step;
- all eight `quality` components are reached by a workflow `run:` line;
- all 23 `scripts/check_*.py` appear in a Makefile recipe;
- every waiver in every Python-side ledger is unexpired at the referent commit.

## 11. RISKS

RISK: The pre-push gate is armed by nothing. `core.hooksPath` is unset in this
checkout and no target, script or bootstrap sets it, so the whole local layer is
opt-in per clone ([`.githooks/pre-push:81`](../../../.githooks/pre-push) `"Install: git config core.hooksPath .githooks"`; bounded:
`grep -n hooksPath genesis.sh scripts/dev-up.sh Makefile` returns nothing).

RISK: The Makefile tells the reader the hook runs, in the clone where it does
not. `check`'s help says "or just push - the pre-push hook runs it"
([`Makefile:223`](../../../Makefile) `"or just push - the pre-push hook runs it"`), and a phased-plan document records the opposite for the box holding the
pen ([`docs/PROGRAM-2026-08-18-phased-plan.md:154`](../../../docs/PROGRAM-2026-08-18-phased-plan.md) `"is unset in the beelink clone and"`).

RISK: Two gates make a false claim about their own wiring, which is the exact
defect class they belong to. `check_continuity_projection.py` ends "Wired into
`make check`, whose target list is the one CI runs"
([`scripts/check_continuity_projection.py:30`](../../../scripts/check_continuity_projection.py) `"Wired into `make check`, whose target list is the one CI runs."`) and
`check_codex_pin_health.py` ends "Wired into `make check`"
([`scripts/check_codex_pin_health.py:44`](../../../scripts/check_codex_pin_health.py) `"Exit 0 clean, 1 on a fatal condition. Wired into `make check`."`). Neither
target is a prerequisite of `quality` or `python-quality`, and no workflow `run:`
line names either. They run only in the pre-push hook, which is unarmed here.

RISK: The orphan-gate census is blind to shell gates. It globs `check_*.py`
([`scripts/check_gate_coverage.py:266`](../../../scripts/check_gate_coverage.py) `glob("check_*.py")`), so `check_brand_core.sh` and
`check_familiar_shader.sh` could become orphaned, or already be orphaned, without
any gate noticing. Both are in fact unwired, one of them on purpose and saying so
([`scripts/check_brand_core.sh:21`](../../../scripts/check_brand_core.sh) `"WIRED TO NOTHING, ON PURPOSE."`), the other silently.

RISK: No gate asserts the pre-push hook covers CI, and the debt is written down.
[`docs/CI-RED-2026-08-14.md:440`](../../../docs/CI-RED-2026-08-14.md) `"No gate asserts the hook covers CI"` proposes the converse direction for
`check_gate_coverage.py`; it is not implemented (bounded: the module has three
checks, `compose_validation_inputs`, `resolve_coverage` and
`unwired_check_scripts`, and no reference to `.githooks` anywhere in
`scripts/`).

RISK: The invariant catalogue may under-declare its own bindings without failing.
361 of 1836 real marker-backed (id, node) pairs are absent from the catalogue's
`tests:` lists, because drift is only checked catalogue-to-marker
([`scripts/check_invariants.py:168`](../../../scripts/check_invariants.py) `"claims {claimed} but no such marker exists"`). Deleting an undeclared binding
turns nothing red.

RISK: The gate that names itself after K-29 and K-30 declares neither. The
Makefile calls it "The K-29/K-30 binding gate"
([`Makefile:474`](../../../Makefile) `"The K-29/K-30 binding gate"`), [`.github/workflows/ci.yml:2`](../../../.github/workflows/ci.yml) `"The binding-invariant gate (K-29/K-30)"` and
[`boltrig/api/cli.py:10`](../../../boltrig/api/cli.py) `"run the invariant-binding gate (K-29/K-30)"` repeat it, and
`grep -cE '^  K-(29|30):' tests/invariants.yaml` returns 0. Only six `K-*`
ids are declared at all.

RISK: The founding ruling that makes all of this binding has never existed as a
file. `check_prose_references.py` allow-lists
`[2026] VJS-CC NANKLE-CONSOLIDATION 001` with the reason that "No file matching it
has ever existed in this repository's history"
([`scripts/check_prose_references.py:409`](../../../scripts/check_prose_references.py) `"has ever existed in this repository's history"`), while [`README.md:72`](../../../README.md) `"VJS-CC NANKLE-CONSOLIDATION 001"`
cites it as the authority for Boltrig's separate existence, and
[`tests/invariants.yaml:18`](../../../tests/invariants.yaml) `"below is the canonical invariant id from"` cites its directive D2
as the canonical source of every `K-*` id.

RISK: Two further orders are relied on in live code and were never filed, both
allow-listed rather than reconstructed:
`[2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001` and
`[2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001`
([`scripts/check_prose_references.py:383`](../../../scripts/check_prose_references.py) `"WAS given and was never written"`). The first is the authority
for the branch protection currently in force.

RISK: `docs/invariants.md` states a declared count of 390 and 1661 bound node ids
([`docs/invariants.md:15`](../../../docs/invariants.md) `"Today: **390 declared, debt 0** (1661 bound"`); measured today, 421 and 1836. The document hedges the
line as prose, and nothing checks it.

RISK: `docs/security-gates.md` contradicts itself about the required check names.
Lines 4 to 7 say the contexts are `quality` and `Security gate` and that the
`ci / quality` form "no check run publishes"; line 97 then instructs the reader to
"require the `ci / quality` and `security / Security gate` checks on `main`"
([`docs/security-gates.md:97`](../../../docs/security-gates.md) `"require the `ci / quality` and"`).

RISK: `docs/security-conformance.md` still records the CI/CD family's residue as
"making the gates REQUIRED in branch protection"
([`docs/security-conformance.md:42`](../../../docs/security-conformance.md) `"making the gates REQUIRED in branch protection - all ops"`) while
[`docs/security-gates.md:3`](../../../docs/security-gates.md) `"and as of 2026-07-25 they ARE"` records that they have
been required since 2026-07-25.
The same document carries a live `PI` runtime family
([`docs/security-conformance.md:34`](../../../docs/security-conformance.md) `"the real Pi loop replaces the stand-in"`) for a lane retired by decision 0020
and declared inert by invariant `FR-RUN-21`.

RISK: `docs/GOAL-trustworthy-gate.md` declares itself MET against a job list that
no longer exists. Its criterion 1 names `ui-build` and `ui-e2e`
([`docs/GOAL-trustworthy-gate.md:25`](../../../docs/GOAL-trustworthy-gate.md) `"`test-and-gate`, `ui-build`, `ui-e2e`, `site-build-test-lint`"`), and
neither string appears anywhere under `.github/` (bounded: `grep -rn
"ui-build\|ui-e2e" .github/` returns nothing).

RISK: `docs/GOAL-claims-must-be-load-bearing.md` states its own targets in stale
numbers: "binding_debt=0 holds for all 330 declared invariants" (today 421),
"236 claims assert a security control and name nothing" (today 206), and "Eleven
gates now run in `make python-quality`" (today 18 prerequisites)
([`docs/GOAL-claims-must-be-load-bearing.md:51`](../../../docs/GOAL-claims-must-be-load-bearing.md) `"holds for all 330 declared invariants"`).

RISK: The order-binding waiver file's own header counts are wrong by a factor of
one and a half. It says "102 binding directives, 55 bound, 47 recorded here"
([`docs/refactoring/order-binding-exemptions.json:15`](../../../docs/refactoring/order-binding-exemptions.json) `"So: 102 binding directives, 55 bound, 47 recorded here"`); the tree holds 163
directives and 15 waived entries. The gate derives its own numbers, so nothing
goes red, but the file that waives court orders misstates the debt it manages.

RISK: The waiver key namespace collides across courts. The key is
`id.split("BOLTRIG-")[-1]` plus the directive id
([`scripts/check_order_directives.py:236`](../../../scripts/check_order_directives.py) `short = order["id"].split("BOLTRIG-")[-1]`), so the appellate
`2026-VJS-CA-BOLTRIG-CODEX-APPROVAL-ROUTING-001` and the county
`2026-VJS-CC-BOLTRIG-CODEX-APPROVAL-ROUTING-001` share the prefix
`CODEX-APPROVAL-ROUTING-001`. Today they use disjoint directive letters (A1-A3
versus D1-D6), so no waiver is currently ambiguous; a future county `A1` would
silently inherit an appellate waiver.

RISK: An order's `implementation_status` is read by nothing. Five orders are
`OPEN`, fifteen declare no status at all, and `check_order_directives.py` reads
only `id`, `status`, `citation` and directive ids
([`scripts/check_order_directives.py:93`](../../../scripts/check_order_directives.py) `order = {"id": "", "status": "", "citation": "", "directives": []}`).
A discharged order and an untouched one are indistinguishable to the gate.

RISK: The decision record is a documentation convention with no mechanism. 42
files, two duplicate numbers (0023, 0030), one number never issued (0005), one
file with no status field, and no gate, template or index (bounded: `ls
docs/decisions | grep -iE "readme|template|index"` returns nothing).

RISK: A declared exemption in the vacuous-green sweep gives a factually wrong
reason. `check_user_authority.py` is exempted as reading "live GitHub org state
over the network"
([`scripts/check_no_vacuous_greens.py:56`](../../../scripts/check_no_vacuous_greens.py) `"reads live GitHub org state over the network"`); it reads a Postgres DSN with
asyncpg ([`scripts/check_user_authority.py:57`](../../../scripts/check_user_authority.py) `"import asyncpg # imported here so --help works"`). The exemption is still
defensible on other grounds, but the checkable claim in it is false.

RISK: The vacuous-green sweep's own adoption figures are stale. It states
"5 of 18" gates use `scan_guard` twice
([`scripts/check_no_vacuous_greens.py:175`](../../../scripts/check_no_vacuous_greens.py) `"Only 5 of 18 gates use scan_guard"`); measured, six gates import
`require_scanned` and the sweep enumerates 20.

RISK: Two ratchets are one-directional where a third is not. A fall in the
unreachable count or the claim residue prints a note and passes
([`scripts/check_reachability.py:229`](../../../scripts/check_reachability.py) `"if len(unreachable) < baseline:"`), so a stale-high baseline can bank slack
indefinitely, while `check_structure.py` treats the identical condition as a
failure.

RISK: `.trivyignore.yaml` carries an acceptance that expired nine days before the
referent commit ([`.trivyignore.yaml:26`](../../../.trivyignore.yaml) `"expired_at: 2026-08-15"`), covering `AVD-DS-0002` on
`apps/worker/Dockerfile`. Whether `make iac-scan` is currently red on it depends
on whether the finding still exists; that cannot be settled without running the
pinned scanner, which this document does not do.

RISK: The VDS proof corpus is mostly not evidence, and nothing in the Python gate
family reads it. 794 proofs: 282 `failed`, 125 `passed`, 387 `vacuous`. Six of
the fifteen proof kinds (`burndown`, `geometry`, `prohibition`,
`retirement_drain`, `states`, `token_pin`) have never once passed and are 100
percent vacuous; `composition` is 51 failed and 0 passed. A vacuous run is
expressly refused as warrant evidence by the specification the proofs cite
([`.vds/proofs/PROOF-20260814-190600.yaml:14`](../../../.vds/proofs/PROOF-20260814-190600.yaml) `"VDS S-7(2)(4) refuses a vacuous run as warrant evidence"`).

RISK: The VDS proofs are ten days older than the ledgers they sit beside. The
newest proof is `PROOF-20260814-190603`; `.vds/ledgers/screens.yaml` was
generated `2026-08-22T18:31:54Z` and `routes.yaml` `2026-08-22T16:31:51Z`. Only
the ledgers are gated (`make vds-ledgers`); the proofs are not, so the design
record's own evidence can age arbitrarily behind the source it describes.

RISK: `.vds` pins no design authority. `designpack = "none@0"` and
`designpack.lock` records `designpack_id: none`, so `token_pin`, `geometry` and
`prohibition` have no thresholds to measure against, which is precisely why they
are vacuous.

RISK: A phased-plan document states that the visual-evidence assertion runs in no
CI workflow ([`docs/PROGRAM-2026-08-18-phased-plan.md:139`](../../../docs/PROGRAM-2026-08-18-phased-plan.md) `"and no CI workflow runs it. The recapture is a"`). The make TARGET is indeed
absent from CI, but the vitest it wraps,
`apps/worker/tests/visual/manifest.test.ts`, matches vitest's default include and
is executed by `pnpm run test` inside `make worker-quality`, which CI's
`worker-build` job does run ([`Makefile:244`](../../../Makefile) `"cd apps/worker && $(PNPM) run test"`). If that reading is right, a stale
receipt is a merge blocker and the document says it is not.

RISK: An unbound-but-load-bearing surface remains by design and is written down:
`UI-TEST-HARNESS-001:D1/D2/D3` records that "the Worker has NO browser smoke test
at all today, and no playwright config or dependency"
([`docs/refactoring/order-binding-exemptions.json:84`](../../../docs/refactoring/order-binding-exemptions.json) `"the Worker has NO browser smoke test at all today"`). Nothing end-to-end
asserts that a built image answers a chat turn.

RISK: `scripts/govern.py` drives a HIGH-consequence verb to completion including
answering its own approval. It is honest about the exemption it reports
([`scripts/govern.py:134`](../../../scripts/govern.py) `"approved under the SOLE-AUTHOR EXEMPTION - nobody independent"`), but it is
wired into no Makefile target and no test, and the only record of it is
`.vjs/permits/PERMIT-1785316217.yaml`, whose scope is that one path.

## 12. OPEN QUESTIONS

1. **Is `make iac-scan` red today on the expired `AVD-DS-0002` acceptance?**
   Settled by running the pinned `aquasec/trivy:0.72.0` config scan against the
   tree, which this document is forbidden to do.

2. **Is the pre-push hook armed on the machine that currently holds the pen?**
   `core.hooksPath` is unset in this checkout; the phased plan says it is unset on
   the beelink and deliberately so as of 2026-08-18. Settled by `git config --get
   core.hooksPath` on each working clone.

3. **Is `apps/worker/tests/visual/manifest.test.ts` currently green?**
   Its source-digest assertion at line 1048 recomputes a `git ls-files` digest
   over `apps/worker/src` and `apps/worker/tests/visual`. Settled by running
   `make visual-evidence`, or by reading the `worker-build` job on the referent
   commit.

4. **Are the six `K-*` ids declared here the same six the doctrine's Appendix A
   defines?** The doctrine repository is not present in any form. Settled only by
   reading `agent-kernel-doctrine`
   `volume-1-the-rust-kernel/appendices/appendix-A-invariant-catalog.md`.

5. **Which of the two 0030 decisions is the real 0030, and does either supersede
   the other?** Both are dated 2026-08-18 and both are accepted; neither names the
   other. Settled by the author, or by a renumbering decision.

6. **Are the 5 `OPEN` orders open in fact, or merely unannotated?** Their
   directives are bound or waived, which is all the gate asks. Settled by reading
   each order's `source_opinion` under `docs/vjs/`, which is outside this area's
   scope.

7. **Does `enforce_admins` remain false on `main`?** Both governance documents say
   so and record the condition precedent for tightening it as met. The setting
   lives on GitHub and nothing in the tree can read it. Settled by
   `gh api /repos/wlilley93/boltrig/branches/main/protection`.

8. **Why do 387 of 794 VDS proofs remain vacuous eight months into the
   programme?** The proofs say the honest answer is that no bound is declared.
   Whether that is a decision or a gap is a question for the VDS record, not for
   this repository's gates.

## 13. Requirements

Note on the register. The BT-REQ-2000 to BT-REQ-2099 block was written into
`docs/brownfield-spec/registers/requirements.tsv` from an earlier draft of this table,
before its citations were repaired. Ids, statements, statuses and invariant bindings are
byte-identical between the two; 29 of the 100 evidence cells differ, because their line
numbers or anchors were corrected here afterwards. This table is the authoritative copy
of the evidence column. The block was not appended a second time, because the register is
append-only and a duplicate id block would be permanent.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-2000 | Every `scripts/check_*.py` is invoked by at least one Makefile recipe, and an orphan fails the gate-coverage gate. | IMPLEMENTED | `scripts/check_gate_coverage.py:266` `.glob("check_*.py")):` | NFR-MNT-04 |
| BT-REQ-2001 | Every one of the eight `make quality` prerequisites is invoked, directly or transitively, by a CI workflow `run:` line. | IMPLEMENTED | [`scripts/check_gate_coverage.py:331`](../../../scripts/check_gate_coverage.py) `"UNCOVERED `{RELEASE_GATE_TARGET}` components"` | NFR-MNT-04 |
| BT-REQ-2002 | All six compose manifests in the tree are `-f` inputs to a `docker compose config` step in the Makefile. | IMPLEMENTED | `scripts/check_gate_coverage.py:160` `"compose manifests under deploy/"` | NFR-MNT-04 |
| BT-REQ-2003 | `make python-quality` runs eighteen gate prerequisites and is the aggregate CI's `test-and-gate` job invokes. | IMPLEMENTED | `Makefile:228` "python-quality: invariants lint architecture structure vds-ledgers" | NFR-MNT-04 |
| BT-REQ-2004 | `make check` is a local subset that omits seven `python-quality` targets and is invoked by no workflow. | IMPLEMENTED-UNTESTED | `Makefile:223` "NOT what CI enforces - CI runs `python-quality`" | - |
| BT-REQ-2005 | `continuity-projection` and `codex-pin-health` run only in the pre-push hook and in no CI job. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:159` `run_gate "codex pin health" codex-pin-health` | - |
| BT-REQ-2006 | `scripts/check_brand_core.sh` and `scripts/check_familiar_shader.sh` are invoked by no Makefile target, hook or workflow. | DEAD | [`scripts/check_brand_core.sh:21`](../../../scripts/check_brand_core.sh) `"WIRED TO NOTHING, ON PURPOSE."` | - |
| BT-REQ-2007 | The orphan-gate census cannot see a shell gate, because its glob matches only `check_*.py`. | IMPLEMENTED | `scripts/check_gate_coverage.py:266` `for path in sorted((ROOT / "scripts").glob("check_*.py")):` | NFR-MNT-04 |
| BT-REQ-2008 | No gate asserts that the pre-push hook covers what CI runs. | SCAFFOLDED | [`docs/CI-RED-2026-08-14.md:440`](../../../docs/CI-RED-2026-08-14.md) `"No gate asserts the hook covers CI"` | - |
| BT-REQ-2009 | The pre-push hook is installed by nothing; `core.hooksPath` must be set by hand per clone. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:81` "Install: git config core.hooksPath .githooks" | - |
| BT-REQ-2010 | The pre-push hook blocks the push outright when `core.hooksPath` is absolute. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:100` "core.hooksPath is ABSOLUTE ($hooks_path)" | - |
| BT-REQ-2011 | `SKIP_PUSH_GATES=1` skips every pre-push gate and `SKIP_QUALITY_GATE=1` skips only the Python suite, each announced on stdout. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:85` `if [[ "${SKIP_PUSH_GATES:-}" == "1" ]]; then` | - |
| BT-REQ-2012 | A pre-push gate refused for lack of memory (exit 75) is reported as not-run, never as failed, and still blocks the push. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:147` "Nothing was tested, so nothing failed" | - |
| BT-REQ-2013 | The absence of the machine-wide heavy-job guard is announced and the gates continue unguarded. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:126` "gates run UNGUARDED" | - |
| BT-REQ-2014 | On macOS the pre-push Python suite runs inside a Linux VM through one line of dispatch around the same make target CI runs. | IMPLEMENTED-UNTESTED | `scripts/quality-gate.sh:107` `exec orb -m "$VM" bash -lc` | - |
| BT-REQ-2015 | The merge-drift check fetches the base ref first and reports a failed fetch as evidence of nothing. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:214` "possibly stale ref, so its silence is not evidence of anything" | - |
| BT-REQ-2016 | The pre-push hook prints, on a green pass, the six CI jobs and three `test-and-gate` steps it did not run. | IMPLEMENTED-UNTESTED | `.githooks/pre-push:248` "the gates ABOVE are green. NOT run here, and NOT predicted by this" | - |
| BT-REQ-2017 | The invariant catalogue declares 421 unique ids at the referent commit, with zero duplicates. | IMPLEMENTED | [`tests/invariants.yaml:23`](../../../tests/invariants.yaml) `"invariants:"` (measured by re-parsing the file read-only) | NFR-MNT-02 |
| BT-REQ-2018 | A repeated invariant id raises rather than resolving last-wins, because a duplicate silently evicted SEC-169 for four months. | IMPLEMENTED | [`scripts/check_invariants.py:120`](../../../scripts/check_invariants.py) `"duplicate invariant id {current!r} in"` | NFR-MNT-02 |
| BT-REQ-2019 | Binding debt is zero: no declared invariant is unbound and no marker is undeclared. | IMPLEMENTED | [`scripts/check_invariants.py:232`](../../../scripts/check_invariants.py) `"RESULT: FAIL - binding debt must be zero (and may only decrease)."` | NFR-MNT-02 |
| BT-REQ-2020 | The catalogue also fails on drift: a claimed node id that no marker backs, or a `service_gated` id outside that invariant's own tests. | IMPLEMENTED | [`scripts/check_invariants.py:168`](../../../scripts/check_invariants.py) `"claims {claimed} but no such marker exists"` | NFR-MNT-02 |
| BT-REQ-2021 | The catalogue may omit a real marker-backed binding without failing; 361 of 1836 real pairs are undeclared. | IMPLEMENTED | `scripts/check_invariants.py:166` `for claimed in meta["tests"]:` (one-directional drift check) | - |
| BT-REQ-2022 | An invariant whose every binding is `service_gated` reports GATED, never ok, so a permanently skipped test cannot discharge it. | IMPLEMENTED | `scripts/check_invariants.py:190` `status = "GATED"` | NFR-MNT-02 |
| BT-REQ-2023 | Exactly six `K-*` ids and one `P*` id are declared; the other 414 invariants are Boltrig-local. | IMPLEMENTED | [`tests/invariants.yaml:786`](../../../tests/invariants.yaml) `"K-2:"` (measured across the whole file) | - |
| BT-REQ-2024 | The canonical source of the `K-*` ids is an external repository that is present nowhere in this tree. | SEAM | `tests/invariants.yaml:18` "below is the canonical invariant id from" (external repo `agent-kernel-doctrine`) | - |
| BT-REQ-2025 | The gate is named after K-29 and K-30, neither of which the catalogue declares. | IMPLEMENTED | `Makefile:474` "The K-29/K-30 binding gate: every claimed invariant must have a test" | - |
| BT-REQ-2026 | `docs/invariants.md` documents 171 of the 421 declared ids and states a stale declared count of 390. | IMPLEMENTED-UNTESTED | [`docs/invariants.md:15`](../../../docs/invariants.md) `"Today: **390 declared, debt 0** (1661 bound"` | - |
| BT-REQ-2027 | The `invariant(id)` marker is registered in pyproject so an unknown marker is not silently ignored. | IMPLEMENTED | [`pyproject.toml:143`](../../../pyproject.toml) `"invariant(id): a binding invariant (P-/SEC-/K-) the test covers"` | - |
| BT-REQ-2028 | `docs/claim-inventory.tsv` must regenerate byte-identically from the sources or the gate fails. | IMPLEMENTED | [`scripts/check_claim_inventory.py:66`](../../../scripts/check_claim_inventory.py) `"is STALE: it is not what the sources now say."` | NFR-MNT-03 |
| BT-REQ-2029 | The load-bearing no-subject residue is 206, exactly at its pinned baseline, and may only decrease. | IMPLEMENTED | [`docs/refactoring/claim-inventory-baseline.json:19`](../../../docs/refactoring/claim-inventory-baseline.json) `"\"load_bearing_no_subject\": 206,"` | NFR-MNT-03 |
| BT-REQ-2030 | A claim naming a subject nothing reaches (SUBJECT-ABSENT) fails unconditionally, regardless of the baseline. | IMPLEMENTED | [`scripts/check_claim_inventory.py:98`](../../../scripts/check_claim_inventory.py) `"the claim outlived its subject, or the"` | NFR-MNT-03 |
| BT-REQ-2031 | The Python structural ratchet is exact in both directions: growth fails and a stale-high baseline also fails. | IMPLEMENTED | [`scripts/check_structure.py:257`](../../../scripts/check_structure.py) `"baseline is stale-high: {path} is {measured} lines"` | NFR-MNT-01 |
| BT-REQ-2032 | Thirty-four Python files carry a structural exemption, each with owner, reason, ISO expiry and exact per-function baselines; none is expired at the referent commit. | IMPLEMENTED | `scripts/check_structure.py:24` `DEFAULT_CONFIG = ROOT / "docs/refactoring/structural-exemptions.json"` | NFR-MNT-01 |
| BT-REQ-2033 | The Worker structural debt catalogue is loaded from an immutable Git object supplied by the CI event, never from a second working-tree file. | IMPLEMENTED | [`.github/workflows/ci.yml:74`](../../../.github/workflows/ci.yml) `"WORKER_STRUCTURE_BASE_REF: ${{ github.event.pull_request.base.sha"` | NFR-MNT-07 |
| BT-REQ-2034 | The unreachable-function count is an upper-bound ratchet only: a fall prints a note and passes. | IMPLEMENTED | [`scripts/check_reachability.py:229`](../../../scripts/check_reachability.py) `"if len(unreachable) < baseline:"` | - |
| BT-REQ-2035 | Every declared reachability root must give a reason naming what calls it; a root with no reason fails. | IMPLEMENTED | [`scripts/check_reachability.py:214`](../../../scripts/check_reachability.py) `"RESULT: FAIL - a declared root gives no reason."` | - |
| BT-REQ-2036 | Seventeen unwired-claims waivers each carry owner, reason and expiry, and a waiver file that waives nothing it can be held to fails the gate. | IMPLEMENTED | [`scripts/check_unwired_claims.py:440`](../../../scripts/check_unwired_claims.py) `"FAIL: the waiver file waives nothing it can be held to."` | NFR-MNT-06 |
| BT-REQ-2037 | The health-claim exemption file is empty and the tests hold it that way. | IMPLEMENTED | [`scripts/check_health_claims.py:40`](../../../scripts/check_health_claims.py) `"The file is currently EMPTY, and the tests hold it that way."` | NFR-MNT-05 |
| BT-REQ-2038 | Every `name==version` pin in a dependency overrides file must appear at that same version in the compiled lock beside it. | IMPLEMENTED | [`scripts/check_override_locks.py:38`](../../../scripts/check_override_locks.py) `"PAIRS = ["` | - |
| BT-REQ-2039 | Every tree scan in `scripts/` declares a floor and fails when it finds fewer, and the sweep tests the property rather than the helper. | IMPLEMENTED | [`scripts/scan_guard.py:42`](../../../scripts/scan_guard.py) `"FAIL: scanned nothing - expected at least {minimum} {what}"` | NFR-MNT-06 |
| BT-REQ-2040 | The vacuous-green sweep runs seventeen of twenty gates against an empty tree and declares its three exemptions with reasons. | IMPLEMENTED | [`scripts/check_no_vacuous_greens.py:48`](../../../scripts/check_no_vacuous_greens.py) `"NO_EMPTY_TREE_FORM = {"` | NFR-MNT-06 |
| BT-REQ-2041 | The sweep's discriminator is the gate's success vocabulary, not its exit code, so an honest skip is not flagged. | IMPLEMENTED | [`scripts/check_no_vacuous_greens.py:106`](../../../scripts/check_no_vacuous_greens.py) `"THE DISCRIMINATOR. Exit 0 is not the test, the PASS WORD is."` | NFR-MNT-06 |
| BT-REQ-2042 | The exemption reason recorded for `check_user_authority.py` in the sweep names GitHub, while the gate reads a Postgres DSN. | IMPLEMENTED-UNTESTED | [`scripts/check_no_vacuous_greens.py:56`](../../../scripts/check_no_vacuous_greens.py) `"reads live GitHub org state over the network"` | - |
| BT-REQ-2043 | Six gate modules import `require_scanned`; the sweep's stated figure of five of eighteen is stale. | IMPLEMENTED | [`scripts/check_no_vacuous_greens.py:175`](../../../scripts/check_no_vacuous_greens.py) `"Only 5 of 18 gates use scan_guard"` | - |
| BT-REQ-2044 | Prose references resolve across five rule kinds: repo paths, pytest node ids, make targets, boltrig env vars and VJS order citations. | IMPLEMENTED | [`scripts/check_prose_references.py:32`](../../../scripts/check_prose_references.py) `"WHAT IT CHECKS. Five kinds of reference"` | NFR-MNT-03 |
| BT-REQ-2045 | Order citations resolve against a vendored citator, never a sibling checkout, so no gate can pass because of a directory on one machine. | IMPLEMENTED | [`.vjs/canon-citations.txt:9`](../../../.vjs/canon-citations.txt) `"So the citator is vendored. Refresh it deliberately with"` | NFR-MNT-03 |
| BT-REQ-2046 | A negated or past-tense clause exempts a reference in the historical record but never in live source under `boltrig/` or `scripts/`. | IMPLEMENTED | `scripts/check_prose_references.py:147` `LIVE_SOURCE_PREFIXES: tuple[str, ...] = ("boltrig/", "scripts/")` | NFR-MNT-03 |
| BT-REQ-2047 | Every repo-relative path cited in a commit `Refs:`/`See:` trailer must have existed in that commit's own tree, not at HEAD. | IMPLEMENTED | [`scripts/check_commit_trailers.py:34`](../../../scripts/check_commit_trailers.py) `"must exist in that commit's OWN tree - not at HEAD"` | - |
| BT-REQ-2048 | A commit-trailer scan that finds zero trailers fails rather than passing. | IMPLEMENTED | [`scripts/check_commit_trailers.py:190`](../../../scripts/check_commit_trailers.py) `"A scan with nothing to check is a broken scan, not a clean history."` | - |
| BT-REQ-2049 | No tracked symlink may dangle, loop, or resolve outside the repository root, and it is deliberately not a ratchet. | IMPLEMENTED | [`scripts/check_tracked_symlinks.py:33`](../../../scripts/check_tracked_symlinks.py) `"Not a ratchet, and deliberately not"` | - |
| BT-REQ-2050 | The full-history secret scan refuses to run over a partial clone rather than scanning what it can reach. | IMPLEMENTED | [`scripts/check_secret_scan_history.py:39`](../../../scripts/check_secret_scan_history.py) `"secret-scan refused: complete Git history is unavailable"` | - |
| BT-REQ-2051 | Twenty-four court orders are filed, all `status: binding`, carrying 163 directives between them. | IMPLEMENTED | `scripts/check_order_directives.py:222` `if order["status"] != "binding":` (measured across the orders directory) | NFR-MNT-03 |
| BT-REQ-2052 | A directive counts as bound only when a file under `tests/` names the directive id within two lines of a line naming its order. | IMPLEMENTED | [`scripts/check_order_directives.py:78`](../../../scripts/check_order_directives.py) `"PROXIMITY_LINES = 2"` | NFR-MNT-03 |
| BT-REQ-2053 | A directive mention in `boltrig/` is the claim, not the enforcement, and never binds. | IMPLEMENTED | [`scripts/check_order_directives.py:31`](../../../scripts/check_order_directives.py) `"strict: the mention must be in tests/, not in boltrig/"` | NFR-MNT-03 |
| BT-REQ-2054 | Fifteen court directives are waived, each with owner, reason and unexpired ISO date, and an unused waiver is itself a failure. | IMPLEMENTED | [`scripts/check_order_directives.py:257`](../../../scripts/check_order_directives.py) `"exemption names a directive that is bound or absent"` | NFR-MNT-03 |
| BT-REQ-2055 | The waiver key is the order id's tail plus the directive id, so two orders of the same name in different courts share one key namespace. | IMPLEMENTED | `scripts/check_order_directives.py:236` `short = order["id"].split("BOLTRIG-")[-1]` | - |
| BT-REQ-2056 | An order's `implementation_status` is read by no gate; five orders read OPEN and fifteen declare no status at all. | IMPLEMENTED | `scripts/check_order_directives.py:93` `order = {"id": "", "status": "", "citation": "", "directives": []}` | - |
| BT-REQ-2057 | The waiver file's own header states 102 directives and 47 entries where the tree holds 163 and 15. | IMPLEMENTED-UNTESTED | [`docs/refactoring/order-binding-exemptions.json:15`](../../../docs/refactoring/order-binding-exemptions.json) `"So: 102 binding directives, 55 bound, 47 recorded here."` | - |
| BT-REQ-2058 | The founding consolidation ruling has never existed as a file in this repository and is allow-listed rather than reconstructed. | IMPLEMENTED | [`scripts/check_prose_references.py:409`](../../../scripts/check_prose_references.py) `"has ever existed in this repository's history"` | NFR-MNT-03 |
| BT-REQ-2059 | Two further orders relied on in live code were never filed and are allow-listed with the finding recorded. | IMPLEMENTED | `scripts/check_prose_references.py:383` "WAS given and was never written" | NFR-MNT-03 |
| BT-REQ-2060 | A VJS permit is a self-issued front-door record that cannot satisfy a check reserved to the Sovereign or to a constituted bench. | IMPLEMENTED-UNTESTED | [`.vjs/permits/PERMIT-1785316217.yaml:25`](../../../.vjs/permits/PERMIT-1785316217.yaml) `"NOT an external authority''s approval"` | - |
| BT-REQ-2061 | `scripts/govern.py` drives a HIGH-consequence verb through the real kernel chokepoint and reports the sole-author exemption rather than assuming it. | IMPLEMENTED-UNTESTED | [`scripts/govern.py:134`](../../../scripts/govern.py) `"approved under the SOLE-AUTHOR EXEMPTION - nobody independent"` | - |
| BT-REQ-2062 | `docs/decisions/` holds forty-two records governed by no gate, template or index. | IMPLEMENTED-UNTESTED | [`README.md:290`](../../../README.md) `"docs/ ARCHITECTURE, invariants, DEFINITION-OF-DONE, decisions/"` | - |
| BT-REQ-2063 | Decision numbers 0023 and 0030 are each issued twice and 0005 was never issued. | IMPLEMENTED-UNTESTED | [`docs/decisions/0023-refuse-model-judged-approvals.md:1`](../../../docs/decisions/0023-refuse-model-judged-approvals.md) `"# Decision 0023: an LLM does not decide what a human was asked to decide"` | - |
| BT-REQ-2064 | Decision status is free text: one record carries no status field and at least three distinct syntaxes are in use. | IMPLEMENTED-UNTESTED | [`docs/decisions/0004-spatial-deck-frontend.md:1`](../../../docs/decisions/0004-spatial-deck-frontend.md) `"# 0004 - The spatial deck frontend"` | - |
| BT-REQ-2065 | AGENTS.md requires a first-impression decision to be surfaced but does not require it to be recorded or numbered. | IMPLEMENTED-UNTESTED | `AGENTS.md:81` "make the call, note it. First-impression" | - |
| BT-REQ-2066 | `.vds/config.toml` is the single VDS anchor and holds paths, globs and governance only, never a design value. | IMPLEMENTED-UNTESTED | [`.vds/config.toml:2`](../../../.vds/config.toml) `"This file holds NO design value (VDS S-2(2))"` | NFR-MNT-08 |
| BT-REQ-2067 | The VDS ledger gate verifies ownership, digests, JSX coordinates and route-manifest drift, and makes no visual verdict. | IMPLEMENTED | [`scripts/check_vds_ledgers.py:9`](../../../scripts/check_vds_ledgers.py) `"This check deliberately makes no visual verdict."` | NFR-MNT-08 |
| BT-REQ-2068 | The VDS ledger gate floors its scans at ten screen files and six routes so an empty scan cannot pass. | IMPLEMENTED | [`scripts/check_vds_ledgers.py:44`](../../../scripts/check_vds_ledgers.py) `"MIN_SCREEN_FILES = 10"` | NFR-MNT-08 |
| BT-REQ-2069 | The 794 committed VDS proofs are 282 failed, 125 passed and 387 vacuous, and no Python gate reads them. | IMPLEMENTED-UNTESTED | [`.vds/proofs/PROOF-20260814-190600.yaml:3`](../../../.vds/proofs/PROOF-20260814-190600.yaml) `"status: vacuous"` | - |
| BT-REQ-2070 | Six VDS proof kinds have never passed and are entirely vacuous because no bound is declared for them. | IMPLEMENTED-UNTESTED | [`.vds/proofs/PROOF-20260814-190600.yaml:14`](../../../.vds/proofs/PROOF-20260814-190600.yaml) `"no geometry bound is declared, so every row is skipped"` | - |
| BT-REQ-2071 | The VDS designpack is pinned to `none@0`, so no external design authority is bound. | IMPLEMENTED-UNTESTED | `.vds/config.toml:6` `designpack = "none@0"` | - |
| BT-REQ-2072 | `ci.yml` declares six jobs that expand to eight runs, collapsed into one required `quality` context that asserts five successes. | IMPLEMENTED-UNTESTED | `.github/workflows/ci.yml:237` `test "${{ needs.test-and-gate.result }}" = success` | - |
| BT-REQ-2073 | `security.yml` declares four jobs that expand to nine runs, collapsed into one required `Security gate` context that asserts three successes. | IMPLEMENTED-UNTESTED | `.github/workflows/security.yml:186` `test "$SOURCE_RESULT" = success` | - |
| BT-REQ-2074 | `security.yml` never cancels an in-progress run on `main`, because a cancelled required check leaves the ref with no successful evidence. | IMPLEMENTED-UNTESTED | [`.github/workflows/security.yml:28`](../../../.github/workflows/security.yml) `"cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}"` | - |
| BT-REQ-2075 | Both aggregator jobs use `if: always()` so a skipped or cancelled dependency fails the context rather than skipping it. | IMPLEMENTED-UNTESTED | [`.github/workflows/ci.yml:226`](../../../.github/workflows/ci.yml) `"if: ${{ always() }}"` | - |
| BT-REQ-2076 | The `test-and-gate` job checks out full history because the commit-trailer gate reads commit messages. | IMPLEMENTED-UNTESTED | [`.github/workflows/ci.yml:47`](../../../.github/workflows/ci.yml) `"fetch-depth: 0"` | - |
| BT-REQ-2077 | CI runs the Python suite against a real pgvector Postgres so the durable-store legs execute rather than skip. | IMPLEMENTED-UNTESTED | [`.github/workflows/ci.yml:27`](../../../.github/workflows/ci.yml) `"image: pgvector/pgvector:pg16@sha256:"` | - |
| BT-REQ-2078 | A pytest run whose Postgres or fakeredis precondition is unmet ends non-zero unless a named opt-out is set. | IMPLEMENTED | [`tests/conftest.py:171`](../../../tests/conftest.py) `"session.exitstatus = pytest.ExitCode.TESTS_FAILED"` | - |
| BT-REQ-2079 | Every product-behaviour environment variable is stripped for the duration of every test, with an eleven-entry keep-list for test selection only. | IMPLEMENTED | [`tests/conftest.py:196`](../../../tests/conftest.py) `"_ENV_STRIP_PREFIXES = ("` | - |
| BT-REQ-2080 | `make gate-status` reports a commit with no completed run as unproven, never as green. | IMPLEMENTED-UNTESTED | [`scripts/gate-status.sh:80`](../../../scripts/gate-status.sh) `"has NO completed run - unproven, not green"` | - |
| BT-REQ-2081 | `gate-status` filters to push-event runs and groups by workflow name, so a Dependabot failure cannot colour the verdict. | IMPLEMENTED-UNTESTED | [`scripts/gate-status.sh:64`](../../../scripts/gate-status.sh) `"So: filter to `push` (the event branch protection gates)"` | - |
| BT-REQ-2082 | The release preflight requires the latest `ci.yml` and `security.yml` runs for the exact release commit to be completed and successful. | IMPLEMENTED-UNTESTED | [`.github/workflows/release.yml:188`](../../../.github/workflows/release.yml) `"require_successful_workflow ci.yml 'ci / quality'"` | - |
| BT-REQ-2083 | The release preflight requires the tagged commit to be an ancestor of the default branch before anything is built. | IMPLEMENTED-UNTESTED | `.github/workflows/release.yml:152` `git merge-base --is-ancestor "$release_commit" "origin/$DEFAULT_BRANCH"` | - |
| BT-REQ-2084 | Branch protection requires the contexts `quality` and `Security gate` with `enforce_admins` false, so the sole admin retains a bypass. | IMPLEMENTED-UNTESTED | [`docs/security-gates.md:15`](../../../docs/security-gates.md) `"`enforce_admins` is FALSE, so the sole admin retains a bypass."` | - |
| BT-REQ-2085 | GitHub Actions execute for this repository; the estate-wide private-repo billing block does not apply to it. | IMPLEMENTED-UNTESTED | `docs/security-conformance.md:26` `the earlier "GitHub Actions is billing-blocked" note was stale` | - |
| BT-REQ-2086 | `docs/security-gates.md` contradicts itself on the required context names, recommending the `ci / quality` form it earlier refutes. | IMPLEMENTED-UNTESTED | [`docs/security-gates.md:97`](../../../docs/security-gates.md) `"require the `ci / quality` and"` | - |
| BT-REQ-2087 | `docs/security-conformance.md` still records required branch-protection checks as an open seam and still carries the retired Pi runtime family. | IMPLEMENTED-UNTESTED | [`docs/security-conformance.md:42`](../../../docs/security-conformance.md) `"making the gates REQUIRED in branch protection - all ops"` | FR-RUN-21 |
| BT-REQ-2088 | `docs/GOAL-trustworthy-gate.md` states its done-criterion against `ui-build` and `ui-e2e`, jobs no workflow declares. | IMPLEMENTED-UNTESTED | [`docs/GOAL-trustworthy-gate.md:25`](../../../docs/GOAL-trustworthy-gate.md) `"`test-and-gate`, `ui-build`, `ui-e2e`, `site-build-test-lint`"` | - |
| BT-REQ-2089 | `docs/GOAL-claims-must-be-load-bearing.md` states 330 declared invariants, 236 residue claims and eleven python-quality gates, all stale. | IMPLEMENTED-UNTESTED | [`docs/GOAL-claims-must-be-load-bearing.md:51`](../../../docs/GOAL-claims-must-be-load-bearing.md) `"holds for all 330 declared invariants"` | - |
| BT-REQ-2090 | One `.trivyignore.yaml` acceptance expired nine days before the referent commit. | IMPLEMENTED-UNTESTED | [`.trivyignore.yaml:26`](../../../.trivyignore.yaml) `"expired_at: 2026-08-15"` | - |
| BT-REQ-2091 | Trivy's vulnerability legs honour `.trivyignore.yaml` explicitly, because without the flag the file is consulted only for misconfigurations. | IMPLEMENTED-UNTESTED | [`.github/workflows/security.yml:170`](../../../.github/workflows/security.yml) `"trivyignores: .trivyignore.yaml"` | - |
| BT-REQ-2092 | The Python audit runs through a wrapper that enforces the expiry on the accepted-advisory ledger and prints what it suppresses. | IMPLEMENTED-UNTESTED | `Makefile:363` "$(PY) scripts/python_audit.py requirements-lock.txt" | - |
| BT-REQ-2093 | `make visual-evidence` runs the existing vitest rather than recomputing the digest, so a second implementation cannot drift from the receipt. | IMPLEMENTED-UNTESTED | `Makefile:131` "cd apps/worker && $(PNPM) exec vitest run tests/visual/manifest.test.ts" | - |
| BT-REQ-2094 | `check_continuity_projection.py` fixes the four continuity frozensets to the sets a court order settled, and a change to the table is a change to the order. | IMPLEMENTED | `scripts/check_continuity_projection.py:41` "Fixed by the order's disposition" | - |
| BT-REQ-2095 | `check_codex_pin_health.py` is fatal only when `BOLTRIG_CODEX_BINARY` is set, and never fatal on version drift. | IMPLEMENTED-UNTESTED | [`scripts/check_codex_pin_health.py:33`](../../../scripts/check_codex_pin_health.py) `"NEVER FATAL: version drift between the pin"` | - |
| BT-REQ-2096 | The Codex protocol pin is checked in as exact constants: version, target, binary digest, schema digest, bundle file count and admitted transports. | IMPLEMENTED | `scripts/check_codex_protocol.py:24` `PIN_BINARY_SHA256 = "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b"` | FR-RUN-19 |
| BT-REQ-2097 | The two cross-repo drift gates exit 2 with NOT CHECKED when the upstream tree is absent, rather than reporting an agreement they did not observe. | IMPLEMENTED-UNTESTED | [`scripts/check_familiar_shader.sh:12`](../../../scripts/check_familiar_shader.sh) `"cannot be found, this says NOT CHECKED and exits non-zero"` | - |
| BT-REQ-2098 | `check_user_authority.py` and `check_fleet_drift.py` are operator tools declared not to be CI gates, each needing a live tenant or a live box. | IMPLEMENTED-UNTESTED | `Makefile:161` "user-authority: ## Does EVERY active user resolve to usable authority? (needs a tenant DSN; not a CI gate)" | - |
| BT-REQ-2099 | Three gates are bound by neither an invariant test nor a selftest: `check_codex_pin_health.py` and the two shell drift gates. | IMPLEMENTED-UNTESTED | `Makefile:121` "codex-pin-health: ## The pinned Codex binary must be present, matching and not group-writable" | - |
