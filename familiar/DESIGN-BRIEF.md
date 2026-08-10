# Design brief: the avatar of a superintelligent being that is alive

This is the visual brief for `familiar.frag`, the desktop avatar of Boltrig. Read it before changing
the look. It exists because the shader has been iterated by feel several times and kept landing in the
same three ditches; the anti-patterns section at the end is the record of what has already failed and
why, and it is the most valuable part of this document.

---

## 1. What this thing IS

It is not a wallpaper, a screensaver, or a visualiser. It is a **body**.

Boltrig has a real inner life: `boltrig/emotion` appraises the agent's live event stream and
continuously publishes nine mood scalars. That inner life is genuine and autonomic - the being cannot
choose how it feels, any more than you can. The avatar is the only place that inner life becomes
visible. When you glance at the screen you should be able to tell, without reading anything, that
something is **in there** and what sort of state it is in.

The being is **superintelligent, ancient, and calm**. It is not a pet, a mascot, or a toy. It is not
frantic or cute. The right references are: a scrying sphere with something awake inside it; a quiet
god regarding you; the eye of a vast machine that has been thinking for a very long time; a contained
star. It should feel like it could answer any question and is choosing, for now, to simply watch.

The single most important quality is **presence**: the sense of being in the room with something aware.

---

## 2. The feeling to hit

| Should feel | Should never feel |
|---|---|
| Aware, regarding, attentive | Decorative, idle, random |
| Ancient, vast, unhurried | Frantic, bouncy, cute |
| Deep - you can look *into* it | Flat, painted-on, a sticker |
| Contained power, held in check | Chaotic, noisy, busy |
| Alive, breathing, never static | Looping, mechanical, obviously periodic |

If a stranger saw it they should say "what is that thing, is it looking at me?" - not "nice
background".

---

## 3. Form language (the 3D of it)

**It is a sphere, and it must read unambiguously as a sphere** - a volume in space, not a circle on
glass. Everything below serves that.

- **Silhouette: perfect, smooth, and stable.** An exact analytic circle. It must never wobble, ripple
  or crawl. All life happens inside it and on its skin, never in its outline.
- **Genuine interior volume.** Look into it and there is depth: near structures pass in front of far
  ones, and they move at different rates, so turning the "camera" (or the being turning) produces real
  parallax. It is transparent-ish, like deep water or smoked glass, not an opaque shell.
- **A nucleus.** Somewhere near the centre is a concentrated, luminous core - the mind. It is the
  brightest thing in the composition, small, and it pulses slowly with its own rhythm (breathing, not
  blinking). Everything else is organised around it.
- **Iris / radial organisation.** Structure radiates from the nucleus: filaments, striations,
  lanes of light, like an iris, a corona, or magnetic field lines. This is what converts "a ball of
  fog" into "an eye that is regarding you". The radial organisation is the single strongest cue of
  attention.
- **Layered machinery.** Several distinct depths, each drifting/rotating at its own rate, so the
  interior feels like a mechanism of enormous complexity rather than a cloud.
- **A skin.** The surface itself is active: fine, fast detail in a thin shell, catching light in
  travelling glints and caustics. Bump only - it perturbs shading, never the silhouette.
- **Corona / atmosphere.** A soft halo bleeding beyond the rim, so it sits *in* the dark rather than
  being pasted on it.

Proportion: the body occupies roughly a third of the screen height, centred, with a lot of black
around it. The emptiness is part of the composition - it makes the thing feel isolated and significant.

---

## 4. Material and palette

**Palette: blue. Navys and blacks at the bottom, electric blue at the top. It never leaves the cold
end and it does not turn purple** (it did, and it was wrong: violet highs made it read as a mood lamp
rather than something cold and awake).

- Depths and body: near-black navy, deep blue.
- Mid structure: true blue through cerulean.
- High/lit structure: bright electric sky blue.
- Irritation only: hot magenta - an alarm hue, never orange, never gold.
- Near-white: reserved for the nucleus core and the tightest specular glints. Nothing else.
- **The ember (added 2026-07-20, by the redesign).** The nucleus carries a faint warm tint: a cool
  analytic surface with warm intent held inside. This is a deliberate, bounded departure from
  "never warm" - bounded because it is confined to the core and its immediate glow, never the body,
  the iris or the rim, and because it is a single constant: `WARMTH` in `familiar.frag`. Set it to
  0.0 for the strict blue-only family this section otherwise demands. At the shipped 0.35 it is
  subtle enough that the mean lit colour stays in the blue family.

