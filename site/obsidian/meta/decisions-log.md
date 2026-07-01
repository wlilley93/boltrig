---
tags: [meta, decision]
updated: 2026-05-22
---

# Decisions Log (ADRs)

Architecture Decision Records. Each entry captures a choice, its context, and its
consequences. Use [[templates/adr-note]] for new entries. Newest first.

---

## ADR-0017 — Scroll-driven neural narrative; camera rig replaces OrbitControls

- **Status:** Accepted
- **Date:** 2026-06-06
- **Supersedes:** ADR-0014 (static orbital brain).

**Context.** ADR-0014 made the home page a single static, orbit-controlled
viewport. The brief changed again: the brain should read like a **specimen on an
AI starship console** — it stands to one side, and *scrolling* narrates a ~5-chapter
story (camera moving around it, regions scanned, a mid-story full-screen takeover
that hides and then reveals the brain, a finale that disperses it). This is a
return to scrollytelling, rebuilt with a stronger design direction. Crucially the
focus/explode GLSL kept dormant by ADR-0014 (`uHighlightPos/Strength`, `uExplode`)
is exactly what this needs — so **no shaders changed**.

**Decision.**

- **Remove `OrbitControls`.** Deleted `brain-orbit.tsx`. A new
  `brain-camera-rig.tsx` reads scroll progress imperatively each frame and
  **damps** the camera between per-chapter keyframes (`story/story-keyframes.ts`).
  Brain "stands to the side" via a lateral `lookAt` offset. `prefers-reduced-motion`
  holds the opening framing.
- **Global story store.** `brain/story/use-story.ts` (zustand `{progress, section}`),
  fed by a render-nothing `story/story-scroll-driver.tsx` off the live Lenis
  instance. Read imperatively in the R3F loop (camera rig + `BrainScene` uniform
  sync) so scrolling never re-renders the heavy WebGL tree — the same discipline
  as `useBrainControls` (ADR-0015).
- **Drive the dormant uniforms.** `BrainScene` now pushes `sampleStory(progress)`'s
  region/highlight/explode into the already-wired uniforms — chapters scan a region,
  the finale blows the brain out.
- **DOM overlay** (`src/components/story/`): `story-overlay` stacks one full-height
  panel per chapter; `story-section` (TextEngine + a futuristic "scan frame") for
  brain chapters; `takeover` for the procedural full-screen "signal field" (a
  ticker-driven `<canvas>`, no video assets) that hides/reveals the brain;
  `story-chrome` for the persistent console frame + chapter rail. Content lives in
  `src/data/story.ts` (draft copy, editable).
- **Chrome changes.** `BrainHud` removed (folded into `story-chrome`); `BrainTelemetry`
  now tracks the active chapter; the dev parameters drawer (`BrainControls`) mounts
  only in development, with its own toggle.

**Consequences.**

