# The referent, the method, and the bounds

This file exists so that no reader of this corpus has to guess what it describes
or how far to trust it.

## The referent

    repo      github.com/wlilley93/boltrig
    branch    origin/main
    commit    19bcae7fa81663fe8998377c86451ba08fb16e48
    subject   Merge pull request #358 from wlilley93/fix/test-postgres-volume-leak
    captured  2026-08-24
    corpus    written on branch docs/brownfield-spec cut from that commit

Everything in this corpus is a statement about THAT TREE. Not about a deployed
stack, not about a feature branch, not about what anyone intends to build. The
repository had eleven other live worktrees on eleven other branches when this was
written and none of them were read.

The corpus is pinned in code, not only in prose: `verify-citations.py` refuses to
run when `git rev-parse HEAD` is not the commit above, because a verifier that
cannot pin its referent will cheerfully confirm every citation against a tree
that has moved underneath it.

## Scale of the referent

    boltrig/          820 python files      154,213 lines
    tests/            537 python files      127,037 lines
    apps/worker/      427 typescript files   99,610 lines
    sdks/              31 typescript files   14,354 lines
    site/             101 typescript files    8,056 lines
    services/          16 python files        4,591 lines
    scripts/           52 python files       11,717 lines
    migrations/        88 alembic versions plus baseline.sql
    tests/invariants.yaml                     2,838 lines
    manifest.yaml                            27,378 lines
    docker-compose.yml                       37,479 lines
    .env.example                             23,841 lines
    docs/decisions/                          40 numbered decisions

## The method

Twenty subsystem areas, one author each, all reading the same pinned tree and all
obeying `AUTHORING-CONTRACT.md`. Each author was told which doctrine claims about
its area to go and TEST rather than repeat, and was told that reporting a claim
as false is the more valuable outcome. Load-bearing claims were then
independently re-derived by agents who did not write the original spec and who
were briefed to refute rather than confirm.

Two depths are kept visibly separate throughout, because a specification with
only the first is half a specification and that gap has cost this estate a
rebuild before:

- SYSTEM depth: objects, contracts, control flow, data, boundaries, failure modes.
- PROCESS depth: what a person or an agent actually DOES with the thing, in
  order, with the gates and the recovery paths.

## What this corpus does not cover

Stated plainly so its silence is never read as evidence of absence:

- No deployed environment was inspected. The stacks this repo rolls to (canary,
  CV, dev) were not queried. Every statement about runtime behaviour is derived
  from code and configuration, not from observation.
- No test suite was executed. Test COUNTS and test NAMES are read from the tree
  and from `tests/invariants.yaml`; a test named here is a test that exists and
  claims to bind an invariant, not a test observed to pass today.
- No `docker`, `make`, `pytest`, or installer command was run. This host has been
  billed by careless gates before.
- The eleven sibling worktrees and their in-flight branches are out of scope, so
  work that is real but unmerged does not appear here at all.
- Third-party upstreams (Hatchet, Bifrost, Codex, signal-cli, the WhatsApp
  bridge, Cognee, Postgres) are specified only at their seam. Their internals are
  not this corpus's subject and were not pinned.

## Reading order

1. `BIBLE.md` for what Boltrig is and where each thing lives.
2. `specs/SPEC-01-kernel-dispatch.md` for the one idea the rest depends on.
3. Then the area you need, from `INDEX.md`.
4. `RISK-REGISTER.md` before you change anything.
5. `GAPS.md` before you trust a silence.

## Status vocabulary

IMPLEMENTED, IMPLEMENTED-UNTESTED, SCAFFOLDED, SEAM, DEAD, UNCERTAIN. Defined in
`AUTHORING-CONTRACT.md`. UNCERTAIN is used deliberately and is not a defect; a
wrong IMPLEMENTED is.
