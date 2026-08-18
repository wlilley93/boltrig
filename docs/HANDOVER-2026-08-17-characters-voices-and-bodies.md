# Handover — characters, voices and bodies, 2026-08-17

> **Superseded by `4b392a21`, later the same day.** Everything under "Outstanding
> work" below has been closed except two items, both waiting on something only
> the account holder can supply — Familiar's register audio needs Fish Audio API
> credit, and the deployed voice container needs its swap authorising. Each is
> marked in place. The rest of the document is left as it was written: it is the
> record of how the work got here, and the reasoning in it is still the reasoning.


Branch `feat/real-brand-mark` in `~/boltrig-fixtree` on the beelink
(`jellytot@192.168.50.2:24222`). Three commits landed and three static deploys
went to `dev.boltrig.io`, each verified by digest match and three 200s.

`~/Projects/boltrig` on the beelink is **another session's tree**. Do not touch
it. Stage by explicit path; never `git add -A`.

---

## What is live

| commit | subject |
| --- | --- |
| `1d01b4d0` | slow the holograms down, stop the centre burning white |
| `f127e663` | lose the flares, lose the inner card, square the lamps |
| `e919d07f` | put the canonical mark in the favicon |

Every one: 955/955 worker tests, `tsc` clean, structure ratchet green, VDS
ledgers clean, four-stage visual evidence pipeline re-run for both the governed
seven-state and the additive lane.

**Colossus's voice is settled and shipping**, and it is the one thing here that
was verified by ear as well as by measurement.

---

## Jarvis V2 and Ultron — where the avatars actually stand

The plan in `~/.claude/plans/swirling-zooming-sundae.md` is **built**. Phases
2–5 are all in the tree: `skins` in the Jarvis bundle, `assertSkins` in
`characterBundle.ts`, `CHARACTER_SKIN_SETTING_KEY` in `character.ts`, the
carousel (`CompanionCarousel.tsx`, `SkinPicker.tsx`, `companionCatalogue.ts`),
preview clips for all four characters, and `previewAudioSignal.ts` driving the
preview from the clip that is playing rather than from a timer. What remains is
not plan phases. It is the look.

### Landed this session, and NOT yet judged by eye

Nobody has looked at either body since these went in. That is the first thing
the next session should do, because several of them interact.

- **Advection halved.** Four copies of `curl(p) * (0.55 + 0.85 * uEnergy)` —
  `shadersSim`, `shadersField`, `shadersRing`, `shadersUltron` — collapsed into
  `flowSpeed()` in `FIELD_GLSL` at `0.26 + 0.40 * energy`. The four had to
  agree: SIM moves a particle by `curl * flowSpeed * dt`, and each draw pass
  puts the streak's TAIL at `p - curl * flowSpeed * uStreak`. Drift there points
  the motion blur the wrong way, silently.
- **Streak length preserved.** `uStreak` raised by the reciprocal at both call
  sites (Jarvis `0.024+0.020e` → `0.051+0.042e`, Ultron `0.052+0.040e` →
  `0.110+0.085e`), so only the pace moved.
- **Jarvis's exterior RINGS are off.** Not deleted — the shaders stay in
  `shadersRing.ts` and restoring them is one import. Both references ask for
  them (Ebb's audio-reactive rings, Territory's rings around a spherical base),
  so this is a departure, recorded at the call site so nobody "restores a
  missing pass".
- **Ultron's petals `1.0 → 0.3`.** He has no rings; his flares were the arms.
  Not 0, because at 0 he is Jarvis in blue and the references separate the two
  by silhouette as much as colour.
- **Embers inverted.** `1.0 + 1.6 * ember(p)` → `1.0 - 0.85 * ember(p)` in both.
  It had been deliberately BRIGHTENING whatever escaped the shell, so the few
  particles outside were also the most visible things on screen.
- **Containment.** Radial spring `3.0 → 6.0`; migrating particles capped at
  `mix(0.34, 0.90, s)` instead of reaching `1.0`, since there are no longer
  rings out there for them to travel to.
