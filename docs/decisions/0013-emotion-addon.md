# 0013 - Emotion add-on: a downstream-only affective projection

- Status: accepted
- Date: 2026-07-18
- Bound by: EMO-1..EMO-5 (`tests/invariants.yaml`), P9 (fail-safe side-channel)

## Context

Boltrig already expresses itself through the desktop orb via
`boltrig/observability/orb_presence.py`: an `EventRelay` subclass mapping run
events to a handful of discrete `orbctl` emotions. That module is a dead end -
a lossy event-to-emotion table with no state, no continuity, and a second
place where affect logic would accrete. The Atrophy prototype has a real
affect model: emotions with baselines and half-lives, needs decaying toward
zero, a P/A/D mood integrator, and appraisals held as data.

## Decision

- **Scope.** A new `boltrig/emotion/` package: a pure engine (`engine.py`, no
  I/O, no clock reads, no randomness - EMO-3), YAML-backed tables
  (`tables.py`, loading `libraries/emotion/*.yaml` - EMO-5), and `relay.py`,
  an `EmotionRelay` subclass of the kernel's `EventRelay` plus the
  `build_event_relay` factory. It SUPERSEDES and deletes
  `boltrig/observability/orb_presence.py`. Per-tenant engines project the run
  event stream into a 9-scalar phenotype file the desktop orb reads.

- **Downstream-only ruling.** Emotion is a read-only affective projection over
  the kernel's event stream. The kernel's ONE emotion touch is the relay
  factory seam in `boltrig/kernel/__init__.py`; nothing else under
  `boltrig/kernel/` may import `boltrig.emotion` (EMO-1, AST-enforced), and
  dispatch outcomes are identical with the relay attached or not. It never
  influences grant checks, HITL, or dispatch, and every exception in the
  side-channel is swallowed (P9).

- **File-based persistence; `config_revisions` and the Store deliberately not
  used.** The publisher thread atomically writes the phenotype to
  `$XDG_RUNTIME_DIR/boltrig-phenotype.json` and periodically snapshots engine
  state to `$XDG_STATE_HOME/boltrig/emotion-state.json` (tmp + `os.replace`).
  A cosmetic side-channel must not couple to the Store or run async writes
  from a thread; plain files keep its failure domain at zero kernel surface,
  and both documents are keys-and-numbers only (EMO-2).

- **Env-only enablement.** `BOLTRIG_EMOTION=0` forces off, `=1` forces on;
  otherwise `orbctl` on PATH decides (the desktop-box heuristic consolidated
  from orb_presence). Missing or invalid YAML, or no `XDG_RUNTIME_DIR`, leaves
  the plain `EventRelay` in place: the feature fails toward off, never toward
  a broken run.

- **Deferred.** Voice integration and a `services/familiar` companion process
  are out of scope for this add-on and deferred.
