---
tags: [frontend, scroll, animation, wip]
updated: 2026-06-06
---

# Story Sections — the scroll narrative

The home page is a **scroll-driven neural narrative**: a fixed particle brain
([[particle-brain]]) behind an animated DOM overlay of **8 chapters**. Decision +
rationale: [[decisions-log]] ADR-0017 (supersedes the static view, ADR-0014).
The whole thing reads like an AI starship console scanning a specimen.

Chapters (7; each index lines up with a `STORY_KEYFRAMES` entry — keep them in
lockstep): **Arrival → Cortex → Signals (takeover) → Network (temporal) → Vision
(occipital) → Balance (cerebellum) → The Whole (finale)**. Chapters 2 and 4–6 drive
the region-highlight uniforms (the scan moves across the surface as the camera
orbits); the finale keeps sweeping the orbit (no pull-back to the front) while it
ramps `explode` to 1 and blows the brain outward, with the centred CTA over the
dispersed field.

Type is **General Sans** throughout (the brand font — both `--font-sans` and
`--font-mono` resolve to it, see [[design-system]]). The chrome is styled like a
**console terminal** (in the blue palette, not green): a `>` prompt + blinking `_`
cursor, `SCREAMING_SNAKE` kickers, wide letter-spacing/uppercase, and a `[ BRACKETED ]`
CTA. Brain chapters render plain terminal-styled text (kicker + headline + body +
`▸ KEY  VALUE` rows). Only the **black-background takeover chapter** uses the
`<TerminalPanel>` — a dark `NAME.LOG` window (titlebar + LIVE light, `>`-prompted body,
`▸ KEY … VALUE` rows), enlarged to ~half-screen width there. Helpers (`term()`,
`<TerminalCursor>`, `<TerminalPanel>`) live in `story/terminal.tsx`. The finale chapter
sets `align: "center"` (fully centred) + a `cta`; the button scrolls to the top via
`scrollTo`.

## Mental model

```
HomeView (server)
├── fixed BrainCanvas (z-0)          ← the brain; camera flown by BrainCameraRig
├── BrainTelemetry (fixed top bar)   ← full-width console status line, tracks active chapter
└── StoryOverlay (client)
    ├── StoryScrollDriver            ← Lenis progress → useStory (render-nothing)
    ├── TakeoverVisual (fixed, z-10) ← procedural signal field; hides/reveals brain
    ├── StoryChrome (fixed, z-30)    ← bottom-centre chapter progress rail (mount-gated on content-ready)
    └── z-20 scroll stack            ← one full-height panel per chapter (scroll length; always mounted, reveal = opacity+translateY fade, no remount)
        ├── StorySection  (brain chapters)
        └── TakeoverPanel (the takeover chapter — minimal centred copy)
```

## State — one scroll value, read two ways

`src/components/brain/story/use-story.ts` (zustand) holds `{ progress: 0→1,
section, entered }` (`entered` gates the brain's fly-in entrance — set by the
loader on hand-off). `StoryScrollDriver` subscribes to the live Lenis instance
([[smooth-scroll]]) and writes both.

> [!note] Content arrives a beat after the loader
> `StoryOverlay`'s `useContentReady()` delays the **copy + chrome** until `entered`
> **+ `CONTENT_DELAY_MS` (500 ms)**, so they reveal a moment after the brain's
> fly-in begins rather than animating in unseen behind the loader curtain.
>
> **The scroll stack stays mounted from first paint** for two reasons: (a) it
> carries the page's scroll length — if it mounted late, `StoryScrollDriver` would
> seed `progress` from a zero-height document (top == bottom → reads as the *end*)
> and the scene would snap straight to the finale on load; and (b) all the heavy
> mounting (every `TextEngine`, its text splitting/measuring) then happens **behind
> the loader curtain**, not at reveal time. The reveal is therefore a **cheap
> opacity + translateY fade with no remount** on the `z-20` wrapper — so it can't
> stall the frame while the brain is flying in. (A keyed remount was tried for a
> "fresh" staggered reveal; rebuilding the whole stack at reveal time was a visible
> lag spike, so it was dropped.) The chrome (fixed, no scroll length) is mount-gated.

- **Canvas reads it imperatively** — `BrainCameraRig` and `BrainScene` call
  `useStory.getState().progress` inside `useFrame`, so scrolling never re-renders
  the heavy WebGL tree (same discipline as `useBrainControls`, [[particle-brain]]).
- **DOM chrome subscribes by selector** — telemetry focus, the chapter rail, and
  the takeover fade subscribe to `section` (changes rarely), not `progress`.

## Camera + focus — `story-keyframes.ts`

One `StoryKeyframe` per chapter: camera `{position, target}`, a brain-local
`region` anchor, and `highlight` / `explode` amounts. `sampleStory(progress, dst)`
interpolates between adjacent frames into a reused object (no per-frame GC).

- `BrainCameraRig` damps the camera toward the sampled framing (frame-rate
  independent) — discrete keyframes become one continuous flythrough. "Brain to
  the side" = a lateral `target` offset. Holds keyframe 0 under
  `prefers-reduced-motion`.
- `BrainScene` copies the sample's `region`/`highlight`/`explode` into the
  shader uniforms that ADR-0014 left dormant (`uHighlightPos`, `uHighlightStrength`,
  `uExplode`) — **no shaders were changed** to build this.

## Overlay components — `src/components/story/`

| File | Role |
|------|------|
| `story-overlay.tsx` | Assembles the scroll stack + mounts driver/chrome/takeover; `useContentReady()` delays the copy/chrome *reveal* to ~500 ms after the loader hands off (stack stays mounted for scroll length) |
| `story-section.tsx` | One brain chapter: `>` kicker + headline + plain body + `▸ KEY  VALUE` rows (no panel). Copy alternates sides; `align: "center"` + optional `cta` for the finale |
| `takeover.tsx` | `TakeoverVisual` (fixed, ticker-driven `<canvas>` signal field that fades over the brain) + `TakeoverPanel` (centred copy + a large ~half-width `<TerminalPanel>`) |
| `story-chrome.tsx` | Just the **bottom-centre** chapter progress rail (corner brackets, scroll hint + brand label all removed — top edge is framed by the telemetry bar; project name is in the document `<title>`) |
| `story-scroll-driver.tsx` | Render-nothing; Lenis progress → `useStory` |
| `terminal.tsx` | Shared terminal helpers: `term()` (→ `SCREAMING_SNAKE`), `<TerminalCursor>` (blinking `_`), and `<TerminalPanel>` (the dark `NAME.LOG` window — used only by the takeover chapter) |

Content lives in `src/data/story.ts` (`STORY_SECTIONS`, indexed to the keyframes).
The shipped copy is **draft placeholder** — replace `eyebrow`/`title`/`body`; keep
`id`/`kind`/order stable so the camera keyframes stay aligned.

## Conventions

- **DOM motion is spring/TextEngine only** ([[animation-system]], [[text-engine]],
  rule #1). The takeover's `<canvas>` field animates on the shared **ticker**
  (`src/lib/animation/ticker.ts`) — a canvas-internal loop, allowed like the brain
  (ADR-0013), only running while the chapter is on screen.
- **No video assets** — the "takeover" is a procedural signal field (drifting
  nodes + links), not a real video.
- **Dev-only controls** — the `BrainControls` parameters drawer mounts only in
  development (`HomeView`); it has no on-screen toggle (open/close with **Shift+P**).
- Tokens for style (`--brain-*` in `globals.css`), props/data for content.

## Related

[[particle-brain]] · [[decisions-log]] · [[smooth-scroll]] · [[animation-system]] · [[text-engine]]
