# The character bundle

Stated 2026-08-13. A character is a **portable bundle of data plus declared
behaviour**, buildable from a checklist and installable into any Boltrig. This
records the shape so characters stop being bespoke wiring and become a package
format.

## The rule that shapes everything

From `apps/worker/src/characterPlugins.ts`, which is already correct:

> The public build deliberately adds nothing here: Boltrig ships Familiar and
> Jarvis, and no operator- or developer-owned companion code. A separately
> reviewed private distribution can add explicit imports in **its own
> entrypoint**; it must not modify this stock module or the public package graph.

So a character bundle is installed by a **private entrypoint**, never by editing
`characterPlugins.ts`, `apps/worker/package.json` or `manifest.yaml`. Those three
are public graph. Wiring Maya into them — as was attempted on 2026-08-13 — puts
operator-owned companion code into the shipped build, which is the exact failure
the module was written to prevent.

## A character BRINGS data; it does not OWN services

This is the load-bearing distinction.

| | owner |
| --- | --- |
| camera daemon, presence, observer, vigil | **Boltrig services** |
| STT, TTS, the voice runtime | **Boltrig services** |
| kernel, agents, MCP tools, automations engine | **Boltrig** |
| camera observations and settings | **Boltrig kernel** |
| anchor images, LoRAs, clips, prompts, voice ids, keys | **the character** |
| **phenotype and emotion state** | **the character** |
| *when and how* the camera/automations are used | **the character** |

A character is **told to make use of** the camera; it does not carry a camera
daemon. Today Maya violates this — `app.pixy.camerad`, `app.companion.observer`
and `app.companion.vigil` are hers, running as her services. They are
infrastructure and belong to Boltrig, with her bundle declaring that she uses
them.

The test: if a second character were installed, would it have to duplicate this?
If yes, it is a service and belongs to Boltrig.

### The camera is Boltrig's, and the user controls it

**Boltrig ships its own camerad.** It is a first-class service with UI: the user
turns it on and off and picks which camera, and its observations and settings
persist to the **kernel**. It is not something a character installs, and no
character may assume it is running — a bundle declares that it *would like* to
use the camera, and gets refused honestly when the user has it off.

This also means the camera is governed in one place. Consent, retention and
device selection are questions about the user's hardware, not about a companion,
so they cannot live in a plugin that a user might install without reading.

### Phenotype and emotion belong to the character

They persist to the **plugin**, not the kernel, because they are not facts about
the user or the machine — they are what this particular character looks like and
how it currently feels. This is already the established position: Familiar has no
phenotype at all, while Jarvis reads one and has a persona, which is why the
choice of body is non-cosmetic rather than a skin.

Note the direction of flow, because it is the interesting part:

    camera (Boltrig) --observations--> character --> phenotype/emotion (plugin)

Boltrig captures **what was seen**; the character decides **what that means for
it**. Two characters watching the same frame may legitimately end up in different
emotional states, and neither is wrong — so the derived state cannot live in the
kernel beside the observation that produced it.

**Open, and genuinely unresolved:** does emotion state travel when a bundle moves
to another Boltrig? Continuity argues yes — a companion that forgets its mood on
reinstall is diminished. But that state was derived from *this* user's camera, so
carrying it elsewhere exports an inference about a person from a device they
control. A defensible split is that phenotype travels and emotion state does not,
but it should be decided deliberately rather than by whatever the serialiser
happens to do.

## The bundle

Nothing here constrains where the assets come from. In this estate me-lora
produces the LoRAs and the voice corpus, but that is a fact about our pipeline,
not part of the format — a character built entirely by hand is equally valid.

### Identity and likeness

- **anchor images** — 3, at different angles. The canonical likeness.
- **visual LoRA** — trained on the anchor images.
- **example clips** — reference renders showing the character correct.

### Voice

- **voice LoRA / reference audio** — for self-hosted synthesis.
- **fallback voice ids** — e.g. Fish and ElevenLabs ids for Maya. These are what
  make a bundle portable: an install with no local TTS still has a voice. The
  self-hosted route is preferred where available, not required.

### Behaviour

