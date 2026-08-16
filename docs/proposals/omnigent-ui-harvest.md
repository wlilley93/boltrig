# Omnigent UI harvest plan

## Objective

Bring Omnigent's session/workspace depth to the Boltrig console without moving
execution or governance authority out of the Boltrig kernel.

Reference inspected: `omnigent-ai/omnigent` revision
`0bea9873e6b697290e0a2d172eb879151839a2a6` on 2026-08-12.

## Adopt / adapt / reject

| Omnigent pattern | Ruling | Boltrig implementation |
|---|---|---|
| Calm task hierarchy and thin rows | Adopt | Pinned/Recent groups over real conversation fields; top command search remains the only search entry point |
| Centered new-session composer | Adapt | Familiar, attachment, skills and exact Bifrost model choice; omit unbacked project/host/harness selectors |
| Chronological prose and work blocks | Adopt | Existing `OrderedWorkTranscript`, normalized SSE events and exact tool correlation remain the data authority |
| `Worked for ...` disclosure | Adopt | Compact natural-language receipt with exact expandable audit details |
| Queue, edit and steer | Adapt | Existing durable steer contract; never imply reorder/delete support until the API provides it |
| Transcript anchoring and user-turn navigation | Adopt | Boltrig hooks with live/reattach/reload parity and reduced-motion support |
| Files, Changes and process panels | Adapt later | Lazy panels over bounded dispatcher verbs and immutable snapshots |
| Terminal panel | Defer | Separate governed-terminal decision; no direct WebSocket shell |
| Subagent list/graph | Adapt | Boltrig run tree, Familiar genotypes and truthful child status |
| Presence, sharing and comments | Defer | Separate tenant ACL, revocation, privacy and retention work |
| Omnigent policy engine and runner dispatch | Reject | Boltrig kernel remains the only authority |
| Omnigent chat store/reducer | Reject | `sdks/web` contracts and `normalizeEvents` remain authoritative |
| Omnigent opaque sidebar/search styling | Reject | Boltrig continuous canvas and borderless glass rails remain authoritative |

## Affordance-to-authority matrix

| Surface | Current authority | Delivery posture |
|---|---|---|
| Task list, pin/archive, working state | Conversation list/lifecycle SDK | Ship in Shell v2 |
| Model selector | Tenant model choices resolved through Bifrost and trusted Codex admission | Ship in Shell v2 |
| Attachments, artifacts and Sources | Chat attachment/artifact contracts | Ship in Shell v2 |
| Tool activity and approvals | Structured chat events plus governed HITL endpoints | Ship in Shell v2 |
| Queue/steer | Durable steer receipts and chat stream | Ship in Shell v2 |
| Subagent identities and run detail | Structured subagent events and run APIs | Ship in Shell v2 |
| Background process / Computer Use | Explicit tool verbs and statuses only | Render only when observed |
| Workspace files and Git diff | No general bounded browser contract yet | Add dispatcher verbs before UI |
| Interactive terminal | No governed lease/channel contract | Omit pending separate decision |
| Human presence/collaboration | Device presence is not session ACL/presence | Omit pending separate product track |

## Delivery sequence

### Milestone 1 - structural foundation

Split the existing shell/chat monolith into small view boundaries and tested
controllers for route ownership, scrolling, resizing and focus. Preserve URLs,
task ids, persisted messages, SSE, the shared normalizer and every existing
mutation.

### Milestone 2 - shell and new task

Ship compact Pinned/Recent task navigation and the deeper new-task composer.
Enforce the principal's negative requirements in DOM and computed-style visual
contracts.

### Milestone 3 - transcript choreography

Ship stable near-bottom following, history prepend anchoring, previous/next
user-turn navigation, jump-to-latest, chronological work receipts, queued
instructions, reconnect and task-switch isolation.

### Milestone 4 - task inspector

Ship a resizable borderless glass inspector with truthful Outputs, Subagents,
Processes, Computer Use, Sources and Run activity groups. Unsupported dynamic
groups do not render; Outputs remains a stable first section and truthfully says
`No outputs` when the task is read-only or has produced none.

### Milestone 5 - governed workspace depth

Add read-only, bounded workspace data behind the dispatcher, followed by lazy
panels. Ship each independently: file metadata listing fits the existing signed
device-root lease; Git and process views stay omitted until their external read
surfaces can be proven root-confined. Path escape, symlink, size, output,
tenant, revocation and approval behavior must be bound by invariants before any
panel is enabled.

### Milestone 6 - responsive rollout

Finish compact/mobile sheets, keyboard and IME behavior, accessibility,
reduced-transparency/motion fallbacks and content-free telemetry. Keep one
renderer, version local presentation preferences, preserve downgrade-readable
pin state, and ratchet the extracted shell/chat boundaries so rollback does not
require a second policy or event authority.

## Acceptance gates

- The same recorded event fixture has the same semantic order live, after
  reattach and after reload.
- A task switch cannot publish stale async content, focus or scroll state.
- Every visible mutation maps to a governed endpoint or dispatcher verb.
- No raw tool arguments, secrets, provider topology or cross-tenant records
  reach presentation models.
- Full keyboard operation, focus restoration, WCAG AA, reduced motion and an
  opaque fallback for environments without backdrop filtering.
- Heavy workspace viewers are lazy and do not increase the initial production
  JavaScript budget by more than ten percent.
- Source-bound desktop, tablet and phone visual evidence is captured for each
  milestone; no conformity claim is made without the required VDS authority.
- Worker tests/typecheck/build and the invariant suite are green whenever the
  relevant layer changes.