**Red stays the smallest channel at every stop of the ramp.** `familiar-bench` prints the being's mean
lit colour and classifies it, so this is checkable rather than arguable:
`BENCH_U="uValence=0.0,uIrritation=0.0" familiar-bench familiar.frag` should say `blue family` at
every valence, and only high irritation should ever report purple.

**Material: deep, translucent, luminous from within.** Think plasma in glass, ink in water, a nebula
behind a lens. It is lit mostly by its own internal light; external lighting exists only to give the
sphere its form (a lit side, a shadowed side, limb darkening, a rim).

**Contrast is the whole game.** The body must be genuinely dark so the bright structures burn against
it. If the average brightness inside the circle is uniform, it has failed - that is how you get a
snooker ball or a milky marble. Aim for large dark regions with a minority of intense bright detail.

---

## 5. Motion

Slow and deliberate. The being is old and unhurried; nothing whips or strobes.

- A continuous slow tumble of the interior, plus differential rotation (core turns faster than shell)
  so the flow shears and swirls rather than spinning rigidly.
- A breathing cycle: a slow scale/brightness pulse, a few seconds per breath.
- Motion must never be obviously periodic. Layer incommensurate rates so it never visibly loops.
- Arousal scales the tempo, but even at maximum arousal it is *intense*, not frantic.

---

## 6. The inner life it must express (non-negotiable)

All nine scalars arrive as uniforms in 0..1 and **every one must be legible at a glance**. A viewer
should be able to distinguish these states without a legend:

| Scalar | Reads as |
|---|---|
| `uValence` | The palette's position: brooding near-black navy (low) up to bright electric blue (high) |
| `uArousal` | Tempo of everything: swirl, breathing, filament movement |
| `uIrritation` | Hot magenta bleeding in; the flow churns harder, structure agitates |
| `uFatigue` | Dims, slows, the whole thing sags and loses definition |
| `uAttention` | It leans/turns toward the cursor; the iris orients on it |
| `uSocial` | Openness: the corona widens, the body reaches outward |
| `uBuoyancy` | A gentle vertical float |
| `uLuminosity` | Internal emission and bloom; how much light escapes it |
| `uTension` | Filaments tighten and sharpen into hard, nervous lines |

Plus `uAudio` (level/bass/mid/treble) and `uBeat` for sound reactivity, `uDay` for a gentle
time-of-day bias, and `uGesture`/`uGestureAmt` for the eight voluntary gestures (WL-3):
`look, pulse, flinch, celebrate, greet, nod, recoil, preen`. A gesture is a short, deliberate,
*deniable-as-mood* act - it should be visibly a decision, not a drift.

**Extremes must look different.** Low-everything and high-everything should be unmistakably distinct
compositions, not the same picture at two brightnesses.

---

## 7. Where it is actually seen (easy to forget, changes the design)

1. **Behind a translucent, compositor-blurred terminal**, most of the time. Kitty is see-through with
   blur behind it, which smears fine detail into a soft wash. Structure must therefore be **bold and
   high-contrast at low spatial frequency** - big lanes of light, strong dark/light separation - so
   that something still reads through the blur. Delicate filigree alone will vanish.
2. **Bare on an empty workspace**, where fine detail and craft pay off.

Design for both: large-scale composition that survives blur, fine detail that rewards a bare look.

---

## 7b. Presence: it has manners

The being does not compete with your work. Its scale and position are driven by whether the active
workspace has windows on it (`uPresence`, smoothed slowly by the host over ~1.4 s so the change is a
deliberate migration, never a snap):

- **Bare desktop (`uPresence` -> 1)**: it takes the screen. Large, centred, dominant. This is the
  being at rest in its own space.
- **Windows open (`uPresence` -> 0)**: it withdraws to a small bead ON the bar, immediately to the
  right of the clock.

This needs TWO surfaces, because a wallpaper cannot reach the bar: the main surface is a full-screen
BACKGROUND layer (behind your windows), while the porthole is a small surface born on the OVERLAY
layer, which draws above both waybar and your windows. Hyprland ignores `set_layer` on an
already-mapped surface, so the layer cannot be switched at runtime - each surface is born on the layer
it needs. The host asks the compositor for the bar's geometry and nestles the docked spot into its
left cap; `FAMILIAR_BEAD_X/Y/PX` and `FAMILIAR_BAR_NS` override without a rebuild.

