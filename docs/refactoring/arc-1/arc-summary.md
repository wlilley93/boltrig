# Arc-1 summary

**Status:** preflight + plan complete (2026-07-01). Round-1 dispatch gated on the
arc-plan sign-off; first beat (channel route hoist) is the agreed template.

## Baseline (arc start)

| Metric | Value |
|---|---|
| In-scope files | 110 |
| Functions | 1040 |
| Package LOC | ~17,200 |
| Files over floor (>400) | 8 |
| Functions over floor | 55 |
| Tests passing | 195 (22 skipped) |
| Invariant gate | 96/96, debt 0 |
| API routes (baseline) | 72 |

## Security posture

No Critical/High findings. bandit B608 on `postgres.py:428` is a confirmed
false-positive (positional placeholders + bound args). One Low (dev CLI 0.0.0.0
bind), one Low (decorative path param), the rest defence-in-depth confirmations.
Dependencies clean (pip-audit 0, semgrep 0). SOC 2 ripgrep script is a documented
evidence gap, not a code defect. Full detail in `pre-arc/findings.md`.

## Floor-passing progress

| Round | Files passing floor | % | Notes |
|---|---|---|---|
| 0 (baseline) | 102/110 | 92.7% | the 8 god files + scattered over-floor fns |
| 1 (in progress) | 102/110 | 92.7% | channel store domain extracted (template proven); god files still over floor, one domain at a time |

## What "done" means for this arc

Every in-scope file under the 400-LOC floor and every function under the function
floor (or on `exemptions.txt` with a recorded reason), API surface diff clean vs
round-1 baseline, invariant gate green, no behaviour change bundled with structural
commits. Projected 3 rounds.
