# Handover: speech becomes Boltrig-native, characters become bundles

2026-08-13. Two things settled today, plus a working-tree audit that corrects a
claim made earlier in the same session.

1. **Speech is Boltrig infrastructure**, not a companion's. A local voice stack
   runs on the M4 and is reachable through an OpenAI-shaped endpoint, so it is
   one *route type* among several rather than the architecture.
2. **Every character is a bundle**, including the ones Boltrig ships. The format
   is specified in `docs/SPEC-character-bundle.md`; this document covers what to
   do next and what the ground actually looks like.

## The service-ownership split

This is the load-bearing line, and today's work was mostly moving things across
it.

| | owner |
| --- | --- |
| camerad, presence, observer, vigil | **Boltrig services** |
| STT, TTS, the voice runtime | **Boltrig services** |
| kernel, agents, MCP tools, automations | **Boltrig** |
| camera observations, settings, enrolled face | **Boltrig kernel** |
| anchor images, LoRAs, clips, prompts, voice ids, declared keys | **the character** |
| phenotype and emotion state | **the character** |
| *when and how* the camera and automations are used | **the character** |

The test, when something is ambiguous: **if installing a second character would
duplicate it, it is infrastructure.** Two companions do not each need a camera
daemon; they do each need their own face.

Today Maya still violates this — `app.pixy.camerad`, `app.companion.observer`
and `app.companion.vigil` run as *her* launchd jobs. They are Boltrig services
that her bundle should merely declare it uses. Moving them is the largest piece
of outstanding work.

## The voice stack, as built

All loopback, all under launchd, all on the M4 because the mic, speakers and
camera are physically there — nothing crosses the network per turn.

    8911  pocket-voice   Pocket TTS + /interrupt      app.boltrig.pocket-voice
    8912  pocket-ears    Kyutai streaming STT         app.boltrig.pocket-ears
    8899  camerad        UVC camera                   app.pixy.camerad
    8910  whisper.cpp    RETIRED (.plist.disabled)

Retiring whisper dropped swap from 8.6 GB to 6.1 GB.

`~/Projects/pocket-voice/README.md` has the full contract. The three things
worth carrying in your head:

- **Pocket TTS runs at ~11.6× realtime on one or two CPU threads**, never
  touching the GPU. That headroom is why it won, not raw speed — CSM's 1.17× on
  Metal leaves nothing for camerad. CSM was separately disqualified on
  *stopping*: lowering temperature made rambling **worse** (0/5 → 4/5 cap hits),
  so the intuitive knob is backwards and there is no safe setting.
- **Barge-in is a playback problem.** Generation finishes long before a human
  could interrupt, so `/interrupt` only bites past ~10 s of audio. The mechanism
  is: stop the speaker, flush the client buffer.
- **AEC decides the playback architecture.** `getUserMedia({echoCancellation})`
  in the Tauri webview gives WebRTC AEC3 free, for headphones *and* speakers —
  but it can only cancel audio **the webview itself played**. So TTS must play
  through the page's audio graph. A native Rust play path leaves the canceller
  with no reference and echo returns in full.

`voices/*.safetensors` are gitignored and must never ship. `maya.safetensors`
is a clone of a specific person's voice.

**Unjudged:** whether Maya actually *sounds* like Maya. Speaker similarity is
Pocket TTS's weakest metric (1898 ELO, against best-in-class WER and quality),
so the deciding question scores oppositely to the ones already answered. Compare
`/tmp/maya_pocket.wav` with `/tmp/csm_maya_10s.wav` by ear.

## Working-tree audit

The previous session recorded that "a clean clone does not build". **That was
wrong, and the correction matters because it changes what is urgent.**

HEAD is self-consistent. `main.tsx` at HEAD does not import
`./characterPlugins`; that import is itself part of the uncommitted change, and
every module HEAD references is tracked. Nothing is broken right now.

What is actually there: **348 untracked and 312 modified files.** Under
`apps/worker/src`, the 49 untracked files are the **extracted halves of an
in-progress decomposition** — 9 tracked-and-modified files (`ChatView`,
`AuthGate`, `Shell`, `App`, `SettingsSurface`, `AgentProfileEditor`,
`ActionsTable`, `VoiceCall`, `main`) import 35 of them. `tsc --noEmit` passes on
the working tree.

