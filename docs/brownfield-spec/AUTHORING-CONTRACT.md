# Boltrig brownfield spec: authoring contract

Every spec file in this corpus is written against ONE referent and obeys this
contract. Read it fully before writing anything.

## The referent (pinned, non-negotiable)

    repo    wlilley93/boltrig
    branch  origin/main
    commit  19bcae7fa81663fe8998377c86451ba08fb16e48
    tree    /var/tmp/claude/claude-1011/-home-jellytot/f7f5f72e-a248-4744-a573-952de9fdf71f/scratchpad/bt-spec

Read ONLY that tree. Do not read `/home/jellytot/Projects/boltrig` (dirty, on a
feature branch), any other `boltrig-*` worktree, or any deployed stack. If a
claim cannot be grounded in the pinned tree, it is not a claim, it is a question
and belongs in the OPEN QUESTIONS section.

## What this corpus is

A reverse-engineered specification of Boltrig AS BUILT. Not a design document,
not a roadmap, not a review. It answers: if this system were gone, what would
someone need to know to rebuild it and to operate it?

Two depths, both required, kept visibly separate:

- **SYSTEM depth** - what the code is and does: objects, contracts, control
  flow, data, boundaries, failure modes.
- **PROCESS depth** - what a human or agent DOES with it: the procedures, the
  order, the gates, the recovery paths. A spec that only has SYSTEM depth is
  half a spec and this has bitten this estate before.

## Citation rules

Every factual claim carries a citation. Format:

    [`path/to/file.py:123`](../../../path/to/file.py) `"a short verbatim anchor"`

The `path:line` is relative to the repo root. The verbatim anchor is 3 to 10
words copied EXACTLY from that line or its immediate neighbour. Line numbers rot;
the anchor is what makes the citation re-findable after drift. A citation with no
anchor is not acceptable.

Never cite a line you did not open and read. Never cite from memory of a similar
codebase.

## Confidence and status vocabulary (use these exact words)

Every requirement row and every load-bearing paragraph is tagged:

- **IMPLEMENTED** - the code path exists, is reachable from a real entrypoint,
  and is exercised by a test you can name.
- **IMPLEMENTED-UNTESTED** - code path exists and is reachable, no test found
  (say where you looked).
- **SCAFFOLDED** - the shape exists (types, signatures, routes) but the body is
  a stub, a `NotImplementedError`, a typed-unavailable return, or a constant.
- **SEAM** - deliberately unimplemented here because an external system supplies
  it (live IdP, live Hatchet, third-party credential, on-box model). Name the
  external thing.
- **DEAD** - present in the tree but unreachable. Prove unreachability or
  downgrade the tag to UNCERTAIN.
- **UNCERTAIN** - you could not settle it. Say precisely what you checked and
  what would settle it. This tag is honourable; a wrong IMPLEMENTED is not.

## Bounded search discipline

If you conclude "X does not exist" or "nothing else calls Y", you MUST state the
bound of the search that produced it, inline:

    No other caller (bounded: `rg -n "resolve_credential\(" boltrig/ tests/ apps/`,
    2026-08-24, pinned tree).

An unbounded absence claim is a defect in this corpus.

## Requirement rows

Each spec ends with a requirements table. IDs are pre-allocated per area (your
prompt gives you your block) so parallel authors never collide. Row shape:

| id | statement | status | evidence | invariant |

- `statement` - one sentence, testable, present tense, no hedging.
- `status` - from the vocabulary above.
- `evidence` - `path:line` plus anchor, or a test node id.
- `invariant` - the `K-*` / `P*` / `SEC*` / `FR*` id from `tests/invariants.yaml`
  that binds it, or `-` if unbound. An unbound security or correctness
  requirement is itself a finding: record it in your RISKS section.

Also append every row, tab-separated, to `docs/brownfield-spec/registers/requirements.tsv`
using `>>` append only. Never rewrite that file; another agent is appending to it
at the same time.

## Section order for every SPEC file

1. Front matter: `area`, `id-block`, `referent commit`, `author-agent`, `date`.
2. **Purpose** - what this subsystem is for, in three sentences.
3. **Boundaries** - what it owns, what it must not touch, which imports are
   forbidden and by what rule.
4. **Objects and contracts** - the nouns, their fields, their lifecycles.
5. **Control flow** - the ordered steps of the main path, each step cited.
   Prefer a numbered list over prose. Include the failure branch of each step.
6. **Data** - tables, columns, migrations, indexes, retention, encryption.
7. **Configuration surface** - every env var and manifest key that changes this
   subsystem's behaviour, with its default and what breaks if it is wrong.
8. **PROCESS** - the human/agent procedures: how it is brought up, changed,
   rolled, recovered, diagnosed. Cite runbooks and Makefile targets.
9. **Failure modes and fail-open/fail-closed posture** - for each guard, say
   which way it fails and prove it from the code.
10. **What is proven** - the invariants and tests that bind this subsystem.
11. **RISKS** - things that look wrong. One line each, prefixed `RISK:`, cited.
    Do not fix anything. Do not edit code. Record.
12. **OPEN QUESTIONS** - what you could not settle and what would settle it.
13. **Requirements table.**

## Hard rules

- Do NOT edit, refactor, or fix any code. This is a read-and-record job.
- Do NOT run the test suite, `docker`, `docker compose`, `make` targets that
  build or start anything, `pytest`, `npm`/`pnpm install`, or any command that
  writes outside `docs/brownfield-spec/`. This host has been billed by careless
  gates before. Reading commands (`rg`, `sed -n`, `cat`, `git log`, `git show`)
  are fine.
- Do NOT write outside `docs/brownfield-spec/`.
- No em dashes anywhere in your output. Use a comma, a colon, or a full stop.
- Prefer the finding to the journey. No "I then looked at". State what is true.
- Length is not a virtue but completeness is. Do not summarise away a contract.
