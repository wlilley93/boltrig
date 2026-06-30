# Boltrig component specs

agents-final design-agent-suite, skill 12 (component specification): API + states +
variants + acceptance criteria, for the hero components. References the semantic
tokens in `DESIGN-SYSTEM.md` (components use semantic tokens only). These are the
parts the renderer and the implementation must get right, because each renders in
every design built with Boltrig.

## 1. Node (canvas) - the hero

- **Purpose**: one step / capability in the graph (registry tree, workflow canvas,
  live run).
- **Variants**: `kind` = kernel-run | service | agent | trigger (see DESIGN-SYSTEM
  §5 for accent/glyph per kind).
- **Props**: `label`, `verbId` (mono), `kind`, `consequence` (low|high),
  `runState?` (pending|running|ok|failed|skipped|paused), `selected`, `health?`
  (for adapter-bound), `onOpenRun?`.
- **States**: default · selected (accent ring) · hover · the six run states ·
  consequence-high marker · disabled/locked (read-only run mode).
- **Acceptance**: kind is identifiable without reading the label; run state is
  conveyed by colour AND a glyph/dot (not hue alone); `paused` is visibly distinct
  from `running` (steady vs pulsing) and shows a "needs you" affordance; verb id is
  mono and copyable; reduced-motion swaps the pulse for a static ring; focusable +
  operable by keyboard.

## 2. Run drawer - the connective tissue

- **Purpose**: one run, traceable from anywhere (Kanban card, chat sub-agent,
  Insight row, approval, workflow run).
- **Sections**: header (run id mono, status, cost) · **live event stream** (the
  transcript, §4) · **execution tree** (recursive agent -> child runs, per-node
  status + cost) · pending approval (answerable inline) · close.
- **Props**: `runId`, `follow` (live vs snapshot), `onOpenRun(childRunId)`.
- **States**: live (events arriving) · settled · pausing (a node awaiting
  approval) · empty/404 ("run not found or not in your scope" - server is
  authoritative) · loading.
- **Acceptance**: opens over any surface without losing context; following a
  sub-agent re-keys the drawer to the child run; an active run streams; a finished
  run replays identically; cost + status always visible in the header; a paused run
  surfaces its approval at the top.

## 3. Chat transcript cards (the live agent work)

The chat is a **live transcript of governed agent work**, not a bubble stream. It
renders the SSE event vocabulary:

- **Reasoning** (`reasoning_delta`): dimmed/secondary "thinking" block, visually
  subordinate to the answer; collapsible.
- **Tool-call card** (`tool_call` + paired `tool_result`): verb id in mono, a
  **consequence badge**, status (running -> ok/failed), collapsible input/output
  (mono, scrollable, never auto-executed - it is data). Acceptance: input/output
  are clearly "data the agent saw/produced", never styled as instructions.
- **Sub-agent card** (`subagent`): task + skills chips + a run handle that opens
  the child in the Run drawer.
- **Inline approval card** (`hitl`): the approval component (§5) embedded in the
  stream.
- **Text** (`text_delta`): the answer, primary.
- **Acceptance**: reasoning is clearly subordinate to the answer; a tool call and
  its result read as one unit; live and replayed turns look identical; the stream
  is re-attachable (a dropped client resumes).

## 4. Approval card - the safety surface (design with weight)

- **Purpose**: a human decides a high-consequence action. NOT a one-click rubber
  stamp.
- **Shows**: who/what is asking (actor), the exact **verb id** + its **inputs**,
  the **consequence** (high, in `--color-consequence-high`), and context. Two
  deliberate actions: Approve / Reject, plus optional notes.
- **States**: pending · approved · rejected · expired.
- **Acceptance**: the stakes are legible before acting; approve requires a
  deliberate action (not a single ambient click); designed against
  approval-fatigue (bursts are grouped/rate-aware); consequence colour + label are
  unmissable; full inputs are inspectable.

## 5. Three-plane navigation

- **Purpose**: primary nav grouped Capability / Orchestration / Activity (+
  Account), each a labelled group of tabs.
- **Props**: active route, role (gates which tabs show - cosmetic; server is
  authoritative), identity.
- **Acceptance**: the three planes read as distinct zones; the active tab is clear;
  deep-linkable (URL-driven); responsive (collapses gracefully); role-hidden tabs
  never imply a client-side security boundary.

## 6. Badges

- **Families**: status (ok/degraded/down/unknown) · consequence (high/low) ·
  run/step state · role · health.
- **Acceptance**: each family is visually distinct; colour is paired with a label
  or glyph (AA, hue-independent); compact enough for dense tables and node chips;
  consequence-high badge is the most prominent (it is a governance signal).

## 7. Supporting (lighter specs)

- **Registry tree node** (noun/verb/binding tiers; verb shows consequence + live
  health; binding shows adapter vs agent).
- **Identity chip** ("signed in as <subject> (<role>) @ <tenant>"), expandable to
  the dev sign-in.
- **Data tables** (audit/runs): mono ids, run ids link to the Run drawer,
  scope-filtered, dense.
- **Home cards** (needs-you / recent-runs / work-in-flight / quick-start /
  what-I-can-do), each a clear glanceable tile.
- **Empty / loading / denied** states: a denied action shows the server's reason
  faithfully; never pre-guessed.

## Quality gate (suite skill 12)

- [ ] Every component references semantic tokens only (no raw hex / primitives).
- [ ] Every component lists its states incl. error/empty/denied + reduced-motion.
- [ ] Run state + consequence are conveyed without relying on hue alone.
- [ ] The approval card is a deliberate, full-context decision (anti-rubber-stamp).
- [ ] Mono is used for all ids/verbs/run-ids/audit rows.
- [ ] AA contrast + visible focus + keyboard/canvas operability.
