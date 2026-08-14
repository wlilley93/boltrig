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

  **What "the kernel governs" does and does not mean, as built (2026-08-13).**
  The kernel governs *consent*: `GET /v1/sensing/capability` answers from the
  user's switches and refuses with a reason. It does **not** enforce the
  declaration, because it is never told which character is asking — the request
  carries the user's session and names no bundle. So an undeclared character
  asking with the camera on is told `granted`. Declaration is honoured by the
  Stage, which asks only for what `wantsSensing` lists; that is a constraint on
  the Stage, not a boundary, since a character add-in shares its JavaScript
  realm. No imagery is at stake — the endpoint returns a decision and never a
  frame — but do not read the sentence above as an enforced check. What closing
  it needs is in `SERVICES-INTO-BOLTRIG-2026-08-13.md` §11 and the module
  docstring of `boltrig/kernel/sensing_capability.py`.
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

    required   id, display name, type
    strongly recommended   prompts, anchor images (companion only), a voice
               (self-hosted OR fallback ids)
    optional   visual LoRA, voice LoRA, example clips, capability usage,
               nightly distillation, key set, phenotype, emotion

**`prompts` was required here and that was WRONG** — corrected 2026-08-13 when
Familiar was actually built as a bundle. **Neither shipped character has
prompts.** Familiar is a shader with no persona text at all, so a format
requiring prompts cannot express the character Boltrig ships by default.

This is exactly the failure the "build Familiar first" rule existed to catch: a
required field that felt obvious because Maya has one. `type` takes its place in
the required set, because a bundle that does not say whether it is a shader or a
companion cannot be rendered at all.

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

### The daemon is always Boltrig's, whoever is watching

Settled 2026-08-13, and it is the decision that makes the rest of the format
safe.

Jarvis watching, Maya watching, Bella watching — **same camerad, same
observation loop, same presence, same retention and quiet-hours and stop-gesture
policy**. Nothing about the *watching* is character-specific. What varies is the
prompt the frame is asked about and where the interpretation lands.

    Boltrig ships    camerad, the observation loop, presence, the
                     retention/quiet-hours/gesture policy, the kernel it
                     writes observations to
    the bundle       the prompt it asks with, what to do with the result,
    brings           which observations matter, where its diary lives

**A bundle therefore never ships executable code — only configuration.** That is
not a restriction we are accepting reluctantly; it is the point. A character is
a thing you might download from someone else, and a downloaded character must
never be able to run a process that watches you through your camera or reads
your enrolled face. It can only ask a question through a daemon *you* own and
*you* can toggle off. The blast radius of installing a stranger's character
drops to "it has bad taste in prompts".

This also resolves `observe.py`, which today fuses two jobs and is the reason
ownership felt ambiguous. The seam runs through the middle of one file: frame
pull, change detection, `QUIET_START`/`QUIET_END`, `DARK_MEAN`, the stop-gesture
pause and `RETENTION_H` are **user hardware policy** and go to Boltrig — the
spec already says consent, retention and device choice cannot sit in a plugin
someone might install without reading. The `PROMPT`, which literally opens *"You
are the eyes of a companion in the room"*, and the diary it appends to are
**character** and go to the bundle.

Presence goes to Boltrig whole. It reads `enrolled.npz`, which is already kernel
data; a bundle-owned service reading kernel-owned biometrics is the wrong way
round. And "is the user in the room" is a fact about the room — a second
character does not get a different answer.

### Phenotype and emotion are manifest fields, not machinery

They are almost certainly **JSON in the manifest**, not a subsystem: the
character declares whether it has a phenotype and an emotional model at all, and
carries its current state as data alongside its prompts.

This is what lets **Familiar** exist. She has no phenotype and nothing to
interpret, so she simply omits the field — and the observation loop carries on
serving whoever does bring one. A format where phenotype were machinery, or
where the camera came *with* the character, could not express her at all. She
remains the format's proof: if Familiar cannot be a bundle, the format is wrong.

### The manifest declares what a character IS: shader or companion

The field that makes the format cohere. A character's visual is one of two
kinds, and the manifest says which:

    type: shader      the character IS a shader -- Familiar, Jarvis.
                      The bundle brings the fragment shader and its uniforms.
    type: companion   the character is a rendered likeness -- Maya, Bella.
                      The bundle brings a .frame.mp4 and its manifest.

**The canvas renders both.** It is one surface with two sources, not two
subsystems — which is why `type` is a flag and not a fork in the architecture.
A shader character has no `.frame.mp4`; a companion character has no fragment
shader; neither is a degraded case of the other.

