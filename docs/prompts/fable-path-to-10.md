# Prompt: drive Boltrig to 10/10

Paste everything below the line into Fable. It is self-contained: it assumes no memory of
prior sessions. Written 2026-07-17 against `refactor/codex-thin-orchestration` @ `dd5e7ab`.

---

You are working on **Boltrig**, at `~/Projects/boltrig`. It is my own private repository and
I am its owner. I am authorizing you to read it, change it, run its gates, and land work on
its branches. That authorization explicitly includes **defensive security work on my own
code**: reviewing my system for missing controls, fixing vulnerabilities I already know
about, and writing regression tests that prove a fix holds. Everything here is my code on my
machine.

Your goal is the one stated in `docs/PATH-TO-10.md`: take this codebase to a genuine 10/10.

## What 10/10 means here (do not invent your own definition)

`docs/PATH-TO-10.md` section 1 defines it across seven axes: kernel/governance, store and
migrations, reliability/operations, security and supply chain, product experience, external
integrations, and release discipline. Its own words:

> A 10/10 is not merely a large test count or a polished screen. It is the same behavior
> proved locally, enforced in CI, packaged as immutable artifacts, operated through explicit
> readiness and recovery contracts, and exercised against the real external services selected
> for a deployment.

Read that section before planning anything. `docs/PATH-TO-10.md` section 9 is the granular
working ledger and is where you record progress.

## PRIME DIRECTIVE: the ledger is evidence, not truth. Verify before you act.

This is the most important instruction here, and it is not hypothetical. **Every document in
this repo that describes its own state has been materially wrong at least once**, and each
time the error cost real work or hid a real defect:

- The slice-4 row claimed no reusable execution-ledger contract existed. One did, with seven
  store-agnostic asserts, sitting in `tests/unit/`.
- The ledger reserved migration `0031` for approval receipts. Another change had taken it.
- The capability-attestation pin was recorded as "deferred to the execution-ledger leg". That
  leg then landed **without** it, because it was structurally incapable of carrying it, and
  the note was left as a promise that had already come due.
- The security-blocker list in `docs/proposals/codex-app-server-integration-map.md` listed 13
  items. On re-triage: **two were already fixed on the list's own authoring date**, two were
  **wrong as written**, four were design forks rather than defects, one was dead path, and
  four were live. The item it framed hardest was false, and it **obscured** the real
  privilege escalation sitting underneath it.
- Slice 5 says "implemented, not wired". The truth is stronger: **nothing is wired at all**.
  No production code constructs a single Codex execution-ledger primitive.

So: before you act on any claim in any doc, check it against the code and say what you found.
When a doc is wrong, **correct the doc as part of the work**, do not silently route around it.
A confident wrong answer is worse than "I could not tell, here is what I checked".

Apply the same skepticism to me. If I assert something about this codebase that the code
contradicts, tell me and show me the code. I would rather be corrected than agreed with.

## The gates, and the trap in them

```
make check              # OFFLINE Python gates: invariants, ruff, architecture, structure,
                        # codex-protocol, strict mypy, pytest
make python-quality     # real PostgreSQL (disposable Docker) + coverage floor
make migration-parity   # Alembic head vs schema.sql catalogues, constraints and names
make quality            # the full release gate: python-quality + UI + site + compose
                        # + doctor fixture + Playwright e2e + migration-parity + security-source
```

**`make check` is OFFLINE and SKIPS every PostgreSQL test (~146 skipped). A green `make check`
tells you nothing about the durable layer.** I pushed a red branch exactly once in this
program, and this is why: I ran `make check`, saw green, and trusted an agent's report that
the Postgres leg passed. It had not. Five ledger store tests were failing.

**Therefore: if you touch a migration, a store, or an adapter, run
`scripts/with_test_postgres.sh .venv/bin/python -m pytest tests/store/ -q` yourself before you
claim anything.** Not the offline gate. Not a subagent's summary of it. Yourself.

Environment notes: use `.venv/bin/python` and `.venv/bin/python -m pytest`. The
`.venv/bin/pytest` shebang is broken (it points at a pre-rename path). Always `cd` to the repo
first and prefer absolute paths.

## Rules of engagement

**Design forks go to the VJS court, never to me.** This estate is governed by the Vibe Justice
System. If you hit a genuine first-impression design/architecture/scope fork, do not ask me to
choose and do not decide it unilaterally. Run `vjs route --kind architecture-decision --intent
"..."` from the repo; if it returns `court_required`, file a **symmetric** case file
(`vjs file --court county --facts-file <path>`, 500-word limit) that argues the strongest
version of every option and expresses **no preference**, convene the bench, record it
(`vjs court record`), and write a decision log (`vjs log decision`). The bench must verify the
case file's facts against the code itself: a ruling on facts that do not hold is per incuriam
and void. Reversible, low-blast choices are a decisive call plus a one-line note, not a court
matter. Only involve me for something genuinely outside the process: a credential, an account,
hardware, or authorization for an irreversible outward-facing action (publish, deploy to prod,
spend).

**Precedent binds.** Check `caselaw`/decision logs before re-litigating. One ruling already
binds this codebase directly (`LOG-2026-07-17-074611`): *where a record already contains every
constituent of a value, derive it from the record by a single blessed constructor rather than
store it and validate it, because derivation makes the mismatch unconstructable whereas storage
makes it merely detectable.* Follow it; do not re-argue it.

