# Maya's bundle — consolidation record, 2026-08-13

Phase 4 of the character-bundle work: Maya's assets get **one root** and **a
manifest**. Both, not either — the manifest is the contract, the root is what
makes her copyable without archaeology.

Format: `docs/SPEC-character-bundle.md`. Schema:
`schemas/character-bundle/v1/character-bundle.schema.json`. Familiar was built
first (`apps/worker/src/bundles/familiar/character.json`) and, as intended,
already dictated the field names and proved that `prompts` must be optional.

## The root

    ~/Projects/character-bundles/maya/

A top-level directory owned by no project, one subdirectory per character.
Four candidates were rejected, each for a reason that would have cost someone
later:

| rejected | why |
| --- | --- |
| `gen-pipeline/me-lora/` | me-lora is a **studio**. It produces *into* a bundle; assets do not live in it. |
| `gen-pipeline/store/` | 22 GB shared across several characters, mirrored nightly to beelink by `backup-store.sh` — which runs **without `--delete`**, so any move under `store/` leaves a silent stale copy on the far side rather than erroring. |
| `boltrig-companion/` | Its own `.gitignore` opens *"assets + heavy local state live in the shared store, never here"*. It holds the private distribution's **code** (`characters/maya/register.ts`); a bundle is configuration only, so the data does not belong beside the code that registers it. |
| `boltrig/` | Public package graph. A companion character reaching it is the exact failure `characterPlugins.ts` exists to prevent. |

**186 MB of real bytes; 3.5 GB when symlinks are followed.** Copy it with
`cp -RL`, not `cp -R`. That is stated at the root and in `provenance.note`.

    maya/
      character.json                    the manifest
      README.md                         the layout, and the EXCLUDED note
      visual/Maya.conversation.frame.mp4   REAL BYTES (rescued)
      visual/Maya.greeting.frame.mp4       REAL BYTES (rescued)
      identity/anchors/                 -> store/clips/Maya/raw
      identity/visual-lora/             -> me-lora/ui/outputs/Luna
      identity/example-clips/           -> store/clips/Maya/wan/{state}/000.mp4
      library/                          -> store/clips/Maya          (2.9 GB, shared)
      voice/lora/                       -> store/voice/lora/maya/checkpoint-600
      voice/reference/                  -> store/voice/zeroshot
      lines/                            -> store/voice/lines/maya    (92 wavs)
      prompts/                          -> maya-remote/maya-persona*.md
      behaviour/camera.json             -> companion-observer/characters/maya.json
      data/                             -> store/clips/Maya/{character.db,prompts.json,PROMPTS.md}

## The manifest

`~/Projects/character-bundles/maya/character.json`, 15,777 bytes.
**Validated against `character-bundle.schema.json` with jsonschema 4.26.0 —
0 errors** (Familiar re-validated in the same run as a control, also 0).
All 12 `assetRef`s were re-hashed from the root after writing: **0 mismatches,
0 escaping paths.**

Required triple plus the two the schema adds over the prose spec:

    id     maya
    name   Maya
    blurb  A companion with a body, a voice, and a memory of your days.
    type   companion          (Familiar and Jarvis are type: shader)
    visual companionVisual

`blurb` is taken verbatim from `boltrig-companion/characters/maya/register.ts`
so the bundle and the registration site cannot disagree.

### What she genuinely has

- **`visual`** — `source: boltrig.canvas.companion`, `frame:
  Maya.conversation.frame.mp4`, `directions: [idle, talk, listening, nod,
  smile]`. The directions are not invented: they are the `states` list read out
  of the file's own `uuid` box.
- **`prompts.persona`** — the full 11 KB of `maya-persona.md`, **inline**. The
  schema types `persona` as a plain `string` and uses `$ref: assetRef`
  everywhere it means "a file in the bundle", so inline is the reading the
  schema supports. It also gives the one asset with no digest an integrity
  story.
- **`phenotype: {reads: true}`** — `register.ts` declares `readsPhenotype: true`
  via `defineClipCharacter`.