This is what `phenotype` hangs off. A `shader` character has nothing to have a
phenotype *of*, which is why Familiar omits the field rather than carrying an
empty one — and why she remains the format's proof.

**FrameGraph and the `.frame.mp4` container are proprietary.** They are the
basis of every companion-type character's visual, so the format depends on
them, but they are not part of what Boltrig ships openly and must not be
described as though they were. A `type: shader` character needs none of it,
which keeps the public build free of the dependency: Boltrig ships Familiar and
Jarvis, and both are shaders.

### Live direction, and how a restricted scene is reached

A `companion` character is not played back; it is **directed**. The conversation
drives segment selection live — the director picks the next segment as the turn
unfolds, which is exactly why navigation is a seek within one file rather than a
clip load.

A bundle may carry a restricted scene as an **optional** asset. The gating rule:

    PERMISSION   a user setting, in the KERNEL. Binary, explicit, revocable.
                 Never inferred, never earned.
    SELECTION    emotional state, in the character. Chooses WHICH segment
                 within what permission already allows.

**Emotion selects; it never unlocks.** Two reasons, and both are load-bearing.
Emotional state is *inferred* — from a camera and a conversation — so making it
the thing that opens a permission boundary puts a noisy signal in charge of
consent. And content that opens as emotional state improves is a reward for
pleasing the character: a mechanic, not a companion. Permission is a question
the user answers once, in settings, in the same place they toggle the camera.

Check permission at **selection time**, never cache it into director state, so
revoking it takes effect on the next turn rather than the next restart.

Structurally this is a second `.frame.mp4`, not extra chapters in the first —
one file is one character in one scene, and a restricted scene must be able to
be *absent* from a bundle entirely. The cost is that moving between scenes is a
source swap rather than a seek, which is the one operation FrameGraph exists to
avoid. So the player **preloads the second file when permission is on**, paying
the swap ahead of the transition instead of during it.

A `shader` character has none of this. The axis exists only where there is a
rendered likeness.

### How direction reaches the video: hold, then schedule

**The holding loop is the default state, not a fallback.** The character is
always in some loop; direction changes swap which one. Nothing ever stalls and
nothing ever cuts, because there is no state in which the player has nothing
legal to show.

Every segment is therefore one of two kinds, and the `.frame.mp4` manifest must
say which:

    loop         seamless, repeats indefinitely (idle, listening, talk)
    transition   one-shot, carries state A -> state B

**The director never interrupts mid-segment.** It sets a *target* state; the
player finishes the current loop iteration and then takes the transition. That
is the whole reason it reads as directed rather than cut. Loop length is
therefore the responsiveness dial — a 4 s idle loop means up to 4 s of latency
to a change, so bake loops short. Segment boundaries are already keyframes (each
source clip opens on an IDR and concat preserves it), so short loops cost
nothing but bake time.

**Speech is the clock, and this is the part worth getting right.** TTS generates
at ~11.6x realtime, so **the audio is finished before playback begins and its
duration is known up front**. The director does not have to react to speech as
it happens — it can schedule the whole shape of the turn in advance: how many
talk-loop iterations fit, and exactly when to take the exit transition so it
lands on the last word. Reacting would always be a frame late; scheduling cannot
be.

**What the model emits is a small enum, not video commands.** Alongside its
text it returns a direction drawn from the states the bundle *declares* —
`idle`, `talk`, `listening`, `nod`, `smile` for the current conversation bake.
Constrained decoding keeps it inside that set, the same trick already used
elsewhere in this estate. The bundle declares the vocabulary; the model chooses
from it; the player owns the machinery. Configuration, not code — consistent
with the daemon decision above.

If no direction arrives, the current loop simply continues. A slow model
degrades to a character who is quietly present, which is the correct failure.

Ownership follows the established line: **loop/transition machinery is the
canvas, so Boltrig.** The available directions, and when each is appropriate,
are declared by the **bundle**. Emotional state selects among them, within what
permission already allows.

### What the public build actually ships

Stated precisely, because a looser version of this is easy to believe and wrong.

    ships publicly    the canvas, the shader source, Familiar and Jarvis,
                      and a visible, EMPTY characterPlugins.ts
    private build     the companion source (the .frame.mp4 reader and
    adds              renderer), the companion character, and its assets

**Nothing is hidden.** `characterPlugins.ts` ships visible and empty, carrying a
comment stating exactly what may go in it. The exclusivity comes from
**entrypoint separation**, not obscurity: the stock entrypoint registers what
ships, a private entrypoint registers what does not.

