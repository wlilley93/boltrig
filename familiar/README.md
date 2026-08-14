# familiar: the living familiar (orb successor)

A real-time GLSL wallpaper for Hyprland: a **volumetric being** whose entire look is its mood. It is
the successor to `../orb` - same proven wayland/EGL/GLES3 harness, but the crude 2D spiked sphere is
replaced by a sphere with an interior: an analytic ray-sphere silhouette (exact, stable, never
crawling) with a front-to-back emission/absorption march through a domain-warped noise volume, a
luminous nucleus, a radial iris, an active skin and a corona, all driven continuously by boltrig's
nine-scalar phenotype. The earlier SDF body that displaced its own surface is gone: it crawled, and it
cost 60 ms/frame (see DESIGN-BRIEF.md anti-pattern 1).

"A creature with a real inner life and a crude body is alive; a beautiful body with a fake inner life is
a screensaver." The orb was the crude body; the familiar is the beautiful one, reading the same inner
life.

## The two add-ons, one creature

boltrig ships the **emotion** add-on (`boltrig/emotion/`): a read-only affective engine, strictly
downstream of dispatch, that appraises the agent's live event stream and publishes a phenotype file
(`$XDG_RUNTIME_DIR/boltrig-phenotype.json`, ~2 Hz, 9 scalars in 0..1). The familiar is the **wayland**
add-on: the body that renders it. They are severable and meet only at that versioned file.

## The phenotype contract (what the shader consumes)

`{"v":1,"ts":<epoch>,"phenotype":{ valence, arousal, irritation, fatigue, attention, social, buoyancy,
luminosity, tension }}` - each 0..1. The host reads and smooths these toward their target (mood morphs,
never snaps) and hands them to `familiar.frag` as `uValence` ... `uTension`. The shader owns every visual
decision:

| scalar | the creature |
|--------|--------------|
| valence | palette ramp: near-black navy (low) -> true blue -> cerulean -> electric blue (high) |
| irritation | pulls the palette to hot magenta (the one non-blue) and agitates the flow |
| arousal | overall motion speed and breathing amplitude |
| fatigue | dims, slows, and sags the body |
| luminosity | internal emission / bloom |
| tension | sharp ridges/needles rise; a fine nervous jitter |
| attention | how strongly it gazes/leans toward the cursor |
| buoyancy | a slow vertical bob and lift |
| social | reserved (openness/reach) |

It also keeps its raw senses: audio (PipeWire monitor FFT -> level/bass/mid/treble + beat), the cursor
(gaze), and time of day (ambient warmth).

## Pieces

```
main.c         C harness: wlr-layer-shell background + EGL/GLES3, phenotype read + smoothing, audio +
               mouse threads, frame-callback paced. Forked from ../orb; the shared-core refactor with orb
               is tracked as a follow-up (see NOTES).
familiar.frag  the creature (installed to ~/.config/familiar/familiar.frag, live-tweakable, SIGUSR1 reload)
protocol/      vendored wlr-layer-shell XML (not shipped by wayland-protocols)
reference/     the WebGL/Three.js prototype (DESIGN-NOTES.md + prototype-creature*.glsl) - the design
               north-star this shader was ported from.
```

Build + install: `make install` (binary to ~/.local/bin, shader seeded to ~/.config/familiar).

## The severability contract (WL-1 / WL-2)

- **WL-1**: this surface imports nothing from `boltrig/`; it consumes only the versioned phenotype file.
  A different producer writing the same schema would drive it identically.
- **WL-2**: no compositor, no EGL/GPU, or no phenotype degrades to a typed message on stderr or the calm
  resting baseline (`PHENO_IDLE`) - never a crash.