- **Composite alpha follows luminance.** Was a hard `1.0`, which made every
  particle body an opaque black rectangle no CSS could defeat. Contexts are
  already `premultipliedAlpha:false` and the composite runs with blending
  disabled, so the value reaches the compositor intact.
- **Centre.** The white block through the iris was the anamorphic starburst — a
  gaussian 4000 tight in y against 26 in x, i.e. a bar fifteen times wider than
  tall, in the hot colour. Off for both holograms, kept in the shader because
  Colossus is a CRT where a horizontal streak off the beam is correct. Core
  lobes moved to the warm end; Ultron's core was nearly twice Jarvis's and now
  matches.

### Outstanding — Jarvis

1. **He is "still a way off" from the reference, and the rings were half the
   structure.** The reference frame is a DENSE globe: visible great circles,
   hard-edged circuit blocks, a bright limb, a legible interior. With the rings
   gone the interior has to carry that structure alone, and it currently does
   not — the LINK pass runs at `uGain: 0.10 + 0.10 * energy`, which is the
   dimmest thing on screen. Raising LINK and widening `uLinkRange` (0.16) is the
   cheapest experiment and has not been tried.
2. **Shard density is untuned since the flares came off.** `SHARD_STRIDE = 11`
   over 16,384 particles is ~1,490 quads at `uSize: 0.016`. They were scattered
   wide when the field threw material out; now that it is contained, they may be
   too sparse to read as circuitry.
3. **The reference's angularity is a shard-shader question, not a count.**
   Animal Logic's Jarvis is "angular shapes mimicking computer circuitry", and
   whether `SHARD_FRAG` currently draws hard-edged fragments or soft glints has
   not been checked against a render this session.

### Outstanding — Ultron

1. **"Very chaotic and not nice to look at" was never fully diagnosed.** The
   petal reduction addresses the reaching arms. It does not address the likely
   second cause: **his draw gains are far higher than Jarvis's.** `crack` runs
   at `0.72 + 0.50 * energy` and `facet` at `0.78 + 0.55 * energy`, against
   Jarvis's shard pass at `0.42 + 0.30`. His `uLinkRange` is 0.26 against
   Jarvis's 0.16, so the web is denser as well as brighter. That combination is
   a good candidate for "chaotic" and is untouched.
2. **`FACET_STRIDE` and `uSize: 0.030`** — nearly twice Jarvis's shard size,
   also untouched.

> **CLOSED.** The harness exists (`apps/worker/tests/visual/render-bodies.mjs`),
> both bodies were judged by eye against it, and both were retuned: the gain
> ORDER was inverted in each, and `flow()` in the shared GLSL chunk now strips
> the radial component for particles on the shell, so streaks lie along the
> sphere instead of bristling off it. That is what turned Jarvis from fur into a
> globe, and it was the reason neither body read as one.

### The gap that makes all of the above slow

**There is no offscreen render harness in this tree.** The plan refers to
`scratchpad/compile_v2.mjs` and `scratchpad/render_v2.mjs`; neither exists here,
and `scratchpad/` does not exist. So every visual judgement costs a full build
and static deploy, and a GLSL compile error is silent at runtime — it shows only
as a fallback.

Playwright is not a dependency of `apps/worker` and **must not become one**
(`apps/worker/package.json` is public graph). It is available at
`/home/jellytot/Projects/waymark/node_modules/playwright/index.mjs`, and the
visual capture script already accepts `--playwright <abs path>`. A small
harness that lifts the shaders from source, compiles them, renders at three
energies and reports **mean saturation of the centre 25% of the frame** would
pay for itself immediately — that number is the one that catches the
white-saturation defect which has now cost three tuning rounds.

---

## Colossus's voice — settled

`pocket-voice` on the M4 (`~/Projects/pocket-voice`, loopback `:8911`). **Never
give it a git remote.**

**The mechanism is general, not a Colossus branch.** Any voice may ship
`voices/<name>.chain.json` and gets the same treatment; a voice without one is
untouched, which is every other voice. `chain.py` implements the graph;
`apply_chain` in `server.py` runs it at the single chokepoint both `/speak` and
`/v1/audio/speech` pass through.

