# Ambition: a 4K, photoreal, non-human eye

This is the improvement brief for `familiar.frag`. It supersedes nothing in `DESIGN-BRIEF.md` - that
document still governs what the thing IS and what it must express. This one governs how good it has
to look, and it sets the bar deliberately high.

---

## 1. The ask, in one sentence

**Build an eye that a stranger would assume was a rendered photograph of a real organism, and that no
stranger could name the species of.**

Not a stylised orb with an eye motif. Not a magic sphere. An **eye**: wet, refractive, layered,
lit, and unmistakably the sense organ of something that is alive and looking at you. And then: not
human, not any animal on Earth. Something whose anatomy is internally consistent enough that a
biologist would accept it and specific enough that an artist could draw a second one.

The being it belongs to is superintelligent, ancient and calm. The eye should carry that: unhurried,
enormous, and completely aware of you.

---

## 2. What "not human" has to mean

The failure mode is a human iris in blue. The second failure mode is a lazy fantasy trope - a plain
vertical cat slit and nothing else. Neither is enough. Go further, and commit:

- **The aperture need not be a circle.** Consider a slit (vertical, horizontal, oblique), a
  W or U-shaped operculum like a cuttlefish, a chain of separate apertures, a keyhole, an aperture
  whose shape *changes* as it dilates rather than merely scaling.
- **The iris need not be one flat annulus.** It could be built in several stacked plates that slide
  across each other, or radial vanes that overlap like a mechanical diaphragm, or a fibrous stroma
  with visible depth between layers.
- **There may be structures with no human equivalent** - a tapetum flashing behind the aperture, a
  nictitating membrane crossing occasionally, a secondary fovea, ridges, a second concentric
  aperture, bioluminescent tissue in the stroma.
- **Whatever you invent must obey its own rules.** The same structures in the same places every
  frame, deforming plausibly. Invented anatomy that stays consistent reads as real; anatomy that
  drifts reads as noise.

The one thing it must NOT be is arbitrary. Every feature should look like it does something.

---

## 3. Where realism actually comes from

Realism in an eye is not resolution and it is not more filaments. It is these, roughly in order of
payoff:

1. **Refraction through the cornea.** The iris is seen through a curved fluid lens, so it is
   magnified, displaced with viewing angle, and distorted near the limb. Currently there is only a
   crude normal-based parallax on the pupil. Doing this properly - refract the view ray at the
   corneal surface, then intersect the iris plane behind it - is the single largest available gain.
2. **Layered stroma with real occlusion.** Fibres at different depths that pass in front of one
   another, cast contact shadow on the layers beneath, and shift against each other with parallax.
3. **Anisotropic specular.** Wet tissue and fibrous structure do not have a round highlight. The
   corneal reflection should be sharp and geometric; the stroma sheen should stretch along the fibre
   direction.
4. **Subsurface scatter in the iris.** Light entering the stroma and leaving somewhere else, so thin
   structures glow at their edges and the tissue reads as translucent rather than painted.
5. **Contact shadow and ambient occlusion** where the iris meets the pupil, under the collarette,
   in the crypts. Cheap, and it is most of what makes tissue look three-dimensional.
6. **A tear film**: a very thin, very sharp, slightly mobile specular layer over everything, with a
   little noise in it. Eyes are wet; dry eyes look like plastic.
7. **Micro-detail that survives 4K.** At 3840x2160 the eye is ~1000 px across. Every structure
   should still have something to say at 200% zoom: fibre-level texture, crypt edges, pigment grain.
8. **Chromatic dispersion** at the limb and through the corneal edge. Already whispered in; it can go
   further.

---

## 4. Where it is now (honest, measured)

Read `familiar.frag`. It currently has: an analytic ray-sphere silhouette, a screen-polar iris of
radial filaments, five rotating shells for interior parallax, a dark pupil with normal-based
parallax and an inner shadow, a geometry-correct corneal highlight, crypts, a collarette with its
shadow, a limbal ring, thought-spark sprites, embers and ridged-noise lightning off the rim.

It costs **7.4 ms/frame at 3840x2160** and **2.2 ms at 1920x1080** on an AMD Radeon 680M.

What it still is not: it is a *sphere with an eye pattern on it*, not an eye. The giveaways are that
the iris sits on the surface rather than behind a lens, the structures are radially symmetric in a
way tissue never is, and everything is lit by one convenient key light with no occlusion anywhere.

---

## 5. Hard constraints (these do not move)

