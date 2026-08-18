# Handover: the Worker structural floor, and what nothing was gating

Date: 2026-08-18

Written alongside `HANDOVER-2026-08-18-per-user-integration-credentials.md`,
which covers the feature. This one covers a red that was already there when
that feature landed, and the reason nobody had been told about it.

## Outcome

- PR #284 on `feat/real-brand-mark` had been red for six consecutive CI runs on
  `worker-build`. The cause is `worker-structure`: seven files from the Ultron
  and Jarvis-v2 bodies over the structural floor, plus ChatView's ratchet out of
  date. Every other job on that run was green, which is why it reads as noise.
- The seven are now under the floor rather than registered as debt. Branch
  `fix/worker-structural-floor`, one commit `d34c974d`, pushed.
- Merged against the current `feat/real-brand-mark` tip in a probe worktree, the
  tree passes: `node apps/worker/scripts/check-structure.mjs` PASS with
  `provenance=enforced`, `node --test apps/worker/scripts/check-structure.node.mjs`
  11/11 (the exact CI step that fails today), `tsc --noEmit` clean, vitest
  980/981. It merges with no conflicts.
- `docs/HANDOVER.md` no longer names a current handover.
- Nine commits that existed on one disk and no remote are now on origin.

## Why nothing local caught it

`core.hooksPath` is UNSET in the beelink clone, and `.git/hooks/` holds nothing
but samples. The repo ships `.githooks/pre-push`, a careful gate whose own last
line is the install step that was never run:

```sh
git config core.hooksPath .githooks    # RELATIVE. An absolute path makes every
                                       # linked worktree run one tree's hooks.
```

The `check` target's help text in the `Makefile` says "or just push - the
pre-push hook runs it". In this clone that sentence is false, and it is the kind
of false that reads as reassurance rather than as a gap.

boltrig is PUBLIC, so its Actions minutes are free and CI genuinely runs. It
just runs after the push, from a machine, once the branch is already public,
which is the whole thing the hook exists to pre-empt.

**It is still not enabled, deliberately.** The hook runs `visual-evidence`,
which fails by design for anyone with edits under `apps/worker/src`. Switching
it on while other sessions are mid-feature would block their pushes too. Turn it
on when the tree is quiet.

## Why the seven were fixed rather than exempted

Three independent sources say the catalogue is not the route for a new file:

- `docs/refactoring/ui-has-no-structural-gate.md`: "Legacy violations are not
  blanket exemptions", and the gate "rejects new or grown debt".
- History. Every prior commit touching `docs/refactoring/worker-structural-debt.json`
  LOWERS a ratchet. None has ever added a file. `debt_files` is still 63 after
  this change, as it was before.
- The tool. `node apps/worker/scripts/check-structure.mjs --candidate` refuses to
  emit an approval when new debt is present: "candidate would self-approve
  structural debt". The sanctioned generator will not do this for you, which is
  the design saying a person must decide.

So the files came under the floor:

| before | after |
| --- | --- |
| `bodyPresets.ts` 485 | 22, plus `jarvisPresets.ts` 264 and `ultronPresets.ts` 221 |
| `bodyTuning.ts` 466 | 20, plus `tuningScalars.ts` 54, `jarvisTuning.ts` 255, `ultronTuning.ts` 159 |
| `glslCommon.ts` 451 | 194, plus `glslField.ts` 264 |
| `neuralPasses.ts` 408 | 257, plus `neuralScene.ts` 219 |
| `ultronPasses.ts` 361 | 250, plus `ultronScene.ts` 160 |
| `JarvisNeuralRenderer.ts` 481 | 385, plus `jarvisFrame.ts` 108 |
| `UltronRenderer.ts` 405 | 379 |

The first three keep a barrel at the old path, so no call site moved. The two
pass files split along a seam that already existed, since each pass picks a
program, sets uniforms and draws; the ORDER stays in `drawScene`, because the
order is the part that carries meaning. Both renderers lose the voice-wave block
they each carried, into `apps/worker/src/components/canvas/voiceWave.ts` with the
two bodies' caps as tuning. Ultron's copy of that block already said "See the
same block in JarvisNeuralRenderer for why", so the duplication was known.

### Two things to know before reviewing the diff

**The draw order is unchanged, including where it contradicts its own comment.**
Ultron's iris pass says it is "Drawn FIRST". It is not: the dendrites precede it,
and they did before this split too. Left exactly as found, with a note saying so.
Whether the iris should go first is a rendering question for whoever tuned it,
not something a structural split may decide by moving a line.

