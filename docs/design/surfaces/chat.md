# Boltrig Chat slide - build-ready surface design spec

Surface: the CHAT row anchor of the spatial deck (row `chat`, column 0, no columns for now per DESIGN-v2 grid). This spec replaces the current `ChatPanel.tsx` in place. It is written against the ground-truth reader (`reader-chat.md`), the frozen deck mechanics (`DESIGN-v2.md`), the shell constraints (`reader-shell.md`), the binding pattern language (P-numbers cited throughout), and the code as it exists today (file:line cited). Every backend gap is tagged FRONTEND-ONLY or DEPENDS-BACKEND, consolidated in section 12.

80% path declaration (P20): **type a message, press Ctrl+Enter, watch the governed response arrive as a live timeline.** Completable with Tier 1 controls only; the surface's single `btn--primary` at rest is Send.

---

## 1. Placement in the deck and the slide frame

- The chat slide is the deck's top-left anchor and the default landing (`#/chat`, DESIGN-v2 decisive call 2). It is **keep-alive pinned once visited** (DESIGN-v2 mount policy), so it is CSS-hidden (`visibility:hidden` + `inert`) when off-screen, never unmounted. This is load-bearing: the reader's hazard list shows unmount aborts an in-flight stream irreversibly (ChatPanel.tsx:96-102, reader-chat section 4). Section 7 additionally moves stream state into a module store so even a hard remount recovers.
- The slide is its own scroller per the deck renderer, but chat overrides that: the slide root for chat sets `overflow:hidden` and lays out three internal regions, each managing its own scroll (rail, transcript). The composer is pinned by flex, not `position:fixed` (the deck transform breaks `position:fixed`, reader-shell section 3; nothing in this surface may use fixed positioning).
- The existing `max-height:60vh` on `.chat__messages` and `70vh` on `.chat__rail` (styles.css:1237, 1304-1306 per reader-shell) are **deleted**: inside a fixed-height slide the regions size from flex (`flex:1; min-height:0; overflow-y:auto`).
- The breadcrumb position chip ("Chat - 1 of 1") renders in the slide header per DESIGN-v2 affordance 6. Edge chevrons: down-chevron only (agents row below); right chevron absent (no columns).
- Deck keyboard chord (Ctrl+Alt+Arrow) never fires while focus is in the composer, the rail search, or any HITL input (DESIGN-v2 guardrail 3; P36).

## 2. Layout regions

```
+-- slide frame (border --color-border-subtle, bg tokens) -------------------+
| [breadcrumb chip]  Chat                                                    |
| +----------------+--+-----------------------------------------------------+
| | A rail (280px) |  |  B conversation header (44px)                       |
| |  search        |  +-----------------------------------------------------+
| |  New conv      |  |  C transcript (flex:1, overflow-y:auto,             |
| |  Today         |  |     content column centered, max-width 860px)       |
| |   - conv row   |  |     ... messages, event cards ...                   |
| |   - conv row   |  |            [ Jump to latest v ]  (floating pill)    |
| |  Earlier       |  +-----------------------------------------------------+
| |   - conv row   |  |  D composer (auto height, pinned by flex)           |
| +----------------+--+-----------------------------------------------------+
+----------------------------------------------------------------------------+
```

- Grid: `grid-template-columns: 280px 1fr` at >=900px. Below 900px the rail collapses to a toggle button in region B ("Conversations (n)") that slides the rail over the transcript as an in-slide absolutely-positioned panel (z-index 30, below drawer 70 / palette 80 per the stacking scale, reader-shell section 3; no portal - none exist in this codebase).
- Density (P34): chat is a **form-weight** surface; comfortable rhythm even under `data-density="compact"`. The transcript content column is capped at 860px and centered for reading measure; event cards span the full content column.
- All new classes join the cascade after the v3 layer, `block__elem--modifier` naming, semantic `--color-*` tokens only (reader-shell section 2).

## 3. Region A: the conversation rail

Data: `GET /v1/conversations` via `useFetch` (ChatPanel.tsx:74; app.py:333-348 returns `{conversations:[{id,title,status,updated_at}]}`), with the deck's `paused` option so the poll quiesces off-slide (DESIGN-v2 polling quiesce). Poll: 30s (light; the stream store, not the poll, drives liveness).

### 3a. Rail header
- Label "Conversations" + count, `--fs-xs` uppercase secondary.
- **New conversation**: ghost `.btn` (NOT primary - P20 allows one primary at rest and Send owns it). Behavior is the existing client-side reset (ChatPanel.tsx:135-143): clears active id, shows the transcript empty state; **no server call**; the conversation id materializes from the first `message_start` of the next send (ChatPanel.tsx:164-166). While a draft is active, a synthetic top row "New conversation" renders in the rail with an accent border, replaced by the real row when the id lands and `convs.reload()` runs.
- **Search**: a plain input, placeholder "Filter conversations", client-side substring filter over titles (FRONTEND-ONLY, reader-chat gap 6). "/" focuses it when focus is not already in an editable (P36).

