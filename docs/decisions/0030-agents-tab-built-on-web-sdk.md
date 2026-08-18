# 0030 - Agents tab is built on the web SDK, not an iframe

- Status: accepted
- Date: 2026-08-18
- Related: `docs/SPEC-capability-doctrine.md`, `docs/PLAN-opbox-boltrig-merge-2026-08-17.md` (§2 point 003, §5 push-back 001)

## Context

The unification plan wants an Agents tab inside the Opbox product that
presents Boltrig's chat/run surface, restyled with Opbox colour tokens. The
plan's stated mechanism — wrapping the Worker UI "as a microservice" inside
Opbox — reads as an iframe embed. Three independent facts block that
mechanism:

- The Worker's nginx sends `X-Frame-Options: DENY` and CSP
  `frame-ancestors 'none'` (`apps/worker/nginx.conf`).
- Opbox's own CSP allows `frame-src 'self'` plus Calendly only
  (opbox-frontend `src/middleware/security-headers.ts`); a third-party frame
  would have to be allow-listed per deployment.
- CSS custom properties do not cross a frame boundary, so "Opbox colour
  tokens" would require a token-sync contract that exists nowhere on either
  side; the only injection path in the Worker (`applyCustomTokens`) is
  visit-scoped to the appearance page.

Meanwhile `sdks/web` already exists and states its purpose as rendering
chat/run data identically to the Worker — a first-class typed client over
kernel `/v1` (chat SSE, runs, work items, routines, budgets, artifacts).

## Decision

The Agents tab (and every Opbox-side Boltrig surface) is built Opbox-native
on the Boltrig web SDK against kernel `/v1`. No iframe anywhere in the
combined product. The existing subpath mount of the Worker console
(`X-Forwarded-Prefix`) remains as the zero-build admin/ops fallback, not as
the product face.

## Consequences

- One kernel, two first-class clients: the Worker console and Opbox-native
  views share the SDK as their common contract — no skin-sync bug class.
- Opbox components consume Opbox CSS custom properties for free; no theming
  bridge to build or test.
- SDK surface must keep pace with whatever the Agents tab needs; gaps are
  SDK work, not reasons to fall back to embedding.
- The console's own branding stays as-is (admin tool); see decision 0033 for
  the product-face styling rule.
