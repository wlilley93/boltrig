# Goal: make boltrig's claims about itself load-bearing

Long horizon. Successor to `GOAL-trustworthy-gate.md`, which is met: CI runs, it
is green, and a green result is now evidence. That goal was about one instrument.
This one is about the class of defect that instrument kept finding.

## The goal

**Every claim boltrig makes about itself must be mechanically tied to the
behaviour it describes, so that a claim cannot drift from reality without
something failing.**

A claim is anything a reader would rely on: a docstring, a comment, a config
attribution, an invariant description, a status endpoint, a container health
signal, a compose pin, a test name, a doc that says a control exists. Today most
of them are prose. Prose is not enforcement. A claim nothing checks is a claim
that will eventually be false, and the more reassuring it is, the longer it
survives.

## Why this, and why now

Not a hypothesis. In a single day of work, every one of the following was found,
and each is the same shape: something asserted a property the running system did
not deliver, and nothing forced them to agree.

| The claim | What was actually true |
| --- | --- |
| "The production back end is Redis" (module docstring, compose comment, readiness gate) | `RedisCounter` was constructed NOWHERE. Every rate limit was per-process and per-boot; a restart silently reset the 2FA brute-force bound |
| `docker ps` says `healthy` | A client tenant sat at `readyz` 503 for ~40 minutes. The healthcheck is `/healthz` and knows nothing about the schema |
| "only the SAME run may resolve it" (credential docstrings, SEC-181) | True of the resolver, false of the system: the door let a caller choose which run they were |
| A guard against a defaulted audit key | Compared against the in-source constant, not the value `.env.example` ships. The documented setup tripped neither the fatal nor the warning |
| `_still_leased`, a lease "fence" | A read-then-write check cannot decide a read-then-write race. A reviewer applied it and reproduced the original defect |
| Order D8: "may not be deleted without a further ruling" | The test it protected was bound to no invariant. Enforceable by nothing |
| A test asserting the retired-runtime rule | Passed on any machine with a gitignored `manifest.yaml`; failed only in CI |
| `tests/invariants.yaml` | Read by a regex parser, and does not actually parse as YAML |
| A compose override pinning an image | Pinned a version the containers were not running. The next `up -d` was a loaded gun |
| Migration `0038` | Applied its schema change, then could not write its own revision id |
| My own case file to the court | Argued from two costs that were not real. The bench checked and both failed |

Eleven instances. One shape. That is a systemic property, not a run of bad luck,
and it is not fixed by fixing eleven things.

## What done looks like

Measurable, and none of it is "we were careful":

1. **No unwired claim.** No production-facing docstring, comment or config
   attribution names a mechanism that no production path constructs. A check
   enumerates the named mechanisms and fails on one nothing builds.
2. **Every invariant is enforced by a gate, not a sentence.** `binding_debt=0`
   holds for all 330 declared invariants. The next bar: every ORDER directive that
   says "must" is bound to something mechanical, the way D8 now is.
3. **Status tells the truth.** No component reports healthy while unable to serve.
   Readiness is what orchestration and operators consult.
4. **Config that is derived, not restated.** Where a value appears twice it is
   derived once, per the derive-don't-store ratio already in the citator. The
   remaining duplications are enumerated and each is either derived or has a
   drift test.
5. **A claim cannot outlive its subject.** Deleting or retiring a mechanism fails
   the gate for every record still asserting it. The SEC-24 drift (an order
   pointing at a renamed test) breaks the build, rather than sitting red for
   ninety minutes.
6. **The record survives contact with a real environment.** Every gate that can
   pass because of something present on one machine is either made hermetic or
   made to fail loudly when its precondition is absent.

## The programme

**Tier 0. Inventory. BUILT 2026-07-27**, and the fact that it took until then is
the sharpest finding in this document. Until that afternoon this paragraph said the
inventory was "the piece nobody has done", the status section forty lines below said
"the inventory's UNVERIFIED column is not worked through", and **there was no
inventory and there never had been**. A document about claims being load-bearing
carried a false claim about its own foundation, and it survived because the two
sentences were far enough apart to read as a plan and a progress note rather than as
a contradiction. That is the defect class, one level up, in the record that defines
it.

