# Boltrig - design system prompt (for claude.ai/design)

Paste **THE PROMPT** block below into claude.ai/design (generative mode) to design
Boltrig's design system + key screens. It is self-contained and grounded in the
real product (a React 18 + Vite app, dark-first, bespoke CSS-variable tokens,
`@xyflow/react` canvas, an SSE event stream) so the output drops onto the existing
front end rather than fighting it. This is the GENERATIVE brief - distinct from
`/design-sync`, which only captures already-designed components.

---

## THE PROMPT

You are designing the visual design system **and the key screens** for **Boltrig**
(boltrig.io). Design Boltrig *specifically* - not a generic "AI console." Every
detail below is real; design for it.

### What Boltrig is
Boltrig is a **governed agent operating system**. A thin, secure kernel sits
between an organisation's AI agents and the outside world and forces every action
an agent takes through one audited path: it checks who is asking and what they may
do, pauses for a human when the stakes are high, resolves credentials only inside
the kernel, executes, then records everything in a tamper-evident log. Agents
reason in plain **nouns and verbs** (e.g. `ticket.create`, `web.fetch`,
`memory.recall`); everything an organisation adds - its integrations, skills,
workflows, models - is **data, not code**. Capabilities are governed: each verb
has a **consequence** level, and high-consequence ones (anything destructive or
outbound) cannot run without human approval.

The product's whole feeling is **a glass box around autonomous power**: agents do
real, multi-step work on their own, and you can see exactly what they did, stop
them, and trust the boundary. Design should make a governed, auditable system feel
**reassuring and alive**, never bureaucratic.

The name is the north star for the feel: **bolt** (electric, fast, a secure
fastening) + **rig** (an apparatus you assemble and operate). Precise, industrial,
dependable, kinetic. Reference points: a mission-control panel, an audio/lighting
rig, a precision instrument - not a SaaS dashboard, not a toy flowchart.

### Who uses it (design for all three, one coherent surface)
- **Operators** watch work happen, approve high-stakes actions, and trace what an
  agent did. They need calm, glanceable status and trustworthy approval moments.
- **Authors / admins** compose what agents can do: wire integrations, build
  workflows on a canvas, govern config. They need a confident, powerful editor.
- **Developers** inspect runs, invoke a verb directly, read the audit. They need
  density and precision.

### The real surfaces to design (these screens exist today)
Navigation is organised in **three planes** plus account - design the left-nav
around them:
- **Capability** - *what agents can do.* A **Registry** shown as a tree (noun ->
  verb -> binding); Skill / Adapter / Model **studios**; a **Dev console** (invoke
  a verb directly, spawn an agent, view generated adapter source).
- **Orchestration** - *how capability is composed.* The **Workflow canvas**
  (author a graph of steps) and **Chat** (start work in natural language).
- **Activity** - *what is happening and happened.* A capability-aware **Home**
  (what needs me / recent runs / work in flight / what I can do); **Chat**; a
  **Kanban** of work items by status (pending / in-flight / blocked /
  awaiting-human / done / failed); an **Approvals** inbox; **Insight** (cost +
  audit search + runs); **Memory** (recall / browse / remember / ingest).
- **Account** - Admin (manifest config + history + rollback + credential refs),
  Settings, the personal "Me" surface, identity.

### The signature surface: the node system (give this the most design love)
Boltrig's spine is a **node graph used three ways**, and it is what makes Boltrig
look like Boltrig:
1. **Registry canvas** - a *tree*: nouns -> verbs -> their one binding (an adapter
   or an agent). Browsing/defining capability.
2. **Workflow canvas** - an authoring *DAG*: boxes are steps, wires are
   dependencies. This is the editor.
3. **Live run canvas** - the *same graph lighting up* as a run executes, node by
   node, in real time.

Design a distinctive, legible **node language**:
- **Four node kinds**, instantly distinguishable: **kernel-run** (a fixed governed
  action), **service** (an action that reaches an *outside* system - visually
  signal "this leaves the boundary"), **agent** (hands a sub-problem to a
  reasoning model - this one can *think*), and **trigger** (chat / cron / webhook
  entry points at the front of a flow).
- **Live run states** on a node: **pending** (dim), **running** (a calm pulse),
  **ok**, **failed**, **skipped**, and **paused-for-approval** (a distinct,
  unmissable "a human is needed here" state - this is a safety signal).
- A **consequence** marker on high-consequence nodes/verbs (the ones that will
  pause for approval).
- Edges read as dependency/flow. The canvas should feel engineered.

### The live event stream (design chat + the run view around this)
When an agent runs, Boltrig streams a typed event sequence over SSE; the UI must
render it richly, never collapse it to a paragraph. The vocabulary is real:
- `reasoning_delta` - the agent's live chain-of-thought ("thinking"), shown dimmed
  / secondary.
- `tool_call` then a paired `tool_result` - the agent invoking a governed verb,
  with input and output. Design a **tool-call card** (verb name in mono, a
  consequence badge, status, collapsible input/output).
