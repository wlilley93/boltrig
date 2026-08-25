# The clip: wire — driving General Montgomery from Boltrig

The protocol `apps/worker/src/components/montgomery/FrameGraphRenderer.ts`
speaks. Kept beside his constitution because the renderer is public now: the
player it talks to is not, so this is the only place the contract is written
down on this side of the boundary.

ClipStage iframes the player (loopback :8902) and speaks `postMessage`
with `type` strings prefixed `clip:`. The player answers with
`clip:state` on every clip boundary and on request.

## Messages the player accepts

| type            | payload                          | effect |
| --------------- | -------------------------------- | ------ |
| `clip:emotion`  | `{tag}`                          | Directed jump to an emotion state hub. Holds `emotions.holdMs` (45s), then decays home through the adjacency graph. Unknown tag clears the direction. |
| `clip:position` | `{hub}`                          | Walk him to a position (H1 desk, H2 far table, H3 fireplace, H4 window). |
| `clip:say`      | `{n}` or `{text}`                | Speak a cached phrase from `phrase_index` (by number, or exact text match). |
| `clip:speak`    | `{audio_b64, mouthCues}`         | LIVE speech: base64 wav + Rhubarb cues — exactly what pocket-voice `POST /v1/audio/speech_with_visemes` returns. The player holds him on the position's `talk_base` loop and composites lip sprites at the bank's fixed rect. |
| `clip:visemes`  | `{on}`                           | Toggle lip compositing. |
| `clip:state?`   | —                                | Reply immediately with `clip:state`. |

## clip:state (player → host)

```json
{"type": "clip:state", "character": "General Montgomery",
 "node": "H1", "mood": "composed", "wantEmotion": null,
 "targetHub": null, "speaking": false,
 "emotions": {"tags": [...], "ambient": [...], "directed": [...],
              "adjacency": {...}, "default": "composed", "holdMs": 45000},
 "positions": ["H1","H2","H3","H4"], "talkBase": ["H1","H2","H3","H4"]}
```

## The emotion contract

The taxonomy ships INSIDE the .frame.mp4 (`manifest.emotions`,
`graph.stateHubs`, `graph.talkBase`) — the character.json schema's
`emotion` block names only the model (`graph-directed`). Ambient drift
walks the calm subset alone; vigilant, displeased and wry play ONLY on a
`clip:emotion` direction. A surprised face never appears without a
surprise — Boltrig's emotion engine is the thing that supplies the
surprise.

## Free-text speech without Boltrig

The player also carries `POST /say {text}` (proxies pocket-voice over the
maya-tts-tunnel and feeds the result to the same live-speech path), so a
bare browser can exercise the full loop.
