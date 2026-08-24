# Risks harvested from SPEC-20-governance-and-gates.md

RISK: The pre-push gate is armed by nothing. `core.hooksPath` is unset in this
checkout and no target, script or bootstrap sets it, so the whole local layer is
opt-in per clone ([`.githooks/pre-push:81`](../../../.githooks/pre-push)
`"Install: git config core.hooksPath .githooks"`; bounded:
`grep -n hooksPath genesis.sh scripts/dev-up.sh Makefile` returns nothing).

---

RISK: The Makefile tells the reader the hook runs, in the clone where it does
not. `check`'s help says "or just push - the pre-push hook runs it"
([`Makefile:223`](../../../Makefile) `"or just push - the pre-push hook runs
it"`), and a phased-plan document records the opposite for the box holding the
pen ([`docs/PROGRAM-2026-08-18-phased-plan.md:154`](../../../docs/PROGRAM-2026-08-18-phased-plan.md) `"is unset in the beelink clone and"`).

---

RISK: Two gates make a false claim about their own wiring, which is the exact
defect class they belong to. `check_continuity_projection.py` ends "Wired into
`make check`, whose target list is the one CI runs"
([`scripts/check_continuity_projection.py:30`](../../../scripts/check_continuity_projection.py) `"Wired into `make check`, whose target list is the one CI runs."`) and
`check_codex_pin_health.py` ends "Wired into `make check`"
([`scripts/check_codex_pin_health.py:44`](../../../scripts/check_codex_pin_health.py) `"Exit 0 clean, 1 on a fatal condition. Wired into `make check`."`). Neither
target is a prerequisite of `quality` or `python-quality`, and no workflow `run:`
line names either. They run only in the pre-push hook, which is unarmed here.

---

RISK: The orphan-gate census is blind to shell gates. It globs `check_*.py`
([`scripts/check_gate_coverage.py:266`](../../../scripts/check_gate_coverage.py) `glob("check_*.py")`), so `check_brand_core.sh` and
`check_familiar_shader.sh` could become orphaned, or already be orphaned, without
any gate noticing. Both are in fact unwired, one of them on purpose and saying so
([`scripts/check_brand_core.sh:21`](../../../scripts/check_brand_core.sh) `"WIRED TO NOTHING, ON PURPOSE."`), the other silently.

---

RISK: No gate asserts the pre-push hook covers CI, and the debt is written down.
[`docs/CI-RED-2026-08-14.md:440`](../../../docs/CI-RED-2026-08-14.md) `"No gate asserts the hook covers CI"` proposes the converse direction for
`check_gate_coverage.py`; it is not implemented (bounded: the module has three
checks, `compose_validation_inputs`, `resolve_coverage` and
`unwired_check_scripts`, and no reference to `.githooks` anywhere in
`scripts/`).

---

RISK: The invariant catalogue may under-declare its own bindings without failing.
361 of 1836 real marker-backed (id, node) pairs are absent from the catalogue's
`tests:` lists, because drift is only checked catalogue-to-marker
([`scripts/check_invariants.py:168`](../../../scripts/check_invariants.py) `"claims {claimed} but no such marker exists"`). Deleting an undeclared binding
turns nothing red.

---

RISK: The gate that names itself after K-29 and K-30 declares neither. The
Makefile calls it "The K-29/K-30 binding gate"
([`Makefile:474`](../../../Makefile) `"The K-29/K-30 binding gate: every claimed
invariant must have a test"`), [`.github/workflows/ci.yml:2`](../../../.github/workflows/ci.yml) `"The binding-invariant gate (K-29/K-30)"` and
[`boltrig/api/cli.py:10`](../../../boltrig/api/cli.py) `"run the invariant-binding gate (K-29/K-30)"` repeat it, and
`grep -cE '^  K-(29|30):' tests/invariants.yaml` returns 0. Only six `K-*`
ids are declared at all.

---

RISK: The founding ruling that makes all of this binding has never existed as a
file. `check_prose_references.py` allow-lists
`[2026] VJS-CC NANKLE-CONSOLIDATION 001` with the reason that "No file matching it
has ever existed in this repository's history"
([`scripts/check_prose_references.py:409`](../../../scripts/check_prose_references.py) `"has ever existed in this repository's history"`), while [`README.md:72`](../../../README.md) `"VJS-CC NANKLE-CONSOLIDATION 001"`
cites it as the authority for Boltrig's separate existence, and
[`tests/invariants.yaml:18`](../../../tests/invariants.yaml) `"below is the canonical invariant id from"` cites its directive D2
as the canonical source of every `K-*` id.

---

