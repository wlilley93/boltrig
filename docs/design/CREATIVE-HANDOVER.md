# Boltrig - Creative Handover

> The north star that sits *above* the specs. `DESIGN-SYSTEM.md` says what the tokens are,
> `COMPONENT-SPECS.md` says how the parts are built, `DESIGN-DECISIONS.md` says what is locked.
> This says **what it must feel like**, and why. Read it first, then build to the others.
> Written 2026-07-21. Voice, not law. Where it meets a locked decision, the locked decision wins.

---

## 0. The one sentence

**Boltrig is the instrument that makes many minds behave like one.**

Codex, any approved model behind it, a fleet of native subagents, a workflow of a hundred steps,
a webhook that fires at 3am - all of it flows through a single governed kernel and comes out the
other side as *one legible act you can watch, stop, and trust*. Every other agent product shows
you a chat box and asks you to have faith. Boltrig shows you the **glass box around autonomous
power**. The UI's entire job is to make that box feel reassuring and alive, never bureaucratic,
never a toy flowchart, never a SaaS dashboard with a robot bolted on.

The name is the brief: **bolt** (electric, fast, a secure fastening) + **rig** (an apparatus you
operate, an audio-lighting-truss you run a show from). A charged graphite instrument. Mission
control for a firm that thinks.

---

## 1. What a person must feel (the emotional spec)

Design is a feeling before it is a layout. In priority order, a Boltrig user must feel:

1. **In command, not in the loop.** The agents do the work alone. You are the operator at the
   desk, not the bottleneck in the chain. The UI never makes you feel like you are babysitting a
   process; it makes you feel like you are conducting one and could take the stick at any second.
2. **Sightlines into everything.** Nothing important happens off-screen. A run you started is
   always traceable from anywhere. A subagent three levels deep is one click from being watched.
   The unforgivable sin is a spinner that hides work. The current is always visible in the wire.
3. **Safe because it is *shown*, not because it is *claimed*.** "Governed" is not a badge. It is
   a moment: the run reaches a high-consequence verb, the node stops pulsing and holds a steady
   amber ring, and the interface asks you - a specific human, with the exact verb and inputs in
   front of you - to decide. Trust is manufactured in that pause. Craft it like the hero it is.
4. **That it is one instrument, not a bundle.** The deepest ask in "unify AI technologies" is
   *coherence*. A Codex root phase, a native Codex subagent, and a deterministic adapter call must
   all read as the same species of work lit up on the same canvas. Heterogeneity is the engineering
   reality;
   **the UI's job is to hide the seams and show one rig.** If a user can tell which vendor ran a
   step without reading the label, we have failed the north star.
5. **Quiet until it matters.** Near-black, low-motion, high-signal at rest. The cyan current only
   brightens where there is life; amber only appears where a human is genuinely needed. A calm
   room that snaps to attention. Alarms mean something *because* the room is usually quiet.

If a screen delivers those five, it is worthy. If it is merely tidy, it is not yet.

---

## 2. The metaphor to build inside: the lighting rig

We already have "charged graphite instrument / mission control." Push it one notch more concrete,
because a metaphor you can point at is a metaphor a team can build to.

**Boltrig is a lighting and sound rig for a live show where the performers are AI agents.**

- The **canvas** is the truss: the fixtures (nodes) hang on it, wired to each other.
- A **run** is the show: the current travels the wires, fixtures light up in sequence, you watch
  the cues fire.
- The **kernel** is the dimmer board and the safety interlock: every fixture is powered *through*
  it, and a high-consequence cue physically cannot fire until the operator releases the interlock
  (the approval). No fixture is wired direct to the mains. That is the whole product in one image.
- **Chat** is standing on the stage next to a performer, talking, while the same show plays out on
  the board behind you. The transcript is not a chat log; it is a *live feed of the show from the
  performer's position*.
- The **audit log** is the show report: every cue, every level, timestamped, tamper-evident.

Hold this image. When a design choice is ambiguous, ask: *what would the best lighting console in
the world do here?* It would be dark, tactile, legible under pressure, and it would never, ever
hide a live channel from the operator.

---

## 3. The five signature moments (spend your craft budget here)

A product is remembered for a handful of moments. These five are where Boltrig earns "worthy."
Everything else is supporting cast and can be merely excellent.

### S1 - The graph coming alive
The registry tree, the authoring DAG, and the live run are **the same graph in three states**
(this is the core design-system promise). The moment worth obsessing over: a static authored graph
*becomes* a running one. The current enters at the trigger, an edge's dash starts animating, the
first node's border blooms to the cyan glow-pulse, resolves to green, and the current moves on.
This should feel like power flowing through a circuit you laid out yourself. It is the single most
Boltrig thing in the product. Frame-worthy.