**ChatView is recorded at its measured 1334/1253/102, which is a raise on the
branch's own 1331.** The three lines all come from `737f8f1f`: a doc comment, a
`takeaway` field, and the `??` that is the +1 complexity. It is still below
main's 1337, so the gate's provenance check against trusted baseline `7722f07d`
passes it as no new debt rather than as a raise. That is the gate's own
judgement, not an argument made around it. `refactoring-overrides.md` says
raising a ratchet needs explicit governance review; this is the reason no review
was sought, and it is the part of this change most worth a second opinion.

## Deliberately not done

**The visual-evidence receipt is the one remaining failure**, on my branch and on
the merge. `apps/worker/tests/visual/README.md` is explicit: any edit under
`apps/worker/src` invalidates a source-bound receipt by design, and the fix is to
run the capture lanes "after the UI has stopped changing", never to rewrite a
digest. The UI has not stopped changing: at least one other session was
committing to `apps/worker/src` while this was written. The recapture belongs on
the merged tree, once.

Also untouched: the `member` role, org-admin offboarding, per-connection health
and the workspace level, all of which the integration-credentials handover
already lists as out of scope.

## Other commits made today

On `feat/console-target`, four commits ending `cf71acfc`:

- `fca2ce33` The public-product gate asserted the character registry was exactly
  Familiar then Jarvis, while `51f79c7f` had already registered Ultron. Verified
  by running HEAD's copy of `scripts/validate_public_product.py` against the
  tree, which fails; the branch had been carrying a red gate since the character
  landed. Its PASS line also named only two characters and would have kept saying
  so while admitting a third.
- `4981365c` The adapter test `test_a_proxied_config_builds_an_unpinned_proxied_client`
  resolved `example.com` live, so a unit test about client construction depended
  on DNS. Its file lives only on `feat/console-target`, which is why it is named
  here rather than pathed: `make prose-references` correctly refused the path
  when this handover was checked from `fix/worker-structural-floor`.
- `cf6a19e6` The evidence receipts, ledgers and claim inventory that `003886f7`
  said "regenerate next". They had been regenerated and left uncommitted. Checked
  green before committing with `make vds-ledgers`, `make claims` and
  `make visual-evidence`, not assumed.
- `cf71acfc` A gitignore rule for `docker-compose.override.yml.*`. A 0600 retag
  backup had sat untracked since the 16th; the existing
  `docker-compose.override.*.yml*` rule does not match that shape. Proved with a
  probe file, then removed it.

On `feat/real-brand-mark`, `83e0f2bd`: `docs/HANDOVER.md` had said
`HANDOVER-2026-07-21.md` was "the current engineering handover" through sixteen
later handovers across eleven dates, the first landing two days after the pointer
was written. It stored a fact that changes, in a file nothing forces you to
touch when it changes. It now gives the derivation instead.

## Traps this cost time to find

**A worktree that is clean is not a worktree you own.** `boltrig-fixtree` swept
clean at the start and an hour later held 661 insertions of staged work from
another session. A `git stash push` scoped by pathspec still carries the whole
INDEX, so applying that stash elsewhere brings the other session's staged
changes with it. Their tree was restored and verified byte-identical. Check
immediately before writing, not once at the start.

**There are several concurrent sessions in this repo.** At the time of writing:
`boltrig-fixtree` on `feat/real-brand-mark`, `boltrig-wp1` on
`capability-doctrine-001`, and a third under a scratchpad path on
`feat/brand-mark-opbox-blue`. Both of the first two moved forward mid-session,
so the durability push had to be repeated. `git log --oneline --branches --not
--remotes | wc -l` is the check; it should read 0.

**`/tmp` on this box is tmpfs.** A worktree was registered at `/tmp/boltrig-clean`
holding 72MB of RAM on an 18GB machine, and it would have vanished on reboot
leaving a stale registration. Removed.

**Two of the worker tests are flaky under a loaded box**, and both failed once
and passed once in each of two trees: `tests/onboarding.test.tsx` "uses Enter to
continue without stealing Enter from an open picker", and
`tests/voiceLoudness.test.ts` "never lets the result clip". Neither is caused by
this change; the parent commit shows the same. Do not read a single red run of
either as a regression.

## Next

1. Merge `fix/worker-structural-floor` into `feat/real-brand-mark`. It is a clean
   merge and it turns `worker-build` green on the step that is failing.
2. Recapture the visual evidence on the merged tree, once the UI has settled.
3. Enable the pre-push hook when no session is mid-feature.
4. `docs/HANDOVER.md` being stale for four weeks was a symptom. Nothing checks
   that a pointer still points at something current, which is why it now derives
   rather than stores.