It is a SCRIPT, not a page: `scripts/build_claim_inventory.py` writes
`docs/claim-inventory.tsv`, and `make claims` refuses both a stale census and a
growing residue. A hand-written inventory is accurate for one afternoon, and there
are 1,297 claim-bearing statements in `boltrig/` alone.

**Tier 1. Bind the load-bearing ones.** Not all claims deserve a gate. Rank by
what a false version would cost: a security control's description outranks a
comment about a variable name. Bind the top tier mechanically.

**Tier 2. Make drift fail.** The generalisation of the SEC-24 lesson. Renaming or
deleting a thing should break every record that names it. This is mostly
tooling: symbol-aware checks over the catalogue, the orders, and the docs.

**Tier 3. Close the environment-dependent gates.** `manifest.yaml`,
`BOLTRIG_TEST_DATABASE_URL`, and the rest of the family where a check passes for a
reason unrelated to the code.

**Tier 4. The lease fence.** `[2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001`,
already ruled and OPEN. It belongs here because its D9 is precisely this goal:
record that the change makes the RECORD single-writer and does NOT make execution
exactly-once.

## Where it stands (2026-07-26)

Eleven gates now run in `make python-quality`, so they are in `ci/test-and-gate`
and a claim cannot drift past them silently. Do not take that number on trust; it is
the kind this document is about. Count it:

```
grep '^python-quality:' Makefile | sed 's/##.*//' | cut -d: -f2- \
  | tr ' ' '\n' | grep -vE '^$|typecheck' | wc -l
```

The first version of that command counted 20, because it did not strip the `##` help
text and counted every word of it. A counting rule that miscounts is worse than no
number, and it took one run to find out - which is the argument for printing the
command beside the figure rather than only the figure. Each was written because of a defect
that had already shipped, and each found more on its first run.

| Gate | Binds | Found on its first run |
| --- | --- | --- |
| `unwired-claims` | A class or function the record names that no production path reaches | `RedisCounter`. Then, once extended to functions: `run_retention_forever` (see below), `sweep_run_scoped` (7 records, "its only caller is the org pump", true count zero), `consume_if_approved` (the dispatch gate calls something else), `consume_budget` (superseded, 6 docstrings still anchored on it) |
| `prose-references` | Every repo path, test node id, `make` target and env var named in prose | 12 broken references, including a founding ruling cited as binding whose register entry has never existed in this repository's history |
| `gate-coverage` | Every compose manifest is validated; every `quality` component runs in CI | `migration-parity` and `doctor-fixture` ran in no CI job; three compose overlays reached no validation step, including the one `genesis.sh` runs |
| `health-claims` | No service reports healthy while unable to serve | The kernel and fleet-worker. **Both are now fixed and the exemption file is empty**: the kernel probes `/readyz`, and `boltrig fleet-health` reads back the signed receipt the worker publishes, proven red on production for a forged key and an unreachable Redis. Extending the gate to admit a readiness COMMAND (derived: the subcommand must be dispatched, and its module must read the same evidence the `/readyz` handler reads) found two wrong versions of that rule before the right one |
| `claims` | Tier 0's ratchet: `docs/claim-inventory.tsv` regenerates byte-identically, and the count of load-bearing claims naming nothing resolvable may only fall | 1,297 claim-bearing statements across `boltrig/` and the compose files, of which **236 assert a security control and name nothing a machine can resolve**. Zero name a subject that is dead, which is `unwired-claims` having already cleared that class - so the two gates cover the same defect through different doors and neither is redundant |
| `structure` | File and function length, as an expiring ratchet | Pre-existing; it caught two of this week's own changes |
| `invariants` | Every declared invariant is bound and every marker declared | The catalogue had silently eaten a whole invariant to a duplicate id, and had never parsed as the YAML its name claims |
| `order-directives` | Every directive of a `status: binding` court order is named by a test, beside the order | 102 binding directives; **only 36 were bound by anything**. The gate then caught itself over-counting - it had matched an order and a directive anywhere in the same file, which its own new test file (naming six orders) cross-matched immediately - so it now requires them within two lines and reports the smaller, true number. Worked down to **106 of 112 bound**, with 6 waived: the remaining 6 are directives no test can honestly hold (3 appellate with no engineering consequence by their own terms, 3 Principal gates on live cutovers CI cannot decide). This row said "96, which is the floor" until 2026-07-27; the floor held and the total moved, because the schema-validation ledger order added 10 directives and every one of them was bound. Quote `make order-directives`, not this sentence. Binding the rest is what the gate is for. COUNTY 8 D7 ordered a forced password rotation for the seeded superadmin and **half of it was not implemented** - built, tested and deployed the same day. D9's "never opbox's domain models" turned out to be a set intersection over two real schemas rather than the hand-split I had refused: four tables shared, three auth/tenancy and one a name collision with zero shared columns |

