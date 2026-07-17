# Prompt: plan Boltrig's path to 10/10 (Fable planner, hands off to Opus)

Paste everything below the line into Fable. It is self-contained and assumes no memory of prior
sessions. Written 2026-07-17 against `refactor/codex-thin-orchestration` @ `dd5e7ab`.

You are the **planner**. You audit the real state and produce one ranked, code-grounded,
executable plan. A separate executor (Opus) then carries it out. Your deliverable is the plan,
not the commits.

---

You are planning work on **Boltrig**, at `~/Projects/boltrig`. It is my own private repository
and I am its owner. I authorize you to read it, grep it, and run its read-only gates. This is a
**planning and audit** task on my own code, and it explicitly includes **defensive security
review of my own system**: finding missing controls and specifying fixes. Everything here is my
code on my machine.

Your goal: produce the plan that takes this codebase to a genuine 10/10 as defined by its own
`docs/PATH-TO-10.md`. You do not change product code. You may correct the state claims in the
docs, and you write exactly one new file: the plan (see Output below).

## What 10/10 means here (do not invent your own definition)

`docs/PATH-TO-10.md` section 1 defines it across seven axes: kernel/governance, store and
migrations, reliability/operations, security and supply chain, product experience, external
integrations, and release discipline. Read that section first. Its own words:

> A 10/10 is not merely a large test count or a polished screen. It is the same behavior proved
> locally, enforced in CI, packaged as immutable artifacts, operated through explicit readiness
> and recovery contracts, and exercised against the real external services selected for a
> deployment.

Section 9 is the granular ledger and is where the executor records progress.

## Prime directive: the ledger is evidence, not truth. Verify before you plan.

This is the most important instruction here, and it is not hypothetical. **Every document in
this repo that describes its own state has been materially wrong at least once**, and each time
it hid a real defect or cost real work:

- The slice-4 row claimed no reusable execution-ledger contract existed. One did, in `tests/unit/`.
- Migration `0031` was reserved for approval receipts; another change had already taken it.
- The capability-attestation pin was recorded as "deferred to the execution-ledger leg". That
  leg then landed **without** it, because it was structurally incapable of carrying it.
- The security-blocker list in `docs/proposals/codex-app-server-integration-map.md` had 13 items.
  On re-triage: two were already fixed on the list's own authoring date, two were wrong as
  written, four were design forks not defects, one was dead path, four were live. The item it
  framed hardest was false and **obscured** the real privilege escalation underneath it.
- Slice 5 says "implemented, not wired". The truth is stronger: **nothing is wired at all.**

So plan from the code, not from the prose. Every claim you build the plan on, check against the
code and cite `file:line`. Where a doc is wrong, put the correction in your plan. A plan built on
a false premise is worse than no plan. If I assert something the code contradicts, say so and
show me the code; I would rather be corrected than agreed with.

## The gate trap your plan must account for

```
make check              # OFFLINE Python gates. SKIPS the entire PostgreSQL leg (~146 tests).
make python-quality     # real PostgreSQL (disposable Docker) + coverage floor
make migration-parity   # Alembic head vs schema.sql catalogues, constraints and names
make quality            # the full release gate (python-quality + UI + site + compose + doctor
                        # + Playwright e2e + migration-parity + security-source)
```

**A green `make check` tells you nothing about the durable layer.** A red branch shipped in this
program exactly once for this reason: offline gate green, plus a trusted-but-false report that
the Postgres leg passed. So any plan step that touches a migration, a store, or an adapter must
require running `scripts/with_test_postgres.sh .venv/bin/python -m pytest tests/store/ -q`
directly, not the offline gate and not a summary of it.

Environment: use `.venv/bin/python` and `.venv/bin/python -m pytest` (the `.venv/bin/pytest`
shebang is broken). `cd` to the repo first; prefer absolute paths.

## The proof standard your plan must impose on the executor

Bake these into every step, because they are how this codebase catches real defects:

- **Mutation-test security- and concurrency-critical changes**: break what the test claims to
  prove, confirm it fails for the right reason, restore, confirm green, confirm no residue. Then
  **confirm the mutation actually applied** - a mutation that silently fails to match its anchor
  produces a vacuous green indistinguishable from a real one.
- **Express "the caller cannot supply X" as a signature, not a value.** A bypass seam that merely
  defaults to a derived value is caught by exactly one test out of 51: the one asserting
  `inspect.signature(f).parameters == [...]`. Every value assertion passes straight through it.
- **Require negative results.** "This mutation was not caught, and here is why it cannot be" is
  worth more than a clean scoreboard. Two live examples: the deadlock test is a regression guard,
  not a discovery (no lock-order cycle is reachable, so inverting the order passes through it);
  and the free-running race test cannot catch a missing lock even in principle.

## Rules your plan must encode