So the risk was never that these are experiments. It is **atomicity**: each of
those 9 importers must be committed together with the modules it pulls in.
Staging one side alone is precisely what would produce the broken clone that was
mistakenly reported as already existing.

Two things the audit caught that a bulk `git add -A` would have committed:

- **An operator path in the public build.** `apps/worker/src-tauri/src/
  camera_uvc.m` described the camerad interlock in terms of
  `~/pixy-stream/camerad.py` and "the Pixy". The interlock itself is correct and
  stays — it fails closed against a wedged device whose only recovery is a
  physical replug — but the comment now describes *Boltrig's* camerad. **Fixed.**
- **`/work/`, 637 MB of smoke scratch**, never gitignored: two extracted codex
  binaries at 291 MB and 253 MB plus captured screenshots, nothing under it ever
  tracked. **Now anchored-ignored**, with the reason recorded in `.gitignore`
  beside the existing note about unanchored `build/` having silently swallowed
  eight real source components.

Scans across all 348 untracked files found **zero** references to
maya/pixy/me-lora/companion and **zero** secret-shaped strings. The tree is not
contaminated with operator data.

## What to do next

**1. Commit the decomposition, in importer-sized groups.** Nine natural commits,
each an importer plus the modules it pulls in: `chat/*` with `ChatView`,
`auth/*` with `AuthGate`, `shell/*` with `App` and `Shell`, and so on.
`characterPlugins.ts` goes with `main.tsx`. Typecheck between groups rather than
at the end — a group that fails alone is a genuine missing dependency.

**2. Move the shared services into Boltrig.** camerad, observer, vigil and
presence become first-class services with UI toggles, and their observations and
settings persist to the kernel. Boltrig ships its own camerad: the user turns it
on and picks the device, and a character declares it *would like* the camera and
is refused honestly when it is off. Consent, retention and device choice are
questions about the user's hardware, so they cannot sit in a plugin someone
might install without reading.

**3. Build Familiar and Jarvis as bundles, not just Maya.** This is the format's
proof. **Familiar is the hard case because she has no phenotype** — a format
that only fits richly-specified characters like Maya has smuggled in
assumptions. If Familiar cannot be expressed as a bundle, the format is wrong.
It also stops the spec rotting: a format exercised only by private companions
drifts silently; one the shipped characters depend on cannot.

**4. Consolidate Maya's assets under one root, and write the manifest.** Both,
not either — the manifest is the contract, the root is what makes her copyable
without archaeology. me-lora's output paths follow the move; it stays the studio
that produces *into* the bundle.

**5. Client-side barge-in in the Worker.** An energy/VAD gate at ~20–50 ms, not
the STT's `speech_start`, which was measured at **1.746 s** for speech beginning
~0.3 s in because it waits for a decoded token. Interrupt on energy, let the
transcript follow, and route TTS playback through Web Audio so AEC has its
reference.

**6. The cron jobs fail tonight.** 03:17 consolidate, 03:40 store backup and
04:05 compose all expect ollama on `:11434`, which is down because the model
moved to the M1. Repoint or disable them.

## Decisions that are settled, so do not relitigate

- **Every character is a bundle**, shipped ones included. The stock entrypoint
  imports bundles that ship; a private entrypoint imports ones that do not.
  `characterPlugins.ts`, `apps/worker/package.json` and `manifest.yaml` are all
  public graph and must not be edited to register a private character.
- **Phenotype and emotion both travel** with a bundle, but **export is
  user-gated**, because emotion is inferred from a specific user's camera.
- **The enrolled face is kernel data and is never exportable in a bundle.** This
  deliberately overrides "likeness belongs to the character", because it is not
  the character's likeness: anchor images are Maya's face, `enrolled.npz` is the
  user's — and a character is a thing you might share.
- **This M4 deployment is the operator's personal Boltrig**, not the shipped
  default. Other installs may route voice to xAI realtime, ElevenLabs or Fish
  Audio, which is why `pocket-voice` also serves `POST /v1/audio/speech`: one
  TTS adapter, varying base URL.

## See also

`docs/SPEC-character-bundle.md`, `~/Projects/pocket-voice/README.md`,
`apps/worker/src/characterPlugins.ts` for the registration rule, and
`docs/VISION-2026-08-13-app-that-bakes-a-site.md` gap 4 (the character contract)
and gap 5 (the self-hosted voice route type, which `pocket-voice` closes).
