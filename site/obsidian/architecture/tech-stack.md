---
tags: [architecture, stable]
updated: 2026-05-21
---

# Tech Stack

Every dependency in `package.json`, what it does, and why it is here.
Package name: `next16-claude-starter` · version `0.1.0` · private.

## Core framework

| Package | Version | Role |
|---------|---------|------|
| `next` | `16.2.0` | App Router framework. ⚠️ See warning below. |
| `react` / `react-dom` | `19.2.4` | UI runtime |
| `typescript` | `^5` | Type system — `any` is banned |

> [!warning] This is not the Next.js you may know
> `AGENTS.md` warns: APIs, conventions, and file structure may differ from older
> Next.js knowledge. Always check [[routing]] before writing routing code, and
> heed deprecation notices.

## Styling

| Package | Version | Role |
|---------|---------|------|
| `tailwindcss` | `^4` | Utility CSS — **no `tailwind.config.js`** |
| `@tailwindcss/postcss` | `^4` | PostCSS integration |

Tailwind v4 is configured entirely in `src/app/globals.css` via `@theme inline`.
See [[design-system]].

## Animation (the heart of the starter)

| Package | Version | Role |
|---------|---------|------|
| `@react-spring/web` | `^10.0.3` | Spring physics — drives **all** motion |
| `spring-text-engine` | `^0.1.5` | Scroll-aware spring text animation |

No `framer-motion`, no CSS transitions/keyframes. See [[animation-system]] and
[[text-engine]]. ADR: [[decisions-log]] ADR-0002.

## 3D / WebGL

| Package | Version | Role |
|---------|---------|------|
| `three` | `^0.171.0` | WebGL engine — geometry, shaders, post-processing |
| `@react-three/fiber` | `^9.0.0` | React renderer for `three` (declarative scene graph) |
| `@react-three/drei` | `^10.0.0` | R3F helpers — `useGLTF`, loaders, utilities |
| `@types/three` | `^0.184.1` | Type definitions for `three` (dev) |

Used by the home-page particle brain (`src/components/brain/`). Animation
*inside* the canvas runs on the R3F render loop, not `@react-spring/web` — the
spring-only rule is scoped to DOM motion. ADR: [[decisions-log]] ADR-0013.

> [!note] `@react-three/fiber` globally augments `JSX.IntrinsicElements`. The
> vendored springs' dynamic `<Tag>` renders were migrated from `ElementType` to
> a shared `DynamicTag` type (`src/types/springs.ts`) so the augmentation no
> longer collapses their `children` to `never` — `next build` is green. See
> ADR-0013.

## Scroll & state

| Package | Version | Role |
|---------|---------|------|
| `lenis` | `^1.3.19` | Smooth scrolling |
| `zustand` | `^5.0.12` | Lightweight global state (scroll store) |
| `resize-observer-polyfill` | `^1.5.1` | ResizeObserver fallback for animation hooks |
| `zod` | `^4.4.3` | Schema validation — env (`src/env.ts`) + API payloads. See [[api-architecture]] |

See [[smooth-scroll]] and [[data-flow]].

## Misc

No miscellaneous runtime dependencies. Cookie consent is an in-house component
(`src/components/common/Cookie/`) built on Zustand + `@react-spring/web` — the
former `react-cookie-consent` package was removed. See [[components/common]].

## Tooling

| Package | Role |
|---------|------|
| `eslint` `^9` + `eslint-config-next` | Linting — run `yarn lint` before commits |
| `@types/*` | Type definitions for node/react |

## Scripts

```bash
yarn dev      # next dev — local development
yarn build    # next build — production build
yarn start    # next start — serve production build
yarn lint     # eslint
```

Package manager: **Yarn** (`yarn.lock` is committed).

## Not yet in the stack

Auth, database/ORM, payments, i18n, data-fetching libraries. The original starter
spec listed these as "add as needed" placeholders. Document them here when adopted,
and add an ADR to [[decisions-log]].

## Related

[[system-overview]] · [[folder-structure]]
