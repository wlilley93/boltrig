# Handover: the character canon, and getting it live

Written 2026-08-22 by the session that ported Jarvis, Ultron and Colossus from
the bench into the app. Everything below is on branch `bench-unified` and
**none of it is deployed**. Read the first two sections before touching
anything; they are the two ways this work can be destroyed by accident.

---

## 1. The canon is not in git

`tests/visual/presets.json` holds every saved character look — the whole point
of the bench — and it is **gitignored** (`.gitignore:82`). There is exactly one
copy, on the beelink, in the working tree.

That means:

- **Never `git clean -x`, never delete the worktree, never restore it from a
  fresh clone.** A clone has no canon and nothing will tell you it is missing;
  the bench simply starts from the shipped presets as though nothing was ever
  tuned.
- Backups live in `~/Backups/shader-bench-settings-20260820-2010/`. The most
  recent are `presets-20260821-pre-familiar-clean.json` (before alien fields
  were stripped from her slots) and `presets-20260821-1525-post-loss.json`.
  Snapshot before any bulk edit to the store.
- The shipped tuning tables in `src/components/canvas/` are the only copy of
  the canon that CI can see. They are a **derived artefact**; the store is the
  source. If they disagree, the store is right and the tables are stale.

`tests/visual/verify-canon-port.mjs` is the check that they agree. Run it after
any canon port or any edit to a tuning table:

```
npx tsx tests/visual/verify-canon-port.mjs
```

It is not a vitest test on purpose — a test needing an untracked file fails on
every fresh clone, which is a check that cannot pass. Current state: **ALL
GREEN**, Jarvis and Ultron both `MATCHES CANON`, speech maps 57/57 and 47/47.

## 2. The bench is a live instrument while Will is mixing

Editing `tests/visual/shader-bench.{ts,html}` **forces a reload of his open
tab**. If he is mid-take that discards uncommitted dial work. Two rules:

- Hands off those two files while he is actively mixing, unless he asks.
- **Headless probes publish.** Every touch autosaves (1.5s debounce), so a
  playwright run that moves a dial writes a real version into the store. Prune
  probe autosaves after any bench automation, and diff before you do — an
  autosave that differs only in LFO-swept fields is a mid-sweep snapshot, not
  drift.

A related defect already cost his work once and is now fixed, but know the
shape: an autosave pending across a body switch fires 1.5s later with the NEW
slot key and the OLD body's numbers. `mount()` now cancels the pending timer
and `saved()` keeps only fields the shipped struct declares.

---

## 3. What landed (8 commits, all on `bench-unified`)

