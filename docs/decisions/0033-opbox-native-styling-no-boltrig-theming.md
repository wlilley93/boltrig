# 0033 - One embedded chat experience, Opbox-styled — no Boltrig theming

- Status: accepted
- Date: 2026-08-18
- Related: decision 0030, `docs/PLAN-opbox-boltrig-merge-2026-08-17.md` (§2 points 003 vs 012, §5 push-back 011)

## Context

The unification plan contains two opposite theming directions: the Agents tab
restyled with Opbox colour tokens (point 003), and "all AI side panels become
Boltrig-themed chats" (point 012). Boltrig has no theming machinery to offer
anyway: three coexisting CSS-variable generations, branding compiled into the
bundle (title/meta/BrandMark/desktop label/marketing copy hardcoded), and no
token-sync contract. A foreign-skinned pane inside a business product reads
as a bug, not as "the AI pane looks like the AI".

## Decision

In the combined product, every embedded AI surface is **one chat experience
built once, Opbox-styled** — the same SDK chat component mounted at the
existing points: the Agents tab, Spotlight's AI mode, the entity AI tab, the
dashboard widget, and the mobile route. Point 012's "Boltrig-themed" half is
dropped. No second theming system and no skin-sync test regime are built. The
Worker console keeps its own look as the admin/dev tool it is.

## Consequences

- Theming work collapses to zero: Opbox components inherit Opbox CSS custom
  properties natively.
- One chat component means one place to fix composer, receipts, approvals,
  and SSE behaviour — divergence between mounting points becomes a bug, not a
  lifestyle.
- Boltrig-only deployments are unaffected: the console remains their face.
