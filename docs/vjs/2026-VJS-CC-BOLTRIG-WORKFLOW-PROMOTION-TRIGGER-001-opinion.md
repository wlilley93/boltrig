# [2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 - opinion

First Instance, single judge, boltrig County. Case file: SUBMISSION-2026-07-27-144351.
Convening: CONVENING-county-2026-07-27-151330, case file
`sha256:17b8ee13fe22071aebf7ac7a64ab68192bcea569144bfee153a8c088d9cfcb19`.

**No citation is minted**, for the reason recorded in the schema-validation ledger order: the
allocator refuses the canon COUNTY series at a subscriber seat ([2026] VJS-PC 19) and minting at
canon offers a number this repository's mirror already uses.

**Implementation status: DISCHARGED, 2026-07-27.**

---

## 1. Findings on the facts

Every file the pleading cites was opened and the caller chains traced.

**G1 - PARTLY CONFIRMED, and wrong in its load-bearing clause.**

Confirmed: `library.py:112` calls `_reuse_weights`; `:150` maps every stored promotion through
`reuse_weight`; the weight is the second element of the sort key (at `:129`, not `:126`).

**Corrected:** "the read side runs on every workflow selection" is **false**.
`WorkflowLibrary.match` has exactly one caller in the repository,
`generator.py:138` inside `select_or_generate_workflow`, and that function has **no production
caller**: every reference under `boltrig/` is its own definition and the package re-export.
Production selects a workflow by explicit id, through `control.workflow.trigger`,
`control.workflow.execute` and the pump's addressed `workflow:<id>` target. The pleading's
central metaphor fails: this is an **unwired** reader over a table nothing writes.

**G2 - CONFIRMED in its load-bearing half; the supporting measurement is wrong.**

Confirmed: the promoter is constructed at `bootstrap.py:719` into `platform["promoter"]`, and
neither `evaluate` nor `apply_promotion_signal` has a production caller.

**Corrected:** "the only platform keys any reader looks up are `workflows` and `admin`" is
false. `eval`, `spawner`, `status` and `readiness` are all read elsewhere. `promoter` is the one
key with no reader, which is the point the pleading needed and did not make, and which the
waiver it cites states correctly. **The submission contradicts the document it relies on.**

**G3 - CONFIRMED as to the table; understated as to why.** The sort key is inert for a stronger
reason than an empty table: the sort never executes in production at all. Filling the table
would change nothing.

**G4 - CONFIRMED, and the waiver is worse than pleaded.** It records neither the second writer
nor the unwired reader, and it could not: `check_unwired_claims.py` suppressed the function rule
for any name in an `__all__` and counted an `ImportFrom` as a reference, so a single re-export in
`workflows/__init__.py` hid `apply_promotion_signal`, `reuse_weight` and
`select_or_generate_workflow` at once. The gate's part-3 rule caught the CLASS; the gate was
structurally blind on the exported-FUNCTION path.

**G5 - CONFIRMED as a statement of COUNTY 5, with one correction to the record.** COUNTY 5's
stated ground for rejecting deferral, "the loop is already live and already reuses learned
artifacts", is not true today: `learn_from_success` is gated on
`outcome["generated_workflow"]`, and `GENERATED_WORKFLOW_KEY` is written by nothing under
`boltrig/`. The write half never fires either. That is a mistaken fact, not ignorance of binding
law, so COUNTY 5 is **not** per incuriam and its ratio stands untouched; only its urgency
rationale is undermined.

**G6 - CONFIRMED.** `EvalRunner.run_case` spawns through the spawner and records an `EvalRun`. A
spawn is model spend.

**Found, not pleaded:** `WorkflowPromotion` carries no version and no definition digest, while
`WorkflowDefinition` is versioned and `learn_from_success` re-upserts under the same id. A
stored PROMOTED state would therefore outlive the definition its eval proved, silently.

---

## 2. Precedent

**BINDING, directly on point: [2026] VJS-COUNTY 5.** Self-improvement raises competence, never
authority. Every pleaded option complies, so COUNTY 5 does not choose between them. Its D4
constrains promotion loops "when those legs are built": it contemplates them, it does not
command them. Retiring a leg is therefore not disobedience, and a deleted path cannot breach any
of its five prohibitions.