| commit | what |
| --- | --- |
| `36661fa5` | Jarvis "Final 1740" ported: tuning, modes, arrival, pulses, new `JARVIS_SPEECH`, film mounted in `useJarvisRenderer` |
| `c4d4142f` | Ultron "final 1800" ported the same way; five membrane films shipped |
| `cd6b99bc` | Jarvis refreshed to "v2 final 1822" (lit shell at idle; thinking's own outer sweeps) |
| `5a0880ee` | Colossus joins the mixer; Familiar's desk healed; bench stage true black |
| `f78f5c9e` | Colossus reports the thought while thinking, and his reply carries its own sign summary |
| `2d6ea59a` | The app goes true black behind Familiar, both themes |
| `93f41441` | Colossus onboarding preview clips re-rendered in his final voice |
| `92634420` | Ultron's one real LFO sweep restored (see the trap below) |

### The three mechanisms worth understanding

**Speech reach.** `JARVIS_SPEECH` / `ULTRON_SPEECH` map `"field:index"` to the
value that dial holds at full syllable. The renderers grow a syllable envelope
(a VU needle over `state.level`, 0.45 attack / 0.1 release per frame) and lerp
every mapped dial toward its spoken value. This is most of what "speaking"
looks like — the mode deltas are nearly bare on purpose. Applied on the
**shipped path only**: the bench pins its tuning and folds the same reaches in
itself, so applying them in both places speaks twice.

**LFO → pulse translation.** The bench sweeps a field over an absolute
`min..max` with a raised cosine; a `Pulse` is a sine *fraction* of the base.
They meet where the base carries the sweep's **centre** and the pulse carries
`depth = half-range / centre`, `phase = bench phase − 0.25`. A depth of 1 is
correct, not a typo — those sweeps bottom at zero. A **rate-0 LFO holds at
`min`** and ships as a plain constant with no pulse (Jarvis's `latticeBlur`).

**The films.** Jarvis uses ONE loop for every state — state character rides
`latticeSpeed`, which the transition lerps, so working→standby is the same
video easing back down rather than a crossfade glitch. Ultron uses five, one
per state, and the deck crossfades. Assets are in `public/companion/`.

---

## 4. Traps this session paid for

- **A bounded search is not a fact about the system.** The Ultron port read
  *standby's* LFO rack, found it empty, and shipped "the canon runs no sweeps".
  Working actually carries one (`eye:1`, 0..0.84 at 0.15Hz), so the table froze
  a mid-sweep `0.698739` as a constant and the aura stood still. Fixed in
  `92634420`. **Audit every slot, not the first one.**
- **The bench renders nothing under SwiftShader** when video composites are
  involved — the GL context dies. Headless probes can read the DOM (desks,
  strips, computed styles) but cannot judge a picture. Composite look is an
  M4-eyes job.
- **Additive evidence binds to a source digest** over `apps/worker/src` and
  `apps/worker/tests/visual`. Any change in those trees fails
  `tests/visual/manifest.test.ts` until you recapture:
  ```
  node tests/visual/capture-current.mjs --additive-evidence \
    --playwright /home/jellytot/pw-node/node_modules/playwright-core/index.mjs
  ```
  Pass `--origin http://localhost:1427` if another session holds :1420. The
  bundled `playwright` is absent; the flag above is mandatory on this box.
- **Whisper transcripts drift within one server session.** Verifying the
  Colossus voice clips, two passes misheard words on audio a *fresh* process
  hears perfectly. Verify audio in a fresh process, adjacent to a known-good
  control.
- **`tsc` on this branch reports `frame` / `transitionTo` / `replay` union
  errors.** They are not from this work — and main has already fixed them (see
  below), so they disappear on merge rather than needing a fix here.

---

## 5. Getting it live — the real work, not yet started

**Nothing is deployed.** Prod, canary and dev on `jellytot-prod` all run
`v0.4.42`; that image's revision label is `76d0944e`, which is the tip of
`main`. Balmoral has no boltrig stack. Main contains **none** of these symbols:
`JARVIS_SPEECH`, `ULTRON_SPEECH`, `colossusTuning`, `thinkingTrace`,
`colossusReply`; its `JARVIS_TUNING` still opens `outerShell: [1.45, 0.34,
0.46]`; and `public/companion/` on main holds no `.mp4` at all.

**The branch is badly stale.** Relative to the merge base (`dba4126f`):

```
main-only:            279 commits
bench-unified-only:    26 commits
```

Among main's 279 is `78b5986a` "bench: Jarvis V1 joins the union without the
methods the others share" — the fix for the union errors above. Two sessions
have been editing the *same* bench and character files, so this merge is where
the risk lives, not in the porting.

**Suggested order, and do not skip step 3:**

1. Snapshot `presets.json` to `~/Backups/` first.
2. Merge `origin/main` into `bench-unified` (merge, not rebase — 26 commits
   are already pushed and another session pulls this branch).
3. **Re-run `verify-canon-port.mjs`.** A conflict resolved wrongly in a tuning
   table is silent; this is the only thing that catches it.
4. `npx tsc --noEmit` — expect it clean now, with no filtering.
5. Full `npx vitest run`, then recapture additive evidence.
6. Only then tag and build. Roll set per the prod recipe is canary + CV + dev.

---

## 6. Open, and each needs Will

- **Crest films: HELD by his explicit word.** Five centurion-crest Jarvis loops
  are staged and ready; Atlas returns `402 insufficient balance`. Script and
  anchor frame are in the `me-lora-ui` container at `/tmp/atlas-jarvis-crest.py`
  and `/tmp/crest-frame.jpg`, archived in `~/Backups/…/loop-source-frames/`.
  Fire only on a top-up. **These would supersede the current Jarvis film** —
  the shipped loop is the original `jarvis-lattice.mp4`.
- **Jarvis's canon only draws on the `ultron` skin.** Will chose to keep the V1
  instrument dial as the default (it carries telemetry and the work board,
  which the neural body has nowhere to put). The canon is one skin-picker click
  away, not the out-of-the-box body. Do not "fix" this.
- **Colossus's JSON reply format is prompt-enforced, not schema-enforced.** His
  bundle mandates `{"say", "sign"}`; `colossusReply.ts` parses it and **fails
  open to raw text** on every path. It reaches replies made after the bundle
  reloads; old history renders untouched.
- **The wider credential rotation is still owed** — 38 items at
  `~/Backups/opbox-db/CREDENTIAL-ROTATION-CHECKLIST-20260819.md`. The R2 pair
  was rotated 2026-08-21 and is done.

---

## 7. Facts you will want and would otherwise hunt for

- Bench: `192.168.50.2:1425/tests/visual/shader-bench.html?token=…`, token via
  `sudo grep '^BOLTRIG_BENCH_TOKEN=' /etc/boltrig-bench.env | cut -d= -f2`.
  Never commit it.
- Will's clock is UTC+1; the box is UTC. His "1822" is 17:22 UTC — that is how
  the canon labels line up with `savedAt`.
- Named canon in the store right now: **"Jarvis v2 final 1822"** and **"Ultron
  final 1800"**, on all seven slots each. Trailing autosaves differ only in
  swept fields.
- Familiar's newest is an autosave with 24 fields; her slots were cleaned of 44
  alien Jarvis fields that a cross-body autosave had written in.
- The `baseline` slot is a bench convenience with no app mode. Ultron's and
  Jarvis's are byte-identical to `speaking`; nothing ports it.
