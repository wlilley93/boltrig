# The genotype: a maximal parameter set for authoring familiars

Goal: an editor that can produce millions of distinct familiars, and a deterministic
seed per sub-agent so each one gets its own stable body - identicons, but alive.

This document is the PARAMETER INVENTORY. It is derived by reading `familiar.frag`
(1699 lines) and recording what actually varies the creature, what is hardcoded, and
what would have to change structurally. Nothing here is aspirational: every entry
names the line or construct it comes from.

## 0. The distinction everything rests on

The shader already has two kinds of input and they must not be confused.

| | PHENOTYPE (exists) | GENOTYPE (proposed) |
| --- | --- | --- |
| What it is | how the being FEELS | what the being IS |
| Count | 9 scalars | ~60 parameters |
| Source | `boltrig/emotion` engine, derived per read | seeded from the agent id, stable forever |
| Changes | second to second | never, unless re-authored |
| Uniforms | `uValence..uTension` | new `uGene[...]` block |

A sub-agent orb is therefore `render(genotype(agent_id), phenotype(now))`. Two agents
in the same mood look different; one agent in two moods is recognisably the same being.
Getting this wrong - folding identity into the mood scalars - would make every agent
look identical whenever they happened to feel the same, which is the whole failure to
avoid.

## 1. SILHOUETTE - the structural change

**Today the silhouette is not a parameter. It is `length()`.**

    familiar.frag:231   float dScreen = length(uv - centre);

That single call is why every familiar is a circle. `RADIUS`, `uFitScale` and the swell
terms scale it; nothing can un-circle it. Figures-of-8, bowties and lobed forms are not
reachable by tuning - the distance function itself has to be replaced.

Two families cover the ask between them, and they compose:

**Cassini ovals** - `|p-f1| * |p-f2| = b^2`. One parameter walks the whole path from
circle to figure-8 to two separate bodies, which is exactly the requested range:

    a = 0        perfect circle
    a < b        ellipse, then egg
    a -> b       peanut / dumbbell, waist closing
    a = b        LEMNISCATE - the true figure-of-8
    a > b        two separate lobes orbiting a shared centre

**Superformula** (Gielis) - `r(t) = (|cos(m t/4)/A|^n2 + |sin(m t/4)/B|^n3)^(-1/n1)`.
Gives the angular families Cassini cannot: triangles, squares, stars, flowers, gears.

**CORRECTION, made by rendering rather than reasoning.** An earlier draft of this
document claimed the superformula produced bowties at `m=2` with low `n1`. It does
not. Rendered, `m=2` gives an ellipse at low `n1` and a circle with four spikes at
high `n1` - never a bowtie. The bowtie IS the lemniscate, i.e. the `a = b` case of
Cassini, where the two lobes meet at exactly a point. Bowtie and figure-of-eight are
the same curve, and both belong to Cassini. The claim was plausible and wrong, which
is exactly what a contact sheet is for.

| # | Parameter | Range | What it does |
| --- | --- | --- | --- |
| 1 | `shapeFamily` | enum 0..2 | cassini / superformula / blend of both |
| 2 | `shapeBlend` | 0..1 | crossfade when family = blend |
| 3 | `focalSep` (a) | 0..1.4 | circle -> peanut -> figure-8 -> split |
| 4 | `cassiniB` | 0.4..1.2 | body thickness at the waist |
| 5 | `lobeBalance` | -1..1 | one lobe larger than the other |
| 6 | `superM` | 0..12 | symmetry order: 2 = ellipse/lens, 3 = triangle, 5 = star, 12 = gear (NOT bowtie - see the correction above) |
| 7 | `superN1` | 0.1..8 | overall pinch; low = spiky, high = round |
| 8 | `superN2` | 0.1..8 | horizontal exponent |
| 9 | `superN3` | 0.1..8 | vertical exponent |
| 10 | `superA` / `superB` | 0.5..2 | per-axis scale inside the formula |
| 11 | `aspect` | 0.5..2 | stretch x vs y |
| 12 | `rotation` | 0..2pi | resting orientation |
| 13 | `twist` | -1..1 | rotation that varies with radius; shears the lobes |
| 14 | `edgeSoftness` | 0..1 | hard silhouette vs vapour |
| 15 | `cornerRound` | 0..1 | post-hoc rounding of any sharp vertices |

## 2. PALETTE