- **prompts** — persona, system prompt, style.
- **capability usage** — *when and how* declared kernel capabilities are used:
  which camera events matter, what to do with presence, which automations to
  register. Declaration only; the character requests, the kernel governs.
- **nightly LoRA distillation config** — the per-character training loop lives
  with the character, since what it trains on is hers.

### Credentials

- **the set of API keys it wishes to use** — declared by the bundle, supplied by
  the operator. A character says which providers it wants; it never ships keys.
  Never commit a populated key set.

## Optionality is the point

Most fields are optional, and that is deliberate: a character with only prompts
and a fallback voice id is a valid character. The checklist below degrades
rather than fails, so a bundle can be built up incrementally.

    required   id, display name, prompts
    strongly recommended   anchor images, a voice (self-hosted OR fallback ids)
    optional   visual LoRA, voice LoRA, example clips, capability usage,
               nightly distillation, key set

An install must refuse gracefully when an optional asset is absent — no visual
LoRA means no generated likeness, not a broken character. This mirrors the
existing rule that a modality route may not select a model lacking that
modality: absent capability must be visible, never silently substituted.

## Why this is worth having

1. **Portability.** A character moves between Boltrigs as data.
2. **A checklist.** Building a new character stops being archaeology.
3. **Private by construction.** Bundles live outside the public graph, so
   Familiar and Jarvis remain the only shipped characters without anyone
   policing diffs.
4. **It makes consolidation tractable.** "What is Maya" gets a concrete answer,
   and everything not on the list is Boltrig's.

## Decisions taken 2026-08-13

### Familiar and Jarvis are bundles too

**Every character is a bundle, including the shipped ones.** Familiar and Jarvis
get built exactly the way Maya is — same format, same checklist, same loader.
They are not a privileged built-in path with plugins bolted alongside.

This resolves the awkwardness in `characterPlugins.ts` rather than living with
it. The mechanism becomes uniform: the stock entrypoint imports the bundles that
**ship** (Familiar, Jarvis), and a private entrypoint imports bundles that do
not (Maya). The rule about not touching the public graph survives unchanged, but
it is now a statement about *which bundles are listed where*, not about two
different kinds of character.

It also makes the format honest. A bundle spec exercised only by private
companions would drift and rot; one that Familiar and Jarvis depend on cannot.
And it gives the spec its proof: **if Familiar cannot be expressed as a bundle,
the bundle format is wrong.** Familiar is the hard case precisely because it has
no phenotype — a format that only fits richly-specified characters like Maya has
smuggled in assumptions.

### Assets: consolidate AND manifest

Both, not either. Maya's assets physically consolidate under one bundle root, and
the manifest names them. The manifest is the contract; the root is what makes her
copyable without archaeology. me-lora's output paths follow the move — it remains
the studio that *produces* into the bundle, rather than a place assets live.

### Emotion travels, gated at export

Phenotype **and** emotion state travel with a bundle, so a character keeps its
continuity across a reinstall or a move. Because emotion is inferred from a
specific user's camera, **export is user-gated**: carrying it is a deliberate act
with a consent surface, not a silent side effect of copying a directory.

### The enrolled face is kernel data, never bundle data

`~/pixy-stream/identity/` holds biometric data about the **user**, so it moves to
the kernel under the same consent and retention rules as camera observations. It
must never be exportable inside a character bundle — a character is a thing you
might share, and a shared character must not carry someone's face.

Note this is the one place the "likeness belongs to the character" rule is
deliberately overridden, and the reason is that it is not the *character's*
likeness. Anchor images are Maya's face. `enrolled.npz` is yours.

## Open questions

- **Bundle format on disk** — directory with a manifest, or an archive?
- **How the private entrypoint is selected at build time** — env var, separate
  Vite entry, or a private repo that vendors the public one?
- **Where bundle assets live at runtime.** Maya's are spread across
  `~/Projects/gen-pipeline/store` (22G) and `~/Projects/boltrig-companion`; a
  bundle implies one root, and the consolidation above is what creates it.

(*The face-enrolment question that stood here is settled — see "The enrolled
face is kernel data, never bundle data" above.*)

## See also

`docs/VISION-2026-08-13-app-that-bakes-a-site.md` gap 4 (the character contract),
and `apps/worker/src/characterPlugins.ts` for the registration rule.