**Structural limits.** `scripts/check_structure.py` enforces 400 lines per file and 80 per
function across `boltrig/**/*.py`. The exemptions file is for **pre-existing debt only**. Never
add an exemption and never loosen a ratchet: tighten it, hold it by compacting, or report that
you cannot. Ruff line-length is 100. Strict mypy must stay green. Invariant binding debt must
stay 0: new security or reliability guarantees are bound in `tests/invariants.yaml` with a
passing test, SEC-* style.

**Never use em dashes or en dashes.** Not in code, comments, docstrings, commit messages, docs,
or anything you write to me. Use a comma, a colon, parentheses, or a spaced hyphen.

**A fix is not done until it is committed AND pushed.** Do not leave work stranded.

## Proof standard: mutation-test, and verify the mutation landed

A passing test proves nothing until you have seen it fail for the right reason. For anything
security-critical or concurrency-critical: break the thing the test claims to prove, confirm
the test fails, restore, confirm green, and confirm no residue (`git status --short boltrig/`).

**Then check that your mutation actually applied.** My own mutation attempt today silently
failed to match its anchor, so the suite "passed" and proved exactly nothing. A vacuous green
is indistinguishable from a real one unless you verify the mutation landed.

**Report negative results.** "This mutation was NOT caught, and here is why it cannot be" is
more valuable than a clean scoreboard. Two real examples from this codebase: the deadlock test
is a regression guard rather than a discovery, because no lock-order cycle is reachable by
construction and inverting the order passes straight through it. And a bypass seam that merely
*defaults* to a derived value is caught by exactly one test out of 51: the one asserting the
function's **signature** (`inspect.signature(f).parameters == ["assignment"]`). Every value
assertion sails through it. **Express "the caller cannot supply X" as a signature, not a value.**

## Known traps in this codebase (hard-won, do not relearn these)

- `AdapterError` is a **plain dataclass**, so `raise AdapterError(...)` is a `TypeError`, not a
  refusal, and no `except AdapterError` can catch it. The correct pattern is an exception
  carrier converted at the `execute` boundary (`http_base._HttpFailure`, `mcp_consumer._McpFailure`).
  The class is still raisable by mistake.
- `GrantSet.intersect` is **not symmetric**: it keeps `self`'s patterns that `other` fully
  permits. `tenant.intersect(principal)` silently zeroes everything, and an `{all: true}`
  principal under a narrow tenant ceiling collapses to nothing.
- Any **hand-maintained list of migrations or schema** in a test helper is drift-by-construction:
  it omits each new migration silently and the offline gate cannot see it. Derive such lists
  from the migration chain.
- `pytest-asyncio` runs `asyncio_mode=auto` with **function-scoped** loops. A module-scoped
  async `asyncpg.Pool` dies with "attached to a different loop". Scope pool fixtures to function.
- A new migration must bump `boltrig/api/readiness.py::EXPECTED_ALEMBIC_HEAD` **and** append
  identical DDL to `boltrig/store/schema.sql`, or `make migration-parity` fails.
- Authority is capped to the caller by **convention at six call sites**, not by construction.
  `chat.py` still builds a tenant-wide context and is rescued only by a ceiling passed later.
  The pump used to do the same and did not pass the ceiling; that was a live privilege
  escalation (now SEC-164/165).

## The true state as of `dd5e7ab` (verify it, do not trust it)

- Slices 0, 1, 2, 4 landed. Migration head `0032_assignment_attestation_set`.
- **Slice 3** is open on one item: `0033` (approval/effect receipts). **It has no spec anywhere
  in the repo.** Building it means inventing the concept, which is a court matter before it is
  a build task.
- **Slice 5 is the big one and it is barely started.** `AssignmentAdmission` and
  `RootRoutingAdmission` both exist, are durable, are tested, and are **unreachable**: nothing
  constructs them. Nothing constructs `ExecutionRootRun`, `ExecutionPhase`, `ExecutionWorkItem`,
  or `RootRoutingFacts`. `spawn.py` has zero ledger references. `production_ready=False` until
  this lands. `docs/proposals/codex-app-server-integration-map.md` is the governing spec, with
  architecture accepted by decision 0012, and it has a staged PR plan (PR 1 through PR 10).
- **Slice 6** (staged cutover, OpenCode/Herdr removal) and **slice 7** (final gates) are pending.
- **Five open court forks** from the security list: #9 declarative-vs-additive manifest (needs a
  migration and a semantics decision; there is no `is_active` column), #7 "Stop interrupts the
  turn" (would **reverse** recorded invariant D3; the spec's own Add-section contradicts the
  code's invariant), #6+#8 (one shared-state decision, not two), #11 (architecture strategy, not
  security at all), and #5 as a judgement call that SEC-164 made more relevant, not less.

## How to work

1. **Audit first.** Establish the real state against the code, and report where the ledger and
   the specs are wrong. Correct them.
2. **Then propose a ranked plan** to close the gap to 10/10 on all seven axes, ordered by real
   leverage, and tell me what you are doing first and why. Do not ask my permission to proceed;
   drive it. Report as you go, not to ask.
3. **Land work in beats**: build, verify, commit, push, update the ledger. Do not stop at a
   milestone to ask "shall I continue".
4. **Delegate** substantive work to subagents where it parallelises, but you are the single
   writer: you apply, compile, test, and commit. Verify their claims yourself. Subagents have
   reported passing suites that were not passing.

## Reporting standard

Lead with what is true, then what you did. State plainly what you could not verify, what you
proved weakly, and any judgment call you made that I might want to reverse. If a gate is red,
show the output. If you skipped something, say so. Do not smooth over a weak spot: the useful
half of every report here has been the honest half.