RISK: Two further orders are relied on in live code and were never filed, both
allow-listed rather than reconstructed:
`[2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001` and
`[2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001`
([`scripts/check_prose_references.py:383`](../../../scripts/check_prose_references.py) `"WAS given and was never written"`). The first is the authority
for the branch protection currently in force.

---

RISK: `docs/invariants.md` states a declared count of 390 and 1661 bound node ids
([`docs/invariants.md:15`](../../../docs/invariants.md) `"Today: **390 declared, debt 0** (1661 bound"`); measured today, 421 and 1836. The document hedges the
line as prose, and nothing checks it.

---

RISK: `docs/security-gates.md` contradicts itself about the required check names.
Lines 4 to 7 say the contexts are `quality` and `Security gate` and that the
`ci / quality` form "no check run publishes"; line 97 then instructs the reader to
"require the `ci / quality` and `security / Security gate` checks on `main`"
([`docs/security-gates.md:97`](../../../docs/security-gates.md) `"require the `ci / quality` and"`).

---

RISK: `docs/security-conformance.md` still records the CI/CD family's residue as
"making the gates REQUIRED in branch protection"
([`docs/security-conformance.md:42`](../../../docs/security-conformance.md) `"making the gates REQUIRED in branch protection - all ops"`) while
[`docs/security-gates.md:3`](../../../docs/security-gates.md) `"and as of 2026-07-25 they ARE"` records that they have
been required since 2026-07-25.
The same document carries a live `PI` runtime family
([`docs/security-conformance.md:34`](../../../docs/security-conformance.md) `"the real Pi loop replaces the stand-in"`) for a lane retired by decision 0020
and declared inert by invariant `FR-RUN-21`.

---

RISK: `docs/GOAL-trustworthy-gate.md` declares itself MET against a job list that
no longer exists. Its criterion 1 names `ui-build` and `ui-e2e`
([`docs/GOAL-trustworthy-gate.md:25`](../../../docs/GOAL-trustworthy-gate.md) `"`test-and-gate`, `ui-build`, `ui-e2e`, `site-build-test-lint`"`), and
neither string appears anywhere under `.github/` (bounded: `grep -rn
"ui-build\|ui-e2e" .github/` returns nothing).

---

RISK: `docs/GOAL-claims-must-be-load-bearing.md` states its own targets in stale
numbers: "binding_debt=0 holds for all 330 declared invariants" (today 421),
"236 claims assert a security control and name nothing" (today 206), and "Eleven
gates now run in `make python-quality`" (today 18 prerequisites)
([`docs/GOAL-claims-must-be-load-bearing.md:51`](../../../docs/GOAL-claims-must-be-load-bearing.md) `"holds for all 330 declared invariants"`).

---

RISK: The order-binding waiver file's own header counts are wrong by a factor of
one and a half. It says "102 binding directives, 55 bound, 47 recorded here"
([`docs/refactoring/order-binding-exemptions.json:15`](../../../docs/refactoring/order-binding-exemptions.json) `"So: 102 binding directives, 55 bound, 47 recorded here"`); the tree holds 163
directives and 15 waived entries. The gate derives its own numbers, so nothing
goes red, but the file that waives court orders misstates the debt it manages.

---

RISK: The waiver key namespace collides across courts. The key is
`id.split("BOLTRIG-")[-1]` plus the directive id
([`scripts/check_order_directives.py:236`](../../../scripts/check_order_directives.py) `short = order["id"].split("BOLTRIG-")[-1]`), so the appellate
`2026-VJS-CA-BOLTRIG-CODEX-APPROVAL-ROUTING-001` and the county
`2026-VJS-CC-BOLTRIG-CODEX-APPROVAL-ROUTING-001` share the prefix
`CODEX-APPROVAL-ROUTING-001`. Today they use disjoint directive letters (A1-A3
versus D1-D6), so no waiver is currently ambiguous; a future county `A1` would
silently inherit an appellate waiver.

---

RISK: An order's `implementation_status` is read by nothing. Five orders are
`OPEN`, fifteen declare no status at all, and `check_order_directives.py` reads
only `id`, `status`, `citation` and directive ids
([`scripts/check_order_directives.py:93`](../../../scripts/check_order_directives.py) `order = {"id": "", "status": "", "citation": "", "directives": []}`).
A discharged order and an untouched one are indistinguishable to the gate.

---

RISK: The decision record is a documentation convention with no mechanism. 42
files, two duplicate numbers (0023, 0030), one number never issued (0005), one
file with no status field, and no gate, template or index (bounded: `ls
docs/decisions | grep -iE "readme|template|index"` returns nothing).

---