- **Design forks go to the VJS court, never to me.** If a step is a genuine first-impression
  design/architecture/scope decision, the plan must route it through `vjs route` and, if
  `court_required`, a symmetric case file that argues every option's strongest form with no
  preference, a convened bench that verifies the facts against code, and a decision log. Mark
  every such step `kind: court-fork`. Reversible low-blast choices are a decisive call plus a
  note, not a court matter.
- **Precedent binds.** One ruling already binds this repo (`LOG-2026-07-17-074611`): *where a
  record already contains every constituent of a value, derive it by a single blessed constructor
  rather than store it and validate it, because derivation makes the mismatch unconstructable
  whereas storage makes it merely detectable.* Do not plan work that re-litigates it.
- **Structural limits, no exemptions.** `scripts/check_structure.py` enforces 400 lines/file and
  80/function across `boltrig/**/*.py`. Plans never add an exemption or loosen a ratchet: tighten,
  hold by compacting, or split. Ruff line-length 100. Strict mypy stays green. Invariant binding
  debt stays 0 (new guarantees bound in `tests/invariants.yaml`, SEC-* style).
- **A step is done only when committed AND pushed.** Encode that in every build step's done-when.
- **Never use em dashes or en dashes**, in the plan or anything you write to me. Use a comma, a
  colon, parentheses, or a spaced hyphen.

## Known traps that should shape the plan (do not make the executor relearn these)

- `AdapterError` is a plain dataclass, so `raise AdapterError(...)` is a `TypeError`, not a
  refusal, and no `except AdapterError` catches it. Correct pattern: an exception carrier
  converted at the `execute` boundary (`http_base._HttpFailure`, `mcp_consumer._McpFailure`).
- `GrantSet.intersect` is not symmetric: it keeps `self`'s patterns that `other` fully permits, so
  `tenant.intersect(principal)` silently zeroes everything.
- Any hand-maintained migration/schema list in a test helper is drift-by-construction and the
  offline gate cannot see it. Derive such lists from the migration chain.
- `pytest-asyncio` runs `asyncio_mode=auto` with function-scoped loops; a module-scoped
  `asyncpg.Pool` fails "attached to a different loop". Scope pool fixtures to function.
- A new migration must bump `readiness.py::EXPECTED_ALEMBIC_HEAD` and append identical DDL to
  `boltrig/store/schema.sql`, or `make migration-parity` fails.
- Authority is capped to the caller by convention at six call sites, not by construction; `chat.py`
  still builds a tenant-wide context rescued only by a later ceiling.

## The true state to verify as step 1 (from `dd5e7ab`, do not trust it)

- Slices 0, 1, 2, 4 landed. Migration head `0032_assignment_attestation_set`.
- **Slice 3** is open on one item, `0033` (approval/effect receipts). It has **no spec anywhere in
  the repo**, so it is a court fork before it is a build task.
- **Slice 5 is the biggest lever and is barely started.** `AssignmentAdmission` and
  `RootRoutingAdmission` exist, are durable and tested, and are **unreachable**: nothing constructs
  them, `ExecutionRootRun`/`ExecutionPhase`/`ExecutionWorkItem`/`RootRoutingFacts`, and `spawn.py`
  has no ledger references. The governing spec is `docs/proposals/codex-app-server-integration-map.md`
  (architecture accepted by decision 0012), with a staged plan PR 1 through PR 10.
- **Slices 6 and 7** (cutover + legacy removal, final gates) are pending.
- **Four security fixes landed this session** (SEC-164/165 pump principal capping, SEC-166
  cancellation barrier, SEC-167 MCP credential seam). **Five items remain open as court forks**
  from that list (#5, #6, #7, #8, #9, #11); verify their status yourself.

## Output: the plan

Write your plan to `docs/PATH-TO-10-PLAN.md`, in this shape, and give me the same as your reply:

1. **Corrected state.** Every place the ledger or a spec is wrong, with the code that proves it.
2. **Ranked workstreams to 10/10**, ordered by real leverage, one per axis or theme. For each,
   state what 10 looks like on that axis and the gap.
3. **Ordered steps** within each workstream. Every step carries: `what` (one line), `files`
   (the concrete paths), `kind` (`build` | `court-fork` | `external-dep`), `proof` (the exact gate
   or mutation the executor must pass), and `done-when`.
4. **Court forks**, listed separately, each with the options to put to the bench (no preference).
5. **External dependencies**, listed separately: what only I, the owner, can provide (a credential,
   an account, hardware, or authorization for an irreversible action).
6. **The single recommended first move**, and why it is the highest-leverage next step.

The plan must be executable by the executor without you present: concrete paths, concrete proofs,
no "figure it out later".

## How to work

Audit read-only first and establish the real state. Do not ask my permission to plan; produce the
plan and lead with what you found. State plainly what you could not verify and any place you are
guessing. The useful half of every report in this program has been the honest half.
