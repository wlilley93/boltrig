# Decision 0018: a held write is resumed by replaying the record of the call

**Status:** decided, first instance, odd bench of one. **Date:** 2026-07-26.

## The matter

A human-in-the-loop APPROVAL raised inside a CHAT turn was recorded and never executed.

Ground truth, live Classical Visas tenant (`cvboltrig`):

| verb | run_id | work_item_id | status | decision |
|---|---|---|---|---|
| `control.adapter.activate` | null | null | **consumed** | approve |
| `opbox.add_comment` | set | null | **answered** | approve |
| `opbox.add_comment` | set | null | **timed_out** | (none) |

A human approved `opbox.add_comment` at 11:41:52. It sits at `answered`, never `consumed`, and
the comment was never posted. `consumed` is the terminal state meaning an approval was actually
spent by a re-driven run.

Full evidence and the mechanism trace: `docs/findings/2026-07-26-hitl-resume-chat-vs-durable.md`.

## HELD

Disposition (b) prevails, but only in the corrected form the bench now defines: on answer, RE-
ENTER THE SAME RUN IDENTITY in the process that owns the caller's event stream and re-invoke the
RECORDED CALL (canonical params sealed at pause time, approval id taken from a paused
checkpoint), never a model-regenerated one; (a) is refused because its execution locus has no
path to the subscriber, and (c) is refused as a disposition while its "no instrument without a
redeemer" principle is adopted as a subsidiary holding and ordered.

## Ratio (the citable principle)

A held write is resumed by replaying the RECORD OF THE CALL, not by replaying the agent that
produced it, and not by making the caller's envelope durable. Durability of the envelope is a
delivery trigger; correctness comes from re-invoking canonical, checkpointed params under the
ORIGINAL run identity, so that approval_request_fingerprint (boltrig/kernel/hitl.py:109-145,
which binds initiator.run_id at :130 and the params verbatim at :118-121) matches by
construction and the ANSWERED->CONSUMED CAS (hitl.py:337-368; boltrig/store/postgres.py:644-651)
makes execution exactly-once. Three corollaries bind: (1) a resume design that mints a FRESH run
id, or that re-derives the call from a non-deterministic runtime, is void against SEC-14 and
degrades to the very symptom it is built to cure; (2) a resume must execute in the process that
owns the run's EventRelay, because the relay is per-Kernel and in-process
(boltrig/kernel/__init__.py:69; boltrig/kernel/events.py:72-88) and a publisher in another
process is a publisher into a stream nobody can subscribe to; (3) the system does not need to
resume an AGENT in order to execute a CALL a human authorised, so the absence of a re-enterable
runtime (boltrig/fleet/codex_runtime.py:228-233: token revoked in `finally`, no session id) is
not a reason to refuse the hold. Subsidiary holding, adopted from the losing (c): an approval
instrument must never be minted on a lane that has no redeemer; the gate that mints it must be
able to name the redeemer from the record, and that gate is what proves the fix has not
regressed.

## Reasons

FINDINGS OF FACT (verified against source, not accepted from the advocates)

F1. The relay is per-process and per-Kernel. `Kernel.__init__` builds its own relay at
boltrig/kernel/__init__.py:69, and `EventRelay` holds `_subs`/`_backlog`/`_seq` as plain in-
memory dicts (boltrig/kernel/events.py:72-88). The chat SSE subscriber runs in the API process
(boltrig/fleet/chat.py:539-545 subscribes; boltrig/kernel/app.py:520-526 forwards). The Hatchet
worker builds its OWN kernel (boltrig/fleet/hatchet_app.py:277-300, `_default_bootstrap` ->
`build_kernel_async`) and therefore its own relay. A chat turn executed there would publish
every text_delta, tool_call and hitl frame into a relay the browser cannot reach. That is not
"added latency on the interactive path"; it is a cross-process event bus as a PRECONDITION to a
single durable chat token. Advocate (b) is right and this fact alone defeats (a) as framed.