### 3b. Grouping and rows
- Group by `updated_at` under plain headers: **Today / Yesterday / This week / Earlier** (client-side). Relative times refresh on a 60s interval (extends `whenText`, ChatPanel.tsx:31-40); absolute timestamp on `title=` (P34).
- Row anatomy (button, full width): title line (truncate, "(untitled)" fallback as today, ChatPanel.tsx:257) + meta line (relative time). The raw status badge on every row (ChatPanel.tsx:259-261) is **removed**: status is only shown when it is information (P21 rung 1 - "OPEN" on every row teaches nothing). Rows whose conversation has a live stream session (section 7) show a **cyan pulse dot** (running pulses, canon); a session that completed while unviewed shows a **steady cyan dot** cleared on open.
- Active row: `conv-item--active` as today. Selecting a row loads the transcript (`api.conversation(id)`, ChatPanel.tsx:110-133) but **no longer aborts an in-flight stream** (change from ChatPanel.tsx:126): streams live in the module store keyed by conversation, so a background turn keeps arriving and its row pulses (section 7). FRONTEND-ONLY.
- CLOSED conversations (soft delete sets status CLOSED, access_routes.py:131-144) are filtered from the default list; a Tier 3 disclosure at the rail foot, "Closed (n)" (N11), reveals them read-only (P18).

### 3c. Row actions
- One inline hover/focus action per row (P35 allows two max): **Delete**. It is `ArmConfirm` (N14, P27) IN the row, tone danger, never `window.confirm`: rest label an icon+label ghost "Delete"; armed state swaps the row content in place to "Delete '<title>'? Its transcript stays in the audit log." + [Confirm delete] (down-colored) + [Cancel]; disarm on Escape, Cancel, or slide navigation; busy "Deleting..."; then `api.deleteMyConversation(id)` (client.ts:596-601 -> `DELETE /v1/me/conversations/{id}`, a soft close). On ok: reload list; if the deleted conversation was active, reset to the draft view. Errors render the faithful reason inline (L3, `apiReason`, shared.tsx). FRONTEND-ONLY (route exists; UI absent today, reader-chat gap 4).
- **Rename**: DEPENDS-BACKEND. Title is fixed at first-60-chars (chat.py:89) and no PATCH route exists (reader-chat gap 13). The row reserves the slot (second action position) but renders nothing until `PATCH /v1/conversations/{id} {title}` (or a `control.conversation.retitle` verb) lands. No fake affordance.

### 3d. Rail states (P24 precedence: denied > error > loading > empty > ready)
- Loading (first load only): `Skeleton variant="rows" count={5}` (N13, P25). Polls never skeleton (useFetch keeps stale data, reader-chat citation useFetch.ts:51-53 behavior).
- Error: `ErrorState` with reason + "Try again".
- Denied: calm warn callout with the server reason verbatim, "Ask an admin to widen your access." No retry (P24).
- Empty: muted line "No conversations yet. Say hello below." (the composer is the CTA; no button needed - the 80% path starts in region D).

## 4. Region B: conversation header

A 44px strip above the transcript:
- Left: conversation title (or "New conversation"), plain text. No inline edit until rename exists (3c).
- Right, in order:
  - **Actor chip**: mono chip `chief-of-staff` with TermTip (P21 rung 2): "This conversation is handled by the chief-of-staff orchestrator. Every action it takes runs through the kernel." This is the honest rendering of the hardcoded actor (chat.py:172-173, reader-chat section 1). It is **non-interactive**. When `ChatRequest` gains an agent/model field (DEPENDS-BACKEND, reader-chat gap 10) this chip becomes an `EntityPicker` (P6/N4) over `GET /v1/capabilities` agent profiles with the inline preview card (runtime, model endpoint, cost tier). The slot is designed; the control is not built until the field exists.
  - **Run link**: when the latest turn has a `run_id`, a `RunLink` (shared.tsx:73-83) "View run" opens the global run drawer without moving the deck (DESIGN-v2 overlays).
  - Sub-900px: the "Conversations (n)" rail toggle.

## 5. Region C: the transcript