**BINDING: the derive-don't-store ratio** (county, 2026-07-17). Where a record already contains
every constituent of a value, the record must not also carry that value: derivation makes the
mismatch unconstructable, storage makes it merely detectable. Directly engaged. The eval-gated
state is a pure function of records the system already keeps (the eval cases targeting the
workflow, and their latest `EvalRun.passed`). It was stored anyway, in a row with neither
version nor digest.

**BINDING, same court, same day: the schema-validation ledger order.** Distinguishable on facts.
What carries across is its second limb, store only what cannot be recomputed and derive the rest
pinned by a digest, and its method: it refused all three pleaded options because the filing had
chosen the wrong axis.

**DISTINGUISHED: the work-item lease fence order.** Two limbs assist by analogy only. Its
treatment of a mechanism real on one backend and absent on the other as a PARITY DEFECT to be
repaired: `check_unwired_claims.py` is honest on the class path and cosmetic on the
exported-function path, and the repair is parity, not a waiver on the one instance it caught.
And its D9 duty to record what a change does NOT achieve, discharged at L3 below.

---

## 3. Reasoning

**None of A, B, C or D is right as pleaded.** A, B and C each answer "which trigger writes a
promotion", and each is defeated by the same fact the pleading did not establish: the value has
no consumer. A court asked to choose between three writers whose outputs are read by nothing is
not being asked a question, it is being shown a symptom.

Option C is additionally impossible in the form pleaded. `harvest_reuse_signal` IS wired, at
`bootstrap.py:371` and `access_routes.py:309`, and **neither site holds a workflow id**. The
score half is not merely untriggered, it is untriggerable without a linkage the record does not
keep.

Option D reaches the right outcome for the wrong reason. "Nothing regresses because nothing
happens now" is equally true of every dead subsystem and proves too much, and its deletion list
is short by the pieces that matter, because the pleading believed the reader was live.

> **THE RATIO.** A fork about which trigger should WRITE a value is not justiciable while no
> production path READS it. Reachability is transitive and is measured to a production entry
> point: a reader that has a caller is not wired if that caller has none. Where the consumer is
> transitively unreachable, every candidate producer is equally inert, the choice decides
> nothing, and the court refuses it. **Wire or retire the CONSUMER first.**

**Corollary 1, on pleading.** A submission asserting a reader "runs on every X" must prove the
transitive chain to a production entry point. A caller count that stops at the first hop
misstates the record, and a misstatement about reachability is not a detail: it is the whole
question, dressed as background.

**Corollary 2, on gates.** A reachability gate that accepts a name's presence in `__all__`, or a
package re-export, as evidence of wiring is honest on the paths it walks and cosmetic on those
it does not. That is a parity defect and the repair is parity.

**Corollary 3, on triggers.** Where the value a trigger would write is a pure function of
records the system already keeps, there is no trigger question at all. **A live product question
about WHEN a value is written is a symptom that the value was stored where it should have been
derived.**

### The deferral question, answered rather than passed on

The waiver said the promoter awaited "the product decision of WHEN promotion runs". **That is
not the Principal's decision and this court decided it: there is no such decision.** On the
current record every answer to "when" has identical effect, so the question is not ripe and no
decision-maker could be given material on which to answer it. And permanently: the state is
derivable, so promotion is not an event with a trigger. Routing it to the Principal would have
handed them an unanswerable question and bought another expiry cycle.

There IS a genuine Principal-owned question, and it is a different one nobody asked: should the
pump's routing path consult the library BY INTENT before routing an unaddressed item to the
chief of staff? That changes what runs for a tenant. It is filed as
`docs/decisions/0019-route-by-intent-is-the-principals.md`, and it is the real blocker the
waiver mis-described.

---

## 4. Disposition

A, B and C **refused**, not weighed. D **adopted in part, on different reasoning, and extended**.
The cut runs through `signals.py`: `harvest_reuse_signal` is wired, has a live consumer, and
stays.

---

## 5. Limits, recorded rather than ordered

**L1.** D2 narrows the blind spot; it does not close it. Reachability from an enumerated root set
cannot see through `getattr` seams, protocol dispatch or config-named handlers, and an
over-broad root set silently re-admits exactly this defect. No mechanical check can hold "the
root set is honest".