- **`identity`** — 3 anchor images, the visual LoRA, 5 example clips.
- **`voice.selfHosted`** — the 10 s zero-shot reference and the **107 MB
  `adapter_model.safetensors`**, not the 5.4 GB checkpoint tree around it.
- **`voice.fallbackVoiceIds`** — `elevenlabs: gy5tIyyb2goenGrDhfuL` and
  `pocket-voice: maya`.
- **`capabilities`** — camera wanted with her prompt and diary name, presence
  wanted, budgets **not** wanted, two automations.
- **`credentials.providers: ["elevenlabs"]`** — names only, never populated.

### What was deliberately OMITTED (Familiar established that omission is the pattern)

| field | why it is absent |
| --- | --- |
| `visual.segments` | The segment manifest lives **inside** the `.frame.mp4`'s `uuid` box (`frame_bake.py` → `frame_box.write`). There is no sidecar file, so an `assetRef` would have to be invented. |
| `visual.restrictedScene` | `store/clips/Maya/spicy/` is 3 raw clips, not a baked scene. No second `.frame.mp4` exists, and the format requires a restricted scene to be able to be absent entirely. |
| `emotion` | The schema requires `model`, and states it must be one the bound canvas source *declares it supports*. No companion source is registered yet, so any name I wrote would be a guess that fails at registration. See outstanding. |
| `phenotype.state` | `~/.local/state/boltrig/emotion-state.json` is `{"v":1,"tenants":{}}` and `store/state/dev_override.json` is all zeros and is a **dev artefact**. Carrying zeros would assert a state she does not have. |
| `distillation` | There is no per-character LoRA loop for Maya. Boltrig's `distill_sidecar` on `:8930` is generic **text** infrastructure and names no character. Her nightly jobs are `consolidate.py` (03:17) and `compose.py` (04:05), neither of which trains anything. Familiar omits the field; so does she. |
| a Fish Audio id | `maya-remote/voices.json` is Fish, is 32-hex, and has **no `maya` key**. It is infrastructure, not hers. Merging it with the ElevenLabs map would resolve a name to an id `api.fish.audio` cannot accept, and the failure would look like a bad voice rather than a bad provider. |
| `capabilities.camera.observations` | Nothing in the estate says *which* observations matter. `skip_markers`, `max_tokens` and `temperature` from `companion-observer/characters/maya.json` have no home in the schema — see outstanding. |

## Moved vs. referenced

**Exactly two files gained a new home. Everything else is a symlink.**

**Rescued (copied, not moved):** `Maya.conversation.frame.mp4` (140.8 MB) and
`Maya.greeting.frame.mp4` (54.4 MB) were sitting in **another session's
`/private/tmp` scratchpad** with **no reader anywhere in the estate** — the
highest-risk assets in the inventory, and the only companion-type visual Maya
has. They are now real bytes under `visual/`, byte-identical (sha256 verified
both sides), and `frame_box.read()` parses both from the bundle copy.

They were **copied, not moved**: deleting another agent's scratchpad files is
not mine to do. The scratchpad pair is the one at risk of a sweep; the bundle
pair is now canonical.

**Referenced:** everything else. Anchor images, the visual LoRA, the 2.9 GB
clip library, the voice LoRA, the zero-shot reference, the 92 rendered lines,
the persona, the camera config, `character.db`. Each has at least one live
reader with a hard-coded absolute path, and several have more than one.

**No reader was updated, because no reader needed to be.** That is the outcome
the brief asked for — a tidy tree with a broken pipeline is worse than an
untidy one.

Two references worth naming explicitly:

- `library/` → `store/clips/Maya` is a **shared dataset**. Bella (2.0 GB), Luna
  and amara live in the same tree, and `upscale_library.py` and the player both
  read it. It is referenced, never enumerated in the manifest, never moved.