The message log. `overflow-y:auto; overscroll-behavior:contain`, content column centered at max-width 860px. `aria-live="polite"` while the slide is active, `"off"` while inactive (DESIGN-v2 polling quiesce; today's static `aria-live` is ChatPanel.tsx:273).

### 5a. Message anatomy
- **User message**: right-aligned card on `--color-bg-inset`, max-width 70% of the content column, markdown-rendered (users paste code too). Meta row on hover: relative timestamp (`created_at` is returned, reader-chat gap 5) with absolute on `title`, and a Copy action.
- **Assistant message**: full width of the content column, no card chrome (the transcript is the instrument's surface, not a bubble pile): the turn timeline (5c) then the rendered text. Meta/action row (5d) below.
- Role labels: keep the compact role tag (`chat-msg__role`) but sentence-cased "you" / "orchestrator"; assistant turns that carry a run get their identity from the actor chip, not repeated per message.
- Persisted and live turns render through the **same** `normalizeEvents` + timeline components (the invariant chatTurn.tsx already holds for the Run drawer; preserve it - the Run drawer inherits every refinement here for free).

### 5b. Markdown renderer requirements (the recorded dependency)

The markdown dependency is a recorded decision (DESIGN-v2 decisive call 5). This spec defines **what the renderer must support**, not which library:

1. CommonMark core: paragraphs, emphasis, strong, ordered/unordered lists (nested), blockquotes, horizontal rules, inline code, links.
2. GFM tables (rendered with P35 table styling inside a horizontal-scroll wrapper) and strikethrough.
3. **Fenced code blocks**: language label chip (mono, `--fs-xs`), a per-block **Copy** ghost button (top-right, "Copied" wisp on success, see clipboard rule below), `--font-mono`, max-height 400px with an "Expand" affordance beyond it. Syntax highlighting is optional at first ship; if included it must be theme-token driven (no bundled light-theme CSS).
4. Headings render **demoted**: h1/h2 at `--fs-lg`, h3+ at `--fs-md` - a chat answer must not shout page-scale type inside the transcript.
5. **Raw HTML is never rendered** - escaped or stripped, no exceptions (the transcript renders model output; this is the XSS boundary).
6. **Images are not rendered** as `<img>`: they render as their link. No attachment pipeline exists (reader-chat gap 11); remote image fetch from model output is a privacy/leak channel. Revisit when attachments land.
7. **Streaming-safe**: must tolerate incomplete markdown mid-stream (an unclosed fence renders as an open code block; no layout thrash on each append). Today the top-level answer arrives as ONE `text_delta` (chat.py:197-199, reader-chat section 1 caveat) so this is cheap; fine-grained deltas (reader-chat gap 14, NEEDS-BACKEND) must not require renderer changes.
8. Links: external links open `target="_blank" rel="noopener noreferrer"` with an external marker. **Internal hash links** (`#/agents/x`, `#/automations/y`) render as deep-link chips that call `navigate()` so the deck animates to the slide - this is how chat-authored entities are reachable (section 8).
9. Mono for every id/verb/pattern the model emits in inline code (brand law, P34).

Clipboard rule (all copy buttons on this surface): `navigator.clipboard.writeText` with a `document.execCommand("copy")` textarea fallback; on failure show an inline "Press Ctrl+C" selected-text fallback, never fail silently (the known insecure-context trap, design-debt W2).

### 5c. The turn timeline (typed event cards)

`normalizeEvents` (chatTurn.tsx:55-134) currently folds events into kind buckets, painted grouped by kind above the text (chatTurn.tsx:331-367), losing chronology. Upgrade (FRONTEND-ONLY, shared with the Run drawer):

- `NormalizedTurn` gains `timeline: TimelineEntry[]` preserving **arrival order** for tool, subagent, hitl, and step-group entries. Reasoning stays one accumulated block pinned first; text stays one block pinned last (faithful to today's coarse delta). The timeline type supports interleaved text segments so fine-grained streaming (gap 14) slots in without redesign.
- Rendering order: [Thinking] then interleaved cards in event order then [answer text].

**Thinking block** - `Disclosure` (N11, P21 rung 3 treatment): summary "Thinking" with a live character-count while streaming; **auto-open while reasoning streams, auto-collapses when the first answer text arrives or the turn ends**; user toggle always wins over auto behavior once touched. Body: dimmed secondary text, pre-wrap. Replaces the always-open block (chatTurn.tsx:344-349, reader-chat gap 5).

**ToolCard** (upgrade of chatTurn.tsx:147-170) - collapsed `<details>` row:
- Summary: verb id (mono `badge--verb`), status badge from the glossary (`StatusBadge`; running shows the cyan pulse dot - running pulses, paused is steady, canon), and a **consequence badge when the verb is high** - enriched client-side from a cached `GET /v1/capabilities` lookup (FRONTEND-ONLY; the amber marker foreshadows the pause, P28, L4).
- Body: input and output rendered as read-only key-value rows when they are flat objects (labelled values, mono ids), with the raw JSON inside a `JsonDisclosure`-style collapsed block (P10 - JSON is the escape hatch, not the face). Strings render as text. Pairing logic unchanged (result matches most recent running call of the verb, chatTurn.tsx:82-94).
- No duration/timestamps: events carry none (honest omission; flag in section 12 as a nice-to-have event field, NEEDS-BACKEND).

**StepsCard** (chatTurn.tsx:175-194) - keep the folded-by-step_id checklist (chatTurn.tsx:111-125). Each row: status badge + action verb (mono). Rows are **not** deep-linked: `workflow_step` events carry no workflow id (types.ts:172-234 union, reader-chat section 2), so `#/automations/:wfid/step/:stepId` cannot be built honestly. DEPENDS-BACKEND: add `workflow_id` to the `workflow_step` event; when it lands, each row gains a chevron deep-link chip to its step slide. The card head keeps "workflow - n steps"; the turn's RunLink is the drill-down meanwhile.

**SubagentCard** (chatTurn.tsx:199-234) - keep: "sub-agent" badge, task line, skill chips (mono), and the run handle. The run handle stays `openRun(childRunId)` (opens the global drawer, never moves the deck, DESIGN-v2 overlays). Copy: the handle reads "View run <id>" with the id middle-truncated, full id on `title` + click-to-copy on the id itself (P34). No completion status is invented: the event stream has no subagent-finished event; the card states "delegated" and the drawer is the truth.

**HITL card - the signature amber moment** (upgrade of ChatHitlCard, chatTurn.tsx:238-329) - this is P30/P33's chat-side rendering, visually aligned to `PendingHumanCard` (N15):
- **Amber-orange left accent bar** (`--color-consequence-high`), **steady, never pulsing** (canon: paused is steady). This is the ONLY amber on the whole surface (L4).
- Headline by kind: approval -> "Paused for approval"; clarification -> "The orchestrator needs an answer".
- Body: the question verbatim; `hitl_request_id` mono, middle-truncated, click-to-copy; the plain sentence (approval only): "A person needs to approve this before it runs." (concept canon, P22).
- Approval controls: option buttons (server options, else approve/reject, as today chatTurn.tsx:254-259) but the decision goes through **ArmConfirm** (N14, tone consequence): pressing "approve" arms in place to "Approve this action? It will run immediately." + [Confirm approve] + Cancel - no rubber stamp (P30: "the arm-confirm ritual of the approvals surface still applies"). Reject arms identically ("Reject this action? The agent will be told why - add a note."). Notes: optional auto-growing textarea, placeholder "Notes (optional) - recorded with your decision" (P10 free text lawful).
- Clarification controls: free-text input + Send, no arm (answering a question is low-blast). Enter submits this single-input row (P36).
- Submit: `POST /v1/hitl/{id}/respond` `{decision, notes}` (client.ts respondHitl; app.py:408+). Busy "Recording...". Result states: recorded (ok treatment, decision echoed), already-resolved/expired rendered faithfully from the response status, error with the verbatim reason (L3).
- **Resolution reconciles from the server, not component memory** (P33; the local `resolvedHitls` map, ChatPanel.tsx:86,106-108, is the named anti-pattern): a module-level hitl-resolution store polls `GET /v1/hitl` every 8s while any unresolved hitl card is visible on the active slide, pausing when the slide is inactive (deck quiesce). A pause answered from the Approvals slide (or by another user) flips this card in place; a pause answered here flips Approvals. FRONTEND-ONLY (reader-chat gap 8).
- Footer links: "Open in Approvals" -> `navigate("/approvals")` (the ops-row slide; the deck animates); RunLink when the turn has a run_id.
- First-ever pending_human a user sees: one `CoachMark` (N12, P21 rung 5, `boltrig.coach.first-hitl`): "The kernel paused this action for a human. This is Boltrig working as designed - approve it here or in Approvals."

**Entity-link card** - new composition (existing vocabulary: `.card` + badge + link chip; no new primitive). When a `tool_result` for a `control.*` verb resolves ok, its output is `{upserted, id}` (control_plane.py:102, 113, 121). Render, after the ToolCard, a quiet one-line card: kind badge + "Capability `worker-cheap` saved" + deep-link chip "Open its slide". Mapping:

| verb (tool_result) | link target |
|---|---|
| `control.capability.upsert` | `#/agents/<id>` (agent slide, DESIGN-v2 agents row) |
| `control.workflow.upsert` | `#/automations/<id>` (canvas slide) |
| `control.model_endpoint.upsert` | no keyed slide exists; render the id mono, no link, until a home slide lands |

FRONTEND-ONLY (output shape exists today). This card is the "created entities render in the transcript" contract of chat-as-console (section 8).

**Errors smuggled as text** - there is no typed `error` SSE event; failures arrive as a `text_delta` of "(turn error: ...)" (chat.py:145-146, 207-208, reader-chat section 2). Render them as the text they are - **no string-matching magic** to detect them (brittle, dishonest). DEPENDS-BACKEND: a typed `error` event (reader-chat gap 16); when it lands, render an `ErrorState`-toned block in the timeline instead.

**Degraded** - `text_delta` may carry `degraded:true` (chat.py:197). The turn's text block gets a `badge--degraded` at its edge with TermTip "This answer came from the fallback path. The run has details." (P24: degraded is information, not a wall).

### 5d. Turn footer and message actions

Hover/focus-revealed ghost action row under each assistant message (visible-on-focus for keyboard):
- **Copy** - copies the raw markdown source of `content`. "Copied" wisp.
- **View run** - `RunLink` when `run_id` present (persisted messages carry it, types.ts:151-159).
- Timestamp - relative, absolute on `title`.
- **Regenerate** - DEPENDS-BACKEND, slot reserved as the last action on the LAST assistant message only. The store is append-only (`add_message`, chat.py:95-100, 114-120); no truncate/fork/regenerate route exists (reader-chat gap 9). Do not render until `POST /v1/conversations/{id}/regenerate` (or a truncate-and-resend contract) lands. When it lands: plain button, no arm (regenerating is low-blast; the old answer stays in the audit log), busy "Regenerating...", and the new turn streams as normal. Edit-past-message and branching: same dependency family, explicitly out of scope until the backend contract exists - no UI slot is drawn for them (do not tease what cannot ship).

### 5e. Scroll behavior

(reader-chat section 4: no auto-scroll exists today, and the deck transform fights scroll positions.)
- **Stick-to-bottom**: while streaming, if the user is within 80px of the bottom, each append keeps the view pinned to bottom. Any upward scroll releases the pin.
- **Jump to latest**: when unpinned and new content arrives, a floating pill button (bottom-center of region C, absolutely positioned inside the slide, never fixed) "Jump to latest" scrolls to bottom and re-pins. It also shows a small amber dot if the unseen content includes an unresolved HITL card (the one lawful reuse of amber: it IS the governance signal, L4).
- Per-slide scroll position is stored on slide-exit and restored on slide-enter (deck contract). Reduce-motion: `scrollTo` uses `behavior:"auto"`.

## 6. Region D: the composer

- **Textarea**: auto-growing 2 to 8 rows, then internal scroll. Placeholder "Message the orchestrator...". Paste of multi-line/code content just works (it is a textarea; no paste interception).
- **Keyboard (P36, binding)**: plain **Enter inserts a newline, always**; **Ctrl+Enter (Cmd+Enter on mac) sends**. This supersedes the current Enter-sends handler (ChatPanel.tsx:211-216). A permanent quiet hint under the textarea teaches it: "Enter for a new line. Ctrl+Enter to send." Note for the pattern seat: this is P36 applied as written; if user feedback demands Enter-to-send, that is a fork back to the pattern document (an opt-in behavior setting), not a local deviation.
- **Send**: `btn--primary`, label "Send", disabled when the trimmed input is empty. Sending: optimistic user bubble + a new stream session in the store (section 7), exactly the current request shape: `POST /v1/chat` `{message}` or `{conversation_id, message}` (streamChat, client.ts:696-747; app.py:307-331).
- **Stop - honest semantics** (reader-chat gaps 2 and 12): while THIS conversation is streaming, Send is replaced by a ghost button "Stop" (square icon). Not amber (no governance in play, L4), not red (nothing is destroyed). Pressing it aborts the client reader (`AbortController`) and marks the session "stopped". The partial turn stays on screen, followed by an `InfoCallout tone="info"` - the StoppedNotice: **"Stopped watching. The agent may still be finishing on the server - its work continues and is audited."** (events.py:7: the run keeps producing regardless.) Actions inside the callout: **"Watch again"** (re-attach via `streamRunEvents(runId, {follow:true})`, section 7) and **"Refresh transcript"** (the current reconnect behavior, ChatPanel.tsx:198-209). A true server-side cancel is DEPENDS-BACKEND (`POST /v1/runs/{id}/cancel` does not exist); when it lands, the StoppedNotice gains a second, arm-confirmed action "Stop the run" (N14, tone consequence - it halts governed work).
- **Sending while another conversation streams** is allowed (per-conversation sessions, section 7); Send is only locked for the conversation that is itself streaming (single-flight per conversation preserved from ChatPanel.tsx:147).
- **Actor slot**: the header chip (section 4) is the model/agent picker slot. Nothing interactive in the composer until the backend field exists.
- **Attachment slot**: DEPENDS-BACKEND (no upload route, no attachment field on ChatRequest, reader-chat gap 11). The composer's left icon position is reserved; nothing renders.
- Empty-state prompt chips (EXAMPLE_PROMPTS, ChatPanel.tsx:22-26) stay: clicking one fills the composer (not auto-send), matching the prefill contract (P32: the user always owns the send).
- Composer error (a non-SSE RBAC/validation failure from `POST /v1/chat`, which raises before the first event in the canonical envelope, app.py:307-331): renders directly above the composer as the P15 footer error - `FetchError` semantics, 403 as the calm warn callout with the server reason verbatim, other errors as `ErrorState`. The composer stays enabled (the server is the authority, L3; the UI never pre-guesses a denial).

## 7. The streaming engine (module store, re-attach, off-screen behavior)

New module `ui/src/chatStream.ts`, the `useSyncExternalStore` idiom already used for identity (identity.ts per reader-shell). This replaces the component-local `liveEvents`/`abortRef`/`pendingConvId`/`alive` cluster (ChatPanel.tsx:82-102) and resolves every hazard in reader-chat section 4.

**Shape**
```
sessions: Map<key, Session>   // key = conversation_id, or "draft" until message_start lands
Session {
  key, runId?, convId?,
  pendingUser: string,
  events: ChatEvent[],
  status: "streaming" | "stopped" | "done" | "error",
  error?: string,
  unseen: boolean,            // finished while the chat slide was inactive or another conv was open
}
```

**Contracts**
1. `startSession(convIdOrNull, message)`: creates the session, runs `streamChat` (client.ts:696-747). On `message_start`, re-keys "draft" to the real `conversation_id` and records `run_id` (the existing capture, ChatPanel.tsx:164-166). Events append to the session array **outside React**; subscribers are notified immediately while the chat slide is active, throttled to 1/s while inactive, flushed on slide activation (kills the O(n)-per-event re-render burn while hidden, reader-chat section 4).
2. On clean `message_end`: mark "done", re-fetch the transcript for `convId` and reload the rail (the existing settle sequence, ChatPanel.tsx:175-184), then drop the session. If the slide was inactive or a different conversation was open, set `unseen` first and keep the session until viewed.
3. `stopWatching(key)`: aborts the reader, status "stopped", session and partial events retained (feeds the StoppedNotice, section 6).
4. `attach(key)`: re-subscribes via `streamRunEvents(session.runId, onEvent, {follow:true})` (client.ts:752-796 -> `GET /v1/runs/{run_id}/events?follow=1`, app.py:534-558). The relay **replays its backlog from the start** then follows (events.py:22-77), so on attach the session's `events` array is **replaced wholesale** by the replayed stream - no dedupe heuristics. Known limit, stated honestly in code comments: the backlog window is 500 events and the relay is in-process (events.py:23, 9-10); a 404 `unknown_run` or a replay that ends with no `message_end` falls back to "Refresh transcript" (fetch persisted state). Used by: StoppedNotice "Watch again", stream-drop recovery, and post-remount recovery of a session whose reader died.
5. Stream error (not user abort): status "error", partial turn retained, and the recovery block renders BOTH options: "Reconnect live" (`attach`) and "Refresh transcript" - upgrading today's fetch-only "Reconnect" (ChatPanel.tsx:189-209, 340-347; reader-chat gap 3).
6. Switching conversations or slides never aborts a session (removes the abort in `selectConversation`, ChatPanel.tsx:126). Unmount of the panel no longer kills streams (the store owns the readers); the keep-alive pin makes this mostly moot, but the store makes it true unconditionally.

**Off-screen completion signal** (deck integration)
- The sidebar map's chat row and the minimap chat cell subscribe to the store: **cyan pulse dot** while any session is streaming; **steady cyan dot with a count** when sessions are `unseen`; cleared when the chat slide becomes active and the conversation is opened. (Mirrors the DESIGN-v2 sidebar ops HITL badge mechanic; no poll needed - the store is in memory.)
- One polite announcement through the global live region OUTSIDE the deck (DESIGN-v2 mount policy) per completion while the slide is inactive: "Chat: response ready." Never for streams completed in view.
- The rail row dots (3b) come from the same store.

## 8. Chat-as-console

The Principal's bar 2 made concrete: the chat IS the second client of the verb-space. Nothing here requires the UI to special-case "console" turns - the typed event cards (5c) already render verb traffic; this section pins the contracts.

### 8a. How building an agent by talking works (worked flow)
1. User: "Create a cheap ephemeral worker capability called worker-cheap on the pi runtime."
2. The orchestrator plans and invokes `control.capability.upsert {name:"worker-cheap", runtime:"pi", cost_tier:"cheap", is_ephemeral:true}` through the chokepoint. In the transcript: a **ToolCard** appears - verb `control.capability.upsert` (mono), status running (pulse), **amber conseq-high badge** (every `control.*` verb is high, control_plane.py:49-50).
3. The consequence gate holds it: an **hitl event** arrives and the **amber HITL card** (5c) renders - "Paused for approval", the question, arm-confirmed approve/reject, "Open in Approvals". The same pause is simultaneously in the Approvals inbox (P33: one pause, two renderings, one truth via `POST /v1/hitl/{id}/respond`).
4. On approval (from either surface - the reconciliation poll flips the card), the ToolCard resolves ok and the **entity-link card** renders: "Capability `worker-cheap` saved - Open its slide" -> `navigate("/agents/worker-cheap")`, the deck animates down-and-right to the agent slide.
5. The final answer text summarises what happened; the run is one click away (RunLink).

Editing a workflow by talking is the same shape: "Change the notify step to use ticket.create" -> `control.workflow.upsert` ToolCard -> HITL pause -> entity-link card to `#/automations/<wfid>`.

### 8b. What chat can and cannot do today (honesty ledger)
- CAN, governed: everything with a registered verb - the three `control.*` verbs (control_plane.py:52-89) plus every adapter verb. The cards above render it faithfully.
- CANNOT yet, and the orchestrator should say so rather than the UI pretending: skill upsert, verb/noun authoring, bindings, MCP register/activate, hierarchy, personal-agent config, and **every delete** - these are direct author-gated routes or absent entirely (P31 registry). Each is a BACKEND DEP carried by P31; the chat surface needs no change when they land - new `control.*` verbs automatically render as ToolCards + HITL cards + (with `{upserted,id}` outputs) entity links.

### 8c. The prefilled-composer deep-link pattern (what other surfaces use)
This is the receiving half of `ByChat` (P32/N16), owned by this surface:
- New one-shot module `ui/src/composerPrefill.ts`: `setComposerPrefill(text: string): void` and `consumeComposerPrefill(): string | null` (returns once, then null; module variable, the identity-store idiom; a hash query param is NOT used because `?run=` owns the query slot, router.ts:64-82).
- Any surface: `setComposerPrefill(phrase)` then `navigate("/chat")` - the deck animates to the chat anchor.
- The chat slide consumes the prefill on becoming active: the text lands in the composer, **focused, cursor at end, never auto-sent** (P32: the user owns the send). If the composer already holds a draft, the prefill is appended on a new line rather than destroying the draft (no silent data loss, the P17 spirit).
- The example-prompt chips (empty state) use the same mechanism internally.

### 8d. Parity of the chat surface's own flows
Chat's own management operations must themselves be speakable (L2) - see the table in section 11.

## 9. States (per region, P24 precedence everywhere)

| Region | denied | error | loading (first only) | empty | ready extras |
|---|---|---|---|---|---|
| Rail | warn callout, server reason, no retry | ErrorState + Try again | Skeleton rows x5 | "No conversations yet. Say hello below." | pulse/unseen dots |
| Transcript | non-owner `GET /v1/conversations/{id}` 403 (chat.py:41-50): warn callout with reason verbatim + "Ask an admin to widen your access."; composer hidden for that conversation | ErrorState + Try again (re-fetch transcript) | Skeleton variant="transcript" | EmptyState: title "Start a conversation", body "Ask in plain language - the orchestrator plans, acts through the kernel, and pauses for approval when an action needs a human." + example chips | degraded badge per 5c |
| Composer | inline warn callout above composer with server reason (403 from POST /v1/chat) | ErrorState above composer; 503 `{error:"chat_unavailable"}` renders "Chat is not available on this deployment." verbatim reason (app.py:307-331) | n/a | n/a | Stop replaces Send while streaming |
| pending_human | n/a | n/a | n/a | n/a | the amber HITL card (5c); never a failure, never a spinner, never suppressed (P30) |

Slide-scale denial: chat itself is ungated (DESIGN-v2 grid: row chat gate none), so no whole-slide 403 treatment is needed; per-request denials render as above (L3).

## 10. Keyboard and accessibility

- Ctrl/Cmd+Enter send; Enter newline (P36). Escape: disarms any armed ArmConfirm first; otherwise deck/global semantics (palette/drawer own Escape when open).
- "/" focuses rail search when focus is not in an editable (P36).
- Deck chord Ctrl+Alt+Arrow suppressed in composer/inputs (DESIGN-v2 guardrail).
- HITL card: when a new hitl event arrives on the ACTIVE slide, move focus is NOT stolen; the Jump-to-latest pill carries the amber dot instead. The card's first control is reachable in tab order; ArmConfirm confirm-on-Enter only while the confirm button is focused (P36).
- Transcript container `aria-live="polite"` active / `"off"` inactive; `aria-busy` while streaming (existing, ChatPanel.tsx:273). Event cards are regular DOM (details/summary keyboardable natively).
- All copy/click-to-copy controls carry `aria-label` naming the object ("Copy run id"). Focus ring preserved everywhere (styles.css:1581-1590); 44px targets under `(pointer:coarse)` for chips, chevrons, rail rows (styles.css:1593-1604).
- Reduce-motion: no pulse animations (steady dots), skeleton static, auto-scroll instant (`:root.reduce-motion` zeroes durations, reader-shell section 2).

## 11. Parity table (P31 format: UI action | verb path | chat phrasing | status)

| UI action | Verb path / route | Chat phrasing | Status |
|---|---|---|---|
| Send message | `POST /v1/chat` (app.py:307-331) | is itself the chat | exists |
| New conversation | none (client reset; id from first `message_start`) | omit conversation_id on next send | exists |
| Delete conversation | `DELETE /v1/me/conversations/{id}` (access_routes.py:131-144) | "Delete my triage conversation" -> orchestrator performs the same soft close | exists (route); orchestrator tool for it: verify, else BACKEND DEP `control.conversation.close` |
| Rename conversation | none | "Rename this conversation to Invoices" | DEPENDS-BACKEND (`PATCH /v1/conversations/{id}` or `control.conversation.retitle`; gap 13) |
| Stop watching | client abort only | n/a (client-local) | exists; honest copy mandatory |
| Stop the run | none | "Cancel that run" | DEPENDS-BACKEND (`POST /v1/runs/{id}/cancel`; gap 12) |
| Regenerate | none | "Try that answer again" | DEPENDS-BACKEND (gap 9) |
| Answer HITL (approve/reject/clarify) | `POST /v1/hitl/{id}/respond` (app.py:408+) | "Approve the pending ticket.create" -> same route | exists; same route serves Approvals (P33) |
| Open sub-agent run | `GET /v1/runs/{id}/events` via drawer | "Show me what the sub-agent did on run X" | exists |
| Build agent / edit workflow / set endpoint via chat | `control.capability.upsert` / `control.workflow.upsert` / `control.model_endpoint.upsert` (control_plane.py:52-89) | natural language; orchestrator invokes; 202-equivalent = hitl event in-stream | exists (renders per 5c/8a) |
| Pick model/agent for the conversation | none (`actor` hardcoded, chat.py:172-173) | "Use the research agent for this conversation" | DEPENDS-BACKEND (ChatRequest field; gap 10) |
| Attach a file | none | n/a | DEPENDS-BACKEND (gap 11) |

## 12. Dependency register (consolidated, faithfully tagged)

FRONTEND-ONLY (buildable now):
1. Markdown rendering per 5b - the ONE new dependency, already a recorded decision (DESIGN-v2 call 5). Requirements are the contract; library choice is the implementer's within them.
2. Stream store + per-conversation sessions + Stop (client abort) + StoppedNotice (gaps 2 partial, 6, 7).
3. True live re-attach via `streamRunEvents(runId,{follow:true})` (client.ts:752-796; gap 3), replacing fetch-only Reconnect.
4. Delete conversation UI with ArmConfirm (gap 4; route exists).
5. Collapsible thinking, stick-to-bottom + jump-to-latest, per-message timestamps, copy actions (gap 5).
6. Rail search, date grouping, relative-time refresh, closed-conversation disclosure (gap 6).
7. Composer autogrow + P36 keys (gap 7).
8. HITL resolution reconciliation via `GET /v1/hitl` poll, slide-quiesced (gap 8); shared module so Approvals and chat agree.
9. Ordered turn timeline + consequence enrichment of ToolCards from cached `/v1/capabilities`.
10. Entity-link cards from `control.*` tool_result outputs.
11. Off-screen completion signal (store-driven sidebar/minimap dots + live-region announcement).

DEPENDS-BACKEND (slot designed, control not rendered until the contract exists):
- Regenerate / edit / branch: append-only store (chat.py:95-120); needs a regenerate or truncate-and-resend route (gap 9).
- Model/agent picker: ChatRequest field + executor plumbing past the hardcoded `chief-of-staff` (chat.py:168-173; gap 10). Slot: the header actor chip -> EntityPicker.
- Attachments: upload route + message attachment field (gap 11). Slot: composer left icon position.
- True cancel: `POST /v1/runs/{id}/cancel` (gap 12; events.py:7). Slot: second action in StoppedNotice, arm-confirmed.
- Rename / auto-title: PATCH route or `control.conversation.retitle` (gap 13). Slot: rail row second action + header title edit.
- Fine-grained token streaming of the final answer (chat.py:189-199; gap 14). Timeline type already accommodates it.
- Typed `error` SSE event (gap 16) for distinct failure rendering; until then errors render as the text they arrive as.
- `workflow_id` on `workflow_step` events, for step-slide deep links from StepsCard.
- Message feedback / per-turn cost events (gap 15): no UI slot drawn - do not tease.
- Chat-parity BACKEND DEPs for console writes (skills, verbs, bindings, MCP, hierarchy, personal agent, deletes) are owned by P31's registry; chat inherits them with zero UI change.

## 13. Exact API surface used

| Call | Where | Grounding |
|---|---|---|
| `GET /v1/conversations` | rail, 30s quiesced poll | app.py:333-348; ChatPanel.tsx:74 |
| `GET /v1/conversations/{id}` | transcript load, post-turn settle | app.py:349-372; ChatPanel.tsx:110-122 |
| `POST /v1/chat` (SSE) | send | app.py:307-331; client.ts:696-747 |
| `GET /v1/runs/{run_id}/events?follow=1` (SSE) | re-attach / watch again | app.py:534-558; client.ts:752-796; relay events.py:22-77 |
| `DELETE /v1/me/conversations/{id}` | rail delete | access_routes.py:131-144; client.ts:596-601 |
| `POST /v1/hitl/{id}/respond` | HITL card | app.py:408+; chatTurn.tsx:269 |
| `GET /v1/hitl` | resolution reconciliation poll | ApprovalsPanel's existing source (reader-shell section 4) |
| `GET /v1/capabilities` | ToolCard consequence enrichment (cached, on demand) | shared read surface (P31 rule 3) |

SSE event union consumed: exactly types.ts:172-234 (message_start, text_delta [+degraded], reasoning_delta, tool_call, tool_result, subagent, hitl, workflow_step, message_end). No invented events.

## 14. CSS and component register additions

- New classes (after the v3 layer, `--color-*` tokens only): `.chat2` slide grid, `.chat2__rail`, `.conv-group`, `.conv-item__dot`, `.chat2__head`, `.chat2__transcript`, `.chat-md` (markdown scope), `.chat-code` (fence chrome), `.chat-jump` (pill), `.chat-stopped`, `.chat-entity` (entity-link card), upgraded `.chat-hitl` (amber left bar via `--color-consequence-high`), `.chat-turn__actions`.
- Primitives consumed from the register: N11 Disclosure (thinking, closed conversations, JSON in ToolCards), N13 Skeleton (rows + new "transcript" variant), N14 ArmConfirm (delete, HITL decisions), N12 CoachMark (first HITL), N16 ByChat receiving half (`composerPrefill.ts`). The HITL card is the chat rendering of N15's anatomy per P33 (shared tokens and copy; the console PendingHumanCard and this card must look like siblings).
- New modules: `ui/src/chatStream.ts` (section 7), `ui/src/composerPrefill.ts` (8c), `ui/src/panels/markdown.tsx` (5b wrapper). `chatTurn.tsx` upgraded in place (timeline) - the Run drawer inherits it.
- No portals, no toasts, no `position:fixed`, no new UI framework (reader-shell section 3; DESIGN-v2 call 5).

## 15. Copy deck (canonical strings)

- Page lead (PageIntro retained): "Talk to the orchestrator in plain language; it plans, calls tools, and asks for approval when an action needs a human." (existing, ChatPanel.tsx:231).
- Composer hint: "Enter for a new line. Ctrl+Enter to send." (mac: "Cmd+Enter to send.")
- StoppedNotice: "Stopped watching. The agent may still be finishing on the server - its work continues and is audited." Actions: "Watch again" / "Refresh transcript".
- Stream drop: "The live stream dropped. Your turn is still running on the server." Actions: "Reconnect live" / "Refresh transcript".
- HITL approval headline: "Paused for approval". Clarification headline: "The orchestrator needs an answer". Approval body sentence: "A person needs to approve this before it runs."
- Approve arm: "Approve this action? It will run immediately." Reject arm: "Reject this action? The agent will be told why - add a note."
- Delete arm: "Delete '<title>'? Its transcript stays in the audit log."
- Empty transcript: title "Start a conversation"; body "Ask in plain language - the orchestrator plans, acts through the kernel, and pauses for approval when an action needs a human."
- Empty rail: "No conversations yet. Say hello below."
- Degraded gloss: "This answer came from the fallback path. The run has details."
- First-HITL coach mark: "The kernel paused this action for a human. This is Boltrig working as designed - approve it here or in Approvals."
- Tone rules per P22: sentence case, no exclamation marks, ids/verbs mono, no em or en dashes anywhere.

## 16. Build order and acceptance

1. Slide-frame layout + flex scroll regions (delete the vh caps) - visual parity with today.
2. `chatStream.ts` store; port send/settle/drop paths; Stop + StoppedNotice; re-attach.
3. Rail: grouping, search, delete ArmConfirm, dots, closed disclosure.
4. Markdown module + code fences + copy actions (the dependency lands here).
5. Timeline upgrade in `chatTurn.tsx` (ordered cards, collapsible thinking, consequence enrichment, entity-link cards, HITL card upgrade + reconciliation poll). Verify the Run drawer still renders identically improved.
6. Scroll engine (stick-to-bottom, jump pill), composer keys, prefill consumer, sidebar/minimap signals, coach mark.

Acceptance checks an engineer can run: send a turn, navigate two slides away mid-stream, return - the turn is intact and live (store + keep-alive). Kill the network mid-stream - partial turn + both recovery actions. Ask the orchestrator to create a capability - ToolCard with amber badge, amber HITL card, approve via Approvals slide - the chat card flips within 8s; entity-link card navigates to the agent slide. Press Enter in the composer - newline, not send. Delete a conversation - arm-confirm in row, no `window.confirm` anywhere. Trigger a 403 (non-owner conversation) - calm warn callout with the server's exact reason.