# 0025 - Familiar Stage: a renderer ladder inside Worker, not a new surface

- Status: accepted
- Date: 2026-08-10
- Amends: nothing; builds on 0013 (emotion downstream-only), 0014 (familiar.express),
  0021 (Worker primary surface)

## Context

Worker renders the Familiar as a CSS orb (`.familiar-orb` in `ChatView.tsx`, a
`mini-familiar` dot in `VoiceCall.tsx`). Two proven richer implementations exist:

- `wlilley93/boltrig-familiar` (checked out on the beelink as
  `~/Projects/beelink-desktop`): the production GLES3 body — `familiar/familiar.frag`
  (1,929 lines, theme 2 "silk"), nine-scalar phenotype, gesture channel, design brief,
  headless bench. Canonical visual design.
- `wlilley93/boltrig-familiar-web`: a static browser port proving the production
  shader runs on a WebGL2 canvas — hero↔compact orb modes, client-side mood engine,
  ambient gestures, `prefers-reduced-motion` (~1 fps calm mode), WebGL-failure
  fallback. Donor implementation, not a production frontend.

Observed at decision time: `boltrig` on `main`, clean; the desktop repo carries an
uncommitted filament-shell prototype (benched 4.35 ms worst-case at 1080p on the
680M) that is deliberately NOT part of this work until it lands there.

An earlier plan targeted Hyprland/layer-shell/systemd presentation. That is
discarded: the production surface is Worker (web + Tauri), per 0021.

## Decision

One presentation component, `<FamiliarStage />`, hosted by Worker, over a renderer
ladder chosen by a broker at mount:

| Backend | Role |
| --- | --- |
| CSS `FamiliarBadge` | floor: message avatars, subagent dots, no-WebGL fallback |
| `webgl2` | universal Stage renderer, bundled, zero external processes |
| `unreal-local` / `unreal-remote` | optional premium tier, DEFERRED (see below) |

- **FamiliarBadge** is the extracted CSS orb (was `Familiar` inside `ChatView`).
  It keeps genotype palette + accessible labels and stays per-message cheap. There
  is never a premium renderer per message — one Stage session per Worker client.
- **FamiliarWebGLRenderer** ports the familiar-web host (fullscreen-triangle
  WebGL2, companion/aperture uniform recipe, mood baseline, gesture envelope,
  reduced-motion, DPR cap 1.25) behind a `FamiliarRenderer` interface
  (`mount/update/resize/setMode/suspend/resume/status/destroy`). The shader is
  vendored verbatim from boltrig-familiar-web (itself verbatim from
  boltrig-familiar) and imported as a Vite `?raw` asset — no runtime fetch, CSP
  untouched. Shader upgrades flow boltrig-familiar → here, never the reverse.
- Stage presentation modes: `hero` (new conversation), `conversation` (compact,
  chat header), `voice` (expanded during a call), `minimised` (hidden tab, tiny
  viewport, or reduced-data) — plus `prefers-reduced-motion` handling at ~1 fps
  with the inner life frozen.
- State: the Stage consumes a client-side `FamiliarState` derived by a reducer
  from the structured chat events Worker already receives (working/ready, voice
  active, gesture). The full FamiliarState v2 contract (phenotype projection from
  `boltrig/emotion`, activity channel, 8-band audio/voice features) is a follow-up
  that belongs in the web SDK; emotion stays downstream-only and cosmetic (0013),
  expression stays a granted verb (0014). Familiar state must never influence
  grants, HITL, routing or dispatch.

**Unreal (5.8 + Niagara via Pixel Streaming 2) is a deferred premium backend.**
Gate order: this WebGL fallback lands and ships first; the Unreal project lives in
`boltrig-familiar` (`unreal/FamiliarUE/`); it reaches Worker only as a Pixel
Streaming `MediaStream` owned by the same `FamiliarRenderer` interface; a packaged
runtime carries no MCP, no credentials, no conversation content, loopback-only
under Tauri supervision with fixed start/status/stop commands. Editor-side Unreal
MCP binds 127.0.0.1:8765 (8000 is Boltrig's). None of that starts until the Stage
exists and the Mac-side engine install (interactive Epic step) is done.

## Consequences

- Commit plan: (1) this ADR; (2) extract `FamiliarBadge` + `familiar/` module
  skeleton, behaviour preserved; (3) WebGL renderer + Stage + reducer + tests.
  Worker CSP, Tauri capabilities and the SDK are untouched by commits 1-3.
- `VoiceCall`'s `mini-familiar` participant dots stay as-is until the Stage's
  voice mode replaces the call presentation deliberately.
- The desktop GLES familiar remains the beelink's presentation and the canonical
  shader source; nothing in Worker supersedes it.