F2. The mechanism (a) calls "proven" has never run and is not tested. No process in the shipped
stack serves the durable tasks: docker-compose.yml runs only `uvicorn boltrig.api.asgi:app`
(line 147) and `python -m boltrig.api.worker` (line 196); `boltrig/fleet/hatchet_worker.py` is
started nowhere, and `boltrig/api/worker.py:_run` builds a `HatchetExecutor` and runs the PUMP,
never a Hatchet worker. Further, tests/integration/test_durable_resume.py exercises the resume
entirely through `LocalDurableExecutor` by calling `run_workflow_body` directly (its file
docstring says so; the gated case at ~lines 395-428 answers, then re-calls `run_workflow_body`
twice). `ctx.aio_wait_for` at boltrig/fleet/hatchet_app.py:350-364 has neither a test nor a
running consumer. So the PROVEN property is not the durable wait. It is record-driven re-entry:
`run_workflow_body` re-called with the same payload converges because the params come from the
workflow snapshot (boltrig/workflows/interpreter.py:290-297) and the approval id comes from the
paused checkpoint (interpreter.py:269-274). The wait is only the trigger, and it is the unproven
part. This reframes the fork and is the single most important correction in this judgment.

F3. "Replay into a FRESH run" is void on the source. `approval_request_fingerprint` folds
`initiator.run_id` (hitl.py:130) into the digest, and `consume_approved_by` compares with
`hmac.compare_digest` (hitl.py:361). A new run id cannot match, so the gate mints a SECOND
request (approval_gate.py:140-156): approve, wait, be asked again. Disposition (b) AS STATED IN
THE MATTER is therefore foreclosed by the system's own authorisation invariant. Advocate (b)
conceded and tightened; advocate (c) identified it correctly. Only the tightened form survives,
and the bench adopts the tightened form under its own definition.

F4. The three-line "just pass work_item_id" theory is a dead end. `pump.requeue` returns None
unless the item is AWAITING_HUMAN or BLOCKED (boltrig/fleet/pump.py:430-434). A chat turn's item
is created IN_FLIGHT (chat.py:704-710) and settles DONE/FAILED (chat.py:790, 803), because
`PendingHuman` never escapes to chat at all: boltrig/kernel/mcp.py:388-393 converts it into
`{"isError": True, "text": "pending approval: <id>"}` and the Codex cell keeps talking. The only
writers of AWAITING_HUMAN are the escalation paths (pump.py:511-533 `_park`). Advocate (c) is
correct and I so find. Consequently I do NOT order the `work_item_id=context.run_id` parity
change advocate (a) proposed for approval_gate.py:140-155: it is inert on the chat lane and mis-
binding on the org lane, where `context.run_id` is the pump's run id and the work item id is a
separate value.

F5. The canonical params are durable NOWHERE. The run event redacts (`_event_safe`,
dispatch.py:95-111); the approval display context redacts (approval_gate.py:34-47); the chat
stream carries only key names (`_summarise_params`, dispatch.py:77-84); the persisted assistant
message carries the projected events (chat.py:426-436). The fingerprint is one-way. So EVERY
disposition that executes a held write must add exactly one new durable artefact. That cost is
common to (a) and (b) and discriminates between them not at all. Advocate (a) is right about
this and advocate (b) conceded it honestly; both are credited.

F6. The stream must be reopened. `_safe_exec` closes it in its `finally` (chat.py:665-666) and
`subscribe` returns immediately for a closed key (events.py:157-158). `reopen` is roughly four
lines and seq monotonicity already survives by design (events.py:84-86). Verified as advocate
(b) stated.

F7. `sweep_run_scoped` is called only by the org lane (pump.py:584). The chat lane never sweeps,
so a run-scoped seal on a chat root run survives the turn. That makes the sealed-call seam
usable here, and it makes an explicit sweep MANDATORY or the seal leaks.

F8. `resume_since` exists server-side and names this exact use
(boltrig/kernel/hitl_http.py:76-88, 104-135; boltrig/kernel/app.py:783-808).

CORRECTIONS TO THE ADVOCATES, BY FILE:LINE

To (a): (i) "the existing aio_wait_for path applies unchanged" is false and was conceded, but
the deeper error stands uncorrected in the case: the path is not merely inapplicable, it is
untested (hatchet_app.py:350-364) and unserved (docker-compose.yml, no `hatchet_worker`), so
"uniform with the proven mechanism" misdescribes the record. (ii) The citation of
ui/src/api/sse.ts:216-243 and ui/src/panels/chat/useChatStreamActions.ts:240-250 as the follower
that would consume `?since=resume_since` is wrong on the source: `streamRunEvents` accepts only
`{signal, follow}` and never sends `since` (grep of ui/src returns exactly one hit, sse.ts:225,
for `follow=1`). The `?since=` consumer is the Opbox client named in
docs/findings/2026-07-26-hitl-resume-chat-vs-durable.md, not this repo's console. Not fatal,
since hitl_http.py:82-88 declares the cursor "an optimization, never load-bearing", but the
record must be straight. (iii) (a)'s own escape hatch, "register the chat task on a worker
inside the API process so the relay stays in-process", concedes the whole matter: it keeps the
API process as the executor and buys an engine dependency for a trigger the answer callback
already provides.

