---
tags: [frontend, 3d, wip]
updated: 2026-05-29
---

# Particle Brain (WebGL)

The home-page hero: a brain GLB sampled into a point cloud and rendered with
[React Three Fiber](https://r3f.docs.pmnd.rs/). Ported from the vanilla `three`
prototype `scenes/brain-particles.html`. Adoption rationale + trade-offs are in
[[decisions-log]] ADR-0013; deps are in [[tech-stack]].

## Module map — `src/components/brain/`

| File | Role |
|------|------|
| `index.ts` | Public exports (`BrainCanvas`, `BrainHud`, `BrainControls`, `BrainLoader`, `BRAIN_CONFIG`, `useBrainControls`, types) |
| `config.ts` | `BRAIN_CONFIG` defaults + `serializeBrainConfig` + render `BRAIN_LAYERS` |
| `brain-canvas.tsx` | **Client leaf** — the `<Canvas>`, background/fog, `<Suspense>` |
| `brain-camera-rig.tsx` | Scroll-driven camera (replaces `OrbitControls`) — damps between story keyframes |
| `story/use-story.ts` | **zustand store** — global scroll `{progress, section}` (read imperatively in the loop) |
| `story/story-keyframes.ts` | Per-chapter camera `{position,target}` + region/highlight/explode; `sampleStory()` |
| `brain-scene.tsx` | Brain + ambient `<points>`; fly-in reveal + live uniform sync; drives focus/explode from scroll |
| `brain-renderer.tsx` | Takes over the render loop — 2 composers, real UnrealBloom + warped gradient; live corner colours |
| `use-brain-resources.ts` | Loads the GLB (`useGLTF`), samples the surface (count/occlusion from the store), builds uniforms once |
| `use-brain-controls.ts` | **zustand store** — live `config` + camera params + panel state (the control source of truth) |
| `brain-controls.tsx` | The parameters drawer (dev-only) — colour/size/count/motion/cursor/bloom controls + copy-paste config export. Open via the floating ⚙ button (bottom-right) or **Shift+P** |
| `brain-hud.tsx` | Corner HUD chrome — eyebrow, title, status, parameters toggle |
| `brain-telemetry.tsx` | Terminal-style neural monitor (top-right) — live synthetic telemetry feed |
| `brain-loader.tsx` | Immersive breathing loader (drei `useProgress`) that fades out on load |
| `lib/sampling.ts` | Triangle gather, area-weighted sampling (positions + normals), centre/scale, cavity occlusion, hex→vec3 |
| `lib/shaders.ts` | GLSL sources (ambient, brain, final composite) |

Model asset: `public/assets/brain/rotten-brain.glb`.

> [!note] Now a scroll-driven narrative again (ADR-0017, supersedes ADR-0014)
> The static orbital view was replaced by a **5-chapter scroll story**: a fixed
> brain canvas behind an animated DOM overlay (`src/components/story/`, see
> [[story-sections]]), with `brain-camera-rig.tsx` flying the camera between
> `story/story-keyframes.ts` from scroll progress (`story/use-story.ts`).
> `BrainScene` now **drives** the previously-dormant highlight/explode uniforms
> from `sampleStory(progress)` — chapters scan a region, the finale disperses the
> brain. `OrbitControls` (`brain-orbit.tsx`) and `BrainHud` are gone. The
> historical scrollytelling sections below describe an earlier removed
> implementation and are kept only for reference.

## Live controls, loader & HUD (ADR-0015)

- **Control store** — `useBrainControls` (zustand) holds the live `config`
  (mirrors `BRAIN_CONFIG`), camera params, and panel open state. It is the single
  source of truth for the live look; `BRAIN_CONFIG` is the default seed.
- **How edits reach the GPU** — colour/size/motion params are pushed into the
  shader uniforms by an **identity-checked sync inside `useFrame`** (`BrainScene`
  for the brain/ambient uniforms, `BrainRenderer` for the corner-gradient
  colours). Writing in the loop keeps `useFrame` the sole writer of the material
  refs — required by the `react-hooks/immutability` lint rule. Count / occlusion
  params instead re-render `useBrainResources` (selector subscription) so the
  geometry rebuilds; the panel commits those sliders **on release** to avoid
  re-sampling the point cloud every drag step.
- **Config export** — `serializeBrainConfig(config)` reproduces the exact
  `BRAIN_CONFIG` source literal; `BrainControls` shows it in a copy block so a
  tuned look can be pasted back into `config.ts` as the default.
- **Loader** — `BrainLoader` reads drei `useProgress` (the shared THREE loading
  manager) and shows a breathing neural field + calm phrase + progress meter over
  a deep radial-blue void, fading out once the model loads (min-hold + a hard-cap
  fallback for instant/cached loads where the manager never re-fires).
- **HUD + telemetry** — `BrainHud` anchors the corners; `BrainTelemetry`
  (top-right) is a terminal-style monitor streaming *synthetic* synaptic activity
  (firing rate, coherence, a waveform sparkline, a cycling focus region, an
  appended log feed, a blinking cursor). Looping motion is `@react-spring/web`;
  the streaming data updates on `setInterval` in effects, seeded with static
  values so SSR and the first client render match. All chrome is
  pointer-transparent except the toggle/panel, so orbit works anywhere.
- **Tokens** — DOM chrome uses `--brain-void/-deep/-azure/-sky` (→
  `bg-/text-/border-brain-*`) from `globals.css`, matched to the scene palette.

## Depth & immersion

- **More, smaller particles** — `surfaceCount` 360k, `particleSize` 0.03.
- **Looped surface flow** — every particle continuously traces a *full closed
  circle* within the **tangent plane** of its baked surface normal (`aNormal`,
  from `sampleSurface`), so it orbits *on* the brain's shape rather than off it.
  Tuned by `flowSpeed` / `flowAmount` (the loop radius) — kept small so the shape
  stays readable.
- **Cavity occlusion** — `computeOcclusion` (in `lib/sampling.ts`) bakes a
  per-particle `aOcclusion` (0 = exposed gyrus → 1 = deep sulcus) from local
  point density via a spatial hash. The brain shader sinks occluded particles
  toward `deepColor` (a **dark green**, via `occlusionStrength`), so the folds
  (вмятины) read as depth.
- **Region highlight + focus framing** — `BrainScene` drives `uHighlightPos` /
  `uHighlightStrength` from `activeAct(scrollProgress)`; particles within
  `highlightRadius` of the active region tint toward `highlightColor` (a deeper
  green accent) and grow. The **brain holds a fixed orientation** — the *camera*
  frames each region (`frameRegion` in `story-keyframes.ts` looks at the
  region's anchor from outside it), so the focal zone lands centred. This
  decoupling (no camera↔brain rotation feedback) is what keeps the scroll
  smooth.
- **Focus isolation** — while a region is active, every particle that *isn't*
  the highlighted cluster darkens toward `deepColor` (`isolateStrength`), so the
  zone clearly stands out; the side opposite the region also fades in alpha
  (`vFar` × `focusFadeStrength`, gentler now that the darkening carries it).
  Anchors live in `story-regions.ts` (brain-local space; the brain is unrotated,
  so anchor = world position).
- **Finale blow-up + neuron constellation** — over the last stretch of scroll
  (`uExplode`, ramped 0.9→1) the brain's particles fly outward (`uExplodeDist`)
  and fade while the camera dives inside it (Act 5 keyframe). As they disperse, a
  **neuron constellation** (`BrainConstellations`: star nodes + nearest-neighbour
  link lines, `constellationCount` / `constellationColor`) fades in (scroll
  0.92→1), so the brain resolves into the neural network it represents.

## Entrance & camera framing

- **Fly-in entrance** — the reveal is gated on `useStory.entered` (set by
  `BrainLoader` as it hands off). Once entered, `BrainScene` eases `eased` 0→1 over
  ~3 s (easeOutQuart) and, with the **brain fully assembled** (no entrance explode —
  `uExplode` carries only the scroll finale now), flies the group in **from near the
  camera** (`REVEAL_START_Z` 3.6 → 0) while **unwinding one full 360° horizontal
  turn** (`REVEAL_SPIN` = 2π, `(1 - eased) * REVEAL_SPIN`) into its resting
  orientation as the loader crossfades out. Cursor parallax is damped in refs
  (`parallaxRY`/`parallaxRX`) so the reveal spin layers on top without two writers
  fighting over `group.rotation`.
- **Responsive framing** — `BrainCameraRig` post-processes each sampled keyframe by a
  `mobile` factor from the viewport aspect: on narrow/portrait screens it drops the
  lateral `target` offset (centres the brain) and pushes the camera back so the
  side-framed keyframes don't crop it on tablet/phone.

## Cursor interactivity (hover halo + parallax)

Pointing at the brain ignites the particles under the cursor — they brighten and
swell, so neurons appear to fire where you point. The brain group also **tilts a
touch toward the pointer** (eased, scaled by the cursor strength). It is **screen-space**, not a
raycast: `BrainScene` listens to `pointermove` on the window, converts to NDC, and
each frame eases the `uMouse` uniform toward it (plus `uCursor` strength in/out and
`uAspect` for a circular halo). The brain vertex shader computes each particle's
NDC distance to `uMouse` into a `vCursor` varying (sized up); the fragment adds
`uCursorColor * vCursor` additively (kept subtle so even dim particles register).
The halo's NDC radius (`uCursorRadius`) **shrinks with camera distance** (driven from
`camera.position.length()` in `BrainScene`), so it stays small relative to a distant
brain. Uniforms live in `use-brain-resources.ts`; the effect is independent of
camera/brain position.

The whole effect is **fully tunable** from the **Cursor** section of the control
panel (six `BRAIN_CONFIG.cursor*` fields, all live + exported):
- `cursorColor` → `uCursorColor` (halo tint).
- `cursorStrength` → `uCursorStrength`, a uniform that scales the three previously
  hardcoded shader constants together — the vertex point-size swell and the
  fragment's additive colour + alpha lift. `0` switches the halo off.
- `cursorRadius` → the base of the distance-scaled `uCursorRadius` (the runtime
  clamp is now `0.4×..1.3×` this base, not the old fixed `0.04..0.13`).
- `cursorFollow` → the per-frame `uMouse` lerp factor (how fast the halo trails).
- `cursorFade` → the per-frame `uCursor` in/out lerp (how fast it fades on enter/leave).
- `cursorParallax` → multiplier on the brain's tilt-toward-pointer (`0` = no tilt).

## Annotated callouts

`BrainLabels` renders one drei `<Html>` per anchored region **inside the brain
group** (so labels track the rotating anatomy). A leader line runs up from a dot
on the surface to the region name. Only the active chapter's label is visible,
faded in/out with `@react-spring/web` (spring, not CSS — rule #1). Tune anchor
positions / copy in `story-regions.ts`.

## The scrollytelling ("Brain Story")

`HomeView` stacks a `position:fixed` `<BrainCanvas>` (z-0) behind the
`<StoryChapters>` overlay (z-10, `pointer-events-none` so parallax still reaches
the canvas). One scroll progress value (0→1, from `useScrollProgress`) drives
`CameraRig`, which eases the camera between `STORY_KEYFRAMES`. Position is
interpolated in **spherical coordinates around the brain centre**, so the camera
**orbits around** the brain (arcing to the far side) rather than dollying
through it; the look-at target lerps linearly. Acts: **Arrival (from the side) →
Cortex → Synapse → Hemispheres → Occipital (rear) → The Whole (blow-up + dive inside)**. To extend it, add a
keyframe (`story-keyframes.ts`) + a region (`story-regions.ts`) + a chapter
(`brain-story.ts`) at the same index. `prefers-reduced-motion` holds the
opening framing.

## How it renders

`BrainRenderer` registers a **positive-priority `useFrame`**, which makes R3F
hand off rendering. Each frame it runs **two** `EffectComposer`s:

1. `sceneComposer` — `RenderPass` → `GammaCorrectionShader` → one `UnrealBloomPass`
   (real bloom). Its `strength` / `radius` / `threshold` are seeded from
   `BRAIN_CONFIG.bloom*` and **live-synced from the store each frame** (plain props
   on the pass — assign-per-frame, no rebuild), so the panel can tune bloom in
   real time. Everything is on the default layer, so there is **no per-frame
   `camera.layers` switching**.
2. `finalComposer` — a single full-screen `ShaderPass` compositing that
   scene+bloom (`tScene`) over the warped corner-gradient background.

> [!note] Flicker fix (ADR-0016)
> The original prototype's **three-composer / layer-mask** pipeline (soft bloom →
> strong bloom → final, switching `camera.layers` each pass) flickered: with the
> scrollytelling removed, two composers rendered *empty* layers and the camera
> layer mask was rewritten every frame. It was collapsed to the one-render +
> one-bloom pipeline above — same genuine `UnrealBloom`, temporally stable. The
> `BRAIN_LAYERS` constant in `config.ts` is now unused (kept for reference).

## Conventions that apply here

- **Motion**: animation *inside* the canvas (shader uniforms, transforms,
  camera) runs on the R3F loop, **not** `@react-spring/web`. The spring-only
  rule ([[animation-system]]) governs DOM motion only — see ADR-0013.
- **Per-frame mutation goes through refs** (material refs, `useRef`), never by
  mutating a hook's memoised return — the `react-hooks` immutability lint rule
  (the `yarn lint` gate) forbids the latter.
- **Tuning** the look: edit `BRAIN_CONFIG` (colours, counts, speeds, glow). The
  current palette is **deep blue** (navy/azure/sky) — particles + the warped
  background gradient (`cornerBlue`/`cornerOrange`). These are scene *content*,
  not `globals.css` design tokens.
- **Camera**: `BrainCameraRig` (replaces `OrbitControls`) — reads scroll
  `progress` imperatively and damps the camera between `STORY_KEYFRAMES`. Runs at
  default `useFrame` priority, before `BrainRenderer` (priority 1) renders.
  `prefers-reduced-motion` holds the opening framing. See [[story-sections]].

## Related

[[decisions-log]] · [[tech-stack]] · [[component-conventions]] · [[animation-system]] · [[routing]]
