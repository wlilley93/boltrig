# Boltrig, as built

The front door to a reverse-engineered specification of Boltrig at commit
`19bcae7f`. If you read one file before touching this system, read this one, then
`REFERENT.md` for what the corpus does and does not cover.

## What Boltrig is

A self-hostable agent-orchestration platform: a thin kernel that is the single
chokepoint for every external action, and a permanent agent fleet that spawns
ephemeral workers to do work. It is a clean-room implementation of a kernel
doctrine it does not author, and it is the standard agent engine across this
estate.

Three claims define it, and this corpus tests all three rather than repeating
them:

1. **A thin core.** The kernel implements policy nowhere. It composes a
   dispatcher, grant checker, rate limiter, credential resolver, audit writer,
   HITL gate and cost accountant, and loads everything else as data. Adding an
   integration should change no core code.
2. **A permanent fleet spawning ephemerals.** A tier1 chief-of-staff over tier2
   department heads takes in work and spawns short-lived children, choosing the
   cheapest capable runtime, reserving budget first, enforcing recursion depth.
3. **Nouns and verbs.** Agents reason in stable nouns (`ticket`) and verbs
   (`ticket.create`); a binding resolves each verb to a concrete adapter or
   agent, and the agent never learns which system sits behind it.

Where the code diverges from those sentences, the divergence is recorded in the
area spec and, where it matters, in `RISK-REGISTER.md`. Several of them do
diverge. That is the point of a brownfield spec.

## The shape of the thing

    boltrig/          820 python files    154,213 lines   the kernel, fleet, store, adapters
    tests/            537 python files    127,037 lines   82 percent of source size
    apps/worker/      427 ts files         99,610 lines   the primary human surface
    sdks/ + site/     132 ts files         22,410 lines   public SDK and marketing site
    ios/              swift                               companion app
    services/          16 python files      4,591 lines   channel gateway, distill sidecar
    migrations/        88 alembic revisions plus baseline.sql
    tests/invariants.yaml    2,838 lines   421 declared invariants
    docker-compose.yml      37,479 lines   15 services
    manifest.yaml           27,378 lines   the configuration surface
    docs/decisions/         40 numbered decisions

1,708 commits. First commit 2026-06-28, referent 2026-08-24. This system is
about eight weeks old.

## How to read this corpus

| you want | read |
| --- | --- |
| what a subsystem is and does | `INDEX.md`, then the area spec |
| the one idea everything rests on | `specs/SPEC-01-kernel-dispatch.md` |
| what is dangerous | `RISK-REGISTER.md`, worst first |
| what this corpus cannot tell you | `GAPS.md` and `REFERENT.md` |
| a testable statement of behaviour | `registers/requirements.tsv` |
| whether a citation is still good | `python3 verify-citations.py` |

## What the register says

1,899 requirement rows across twenty areas, each a single testable sentence
carrying a `path:line` citation and a verbatim anchor.

    IMPLEMENTED             1,363   71.8 percent
    IMPLEMENTED-UNTESTED      474   25.0 percent
    DEAD                       41    2.2 percent
    SEAM                       11    0.6 percent
    SCAFFOLDED                  9    0.5 percent
    UNCERTAIN                   1    0.1 percent

Two numbers deserve to be uncomfortable.

**One row in four is IMPLEMENTED-UNTESTED.** The behaviour is there and reachable
and the author went looking for a test and did not find one. In a repository
whose entire governance story is that every claim is pinned to a test, a quarter
of the specified behaviour is not.

**904 rows, 47.6 percent, bind no invariant at all.** The invariant catalogue
declares 421 invariants and the gate holds binding debt at zero, which is real
and is a genuine achievement. But debt zero means every DECLARED invariant has a
test, not that every behaviour has an invariant. Nearly half of what this system
does is outside the catalogue entirely, so the ratchet cannot see it.

Neither number is an accusation. Both are the difference between "our gate is
green" and "our behaviour is covered", and a brownfield spec exists to make that
difference legible.

## What survived being attacked

Every HIGH-severity finding the authors raised was put to three independent
panels briefed to REFUTE it, each reading a different lens (what the code does,
whether the path is reachable, whether the statement overclaims), each defaulting
to refuted when uncertain.

    56 findings put to panels
    40 CONFIRMED
    16 REFUTED as written
     0 split

Twenty-nine percent did not survive. One of the loudest, "68 of 161
state-changing routes bypass the dispatcher, in breach of the one-chokepoint
doctrine", was refuted by all three panels: the routes really do not dispatch,
but AGENTS.md scopes the chokepoint to external actions, decision 0003 rules the
channel intake path terminates at its seam, the external egress those routes
front DOES dispatch, and the count itself was an unreproduced census. It is a
governance-surface observation, not a demonstrated breach.

Two findings got WORSE under attack. The audit-key boot guard was reported as
falling back to an in-source development key; a panel established that the
shipped `.env.example` sets `BOLTRIG_AUDIT_HMAC_KEY` to the empty string
deliberately, so a deployment following the README keys its tamper-evidence
chain with empty bytes, and the fallback never fires.

`RISK-REGISTER.md` carries all 56 with their verdicts. Read the refuted section
too: almost every refutation carries a narrower statement that IS true, and that
narrower statement is what should be believed. Nothing here should be actioned
from an author's first pass alone.

MEDIUM and LOW findings were not put to panels. They carry exactly one reading.

## Evidence discipline

Every claim in every spec carries a citation of the form

```
[`repo/relative/path.py:123`](../../../repo/relative/path.py) `"verbatim anchor"`
```

`verify-citations.py` checks all of them. It refuses to run unless
`git rev-parse HEAD` is the referent commit, because a verifier that cannot pin
its referent will confirm citations against a tree that has moved underneath it,
which is how a previous corpus in this estate ended up reasoning from a
paraphrase. It carries a self-test that seeds four broken citations and two valid
but awkward shapes, and fails if it misses a break OR flags a valid one. Run
`python3 verify-citations.py --selftest` before trusting a green result.

At the last run every citation in the corpus resolved and was anchored.

## The standing caveats

The corpus describes a tree, not a running system. No environment was inspected,
no test was executed, no container was started. A test named here exists and
claims to bind an invariant; it was not observed to pass. Eleven sibling
worktrees carrying in-flight work were out of scope, so anything real but
unmerged is invisible here. `REFERENT.md` states all of this precisely, and
`GAPS.md` records where a silence in this corpus must not be read as an absence
in the system.