From `familiar.frag:214-227`. The ramp is four hardcoded `vec3`s plus a magenta for
irritation, mixed by valence. Parameterise as HSV so a seed can walk hue coherently
rather than producing mud.

| # | Parameter | Notes |
| --- | --- | --- |
| 16 | `hueBase` | 0..1; today's family sits at navy->sky |
| 17 | `hueSpread` | how far the ramp travels across valence |
| 18 | `hueDirection` | +/-; ramp warm-ward or cool-ward |
| 19 | `saturation` | global |
| 20 | `valueFloor` | how dark the darkest tone is (the "near-black navy" of the brief) |
| 21 | `warmth` | the `WARMTH` const, line 74: ember at the core |
| 22 | `irritationHue` | today hardcoded magenta `vec3(0.820,0.180,0.620)` |
| 23 | `irritationGain` | `irr*0.70` at line 223 |
| 24 | `highlightHue` | `hot` mix target, line 226 |
| 25 | `highlightGain` | `0.40 + 0.18*lum` |
| 26 | `dayTintCool` / `dayTintWarm` | line 225, the day/night pair |
| 27 | `paletteMode` | enum: analogous / complementary / duotone / mono |

## 3. INTERIOR

| # | Parameter | Source |
| --- | --- | --- |
| 28 | `shells` | `SHELLS = 5`, line 70 |
| 29 | `shellSpacing` | layered interior mist falloff |
| 30 | `silkOctaves` | the `w1/w2/silk` chain, lines 285-287 |
| 31 | `silkScale` | `w*1.1`, `w*1.5`, `w*1.7` |
| 32 | `silkChurn` | `(1.9 + 0.8*irr)` warp strength |
| 33 | `veinDensity` | subsurface veins |
| 34 | `veinContrast` | |
| 35 | `nucleusSize` | the dark core |
| 36 | `nucleusDarkness` | |
| 37 | `refractDepth` | interior subsurface refraction |
| 38 | `lensRing` | line 334, the refractive rim around the heart |

## 4. SURFACE

| # | Parameter | Source |
| --- | --- | --- |
| 39 | `bumpAmp` | `bump` gradient, lines 249-251 |
| 40 | `bumpScale` | `bq` frequency |
| 41 | `ridgeSharp` | `ridge()`, line 119 - the tension ridges |
| 42 | `ridgeGain` | how much tension raises them |
| 43 | `specSharp` | dual-lobe wet specular |
| 44 | `specGain` | |
| 45 | `fresnelPower` | |
| 46 | `roughness` | |
| 47 | `lightDir` | `L = normalize(vec3(-0.50,0.62,-0.60))`, line 232 |

## 5. EMISSION

| # | Parameter | Source |
| --- | --- | --- |
| 48 | `sparks` | `SPARKS = 7`, line 71 |
| 49 | `embers` | `EMBERS = 12`, line 72 - rim particles |
| 50 | `moteSize` | |
| 51 | `moteSpeed` | |
| 52 | `ejectRate` | line 452 |
| 53 | `haloReach` | `haloK`, line 421 |
| 54 | `haloGain` | |
| 55 | `coronaMode` | enum: none / halo / sonar / skirt |

## 6. MOTION

| # | Parameter | Source |
| --- | --- | --- |
| 56 | `tempoBase` | `0.26` in the tempo expression, line 143 |
| 57 | `tempoArousalGain` | `0.85*arousal` |
| 58 | `tempoFatigueDamp` | `1.0 - 0.45*fatigue` |
| 59 | `breathRate` | |
| 60 | `breathDepth` | |
| 61 | `gazeReach` | line 1156, how far a cursor pulls attention |
| 62 | `wobble` | |

## 7. What is NOT a genotype parameter

Recorded so the editor does not grow the wrong knobs:

- **The 9 phenotype scalars.** Mood, not identity. An editor slider for them is a
  PREVIEW control (see what this body looks like when irritated), never a saved value.
- **`uPresence`, `uAperture`, `uCompanion`, `uFill`, `uHover`, `uDock*`** - host/window
  state, owned by the harness.
- **`FAMILIAR_REALM`** - the room, not the being. Shared backdrop.
- **`FAMILIAR_THEME`** - currently a `#define` selecting eye / plasma / silk. Arguably
  a genotype gene, but it swaps whole `main()` branches rather than tuning one, so it
  is a coarse family selector above the genotype rather than a parameter inside it.

