---
tags: [meta, changelog]
updated: 2026-05-23
---

# Changelog

Chronological log of notable changes to the project. Newest first.
This is a human-curated log — not a mirror of `git log`.

## 2026-06-06

- **Content arrives a beat after the loader** — `StoryOverlay` delays the copy +
  chrome *reveal* via a new `useContentReady()` (`entered` + `CONTENT_DELAY_MS`
  500 ms), so the narrative reveals *after* the brain's fly-in begins, instead of
  animating in unseen behind the loader curtain. The scroll stack stays **mounted
  from first paint** so (a) `StoryScrollDriver` seeds `progress` from a full-height
  document (else top == bottom → scene snaps to the finale on load) and (b) all the
  heavy `TextEngine` mounting happens behind the loader curtain. The reveal is a
  **cheap opacity + translateY fade, no remount** — an earlier keyed remount for a
  fresh staggered reveal caused a frame-stall lag as the brain flew in, so it was
  dropped. See [[story-sections]].
- **Reveal reworked → fly-in + 360° spin** — replaced the assemble-from-dispersed-
  particles entrance with a solid fly-in: the fully-assembled brain now enters
  **from near the camera** (`REVEAL_START_Z` 3.6 → 0) while **unwinding one full
  360° horizontal turn** (`REVEAL_SPIN` 2π) into its resting orientation over the
  same ~3 s easeOutQuart. The entrance no longer drives `uExplode` (that now carries
  only the scroll finale), and cursor parallax moved into refs so the spin layers
  cleanly on top. See [[particle-brain]].
- **Full cursor-effect controls** — added a **Cursor** section to the panel with
  six live, exportable `BRAIN_CONFIG.cursor*` knobs: halo colour, strength
  (a new `uCursorStrength` uniform scaling the swell + glow + alpha that were
  hardcoded shader constants), halo size (base of the distance-scaled radius),
  follow smoothing, fade speed, and parallax-tilt multiplier. Previously these
  were scattered magic numbers in `brain-scene.tsx` / `shaders.ts` /
  `use-brain-resources.ts`. See [[particle-brain]].
- **Discoverable controls toggle** — the dev-only parameters drawer was
  Shift+P-only with no on-screen affordance, so it read as "no controls". Added a
  floating ⚙ button (bottom-right, dev-only, hidden while open) that opens it;
  Shift+P still works. See [[particle-brain]].
- **Bloom in the control panel** — the three `UnrealBloomPass` params (strength,
  radius, threshold) moved from hardcoded constants in `brain-renderer.tsx` into
  `BRAIN_CONFIG` (`bloomStrength` 0.7 / `bloomRadius` 0.4 / `bloomThreshold` 0).
  The renderer seeds the pass from config and live-syncs the props each frame
  (same pattern as the corner colours), and a new **Bloom** section in
  `BrainControls` exposes all three as sliders — so they tune in real time and
  bake into the copy-paste config export. See [[particle-brain]].
