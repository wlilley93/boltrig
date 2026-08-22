# Handover: the Familiar gets states, dials, and a seat on the bench

`feat/real-brand-mark`, 2026-08-19. Four commits on top of the offboarding work:
`d372e6d8`, `7c89f5e1`, `effce8bd`, `d2568268`. All pushed.

This is a per-topic handover in the usual convention, not a project status. The
decision it implements is
[`decisions/0030-familiar-modes-and-dials.md`](decisions/0030-familiar-modes-and-dials.md),
which amends 0025.

The session started as a question — is anything worth harvesting from orb-ui,
ElevenLabs UI or voice-orb-visualizer — and the answer was no, but finding out
took reading the whole stack, and three things fell out of that reading.

## The finding worth carrying to other features

**`micLevel` was declared by every character, read by two of them, and produced
by nothing at all.**

`CharacterTurnInput` has carried `micActive` and `micLevel` since the character
contract was written. `JarvisState.jarvisStateFromTurn` and its Ultron twin both
branch on them. Grep for a PRODUCER and there was never one: the only assignment
in the tree was a hardcoded `0.48` inside the onboarding preview's cycle table.
So Jarvis's listening waveform — a real pass, with a real dial — had been
integrating a constant zero since it landed, and it looked exactly like a body
that was choosing to be still.

This is the same shape as the defect `canvas/bodyEmotion.ts` opens with: ten
scalars arriving and three being read, under a `readsPhenotype: true` that
claimed otherwise. **A declaration nothing downstream honours reads as working
software**, because every layer in the chain is individually correct — the field
exists, the type-checks pass, the consumer branches on it — and the gap is
between two files that never mention each other.

The generalisation, which is cheap: when you add a field to a shared contract,
grep for who WRITES it, not who reads it. A consumer-only search is the search
that goes green. And in a UI whose whole job is to display state, a channel
stuck at its zero value is invisible: nothing throws, nothing renders wrong, the
body just looks calm.

The meter now comes from the barge-in gate, which is the second half of the
finding: **the work was already being done.** `voiceBargeIn.ts` polls the
microphone every 10ms and tracks what silence sounds like in this room, because
that is what deciding an interrupt requires. A level meter needs exactly that and
nothing more, so opening a second `AnalyserNode` and calibrating a second floor
would have been building a worse copy of a thing already running. Before reaching
for an analyser, look at what the audio graph already knows.

## The second finding: the capture digest reads the git INDEX

This cost the session two full recapture passes and it will cost the next one
the same unless it is written down.

Every edit under `apps/worker/src` or `apps/worker/tests/visual` invalidates the
source-bound capture receipts, which is by design and documented. What is not
documented is the ORDER:

    git add everything  →  capture  →  commit

`sourceDigest.mjs` walks `git ls-files`, so a NEW file that is still untracked is
invisible to it. Capture with new modules untracked and the receipt is honest
about a tree that will never exist; `git commit` then makes them tracked, the
digest moves, and the receipt you took ten minutes ago is stale on arrival. Seven
new modules landed in this work and the first recapture described a tree without
any of them.

Two more sharp edges in the same chain, both hit:

- **`--evidence` promotes `current/` atomically, which DELETES `diff/`,
  `metrics.json` and `vds-route-manifest.json`.** They are products of the later
  stages. The route manifest in particular has to be `git checkout`ed back before
  `scripts/regen_vds_route_manifest.py` can run, because that script carries its
  `routes` and `doesNotCover` governance declarations through untouched rather
  than inventing them, and fails with a bare "No such file or directory".
- **`vds ledger screens` records LINE NUMBERS.** Lifting the stage input out of
  `VoiceCall.tsx` moved a few dozen recorded anchors and `make vds-ledgers`
  reported it as several dozen missing elements rather than as a shift.

The full chain, which is four stages and only three of them are in
[`../apps/worker/tests/visual/README.md`](../apps/worker/tests/visual/README.md):

    node apps/worker/tests/visual/capture-current.mjs --evidence \
      --timeout-ms 45000 --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs
    node apps/worker/tests/visual/capture-current.mjs --additive-evidence ...
    python3 apps/worker/tests/visual/compare-current.py
    python3 scripts/regen_vds_route_manifest.py          # not in the README
    vds ledger screens
    vds ledger routes --from docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json

## What the Familiar now is

