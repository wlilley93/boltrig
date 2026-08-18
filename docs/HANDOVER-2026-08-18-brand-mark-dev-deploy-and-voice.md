# Handover: the brand mark, a dev deploy, and proving the voice, 2026-08-18

Branch `feat/brand-mark-opbox-blue`, one commit (`dcacb653`) off `83e0f2bd`,
pushed. Built and deployed to `dev.boltrig.io`; live and verified.

Asked for: deploy the latest shaders and Boltrig to `dev.boltrig.io`; make the
logo's dot the same blue as the Opbox logo and pulse the way Opbox's does; put
the logo on the login modals; confirm Colossus's upgraded voice is live; and
confirm the shader bench is reachable and that Jarvis and Ultron have new
settings.

---

## What is live on dev.boltrig.io

Served bundle moved `index-rC7a-UJq.js` to `index-hr3IwG4n.js`. Three public
endpoints 200. Rollback retained as `dist.rollback-20260818T110256Z` on
jellytot-prod.

**The shaders were already in the branch.** `feat/familiar-shader-filaments` is
fully merged (`git log HEAD..feat/familiar-shader-filaments` is empty), and every
bodies/Jarvis/Ultron/Colossus commit is on `feat/real-brand-mark`. Nothing had to
be moved; what was missing was a deploy, not a merge.

### Verification, and why three 200s were not enough

`/`, `/healthz` and `/readyz` all answer 200 from the OLD tree, so they cannot
tell you a deploy happened. Four checks were run instead, each answering
something the previous one could not:

| check | answers |
| --- | --- |
| local vs remote tree digest, 67 files each | the bytes arrived intact |
| served `index.html` names `index-hr3IwG4n.js` | the swap took effect |
| fetched that asset over HTTPS and grepped it | the CHANGE is in what is served, not merely in what was built |
| Playwright against the live origin | a person actually sees it |

The last one is the only one that could distinguish "the code is in the bundle"
from "the mark renders". It reported `coreFill: #0066FF`, `coreAnimation:
boltrig-mark-pulse 2.6s`, the ping element present, and `inAuthCard: true` on
the "Welcome back" screen.

---

## The mark

### Colour

The core was `#3DD3F0`, the design system's `--c-cyan-500`. It is now `#0066FF`,
copied from `public/opbox-mark.svg` in the Opbox tree.

A note for whoever checks this against Opbox and finds a mismatch: Opbox's
in-app dot renders `var(--accent)`, which is `#006BFF` in its default theme.
That is five units of green from the logo asset and indistinguishable at dot
size. The LOGO file is the one copied here, because a logo is what this element
is. Neither value is a typo.

`apps/worker/public/favicon.svg` carries the same value. That pairing is
load-bearing rather than tidy: the desktop icons under
`apps/worker/src-tauri/icons` are rasterised FROM the favicon (`4b392a21`), so a
core changed in one file alone is precisely how this tree grew a third drawing
of its own mark the last time. A new test in
`apps/worker/tests/brandWordmark.test.tsx` pins the two files to each other
rather than pinning the value, so a future rebrand edits two files and the test
follows rather than fighting it.

The rest of `--c-cyan-500` is untouched. This is the mark, not the accent.

### Pulse

Timings are copied from Opbox's `.opbox-dot`, not re-invented: 2.6s, the same
easings, the same 0.92 trough, the same 3.4x radar ping. Three things did not
transfer cleanly and each is commented at the site in
`apps/worker/src/styles.css`:

1. **What the transform turns about.** A CSS box scales about its own centre; an
   SVG circle scales about the user-space origin, which here is the mark's
   top-left corner. A straight copy made the core swing diagonally instead of
   breathe. `transform-box: fill-box` puts the origin back on the shape.
2. **The ping is rendered only when pulsing.** An element animated to opacity 0
   is still an element, and leaving it in the static mark would put a stray
   hairline ring at r=5 under any renderer that ignores the animation.
3. **Reduced motion HIDES the ping rather than pausing it.** A paused ring
   freezes at whatever frame it stopped on and becomes a permanent halo no
   design asked for. This is also what keeps the evidence pipeline
   deterministic: `apps/worker/tests/visual/capture-current.mjs` runs with
   `reducedMotion` set to reduce, so the mark it photographs is the still one,
   and a pulsing logo does not turn every future capture into a diff.

`BrandMark` takes a `pulse` prop defaulting to true. Opbox's own policy is the
reason it exists: pulse on auth cards, modal headers and gates, off in dense app
chrome and table rows where a moving dot is noise. Every current call site is
the first kind.

### The login modals

The mark went into `AuthCard` in `apps/worker/src/components/auth/AuthShell.tsx`,
which is the single seam all nine auth surfaces pass through: sign-in, the 2FA
prompt and its setup, both password resets, invite acceptance, the desktop
bridge, the no-server screen. One edit reaches all of them, and the test now
asserts the pairing there so one of the nine cannot grow a different header.

