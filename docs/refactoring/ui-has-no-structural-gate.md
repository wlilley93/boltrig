---
tags:
  - refactoring
  - structure
  - ui
  - boltrig
created: "2026-08-10"
updated: "2026-08-12"
parent: refactoring
---
# The Worker structural gap and its enforced closure

Recorded while closing `structural/round2-chat` unmerged (2026-08-10). The
branch is the reason this file exists, but the finding outlives it.

## Resolution (2026-08-12)

The Worker gap is closed. `apps/worker/scripts/check-structure.mjs` uses the
pinned TypeScript compiler to measure every `.ts` and `.tsx` file under
`apps/worker/src`. Clean code is held to the agents-final floor: 400 physical
file lines, 80 function lines, five parameters, cyclomatic complexity 15 and
nesting depth four. The scan refuses to pass if it sees fewer than 100 source
files.

Legacy violations are not blanket exemptions. Each one is recorded in
`docs/refactoring/worker-structural-debt.json` with exact current file maxima,
an exact source-ordered record for every over-limit function, an owner, a reason
and an ISO expiry. The gate rejects new or grown debt and also rejects a
stale-high record after an improvement, so every extraction lowers the ratchet
in the same change. Duplicate JSON keys, missing files, malformed metadata and
expired entries fail closed.

`make worker-structure` runs both the seeded checker tests and the live-tree
check. `worker-quality` depends on it, and the CI Worker job runs
`worker-quality`. This closure is bound as `NFR-MNT-07`. The site remains out of
scope for this Worker-only gate.

## The original measurement

`scripts/check_structure.py` does not scan the repository. `scan_tree()` roots
at `repo_root / "boltrig"` and walks `*.py` under it; `_parse_function_baselines`
refuses any exemption path that does not start with `boltrig` and end in `.py`.
So the file-size and function-size limits — and the expiring debt ratchets that
make them bite — cover the Python kernel package and **nothing else**.

At the time, nothing took their place on the front end:

- The former frontend quality target ran package audit, typecheck, coverage and
  build, but none of those measured file length, function length or complexity.
- The former frontend had no eslint config, so there was no `max-lines`,
  `max-statements` or `complexity` rule to violate. That frontend is now
  retired; the Worker is the maintained browser source.

`apps/worker/` and `site/` were in the same position. The resolution above now
covers the Worker; the site remains separate.

## Why that matters

A commit can claim `ChatPanel.tsx 211->239 LOC, max fn 190->79 LOC` and be
measured by nothing. The `structural/round2-*` family was written against a
floor that, for `.tsx`, was never enforced — several of those branches merged,
and the remaining one drifted for five weeks because no gate was failing to
force the issue.

This was a gap, not a licence. NFR-MNT-07 now makes Worker size and complexity
claims machine-checkable in CI.

## Why `structural/round2-chat` was closed rather than merged

Merging it would have cost two real regressions to buy a decomposition no gate
requires:

- **The channel hooks would have gone backwards.** The branch extracts
  `useBindingList`/`useChannelRow` as they stood in July: direct
  `api.bindChannel` calls with hand-rolled `busy`/`error` state. Main has since
  moved both onto `useControlMutation` with `onPendingDenied`. Taking the
  extracted files swaps the governed mutation path back out for hand-rolled
  fetch handling.
- **`ChatPanel` would have reverted with it.** The branch's decomposition was
  built on older JSX: it passes `setInCall`/`setCallSeconds` to `ChatHeader`
  and `switchDir`/`switchCount` to `ChatMessages` — props main no longer
  passes — and restores inline styles main moved into CSS.

The decomposition itself is still a reasonable shape. Redoing it means applying
that shape to main's current implementations, not merging July's copies of
them; the branch cannot be rebased into correctness, because the conflict is
semantic rather than textual.