**Where the settings came from.** `~/Desktop/colossus-audition/mixer.html`, a
four-channel browser bench served by `python3 -m http.server 8770` from that
directory. Each channel has its own vocoder, EQ and harmonix, loops in sync, and
**Copy settings** exports the JSON that `chain.py` consumes verbatim. That
verbatim consumption is deliberate: a transcription step between the thing that
was heard and the thing that runs is where "why does it sound different now"
comes from.

Shipped configuration, in the order it was decided by ear:

| stage | value | why |
| --- | --- | --- |
| clone | `colossus-c3` | chosen by ear from five auditioned through the chain |
| `rate` | 0.85 | slower delivery |
| channel 1 `voc.wet` | 0.70 | more fixed-pitch carrier = flatter, less sing-song |
| channel 1 `gain` | −13 dB | the clone sits under the vocoder, not over it |
| `ex.lfo` | 0.11 Hz, drive ±25%, amount ±3 dB, xover ±22% | the harmonizer drifts rather than sitting still; the two channels are phase-offset so they breathe out of step |
| `masterEq` | +14 dB low shelf @ 110 Hz | bass |
| `masterLimit` | +8 dB drive, 0.94 ceiling | loudness: RMS −19.7 → −13.7 dBFS |

**Verified:** live output matches the approved bench render at RMS −13.7 vs
−13.8 dBFS, peak 0.94 both, energy below 200 Hz 23.5% vs 23.4%. Costs 0.34 s per
11 s of speech.

### Four traps found here, each of which cost a round

1. **Gain staging in front of a saturator.** The chain contains `tanh` at drive
   20. A saturator is defined by the level it SEES: the bench normalised its
   clip to unity, the model's raw output peaks well below that, and `tanh(20x)`
   on a quiet signal is not a saturator at all — it is a linear +26 dB boost on
   the high band. Measured 24% of energy above 4 kHz against the approved 2.5%.
   `apply_chain` now normalises before the graph and it is not cosmetic.
2. **`ffmpeg` by bare name under launchd.** The rate stage shells out to
   `atempo`. launchd's PATH is the system minimum — no `/opt/homebrew/bin` — so
   `subprocess.run(["ffmpeg", ...])` raises `FileNotFoundError` there while
   working perfectly from a shell. The caller fails open, so the symptom was not
   an error: the voice quietly served unprocessed, which sounds like a working
   voice with the wrong settings. `_ffmpeg()` now resolves an absolute path.
3. **A duplicated graph drifted within one session.** `chain.py` existed twice —
   a bench copy and a server copy — and a `cp` of the bench copy silently
   replaced the server's adapted `render()`. The chain stopped applying and
   failed open. There is now ONE `render(settings, source, sr)` that takes
   either a dict of clips (bench) or a single array (server).
4. **Two Colossus clones are broken, not dark.** `colossus-L1` emits 52–60% of
   its energy above 4 kHz across three separate rolls, and `L2` 25%. That is
   hiss. `c1`/`c3` sit at 1.5–3.1%. Pocket TTS is non-deterministic, so one
   render is not a measurement — but three rolls each is, and these are
   genuinely bad clones. The previously shipped `colossus.safetensors` was one
   of them; the old file is kept as `colossus.noisy-backup.safetensors`.

**Why a match-EQ could not have worked**, since it will be suggested again: the
earlier attempt transplanted the film's long-term average spectrum onto the
clone and was rejected by ear. An average spectrum can only redistribute what
the model already produced, and nothing in a humanised clone is the buzz of a
carrier. `voices/colossus.eq.npy` is deleted.

---

## Outstanding work, everything else

### Asked for and not started

