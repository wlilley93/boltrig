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
   already holds for the 325 declared invariants. The next bar: every ORDER
   directive that says "must" is bound to something mechanical, the way D8 now is.
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

**Tier 0. Inventory.** Enumerate the claims. Every docstring asserting a
mechanism, every config comment attributing behaviour to a service, every
invariant description, every order directive, every doc claiming a control. This
is the piece nobody has done and everything else depends on it. Expect the
inventory itself to find defects, because reading a claim next to its
implementation is what found most of the eleven.

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
