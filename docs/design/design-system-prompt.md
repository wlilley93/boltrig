# Boltrig - design system prompt (for claude.ai/design)

Paste the block below into claude.ai/design to generate Boltrig's design system /
UI kit. It is self-contained: it explains what Boltrig is, who uses it, the
surfaces to design, the feel, and the concrete tokens/components to produce. It is
grounded in the real product (a React 18 + Vite app, dark-first, bespoke CSS
tokens, `@xyflow/react` canvas) so the output drops into the existing front end.

---

## THE PROMPT

You are designing the visual design system for **Boltrig** (boltrig.io).

### What Boltrig is
Boltrig is a **governed agent operating system**: a thin, secure kernel that sits
between an organisation's AI agents and the outside world, and forces every action
an agent takes through one audited path that checks permission, asks a human when
the stakes are high, and records everything. Agents reason in plain "nouns and
verbs"; everything an organisation adds (its integrations, skills, workflows,
models) is data, not code. The promise is **power you can trust**: autonomous
agents doing real work, with a glass box around them.

The name signals the feel: **bolt** (electric, fast, a secure fastening) + **rig**
(an apparatus you assemble and operate). Precise, industrial, dependable, alive.

### Who uses it (design for all three)
- **Operators** - watch work happen, approve high-stakes actions, trace what an
  agent did. They need calm, legible, at-a-glance status.
- **Authors / admins** - compose what agents can do: wire integrations, build
  workflows on a canvas, govern config. They need a confident, powerful editing
  surface.
- **Developers** - inspect runs, invoke verbs directly, read the audit. They need
  density and precision.

### The product is organised in three planes (the primary navigation)
1. **Capability** - what agents CAN do: a registry shown as a *tree* of nouns ->
   verbs -> bindings; the integration/skill/model studios.
2. **Orchestration** - how capability is *composed*: a node-based **workflow
   canvas** (boxes = steps, wires = dependencies), and chat as a way to start work.
3. **Activity** - what is *happening and happened*: a capability-aware home, a
   live chat that streams the agent's reasoning and tool calls, a Kanban of work,
   an approvals inbox, an audit/execution tree, memory.

The connective tissue is **the run**: one agent run is traceable everywhere
through a shared **Run drawer** (its live event stream, its execution tree, its
cost, any pending approval). Design this drawer as a first-class, recurring surface.

### The signature surface: the node system
Boltrig's spine is a **node graph** used three ways - a capability *tree*, a
workflow *canvas* you author, and the *same canvas lighting up live* as a run
executes node by node. Give it a distinctive, legible node language:
- **Node kinds**, visually distinct at a glance: a **kernel-run** node (a fixed
  governed action), a **service** node (an action that reaches an outside system -
  show that it leaves the boundary), an **agent** node (hands a sub-problem to a
  reasoning model), and **trigger** nodes (chat / cron / webhook entry points).
- **Live run states** on a node: pending (dim), running (a calm pulse), ok,
  failed, skipped, and paused-for-approval (a clear "needs a human" state).
- **Edges** read as dependency/flow; the canvas should feel like an engineer's
  rig, not a toy flowchart.

### The feel
Dark-first, high-trust, technical-but-approachable. Think a precision instrument /
mission-control panel: structured, quiet by default, with confident accent moments
for the things that matter (a high-consequence action, a live run, an approval).
Not playful, not sterile. Restrained colour, strong hierarchy, generous use of
monospace for ids/verbs/code, humane spacing. It should make a governed,
auditable system feel reassuring rather than bureaucratic.

### Deliver a design system with
- **Colour tokens** (dark theme primary; also light + a high-contrast variant):
  surfaces (bg layers), text + muted, borders, a primary accent and a secondary
  accent, and **semantic colours** for: ok / warning / down / unknown,
  **consequence** (a clear "high-consequence / destructive" colour vs low), and
  **run/step states** (pending/running/ok/failed/skipped/paused).
- **Typography**: a UI sans, plus a monospace for ids, verb names, code, and audit
  rows. Define a type scale and a density option (comfortable + compact).
- **The node visual language**: the four node kinds, the run-state treatments
  (incl. a reduced-motion-safe "running" indicator), edges, and the canvas
  background/controls/minimap aesthetic.
- **Core components**: the three-plane left navigation; the Run drawer; badges
  (status, health, consequence, role); the approval card (must present full
  context so a human can decide responsibly - this is a safety surface, not a
  one-click rubber stamp); the chat stream with inline "thinking" (agent
  reasoning), tool-call cards, sub-agent cards, and inline approval; data tables
  (audit/runs); forms; the identity chip ("signed in as ...").
- **Motion**: subtle, purposeful (a run node pulsing, an event arriving), always
  honouring reduced-motion.
- **Accessibility**: WCAG AA contrast on all text and semantic colours, focus
  states, and an explicit accessible treatment for the canvas (focusable nodes).
- A short **brand statement** and logo/mark direction for "Boltrig" (the bolt +
  rig idea) that works as a small monochrome mark in a dark header.

### Constraints
The target is a real React + Vite app with a lean, bespoke CSS-variable design
system (no component framework) and `@xyflow/react` for the canvas. Express the
system as **design tokens** (CSS custom properties) plus component specs that map
cleanly onto that, not a heavyweight kit. Output the token set, the component
gallery, and the node/canvas language.

---

## How to use
1. Open claude.ai/design, paste THE PROMPT block above.
2. Iterate on the generated system; pull the tokens into `ui/src/styles.css`
   (the app already uses CSS custom properties on `:root` with theme/density/
   contrast variants), and the node treatments into the `.wf-node--*` /
   `.reg-node--*` classes and the run-state classes.
3. Keep it dark-first and token-driven so it composes with the existing UI rather
   than replacing it.