RISK: A declared exemption in the vacuous-green sweep gives a factually wrong
reason. `check_user_authority.py` is exempted as reading "live GitHub org state
over the network"
([`scripts/check_no_vacuous_greens.py:56`](../../../scripts/check_no_vacuous_greens.py) `"reads live GitHub org state over the network"`); it reads a Postgres DSN with
asyncpg ([`scripts/check_user_authority.py:57`](../../../scripts/check_user_authority.py) `"import asyncpg # imported here so --help works"`). The exemption is still
defensible on other grounds, but the checkable claim in it is false.

---

RISK: The vacuous-green sweep's own adoption figures are stale. It states
"5 of 18" gates use `scan_guard` twice
([`scripts/check_no_vacuous_greens.py:175`](../../../scripts/check_no_vacuous_greens.py) `"Only 5 of 18 gates use scan_guard"`); measured, six gates import
`require_scanned` and the sweep enumerates 20.

---

RISK: Two ratchets are one-directional where a third is not. A fall in the
unreachable count or the claim residue prints a note and passes
([`scripts/check_reachability.py:229`](../../../scripts/check_reachability.py) `"if len(unreachable) < baseline:"`), so a stale-high baseline can bank slack
indefinitely, while `check_structure.py` treats the identical condition as a
failure.

---

RISK: `.trivyignore.yaml` carries an acceptance that expired nine days before the
referent commit ([`.trivyignore.yaml:26`](../../../.trivyignore.yaml) `"expired_at: 2026-08-15"`), covering `AVD-DS-0002` on
`apps/worker/Dockerfile`. Whether `make iac-scan` is currently red on it depends
on whether the finding still exists; that cannot be settled without running the
pinned scanner, which this document does not do.

---

RISK: The VDS proof corpus is mostly not evidence, and nothing in the Python gate
family reads it. 794 proofs: 282 `failed`, 125 `passed`, 387 `vacuous`. Six of
the fifteen proof kinds (`burndown`, `geometry`, `prohibition`,
`retirement_drain`, `states`, `token_pin`) have never once passed and are 100
percent vacuous; `composition` is 51 failed and 0 passed. A vacuous run is
expressly refused as warrant evidence by the specification the proofs cite
([`.vds/proofs/PROOF-20260814-190600.yaml:14`](../../../.vds/proofs/PROOF-20260814-190600.yaml) `"VDS S-7(2)(4) refuses a vacuous run as warrant evidence"`).

---

RISK: The VDS proofs are ten days older than the ledgers they sit beside. The
newest proof is `PROOF-20260814-190603`; `.vds/ledgers/screens.yaml` was
generated `2026-08-22T18:31:54Z` and `routes.yaml` `2026-08-22T16:31:51Z`. Only
the ledgers are gated (`make vds-ledgers`); the proofs are not, so the design
record's own evidence can age arbitrarily behind the source it describes.

---

RISK: `.vds` pins no design authority. `designpack = "none@0"` and
`designpack.lock` records `designpack_id: none`, so `token_pin`, `geometry` and
`prohibition` have no thresholds to measure against, which is precisely why they
are vacuous.

---

RISK: A phased-plan document states that the visual-evidence assertion runs in no
CI workflow ([`docs/PROGRAM-2026-08-18-phased-plan.md:139`](../../../docs/PROGRAM-2026-08-18-phased-plan.md) `"and no CI workflow runs it. The recapture is a"`). The make TARGET is indeed
absent from CI, but the vitest it wraps,
`apps/worker/tests/visual/manifest.test.ts`, matches vitest's default include and
is executed by `pnpm run test` inside `make worker-quality`, which CI's
`worker-build` job does run ([`Makefile:244`](../../../Makefile)
`"cd apps/worker && $(PNPM) run test"`). If that reading is right, a stale
receipt is a merge blocker and the document says it is not.

---

RISK: An unbound-but-load-bearing surface remains by design and is written down:
`UI-TEST-HARNESS-001:D1/D2/D3` records that "the Worker has NO browser smoke test
at all today, and no playwright config or dependency"
([`docs/refactoring/order-binding-exemptions.json:84`](../../../docs/refactoring/order-binding-exemptions.json) `"the Worker has NO browser smoke test at all today"`). Nothing end-to-end
asserts that a built image answers a chat turn.

---

RISK: `scripts/govern.py` drives a HIGH-consequence verb to completion including
answering its own approval. It is honest about the exemption it reports
([`scripts/govern.py:134`](../../../scripts/govern.py) `"approved under the SOLE-AUTHOR EXEMPTION - nobody independent"`), but it is
wired into no Makefile target and no test, and the only record of it is
`.vjs/permits/PERMIT-1785316217.yaml`, whose scope is that one path.