**L2.** The rebuild rule, if the Principal answers 0019 yes: the eval-gated state must be
**derived**, at read time, from the eval cases targeting the workflow and their latest run,
pinned by the definition's `build_workflow_snapshot` digest so an eval that proved an earlier
definition cannot rank a changed one. No table, no writer, no trigger.

**L3.** This order removes an inert subsystem and a false claim. It does **not** make the
self-improvement flywheel work, and no directive here causes any learned workflow ever to be
reused.

---

## 6. Obiter

**O1.** COUNTY 5 pinned the authority boundary "before the loop is extended", on a stated belief
that the loop was already live. On today's record it never ran. The ratio is unaffected and
worth keeping over an inert path. But the bench was told a loop was live because code existed
and had callers, and no gate could contradict it. That is the same defect the loop's own
governance was convened to prevent, occurring in the convening.

**O2.** Two records described this subsystem accurately and one did not. The waiver got the
platform keys right; the docstrings said "reserved API" rather than claiming a live control. The
**submission** is the document that overstated, in the one sentence the matter turned on. Careful
prose in the code did not save a careless sentence in the pleading, which suggests the check that
matters is not on prose quality but on whether a claim about reachability was measured at all.

---

## Discharge record (2026-07-27)

All nine directives implemented.

**D1.** `check_unwired_claims.py` now tracks a package `__init__`'s `ImportFrom` names as
RE-EXPORTS rather than references, and drops both suppressions for the function rule. A class may
still be exported for an outside caller to construct, which is a real seam; a function has no
such seam here. First run after the repair reported five names the gate had been blind to,
including `apply_promotion_signal`, exactly as the judgment predicted.

**D2.** `scripts/check_reachability.py`. Roots are derived structurally (decorated functions,
methods overriding a foreign base, module-level and class-body loads, dunders, `getattr`
literals) with the rest declared in `docs/refactoring/reachability-roots.json`, each needing a
reason. **First measurement: 2,735 functions, 145 unreachable, 71 of them with no caller at
all.** The root set is deliberately EMPTY on that first run so the number is the raw
measurement rather than one laundered through roots guessed at in an afternoon.

The 71 corroborate the graph from the other direction: they contain every name the repaired
unwired gate reports and every name its waiver file waives. They also contain findings the order
did not anticipate, `redact` in `kernel/pii.py` and `apply_rls` in `store/postgres.py` among
them, with no caller anywhere in the package.

**D3, D4.** The promotion machinery is deleted, migration `0040` drops the table, and
`harvest_reuse_signal` and both its call sites survive with a test that says so.

**D5, D6.** The `WorkflowPromoter` waiver is removed with its subject. Every remaining waiver
carries a `blocker`.

**A DEVIATION FROM D6, recorded rather than made quietly.** The order names two blocker forms,
`caller:` and `principal:`. Applying only those would have forced four of the six live waivers to
say something false: `consume` is a gate false positive, `push` is a method of an exported
reference adapter deliberately kept off the protocol, `accept_once` is a test-only seam whose
production counterpart is a different function, and `sweep_run_scoped` must NEVER acquire a
caller at a run terminal. None of those is waiting for anything. A third form, `design:<slug>`,
was added for them. It is deliberately the weakest of the three and is not checkable, which is
the point: a waiver that can name neither a caller nor a decision is asserting the name should
never have one, and that should look different in kind. If the court disagrees, it can narrow it.

**D7.** The prose asserting a live loop is corrected.

**D8.** `docs/decisions/0019-route-by-intent-is-the-principals.md`, record id
`PRINCIPAL-2026-07-27-ROUTE-BY-INTENT`, expiry 2026-10-31. On expiry without an answer the ratio
applies with no further order: retire.

**D9.** Every new gate is bound by a seeded failure that was RUN, not merely written: an
unreasoned root, a missing baseline, and a `root -> a -> b` / `c -> d` fixture where only the
second chain is reported. One of those seeded tests found a defect in its own gate on the first
run, a `relative_to` that raised when pointed outside the repository, which would have made the
check crash exactly where it was supposed to report.

**Found while discharging, and worth more than the directive that found it.** Two tests in
`test_claim_gates.py` had the same name. The second silently replaced the first, so a case that
had been passing simply stopped existing the moment its twin landed. Nothing warned. That is the
day's recurring shape once more: not a check that failed, but a check that quietly ceased to be
run.