- **WL-3** (voluntary expression via a `familiar.express` verb through boltrig's chokepoint) IS built:
  boltrig dispatches the verb through its one chokepoint and writes a small express record next to the
  phenotype file; `FAMILIAR_EXPRESS=0` ignores it. Fire one by hand with `fire-gesture <name>`.

## Realm variants (the room the being floats in)

The background environment is compile-time swappable: `#if FAMILIAR_REALM` branches in
`familiar.frag` (contract: each assigns `bg`, gates on `roomVis`, drives everything from the
phenotype, no marching). Four ship today:

| # | room | feel |
|---|------|------|
| 1 | transit chamber (default) | warp-tunnel spokes + counter-rotating ribs around a distant black hole |
| 2 | the cylinder | a vast greebled cylinder wall whose far reaches fall to black; mood-coloured sparks |
| 3 | emberfield | near-featureless dark; four parallax depths of drifting embers, rare flares, one light nebula banked back-left |
| 4 | the abyss | a flooded vertical column; god-ray shafts from below, bioluminescent motes, marine snow |

Swap live with `use-realm N` (rewrites the define in the installed shader + SIGUSR1; the old
program is kept if the new one fails). `make install` reseeds the repo's default (3); change the
`#define FAMILIAR_REALM` line in the repo to make a choice permanent. Development copies of each
variant live in `variants/` - bench any of them headlessly before promoting a new one, same as
the main shader.

## Cost (it is a wallpaper, not a benchmark)

A raymarched creature is trivially easy to make unaffordable: the first version cost **60 ms/frame
(17 fps)** at 1080p on this box's Radeon 680M and visibly lagged the desktop. It now costs **~6 ms**.
The wins, in order of size:

1. **Cheap noise.** Ashima simplex was being evaluated hundreds of times per pixel. Value noise with a
   small hash is a fraction of the cost and, on a soft organic body, looks the same (60 -> 20 ms).
2. **`mapLo` for secondary rays.** Shadow, ambient-occlusion and interior-transmission rays sample the
   body dozens of times per pixel but only need its mass, not its ridges. They now use a one-octave
   bulk distance instead of the full detail map (20 -> 14 ms).
3. **Fewer steps.** Primary march 90 -> 64, interior 18 -> 9 (with stride and absorption rescaled so
   the goo keeps its density), shadow 12 -> 6, AO 5 -> 3.
4. **Render scale.** The shader runs offscreen at `FAMILIAR_SCALE` and is resampled to the display.
   It defaults to 1.25: 2.0 (a true 2x supersample, an exact box-filter downscale) kept the fibre
   creases and particle cores perfectly resolved but cost ~14 ms a frame at this display's
   geometry; 1.25 smudges the downscale slightly and lands at ~7 ms. Raise it back toward 2.0
   only if the GPU is otherwise idle.
5. **Frame cap.** `FAMILIAR_FPS` (default 30). A glacial being is indistinguishable from 60 in
   motion and it HALVES the per-second GPU load: measured here, 60 fps at scale 1.5 was ~650 ms
   of GPU per second (the desktop felt laggy); 30 fps at 1.25 is ~230 ms/s.

`familiar-bench` measures all of this headlessly (no compositor or monitor needed) and prints a sanity
readback of the frame, so you can tune the shader without a display and know you have not shipped a
black rectangle:

```
make bench && ./build/familiar-bench familiar.frag 1920 1080 40
# familiar.frag 1920x1080  6.28 ms/frame (159 fps) ...
#   image: mean=35.1 sd=66.7 min=2 max=249 lit=17.7% -> looks like a creature
#   centroid: 969.1,536.1 px from bottom-left; top edge 14 px from the top
#   lit colour: R105 G176 B222 -> blue family
```

It can also dump the frame and sweep any uniform, so a look can be judged (or sent to a designer)
without a monitor or waiting for a mood to happen:

```
BENCH_U="uIrritation=0.9" BENCH_PPM=/tmp/angry.ppm familiar-bench familiar.frag 1280 720
BENCH_WORLD=1920x1080 BENCH_ORIGIN=194,930 BENCH_FILL=1 BENCH_PRESENCE=0 familiar-bench familiar.frag 126 150
```

The second renders exactly what the bar porthole renders, which is how the migration geometry is
verified: both windows must put the being's centroid on the same screen pixel.

**Change the shader, run the bench.** Keep it well under budget: it is background furniture sharing the
GPU with real work.

## Knobs

- `FAMILIAR_FPS` (10..120, default 30), `FAMILIAR_SCALE` (0.30..2.0, default 1.25 - raise toward 2.0
  only with GPU headroom to spare), `FAMILIAR_PRESENCE_TAU` (0.05..5.0, default 0.28; how quick the
  exit is - the whole collapse lands in well under a second),
  `FAMILIAR_PRESENCE_IN_TAU` (0.05..5.0, default 0.8; how slowly the being fades in on a bare
  desktop - about three seconds, and the chat bar (familiar-chat) is timed to appear only after
  the fade completes),
  `FAMILIAR_BEAD_X/Y/PX` and `FAMILIAR_BAR_NS` (where it docks), `FAMILIAR_SHADER` (path),
  `FAMILIAR_AUDIO_CMD` (capture override), `FAMILIAR_EXPRESS=0` (ignore voluntary gestures),
  `FAMILIAR_PHENO=0` (ignore the phenotype file; run on the resting baseline, e.g. a demo with no boltrig).
- Hot-reload after editing the live shader: `systemctl --user kill -s USR1 familiar` (once it runs as a
  service), or send SIGUSR1 to the process.

## Notes

- The audio tap and the input-region gotcha are inherited verbatim from `../orb` (see its README) - a
  decorative background must set an EMPTY input region or it breaks lan-mouse's edge capture.
- **Nothing large of ours goes on the overlay/top layers.** lan-mouse captures the right screen edge
  with a `1919 0 1x1080` overlay strip; anything of ours that covers it eats the cursor arriving from
  the Mac, invisibly. The wallpaper is born on BACKGROUND and never calls `set_layer` (Hyprland applies
  it late anyway, so a runtime switch is both unsafe and unreliable); the bar surface is a separate
  small OVERLAY porthole. `./check.sh` binds this - static greps plus a live `hyprctl layers` intersection test
  against the capture strip - and `make install` runs it, so a violating build cannot be installed.
- **Never create headless outputs on this box** (`hyprctl output create headless ...`), not even
  briefly for testing. `lan-mouse` binds its edge-capture zone to whichever output sits at the screen
  edge, so a phantom output to the right silently becomes the capture target: the cursor crosses from
  the Mac, lands on an invisible screen, and appears to be swallowed. It has bitten once (2026-07-20):
  a leftover `perftest` output at (1920,0) captured the right edge, and the cursor ended up parked at
  x=1919 inside the barrier. lan-mouse rebinds itself once the phantom is removed, but the cursor must
  be freed by hand (`hyprctl dispatch movecursor 960 540`) and a `systemctl --user restart
  lan-mouse.service` gives a clean rebind. **`familiar-bench` is surfaceless and needs no output at
  all** - use it instead of spinning up a headless display to test the shader.
- Rendering is frame-callback paced, so a fully occluded or off display stops the draw loop; a monitor
  that is KVM-switched away has no vblank, so the wallpaper pauses until it returns (restart to resume).
- Cutover is DONE: the familiar is the desktop body. `orb.service` is disabled and `../orb` is kept
  only as the reference implementation of the harness; do not run both (they claim the same layer).
