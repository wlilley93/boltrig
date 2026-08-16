# External harvest notes: FounderOS-DEMO (github.com/Bennettxai/FounderOS-DEMO)

Status: evaluated 2026-08-16. Clean-room notes only; no code, prompts, or assets
copied. MIT-licensed repo, so a verbatim copy would be legal, but nothing in it
earned adoption at code level. This file records the three design-level ideas
worth keeping in view and the evaluation verdict on the rest.

## Evaluated and rejected (with reasons)

- **Agent runtime** — an in-process registry with `run()`/broadcast fan-out, an
  LLM conductor router that falls back to the first agent, and read-only chat
  tools. Pre-doctrinal: no chokepoint, grants, HITL, tenancy, or audit. The
  LLM-picks-the-agent routing is exactly the shape decision 0019 waived for
  Boltrig, so it was rejected on posture, not just capability.
- **Credential handling** — a web app that resolves keys by reading canonical
  env files live and rewrites `.env.local` at runtime. This is the side door the
  kernel-only credential rule exists to forbid; recorded here as the named
  anti-pattern it is.
- **Knowledge lifecycle prose** — the README's promotion-gated memory lifecycle
  is documentation of an unbuilt product; nothing to harvest. Boltrig's
  knowledge catalogue and cognify path are already past it.
- **Workflow surface** — a seeded per-step stats dashboard, not an engine.

## Keeper 1: screen-context grounding

The demo injects a route-aware summary of what the operator is currently looking
at into the chat system prompt, so "this" and "here" resolve against the visible
screen. The properties worth copying if the console chat ever wants grounding:

- one cheap resolver per route; expensive reads only on the flagship route;
- unknown paths degrade to a plain title line; resolver failure never blocks
  the chat;
- the summary is capped (truncated) before injection.

Mapping to Boltrig: a head-side concern. It would be composed as data in the
console's prompt assembly, not an event-schema change — rendering knowledge
lives in the head, per the streaming contract.

## Keeper 2: connector status vocabulary

Every external integration in the demo reports one uniform three-state status —
`connected | not_configured | error` — plus a human-readable detail string and
optional metadata. A fake green light is never emitted. If Boltrig grows a
connections/integrations board over its adapters, this three-state-plus-detail
convention is the right surface shape: honest by construction, uniform across
adapters, and trivially renderable from `describe()`-level data.

## Keeper 3: deterministic graph layout

Their knowledge-graph view uses a pure, fully deterministic layout: a
force-directed pass seeded from a projection, then an area-uniform radial
redistribution (rank-based radii) that guarantees constant density across the
disc, plus golden-angle fallbacks for degenerate cases. No randomness anywhere,
so it is snapshot-testable and stable across reloads. If the console ever renders
a knowledge or org graph, this two-stage layout (springs decide angle and order;
ranks decide radius) is the technique to reimplement — reimplement, not copy.

## Provenance boundary

Evaluation was black-box: read the repo, record capability names and patterns,
write Boltrig-native notes. Nothing was vendored.
