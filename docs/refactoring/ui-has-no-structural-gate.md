---
tags:
  - refactoring
  - structure
  - ui
  - boltrig
created: "2026-08-10"
parent: refactoring
---
# The structural floor is Python-only, and the UI never had one

Recorded while closing `structural/round2-chat` unmerged (2026-08-10). The
branch is the reason this file exists, but the finding outlives it.

## The measurement

`scripts/check_structure.py` does not scan the repository. `scan_tree()` roots
at `repo_root / "boltrig"` and walks `*.py` under it; `_parse_function_baselines`
refuses any exemption path that does not start with `boltrig` and end in `.py`.
So the file-size and function-size limits — and the expiring debt ratchets that
make them bite — cover the Python kernel package and **nothing else**.

Nothing takes their place on the front end:

- `make ui-quality` runs `pnpm audit`, `typecheck`, `test:coverage` and `build`.
  None of those measure file length, function length or complexity.
- there is no eslint config in `ui/` at all, so there is no `max-lines`,
  `max-statements` or `complexity` rule to violate.

`apps/worker/` and `site/` are in the same position.

## Why that matters

A commit can claim `ChatPanel.tsx 211->239 LOC, max fn 190->79 LOC` and be
measured by nothing. The `structural/round2-*` family was written against a
floor that, for `.tsx`, was never enforced — several of those branches merged,
and the remaining one drifted for five weeks because no gate was failing to
force the issue.

This is a gap, not a licence. If the front end should hold a size budget, give
it one that runs in CI (an eslint `max-lines`/`complexity` rule in `ui-quality`
is the cheap version); until then, treat LOC figures in a TypeScript commit
message as a claim no machine has checked.

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