**Deliberately NOT `BrandLockup`.** That component's stated contract is the two
ONBOARDING headers staying identical to each other. Widening it to a third
surface with its own chrome is a decision worth taking on its own rather than as
a side effect of putting a logo on a login box, and it would have meant moving
the component and renaming its `onboarding-` scoped classes mid-deploy. The
sizing in `.auth-mark` is the lockup's own 2.2em/0.55em, so the two match today.
If a fourth surface wants the mark, that is the moment to promote the lockup
properly. Recorded here so the next person makes that call knowingly rather than
discovering two pairings and assuming drift.

---

## Colossus's voice is live, and here are the numbers

The 2026-08-17 handover recorded the pocket-voice container swap as **still
owed**. It has since happened, and went past the `1.2` that document named:
`boltrig-pocket-voice` on jellytot-prod runs **`boltrig/pocket-voice:1.3`**.
`:1.1` and `:1.2` remain as exited containers, which is the rollback.

Do not read "the image was swapped" as "the voice works". The exact failure the
previous round paid for was a container that looked healthy while serving
unprocessed audio, so this was measured rather than inspected. Synthesised
through `POST /v1/audio/speech`, which is the route
`boltrig/adapters/builtin/pocket_voice.py` actually calls:

| measure | approved at the bench | measured 2026-08-18 |
| --- | --- | --- |
| RMS | -13.7 dBFS | **-13.76** |
| peak | 0.94, the limiter ceiling | **0.94** |
| energy below 200 Hz | 23.4 to 23.5% | 33.8%, text-dependent, shelf clearly on |
| energy above 4 kHz | 1.5 to 3.1% for a good clone | **0.1%** |

The above-4 kHz figure is the one that identifies the CLONE rather than the
chain. The broken `colossus-L1` sits at 52 to 60% and `L2` at 25%, so 0.1%
confirms the container carries a good clone and not the noisy
`colossus.safetensors` that shipped before.

All four voices answer (`colossus`, `familiar`, `jarvis`, `ultron`, plus seven
registers each for Jarvis and Ultron). The earlier 404s for three of the four are
gone. Only Colossus carries a chain file, which is the design: a voice without
one is untouched.

Container facts worth not rediscovering: `ffmpeg` resolves at `/usr/bin/ffmpeg`,
so the launchd bare-name trap does not apply in the container; scipy 1.18.0 and
numpy 2.5.2 present; it listens on `127.0.0.1:8911` INSIDE the container on
network `boltrig_default` at 172.20.0.12 with no published port, so reach it with
`docker exec`.

### The defect found on the way: `/speak/stream` skips the chain

`server.py` has three synthesis routes and `apply_chain` is called by one.

- `POST /speak` calls it. Its comment reads: *"The one chokepoint: /speak and
  /v1/audio/speech both land here, so a voice with a chain is processed on every
  surface rather than wherever a caller remembered to ask."*
- `POST /v1/audio/speech` delegates to `speak()`, so it inherits the chain.
- `POST /speak/stream` does **not**. It yields `to_pcm16(chunk)` straight from
  the model. Its own docstring says *"this is the one a conversation should
  use."*

So the comment says "every surface", means two of the three, and the one it
misses is the one the tree recommends. Measured, same text and voice:

| route | RMS dBFS | peak | energy below 200 Hz |
| --- | --- | --- | --- |
| `/v1/audio/speech` | -13.76 | 0.94 | 33.8% |
| `/speak/stream` | -17.07 | 0.778 | **0.2%** |

The 0.2% is the tell. The +14 dB shelf at 110 Hz is simply absent.

**Boltrig is not affected today**, because the adapter uses the OpenAI-shaped
route. The hazard is that switching to streaming for time-to-first-chunk, which
the docstring actively invites, would silently lose the voice, and it would
present as a wrong clone rather than a missing filter.

**It is not a one-line fix.** `apply_chain` normalises before the graph and ends
in a limiter, and both want the whole utterance; applying it per chunk would step
the level at every chunk boundary. Whoever takes it should decide between
buffering the utterance behind the streaming shape (losing the latency the route
exists for) and a streaming-safe chain with fixed makeup gain and a look-ahead
limiter. Source of truth is `~/Projects/pocket-voice` on the M4, which must never
be given a git remote, so a fix means an image rebuild and redeploy.

---

## The shader bench, and what "new settings" means

The bench is `apps/worker/tests/visual/shader-bench.html` with
`apps/worker/tests/visual/shader-bench.ts`, served as a route on the WORKER'S
VITE DEV SERVER. It is token-gated and `apps/worker/vite.config.ts` names the
tailnet host in `allowedHosts` so `tailscale serve` can reach it (`4de99b5f`).

**It is not on the M4.** `mac-m4` carries only csm-mlx, pocket-voice,
vibe-design-system and vibe-justice-system, with no Boltrig checkout. The bench
runs from the Boltrig tree on the beelink. What IS on the M4 is the separate
VOICE mixer that decided Colossus's chain. The two tools are both called a mixer
and are easy to conflate.