Keep two things apart that are easy to conflate:

- **The entrypoint rule is the technical guarantee.** It is why no companion can
  reach a public build even by accident, and why the rule is "explicit imports,
  never a glob" — Vite emits every matched module as a production chunk, so a
  glob would ship whatever happened to be installed.
- **The private `.frame.mp4` pipeline is a business moat.** Real, but not
  load-bearing. If someone else built one tomorrow nothing about this design
  breaks; they would run their own private distribution. Relying on the pipeline
  being rare would be the fragile version of a guarantee the entrypoint rule
  already gives for free.

### The canvas is one surface with a source interface

This resolves the tension between "one canvas, two sources" and "`.frame.mp4` is
proprietary". Taken naively, one canvas that renders both would put the
container reader — the whole trick is an 80-line `uuid`-box parse — into the
public build, publishing the format.

So: the canvas ships as a single surface with a **source interface**. The shader
source ships with it. **The companion source registers exactly the way a
character does**, which means the private entrypoint adds the character *and*
its renderer together.

The result is one canvas rather than two subsystems, a public build with no
proprietary reader in it, and `type: companion` declared in the format but
unimplemented publicly. Everything companion-shaped — reader, renderer,
character, assets — arrives as one private unit.

**Decide this before anyone implements the canvas.** Building the companion path
into the public renderer first and extracting it later means the format has
already leaked.

## Decisions taken 2026-08-14

### The bundle on disk is a VIEW, not an artefact — measured

The three gaps Maya's consolidation exposed were re-examined. One is closed, one
is misdescribed, and the third is bigger than it was written up as.

**`Maya.greeting.frame.mp4` needs no new slot — greeting folds into the bake.**
`companionVisual` has `frame` plus an optional `restrictedScene`, and greeting
looked like it wanted a third. It does not, because a `.frame.mp4` is *already*
a multi-region graph: every clip the player can reach is laid on one track with
chapters at the boundaries and the whole state machine in a `uuid` box. A
greeting is an entry region of that graph. Adding a `scenes[]` list would put a
second graph-selector *above* a format whose entire purpose is that one file
holds the whole reachable space — two mechanisms for one job.

`restrictedScene` stays a separate slot, and the reason is worth stating because
it is not "greeting is less important": it is a **distribution** boundary, not a
graph boundary. A user without permission should not have the bytes at all, so
those frames must be separately shippable. Unrestricted scenes have no such
requirement, so they belong in one bake. The rule is: **a slot exists only where
a permission boundary exists.**

**`behaviour/camera.json` is NOT two sources of truth.** It is a *symlink* to
`companion-observer/characters/maya.json` — one file, resolved via
`Path.resolve()`. The duplication the earlier note describes does not exist, and
a parity test written to catch drift between them was deleted after mutation
testing showed it could never fail: it compared a file with itself.

**But the symlink is the real finding.** Maya's bundle contains **21 symlinks**,
all relative, all escaping the bundle root into `gen-pipeline`, `maya-remote`
and `companion-observer` — `library`, `lines`, `prompts/persona.md`,
`data/character.db`, `identity/visual-lora/*`, `identity/example-clips/*`.
`~/Projects/character-bundles` is not a git repository, so there is no history
either. Measured by packing it the way anyone would:

    tar -cf  (no --dereference), unpack elsewhere  ->  21 dangling links
    tar -chf (--dereference),    unpack elsewhere  ->  18 dangling links

`--dereference` does **not** rescue it: 18 remain, because there are symlinks
nested inside the directories it followed. So the spec's central claim — that a
character *brings* its data — is not true of the bundle as it exists on disk. It
brings references to one operator's home directory, and it is assembled in place
rather than built.

This does not invalidate the format; the manifest, the `type` split and the
capability declarations are all real. It reclassifies the on-disk layout as a
**development view**, and makes "Bundle format on disk" below the question that
has to be answered before any bundle moves between machines. Whatever answer is
chosen needs an export step that resolves links recursively and a check that
refuses to publish a bundle containing a path outside its own root.

## Open questions

- **Bundle format on disk** — directory with a manifest, or an archive? *Now
  load-bearing rather than cosmetic: see the 2026-08-14 decision above. Any
  answer needs a recursive-dereference export and a refusal on out-of-root
  paths, or a bundle "ships" 21 links to nothing.*
- **`emotion` is still unset** — the schema wants a model name that the bound
  canvas source declares it supports, and no companion source is registered yet.
  Blocked on the private companion renderer, not on a decision.
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
