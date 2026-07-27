# The familiar in boltrig

*Where it goes, how it appears, and what has to be true for it to be worth having.*

## The problem it solves

Codex gives each agent one of eight fixed icons, drawn from a bag. In its own screenshots
"Third architecture", "Third accessibility" and "Trial classify" all carry the same blue
pinwheel; "Test secure" gets a globe and "Test audit" a four-loop mark. The picture tells you
nothing about the agent. It is there so the row is not empty.

That is a missed opportunity rather than a bug, and the opportunity is specific: in a fleet
that runs many agents at once, **the fastest channel a human has is shape recognition**, and
it is currently spent on noise. A bar of twenty agents should be readable as "three
researchers, a reviewer and a builder" before a single label is read.

So the familiar is not an avatar with extra steps. The rule is:

> **The picture is evidence about the agent. Anything in it that is not derived from a fact
> about the agent or its run does not belong in it.**

Everything below follows from that one sentence.

## Three layers, and why they are separate

| Layer | What it says | Changes | Source |
| --- | --- | --- | --- |
| **Genotype** | what the agent IS | never | role + id, or authored config |
| **Temperament** | how it RESPONDS | per agent, rarely | `libraries/emotion/model.yaml` |
| **Phenotype** | how it FEELS now | every frame | derived from run facts |

The separation is what makes a familiar recognisable. If mood could change the body you could
not identify an agent across a bad afternoon; if identity could drift you could not identify it
across a week. A subagent orb is therefore exactly:

```
render( genotype(agent), phenotype(now) )
```

### Genotype: derived from meaning, not from bytes

The naive version hashes the agent id and indexes a table. That is Codex's bag of eight with
more entries: still arbitrary, still uninformative. Instead the **role picks the shape family**
and the **id varies only within it**:

| Role | Body | Why that shape |
| --- | --- | --- |
| orchestrator | a whole circle | the thing the others are parts of |
| researcher | an egg, slightly parted | something opening |
| reviewer | a lemniscate | two lobes weighing against each other |
| builder | a gear | |
| guardian | a shield, point down | |
| analyst | a star | many radiating directions |

An unrecognised role gets the plain circle rather than a guess. Guessing would make the
picture lie, and the whole value is that it does not.

Authored beats derived: an agent whose config carries a `familiar` block gets exactly that
body. The derivation is the fallback for agents nobody has dressed.

### Phenotype: derived from the run, never stored beside it

Boltrig has no per-agent emotion engine and should not grow one - a stored mood per agent
would be a second source of truth beside the run state that already exists. Every channel is
projected from run facts the console has already fetched: status, time in status, whether it
is blocked on a human, whether it is speaking. That is the binding derive-don't-store shape:
**a familiar cannot be calm while its run is on fire.**

The test for whether a mood channel belongs: can a user point at the screen and say "why is it
doing that", and can you answer with a fact? If the answer is "it just does that sometimes", it
is decoration and it does not go in.

## Where it goes

### 1. Chat: one seam, six surfaces

`ui/src/panels/chat/AgentAvatar.tsx` was **already** the single place an agent becomes a
picture: the fleet bar, the hover card, the activity timeline, message bubbles, the sub-run
panel and the agent sidebar all render through it. The familiar goes there and nowhere else.
Six surfaces get it at once, they cannot disagree about what an agent looks like, and a seventh
surface added tomorrow inherits it without anyone remembering to wire it up.

The initials stay as the fallback, and the status dot stays on top. That is not duplication:
the dot is the unambiguous, screen-reader-legible statement of state, and the familiar is the
glanceable one. Two channels carrying the same fact is why this ships without an accessibility
regression.

### 2. Subagents in the same chat

A parent spawning three subagents is the case the familiar is *for*, because it is the case
where names are least useful ("Third architecture", "Third observability", "Third reliability")
and shape is most useful.

- Each subagent renders at **24px inline in the parent's turn**, in the order spawned.
- Subagents inherit the parent's **role band** unless they declare their own, so a fan-out
  reads as one family working together, with the odd one out visibly odd.
- The parent's own familiar sits at 32px at the head of the turn, so the hierarchy is legible
  without indentation.
- When all subagents finish, they settle to the `done` mood together - a visible "the fan-out
  is complete" that does not require reading three summaries.

### 3. Automations

An automation is an agent that runs without anyone watching, which makes the *history* the
surface that matters rather than the live view.

- The automation's familiar is its row icon in the automations list, so a list of twenty
  scheduled jobs is scannable by kind.
- Each **run in the history** carries the familiar at that run's terminal mood: a column of
  mostly-settled bodies with one magenta one is a failure you find without reading dates.
- A **currently-firing** automation shows the running mood live, which is the only signal in
  the list that distinguishes "scheduled" from "happening right now".

### 4. Calls

Calls are where the familiar stops being an icon and becomes a presence.