**The bench's saved presets are not the shipped look, and nothing promotes
them.** `Copy settings` POSTs to `/__bench-presets`, a vite middleware in
`apps/worker/vite.config.ts` that writes a `presets.json` beside the bench. That
file is gitignored and read by nothing except the bench. Checked 2026-08-18: it
held exactly one entry, `jarvis.standby` from 17:04 the previous evening, and no
Ultron entry at all. Reading it would have supported the conclusion that Ultron
is untuned, which is false.

**The shipped tuning is
`apps/worker/src/components/canvas/bodyPresets.ts`**: `JARVIS_ARRIVAL`,
`JARVIS_MODES`, `JARVIS_PULSES` and the Ultron equivalents. An arrival state plus
five modes (standby, listening, thinking, working, speaking) plus per-mode LFO
pulses, for both bodies. Both are fully populated. Answer "does this body have
new settings" from that file, never from the bench's scratch state.

---

## Two things about the tree that will bite the next session

### The branch fork is real and nobody has merged it

`feat/real-brand-mark` and `feat/console-target` forked at `e79e64b7` and both
moved. As at 2026-08-18:

| branch | commits the other lacks | what is in them |
| --- | --- | --- |
| `feat/real-brand-mark` | 45 | every Colossus/Jarvis/Ultron body, shader and voice commit, the brand mark, per-user integration credentials |
| `feat/console-target` | 43 | the security/egress/audit-outbox hardening wave, HITL reconciliation, cross-platform visual evidence |

Neither is "latest Boltrig". The dev preview has been fed from
`feat/real-brand-mark` and this deploy continued that, which is the defensible
choice for a request about shaders and the mark, but it means the hardening wave
is NOT on dev.boltrig.io. Merging them is a real job and an unclaimed one. Do not
let a later session assume the branch it is on is the whole product.

### `~/boltrig-fixtree` is shared with a live session

It moved three times in ten minutes during this work: HEAD advanced `83e0f2bd` to
`56e78baa`, and six untracked `canvas/*.ts` files appeared with mtimes ninety
seconds apart. Building there would have shipped another agent's half-finished
shader refactor to dev.boltrig.io.

The pattern used instead, which works and is cheap:

    git worktree add --detach <scratch> <pushed-commit>
    cp -al ~/boltrig-fixtree/apps/worker/node_modules <scratch>/apps/worker/node_modules

The hardlink copy is 131M and near-instant, and the worktree is self-consistent
because `apps/worker/vite.config.ts` aliases the web SDK to
`../../sdks/web/src/index.ts`, i.e. to the worktree's own source rather than to
an installed snapshot. In the shared tree, stage by explicit path and never
`git add -A`.

---

## Gates

`tsc` clean. 982 worker tests, one red. That red is
`apps/worker/tests/onboarding.test.tsx`, "uses Enter to continue without stealing
Enter from an open picker", and it is **pre-existing**: it fails identically on
pristine `83e0f2bd` with no changes applied, which was checked rather than
assumed. `apps/worker/tests/voiceLoudness.test.ts` failed once in a full run and
passed in isolation and on re-run; it is load-flaky, not broken.

The new colour test was negative-controlled. Reverting the favicon alone turns it
red with `expected '#3DD3F0' to be '#0066FF'`, so it is a check that can fail.

Four-stage evidence pipeline re-run for both lanes, staged first because
`sourceTreeDigest` reads the git index. VDS ledgers rebound and scanned clean at
15 screens, 1643 references, 6 visual-review routes. Note `make vds-ledgers`
calls `.venv/bin/python`, which a fresh worktree does not have; run
`scripts/check_vds_ledgers.py` with the fixtree's interpreter instead.

---

## Outstanding

1. **The favicon is stale at Cloudflare's edge.** The origin serves `#0066FF`;
   the edge returned `cf-cache-status: HIT` with `max-age=14400` and roughly
   three and a half hours left. index.html is uncached and was immediately new,
   so only this one root-level asset lags. The CF token `still-block-6ced` has
   DNS, Tunnel and Access scopes but **no Cache Purge**, and the purge attempt
   returned error 10000 "Authentication error". That code is also what a
   token-wide throttle returns, so it was tried exactly once and not retried.
   Either add the scope or let it expire.
2. **The desktop icons now trail the favicon.** They are the cyan core, and they
   are rasterised from the favicon, so the drift is real. It affects only the
   next desktop build, not the web preview. Deliberately not attempted: it is
   twenty files including `.icns`, `.ico`, android and ios, at the 55.9% inset
   `4b392a21` measured off the set it replaced, and no script for it exists in
   the tree. `rsvg-convert`, `convert` and `magick` are all available on the
   beelink, so the work is bounded; guessing the inset and background is what
   makes it worth doing carefully rather than quickly.
3. **`/speak/stream` skipping the chain**, as above. Not urgent, since nothing
   calls it, and genuinely a design decision rather than a patch.
4. **The branch merge**, as above. The largest of the four and the one nobody
   owns.

Still owed from the 2026-08-17 handover and unchanged by this session: Familiar's
register audio needs Fish Audio API credit, which is a billing state only the
account holder can clear.