## 8. Combinatorics

62 parameters. Even at a conservative 8 distinguishable steps each, and counting only
the 15 shape parameters, that is 8^15 - about 3.5e13 silhouettes before colour. The
practical bound is not the space, it is DISTINGUISHABILITY: two genotypes that differ
only in `bumpScale` are the same being to a human at 64px.

So the seeding function matters more than the count. A useful seed:

1. hashes the agent id to a 64-bit value;
2. spends most bits on the parameters that read at a glance - `shapeFamily`, `superM`,
   `focalSep`, `hueBase`, `coronaMode`;
3. spends few bits on fine surface detail;
4. is CONSTRAINED, not uniform: sample from curated ranges per family so no seed can
   produce an unreadable smear. The R&C editors did this implicitly - their sliders had
   ranges chosen by someone who knew which values looked wrong.

## 9. The three deliverables this implies

1. **Shape rewrite** - replace `length(uv - centre)` with a parameterised SDF. This is
   the only structural change; everything else is promoting a constant to a uniform.
2. **The editor** - live sliders over all 62, grouped as above, with a preview that can
   also drive the 9 phenotype scalars so you can see the body in every mood before
   committing it.
3. **The seeder** - `genotype(agent_id) -> 62 values`, deterministic, curated ranges,
   with a contact sheet renderer so a hundred agent orbs can be eyeballed at once for
   collisions.

## 10. Honest limits

- The parameter list is derived from THEME 2 (silk), the body that currently renders.
  Themes 0 (eye) and 1 (plasma) have their own constants; a full inventory of those is
  not done here and would add perhaps 20 more, many of them eye-specific (iris filament
  count, collarette, limbal ring, tapetum).
- Line numbers are from `familiar.frag` at the time of writing and will drift.
- **A PARTED BODY HAD NO CORE, AND SO ALMOST NO LIGHT. FIXED 2026-07-27.**
  Measured before: a Cassini genotype past the split (`focal=1.05, cassiniB=0.85`) rendered at
  5.9% lit with a peak of 39/255, and the bench called it `SUSPECT (flat/black?)`. The maths was
  right - the lobes exist within +/-20.5 degrees and span r 0.616..1.351 - but every downstream
  consumer measured depth as distance from the FIGURE's centre, and a parted figure's centre is
  the empty gap between its lobes. Each lobe rendered as the rind of a sphere whose glowing
  middle had been cut out.
  Now, when the body is parted, depth is measured across the LOBE's own thickness: zero on its
  radial mid-line, `scale` at both of its boundaries. Measured after: **12.9% lit, peak 239**,
  and the bench calls it a creature. Two lit lobes, each with its own interior.
  The fix took two goes and the first one was worse than the bug: it returned a dimensionless
  0..1 and the body vanished entirely, because the contract is NOT "1.0 on the silhouette" as
  the header of shape.glsl said - it is that the value equals `scale` there, since every
  downstream test compares against `scale`. `gScale` is threaded in for that one branch.
- The genotype shapes the SILHOUETTE and, via the remapped ray origin, the body volume.
  It does not yet reach the 47 remaining interior constants (silk band edges, mote counts,
  ember placement), which stay hardcoded.

**Build status of this section's claims (2026-07-27).** Built, compiled, rendered and looked
at: the silhouette, the body volume, the parted-lobe interior, hue and saturation, six
interior multipliers (warmth, breathDepth, bumpAmp, silkChurn, specSharp, haloReach), two
motion genes (tempoBase, bodyScale) and six for light and surface (specGain, fresnelGain,
haloGain, irritationGain, lightAzimuth, bumpScale). That is **30 of the ~107 parameters
inventoried above**, held in 32 uniform slots with 2 reserved.

The identity case is verified pixel-equal to the pre-genotype shader and re-verified after
every growth since: the circle measures mean 46.7 / sd 54.9 / max 239 / 38.4% lit, unchanged
throughout.

Every gene is measured by PER-PIXEL DIFFERENCE against the identity render, not by whole-frame
statistics. That distinction earned its keep on the last batch: `specGain` and `bumpScale` move
the frame's mean by less than 0.2 of a level and would read as dead on an aggregate, while the
diff shows them changing 1 to 2 percent of pixels by up to 83 levels. A whole-body average is
the wrong instrument for a localised term, which is the same mistake that once hid the ember at
the core.