- `identity/visual-lora/luna_char.safetensors` is the **Luna face**, shared with
  the Luna character. Maya has no LoRA of her own. The host copy under
  `me-lora/ui/outputs/Luna/` is what the symlink points at; the **live** object
  is `e874c34c7c124eddb91d14243eac00ec.safetensors` in the named volume
  `me-lora_minio-data` (confirmed present). `me-lora/minio-data/` **on the host
  is stale and does not contain it** — trusting that directory would conclude
  Maya's likeness is missing. `configs/atlas_cloud.json` keeps its `minio://`
  ref; it was not touched.

## Deliberately EXCLUDED

Written at the root as a `## NEVER ADD THESE` block in
`~/Projects/character-bundles/maya/README.md`, so the next person cannot
"complete" the bundle by adding them.

    ~/pixy-stream/identity/enrolled.npz          and its two .bak-20260813-* copies
    ~/pixy-stream/identity/config.json           room-calibrated threshold
    ~/Projects/gen-pipeline/store/personal/**    diary, frames, observations, fact-sheet

`enrolled.npz` is the **operator's** enrolled face; `config.json` is calibrated
to the operator's room. This is the one place the rule "likeness belongs to the
character" is **deliberately overridden**, and the reason is that it is not the
character's likeness: the anchor images are Maya's face, `enrolled.npz` is
yours. A character is a thing you might share.

Also excluded: every populated key, token and credential. Named specifically in
the root README because it is world-readable and looks innocuous:
`me-lora/scripts/voice-pipeline/lora_r2_url.txt`, a **live presigned R2 URL** —
a credential in all but name.

Also excluded: the cloned voice bytes.
`~/Projects/pocket-voice/voices/maya.safetensors` and `maya-serious` are
**named, never copied**, and `~/Projects/pocket-voice/refs/maya/` is not linked
at all. The manifest reaches them through `fallbackVoiceIds["pocket-voice"] =
"maya"`, which pocket-voice resolves by name.

*(Worth recording, since it corrects a reasonable assumption: Maya's voice is
**not** a clone of a real person. `gen_corpus_v2.py` generated her corpus from
**ElevenLabs voice `gy5tIyyb2goenGrDhfuL`** — the same id now in her manifest —
and `refs/maya/*/candidates.json` records `"generator": "ElevenLabs TTS"`,
`"cloned": false`. The exclusion is honoured anyway: the rule is right even
where this particular provenance is benign.)*

**Audit run after construction:** no file matching `enrolled.npz*`,
`config.json`, `fact-sheet.md`, `observations.jsonl`, `.env` or `*_url.txt`
exists anywhere under the root, and **no symlink in the root resolves into
`pixy-stream/` or `store/personal/`**.

A `.gitignore` sits at `~/Projects/character-bundles/`. The tree is **not** a
git repo; the file exists so that a later `git init` cannot sweep up a face, a
cloned voice, a `.frame.mp4` or a credential.

## Readers exercised — real output, not assumptions

Everything below was **run**.

| reader | how | result |
| --- | --- | --- |
| `companion-observer/character.py` | `.venv/bin/python -c "character.load()"` | 1 character: `id=maya`, prompt intact, `diary_dir` → `store/personal/diary` |
| `upscale_library.py` | `--dry-run --limit 5` | `5 clips to consider`, 5× `skip-already-4k` |
| `me-lora/scripts/character_db.py` | `db_path('Maya')` + `load_prompts('Maya')` through the **`dataset` symlink** | path exists; 234 clip rows, 41 intent rows, 6 prompt keys |
| me-lora UI (`:8000`) | `GET /` then authenticated `GET /api/characters` and `/api/voice/refs` | `307` → login; characters list served; `/api/voice/refs` served `joi` + registers, exercising the read-only `pocket-voice/refs` bind mount |
| `pocket-voice` (`:8911`) | `GET /voices` | `{"local":["maya","maya-serious"], ...}` — the manifest's `pocket-voice: maya` resolves by name |
| `compose.py` (crontab 04:05) | imported under `/opt/homebrew/bin/python3`, printed path constants | `LINES`, `SHEET`, `PERSONA`, `RENDER`, `VOICE_PY` all `exists=True` |
| `vigil.py` | imported, printed path constants | `FRAME` and `STORE` `exists=True` |
| `maya_player.py` reader paths | loaded `catalog.json` + `chain_index.json` from `store/clips/Maya/wan` | 24 catalog keys, 534 chain entries, 92 line wavs |
| `rescue_shards.py` / `pods/launch.py` | grepped the anchor tuple, stat'd all three | tuple unchanged at `rescue_shards.py:21` and `launch.py:126`; all three files present |
| `frame_box.read()` | run against the **bundle copies** | `conversation` 50 segs / 253.1 s; `greeting` 20 segs / 101.2 s |
| the schema itself | `jsonschema 4.26.0` Draft202012Validator | Maya **VALID**; Familiar **VALID** (control) |

**Not run, and why:**

- `compose.py` was **imported, not executed**. Executing it renders voice lines
  through the OmniVoice venv and would write into `store/voice/lines/maya`. Its
  inputs were proved to resolve; the render was not performed.
- `vigil.py` likewise — it is a loop with a launchd job behind it.
- `maya_player.py` on `:8901` **was not running before I started and is not
  running now.** `curl` returned `000`. I did not stop it and did not touch it;
  its data paths were exercised directly instead. This is consistent with the
  open task about the presence-to-player coupling.
- `backup-store.sh` was **not** run. Nothing under `store/` changed, so nothing
  it mirrors changed. I did not touch beelink, Salad, R2 or any network surface.
- `vigil.py`'s `INTRUSIONS` path reports `exists=False`. **Pre-existing and not
  a breakage** — `vigil.py:64` creates it lazily with `os.makedirs(exist_ok=True)`.

## Outstanding

1. **`boltrig.canvas.companion` is a name nobody registers yet.** The manifest
   declares it because the schema is explicit that an unregistered source id
   must be *refused by name, never substituted*. Refusal is the correct
   behaviour until the private companion source exists. The alternative — a
   source id that happens to be present — is the failure the schema warns about.
2. **`Maya.greeting.frame.mp4` has no slot in the manifest.** `companionVisual`
   allows exactly one `frame` plus an optional `restrictedScene`, and greeting
   is a second *unrestricted* scene. It is in the root and safe; the format
   currently cannot name it. Either the schema grows a scene list, or greeting
   folds into the conversation bake.
3. **`emotion` is unset.** She reads a phenotype but has no declared affective
   model name that a canvas source supports. Resolve with item 1.
4. **`camera.json` carries fields the schema cannot express** —
   `skip_markers`, `max_tokens`, `temperature`. `behaviour/camera.json` remains
   the fuller config `companion-observer` actually reads, and the manifest
   carries only `prompt` and `diary`. Two sources of truth for one capability.
5. **The persona has the same shape of problem.** `prompts.persona` is inline
   and is the contract; `maya-remote/maya-persona.md` is the editing source
   `compose.py` reads nightly. Its sha256 at consolidation is recorded in
   `provenance.note`, so drift is detectable — but nothing detects it
   automatically. A future Maya-bundle verifier, mirroring the existing
   Familiar shader check, would close items 4 and 5 together; no such verifier
   is shipped yet.
6. **`character.db` carries `sessions` and `session_events`** — a record of the
   operator's use, closer to kernel data than character data. It is referenced,
   not copied, so nothing has leaked; but an export path must decide whether
   those two tables travel. Flagged in the inventory, still undecided.
7. **`checkpoint-400`** (2.7 GB) still has no reader and survives only in the
   A/B wavs. Not bundle data. Deleting it is a separate decision.
8. **The `.frame.mp4` pair still exists in the other session's scratchpad.**
   Copied, not moved, on purpose. Someone should confirm that session is done
   and remove them, or leave them to be swept.
9. **Bella, Luna and JOI have no bundle.** `character-bundles/` is shaped for
   them; JOI already has an ElevenLabs id sitting in
   `maya-remote/voices.elevenlabs.json` waiting for a manifest of her own.

Nothing was committed. No git remote was added anywhere. No `minio://` ref was
replaced with a permanent URL.