- The page scrolls again (≈5×100vh); Lenis is load-bearing once more.
- All DOM motion stays spring/TextEngine-based (rule #1); only canvas-internal
  motion (camera, uniforms, the signal field) runs on the R3F/ticker loop (ADR-0013).
- `BRAIN_LAYERS` stays unused; the bloom pipeline (ADR-0016) is untouched.
- The static-view overlay (`BrainIntro`) and `brain-hud`/`brain-orbit` are gone;
  ADR-0014 remains for history.

---

## ADR-0016 — Collapse the bloom pipeline to one render + one bloom

- **Status:** Accepted
- **Date:** 2026-06-06

**Context.** `BrainRenderer` inherited the vanilla prototype's layered selective-
bloom pipeline: three `EffectComposer`s (soft bloom → strong bloom → final
composite) with the brain on a dedicated render layer and `camera.layers.set()`
rewriting the camera's layer mask between each composer every frame. That made
sense when the scrollytelling put different objects (constellations, etc.) on
different layers. After ADR-0014 removed all of that, **everything lives on one
layer** — so two of the three composers rendered *empty* layers, and the per-frame
layer-mask rewrite plus the redundant scene renders produced a visible **flicker**.

**Decision.** Collapse to a flat, temporally-stable pipeline that keeps a genuine
`UnrealBloomPass`:

1. `sceneComposer` — `RenderPass` → `GammaCorrectionShader` → one `UnrealBloomPass`
   (`strength 0.7`, `radius 0.4`, `threshold 0`). No layer switching; the camera
   sees the default layer where both `<points>` now live.
2. `finalComposer` — a single full-screen `ShaderPass` compositing the off-screen
   scene+bloom (`tScene = sceneComposer.readBuffer.texture`) over the warped
   corner-gradient background.

`FINAL_FRAGMENT` was simplified from four sampled textures
(`torusTexture`/`bloomTexture`/`tDiffuse`/`haloTexture`) to a single `tScene`.
The per-points layer assignment in `BrainScene` was removed; `BRAIN_LAYERS` in
`config.ts` is now unused (kept for reference).

**Consequences.**

- Flicker gone; one scene render + one bloom per frame instead of three scene
  renders + two blooms + three layer-mask writes (also cheaper).
- `threshold 0` is deliberate — a non-zero bloom threshold reintroduces flicker as
  moving particles cross the brightness cutoff.
- Selective per-layer bloom is no longer available; if a future effect needs some
  objects to bloom differently, reintroduce a layer + dedicated composer (the
  `BRAIN_LAYERS` scaffold is still there). Amends the render-pipeline portion of
  ADR-0013.

---

## ADR-0015 — Live scene controls via a store-driven uniform sync

- **Status:** Accepted
- **Date:** 2026-06-06

**Context.** The static orbital brain (ADR-0014) needed a real-time control
surface — edit every colour, size, count, and motion knob live — plus an
immersive loader and richer HUD. Two constraints shaped the design:

1. Re-rendering the WebGL tree (or rebuilding the ~360k-point geometry / the
   three-composer pipeline) on every slider tick would stutter badly.
2. The React-Compiler `react-hooks/immutability` lint rule (the `yarn lint`
   gate) forbids mutating a ref's value in `useFrame` if that same ref is also
   read in a `useEffect` — so the "subscribe in an effect, push into material
   uniforms" pattern is disallowed.

**Decision.**

- **`useBrainControls` zustand store** holds a live `config` (mirrors
  `BRAIN_CONFIG`) + camera params + panel state. The control panel mutates it.
- **Imperative uniform sync inside the render loop.** `BrainScene` /
  `BrainRenderer` read `useBrainControls.getState().config` each frame and push
  colour/size/motion values into the shader uniforms only when the config object
  identity changed (cheap guard). Keeping the write in `useFrame` makes it the
  *sole* writer of the material refs — satisfying the immutability rule (the
  effect-based variant was tried first and rejected by lint).
- **Geometry params re-render by selector.** `useBrainResources` subscribes to
  `surfaceCount` / `ambientCount` / `occlusionRadius` so the memoised geometry
  rebuilds when they change; the panel commits those sliders on release (a draft
  value during drag) so re-sampling fires once, not per step. Uniform objects are
  built **once** from `BRAIN_CONFIG` defaults.
- **`serializeBrainConfig`** renders the live values back to the `BRAIN_CONFIG`
  source literal for a copy-paste "bake it in" workflow in the panel.
- **Loader / HUD / telemetry** are DOM chrome: all *motion* is `@react-spring/web`
  (breathing rings, blinking cursor, reveals — rule #1); the telemetry's
  streaming *data* updates on `setInterval` timers in effects, seeded with static
  values so SSR and the first client render match (no hydration drift).
- **New design tokens** (`--brain-void/-deep/-azure/-sky`) keep DOM chrome
  colour-matched to the scene without raw hex in class names (rule #4).

**Consequences.**

- Dragging colour/size/motion sliders never re-renders or rebuilds the scene —
  only the per-frame identity guard flips. Count sliders accept a one-off
  re-sample on release.
- The store is the single source of truth for the live look; `BRAIN_CONFIG`
  remains the *default* seed (and the copy target).
- Adds a small client surface (panel + HUD + loader + telemetry) over the canvas;
  all pointer-transparent except the toggle/panel, so orbit still works anywhere.

---

## ADR-0014 — Static orbital brain over scrollytelling

- **Status:** Accepted
- **Date:** 2026-06-05

**Context.** The home page shipped as a scroll-driven "Brain Story": a fixed
canvas behind a stack of full-height `StoryChapters`, with `CameraRig`
interpolating `STORY_KEYFRAMES` from Lenis scroll progress, per-region highlight
/ focus-isolation, anatomical `BrainLabels`, and a finale blow-up +
`BrainConstellations`. The brief changed: a **single, elegant, user-controlled**
view — deep blue, no narrative, viewer free to rotate.

**Decision.**

- **Replace scroll camera with `OrbitControls`** (drei) in `BrainCanvas`:
  `makeDefault`, `enablePan={false}`, damping, distance clamps, and a gentle idle
  `autoRotate`. The viewer drives the camera; the brain keeps its fixed
  orientation (so the decoupling ADR-0013 relied on still holds).
- **Remove the scroll narrative entirely.** Deleted `CameraRig`,
  `StoryChapters`, `story-keyframes`, `story-regions`, `use-scroll-progress`,
  `BrainLabels`, `BrainConstellations`, `lib/constellations`, and the
  `brain-story` mock. `BrainScene` keeps only the fly-in reveal and live uniforms
  (time/resolution/alpha); the highlight + explode shader uniforms remain wired
  but stay at their neutral `0` defaults.
- **Single overlay.** `BrainIntro` (a `spring-text-engine` `mode="once"` reveal,
  pointer-transparent) replaces the chapter stack; `HomeView` is a single
  non-scrolling `100lvh` viewport.
- **Deep blue palette.** `BRAIN_CONFIG` retuned green → blue (scene content, not
  design tokens — unchanged from ADR-0013's reasoning).

**Consequences.**

- The page no longer scrolls; Lenis (`ScrollLayout`) stays mounted but is inert
  on a one-viewport page — left in place to avoid touching the root layout.
- Highlight/explode/focus GLSL is retained but dormant — kept so the effect can
  be re-driven later (e.g. hover/click focus) without re-porting shaders.
- Supersedes the scrollytelling described in earlier ADR-0013 notes and the
  2026-05-29 changelog entries; those remain for history.

---

## ADR-0013 — React Three Fiber for the particle-brain home page

- **Status:** Accepted
- **Date:** 2026-05-29

**Context.** The home page needed to render a heavy WebGL scene — a brain GLB
sampled into a ~235k-point cloud with custom GLSL shaders, layered
`UnrealBloom`, and a warped fullscreen background — ported from a vanilla
`three` prototype (`scenes/brain-particles.html`). Two project constraints
collided with this:

1. The hard rule "all motion is spring-based via `@react-spring/web`"
   (ADR-0002) was written for **DOM/UI** motion. A particle system's per-frame
   animation (breathing, synapse pulses, fly-in reveal, pointer parallax) lives
   on the GPU render loop and cannot be expressed as CSS/spring transitions.
2. `@react-three/fiber` v9 ships a **global** JSX augmentation
   (`declare module 'react' { namespace JSX { interface IntrinsicElements
   extends ThreeElements } }`). `ThreeToJSXElements` maps THREE's
   non-constructor exports to `never`-typed pseudo-elements, which the vendored
   springs' `animated[tag] as ElementType` cast then intersects to
   `children: never`.

**Decision.**

- Adopt `three` + `@react-three/fiber` + `@react-three/drei` for 3D/WebGL work.
  The brain lives in a self-contained feature module, `src/components/brain/`
  (canvas leaf, scene, an imperative three-composer `BrainRenderer` that takes
  over the render loop via a positive-priority `useFrame`, shader sources, and
  surface-sampling utils). `useGLTF` (drei) loads the model under `<Suspense>`.
- **Scope the spring-only rule to DOM motion.** Animation *inside* a WebGL
  canvas (shader uniforms, camera, object transforms) is driven on the R3F
  render loop. `@react-spring/web` still governs every DOM/UI transition. No CSS
  transitions/keyframes were added.
- Mutate three objects per-frame **through component/`useRef` refs**, never by
  mutating a hook's memoised return — the React-Compiler `react-hooks`
  immutability rule (the `yarn lint` gate) forbids the latter.
- Brain *config* (colours, counts, speeds) is a typed `BRAIN_CONFIG` object fed
  to shader uniforms — it is scene content, not CSS styling, so it does not go
  through `globals.css` design tokens (ADR-0004 unaffected).

**Consequences.**

- `yarn lint` — the project's enforced gate (hard rule #7) — stays green.
- **The animation engine was patched (with sign-off)** to make `next build`'s
  TypeScript pass — green for the first time in the repo:
  - A shared `DynamicTag` type (`src/types/springs.ts`, *not* protected)
    replaces the `as ElementType` / `as React.ElementType` casts in
    `animated-var-text-tag`, `hover`, `spring`, `spring-trigger`, and
    `progress-trigger`. It pins the dynamic `<Tag>` to a single element's prop
    shape (`HTMLAttributes<HTMLElement> & { children?; ref? }`), so R3F's
    `never`-typed pseudo-elements in the global `JSX.IntrinsicElements` no
    longer collapse `children` to `never`.
  - The **pre-existing** `inViewRef.current = node` in `in-view.tsx` (a
    callback ref mis-used as an object ref) is now `inViewRef(node)`.
  - These are the only edits ever made to the `#do-not-modify` engine besides
    ADR-0009; future R3F-vs-springs type drift should reuse `DynamicTag`.
- New 3D work should follow this module's shape; document new components in the
  catalog and keep the spring-only rule for DOM motion. Deep-green palette is a
  content choice in `BRAIN_CONFIG`, not a token.

## Related

[[decisions-log]] · [[tech-stack]] · [[component-conventions]] · [[animation-system]]

---

## ADR-0012 — Styling lives in utilities and components, not `globals.css`

- **Status:** Accepted
- **Date:** 2026-05-22

**Context.** ADR-0004 made design tokens the styling currency and ruled that
"new values must be added to `globals.css` first." Combined with the
design-system guidance to *"extract repeated multi-class patterns to
`@layer components`"*, the path of least resistance for any repeated visual
pattern became a named class in `globals.css`. On an animation-heavy,
multi-section marketing site that grows the file without bound — a single
global stylesheet accumulating hundreds of component-specific classes that are
never deleted when their component is. The fix is a placement rule, not a
file-splitting trick: splitting `globals.css` into many files only spreads the
same bloat.

**Decision.** Styling follows a strict placement order; `globals.css` stays
bounded by design.

- One-off styling → **Tailwind utilities** in `className`. Nothing enters CSS.
- A repeated pattern with markup/structure/props → a **React component**
  (`components/ui/`), *not* a CSS class. This is the default answer to "this
  looks repeated" — e.g. an eyebrow label with a `::before` dot is an
  `<Eyebrow>` component, not a `.label-eyebrow` class.
- A repeated pure-utility combo with no structure → a Tailwind v4 `@utility`.
- `@layer components` is reserved **strictly** for what utilities and
  components genuinely cannot express: pseudo-elements (`::before`/`::after`),
  third-party DOM overrides (`!important` on library markup), complex
  descendant/state selectors.
- `globals.css` only ever holds: `@import`, tokens (`:root` + `@theme`), base
  element resets (`@layer base`), and the narrow `@layer components`
  exceptions above. If it grows past that, something was misplaced.
- CSS Modules were considered and **rejected** — a second styling mechanism
  for the rare bespoke-CSS case is not worth the extra mental model when
  motion is spring-based (no keyframes — ADR-0002) and utilities + components
  cover everything else.

**Consequences.** `globals.css` stays a few-hundred-line file indefinitely.
"Repeated thing" pressure now pushes toward React components — which the
project wants anyway. This **amends ADR-0004**: design *tokens* still go in
`globals.css` first, but component-specific *classes* no longer do.
[[design-system]] and [[component-conventions]] updated to match.

---

## ADR-0011 — API layer: `app/api` route handlers, secrets server-side

- **Status:** Accepted
- **Date:** 2026-05-22

**Context.** The starter had no API layer. It needs a convention for reaching
external services that keeps secret keys off the client and gives endpoints a
consistent shape.

**Decision.** External calls go through Next.js Route Handlers —
`src/app/api/<resource>/route.ts`:
- **The handler owns the work** — business logic, multiple upstream calls,
  filtering, and reading secret env vars all live in `route.ts`. No mandatory
  passthrough service layer; extract shared code only when genuinely reused.
- Secrets are safe in handlers because `route.ts` is never bundled to the
  browser. Secret env vars are **unprefixed**; `NEXT_PUBLIC_` only for
  browser-safe values.
- Every endpoint: validates input with `zod`, returns the `{ data }` /
  `{ error }` envelope via the shared `handle()` wrapper (`src/lib/api/`), runs
  on the Node runtime (not Edge).
- `src/env.ts` validates env with zod — `publicEnv` vs `getServerEnv()`.
- Client Components fetch via `apiFetch` (`src/lib/api-client.ts`), same-origin
  only. Render-time data is read in Server Components.
- Added `zod`. The example endpoint is `app/api/contact/route.ts`.
- Codified as **AGENTS.md hard rule #9**.

**Consequences.** A clear, secret-safe API convention (full note:
[[api-architecture]]). Server Actions were considered for mutations but
deferred — for now everything goes through `app/api`. The choice can be
revisited if forms need progressive enhancement. First server dependency
(`zod`) and first server-only env var (`CONTACT_ENDPOINT`) now exist.

---

## ADR-0010 — SEO & performance hardening

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** A review found gaps that would hurt a production marketing site:
`metadataBase` defaulted to `null` (relative OG/canonical URLs never resolved to
absolute — broken social previews); `themeColor` sat on the deprecated metadata
field; there was no `robots.txt`, `sitemap.xml`, or structured data; the
`next.config.ts` was empty; `ScrollLayout` leaked a `requestAnimationFrame`
loop; the home view was a top-level `"use client"` (violating hard rule #6);
and the animation-heavy starter ignored `prefers-reduced-motion`.

**Decision.**
- **Site config.** `src/lib/site.ts` (`siteConfig`) is the single source of
  truth for SEO, fed by `NEXT_PUBLIC_SITE_URL` (fallback `http://localhost:3000`).
- **Metadata.** `metadataBase` is always set; `themeColor` moved to a
  `generateViewport()` / `viewport` export; dead `keywords` / `other` tags
  dropped; OG dimensions corrected to match the asset.
- **Crawlability.** Added `app/robots.ts`, `app/sitemap.ts`, and a JSON-LD
  `Organization`+`WebSite` helper rendered once in the root layout.
- **App Router files.** Added `loading.tsx` (enables streaming), `error.tsx`,
  `not-found.tsx`.
- **Rendering.** `HomeView` is a Server Component; client-only animation moved
  to the `HomeShowcase` leaf — models hard rule #6 instead of breaking it.
- **Reduced motion.** `<ReducedMotion>` calls react-spring's `useReducedMotion`,
  toggling the global `skipAnimation` — one app-root mount covers every spring
  and `spring-text-engine`. Chosen over per-component handling for its reach.
- **Build config.** `next.config.ts` now sets `removeConsole` (prod),
  AVIF/WebP, `next/image` breakpoints aligned to the adaptive-grid widths, and
  `poweredByHeader: false`. React Compiler is left as a documented opt-in (needs
  `babel-plugin-react-compiler`).
- Fixed the `ScrollLayout` Lenis rAF leak (cancel on unmount).

**Consequences.** Social/SEO metadata is correct in production once
`NEXT_PUBLIC_SITE_URL` is set. The first project env var now exists (see
[[environment-variables]]). `isBot()` stays available but is discouraged — it
opts routes out of static rendering; reduced-motion is the preferred lever (see
[[seo-metadata]]). React Compiler remains opt-in pending a dependency install.

---

## ADR-0009 — Shared animation ticker; authorized engine performance refactor

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** A performance review of the animation engine found load issues that
scale with the number of animated components on a page:
- `useLoop` started a **private `requestAnimationFrame` loop per hook instance** —
  N scroll-driven components meant N rAF loops, none of which ever stopped.
- `useWindowWidth` attached a **separate debounced `resize` listener per call** —
  one per spring component.
- `useDynamicInView` re-created its `IntersectionObserver` **on every render**
  (effect keyed on an unstable `options` object), and a dead `Proxy` branch
  created observers that were never disconnected.
- `useLoop`'s mount-only effect captured a **stale `onRender`**, so prop changes
  after mount were ignored.
All of this lives under `src/hooks/animation/` and `src/components/animation/springs/`
— `#do-not-modify` (ADR-0002).

**Decision.** With explicit user sign-off, apply a one-time performance refactor
to the protected engine, and introduce a shared, unprotected loop primitive:
- New `src/lib/animation/ticker.ts` — a single app-wide, reference-counted rAF
  loop (`subscribeToTicker`). It starts on the first subscriber, stops on the
  last, and throttles each subscriber independently. **Not** `#do-not-modify` —
  it is the supported extension point.
- `useLoop` now subscribes to the ticker and reads `onRender` / `framerate`
  through refs (fixes the stale-closure bug). Public signature unchanged.
- `useDynamicInView` rewritten without the `Proxy`: one observer, re-created only
  when the observed element or options actually change; exposes a callback ref.
- `use-window-size.ts` (not protected) now serves all three hooks from one
  debounced `resize` listener via `useSyncExternalStore`. The unused
  `debounceDelay` parameter was dropped.
- `mode="forward"` `scroll` listeners in `<Spring>` / `<Inview>` made `passive`.
- Hard rule #2 amended: the engine stays protected by default; changes require
  explicit sign-off.

**Consequences.** A page with N animated components now runs **one** rAF loop and
**one** resize listener instead of N of each, with no observer churn. Public
hook/component APIs are unchanged except `useWindowWidth`/`Height`/`Size`, which
no longer take a `debounceDelay` argument (no caller passed one). This **amends
ADR-0002's** do-not-modify scope.

A follow-up pass then cleared all 13 pre-existing ESLint problems in the engine
(also authorized): `isMobileDisabled` gained an optional `viewportWidth`
argument, missing `disableOnMobile` effect deps were added, a
`trigger.current`-in-cleanup hazard in `<Hover>` was fixed, `<Handle>`'s
transition effects were ref-stabilised, and `useProgressTrigger` now returns
`progress` as a `RefObject<number>` (no consumer affected).

---

## ADR-0008 — Adaptive scaling grid via root font-size

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** An adaptive scaling system was dropped into `src/components/common/`
to keep a rem-based design proportional across viewports. It shipped as a
`styled-components` implementation (`createGlobalStyle`, a `css` `media` helper,
`rm`/`em` helpers, plus `colors.ts` / `fonts.ts` / `utils.ts`). `styled-components`
is not a project dependency, and global CSS belongs in `globals.css` per ADR-0004.

**Decision.** Keep only the scaling behaviour; rebuild it to the project stack.
- **Scale down** (viewport ≤ largest breakpoint) — `vw`-based `html { font-size }`
  media queries in `globals.css`, inside `@layer base`.
- **Scale up** (viewport > largest breakpoint) — a `<AdaptiveGrid>` client
  component (`useAdaptiveGrid` hook) sets an inline `html` font-size at runtime,
  reusing the existing `useResizeLoop` render loop.
- Breakpoints live in `grid.config.ts` as typed config; the `globals.css` media
  queries mirror them and must be kept in sync (formula in both files).
- The dropped `styled-components` files were deleted, not committed.

**Consequences.** A rem-based layout now scales as one unit on every viewport.
`styled-components` stays out of the dependency tree. The breakpoint set is
duplicated across `grid.config.ts` and `globals.css` by design — the CSS-only
config rule (ADR-0004) forbids generating the media queries from JS.

---

## ADR-0007 — Automate the vault workflow with Claude Code hooks

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** The "read the vault first, follow the relevant guide, update the docs
after every change" workflow depended on the user reminding the agent each time.
Documentation drifts the moment it relies on memory.

**Decision.** Encode the workflow as Claude Code hooks in `.claude/settings.json`
(committed, team-wide):
- `SessionStart` — injects a pointer to read the vault first.
- `UserPromptSubmit` — on every request, reminds the agent to consult the relevant
  guide and to update docs for any change made.
- `Stop` — at the end of every turn, blocks **once** to confirm the vault was
  updated. A `${TMPDIR}` marker keyed by session id guarantees it blocks at most
  once per turn (no infinite loop).

**Consequences.** The documentation workflow is enforced without user prompting.
`.claude/settings.json` is now a tracked project file. Hooks are reviewable and
disableable via `/hooks`. New hooks take effect on the next session start (or after
opening `/hooks`). See [[ai-agent-guide]].

---

## ADR-0006 — The vault is the single source of truth

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** ADR-0001 left dense spec files (`project-specs.md`, `text-engine-docs.md`)
at the repo root alongside the vault, creating duplication — the same conventions
existed both as terse specs and as expanded vault notes, which would drift.

**Decision.** The vault is the **only** documentation source.
- `project-specs.md` — deleted; its content was already decomposed into the
  `architecture/` and `frontend/` notes (and `environment-variables.md`).
- `text-engine-docs.md` — moved into the vault as [[text-engine-reference]].
- `generic-layout-prompt.md` — moved into the vault (see ADR via [[changelog]]).
- Root keeps only thin shims: `AGENTS.md` carries the breaking-change warning and
  hard rules and points into the vault; `CLAUDE.md` and `.cursorrules` both
  `@`-import `AGENTS.md`.

**Consequences.** No documentation duplication. Agents bootstrap from `AGENTS.md`
and read vault notes on demand. This **amends ADR-0001** — root files no longer
hold canonical spec content.

---

## ADR-0005 — Use standard `next/link` for navigation

- **Status:** Accepted
- **Date:** 2026-05-21

**Context.** Two conflicting conventions existed: `project-specs.md` specified
standard `next/link` / `useRouter`, while `generic-layout-prompt.md` specified
custom `<AnimLink>` / `useAnimRouter()` wrappers. The custom wrappers were never
built.

**Decision.** Use standard Next.js navigation — `<Link>` from `next/link` and
`useRouter` from `next/navigation`. The `AnimLink` / `useAnimRouter` convention is
dropped. See [[routing]].

**Consequences.** `generic-layout-prompt.md` §5 updated to match. No animated-route-
transition layer exists; if one is needed later, revisit with a new ADR.

---

## ADR-0001 — Adopt an Obsidian vault as the project brain

- **Status:** Accepted — amended by ADR-0006
- **Date:** 2026-05-21

**Context.** Project knowledge was scattered across root markdown files
(`project-specs.md`, `text-engine-docs.md`, `AGENTS.md`). New contributors and AI
agents had no structured map of the system.

**Decision.** Introduce `obsidian/` as an Obsidian vault — a linked, navigable
second brain. Root spec files remain as machine-read sources; the vault expands on
them. See [[ai-agent-guide]].

**Consequences.** Docs must now be maintained alongside code. The vault is the
canonical place to *understand* the project; root files stay canonical for *tooling*.

---

## ADR-0002 — All motion is spring-based (`@react-spring/web`)

- **Status:** Accepted (inherited from starter)
- **Date:** Project baseline

**Context.** Marketing sites need rich, interruptible, physically natural motion.
CSS transitions and keyframes are rigid; competing libraries add weight.

**Decision.** Use `@react-spring/web` for every animation. A custom component layer
(`src/components/animation/springs/`) wraps it. CSS transitions, CSS keyframes, and
`framer-motion` are **banned**.

**Consequences.** All animation goes through the [[animation-system]]. The springs
folder is `#do-not-modify`. Text animation is delegated to [[text-engine]].

---

## ADR-0003 — Routes delegate to Views

- **Status:** Accepted (inherited from starter)
- **Date:** Project baseline

**Context.** Mixing routing concerns with page UI makes `app/` files heavy and hard
to test.

**Decision.** `app/**/page.tsx` files only import and render a component from
`src/views/`. All layout/UI logic lives in the view. See [[routing]].

**Consequences.** Every route is a 3-line file. Views are the real page components.

---

## ADR-0004 — Tailwind v4 with CSS-based config

- **Status:** Accepted (inherited from starter)
- **Date:** Project baseline

**Context.** Tailwind v4 removes `tailwind.config.js` in favour of CSS-native config.

**Decision.** All theme tokens live in `globals.css` under `:root` and `@theme inline`.
No JS config file. Raw values in class names are banned. See [[design-system]].

**Consequences.** Design tokens are the only styling currency. New values must be
added to `globals.css` first.
