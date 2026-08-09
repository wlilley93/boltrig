# 0024 - Attachment: the slow bond, expression-only

- Status: accepted (owner-instructed, 2026-08-09)
- Date: 2026-08-09
- Varies: 0013 (emotion addon) - one deliberate, bounded variation
- Bound by: EMO-6 (`tests/invariants.yaml`)

## Context

The emotion engine (0013) carries genuinely relational vocabulary - connection,
warmth, tenderness; social and recognition needs; appraisals keyed to the
user's own acts (`user_message`, `praise`, `poke`, `hitl_pause`). But every
part of that state decays on an hours-scale half-life: a thousand warm
interactions leave the same resting state as none. The fast layer feels the
moment and forgets the bond. Meanwhile sleep distillation (0023) gave the
system its slow dispositional layer (weights shaped by the owner's judgments)
and memory carries the explicit layer. The relational stack was three layers
with the middle one amnesiac.

## Decision

- **Attachment is a new slow scalar in the emotion engine** (0..1, default 0):
  it accumulates in small increments from relational appraisals (data in
  `appraisals.yaml` - an optional `attachment:` delta per kind, scaled by
  intensity like every other delta) and decays in **REAL time** with a
  configured half-life measured in DAYS (`model.yaml`), never tempo-scaled -
  the tension precedent, at the opposite end of the clock. Hundreds of warm
  interactions build it; weeks of absence slowly let it fade. It is a number,
  keyed to nothing and nobody by name (EMO-2 intact).

- **Attachment lifts expression baselines only.** Its single effect inside the
  engine: the effective baselines that connection/warmth/tenderness decay
  TOWARD rise with attachment (per-emotion lift weights, data in
  `model.yaml`). A bonded engine rests warmer; an unbonded one is exactly the
  0013 engine. It also appears as a tenth phenotype scalar so expression
  surfaces (the orb today; voice tone and UI presence when they arrive) can
  carry it.

- **The 0013 boundary stands: expression yes, action no.** Nothing here
  touches dispatch, grants, HITL, routing or any adapter parameter. EMO-1's
  AST import ban and identical-dispatch tests still hold verbatim. What this
  ruling ADDS to 0013's vocabulary is the explicit line for the future:
  affect (including attachment) may inform how the system *presents* -
  orb, voice timbre, presence surfaces - and may never inform what it *does*.
  Any consumer on the action side of that line needs its own ruling.

- **Sleep distillation appraises.** The event map gains rules for the distill
  verbs: a promoted night appraises as `growth` (satisfaction, confidence,
  purpose, a grain of attachment - the system consolidating the owner's
  judgments into itself is a relational act), a held night as a mild
  `task_error`-shaped setback. Pure data (`event_map.yaml`), zero code.

## What this deliberately is not

- Not memory: attachment stores no events, no names, no content - one float.
- Not behaviour: a wistful orb, never a wistful action.
- Not per-user: engines are per-tenant (EMO-4); a tenant with several humans
  has one bond with "the humans it works with". Per-user attachment would
  need identity plumbed into the relay and is deferred until wanted.
- Not the notes lane: `docs/proposals/notes-before-weights.md` remains the
  path to an explicit, inspectable "how we work together" record.

## Consequences

- The three relational layers now connect: the fast layer remembers the bond
  (attachment), the slow layer embodies it (register adapter), the explicit
  layer can state it (memory/notes). Each stays in its own failure domain.
- The phenotype gains one scalar; downstream consumers that ignore it are
  unaffected (additive, P9).
- EMO-6 pins the boundary: accumulation only via appraisals, real-time decay,
  baseline-lift only, snapshot round-trip, phenotype-only exposure.
