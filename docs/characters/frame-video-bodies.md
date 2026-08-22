# Frame-video bodies (.frame.mp4)

**Status: design contract, agreed 2026-08-20. Nothing here is implemented in
the worker yet.** This document is the authority for the third body kind:
characters whose body is a graph of pre-rendered video clips rather than a
shader. First instance: **General Montgomery**. The mechanism predates this
document — Montgomery's original ambient-loop generator (companion repo,
`scripts/agents/general_montgomery/generate_ambient_loop.py`) already worked
this way: *"All loops start and end on the source portrait, so they can be
chained in any order."* This contract is that idea made exact and put under
governance.

## The graph

A frame-video body is a state machine (authored and validated in FrameGraph
Studio):

- **Hubs** are poses: standing at the map table, seated at the desk, by the
  window. Each hub is ONE canonical frame.
- **Spokes** are variations that leave a hub and RETURN TO THE SAME HUB:
  a nod, a shift of weight, a glance down at papers, speaking. A hub needs at
  least one idle spoke or the body is a photograph.
- **Transitions** are moves between hubs: he walks from the desk to the map
  table. Different start and end frames, still hub-to-hub.

Playback is graph traversal. **The legal move set IS the character's
expressive range**: emotion, phenotype and presentation mode do not draw
anything — they are a policy choosing the next edge among the legal ones. More
hubs and more spokes means more legal moves means more lifelike; the graph
grows a character the way vocabulary grows a language.

Runtime mapping: the worker's five `BodyMode`s (standby / listening /
thinking / working / speaking) partition each hub's spokes; emotion state
biases selection within the partition. Mode changes take effect at the next
hub — joins exist ONLY at hubs, so a spoke plays to completion (barge-in
included: the earliest legal cut is the hub it is already returning to).

## Byte-exact joins, or why this composes at all

A cut between two clips is invisible only when the frame before it and the
frame after it are THE SAME FRAME. Same bytes, not same-ish.

No generator produces that. 44 of the 190 video models in the Atlas catalogue
accept an end frame (Seedance, Kling, Veo 3.1, Flux-3 FLF, Minimax h3,
Wan 2.7) and every one CONDITIONS on it — the target goes through the VAE and
the decoded last frame is the model's rendering of it. Byte-exactness is
CONSTRUCTED instead, in FrameGraph Studio (`server/framegraph/forge.py`):
every clip's first and last frames are rewritten with the canonical hub
frames at encode time, deterministically pinned so the same hub PNG decodes
to the same bytes in every clip it is forced into. Measured 2026-08-20: two
clips sharing nothing but geometry, forced to one hub — all four edges
hash-identical; a real wan-2.7 hub-to-hub render came back with first sha ==
last sha in 34s, swap seams 0.5/0.97 (green) because conditioning and forcing
are a pairing: the model lands NEAR the hub, the forge lands ON it.

Authoring therefore always both conditions and forces. The seam score on
every forced edge is the join's visibility, measured; a red edge is a spoke
that needs re-rendering, not a spoke that ships.

## Geometry law

**One character, one canvas, forever.** The forced hub is the hub scaled to
the clip's geometry, so clips at two sizes carry two different hubs and never
join — and hosted models resize on their own (wan-2.7 returned 722x1274 for a
544x960 ask). FGS conforms every clip to the character's canvas
(`target_size` in forge). Call mode is a full-bleed landscape surface, so
frame-video characters pin a landscape canvas — 1280x720 minimum, 1920x1080
preferred. Portrait bodies do not exist in this kind.

## Environment law

**The character and his environment are one image.** Hubs are generated as
full scenes — Montgomery IN his briefing room, the room in the frame, lit by
the frame's own light (his face recipe already ends: "Background: muted,
dark, out of focus. A war room, an office, a dim briefing room."). No
transparent-background sprites, no compositing a figure over a backdrop, no
swapping the room behind a cut. A change of place is a TRANSITION — he walks
there — because a cut that moves only the background reads as teleportation,
and because every legal move must be a real clip with real joins.

## Call-mode presentation

When a call is active (`onCallActive`) and the character's body is
frame-video, the stage is **full-bleed**: the video fills everything right of
the left rail primary nav. The left rail stays. Everything else floats OVER
the video as overlays — the chat UI, the top-right tools-used overlay, call
controls. Shader characters keep their existing stage; outside call mode
nothing changes for anyone.

## Bundle shape (draft — the part most likely to change)

```
apps/worker/src/bundles/general_montgomery/
├── character.json        # constitution-backed prompt, voice, capabilities
├── body.graph.json       # hubs, spokes, transitions, mode partitions,
│                         # canvas, per-edge seam scores, canonical hashes
└── (clips by asset ref)  # video is too heavy for git; refs resolve through
                          # the asset store, player prearms the next clip a
                          # whole clip early (maya-player precedent)
```

Open: asset hosting, the VideoStage component beside FamiliarStage, graph
schema versioning. Every clip's edge hashes and the canonical hub hash ship
in the graph so the PLAYER can verify the join contract at load — claimed
exactness is always verifiable, never assumed.

## Montgomery: provenance

Recovered 2026-08-20 (`~/monty-recovered` on the beelink): soul, system
prompt, heartbeat and agent.json from Atrophy's git history (deleted in
commit 9bf78657's parent); ElevenLabs voice `0z5GDPjj5mWasIEHkugR` ("clipped
British military register"); his complete face recipe — Flux prompt, negative
prompt, `fal-ai/flux-general`, 50 steps, guidance 3.5 — and the Kling 3.0
ambient-loop generator, both in the `companion` repo
(`scripts/agents/general_montgomery/`). His original rendered portraits are
confirmed gone from every machine, disk and repo; the face is regenerated
from the recipe, in-environment, on the pinned canvas. The constitution
document for this directory's table comes from the recovered system prompt
when the character is actually built.
