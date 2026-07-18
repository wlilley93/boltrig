# 0014 - familiar.express: voluntary expression through the chokepoint (WL-3)

Status: accepted (2026-07-18)

## Context

The desktop familiar (the wayland add-on, `~/Projects/beelink-desktop/familiar`) renders boltrig's
inner life. The emotion add-on (`boltrig/emotion`) gives it an AUTONOMIC path: a downstream projection
that appraises the run-event stream and publishes a phenotype file the surface reads. That path is
strictly downstream of dispatch (EMO-1) - the creature cannot help how it feels; nothing chooses it.

The governing ruling of the emotion/wayland design distinguishes a second path: VOLUNTARY expression -
the agent deliberately choosing to express something (look at the user, pulse, celebrate). That is an
ACTION, not a projection, so it must not be a side door from an agent to the surface. WL-3 requires it
to be a registered verb, schema-bound, grant-checked, and audited, like any other action.

## Decision

Add `familiar.express` as a normal builtin adapter (`boltrig/adapters/builtin/familiar.py`), NOT part of
`boltrig/emotion` (which is downstream-only and must never influence dispatch, EMO-1). The verb:

- is registered via `describe()` with an input binding: a closed `gesture` enum
  (`look|pulse|flinch|celebrate|greet|nod|recoil|preen`), optional `intensity` 0..1 and `ttl_s` (capped),
  `additionalProperties: false`;
- goes through the one dispatch chokepoint, so it is schema-validated (SEC-21), grant-checked (SEC-07,
  grant token `familiar.express`), and audited (SEC-16) with no adapter-side work;
- its handler is the ONLY writer of the express channel `$XDG_RUNTIME_DIR/boltrig-express.json` (a tiny,
  world-readable, atomic write), which the surface reads and renders as a short decaying gesture over the
  sustained mood. The surface only ever READS; nothing writes that channel except a granted, audited
  dispatch. That is the "no side door" clause.

The record is content-free (a gesture enum + two numbers), so nothing sensitive reaches the observable
surface (K-20). Delivery is best-effort: with no runtime dir (headless/prod) the verb still dispatches
and audits, `delivered` is just false.

## Consequences

- WL-3 is bound at binding-debt 0 by `tests/security/test_familiar_express.py` (ungranted -> denied +
  audited + nothing written; bad gesture -> schema-rejected + nothing written; granted -> dispatched +
  audited + channel written).
- Severability: the adapter imports only `boltrig.adapters.base` + `boltrig.models` (+ stdlib). It does
  NOT import `boltrig.emotion` (forbidden for the adapters layer); the atomic-write pattern is copied,
  not imported.
- The surface-side rendering of gestures (the beelink `familiar` reading the express channel) is the
  cosmetic other half; the governance lives entirely here.

## Alternatives rejected

- Feeding `familiar.express` into the emotion engine as an appraisal: collapses the voluntary/autonomic
  distinction and would put a dispatch verb inside the downstream-only emotion package, blurring EMO-1.
- A direct socket/IPC from an agent to the surface: the exact side door WL-3 forbids.