### S2 - The approval pause
A live run hits a `consequence-high` verb. The pulsing stops. The node holds a **steady** amber
ring (steady, because pulsing means "working" and this node is not working, it is *waiting for
you*). An approval card rises with the full context: who, which exact verb, the literal inputs,
the consequence named in amber. Two deliberate choices, no rubber stamp, designed against
approval-fatigue. When you approve, the write does not "flip to ok in place" - the verb
re-invokes with your single-use approval and the *result* of that real execution renders. This is
where governed becomes trustworthy. Get the timing, the weight, and the copy exactly right.

### S3 - Following a subagent down
A run spawns a subagent. Its card appears in the stream. You click it and the run drawer *re-keys*
to the child - same instrument, new focus, the breadcrumb showing the descent. You can go three,
four levels deep and always climb back. This is how "a team of agents" stops being an abstraction
and becomes something you can *walk through*. The recursion is the feature; make the descent feel
like stepping through doors, not like losing your place.

### S4 - One chat turn, fully lit
A single mid-run chat turn is the reference client (it is graded B+ and settled; enhance, do not
rewrite). In one turn a user should see: dimmed live reasoning (subordinate, never the headline),
a tool-call card resolving (verb in mono, consequence badge, collapsible I/O as *data*), a
subagent card, and an inline approval - all as distinct, richly-typed events, never collapsed to a
paragraph of prose. Chat is a **live transcript of governed agent work**. The composer's thinking
state pulses light around the rim like cues tracing a track (already fixed this session - protect
it; the box must never rotate).

### S5 - The room at rest
Underrated and essential: the Home landing when nothing is on fire. Capability-aware: what needs
you, what ran recently, what is in flight, what you can start, what Boltrig can do. This is the
calm the alarms are measured against. If Home is busy and anxious, the whole instrument feels
anxious. Make rest feel *composed* - an operator's desk at the top of a quiet shift.

---

## 4. The aesthetic direction (in the real tokens)

Build the feeling out of the vocabulary that already exists in `ui/src/styles.css`. Do not invent
a parallel palette. The craft is in *how* these are used, not in new hex.