- **GLSL ES 3.00**, single fullscreen fragment pass. `#version 300 es`, `precision highp float`,
  `out vec4 fragColor`. No textures, no extensions, no compute, no multi-pass, no feedback buffers.
- **All loop bounds constant integers.** Break early inside.
- **Premultiplied alpha out**: `fragColor = vec4(colour * a, a)`.
- **The uniform contract is fixed** (see `DESIGN-BRIEF.md` §6 and the top of the shader). New
  uniforms mean host changes - ask, do not assume.
- **One world, two windows.** Position and scale come from `uWorldRes`/`uOrigin`/`uPxScale`, never
  from `iResolution`. The porthole must never get its own composition. This is what makes the
  migration read as one object; it was arrived at the hard way.
- **Palette: blue.** Navy and black at the bottom, electric blue at the top, never purple. Magenta is
  reserved for irritation. A faint warm ember at the core is permitted (`WARMTH`).
- **All nine mood scalars must stay legible**, and extremes must look like different creatures in
  different states, not the same picture at two brightnesses.

### Budget

**Target <= 8 ms/frame at 3840x2160** (the wallpaper supersamples 2x from 1080p). Hard ceiling 14 ms.
This is background furniture sharing an integrated GPU with real work.

Spend the budget where it shows. Refraction and occlusion are worth far more per millisecond than
another octave of noise. If a feature costs more than 1 ms, it needs to be visible in a still.

---

## 6. Anti-patterns (real, expensive, already paid for)

1. **Displacing the silhouette with noise** - the outline crawls and it cost 60 ms/frame. Keep the
   silhouette analytic.
2. **The uniform milky ball** - density accumulating until everything is one pale tint. Keep the body
   dark; spend brightness sparingly.
3. **Broad gloss over an opaque body** reads as polished plastic. Emission-led, tight glints only.
4. **Rotating noise by an angle that depends on 3D radius** shears it into concentric shells that
   read as bullseye rings. Vary twist with height or position, never radius alone.
5. **Structure that varies along the view ray blurs away** under integration. Anything that must stay
   sharp has to vary in screen space.
6. **Judging the look through the translucent terminal.** Always check bare, or with the bench.
7. **Non-integer supersampling.** The downscale is a bilinear blit: an exact box filter at 2.0, a
   smudge at 1.5. It made things blurrier, not sharper.
8. **Smooth exponential tongues read as an aurora, not fire.** Fire needs ridged noise (a thin crease
   with darkness either side), a near-white core, and intermittency.
9. **Ridged noise with a strong radial term draws closed contours** - cracked mud, not lightning. A
   bolt is thin in angle and long along the radius.
10. **Flickering by discrete angular sectors** leaves hard straight-edged wedges. Masks must be
    smooth in angle and discrete only in time.
11. **Any bounded region must fade out before its own boundary,** or the cutoff draws a visible
    circle in the void.
12. **A catchlight glued to the pupil** travels with the gaze and makes the eye look indifferent to
    light. Corneal reflections are fixed by geometry; the pupil roams beneath them.

---

## 7. How to work, and how it gets judged

Do not iterate blind. Everything here is measurable in seconds:

```
familiar-bench proposed.frag 3840 2160 20
  -> ms/frame, image statistics, the being's centroid and top edge,
     and whether the palette is still in the blue family

BENCH_U="uValence=0.1,uIrritation=0.9" BENCH_PPM=/tmp/out.ppm familiar-bench proposed.frag 1600 1600
  -> renders any exact mood to an image

BENCH_WORLD=1920x1080 BENCH_ORIGIN=0,938 BENCH_FILL=1 BENCH_PRESENCE=0 \
  familiar-bench proposed.frag 80 142
  -> renders exactly what the bar porthole renders, to prove the two windows still agree
```

Send a `.frag`, get numbers and renders back. A design that is beautiful at 20 ms is not shippable
here, and the bench finds that out far more cheaply than the desktop does.

### Success criteria

- At 3840x2160, a still of it survives being **zoomed to 200%** and still has structure to look at.
- A stranger asked "what is this a photo of?" says **an eye**, and cannot say whose.
- The invented anatomy is **consistent**: the same structures in the same places, deforming
  plausibly, frame after frame.
- **Dilation is a shape change**, not a scale factor, and it responds to light and to focus.
- Mood remains legible across all nine scalars, and irritation still burns magenta.
- <= 8 ms/frame at 4K, verified.
- Silhouette glass-smooth and rock-stable at all times.
- It is unsettling to look at for slightly too long. It should feel like it is looking back.