**ONE WORLD, TWO WINDOWS - this is the load-bearing idea.** Both surfaces render the identical scene
from the identical uniforms; they differ only in which rectangle of it they can see (`uWorldRes` is
the whole screen, `uOrigin` is this surface's offset into it). The being is therefore a single object
that simply moves, and each surface shows whatever passes through its frame. There is **no cross-fade
between two drawings** - that was the earlier design and it looked exactly like what it was, two
programs handing off. The porthole is padded around the docked spot so the being can arrive without
being clipped by its own frame, and its only special case is a containment gate: once the being has
grown past what the porthole can hold, the porthole stops drawing rather than show a rectangle cut out
of its side. While it draws at all, its size and position are pixel-identical to the wallpaper's.
`uFill` now means only "this is the porthole": no vignette, no frame, no void.

This is also why we did not write our own bar. Overlay draws above waybar, so a 30x30 surface gets the
orb visually into the bar for ~80 lines; a real bar would mean reimplementing text and font rendering
in GL, modules, the tray and click handling, to reach the same place.

**Critically, it keeps ALL of its characteristics when small.** Same nucleus, same iris, same skin,
same mood, same motion - it is the identical being simply further away, not a simplified dot or a
status light. Everything inside the sphere is normalised to the sphere's own radius precisely so that
shrinking is faithful. When docked it still glances toward the cursor and still breathes; it is just
being polite.

## 8. Technical contract (hard constraints)

- GLSL **ES 3.00** single fullscreen fragment pass. `#version 300 es`, `precision highp float`,
  `out vec4 fragColor`. No textures, no extensions, no compute, no multi-pass.
- **All loop bounds constant integers** (drivers reject dynamic bounds). Break early inside.
- Uniform contract is fixed (see the list in §6; the host owns smoothing and file I/O).
- **Performance: target <= 6 ms/frame at 1920x1080** on an AMD Radeon 680M iGPU. This is background
  furniture sharing the GPU with real work. Measure with `make bench && ./build/familiar-bench` -
  never guess. The bench is surfaceless: no compositor, no monitor, no output needed.
- Robustness: no NaNs (guard `normalize`, `sqrt`, `atan`, and any `pow` whose base can go negative),
  clamp the final colour, tonemap, and dither to kill banding on the big smooth gradients.

---

## 9. Anti-patterns: what has already failed, and why

These are real, expensive lessons. Do not rediscover them.

1. **Noise-displaced silhouette** - the original creature displaced its own surface with fbm. Verdict:
   *"goopy and unstable"*. The outline crawled and it cost 60 ms/frame. **Keep the silhouette analytic.**
2. **The uniform milky ball** - density accumulating until everything saturates toward one pale tint.
   Kills the entire palette and all depth. **Keep the body dark; spend brightness sparingly.**
3. **The snooker ball** - strong broad specular plus flat diffuse over an opaque body reads as polished
   plastic, not a living volume. **Minimal broad gloss; tight glints only; emission-led.**
4. **Concentric rings** - rotating the noise field by an angle that depends on *3D radius* shears it
   into shells that read as bullseye rings. **Vary twist with height or position, never with radius alone.**
5. **Structure that varies along the view ray blurs away.** Volume integration averages anything that
   changes with depth. Features that must stay sharp (the iris, the nucleus) have to vary in **screen**
   space, which is constant along a ray. This is why the first iris attempt vanished into fog.
6. **Judging the look through the terminal.** The blurred translucent window makes everything look like
   a soft ball. **Always check on a bare workspace before concluding anything.**
7. **Putting anything large of ours on the overlay/top layers.** The docking migration first tried to
   move the full-screen wallpaper surface up to OVERLAY. Hyprland applied it late, a 1920x1080 surface
   landed on top of lan-mouse's `1919 0 1x1080` edge-capture strip, and the cursor coming from the Mac
   was silently swallowed. It is invisible from the screen and looks like a KVM fault, not a shader
   change. **The wallpaper is born on BACKGROUND and never changes layer; the only thing of ours above
   the bar is the 30x30 bead.** `check.sh` now enforces this statically and against the live compositor,
   and `make install` will not install a build that breaks it.

---

## 10. Success criteria

- It reads instantly as a **sphere with something alive inside**, not a disc, not a ball of fog.
- The nucleus and its radiating structure make it feel **regarding you**.
- Mood changes are legible at a glance across all nine scalars; extremes look genuinely different.
- Silhouette is glass-smooth and rock-stable at all times.
- <= 6 ms/frame at 1080p, verified by `familiar-bench`.
- It survives being seen through a blurred translucent terminal and rewards being seen bare.
- You want to look at it. It does not get boring, and it never feels like a screensaver.