To (b): (i) its formal disposition as filed ("a fresh run") is void per F3; the identity of the
winning disposition is the corrected one, not the filed one. (ii) Its build item (f), a new
run_id -> conversation lookup or a new `conversation_id` column on WorkItem, is unnecessary:
`conversation_id` is already in `ctx.extra` (chat.py:729-733) and therefore inside the context
envelope that must be sealed anyway. Derive it; do not add a column. (iii) Its proposed
`get_answered_hitl_by_fingerprint` store read plus a new index on
`hitl_requests.request_fingerprint` is unnecessary and is stored-beside state: the paused
checkpoint already carries `hitl_request_id` (boltrig/models/work.py:87), which is exactly how
the interpreter resolves it (interpreter.py:271-273). Not ordered. (iv) Its fallback ("if the
sealed call is unavailable, re-drive from the transcript and let the fingerprint adjudicate") is
REJECTED: it re-imports the probabilistic failure its own objection identified. Fail closed
instead.

To (c): (i) FACT 4 is overstated. `consume_approved_by` voiding on `timeout_at`
(hitl.py:351-355) is not a wall clock the resume "does not own": `answer()` already refuses an
overdue request (hitl.py:288-292) and fires the notifier synchronously (hitl.py:308), so the
exposed window is the resume's own latency, measured in milliseconds. It is nonetheless a real
design constraint, and it is why the orders require the recorded call to be invoked BEFORE any
model narration. (ii) Its claim that (a) and (b) each "add a second redeemer/consumer" of the
CAS is corrected: under these orders the chat lane calls the same `kernel.invoke` chokepoint the
interpreter calls, and `consume_approved_by` gains no new semantics and no new caller class.
(iii) Its findings at pump.py:430-434, mcp.py:388-393 and codex_runtime.py:228-233 are accepted
in full and are the best factual work in the case file.

WHY (c) LOSES ON THE MERITS

(c)'s argument is valid and its conclusion does not follow. It proves there is no resumable
AGENT turn. The goal does not require one. The goal requires that a held write execute under the
approver's authority with the approval in the same audit tree as the action, and that is a
property of the CALL, not of the agent. Once the canonical call is in the record, executing it
is deterministic, and the model is needed only to narrate afterwards, where it carries no
authority. (c) would cap the flagship surface permanently on a premise that the orders below
falsify within one commit. Its honest floor is retained exactly where it belongs: in the
residual cases (Order 6), not as the disposition.

WHAT IS NOT FORECLOSED BY BINDING CONTEXT

Nothing here is foreclosed by boltrig decision 0012 or by [2026] VJS-PC 20 cond.(1). Hatchet is
an execution engine, not a model runtime; the resume re-enters `kernel.invoke` and, for
narration, `_drive` -> spawner -> runtime resolver, so the multi-runtime seam and its re-wirable
non-Codex leaf are untouched by any of the three. (a) is refused on the substrate (F1, F2), not
on governance. (b)-as-filed is foreclosed, but by the code's own authorisation invariant
(SEC-14, hitl.py:130 with hitl.py:361), which binds in the same practical sense. The steering
(consolidation over fragmentation; derive rather than store beside) cuts for record-replay and
against a second LANE. The adopted form adds no lane: it adds an entry condition to the existing
`_drive` and re-enters the one chokepoint.

## Orders

### Order 1

ORDER 1 (foundation, no preconditions). Add a DISTINCT sealed-credential kind and id segment for
a held call, mirroring the precedent that already exists for exactly this reason:
`adapter_bearer_cred_id` (boltrig/kernel/credentials.py:52-55) uses a distinct `adapter_bearer:`
segment and a distinct kind so it can never be resolved into a verb param. Add
`held_call_cred_id(run_id, request_id)` -> `run:<run_id>:held_call:<request_id>` with kind
`held_call`, and confirm `_resolve_run_scoped` (credentials.py:190-215) refuses it because it
checks `kind != _SECURE_ANSWER_KIND`. PROOF: a test asserting that a model-supplied param of the
form `run:<run_id>/held_call:<id>` raises CredentialResolution and resolves to nothing.
Rationale: without this, sealing the held call under the SEC-181 secure-answer kind would let a
cell exfiltrate its own pending write's params through a reference in a later param.

### Order 2

ORDER 2 (precondition: Order 1). Make the pause durable at the chokepoint. In
boltrig/kernel/dispatch.py, in the `except PendingHuman` branch (dispatch.py:300-306), after
`_emit_pause`, resolve the ROOT run exactly as `_emit_pause` already does
(`context.parent_run_id or context.run_id`, dispatch.py:206-209) and (i) write
`store.upsert_checkpoint(tenant_id, root_run_id, step=f"held:{call_id}", status="paused",
hitl_request_id=e.hitl_request_id)`, using the reserved `held:` prefix so it can never collide
with the interpreter's `_ck(step_id)` key, and (ii) seal the canonical call `{noun, verb,
params, ctx_envelope}` under Order 1's kind, owner = `context.on_behalf_of or context.actor`. Do
NOT put params in the checkpoint `output` column: it is plain JSON and would become a second
secret store, which is precisely what `_event_safe` (dispatch.py:95-111) and
`_approval_display_context` (approval_gate.py:34-47) exist to prevent. PROOF FROM THE RECORD:
after a chat turn hits a gated verb, `run_checkpoints` holds one row for the chat ROOT run with
status `paused` and the request id, and `credential_refs` holds one `held_call` row. This is the
ONE genuinely new durable write in the whole disposition; every other build item below is
wiring.

### Order 3

ORDER 3 (no preconditions, may land in parallel with 1-2). Add `EventRelay.reopen(tenant_id,
stream_id)` next to `close` (boltrig/kernel/events.py:118-131), dropping the key from `_closed`
only. Do not touch `_seq`: monotonicity across a resumption is already guaranteed by design
(events.py:84-86), which is what makes the `?since=` cursor safe. PROOF: a test that closes a
stream, reopens it, and receives a live event on a fresh subscribe (today `subscribe` returns
immediately for a closed key, events.py:157-158).

### Order 4

ORDER 4 (preconditions: Orders 1, 2, 3). Build the resume and its trigger. (a)
`ChatService.resume_held_write(tenant_id, run_id, hitl_request_id)` in boltrig/fleet/chat.py,
sibling to `regenerate_turn` (chat.py:570). It reads the paused `held:` checkpoint, unseals the
call, derives `conversation_id` from the sealed ctx envelope (it is already in `ctx.extra`,
chat.py:729-733 - do NOT add a column and do NOT add a fingerprint index), reopens the relay
stream, and THEN, BEFORE ANY MODEL WORK, calls `kernel.invoke(noun, verb, params,
ctx_from_envelope, approval_id=<request id>)` on the SAME run id. Model narration, if any, runs
AFTER the write via the unchanged `build_turn_executor`, carries no authority, and must never
gate the write. (b) The trigger: `_on_answer` (boltrig/api/bootstrap.py:293-313) gains a THIRD
route, injected as a callable exactly like `executor` and `pump` so the kernel still never
imports the fleet (P1, bootstrap.py:280-288). It fires only when the answered request is an
APPROVAL whose run carries a `held:`-prefixed paused checkpoint; the interpreter route and the
chat route are mutually exclusive by that prefix. (c) Publish `tool_result` plus a bounded
`text_delta` to the same relay stream, append the continuation as a new assistant message in the
shape of chat.py:426-436 (necessary because the relay evicts the oldest closed streams past
`max_closed`, events.py:119-131, and a 60-minute approval on a busy tenant can outlive the
backlog), then close. EXACTLY-ONCE: zero new mechanism. `consume_approved_by` (hitl.py:337-368)
remains the sole authority and `store.consume_hitl` (postgres.py:644-651) the sole atomic
ANSWERED->CONSUMED transition. The fingerprint matches BY CONSTRUCTION because the params come
from the seal and the run id is unchanged. A duplicate notifier fire is already impossible past
the first genuine answer (`answer_hitl` returning None raises, hitl.py:302-306); a duplicate
route fire, or a race with a synchronous retry, loses the CAS and surfaces as HITLStateConflict
(approval_gate.py:124-133), which Order 6 requires be recorded, never swallowed.

### Order 5

ORDER 5 (precondition: Order 4 must be LIVE first, or this gate would refuse the very lane it
protects). Adopt (c)'s subsidiary holding as a fail-closed gate. In
boltrig/kernel/approval_gate.py, before `hitl.create(...)` at approval_gate.py:141-155, require
that the run have a nameable redeemer, DERIVED from the record and not stored beside it: either
the interpreter lane (the run is checkpointed) or the chat lane (Order 2's `held:` checkpoint is
about to be written). A gated verb dispatched on any other lane raises a typed
`ApprovalNotHoldable` (a new BoltrigError alongside PendingHuman at
boltrig/models/errors.py:138-149, status 409, carrying the verb) and mints NOTHING. Give the new
reason its own branch in boltrig/kernel/mcp.py:400-405 so the cell receives an actionable
instruction rather than a dead request id. PROOF (this is the anti-regression guard, and it must
catch the SHIPPED value, not a mock): a seeded-failure test in tests/security/test_hitl_gate.py
asserting that a gated verb dispatched on a redeemer-less lane raises the typed refusal AND
leaves `hitl_requests` with ZERO new rows. This is what makes the ground-truth state - an
ANSWERED approval nothing can claim - structurally impossible rather than merely fixed once.

### Order 6

ORDER 6 (precondition: Order 4). Candour at the chokepoint on all three residual paths, never
silence, never a silent re-pend. (i) Sealed call missing or unreadable (an old request, a swept
seal): REFUSE. Leave the approval ANSWERED, publish an explicit notice on the run stream, and
audit it. Advocate (b)'s proposed fallback to re-driving the transcript is expressly rejected:
it re-imports the probabilistic failure its own objection identified. (ii) The resumed invoke
re-pends because `_resource_context` was re-read live and the resource legitimately changed
during the approval window (approval_gate.py:73-87 feeding hitl.py:139-142): say the resource
changed, surface the NEW request id, and do not present it as a fresh unexplained ask. This is
SEC-14 working correctly and would behave identically under (a). (iii) HITLStateConflict
(approval_gate.py:124-133): record it on the run stream and in the audit row; it means the write
already ran and the user must be told so, not asked again.

### Order 7

ORDER 7 (precondition: Order 4). Sweep the seal. The chat lane never calls `sweep_run_scoped`
(its only caller is the org lane, boltrig/fleet/pump.py:584), so the held-call seal must be
dropped explicitly on consume, on HITLStateConflict, and by the existing expiry janitor
(boltrig/kernel/hitl_expiry.py, started at boltrig/api/worker.py:114-138) when the request
transitions to TIMED_OUT. PROOF FROM THE RECORD: for a run whose approvals are all terminal,
`credential_refs` holds no `held_call` row.

EXTENDED 2026-07-26 (not part of the original ruling; recorded here because a reader checking the
sweep will look at this Order). Order 7 correctly observed that the chat lane never calls
`sweep_run_scoped`, and scoped the remedy to the held-call seal because that was the matter before
the bench. The SAME absent hook was also leaking the permission-parity ADAPTER BEARER, which was
not in issue here: 29 live rows on cvboltrig, one per turn plus one per delegated child, none ever
deleted. Verified from the record and closed under the rule "a run's secrets live exactly as long
as something can legitimately replay under that run" - which is Order 7's own reasoning applied to
the other thing the run sealed. See `docs/findings/2026-07-26-run-scoped-bearer-never-swept.md`.
Note for anyone touching this: the sweep MUST stay guarded, because
`delete_credential_refs_for_run` deletes the whole `run:<id>:` prefix and would otherwise destroy
the very seal Orders 4 and 6(i) depend on.

### Order 8

ORDER 8 (acceptance, and the only proof this bench will accept). The fix is proved from the
RECORD, never from a green log line. PRIMARY: on the live cvboltrig tenant, a new
`opbox.add_comment` approval raised inside a chat turn and approved by a human reaches
`status='consumed'` in `hitl_requests` with its matching `hitl_responses` row. That is the
ground truth's own discriminator and nothing less closes this matter. CORROBORATING, same
record: `audit_events` carries a row for the SAME `run_id` with that verb, `status='ok'`, and
the approver stamped via `approved_by` (approval_gate.py:157-166), and `GET
/v1/audit/tree/{run_id}` (boltrig/kernel/app.py:751-762) renders the approval and the action in
ONE tree - which is the literal wording of the goal. EXTERNAL: the comment exists in Opbox.
NEGATIVE CONTROL (mandatory, mirroring the double-delivery assertion the existing durable test
already makes): deliver the resume TWICE and assert `hitl_requests` holds exactly one CONSUMED
row and `audit_events` exactly one TOOL_CALL row for that verb and run - not two. DIVERGENCE
TEST: assert that no code path can execute a write whose params were not unsealed from the Order
2 record.

## Reserved (open; a later matter must not assume these decided)

- DISCOVERED DEFECT ON A LANE NOT BEFORE ME, TO BE FILED AS ITS OWN MATTER: the HITL durable
  resume is dead in production for WORKFLOWS too, not only for chat. No process in the shipped
  stack serves the Hatchet tasks - docker-compose.yml runs only `uvicorn boltrig.api.asgi:app`
  (line 147) and `python -m boltrig.api.worker` (line 196), and nothing starts
  `boltrig.fleet.hatchet_worker`. So `executor.push_event` (bootstrap.py:296-305) publishes into a
  scope with no waiter on the workflow lane as well, and any run enqueued via
  `HatchetExecutor.enqueue` -> `aio_run_no_wait` (fleet/workers.py:158-165) sits unclaimed. I make
  no order on it because it is outside this matter, but a bench that verified it will not bury it:
  file it, do not let it ride on this ruling.

- UNTESTED CODE PATH, RESERVED: `ctx.aio_wait_for(UserEventCondition(...))` at
  boltrig/fleet/hatchet_app.py:350-364 has no test. tests/integration/test_durable_resume.py
  proves record-driven re-entry through LocalDurableExecutor by re-calling `run_workflow_body`
  directly; it never exercises the engine wait. Whether that path works at all is undetermined on
  this record and is reserved.

- WHETHER THE CHAT TURN SHOULD EVER BECOME DURABLE: (a) is refused on today's substrate, not
  forever. boltrig/kernel/events.py:9-12 already declares the intended upgrade to a cross-process
  relay and `redis` is already a compose service (docker-compose.yml:69-75). If that relay lands,
  and if a Hatchet worker is actually served, (a) becomes buildable and may be re-argued on
  evidence. The ratio above does not forbid it: it holds that the durable envelope is a trigger,
  not the source of correctness, so a future (a) would still have to replay the recorded call from
  Order 2's checkpoint.

- THE SAME DEFECT CLASS ON THE ORG/PUMP LANE: a gate-raised APPROVAL inside a pump-driven work
  item has no redeemer either. `_park` (pump.py:511-533) files only ESCALATION requests it raised
  itself, and `pump.requeue` (pump.py:430-434) un-parks an escalated item; neither redeems a gate
  approval. Order 5's gate will refuse to mint there, which is correct and fail-closed, but
  whether that lane should instead GAIN a redeemer is undecided and reserved.

- THE DEAD ask-user BINDING: `_ask_user` binds `work_item_id=context.run_id` with a comment
  asserting the ordinary resume wiring will requeue the paused run
  (boltrig/kernel/dispatch.py:250-253). It cannot: the chat item is IN_FLIGHT, and requeue
  requires AWAITING_HUMAN or BLOCKED (pump.py:430-434). Whether to delete the dead binding or make
  the QUESTION lane resume through the Order 4 mechanism is reserved. Note that the comment
  currently describes behaviour the code does not have, which is the same prose-is-not-enforcement
  trap that produced this matter.

- PLUMBING `?since=` INTO THE BOLTRIG CONSOLE: `streamRunEvents` (ui/src/api/sse.ts:216-243)
  accepts only `{signal, follow}` and never sends `since`, so the console will replay a
  continuation's whole retained backlog rather than only the post-decision segment. Cosmetic and
  expressly non-load-bearing (hitl_http.py:82-88 calls the cursor an optimisation), so not
  ordered; reserved.

- THE DATA-AT-REST QUESTION: Order 2 introduces a kernel-only, run-scoped sealed record of
  approved-action params, which is new state beside a record that previously held only a digest. I
  hold it to be the minimum honest cost of executing a held write at all - the durable lane pays
  the identical cost in its checkpoint table - and I have bounded it hard (distinct kind,
  unresolvable into params, swept on every terminal transition). Whether a tenant may opt out of
  holding chat writes entirely, and thereby out of this state, is not before me and is reserved.

- NARRATION FIDELITY: whether the post-write model narration should be a full re-entry of
  `build_turn_executor` or a bounded templated notice is left to the builder as a reversible low-
  blast call, PROVIDED it never gates the write and never carries authority. If a later matter
  finds narration drifting into authority-bearing behaviour, that is a fresh fork.
