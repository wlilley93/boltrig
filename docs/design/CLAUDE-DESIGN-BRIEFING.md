# Boltrig - final briefing for claude.ai/design

This is the **paste-ready** briefing. It carries the product context, the design
system Boltrig already has a baseline for (`DESIGN-SYSTEM.md`), the hero component
specs (`COMPONENT-SPECS.md`), and the screens to design. Produced via the
agents-final design-agent-suite (System + Concept mode). Paste **THE BRIEFING**
block into claude.ai/design generative mode.

---

## THE BRIEFING

Design the visual design system **and six key screens** for **Boltrig**
(boltrig.io). Design Boltrig *specifically*. A baseline token system and component
specs already exist (below) - your job is to render them to a high craft bar and
show them in use, not to invent a different system.

### Product (design for this, it is all real)
Boltrig is a **governed agent operating system**: a secure kernel between an
organisation's AI agents and the world that forces every agent action through one
audited path - check permission, pause for a human when stakes are high, resolve
credentials only inside the kernel, execute, record in a tamper-evident log.
Agents reason in **nouns and verbs** (`ticket.create`, `web.fetch`); everything an
org adds is **data, not code**; each verb has a **consequence** level and
high-consequence ones need human approval. The product is **a glass box around
autonomous power** - agents do real multi-step work alone, and you can watch,
stop, and trust it. Make governed + auditable feel **reassuring and alive**, never
bureaucratic.

**Brand / feel**: the name is **bolt** (electric, fast, a secure fastening) +
**rig** (an apparatus you operate). A charged graphite instrument: near-black
surfaces, an **electric-cyan current** for life + primary action, a warm
**amber-orange reserved for consequence** (the colour of "a human is needed").
Mission-control / precision instrument / an audio-lighting rig - dark-first, quiet
until something matters. Not a SaaS dashboard, not a toy flowchart.

### Users
Operators (watch work, approve high-stakes actions, trace runs), authors/admins
(compose capability, build workflows on a canvas), developers (invoke a verb, read
the audit). One coherent surface.

### The token system to render (baseline - keep this vocabulary)
Dark primary (plus a light + a high-contrast variant). Semantic, intent-named:
- Surfaces: bg-base `#0B0E14`, bg-raised `#12161F`, bg-card `#1A2030`, overlay
  scrim. Borders: subtle `#2E3850`, strong `#3A4357`.
- Text: primary `#E6EAF2`, secondary `#8A93A6`, muted `#5A6477`.
- Accent (the current): cyan `#3DD3F0` (live, primary, focus); secondary indigo
  `#7C8BFF` (links, agent).
- Status: ok `#3FB984`, warn `#E8B339`, down `#F0654A`, unknown `#5A6477`.
- **Consequence**: low `#5A6477`, **high `#FF7A45`** (destructive/outbound).
- **Run state**: pending (dim) / running (cyan, pulsing) / ok / failed / skipped /
  **paused-for-approval (`#FF7A45`, steady ring)**.
Typography: a precise UI sans (Inter/Geist) + a **monospace** (JetBrains/IBM Plex
Mono) used for every verb id, run id, grant token, and audit row - mono = "a real
system identifier", a recurring brand signal. Define a type scale + a compact
density. Radius 6/8/12; subtle elevation; a 1.6s breathe pulse on running nodes; a
cyan arrival flash on new stream events; **all motion off under reduced-motion**.

### The hero: the node system (give this the most craft)
A node graph used three ways - a registry **tree** (noun -> verb -> binding), a
workflow authoring **DAG**, and the **same graph lighting up live** as a run
executes. Four instantly-distinguishable node kinds: **kernel-run** (steel,
default governed action), **service** (indigo + an outward/boundary-cut motif:
"leaves the system"), **agent** (cyan + a "thinking" affordance: the only kind
that streams reasoning), **trigger** (dashed amber + a bolt glyph: chat/cron/
webhook entry). Live run states overlay on a node (pending/running/ok/failed/
skipped/paused), conveyed by colour AND a glyph - never hue alone. A
consequence-high node carries a marker foreshadowing its approval pause. Edges read
as dependency/flow (animated only while live). Engineered, legible, alive.