`irritationGain` is measured twice on purpose: it must move pixels under irritation (it changes
41% of them at `uIrritation=0.6`) and must move NONE without it (measured: maxdelta 0). A gene
that leaks into a mood it does not belong to is worse than a gene that does nothing.

The remaining ~77 are NOT built, and the count is stated because "the genotype" was starting to
read as though the whole inventory existed. Four parameters were briefly believed built and
were not: `warmth` was first wired to a `#define` only theme 0 reads, caught because a 3x sweep
measured byte-identical; `moteGain` and `ejectRate` were wired, swept, found to change no pixel
in any mood (they feed a term discarded wherever `uPresence` is 1) and REMOVED before shipping;
and an earlier draft of section 1 claimed the superformula makes bowties, caught by a contact
sheet. None would have been caught by a test. Assume nothing in the un-built list works until
it has been drawn.


---

# 11. TEMPERAMENT - the third layer, and it is already data

Body and mood are not enough for personality. A familiar's character is mostly *how it
responds*: how fast it takes offence, how long it broods, how quickly curiosity fades.
That is a transfer function between events and mood, and it is neither the genotype
(which is static) nor the phenotype (which is the output).

**It is already fully parameterised.** `boltrig/libraries/emotion/model.yaml` is data,
loaded by `tables.py:_parse_model` into an `EmotionModel`. No code change is needed to
give an agent its own temperament - only its own model file.

| Group | Count | Per-item parameters |
| --- | --- | --- |
| Emotions | 14 | `baseline` (0..1), `half_life_h` |
| Needs | 8 | `default` (0..10), `decay_h` |
| Global | 1 | `tempo` (model-hours per real minute) |
| **Total** | | **45** |

The 14 emotions: connection, curiosity, confidence, warmth, frustration, playfulness,
amusement, anticipation, satisfaction, restlessness, tenderness, melancholy, focus,
defiance.

The 8 needs: stimulation, expression, purpose, autonomy, recognition, novelty, social,
rest.

Two agents with identical bodies and identical event streams will FEEL differently if
their temperaments differ, and that difference shows on the orb through the phenotype.
A `frustration` half-life of 0.25h versus 4h is the difference between an agent that
shrugs things off and one that sulks for the rest of the session.

Worked examples of what the 45 buy:

- **Placid**: frustration baseline 0.05 / half-life 0.5, melancholy half-life 1,
  tempo 90 (slow world).
- **Volatile**: frustration baseline 0.2 / half-life 3, defiance baseline 0.25,
  restlessness half-life 2.
- **Eager**: curiosity baseline 0.85 / half-life 0.5, novelty decay 2 (bores fast),
  anticipation baseline 0.7.
- **Dogged**: focus baseline 0.8 / half-life 4, rest decay 48, satisfaction half-life 6.

# 12. The complete count

| Layer | Parameters | Status |
| --- | --- | --- |
| Genotype (body) | 62 | 15 shape params BUILT (`shape.glsl`); 47 still hardcoded |
| Temperament (personality) | 45 | already data; needs per-agent model files |
| Phenotype (mood) | 9 | live, derived, not authored |
| **Authored total** | **107** | |

# 13. Build status

**Done and verified:**

- `shape.glsl` - the parameterised silhouette. Compiles under `glslangValidator` as
  GLES3. Renders the full Cassini walk (circle -> egg -> peanut -> lemniscate -> two
  parted lobes) and the superformula families (star, flower, triangle, square, gear),
  checked on a contact sheet rather than asserted.
- One real defect found and fixed by that check: the first cut took only the `+` root
  of the Cassini quadratic, which is right for `a <= b` and silently wrong above it -
  the waist filled in, so every "split" case rendered as a solid bowtie. A scanline
  through the centre reported `inside=True` at `a=1.40`, where the figure should have
  been empty. Now returns both roots and treats the inner one as the gap.

**Not done:**

- `shape.glsl` is not yet wired into `familiar.frag`. The drop-in is one line (231),
  plus 15 new uniforms and their host-side plumbing in `main.c`.
- The other 47 genotype parameters are still constants in the shader.
- No editor, no seeder, no contact-sheet renderer for whole familiars.
- Themes 0 (eye) and 1 (plasma) are not inventoried; the eye alone would add perhaps
  20 more (iris filament count, collarette, limbal ring, tapetum).