She had two booleans, `working` and `speaking`, where Jarvis and Ultron have five
states. She now has six.

| Mode | What it means | How she shows it |
| --- | --- | --- |
| `standby` | nothing is happening | gaze away, slowest wander, her own business |
| `listening` | your microphone is live | turned toward you, following your voice at a fifth of speaking gain |
| `thinking` | a turn is loading, nothing streaming yet | inward: gaze off, slow deep pulse, light down |
| `working` | a turn is streaming | outward, the shipped oscillator |
| `speaking` | outgoing voice is playing | the spectrum drives all four channels |
| `error` | the call dropped | one recoil into held tension and lost light |

Precedence, matching Jarvis exactly so two characters cannot disagree about what
the machine is doing: **failure > speaking > listening > working > thinking >
standby**.

Three decisions in it worth not re-litigating:

- **`error` is hers alone, not added to the shared `BodyMode`.** Adding it would
  force an entry into Jarvis's and Ultron's preset tables, and an empty delta
  there is a state the enum claims and the body does not honour — the exact
  defect this whole handover is about.
- **Error is not red.** Irritation is the shader's one colour term and it means
  she is annoyed WITH YOU. A dropped websocket is not a mood, and colouring it as
  one would make an infrastructure failure look like a personality.
- **Listening is carried by GAZE, not amplitude.** At the 96px porthole size,
  "brighter" is not a state anybody reads and "watching you" is. Wired at
  speaking gain the microphone makes her mouth your words back at you, which is
  uncanny in the bad way; that ceiling is why `listen` tops out where it does.

## Where the pieces live

| Piece | Where |
| --- | --- |
| The six modes, precedence, `familiarBusy`, the spoken label | `apps/worker/src/components/familiar/FamiliarState.ts` |
| The dials | `apps/worker/src/components/canvas/familiarTuning.ts` |
| Per-mode deltas + the arrival preset | `apps/worker/src/components/canvas/familiarPresets.ts` |
| Voice → drive: envelope, gate, beat, listening | `apps/worker/src/components/familiar/familiarDrive.ts` |
| The wandering mood and ambient gestures | `apps/worker/src/components/familiar/familiarMood.ts` |
| What the shader is told | `apps/worker/src/components/familiar/familiarUniforms.ts` |
| Renderer + the `setTuning` bench seam | `apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts` |
| The Stage's renderer lifecycle | `apps/worker/src/components/familiar/useFamiliarRenderer.ts` |
| The mic meter | `apps/worker/src/components/voiceBargeIn.ts`, `apps/worker/src/components/voiceBargeInGraph.ts` |
| Call → character contract | `apps/worker/src/components/voiceStageInput.ts` |
| The bench | `apps/worker/tests/visual/shader-bench.ts`, `.html` |
| Tests | `apps/worker/tests/familiarDrive.test.ts`, `apps/worker/tests/voiceMicLevel.test.ts`, `apps/worker/tests/familiarStage.test.tsx` |

**No line of `familiar.frag` moved.** Her look flows from `boltrig-familiar` and
`scripts/check_familiar_shader.sh` still binds the vendored copy to it.
Everything here is on the host side of the uniform push, which is precisely why
she could join the bench at all: there are no draw passes of ours to tune, but
there is a whole recipe deciding how she MOVES, and it was sixteen literals
scattered through a frame loop.

## Speaking: three fixes, one complaint

"Her pulsing is too jagged when she speaks" is answered from three sides, and
each side is a dial so the next person can disagree with the numbers by eye:

- **A silence gate that judges the whole frame once.** The playback analyser
  never reads zero — room tone, AEC residual and codec noise all sit a few
  percent up — so she twitched through every silence in a sentence. Gating each
  band against its own floor would have been the obvious version and is wrong: it
  lets a quiet frame through in whichever band is noisiest, which smears the
  spectrum, so the body answers the SHAPE of the noise floor.
- **A beat channel with an instant attack and a shaped tail.** Onset is positive
  spectral flux — a per-frame DIFFERENCE — so it spikes on the frame a syllable
  lands and collapses to zero on the next one while the vowel is still going.
  Sampled at ~30Hz and multiplied hard in five places inside the shader, raw
  onset is a strobe. Smoothing the attack would be the wrong fix in the other
  direction: it turns a beat into a swell, which is the exact moment being drawn.
