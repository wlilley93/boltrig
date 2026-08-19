# 0030 - The Familiar gets modes, dials, and a place on the bench

- Status: accepted
- Date: 2026-08-18
- Amends: 0025 (Familiar Stage renderer ladder), specifically its client-side
  `FamiliarState` sketch
- Builds on: 0013 (emotion downstream-only), 0014 (familiar.express)

## Context

Three things were true of the Familiar at once, and each hid the next.

**She had two booleans where the other bodies have five states.** `FamiliarState`
carried `working` and `speaking`. Jarvis and Ultron carry
`standby | listening | thinking | working | speaking`, and the shared
`CharacterTurnInput` has carried `micActive` and `micLevel` since the character
contract was written. She dropped both on the floor — so while a person was
talking to her she rendered her idle state, which is the one moment a body has
an obvious job. `micLevel` was worse than unread: **nothing in the tree ever
produced one.** Jarvis's listening waveform was driving on a constant zero.

**She had no failure expression.** Worker maps a dropped call to "not working
any more", so a failure was indistinguishable from a finished turn: every field
went quiet in exactly the same way. The body went calm at the moment the page
said the call had died.

**Everything that decides how she moves was a literal in a frame loop.** The
voice envelope's attack and release, the working oscillator's depth and rate,
the wander's time constant, the gesture interval, her size in the porthole. A
number you can only change by editing a frame loop and reloading the app is a
decision nobody revisits, and "her pulsing is too jagged when she speaks" is the
kind of complaint that can only be answered by looking at her while turning it.

The third is why the first two survived. `tests/visual/shader-bench.html` — the
sliders-and-LFO bench that settled Jarvis and Ultron, itself modelled on the
voice mixer that settled Colossus by ear — could not show her, because she has
no draw passes to tune. Her look is one vendored 2,000-line fragment shader that
flows from `boltrig-familiar` and must never be edited here.

## Decision

**She keeps the five shared modes and adds a sixth of her own.**
`FamiliarMode = standby | listening | thinking | working | speaking | error`.
The five shared spellings match Jarvis and Ultron so a mode is one word across
all three characters. `error` is hers alone: adding it to the shared `BodyMode`
would force an entry into two other preset tables, and an empty delta there is a
state the enum claims and the body does not honour — the same defect shape as a
manifest that over-counts its clones.

Precedence, matching Jarvis: **failure > speaking > listening > working >
thinking > standby.** A dropped call is not less important than the turn that
was streaming when it dropped; she is speaking even while the next turn streams
behind it; and a live microphone outranks a background turn, because the person
in the room is the one waiting.

**The host recipe becomes a tuning struct.** `canvas/familiarTuning.ts` holds
sixteen fields — the four voice channels, the envelope, the silence gate, the
beat impulse, the listening gains, gaze, the arousal lift, the idle oscillator,
composition, daylight, the wander, the gesture interval and the error tone. Every
shipped value is lifted from the literal it replaced, so introducing the struct
changed nothing on screen; `familiarPresets.ts` then carries the per-mode deltas,
and its `working` preset reproduces the old oscillator exactly so the rest of the
table can be judged against something rather than against memory.

**The bench drives the real renderer.** `FamiliarWebGLRenderer` grows the same
`setTuning` / `currentTuning` / `transitionTo` / `intro` / `replay` / public
`frame` seam Jarvis and Ultron already expose, so the bench steps the shipped
renderer rather than a copy of it. A bench that rebuilt the recipe would drift
from it and then be tuning something nobody ships. **No line of `familiar.frag`
moved**, and the drift check that binds the vendored copy to its upstream is
untouched.

**`micLevel` comes from the barge-in gate.** The gate already polls the
microphone every 10ms and already tracks what silence sounds like in this room,
so a level meter needs no second analyser and no second calibration. Its verdict
carries a 0..1 level measured against that tracked floor over a 36dB span — the
figure the captures measured for real speech — throttled to ~30Hz on the way to
React, the same clock the outgoing voice's features use.

**The state is said out loud.** The Stage carries an `aria-live` region as a
SIBLING of the body. It cannot be the `aria-label`: that is a name, announced
once when focus reaches it, and `role="img"` replaces its own subtree in the
accessibility tree — so a live region nested inside one is never announced at
all.

## Consequences

- `FamiliarStageState` is `{ mode, level, bands, onset, micLevel }`. Callers
  that read `.working` / `.speaking` read `.mode` or `familiarBusy()` instead.
- `CharacterTurnInput` gains `failed?: boolean`. Every character may now show a
  failure without reading conversation text, which none of them may.
- The onboarding companion picker cycles her through her modes like the other
  three, instead of pinning her to `working: true` for the whole preview.
- The bench's Body select gains **Familiar**; its Mode select is generated per
  body, because the bodies no longer all have the same states.
- Emotion stays downstream-only and cosmetic (0013) and expression stays a
  granted verb (0014). Nothing here reaches grants, HITL, routing or dispatch.
- Unreal remains the deferred premium backend of 0025, unchanged.
