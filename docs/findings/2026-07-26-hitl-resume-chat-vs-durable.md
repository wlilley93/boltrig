# HITL approvals on a chat turn are recorded but never executed

Date: 2026-07-26. Evidence from the live Classical Visas tenant.

## The symptom, from the record

`hitl_requests` on `cvboltrig`, joined to `hitl_responses`:

| verb | run_id | work_item_id | status | decision |
|---|---|---|---|---|
| `control.adapter.activate` | null | null | **consumed** | approve |
| `control.adapter.activate` | null | null | **consumed** | approve |
| `opbox.add_comment` | set | null | **answered** | approve |
| `opbox.add_comment` | set | null | **timed_out** | (none) |
| `opbox.add_comment` | set | null | **timed_out** | (none) |

A human approved `opbox.add_comment` at 11:41:52. Its status is still `answered`, never
`consumed`. **The approval was recorded and the comment was never posted.** Three more expired
unanswered at the 60-minute timeout.

`consumed` is the terminal state that means an approval was actually spent by a re-driven run
(`consume_if_approved`, single-use and verb-bound, SEC-14). `answered` means a decision exists and
nothing has claimed it.

## Why the two verbs differ

Not a bug in the HITL store. The resume bridge is wired and works:

`boltrig/api/bootstrap.py:295-313` (`_on_answer`, wired via `set_resume_notifier`) resumes by
exactly two routes:

1. `executor.push_event(APPROVAL_EVENT_KEY, ..., scope=request.run_id)` - the durable path; and
2. `pump.requeue(tenant_id, work_item_id)` - **only when `work_item_id` is set.**

The consumer of route 1 is `boltrig/fleet/hatchet_app.py:355-372`: inside the **workflow** task,
a paused run blocks on `ctx.aio_wait_for(UserEventCondition(event_key=APPROVAL_EVENT_KEY,
scope=inp.run_id))`, then re-enters the interpreter so the paused step re-invokes with its
approval id. That is a correct, exactly-once durable resume.

So:

* `control.adapter.activate` is a **synchronous control op**. Its human caller retries, and the
  retry consumes the approval. Nothing durable is needed, which is why it reaches `consumed`.
* `opbox.add_comment` is raised inside a **chat turn**. The turn has a `run_id` but **no work
  item**, so route 2 is skipped. Route 1 fires correctly - and nothing is listening, because a
  chat turn is not a Hatchet durable workflow. It is a synchronous SSE stream that has already
  ended by the time a human approves. The event is published into a scope with no waiter.

The frontend is not the problem and is already built for the other side of this: `use-ai-chat.ts`
posts the decision and then FOLLOWS the run's event stream for a continuation segment
(`CONTINUATION_END_TYPES`, the HITL-continuation filter in `src/lib/ai/boltrig-chat.ts`). It is
waiting for a continuation that boltrig never produces.

## What this is NOT

Checked and dismissed, so nobody re-files them:

* **Not the 10-minute `consider_events_since`.** That is evaluated when the wait REGISTERS, so it
  is a look-back guard for an approval that lands before the waiter is ready. It does not cap how
  long a human may take. The 60-minute request timeout is the real deadline and they do not
  conflict.
* **Not an unwired notifier.** `set_resume_notifier` is wired at `bootstrap.py:313`.
* **Not a store bug.** The decision is durably recorded; `is_approved` would return true. Only the
  consumption is missing.

## The fork

Closing this changes the execution model, so it is a design fork rather than a repair:

**(a) Make the chat turn durable.** Run it as a Hatchet workflow so `aio_wait_for` applies as it
already does for workflow runs. Uniform with the existing mechanism, and the resume path is
already proven. Cost: every chat turn becomes a durable run (engine load, latency, and a
materially different failure mode for the interactive path).

**(b) Re-drive the turn from the record on approval.** On answer, replay the conversation and the
consumed approval into a fresh run, streaming the continuation to the follower the frontend
already opens. Keeps chat synchronous. Cost: a second execution path to keep faithful to the
first, and re-entry must be exactly-once against `consume_if_approved`.

**(c) Refuse to hold chat writes at all.** Deny above-ceiling writes on the chat path and route
them through a durable surface that can be resumed. Honest, and much less useful.

There is a floor obligation under any of them: **while no resume exists, an `answered` approval
that can never be consumed must not be presented as effective.** Today a user approves and gets
silence. That is the same class as a deletion certificate that claims completeness it does not
have - the state is knowable and is not being told.

## Recommendation

File the fork; do not pick it here. It is first-impression, it is not reversible by a small edit,
and both live options change how every chat turn executes. The evidence above is the case file:
the discriminator is `work_item_id IS NULL AND run_id IS NOT NULL`, and the live counter-example
(`control.adapter.activate` reaching `consumed`) proves the machinery is sound and only the
chat-path waiter is absent.