- **Highs routed to the surface, not the nucleus.** `uAudio.w` lights the
  filaments and `uAudio.y` pressurises the nucleus; letting consonants into the
  level channel made every sibilant read as a shout.

The envelope's asymmetry was already there and is kept: fast up, slow down. A
symmetric envelope slow enough to be calm also arrives late, and a body moving
after its own voice is worse than one moving too much.

## The bench

`apps/worker/tests/visual/shader-bench.html` now has three bodies. Open it from the intranet
card at `:3000`, which hands over the token; it is `BOLTRIG_BENCH_TOKEN`-gated
and the secret lives only in `/etc/boltrig-bench.env`.

Sixteen dials under five headings, zero ungrouped, plus the ten emotion
registers. Every slider takes an LFO — measured sweeping `listen` from 0 to 0.47
on a raised cosine while the render stayed live — and **Copy settings** prints
something that pastes straight into `familiarTuning.ts`.

It drives the SHIPPED renderer through `setTuning`, not a copy of the recipe. A
bench that rebuilt the passes would drift from them and then be tuning something
nobody ships; that argument is the bench's own, and she is on it on those terms.

For a ten-second answer without a browser:

    node apps/worker/tests/visual/render-bodies.mjs \
      --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs \
      --body familiar --mode standby --mode listening --mode speaking --mode error

A GLSL error in the vendored shader is otherwise SILENT — the renderer removes
its canvas and the Stage looks like a CSS problem.

## What is measured, and what is not

Measured, offscreen at 512², six modes, `white 0.0000` throughout:

| mode | sat | val |
| --- | --- | --- |
| standby | 0.4479 | 0.5133 |
| listening | 0.4443 | 0.5037 |
| thinking | 0.4154 | 0.5255 |
| working | 0.4209 | 0.4989 |
| speaking | 0.3444 | 0.5525 |
| error | 0.5369 | 0.4097 |

**Listening and standby are almost identical in those numbers, and that is the
instrument's fault rather than the mode's.** The difference between them is
gaze, which moves a pupil and not a histogram, so whole-frame statistics report
"no difference" about the difference that is the entire point of the state. It
is checked at the uniforms instead — `uGaze` above 0.9 listening against below
0.2 standby, `uAttention` higher, `uAudio.x` below speaking — in
`familiarStage.test.tsx`. If you are judging listening by eye, judge it moving.

**Not measured: mobile.** The only performance figure that exists for her is a
native C bench, 4.35ms worst case at 1080p on a 680M, quoted in 0025. Her voice
presentation renders roughly 700k fragments at ~20 vnoise calls each. Nobody has
put her on a phone. Device-pixel-ratio is capped at 1.25 compact and 2 in voice,
`document.hidden` stops the loop, and reduced motion drops to 1fps with the inner
life frozen — but none of that is a measurement.

## What was NOT done

- **`feat/console-target` is untouched.** The bench does not exist on that branch
  and its Familiar is a version behind, so a cherry-pick would be a mess. These
  two want a deliberate merge, the way the Opbox-blue mark met the bodies branch.
- **No library was adopted.** orb-ui and ElevenLabs UI are React-first wrappers
  around a canvas or a three.js sphere; every one of them is a downgrade from a
  2,000-line corneal-refraction shader with a capability-derived genotype. The
  only thing worth reading in orb-ui is its adapter PATTERN, and only if boltrig
  ever fronts Vapi, LiveKit or Pipecat. Licensing was checked and is a non-issue:
  there is no third-party shader provenance anywhere in `familiar/`, `jarvis/` or
  `ultron/`.
- **Cursor-tracking gaze is still deferred**, as 0025 left it. `uGaze` is driven
  by whether she is being spoken to, not by where your pointer is.
- **Nothing ran in CI.** GitHub Actions is still billing-blocked, so the beelink
  run is the only verification this branch has.

## Gate state at the tip

1011 tests across 113 files, `tsc` clean, worker structure gate PASS with debt
files 63 → 62 (`FamiliarWebGLRenderer.ts` left the list entirely, 435 → 340
lines), `make vds-ledgers` clean at 15 screens / 1644 references / 6
visual-review routes, `make commit-trailers` PASS, `make prose-references` 0
unresolved. Both capture receipts carry source digest `5be1b5db` and remain
`captured_unreviewed` with a `not_assessed` verdict. Neither is a sign-off.
