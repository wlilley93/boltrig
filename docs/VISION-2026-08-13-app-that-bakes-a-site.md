# The app that bakes a site

Stated 2026-08-13. This records a product-shape decision and the gap between it
and the tree as it stands, so the work can start from what exists rather than
from a blank page.

## The decision

> "Actually, the more I'm saying out loud, I don't think this is a site at all —
> it's a tauri app that bakes a site. That's the only way to get all the good
> stuff."

The **Tauri app is the product**. It runs on the user's own computer as both an
app and a daemon, so the agent is always present. The website is a build target
of the same UI, kept for testing and for distributing the app — not a second
implementation and not where the work happens.

Decision 0027 makes the execution split explicit: the shared UI runs a hosted
cloud agent in the browser and a local Codex/Bash agent in Tauri. Neither mode
silently falls back to the other.

The reason is capability, not preference. A browser cannot hold a camera open,
run a daemon, reach a model on the user's LAN, or keep a companion resident.
Everything that makes the product worth having needs the user's machine.

`dev.boltrig.io` stays up to exercise the UI. The download lives there.

## What the product is

The user talks to one main agent — **Familiar by default, Jarvis by a system
setting**. Behind it, a fleet of agents does work through the kernel and MCP
tools. Interaction is a text chat or a voice chat, and voice chat accepts typed
text too: they are the same conversation, not two modes.

The user brings their own keys, **including models they run themselves**. Text
is the minimum; images and voice are added the same way. If the app has a
webcam, the agent can see the user and react.

Users add their own tools and MCP servers. The automations tab schedules work on
a cron. The channel gateway makes agents contactable over messaging and email.

## What already exists — start here, do not rebuild

The tree is much closer to this than a reading of the vision suggests.

| Vision element | Where it lives | State |
| --- | --- | --- |
| Character registry, uniform formulation | `apps/worker/src/character.ts` | **Done** |
| Familiar as default | `DEFAULT_CHARACTER = "familiar"` | **Done** |
| Private characters that do not ship | `apps/worker/src/characterPlugins.ts` | **Done** |
| BYO keys UI | `apps/worker/src/components/AiKeyManagement.tsx` | Exists |
| Channels over messaging/email | `services/channel_gateway/` | Exists |
| Settings (models, autonomy, spend, knowledge…) | `apps/worker/src/settingsSections.ts` | Exists |
| Familiar / Jarvis bodies | `apps/worker/src/components/{familiar,jarvis}` | Exists |
| Camera capture | `apps/worker/src-tauri/src/camera_uvc.m` | Exists |
| Web build target | `apps/worker` — `vite build` | **Verified: 978ms** |
| Automations with cron | `apps/worker/src/components/AutomationView.tsx` | Exists |
| Voice call UI | `apps/worker/src/components/VoiceCall.tsx` | Exists |

The character system in particular already implements the last thing in the
brief, and implements it well. `characterPlugins.ts` is the join point for
characters beyond the ones Boltrig ships, with a deliberate rule:

> EXPLICIT IMPORTS ONLY, NEVER A DIRECTORY GLOB. Vite emits every matched module
> as a production chunk even when the surrounding branch is DEV-only, so a glob
> would ship every installed companion to every user.

So "my plugins have a slant for personal use, they don't ship, but a character
should always be formulated the same way" is not future work — it is the
existing contract. Bella and Maya are plugin registrations in a private
distribution entrypoint. A future build-your-own is adding a UI over a registry
that already accepts open ids.

**The web target is also closer than expected.** `apps/worker` builds with plain
`vite build`, exactly one file imports `@tauri-apps/api`, and `desktop.ts`
already carries a `runtime: "desktop" | "web"` discriminator with a
`desktop_runtime_required` refusal path. The UI was written runtime-aware. Baking
a site is mostly proving the web branch degrades honestly, not porting anything.

## The real gaps

1. **`site/` is not the Boltrig site.** It is `next16-claude-starter`, an
   unrelated template. There is no `dev.boltrig.io` build today. The site should
   become a thin shell that ships the `apps/worker` web build plus a download
   page — not a second UI.

2. **No daemon.** The app is quittable: no tray item, no login item, no
   LaunchAgent. "Always present" is unimplemented, and it blocks moving camerad
   ownership into the Worker. This is a posture decision as much as a technical
   one — see the open question below.

3. ~~No automations tab.~~ **Wrong — it exists.** `AutomationView.tsx` builds as
   its own 91.86 kB chunk and carries 154 cron/schedule references. Corrected on
   first inspection: the vision brief listed automations as missing, and so did
   the first draft of this document. Check the build output before believing a
   gap.

4. **CLOSED by codex, 2026-08-13.** "Familiar/Jarvis selection now works in Chat
   and Voice Call" — the choice reaches the agent, not just the Stage, which is
   what the vision required. Phenotype polling runs only when the selected
   character needs it. Plugin registration is immutable and isolated from broken
   subscribers, and the public build was verified to ship exactly Familiar and
   Jarvis with no personal companion code. Verified at 725/725 worker tests,
   3,770 Python tests against real PostgreSQL, 407/407 invariants. `character.ts` is explicit: "this
   value is not sent in Chat requests and does not alter response prose or
   dispatch." The vision — talk to Familiar, or to Jarvis — implies the choice
   reaches the agent. Note this pulls against an existing decision that emotion
   is per-character (Familiar has no phenotype; Jarvis reads one and has a
   persona), so the boundary needs settling deliberately rather than by drift.