1. **Contractions in all prompts.** "It's" not "it is", "I've" not "I have".
   Scope I would take: the fenced sections that actually reach the model —
   Familiar §45, Jarvis §27, Ultron §25, Colossus §48 — not the whole 9,256-line
   constitution set, unless told otherwise. **Contract by judgement, not by
   regex:** a contraction cannot end a clause ("I know what it is", never "I
   know what it's"). Regenerate `personas_shipped.py` and expect
   `test_the_bundle_carries_its_document_section_VERBATIM` to need its expected
   text updated in the same change.

   > **DONE.** 27 edits by judgement across Familiar, Jarvis and Ultron. Colossus is deliberately exempt: his own shipped prompt instructs the model to avoid contractions, so contracting it would break its own instruction on the same page, and his formality is the character. The VERBATIM test needed no expected-text update — it derives the expectation from the document, so re-syncing each bundle from its section was the whole change.

### Asked for, partly done

2. **Bella's ASMR voice.** Joi v2 is installed as
   `pocket-voice/voices/bella-asmr.safetensors` and works. Nothing declares it
   as her secondary voice. The user's framing — "a secondary voice, enabled if
   asked" — is already satisfied mechanically by the per-character voice
   override (`VOICE_OVERRIDE_SETTING_KEY`), so what is missing is the
   declaration and the register documentation in the private repo
   (`~/Projects/boltrig-companion` **on the beelink**, not the M4). Bella is
   private: her constitution must not enter the boltrig tree, because
   `personas_shipped.py` travels inside the kernel container to every
   deployment.
3. **Colossus's ticker should show a 5–6 word takeaway of the message being
   spoken.** Blocked on a contract change, and it is a public-graph one:
   `CharacterTurnInput` in `sdks/web/src/characters.ts` carries `loading`,
   `hasLiveEvents`, `liveEnded`, `voiceSpeaking`, `voiceLevel`, `voiceBands`,
   `voiceOnset`, `micActive`, `micLevel` — **no text at all**. A body cannot
   show words it is never given. The ticker's speed and its one-shot arrival
   sound are done; the content is not.
4. **Familiar's new voice has no registers.** `c8f64deb39914cfca7f47ccfc3bca82f`
   is a base clone only, where Jarvis and Bella have seven each (calm, bright,
   warm, tender, serious, urgent, amused). Note that a TTS reference is a
   PERFORMANCE — the clone learns phrasing and subject matter, so each register
   needs its own script rather than the same line read differently.
5. **Joi v2 into the me-lora voicebox.** Cloned; voicebox reads
   `~/me-lora-voice-refs/<name>/<register>/` and the entry was never created.

   > **DONE.** Filed as `bella/asmr` — the only directory name that clones to `bella-asmr` — with a hand-written manifest, because `make_manifests.py` has no LINES for a register that is really a second clone. The stale `joi` tree was byte-identical to `bella` across all eight registers and pointed at clone targets that do not exist, so it is retired rather than left to be trusted.

   > **BLOCKED, on billing.** All 48 lines are written and committed in pocket-voice's `make_registers.py`, in her own register rather than Jarvis's — hers are about the person's work, his report kernel load, and a clone inherits the subject matter permanently. Fish Audio answers 402 "Insufficient API credit" on every model including the free tier, with the key authenticating, so it is a billing state. With credit: `./make_registers.py --char familiar`, then `./make_manifests.py --char familiar`, then audition and clone the picks.

   > **DONE.** `CharacterTurnInput.speechTakeaway` carries one bounded phrase, and it is a QUOTATION rather than a summary — the opening clause of what he is saying, which cannot misreport the reply. Every other field in that interface stays a fact about the turn.

   > **DONE.** `bella-asmr` is recorded in her constitution as the secondary voice, with its register and the mechanism that reaches it, and it is deliberately NOT declared in `register.ts` — a declared voice is one the host may choose, and this one is chosen by the user. Both clip characters gained a `voiceIds` passthrough on the way: Maya's blurb had claimed a voice since she was written and eight clones sat where nothing could reach them.

### Found on the way

6. **The desktop app icons are a THIRD variant of the mark.**
   `apps/worker/src-tauri/icons/` carries a three-ring version, where the
   favicon now carries the canonical five and `BrandMark.tsx` always did.
   Deliberately not changed here: those are the signed desktop app's icons, and
   changing them belongs with a release rather than with a static preview
   deploy.
7. **Familiar's voice on prod is unverified.** Her bundle names
   `pocket-voice: familiar` and the M4 has `familiar.safetensors`. The dev
   deployment's TTS is a self-hosted container on `jellytot-prod`, and whether
   it carries that voice was never checked. If it does not, she falls back or
   fails, and it would look like a bundle problem.
8. **The mixer is not in any repository.** It lives at
   `~/Desktop/colossus-audition/mixer.html` with its stems. It is the tool that
   decided the voice and will be wanted again for the next character; it
   currently exists in exactly one place with no backup.
9. **One flaky test.** `apps/worker/tests/onboarding.test.tsx > keeps onboarding
   copy focused on the user's choices` failed once in a full run and passed in
   isolation and in every subsequent full run. Not investigated. Cross-file
   interaction rather than an ordering bug, most likely.

   > **FIXED**, and the mechanism is written into the entry above.

   > **DONE.** `me-lora/tools/voice-mixer`, pushed. Its DSP was worse off than the mixer: `octave.py`, `vocoder.py`, `matcheq.py` and `wire_eq.py` existed only in an ephemeral `/private/tmp` session scratchpad and nowhere else on any machine.

   > **CHECKED, AND IT WAS WORSE THAN THAT.** She 404'd, and so did Ultron and Colossus — only Jarvis spoke. The image predated the manifest change that moved her off the `vera` catalog voice, and its `server.py` predated the chain entirely, so Colossus's whole voice would not have run either. `boltrig/pocket-voice:1.2` is built and on jellytot-prod with all four voices, ffmpeg, scipy and `chain.py`; verified by a throwaway container serving all four and logging the chain. **The container swap itself is still owed.**

   > **DONE.** Regenerated from `public/favicon.svg`, so they cannot drift from it. Not release work after all: they are source assets that take effect at the next desktop build, and the inset geometry of the replaced set was kept — measured off it, because a full-bleed icon reads as oversized on an application grid.

   Since fixed, and it was not cross-file: vitest isolates by fork, so no other
   file could reach it. `await findByText("Add vision")` was satisfied by a
   LOADING state -- the Suspense skeleton and the pre-readiness step paint the
   same heading -- and the synchronous `getByRole` on the next line then raced a
   dynamic import against one macrotask turn. `--sequence.seed=7` reproduces it
   every time.
10. **Familiar's voice tests were rewritten, not renumbered.** Two carried a
    REASON in their name that went stale when she moved off `vera`: the
    licensing guard now names the CC-BY-NC voices (`cosette`, `jean`) it exists
    to keep out rather than pinning one permitted value, and "names no cloud
    voice id" became "always names a LOCAL one" — which is the property that
    actually keeps the stock build free of a vendor account, now that every
    character declares both a local and a fish id.

---

## Reproducing the environment

**Deploy to `dev.boltrig.io`** (from the beelink, `~/boltrig-fixtree`):

```sh
cd apps/worker && VITE_API_BASE=https://dev.boltrig.io ./node_modules/.bin/vite build
TS=$(date -u +%Y%m%dT%H%M%SZ)
# digest the local dist, tar it to jellytot-prod as dist.candidate-$TS, compare
# digests, rsync --ignore-existing the live assets in, then atomically swap and
# restart boltrig-dev-preview.service. Full procedure in docs/DEPLOYMENT.md.
```

Verify with three 200s (`/`, `/healthz`, `/readyz`) **and** by grepping the
served index for the `index-*.js` hash the build just produced — the endpoints
return 200 from the old tree too.

**Visual evidence pipeline** — required after any `apps/worker/src` edit, and
**stage first**, because `sourceTreeDigest` reads the git INDEX:

```sh
PW=/home/jellytot/Projects/waymark/node_modules/playwright/index.mjs
node apps/worker/tests/visual/capture-current.mjs --additive-evidence --playwright $PW
node apps/worker/tests/visual/capture-current.mjs --evidence --playwright $PW
python3 apps/worker/tests/visual/compare-current.py
python3 scripts/regen_vds_route_manifest.py
vds ledger screens && vds ledger routes --from docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json
make vds-ledgers
```

**The structure ratchet is never raised.** When `FamiliarWebGLRenderer.frame`
went over, the fix was extraction to `familiarDrive.ts` on a real seam —
arithmetic on reported numbers, no GL — and the ratchet then *required lowering*
(102 → 49 lines, complexity 24 → 12, over-limit functions to empty).