- **Surface**: near-black graphite. `--color-bg-base` (#04060D) is the void the current lives in.
  Panels and cards float just above it (`--bg-raised` / `--bg-card`) with the glass treatment
  already layered in. Depth comes from elevation and subtle borders, not from color. The dark is
  the stage; keep it dark.
- **The current**: electric cyan (`--color-accent`, #3DD3F0). This is *life*. It marks what is
  live, what is primary, what has focus, what just arrived. Ration it. Cyan everywhere is cyan
  nowhere. A screen at rest should have very little cyan; a screen mid-run should trace it exactly
  along the live path and nowhere else.
- **The agent flavour**: indigo (`--color-accent-2`). Secondary, links, the agent species. It is
  the cooler cousin of the current - present, but never competing with cyan for "this is alive."
- **Consequence**: amber-orange (`--color-consequence-high`, #FF7A45) is **sacred** (Law L4). It
  means one thing and only one thing: *a human is needed here*. Never decoration, never a warning
  (warnings are `--color-warn`), never a destructive-local action (that is red). When a user sees
  amber, their hand should move to the approval. Protect this the way you protect a fire alarm.
- **Mono is brand** (Law-adjacent doctrine): every verb id, noun, run id, grant token, and audit
  row renders in `--font-mono` (JetBrains Mono). Mono = "a real system identifier." It is how the
  instrument signals *this is a true thing the kernel knows about*, not UI chrome. Lean into it.
- **Motion**: subtle and meaningful. A running node breathes (1.6s). A new stream event flashes
  cyan once on arrival. Everything else holds still. All of it dies under `prefers-reduced-motion`
  (running becomes a static filled ring). Motion is a signal channel, not seasoning.
- **Type + density**: IBM Plex Sans for UI, the mono for identifiers. `data-density="compact"`
  exists for the developer and audit surfaces - they *want* to be dense and instrument-like; let
  them. Comfortable elsewhere.
- **Light + high-contrast are contracts, not afterthoughts** (D11). The `250` ink step and indigo
  `550` exist specifically to clear WCAG AA on dark. The theme/contrast/density variants are
  load-bearing. Everything you make must survive all three.

The overall read: **an audio-lighting rig, not a dashboard.** Engineered, tactile, legible under
pressure. If a screenshot could be mistaken for a generic AI SaaS with a dark theme, push it
harder toward the instrument.

---

## 5. What you are inheriting, and must not break

This is a handover, not a demolition. The console is mature and hard-won. The ambition ("worthy")
is delivered by *elevation and coherence*, not by a rewrite. The following are load-bearing and on
the **no-rewrite list** (`DESIGN-DECISIONS.md`). Extend them behind their stable seams; a
strangler-fig, never a restart.

- **The spatial deck** (`ui/src/deck/*`). Surfaces are slides on a 2D deck, not tabs (D1). Chat is
  the top-left anchor and default landing. The transform breaks `position:fixed` - pin by flex,
  overlay by the z-index scale (D3). Visited slides are hidden, never unmounted, or you abort a
  live stream (D2). This mechanism is frozen. Build *within* it.
- **The chat streaming + turn normaliser** (`chatTurn*.tsx`, the module stream store). The
  reasoning/tool/subagent/HITL event pipeline is subtle and correctness-critical. Enhance the
  rendering; do not touch the wiring without knowing exactly what you are doing.
- **The token layer** (`:root` + theme/contrast/density variants). Three-layer cascade: primitives
  to semantic (`--color-*`) to legacy aliases. New work consumes *semantic* names only, never
  primitives, never raw hex (D8). Do not rename legacy aliases - components depend on them.
- **The pattern language + AMENDMENTS** (`ui-patterns.md`, `surfaces/AMENDMENTS.md`). These are
  the law of the components. New components come *from the P-numbered register* (D5); a surface
  that needs a control not in the register is a fork back to the pattern doc, not a local
  invention. Raw JSON as a primary control is forbidden.
- **The kernel verb seam** (`ui/src/api/*`). The console talks to the kernel through the verb
  space. Every write flow names its verb path; there is no UI-only capability (Law L2). Render the
  server's `denied` reason; never pre-guess a role gate (Law L3). This boundary is doctrine.

Read `DESIGN-DECISIONS.md` before touching a surface. D1-D15 are canon. D12, D14, and D15 were
ratified on 2026-07-21; D13 was revised to preserve the frozen spatial deck while locking
full-width panels, the collapsible sidebar, and reduced-motion behavior.
If you believe a locked decision is wrong, you do not silently "fix" it and you do not silently
obey it - you put the alternative as a proposal with its case. For a genuine first-impression
design fork, that proposal goes to the **VJS court**, not to Will (standing governance). Check the
citator first.

---

## 6. Where the leverage is (what to elevate first)

From the `ENHANCEMENT-CHARTER.md` scorecard, ordered by leverage. Every listed surface now has
settled IA. Work inside those contracts is Enhance-altitude (decisive call + a work-log note).

1. **Chat** (settled, B+) - the flagship and the reference client. Build to the written chat
   surface spec. Streaming/HITL correctness is no-rewrite. This is S4.
2. **Automations / Workflow canvas** (settled, B) - the core loop and the home of S1. Finish
   run-record fidelity and the live lighting-up.
3. **Approvals / HITL** (settled, B-) - governance-critical, home of S2. Smallest tolerance for
   drift; render the AMENDMENTS approval contract exactly (D6/D7).
4. **Agent Studio** (settled, B-) - org-first fleet authoring; one slide per agent.
5. **Knowledge** (settled, C+) - the shared source library: originals first, stable citations,
   Cognee visibly downstream and rebuildable.
6. **Memory** (settled, C+) - recall first, with provenance attached to every fact.
7. **Admin / control-plane**, **Insight + Eval** (settled) - typed operator control, scoped
   observability, governed budgets, and repeatable behavior proof.
8. Everything else (Home, Channels, Me, Dev console, Registry, Kanban, Router) - token /
   consistency / a11y sweeps, Polish altitude, run in parallel any time. Note: Home is secondary
   on the charter but it *is* S5 - do not neglect the room at rest.

Land small reviewable diffs. No big-bang panel replacement - it destroys the ability to say "keep
mine." Keep the invariant and structure gates green on every commit.

---

## 7. The bar, restated

When you finish a surface, do not ask "is it clean?" Ask the five questions from section 1:

- Does it make the operator feel **in command**, not in the loop?
- Are there **sightlines** into every live thing, or is work hiding behind a spinner?
- Is safety **shown** in a crafted moment, or merely claimed in a badge?
- Does every runtime read as **one instrument**, or can you tell the vendor from the pixels?
- Is it **quiet at rest** so the alarms mean something?

Five yeses is worthy. Anything less is a draft.

---

## 8. Constraints (non-negotiable, so it maps onto the real app)

- **No em dashes or en dashes.** Anywhere. UI copy, code, comments, commit messages. Spaced
  hyphen, comma, colon, or parentheses (D9, and a standing global rule).
- **Semantic tokens only** in new work (D8). No primitives, no raw hex, in components.
- **Every surface declares an 80% path** completable with Tier-1 controls, and exposes exactly one
  primary button at rest (D10).
- **AA is a contract** (D11). Survive dark, light, and high-contrast; survive compact density.
- **React + Vite + CSS custom properties**, `@xyflow/react` for the canvas. No component
  framework. Express the system as tokens + component specs, not a kit.
- Do not grow a third bespoke client surface. D15 fixes console and chat as the **only two
  clients** of one verb-space.

---

## 9. First move

Do not start by drawing. Start by *seeing*. Bring the live stack up (the box has the binary and
the gateway), open the console, and walk the five signature moments in the running product with
your own eyes. Screenshot each. Grade each against section 7. Then pick the single highest-leverage
gap between what you saw and the bar above, propose the smallest diff that closes it, and land it.
Then the next. Surface by surface, top-down by leverage, the instrument gets more worthy every
commit - and it stays shippable the whole way.

That is the run. Build the rig worthy of the show.