5. **The route type now EXISTS — `~/Projects/pocket-voice` closes this gap.**
   Corrected later on 2026-08-13; everything from "CLOSED by codex" down is
   superseded on its central claim. It concludes that *"self-hosted voice has no
   route type yet"* and that the operator's stack *"has no runtime contract to
   author against"*. Both were true only of the stack it names. That stack is
   retired: the M4 now runs **pocket-voice on `:8911`**
   (`app.boltrig.pocket-voice`) and **pocket-ears on `:8912`**
   (`app.boltrig.pocket-ears`), and pocket-voice serves **`POST
   /v1/audio/speech`** — OpenAI's speech shape, which ElevenLabs, Fish Audio and
   the rest already mirror. So boltrig carries **one TTS adapter and varies the
   base URL**, the same trick ollama's OpenAI-compatible endpoint already
   supplies for LLMs, rather than one adapter per vendor. Self-hosted is
   therefore **a route type among several**, not the architecture, and voice does
   not ship "XAI realtime only". Verified on the M4: `GET :8911/healthz` returns
   `{"ok":true,"loaded":true,...}` and `POST :8911/v1/audio/speech` returns
   `200`, while `:8910` (whisper) refuses — its plist is parked `.disabled`. The
   richer `/speak/stream` and `/interrupt` endpoints are the ones OpenAI's shape
   cannot express, and they are what barge-in needs. Full contract:
   `~/Projects/pocket-voice/README.md`. What is genuinely still open is narrower
   than a missing contract: **Voice Settings must grow a base-URL/self-hosted
   route form** to author against it, and STT has no OpenAI-shaped equivalent
   here.

   Superseded note follows.

   **CLOSED by codex, 2026-08-13** — Voice Settings now exists and authors XAI
   realtime routes; unsupported Omnivoice/ElevenLabs claims were removed. **But
   this collides with the operator's own deployment below**, which uses OmniVoice
   on the M4 for TTS. The vision says users bring their own keys "including
   models they themselves are running"; a Voice Settings that only authors XAI
   realtime routes cannot express that stack — not the operator's, and not a
   user's local Piper or Kokoro either. Removing the unsupported claims was
   right; the gap it exposes is that self-hosted voice has no route type yet.
   **Confirmed by codex, 2026-08-13**, in its own words: "Fish Audio, ElevenLabs,
   Omnivoice and STT/TTS authoring remain intentionally unavailable until their
   runtime contracts exist; the UI no longer implies otherwise." That is the
   right call -- an honest UI beats one that offers routes it cannot honour. It
   also means **this gap is now precisely defined**: the operator's M4 voice
   stack (OmniVoice TTS, whisper STT) has no runtime contract to author against,
   so the deployment below is not yet expressible in the product. Self-hosted
   voice needs a route type; it is not a settings-screen omission.

   Original note follows.

   ~~Voice is absent from SETTINGS, but not from the app.~~ `VoiceCall.tsx` and
   `VoiceCall.css` exist; `settingsSections.ts` has **zero** voice/TTS/STT
   references. So a voice call can happen but cannot be configured — which is
   precisely the gap, and a narrower one than "voice is absent". STT and TTS are
   opposite directions and must not become one toggle.

6. **CLOSED by codex, 2026-08-13.** Per-agent modality routes are now
   approval-bound and governed, in `boltrig/config/capability_model_routes.py`;
   JSONB route storage and reference tracking were repaired including legacy
   rows. Multimodal routes can no longer select a model missing a required
   modality — the failure mode that would have made a "vision" route silently
   text-only.

## The operator's own deployment

Not the shipped default — a worked example of BYO keys pointing at self-hosted
models, and the configuration this box actually runs.

    text + vision   M1    ollama, qwen3vl-abliterated (Qwen3-VL-30B-A3B, MoE,
                          vision, abliterated) — 17.4 tok/s, tool calling verified
    voice           M4    pocket-voice :8911 — Pocket TTS, plus POST
                          /v1/audio/speech (OpenAI shape) and /interrupt
                    M4    pocket-ears :8912 — Kyutai streaming STT
                          both loopback, both under launchd. whisper-server :8910
                          and OmniVoice are RETIRED (plists parked .disabled);
                          Pocket TTS is measured at 9.83x realtime on one or two
                          CPU threads, 137ms to first audio, and never touches
                          the GPU — see pocket-voice/README.md
    camera          M4    EMEET Pixy via camerad :8899 (physically attached)
    build/host      beelink  only x86_64 box; builds and dev servers
    video           Salad RTX 3090, on demand, for FrameGraph

Two constraints this topology creates:

- **The camera cannot move.** camerad and the Pixy are on the M4, and
  `camera_uvc.m` is AVFoundation. Whichever machine holds the webcam is where the
  Worker's camera path must run. The M4 is the physical-I/O box — microphone,
  speakers, camera — because that is where the user is.
- **Latency is a real risk for voice.** STT and TTS are on the M4 while the model
  is on the M1, over WiFi at ~21ms. Measure a full turn (speech in → model →
  speech out) before assuming the split is acceptable; if it is not, the model
  moves or the voice stack does.

## Order of work

1. ~~Prove the web build.~~ **Done — `vite build` succeeds in 978ms**, emitting
   ChatView, AutomationView, ChannelsView, characters and BuildView as chunks.
   What remains is walking that build with `runtime: "web"` to confirm every
   desktop-only path refuses honestly instead of appearing to work.
2. **Replace `site/`** with a shell that serves that build plus a download page.
3. **Settle the character contract** (gap 4) before building on top of it.
4. **Daemon posture** (gap 2), which unblocks camerad ownership.
5. **Automations tab** (gap 3), then **voice settings** (gap 5) and the
   `agent_model_routes` normalisation (gap 6).

Steps 1 and 2 are mechanical. Step 3 is a decision. Do not start 4 before 3.