### The live event stream (design chat + the run view around this)
A run streams typed events; render them richly, never collapse to a paragraph:
`reasoning_delta` (live "thinking", dimmed/subordinate), `tool_call`+`tool_result`
(a **tool-call card**: verb in mono, consequence badge, status, collapsible
input/output as data), `subagent` (a **sub-agent card** linking into the child
run), `hitl` (an inline **approval card**), `workflow_step` (lights the live
canvas). Chat is a **live transcript of governed agent work**.

### The connective tissue + the safety surface
- **Run drawer**: one run traceable from anywhere - its live stream, its execution
  tree (recursive agent -> child runs, per-node status + cost), cost/status, and any
  pending approval answerable inline; following a sub-agent re-keys it to the child.
- **Approval card**: a human deciding a high-consequence action. Full context
  (actor, exact verb + inputs, consequence in amber), deliberate approve/reject,
  **not a one-click rubber stamp**, designed against approval-fatigue. This is
  where "governed" becomes visible and trustworthy.

### Navigation
Three planes + account: **Capability** (Registry tree; Skill/Adapter/Model
studios; Dev console), **Orchestration** (Workflow canvas; Chat), **Activity**
(Home; Chat; Kanban; Approvals; Insight; Memory), **Account** (Admin; Settings;
Me; identity chip "signed in as X @ tenant"). Design the left-nav around the three
planes as distinct zones.

### Deliver
1. The **design system**: the token set above rendered to high craft (dark +
   light + high-contrast), typography, the node + canvas language (the hero),
   badges (status/consequence/run-state/role/health), motion, accessibility (AA,
   focus, focusable canvas nodes).
2. The **hero components**: node (4 kinds + 6 run states), Run drawer, the chat
   transcript cards (reasoning / tool-call / sub-agent / inline-approval), the
   approval card, the three-plane nav, badges, the registry tree node, the
   identity chip, audit/runs tables, empty/loading/denied states.
3. **Six screens in use**:
   - Home - the capability-aware landing (needs-you / recent runs / work-in-flight
     / quick-start / what-I-can-do).
   - A live chat turn mid-run - reasoning showing, a tool-call card resolving, a
     sub-agent card, an inline approval.
   - The workflow canvas - authoring a graph (the four node kinds + palette).
   - The same workflow running live - nodes lighting up, one paused-for-approval.
   - The Run drawer - execution tree + live events + cost, over one of the above.
   - The Approvals inbox - at rest and answering one.
4. A short **brand statement** + a **Boltrig mark** (bolt + rig: a lightning
   stroke that doubles as a rigging shackle, or a bracketed-mono lockup) that works
   at 20px, monochrome, on the near-black background.

### Constraints (so it maps onto the real app)
A React + Vite app, lean **CSS custom-property** system (no component framework),
`@xyflow/react` for the canvas. Express the system as **design tokens (CSS
variables) + component specs**, not a heavyweight kit. Keep the intent-named token
shape above; design *the upgrade* in craft. Components reference semantic tokens
only.

---

## How to use + next step
1. Paste **THE BRIEFING** into claude.ai/design (generative). Iterate on the
   system + the six screens.
2. Tell me when you have a direction you like. I (Claude Code) implement it in
   `ui/`: tokens -> `ui/src/styles.css` (`:root` + the theme/contrast/density
   variants), node treatments -> `.wf-node--*` / `.reg-node--*` + run-state
   classes, the chat/Run-drawer/approval components, then rebuild + redeploy the
   live stack.
3. Once the UI is genuinely designed, `/design-sync` captures the real on-brand
   components so future designs stay consistent.

Companion docs (the full system + specs this briefing distils):
`DESIGN-SYSTEM.md`, `COMPONENT-SPECS.md`, `design-system-prompt.md`.
