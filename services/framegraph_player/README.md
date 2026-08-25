# framegraph player

Serves a `.frame.mp4` character: one page, one graph, and the fragments a
browser needs to walk it.

## What it is

A frame-graph character has no shader. Its body is a closed graph of clips
rendered ahead of time and joined byte-exactly at hub frames, and its whole
expressive range is which clip plays next. This process owns that graph and
answers the host over a `postMessage` bridge (`docs/characters/montgomery-clip-wire.md`).

The graph itself rides inside the `.frame.mp4`'s uuid box, so the bundle is
self-describing: point this at the file and it knows the hubs, the walks, the
emotion taxonomy and the phrase index.

## Endpoints

| path | what |
| --- | --- |
| `/`, `/v1`, `/v2` | the player page |
| `/manifest.json` | graph, emotion taxonomy, phrase index, sprite rects |
| `mse720/*.m4s`, `mse720/init.mp4` | the fragments the browser appends |
| `sprite/<hub>/<shape>.png` | viseme sprites, composited over the video |
| `/pw/pNN.wav` | pre-rendered phrase audio |
| `/say` | live TTS for a typed line |
| `/state.json` | where he is, for a caller that cannot listen |

## Running it

```sh
docker compose --profile companion up -d framegraph-player
```

The bundle mounts at `/bundle`. Nothing is baked into the image, so one image
serves any character with a `.frame.mp4`.

## Why it is a service and not a library

The browser has to fetch fragments over HTTP as it plays; that is what
MediaSource does. There is no version of this that is a function call.