- `subagent` - the agent spawned a child run; design a **sub-agent card** that
  links into that child's run.
- `hitl` - the run paused for a human approval, inline.
- `workflow_step` - per-step status that lights up the live run canvas.

So the chat is not a chatbot bubble stream: it is a **live transcript of governed
agent work** - reasoning, tool-call cards, sub-agent cards, and inline approvals,
interleaved with text. Design that.

### The connective tissue: the Run drawer
Every agent run is traceable everywhere through one shared **Run drawer**, opened
from a Kanban card, a chat sub-agent, an Insight row, an approval, or a workflow
run. It shows the run's **live event stream**, its **execution tree** (a recursive
tree of agent -> child runs with per-node status + cost), its cost/status summary,
and any **pending approval** answerable inline. Following a sub-agent re-keys the
drawer to the child run. Design this as a first-class, recurring panel - it is how
the whole product coheres.

### The approval moment (a safety surface, design it with weight)
High-consequence actions pause and route to a human. The **approval card** must
present *full context* - who/what is asking, the exact verb and its inputs, the
consequence - so a person can decide responsibly. It is deliberately **not a
one-click rubber stamp**; design against approval-fatigue (clear, deliberate
approve/reject with the stakes legible). This is where "governed" becomes visible
and trustworthy.

### The feel, restated
Dark-first, high-trust, technical-but-approachable, **quiet by default with
confident accent moments** for the things that matter: a live run, a
high-consequence action, an approval, an agent thinking. Restrained colour, strong
hierarchy, monospace for ids / verbs / code / audit rows, humane spacing, subtle
purposeful motion. Precision instrument, mission control - alive, not sterile.

### Deliver a design system with
- **Colour tokens** (dark primary; also a light and a high-contrast variant -
  the app already supports theme/density/contrast axes): surface layers, text +
  muted, borders, a primary + a secondary accent, and **semantic colours** for
  `ok` / `warn` / `down` / `unknown`, **consequence** (a clear high/destructive vs
  low), and **run-state** (pending / running / ok / failed / skipped / paused).
- **Typography**: a UI sans + a monospace (for ids, verb names, code, audit). A
  type scale and a **density** option (comfortable + compact).
- **The node + canvas language**: the four node kinds, the run-state treatments
  (incl. a reduced-motion-safe "running" indicator), edges, and the canvas
  background / controls / minimap aesthetic. This is the hero.
- **Core components**: the three-plane left nav; the **Run drawer**; the **chat
  transcript** with reasoning / tool-call / sub-agent / inline-approval cards; the
  **approval card**; badges (status, health, consequence, role); the registry
  tree; data tables (audit / runs); forms; the identity chip ("signed in as X @
  tenant"); empty / loading / denied states (the server is authoritative -
  denials are shown, never pre-guessed).
- **Motion**: subtle and purposeful (a run node pulsing, an event arriving), always
  honouring reduced-motion.
- **Accessibility**: WCAG AA on all text and semantic colour, focus states, and an
  accessible treatment for the canvas (focusable nodes).
- A short **brand statement** and a logo/mark direction for "Boltrig" (the bolt +
  rig idea) that works as a small monochrome mark in a dark header.

### Also design these key screens (so the system is shown in use)
1. **Home** - the capability-aware landing: "needs you" (pending approvals),
   recent runs, work-in-flight, quick-start, "what I can do."
2. **A live chat turn** - mid-run: reasoning showing, a tool-call card resolving, a
   sub-agent card, an inline approval.
3. **The workflow canvas** - authoring a graph (the four node kinds, the palette).
4. **The same workflow running live** - nodes lighting up, one paused for approval.
5. **The Run drawer** - execution tree + live events + cost, over any of the above.
6. **The Approvals inbox** - the safety surface at rest and answering one.

### Constraints (so it maps onto the real app)
The target is a React + Vite app with a lean, bespoke **CSS custom-property**
design system (no component framework) and `@xyflow/react` for the canvas. Express
the system as **design tokens (CSS variables)** plus component specs that map onto
that, not a heavyweight kit. Today's tokens live on `:root` in `ui/src/styles.css`
(theme/density/contrast variants; a colour scale; accent + the semantic / status /
consequence colours; `.wf-node--{agent,service,kernel-run,trigger}` + run-state
classes; badges; chat chrome). Design *the upgrade* to that vocabulary - same
token shape, far better craft.

---

## How to use
1. Open claude.ai/design, paste **THE PROMPT** block. Let it generate the system +
   the six screens.
2. Iterate. Then I (Claude Code) implement it in `ui/`: pull tokens into
   `ui/src/styles.css`, the node treatments into the `.wf-node--*` / `.reg-node--*`
   + run-state classes, and rebuild the panels against the new components.
3. Once the UI is actually designed, `/design-sync` becomes worth running - it will
   capture the real, on-brand components so future designs stay consistent.
