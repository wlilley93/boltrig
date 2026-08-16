# 0028 - Conversational routines in v1; Advanced authoring in v2

- Status: accepted
- Date: 2026-08-14

## Context

The existing Automations surface exposed the workflow engine as a graph editor.
That representation is useful for expert orchestration, but it asks an ordinary
user to choose kernel verbs, wire steps and understand execution topology before
they can describe recurring work.

The v1 product question is smaller: what should happen, when should it happen,
which shipped companion should present it, and where does the person see or
intervene in the result?

## Decision

V1 exposes **Routines** as one plain-language goal plus one trigger. Each
occurrence creates an owner-scoped conversation before execution. The normal chat
runtime performs the work under the triggering principal's existing grant ceiling.
Its tool receipts, questions, approvals and final answer are persisted in that
conversation, which appears in Recents and links to Runs.

Familiar and Jarvis are the only v1 companion choices. Completion notifications
use only the account's existing verified notification routes. Approval and
question responses remain canonical HITL records and resume the same durable
routine occurrence; they do not create a parallel inbox-only workflow.

The graph editor, arbitrary step authoring and other expert controls are
**Advanced v2**. Existing graph definitions remain stored and executable through
their existing governed contracts, but the v1 Worker route neither edits nor
silently rewrites them.

## Binding conditions

1. A routine never widens the owner's grants, workspace scope or provider access.
2. Trigger payloads and human answers enter the model as explicitly untrusted data.
3. Every occurrence has one deterministic conversation binding and one durable
   execution identity; retries may replay, but may not create duplicate chats.
4. HITL waits on the exact canonical request scope and re-enters the same
   conversation after the recorded response.
5. The run chat is the canonical in-product result. Notifications are optional
   delivery side channels, never proof of completion.
6. V1 definitions contain no graph steps. Advanced v2 must receive a separate
   product, authority and migration review before it becomes reachable again.

## Consequences

- The common path is input -> governed AI -> visible run chat.
- Scheduled work looks like a conversation the user did not start, rather than an
  opaque background job.
- Approvals and clarifying questions happen where the work is already visible.
- The existing workflow/Hatchet engine remains the execution backbone; n8n or a
  second scheduler is not introduced.
- Advanced graph data is preserved for v2 instead of being deleted or coerced into
  the narrower v1 contract.
