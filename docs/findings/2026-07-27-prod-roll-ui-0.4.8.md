# Prod roll ui 0.4.8 - the familiar reaches the tenants

Date: 2026-07-27. Both stacks rolled `ui 0.4.6` -> `0.4.8`, digest-pinned. No
schema change, no kernel or fleet change.

## Final state

| stack | kernel | fleet | ui | schema | readyz | public |
| --- | --- | --- | --- | --- | --- | --- |
| `app.boltrig.io` | `0.4.7` | `0.4.7` | `0.4.8` | `0039` | ready | 200 |
| CV (client tenant) | `0.4.7` | `0.4.7` | `0.4.8` | `0039` | ready | 200 |

Digest `sha256:24d220e5…`, confirmed with `buildx imagetools inspect` against the
registry rather than from the push exit code.

## Why the versions are not level, on purpose

Every previous roll made a point of putting the whole fleet on one version. This
one does not, and the reason is worth stating rather than leaving as an
inconsistency: everything in it is UI. Rebuilding `kernel` and `fleet` at 0.4.8
would produce new digests for byte-identical behaviour and would restart a client
tenant's kernel for no change it can observe. A restart of a client's serving
kernel is a real cost; a restart of its static file server is not. So `ui` moved
alone and the skew is recorded here instead of being papered over by churn.

## What it carries

The familiar: every agent gets a body derived from what it is (a genotype), with
mood layered on top in real time (a phenotype). Merged across PRs #100 to #104.
24 of roughly 107 genotype parameters are built. The last of them, `tempoBase`
and `bodyScale`, arrived beside two that were REMOVED before they shipped:
`moteGain` and `ejectRate` feed `moteA`, which only ever reaches `cover`, and
`cover` is discarded wherever `uPresence` is 1. Swept across every mood that
produces motes or ejecta, neither changed a single pixel. A gene that cannot be
shown to do something is not a gene.

## Verified at the destination, not at the tag

Four separate places, because "the image is pinned" has been wrong before:

1. The registry holds the digest the overlay names.
2. `docker inspect` on both boxes reports the containers RUNNING that digest.
3. Inside each container, the served bundle contains the shader chunk and 19
   occurrences of `uGene`, so the genotype uniform really is in what nginx will
   hand out.
4. Over the PUBLIC edge, through Cloudflare: `GET /` names
   `assets/index-DBhYj-d-.js`, that chunk answers 200, and
   `assets/familiar-BntiOdFS.js` answers 200 at 113,000 bytes with the same 19
   occurrences. That is the only one of the four that measures what a user gets.

Step 4 is the one that matters and it is the one nothing before this roll did.
The shader is a DYNAMIC import, so it lands in its own chunk rather than in the
main bundle; a container that holds the right files can still be fronted by an
edge that will not serve one of them, and only fetching it over the public URL
can tell those apart.

## Both kernels answer ready

`/readyz` returns `ready` on both, with `model_gateway` the only non-`ok` check
and it is not required. The container healthcheck probes `/readyz` on port 8000
now, not `/healthz`, so the gap that cost the CV tenant forty silent minutes on
2026-07-25 is closed on the boxes and not only in the file.

## Rollback

The previous overlays are at `/tmp/bio.bak` and `/tmp/cv.bak` on the box, and
`boltrig-ui:0.4.6@sha256:60700bd7…` is still in the registry and still in the
local image cache on both stacks. Rolling back is a pin edit and `up -d ui`; no
data moves, because the UI holds none.

---

# 0.4.9, forty minutes later, because 0.4.8 shipped a broken body

`ui 0.4.8` put the familiar in front of both tenants with **every body's radius
multiplied by zero**. Rolled to `0.4.9`
(`sha256:9849af16…`) the same afternoon.

The cause is in `docs/vjs`-adjacent detail in the PR, and the short version is that two
hand-written slot tables described one POSITIONAL uniform and disagreed from slot 22 onward.
`genotype.h` pads with `NULL`s so a gene keeps its index as the array grows; `genotype.ts`
dropped the padding, so `bodyScale` was written to a slot the shader does not read and the
slot the shader reads AS `bodyScale` got a `Float32Array`'s zero fill.

## What this roll changes about how a roll is verified

The 0.4.8 verification above has four steps and step 4 says it is "the only one of the four
that measures what a user gets". That was right about the shader and **wrong about the
genotype**, and the difference is worth writing down because the check looked identical.

`assets/familiar-*.js` is the chunk the DYNAMIC import produces, and it holds the GLSL and
nothing else. Its 19 occurrences of `uGene` are the shader's own, so the check proved the
shader shipped and proved nothing whatever about the packer that feeds it. The packer is in
`assets/index-*.js`, a different chunk entirely, and it was the broken half.

So the check for this roll reads the SLOT TABLE out of the served index chunk:

```
"specSharp","haloReach","specGain","fresnelGain",
"tempoBase","bodyScale","haloGain","irritationGain",
"lightAzimuth","bumpScale",null,null
```

Thirty-two entries, the two holes present, `tempoBase` at index 24 and `bodyScale` at 25,
matching `uGene[6].x` and `uGene[6].y` in the shader beside it. That is the artefact whose
correctness was in question, fetched from the address a browser fetches it from.

Grepping a chunk for a symbol shows that SOMETHING shipped. It does not show that the thing
you were worried about shipped, and a chunk boundary is exactly where those two come apart.
