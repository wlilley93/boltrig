---
tags: [frontend, components, content]
updated: 2026-07-21
---

# Features Section

`src/components/features/features-section.tsx` (exported via
`src/components/features/index.ts`); content in `src/data/features.ts`.

The post-story **feature catalogue**: six themed groups (operational outcomes,
control, evidence, experience, extension, and deployment), each with a one-line
hook and exactly five capability rows written as buyer outcomes. Mounted in
[[../routing|HomeView]] after `StoryOverlay`, in normal document flow.

Key points:

- **Content is data**: `FEATURE_GROUPS` in `src/data/features.ts` is pure typed
  content (`FeatureGroup` / `FeatureItem`), no markup. Edit copy there.
- **Stacking**: the section is `relative z-10 bg-black`, so it fully occludes
  the fixed brain canvas (`z-0`) once the user scrolls past the finale. The
  fixed chrome (telemetry, chapter rail, `z-30`) still floats above it.
- **Scroll mapping**: appending flow content after the story is safe because
  `StoryScrollDriver` normalises progress over the story's own extent
  (`(sectionCount - 1)` viewports), not the whole document. See
  [[../story-sections]].
- **Semantics**: `section[aria-labelledby]` + one `h2`, `h3` per group,
  `ul`/`li` rows, real `a` for the console CTA.
- **Motion**: Server Component; the only client leaves are `<Inview mode="once">`
  reveals (header + each group card), spring-based per rule #1. Everything else
  is static.
- **Style**: console look reused from the story chrome: `>` prompt kicker,
  `SCREAMING_SNAKE`-style labels, `▸` row markers, hairline `border-white/10`
  frames, `brain-sky` accents on a black field. Tokens only, no raw hex/px.

## Claim boundaries

The catalogue was re-audited against the engine on 2026-07-21. Copy must describe
shipped behavior, not a parsed policy field or integration seam. In particular:

- workflow cron specifications are persisted, but automatic cron execution is not wired;
- budget hard stops currently cover spawned agent work at organisation and department scope;
- a manual memory fact can omit its source reference;
- Knowledge currently accepts text, Markdown, and PDF originals; multimodal and
  structured formats remain later phases;
- Cognee is bundled and enabled as the only shipped rebuildable compiler;
- socket channel delivery without an outbound URL remains a queue seam; and
- generic MQ, OCR, and file-share drivers remain seams.

`src/data/features.test.ts` protects the six-by-five structure, unique names,
newly shipped agent-profile/evaluation entries, and the known seam wording.