- The speaking agent renders **large and centred** (160px+), driven by its own voice level
  through `uAudio` - the same swell channel the desktop familiar uses, so it pulses with the
  actual audio rather than on a timer.
- Non-speaking participants sit small around it, still identifiable.
- `phenotypeForRun({ speaking: true })` is **additive**: an agent can be speaking while
  running, while awaiting approval, or while reporting a failure, and it must still look like
  the state it is in. Speaking is not a state, it is something that happens during one.

### 5. Agent creation: the character sheet

`ui/src/panels/agents/AgentCreate.tsx`. Codex configures a custom agent as a TOML file
(`name`, `description`, `developer_instructions` required; `model`,
`model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config` optional). The form is
a face over those exact keys, not a parallel invention - a form whose field is called "effort"
and whose file key is `model_reasoning_effort` is a translation layer, and translation layers
drift.

It adds the two things a text file cannot:

- **Consequence at the point of choosing.** `read-only` is not a dropdown value, it is the
  sentence "this agent cannot change your files". The default is the safe end of the scale,
  because a form that defaults to `workspace-write` makes that decision silently, every time,
  for every agent anyone ever creates.
- **A face before the first run.** The familiar is derived the moment a role is typed. Three
  ways to get a body: **derive** (do nothing), **roll** (stays inside the role band, so a
  reviewer rolled forty times is still visibly a reviewer), **author** (14 real shader genes,
  previewed by the same shader the chat renders).

The designer shows the body at 196px *and* at 40/28/20px simultaneously. A body that reads
beautifully large and turns to mush at 24px has failed at the size it will actually be seen,
and the only honest way to know is to show both at once.

## How it renders

One WebGL2 context for the whole page, blitting into per-avatar 2D canvases.

The obvious build gives each avatar its own context. It works with three agents and then falls
over: browsers cap live WebGL contexts near 16, and past the cap they silently kill the oldest
one - so a fleet bar would blank its first agents as you scrolled, looking like a rendering bug
and actually being an architecture bug.

The shader is a 107KB raymarcher built for a full-screen wallpaper, which sounds alarming for
an avatar and is not: cost is per pixel. Measured, 520x520 runs at 1.38 ms; a 40px familiar is
about 1/170th of that area.

If WebGL2 is missing or the shader fails to link, `familiarAvailable()` goes false and every
caller falls back to initials. A familiar is how you recognise an agent, so the failure mode
must be "you get the old avatar", never "you get a hole where the agent used to be".

## Three defects worth recording, because each was invisible to a passing test

**The uniform arrived and nothing happened.** The first cut changed only `dScreen`, the
silhouette. It compiled, linked, and the uniform demonstrably reached the shader - and a star
rendered as a star-shaped *wire around a perfectly circular ball*, because the interior never
consulted the genotype. Fixed at the definition of the ray origin, so the gate, the lit normal
and the interior all follow from one definition of "how far out am I".

**Every avatar was an opaque rectangle.** The shader's `uPresence` composes
`a = mix(cover, 1.0, ...)`; at 1 that is 1 for every pixel. Correct for a wallpaper, and in a
chat list a hard box behind every agent. Measured: alpha 255 across all 102,400 pixels.
`uPresence 0` is worse - the being withdraws, alpha 0, an invisible avatar. The right mode is
`uFill + uCompanion`, "show the full being, then feather the porthole edge", with `uAperture`
open. Even then the feather had not finished by the canvas corner at `uFitScale 0.42` (corner
alpha 71 of 255, a soft square around every star); 0.34 gets it to 0 with the body still
covering 55% of the frame.

**A claim in a comment that the behaviour did not back.** `awaiting_approval` was documented as
"impossible to miss" and measured 4% brighter than `running`. Raised to about 11%. An
intermediate version also claimed it was the *stillest* body; measured over 0.7s it changed
0.35 against running's 0.36 - no effect at all, because the interior's churn comes from the
shader's own time term and not from arousal. The claim was removed rather than left standing.

The pattern in all three: **compiling is not rendering, and rendering is not looking.**
`ui/src/familiar/preview.tsx` exists so that looking is cheap.

## What is not built

- The genotype reaches the silhouette and the body volume. The remaining ~47 interior
  constants (silk band edges, mote counts, ember placement) are still hardcoded.
- A fully parted body has no centre, so no nucleus, so almost no light - measured at 5.9% lit.
  The reviewer band is deliberately held on the near side of the part. A parted genotype needs
  a nucleus per lobe, which is interior work, not silhouette work.
- The familiar is wired into `AgentAvatar` (chat, and therefore six surfaces). Automations,
  calls and the subagent inline treatment are designed here and not yet built.
- `familiar.frag` now exists in two repos (`beelink-desktop/familiar` and `boltrig/ui/src`).
  That copy will drift and needs a single source before it does.