The single worst find is the measure of why the goal exists. **Right-to-erasure
had never run.** `run_retention_forever` had zero callers - no compose service, no
Makefile target, no deploy unit, no `__main__` - while `security-conformance.md`
recorded DATA-07 and PRIV-04 as BUILT and SEC-74 claimed a deleted conversation no
longer sat in Postgres indefinitely. The purge itself was tested: three tests drove
`run_retention_once` by hand and passed. That is exactly how it survived. **A test
for the mechanism is not a test for the wiring**, and every gate above exists to
tell those two apart.

What remains: Tier 1 is partly done. The load-bearing claims found so far are
bound, and Tier 0 now says how many are not: **236 claims assert a security control
and name nothing a machine can resolve.** That is the queue, and it is the number
this goal's closing ratchet is about. **Tier 3 is closed**: the family is now enumerated in `tests/conftest.py` as two lists, one
BLOCKING (a run that skips the Postgres or shared-rate-limit family ends non-zero)
and one LOUD (a run that could not reach a live service says so, by name, at the
end), and the three vacuous globs each carry a floor that fails when the scan
reads nothing.

Tier 3 also produced the sharpest instance of the whole premise since retention.
`pytest-randomly`, installed to convert latent order-dependence into a failure,
found on its first real outing that the durable-ledger schema fixture **had never
once built what a deployment builds**. It claimed, in its own docstring, to build
"the execution-ledger schema exactly as a deployment builds it" and to be
incapable of drifting; it replayed the migration chain from 0026, and
`0035_channel_durability` alters a table created at 0019, so against an empty
database it had ALWAYS failed. Two different accidents kept supplying the missing
table: a long-lived local test database that already had it, and a test ordering
in which the module that applies the whole chain happened to run first. Same
shape as the other eleven, and found the same way. See
`docs/findings/2026-07-26-fleet-worker-health-signal.md`.

## What this is NOT

- **Not a documentation project.** Writing more prose about the system is the
  failure mode, not the remedy. Every tier ends in a check, or it did not happen.
- **Not a rewrite.** Nothing here requires changing how boltrig works. It requires
  making what it already does and what it says about itself the same thing.
- **Not a promise of correctness.** A system whose claims are all true can still
  be wrong; it just cannot be wrong AND reassuring at the same time. That is the
  whole of the ambition.

## The honest limit

This goal cannot be finished, only held. New claims are written every day, and
the rate at which they are bound is the only thing that keeps the gap from
growing. The measure of success is therefore not a date but a ratchet: the number
of unbound load-bearing claims may only decrease, the way structural debt already
does.

The one thing that would falsify the whole premise is finding that the eleven
above were unrelated after all. They were not. Every one was found the same way:
by going and checking whether the thing the record described was the thing that
runs.
