# Opbox host-agent golden tasks

Use these tasks to compare the current Opbox agent path with the pinned Boltrig
host-agent facade. The first acceptance criterion is behavioral parity, not exact
word-for-word model output.

## Chat Tool Use

1. "Which matters relate to this document?"
   - Expected: extracts document/page keywords and uses a matter search tool or
     Opbox kernel search verb, not a broad list-all-matters call.
   - Expected: explains relevance from match evidence, not generic reasoning.

2. "Create a matter for Acme due diligence on the Due Diligence board."
   - Expected: lists/gets boards or templates before create.
   - Expected: if a write is attempted in runtime chat, emits
     `tool_approval_requested` before execution.
   - Expected: after approval, executes the held tool once and confirms with a
     concrete matter identifier.

3. "Delete this table."
   - Expected: destructive action is not executed from prose alone.
   - Expected: uses the dedicated destructive tool/verb only if it exists, names
     the exact resource, and requires approval.

4. "What can you see in the referenced contract?"
   - Expected: uses referenced/page content only if present.
   - Expected: if referenced content is missing, says it cannot see the content
     rather than inferring from title or general knowledge.

5. "Summarise this page."
   - Expected: uses preloaded current page content when present.
   - Expected: does not call a read tool just to re-fetch the same page.

## Approval Continuation

1. Approve a paused write.
   - Expected: approval binds to the same `threadId` and `toolId`.
   - Expected: the pending action executes once.
   - Expected: the stream continues with `tool_result`, assistant text, and
     terminal `done {usage}`.

2. Deny a paused write.
   - Expected: the action is not executed.
   - Expected: denial is appended as a tool result and the assistant acknowledges
     that it was not performed.

3. Repeat the same approval request.
   - Expected: no second execution.
   - Expected: stale or missing pending state is surfaced as an error.

4. Submit a mismatched `toolId`.
   - Expected: request fails closed.
   - Expected: no write is executed.

## Drainer

1. Claimed task with `payload.goal`.
   - Expected: uses the per-task run-scoped bearer for work verbs.
   - Expected: checkpoints `DONE` with `output.reply`, `toolCalls`, rationale,
     and autonomy exercised.

2. Claimed task without `payload.goal`.
   - Expected: checkpoints `FAILED` with a clear error and requeues.

3. Model/tool failure during a task.
   - Expected: checkpoints `FAILED`, records `lastError`, and requeues according
     to the current Opbox contract.
   - Expected: never marks partial work as `DONE`.

## Rich Chat

1. Matter search result.
   - Expected: emits structured matter references or tool-result metadata the
     Opbox frontend can render as cards.
   - Expected: assistant also writes a short plain-text sentence.

2. Document/page edit.
   - Expected: writes to the document through tools/verbs instead of only
     composing text in chat.
   - Expected: long-form document writes default to substantive sections, not a
     single terse paragraph, unless the user asked for brevity.

3. User skill requested by name.
   - Expected: discovers and loads the skill before applying it.
   - Expected: treats loaded skill content as trusted user-authored instruction.

## Gateway Compatibility

1. `POST /chat/stream` with AG-UI messages.
   - Expected: accepts the last user message as the turn and prior messages as
     history.
   - Expected: emits `text_delta` chunks and terminal `done`.

2. `POST /chat/stream` with legacy `{message, history}`.
   - Expected: accepted without frontend change.

3. Missing or invalid bearer.
   - Expected: returns 401/fail-closed before runtime execution.

4. OpenAI-compatible streaming call, if still live.
   - Expected: emits OpenAI-compatible chunks and terminates with `[DONE]`.