- **Brain look retune** — ported the adjusted particle parameters from the
  `getlayers-scenes` scroll-spin prototype into `BRAIN_CONFIG`: bigger, sparser
  particles (`particleSize` 0.038→0.067, `ambientSize` 0.026→0.067,
  `ambientCount` 8000→4500, `surfaceCount` 180000→140000), a tighter/punchier
  centre (`centerRadius` 0.795→0.37, `centerFalloff` 1.45→4), wider ambient drift
  (`ambientRange` 11→15.5), livelier synapses + flow (`synapseRate` 0.07→0.1,
  `flowSpeed` 1.5→2.3), much stronger glow (`glowStrength` 0.54→2), and a darker
  deep colour (`deepColor` #04122e→#010b1e). See [[particle-brain]].
- **Entrance, loader polish, cursor interactivity, responsive pass**:
  - **Assemble-in entrance** — the brain now plays its reveal *after* the loader hands
    off: a new `entered` flag on `useStory` (set by `BrainLoader` when it starts fading)
    gates `BrainScene`'s reveal, which ramps the explode uniform 1→0 so the particles
    **converge from a dispersed cloud** (eased, 3 s) as the curtain crossfades out.
  - **Loader** — smoother (longer eased curtain) and slicker: a console **boot sequence**
    (breathing core + `> SAMPLING CORTICAL SURFACE` status line with a blinking caret +
    a glowing progress meter). Sets `entered` on hand-off.
  - **Cursor parallax** — the brain tilts a touch toward the pointer (eased, scaled by
    the cursor-halo strength so it's still until you move), on top of the existing halo.
  - **Centred text fix** — `TextEngine` lays words out in a flex row, so `text-align`
    alone didn't centre the Signals title / the finale copy; pass
    `style={{ justifyContent: "center" }}` for centred instances.
  - **Responsive (tablet/mobile)** — the camera rig now **centres the brain and pulls
    back on narrow/portrait viewports** (derived from `state.size` aspect) so the
    side-framed keyframes don't crop it; the telemetry bar drops more segments on small
    screens.
- **Slick dark terminal panels + chrome cleanup**:
  - **`TerminalPanel`** (`story/terminal.tsx`) — a dark "terminal window" (`NAME.LOG`
    titlebar + LIVE light, a `>`-prompted body line, `▸ KEY … VALUE` data rows, blinking
    cursor). Used **only on the black-background takeover chapter** (Signals), where it's
    enlarged to ~half-screen width. The brain chapters keep plain terminal-styled text
    (kicker + headline + body + `▸ KEY  VALUE` rows), no panel.
  - **Chrome stripped down** — removed the page-edge corner brackets and the "Scroll to
    explore" hint; `StoryChrome` is now just the chapter progress rail, **moved to
    bottom-centre** (was bottom-right). The top edge stays framed by the telemetry bar.
- **Telemetry status bar + cursor tuning + 7 chapters**:
  - **Neural monitor → full-width top status line** — `BrainTelemetry` moved from a
    top-right boxed panel to a thin **fixed top bar** spanning the viewport (a console
    title bar): inline `LABEL VALUE` segments (neurons, particles, firing, coherence,
    chapter focus), a running waveform pushed right, and a blinking `>` prompt. The
    two **top** corner brackets were dropped from `StoryChrome` (the bar frames the top
    edge now); bottom corners + rail remain.
  - **Cursor halo tuning** — softer (glow ×1.7→0.8, alpha ×0.65→0.32, size ×2.6→1.3)
    and its NDC radius now **shrinks as the camera pulls away** (new `uCursorRadius`
    uniform, driven from camera distance in `BrainScene`), so it stays small relative
    to a distant brain instead of filling the screen.
  - **Removed the Integration chapter** (old step 7) — Balance now leads straight into
    the finale ("The Whole"), which absorbs the ignition/blow camera. `STORY_SECTIONS`
    and `STORY_KEYFRAMES` are 8 → **7** (still in lockstep).
- **Terminal UI treatment + cursor-reactive brain**:
  - **Console-terminal chrome** — story sections + the takeover panel now read like a
    terminal in the scene's blue palette: a `>` command prompt with a blinking `_`
    cursor, `SCREAMING_SNAKE` kickers, wide letter-spacing/uppercase, `▸ KEY  VALUE`
    data rows, and a `[ BRACKETED ]` CTA. Shared helpers live in
    `src/components/story/terminal.tsx` (`term()` + `<TerminalCursor>`). The finale
    chapter is fully centre-aligned.
  - **Cursor halo on the brain** — pointing at the brain ignites the particles under
    the cursor (they brighten + swell, like neurons firing where you point). New
    shader uniforms `uMouse` / `uCursor` / `uAspect` / `uCursorColor` (`lib/shaders.ts`,
    `use-brain-resources.ts`); `BrainScene` tracks `pointermove` (window) → NDC and
    eases the halo each frame. Screen-space + aspect-corrected, so it tracks the brain
    wherever it is on screen. No new geometry.
- **Brand typeface + finale CTA + ignition finale**:
  - **General Sans everywhere** — replaced Onest with **General Sans** (the agency brand
    font, loaded from Fontshare in `layout.tsx`); both `--font-sans` and `--font-mono`
    resolve to it (`globals.css`), so all chrome + copy share one typeface. `next/font`
    (Onest) was dropped.
  - **`StorySection` reskin** — removed the vertical hairline + index tick and the
    generic "Chapter NN ·" eyebrow; the kicker is now a `›` prompt over the headline.
    Section eyebrows relabelled to short names (Arrival, The Cortex …).
  - **Centred finale + CTA** — `StorySectionData` gained `align` and `cta`. The closing
    chapter ("The Whole") is now centre-aligned with a **Begin again** button that
    scrolls back to the top (`scrollTo`).
  - **Ignition finale camera** — keyframe 7 no longer pulls the camera back to the
    front; it keeps sweeping the orbit (rear-right) while the brain blows outward
    (`explode` ramps to 1 there), and keyframe 8 drifts on through the dispersed field
    behind the centred CTA.
  - **Chrome / metadata** — removed the top-left brand label from `StoryChrome`; the
    project name now lives in the document `<title>` via `siteConfig.name`
    ("Neural Atlas", `src/lib/site.ts`).
- **Chrome tweaks** — moved the chapter rail (01–08 progress indicator) from the
  right edge to the **bottom-right** corner (now a horizontal row). Removed the
  dev parameters drawer's on-screen toggle button; it's keyboard-only now
  (**Shift+P**), still dev-only.
- **Fix: scrolling page stranded above the fold** — the global `body` rule in
  `globals.css` was a single-viewport leftover (`display:flex; justify-content:center;
  align-items:center; height:100vh; width:100vw`). On the now-tall scroll story it
  vertically **centred the entire 800vh stack inside one screen**, so the page loaded
  mid-story with the first chapter pushed above the (unreachable) top. Body is now
  normal document flow (`min-height:100vh; width:100%`); `error.tsx` / `not-found.tsx`
  got their own `min-h-screen` to keep centring. The page now starts at chapter 1 and
  scrolls normally.
- **Story polish — 8 chapters + frame-less sections** (follow-up to ADR-0017):
  - **Three more brain chapters** — Vision (occipital), Balance (cerebellum), and
    Integration (parietal). Each orbits the camera to a new angle and highlights a
    distinct region on the brain itself. `STORY_KEYFRAMES` and `STORY_SECTIONS` grew
    5 → 8 in lockstep (their indices must stay aligned); region anchors travel across
    the surface as you scroll, so the highlight sweeps between parts.
  - **`StorySection` redesign** — dropped the bordered/back-blurred card (the copy no
    longer "travels inside a box"). Now a single console hairline + index tick with
    larger type (title up to `~4.6rem`, body `text-lg/xl`); reveal is a gentle in-place
    fade-up rather than a clipped slide.
- **Scroll-driven neural narrative (replaces the static orbital view)** — see
  ADR-0017. The home page is again a scrolling story, rebuilt as an AI-console
  experience:
  - **OrbitControls removed.** A new `brain-camera-rig.tsx` damps the camera between
    per-chapter keyframes (`brain/story/story-keyframes.ts`) from scroll progress;
    the brain stands to one side at rest. `brain-orbit.tsx` deleted.
  - **Story state.** `brain/story/use-story.ts` (zustand `{progress, section}`) fed
    by `story/story-scroll-driver.tsx` off Lenis; read imperatively in the R3F loop
    so scrolling never re-renders the WebGL tree. `BrainScene` now drives the
    previously-dormant `uHighlightPos/Strength` + `uExplode` uniforms — chapters scan
    a region, the finale disperses the brain. No shaders changed.
  - **DOM overlay** (`src/components/story/`): `story-overlay`, `story-section`
    (TextEngine + futuristic scan frame), `takeover` (a ticker-driven `<canvas>`
    "signal field" that hides then reveals the brain — procedural, no video assets),
    and `story-chrome` (persistent console frame + chapter rail). Copy in
    `src/data/story.ts` (draft, editable).
  - **Chrome.** `BrainHud` removed (folded into `story-chrome`); `BrainTelemetry`
    tracks the active chapter; `BrainControls` is now dev-only (mounts in development,
    with its own toggle).
- **Live controls, immersive loader, terminal HUD** — the static brain gained a
  full real-time control surface and a richer chrome layer (see ADR-0015):
  - **Live parameter controls** — a new `useBrainControls` zustand store mirrors
    `BRAIN_CONFIG` + camera params. `BrainControls` is a spring-in drawer (toggled
    from the HUD) with colour pickers, size/motion sliders, count sliders, and an
    auto-rotate toggle. Colour/size/motion edits stream straight into the shader
    uniforms via an identity-checked sync in the render loop (no rebuild,
    no re-render of the WebGL tree); count/occlusion edits commit on release and
    re-sample geometry. `useBrainResources` no longer takes a config prop — it
    reads geometry params from the store and builds uniforms once from defaults.
  - **Config export** — `serializeBrainConfig` (in `config.ts`) renders the live
    values back as the exact `BRAIN_CONFIG` source literal; the panel shows it in
    a copy-paste block so a look can be baked into `config.ts` as the default.
  - **Immersive loader** — `BrainLoader` (drei `useProgress`): a breathing neural
    field (concentric spring-pulsed rings) over a deep radial-blue void, a calm
    `spring-text-engine` phrase, and a thin progress meter; fades itself out once
    the model loads (min-hold + hard-cap fallback for cached loads).
  - **HUD chrome** — `BrainHud`: brand eyebrow (top-left), title (bottom-left),
    live status + parameters toggle (bottom-right). Replaced the old `BrainIntro`.
  - **Terminal telemetry** — `BrainTelemetry` (top-right): a terminal-style neural
    monitor streaming synthetic synaptic activity — fluctuating firing rate +
    coherence, a scrolling waveform sparkline, a cycling focus region, an appended
    log feed, and a blinking cursor. Looping motion is spring-based; the streaming
    data updates on timers in effects (seeded so SSR/first-client render match).
  - **Camera** — `OrbitControls` moved into `BrainOrbit`, which reads live
    `autoRotate`/`autoRotateSpeed` from the store (re-renders only that node).
  - **Panel scroll fix** — the parameters drawer wasn't scrolling because Lenis
    owns the global wheel; added `data-lenis-prevent` (+ `overscroll-contain`) to
    its scroll container so it scrolls natively (see [[smooth-scroll]]).
  - **Bloom flicker fix** — the inherited three-composer / layer-mask render
    pipeline flickered (two composers rendered empty layers; the camera layer
    mask was rewritten every frame). Collapsed `BrainRenderer` to one scene render
    + one `UnrealBloomPass` + a final warped-gradient composite (`tScene`) — same
    real bloom, temporally stable, no layer switching (see ADR-0016). Removed the
    per-points layer assignment in `BrainScene`; `BRAIN_LAYERS` is now unused.
  - **Design tokens** — added `--brain-void/-deep/-azure/-sky` (mapped to
    `bg-/text-/border-brain-*` utilities) so DOM chrome stays in lock-step with
    the scene without raw hex in class names.

## 2026-06-05

- **Single orbital brain — scrollytelling removed** — the home page is now one
  static, elegant viewport instead of a scroll-driven narrative (see ADR-0014):
  - **Deep blue palette** — `BRAIN_CONFIG` retuned from bio-luminescent green to
    deep blue (navy/azure/sky); the warped-gradient background, ambient cloud,
    synapse flash, and deep-fold colour all shifted to blue; canvas
    background/fog now `#01040e`.
  - **Orbit controls** — `BrainCanvas` swaps the scroll-driven `CameraRig` for
    drei `OrbitControls` (drag to rotate, scroll to zoom, no pan, gentle idle
    `autoRotate`, damping, distance clamps).
  - **Removed the scroll story** — deleted `CameraRig`, `StoryChapters`,
    `story-keyframes`, `story-regions`, `use-scroll-progress`, `BrainLabels`,
    `BrainConstellations`, `lib/constellations`, and the `brain-story` mock.
    `BrainScene` now only drives the fly-in reveal + live uniforms (highlight /
    explode uniforms stay neutral; their shader code is retained, unused).
  - **New overlay** — `BrainIntro` replaces `StoryChapters`: a minimal
    left-aligned editorial title block that reveals once on load
    (`spring-text-engine`, `mode="once"`), pointer-transparent so drag/zoom reach
    the canvas. `HomeView` is now a single non-scrolling `100lvh` viewport.

## 2026-05-29

- **Looped flow, leaner cloud, finale neuron constellation** — three changes:
  - **5× fewer ambient particles** — `ambientCount` 52000 → 10400.
  - **Looped surface flow** — the brain particles' tangential drift is now a
    *full closed circle* in each point's surface tangent plane (cos/sin of a
    seed-offset phase) — they orbit on the brain's shape rather than oscillate.
  - **Neuron constellation finale** — a new `BrainConstellations` component
    (`lib/constellations.ts` builds star nodes + nearest-neighbour link lines)
    fades in as the camera dives inside at the finale (scroll 0.92→1), so the
    dispersing brain reads as a neural network. New `constellationCount` /
    `constellationColor` config; on the bloom layer so the nodes glow.
- **Living surface flow** — brain particles now continuously drift in smooth,
  seed-varied directions that are **projected onto the surface tangent plane**
  (using a baked per-particle `aNormal`), so they flow *along* the brain's shape
  and the silhouette stays readable. `sampleSurface` now also returns geometric
  normals; new `flowSpeed` / `flowAmount` config + `uFlowSpeed` / `uFlowAmount`
  uniforms.
- **Finale + focus isolation + text-load fix** — three changes:
  - **Unique finale** — the last act no longer returns to a front pull-back.
    Instead the brain **blows up** (particles fly outward along seeded radial
    dirs via a new `uExplode`/`uExplodeDist`, fading to ~20%) while the **camera
    dives inside** from the back (Act 5 keyframe `pos [0, 0.15, -0.7]`, looking
    forward). `uExplode` ramps over scroll progress 0.9→1.0 (eased in
    `BrainScene`).
  - **Focus isolation** — while a region is active, the *rest* of the brain now
    darkens toward `deepColor` (`isolateStrength` 0.88) so the highlighted zone
    clearly stands out; the opposite-side alpha fade was softened
    (`focusFadeStrength` 0.82 → 0.55) since the darkening carries the accent.
  - **Text on load** — fixed chapters whose copy looked clipped/jumpy on load:
    removed the inline flex rule-marker beside the animated eyebrow, softened the
    word-rise offsets, loosened title leading (`1.05` → `1.12`), and added
    vertical `py-24` breathing room.
- **Side-on opening framing** — Act 0 (Arrival) now starts from the **side** of
  the brain (`pos [4.3, 0.35, 1.6]`, a 3/4 angle at the same ~4.6 radius) instead
  of straight-on front, so the opening orbit sweeps from the side toward the
  front-top cortex.
- **Back-of-brain stop + orbiting camera** — added a 6th act, the **Occipital
  Lobe** on the rear of the brain (`story-regions.ts` index 4, with chapter +
  keyframe; "The Whole" is now act 5). The `CameraRig` now interpolates the
  camera position in **spherical coordinates around the brain centre** (radius +
  polar linear, azimuth along the shortest arc), so the camera **orbits around**
  the brain to reach the far side instead of dollying through it. The look-at
  target still lerps linearly.
- **Fix: scroll smoothness — decoupled camera from brain** — the
  rotate-the-brain-to-face-the-camera approach was still shaky (per-frame
  `setFromUnitVectors` reading the eased/moving camera, slerp shortest-path
  flips, index flips at act boundaries). Replaced it entirely: the **brain now
  holds a fixed orientation** and the **camera flies between viewpoints** that
  each frame a region (`frameRegion` in `story-keyframes.ts` positions the
  camera out along a region's anchor and looks at it, so the highlight still
  lands centred). Removed all camera↔brain coupling, idle spin, and pointer
  parallax from `BrainScene`; `CameraRig` easing is now frame-rate-independent
  (delta-based). Result: a smooth, deterministic flythrough.
- **Fix: scroll jitter / camera jumps** — the iteration-3 focus orientation
  slerped the brain toward the focus quaternion against a *continuously
  time-spinning* "free" quaternion, so `slerpQuaternions` periodically flipped to
  the shortest path and snapped. The idle spin is now a delta-accumulated angle
  that **slows to a stop as focus ramps in** (never blend against a moving
  target), focus strength is **eased once** and shared by the orientation +
  highlight, and `delta` is clamped. Also hardened `useScrollProgress` to ignore
  non-finite Lenis progress (avoids an occasional snap to Act 0 on resize).
- **Focus framing + accent tuning (iteration 3)** — the active region now
  orients to **face the camera** so the highlighted zone sits mid-screen
  (`BrainScene` slerps the brain's rotation toward a quaternion that points the
  region anchor at the camera, blended by the act's strength; the region-act
  camera keyframes now look at centre). The highlight reads as a **deeper green**
  (tint toward `highlightColor` + gentle glow, not a white blow-out), the side
  **opposite** the active region **fades out** on scroll (`vFar` × new
  `focusFadeStrength`) to accent the focus, and fold/crevice particles sink to a
  visible **dark green** (`deepColor` `#063d20`, was near-black). See
  [[particle-brain]].
- **Brain depth + immersive callouts (iteration 2)** — several upgrades to the
  scrollytelling:
  - **Volumetric depth** — particle count up (235k → 360k) and size down
    (0.05 → 0.03) for a finer cloud; a baked per-particle **cavity occlusion**
    (`computeOcclusion`, spatial-hash density) sinks fold/sulcus particles
    toward a near-black `deepColor`, so the brain's grooves read as depth.
  - **Region highlights + anchored labels** — each chapter highlights its brain
    region (a `uHighlightPos`/`uHighlightStrength` glow in the shader) and shows
    a leader-line callout label anchored to that point in 3D (`BrainLabels` via
    drei `Html`, inside the rotating group; spring-faded, no CSS transitions).
    Anchors live in `story-regions.ts`.
  - **5 acts** — Arrival → Cortex → Synapse → Hemispheres → The Whole (added a
    pull-back closing act; `STORY_KEYFRAMES` + chapters extended).
  - **Typography pass** — chapters restyled toward the reference (large, tight,
    Onest, green eyebrow rule, muted body); switched to `mode="always"` so copy
    **appears and disappears** with scroll, and to word fade-up (no `overflow`
    clip-mask) which fixes the earlier cropped-text bug.
  New `BrainConfig` knobs: `deepColor`, `occlusionStrength`, `occlusionRadius`,
  `highlightColor`, `highlightRadius`. See [[particle-brain]].
- **"Brain Story" scrollytelling** — the home page became a scroll-driven
  narrative: a `CameraRig` flies the camera along `STORY_KEYFRAMES` (one act per
  chapter) as a `StoryChapters` overlay scrolls past the fixed canvas, reading
  Lenis scroll progress via `useScrollProgress`. Four placeholder chapters live
  in `src/data/mocks/brain-story.ts`; copy reveals with `spring-text-engine`
  (`mode="once"`). `prefers-reduced-motion` holds the opening framing. See
  [[particle-brain]].
- **Animation engine patched (sign-off) for a green `next build`** — introduced
  a shared `DynamicTag` type in `src/types/springs.ts`; the `springs/` files now
  cast their dynamic `<Tag>` to it instead of `ElementType`, so R3F's global JSX
  augmentation no longer collapses their `children` to `never`. Also fixed a
  pre-existing callback-ref misuse in `in-view.tsx` (`inViewRef.current = node`
  → `inViewRef(node)`). `next build` now type-checks clean for the first time.
  See [[decisions-log]] ADR-0013.
- **Home page replaced with a WebGL particle brain** — the old
  `home-showcase.tsx` animation demo was removed; the home view now renders a
  full-bleed React Three Fiber scene that samples a brain GLB into a ~235k-point
  cloud with synapse flashes, a drifting ambient cloud, layered bloom, and a
  warped corner-gradient background. New deps: `three`, `@react-three/fiber`,
  `@react-three/drei`, `@types/three` (see [[tech-stack]]). New feature module
  `src/components/brain/` (canvas leaf + scene + custom composer pipeline +
  shaders + surface-sampling utils). Palette tuned to **deep bio-luminescent
  green** for both the particles and the "flame" background gradient. Model
  asset lives at `public/assets/brain/rotten-brain.glb`. Rationale and the two
  trade-offs it forced (GPU scene animation vs. the spring-only motion rule; the
  R3F global-JSX-augmentation vs. the vendored springs' `ElementType` cast) are
  in [[decisions-log]] ADR-0013.

## 2026-05-23

- **README — setup + Vercel deploy steps added** — *Getting started* expanded
  into a four-step flow (clone the template → delete bundled `.git` →
  initialise your own GitHub repo → install & run), with a macOS hint for
  revealing the hidden `.git` folder (`⇧ + ⌘ + .`). Added a *🚀 Deploy to
  Vercel* section covering the CLI flow (`vercel` / `vercel --prod`) and the
  dashboard import path, plus an `env pull` pointer to
  [[environment-variables]].
- **README rewritten to lead with the AI workflow** — root `README.md`
  reorganised so the AI usage guide is the first section: how the three
  `.claude/settings.json` hooks (`SessionStart`, `UserPromptSubmit`, `Stop`)
  enforce the vault workflow automatically, how to write a good request
  against this convention layer, and a cost-expectations note recommending
  **Claude Max (5×)** as the minimum plan (the vault-fan-out + hook
  re-injection on every turn is token-intensive by design). Technical
  *Getting started* and the existing AI-agents entry-point pointer stay
  below.

## 2026-05-22

- **Styling-placement convention added** — to stop `globals.css` accumulating
  hundreds of component-specific classes, styling now follows a strict
  placement order: one-offs are Tailwind utilities, repeated patterns become
  **React components** (not `@layer components` classes), and `@layer
  components` is reserved strictly for pseudo-elements and third-party
  overrides. `globals.css` stays bounded — `@import`, tokens, base resets only.
  No CSS Modules. Codified in [[decisions-log]] ADR-0012; [[design-system]]
  (new *Where a style goes* section) and [[component-conventions]] updated.
- **Semantic-HTML / SEO-markup convention added** — new [[html-semantics]]
  rulebook: landmarks, one `<h1>` + heading outline, native elements over
  `div`s, forms/images/ARIA, JSON-LD over microdata, a `data-*` convention, and
  passing a semantic `tag` to animation components. Codified as AGENTS.md hard
  rule #10; cross-linked from [[component-conventions]] and [[new-page]]. Fixed
  the demo (`home-showcase.tsx`) to a single `<h1>` to follow it.
- **API layer added** — a convention for reaching external services.
  `app/api/<resource>/route.ts` Route Handlers own their logic and read secret
  env vars directly (safe — route files never reach the browser). New: `zod`
  dependency; `src/env.ts` (validated env, public/server split); `src/lib/api/`
  (`handle` wrapper + `ApiError` + `{ data }`/`{ error }` envelope);
  `src/lib/api-client.ts` (typed same-origin fetch); example
  `app/api/contact/route.ts`. Codified as AGENTS.md hard rule #9. See
  [[decisions-log]] ADR-0011 and [[api-architecture]].

## 2026-05-21

- **Asset convention added** — site content assets (images, videos) now live
  under `public/assets/<section>/`, one folder per section; meta/PWA/SEO assets
  stay at the `public/` root. Documented in [[folder-structure]],
  [[component-conventions]], and the [[new-page]] playbook; `public/assets/`
  created with a `.gitkeep`.
- **SEO & performance hardening** — a broad pass on the starter. **SEO:** new
  `src/lib/site.ts` config (single source of truth, fed by `NEXT_PUBLIC_SITE_URL`);
  `metadataBase` is now always set (relative OG/canonical URLs resolve);
  `themeColor` moved to a `viewport` export; added `app/robots.ts`,
  `app/sitemap.ts`, and an `Organization`+`WebSite` JSON-LD helper; OG image
  dimensions corrected to match the asset; dead `keywords`/`other` tags dropped.
  **Performance:** populated `next.config.ts` (`removeConsole` in prod,
  AVIF/WebP, `next/image` breakpoints aligned to the grid, `poweredByHeader:
  false`); fixed a `requestAnimationFrame` leak in `ScrollLayout` (Lenis loop
  never cancelled on unmount); `HomeView` is now a Server Component with the
  animation demo split into the `HomeShowcase` client leaf; added
  `<ReducedMotion>` (honours `prefers-reduced-motion` via react-spring's global
  `skipAnimation`); removed a per-frame `console.log` from the demo; added
  `app/loading.tsx` / `error.tsx` / `not-found.tsx`. See [[decisions-log]]
  ADR-0010, [[seo-metadata]], and [[environment-variables]].
- **Animation engine — lint pass** — cleared all 13 pre-existing ESLint problems
  in the engine (2 errors + 11 warnings), an authorized engine edit (ADR-0009).
  `isMobileDisabled` now takes an optional `viewportWidth` argument, so the
  `active` memos in `<Spring>` / `<Hover>` / `<Inview>` / the trigger hooks
  depend on it genuinely. Added missing `disableOnMobile` effect deps; fixed a
  `trigger.current`-in-cleanup hazard in `<Hover>`; ref-stabilised `<Handle>`'s
  transition effects. **API change:** `useProgressTrigger` now returns `progress`
  as a `RefObject<number>` (read `.current`) instead of a render-time ref read —
  no consumer was affected (`<ProgressTrigger>` discards the return).
- **Animation engine — performance refactor** — fixed load issues that scaled
  with the number of animated components. Added `src/lib/animation/ticker.ts`, a
  single reference-counted `requestAnimationFrame` loop; `useLoop` (and all loop
  hooks) now subscribe to it instead of each starting its own rAF. `useWindowWidth`
  / `Height` / `Size` now share one debounced `resize` listener via a
  `useSyncExternalStore` store (the `debounceDelay` param was dropped — unused).
  `useDynamicInView` rewritten without the per-render `Proxy`/observer churn.
  Fixed a stale-closure bug in `useLoop`. `mode="forward"` scroll listeners made
  `passive`. This was an **authorized edit to `#do-not-modify` engine files** —
  hard rule #2 amended. See [[decisions-log]] ADR-0009 and [[animation-system]].
- **`spring-text-engine` updated** — bumped `^0.1.3` → `^0.1.5` (latest). The
  public API, types, and dependencies are unchanged between these versions
  (verified) — an internal-only patch bump, no code changes required.
- **Adaptive scaling grid added** — a root-font-size scaling system landed in
  `src/components/common/grid/` (`<AdaptiveGrid>` + `useAdaptiveGrid` hook +
  `grid.config.ts`), with `vw` media queries in `globals.css` for scale-down.
  It was dropped into `common/` as a `styled-components` system; ported to the
  project stack — config-driven TS + CSS-only Tailwind, no `styled-components`.
  The unused dropped files (`colors.ts`, `fonts.ts`, `utils.ts`, `index.ts`,
  the `styled-components` `grid.tsx`) were removed. Mounted via `<AdaptiveGrid>`
  in the root layout. See [[components/common]] and [[decisions-log]] ADR-0008.
- **Vault created** — `obsidian/` Obsidian vault initialised as the project's
  second brain. Architecture, frontend, and workflow docs populated. See [[decisions-log]] ADR-0001.
- **Root README rewritten** — replaced `create-next-app` boilerplate with a real
  project README that points into this vault.
- **`generic-layout-prompt.md` moved** — relocated from repo root to
  `obsidian/workflows/` as [[generic-layout-prompt]].
- **Navigation convention resolved** — standard `next/link` confirmed; the unbuilt
  `<AnimLink>` / `useAnimRouter()` convention dropped. See [[decisions-log]] ADR-0005.
- **Docs consolidated into the vault** — `project-specs.md` deleted (decomposed into
  vault notes + new [[environment-variables]]); `text-engine-docs.md` moved in as
  [[text-engine-reference]]. `AGENTS.md` rewritten as a thin shim; `.cursorrules`
  repointed to `@AGENTS.md`. The vault is now the single source of truth.
  See [[decisions-log]] ADR-0006.
- **Vault renamed & restructured** — vault folder `getlayers.io/` → `obsidian/`;
  number prefixes dropped from section folders (`00-meta` → `meta`, etc.). Project
  name standardised to **`next16-claude-starter`** across docs and `package.json`.
- **Components linked to docs** — every file in `src/components/` now carries a
  `// 📖 Docs:` pointer comment to its catalog note, so agents can jump from code
  to docs and back.
- **Vault workflow automated** — added `.claude/settings.json` with `SessionStart`,
  `UserPromptSubmit`, and `Stop` hooks that make agents read the vault first,
  follow the relevant guide, and update docs after every change — with no manual
  reminder. See [[decisions-log]] ADR-0007 and [[ai-agent-guide]].
- **Cookie component replaced** — the `react-cookie-consent`-based `cookie.tsx`
  was replaced by an in-house `Cookie/` component (banner + category preferences
  modal + Zustand store). `react-cookie-consent` removed from dependencies. The
  component shipped using `styled-components` + an external design system; it was
  ported to the project stack — Tailwind v4 tokens and `@react-spring/web` motion.
  Mounted via `<LazyCookie>`. See [[components/common]].
- **Fixed TextEngine spring type mismatch** — the `mode="once"` heading in
  `views/home.tsx` mixed `lineIn={{ y: 0 }}` (number) with `lineOut={{ y: "100%" }}`
  (string), throwing *"Cannot animate between _AnimatedString and _AnimatedValue"*.
  Changed to `y: "0%"`. The buggy pattern in [[text-engine]] / [[text-engine-reference]]
  examples was corrected and a type-matching gotcha note added.

## Project baseline (git history)

| Commit | Description |
|--------|-------------|
| `94b0870` | feat: update starter |
| `5280ef2` | fix: linter errors & build |
| `b2b84e6` | initial — `next16-claude-starter` scaffold |

> [!note]
> The starter shipped with: Next.js 16.2, React 19.2, Tailwind v4, `@react-spring/web`,
> `spring-text-engine`, Lenis, and Zustand. See [[tech-stack]] for the current state.
