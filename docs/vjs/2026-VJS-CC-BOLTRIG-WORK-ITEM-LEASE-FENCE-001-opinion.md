# [2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 - opinion

First Instance, single judge, boltrig County. Case file: SUBMISSION-2026-07-25-170357.
Clerk verdict: **stands-with-correction**, per incuriam: **False**.

Recorded under ACT-002:s7 because the order is capped at 500 words.

**Implementation status: OPEN.** The order binds; the code is not written. Nothing
in the tree may describe the lease as fenced until D1 to D9 land and D7 has been
run against a real Postgres.

## Holding

Option A is adopted, in a narrowed and corrected form. The Store contract gains a CONDITIONAL work-item write whose fence is evaluated by the backend in the same statement as the update, against the lease tuple (lease_owner, lease_expires_at) MINTED AT CLAIM TIME and carried to the writing body, returning whether it wrote. Both backends must honour it: Postgres as `UPDATE work_items SET ... WHERE tenant_id=$ AND id=$ AND lease_owner=$ AND lease_expires_at=$`, the in-memory store as the same scalar predicate against its stored row (exactly the shape `ack_channel_outbox` / `fail_channel_outbox` already implement in BOTH backends, so the case file's premise that InMemoryStore "cannot express it" is rejected as stated).

Two corrections to the case file bound the cost. First, the fence value must NOT be read by the body: `_still_leased` failed because it compared against the body's own read. A store-level CAS whose expected tuple is re-derived at body start inherits the identical defect. The token is captured by `run_once` from the claim result, put on the enqueue payload, and consumed by `_run_item_payload`; a body's authority to write derives from its CLAIM, never from a later read. Second, making the memory store stop sharing WorkItem objects with callers is a PARITY REPAIR, not a change to the parity design: `PostgresStore.get_work_item` already returns a fresh object built by `work_item_from_row`, so the live-row handout is itself the existing divergence, in favour of the backend that does not ship.

The fenced lane is narrow and enumerated, not the whole store: only rows reached through `claim_work_item` need it (pump.py 375, 413, 498, 529, 549 and authority.py 146). `chat.py:805` and `department_head.py:201` write items created IN_FLIGHT with a NULL lease that `claim_work_item` provably never claims, and `WorkPump.requeue` acts on parked, unleased rows; all three are out of scope.

Option B is rejected as a substitute. Its monotonic-terminal-write limb is strictly weaker than and subsumed by the fence; lease renewal and a shorter window are ADMITTED as complementary mitigation but may never be recorded, in code comments, commit messages or findings, as fencing the write.

Scope of the claim, which is part of the holding: this makes the RECORD single-writer. It does not make execution exactly-once, and must not be described as doing so.

## Ratio

Where work is handed to an executor under a lease, authority to write that work's record belongs to the CLAIM, not to the body: (1) the fence must be evaluated by the store in the same statement that performs the write, against a token minted when the claim was granted and carried to the writer, never re-derived from a read the writer itself performs, because a read-then-write check cannot decide a read-then-write race; (2) a guard a caller can defeat by holding a reference to the guarded object is not a guard, so a backend that hands callers its live row must be repaired before it may be said to honour a conditional write; and (3) store parity is owed to the backend that SHIPS: where one backend can express a correctness primitive and the other cannot, the answer is to make the second express it, never to lower the contract to the weaker backend, and never to ship a predicate that is honest on one backend and cosmetic on the other.

## Option B, and why it is mitigation rather than an answer

Option B (bound the damage without a fence) is rejected AS A SUBSTITUTE, on principle, not merely on the evidence.

(a) Its monotonic-terminal-write limb is subsumed. A status-only guard cannot stop the actual harm, because update_work_item writes the WHOLE row: two non-terminal writes still clobber attempts and result. I verified the concrete consequence the case file only gestures at: the loser stamps its stale snapshot back, rolling attempts from 2 to 1, which silently extends the retry budget past max_attempts=3. A fence on the claim tuple stops every one of those writes; a status predicate stops only a subset.

(b) Renewal cannot close it. A heartbeat reduces how often a legitimately long step loses its lease, but a paused, GC-stalled or network-partitioned worker stops renewing while still running, which is precisely the case where two bodies overlap. Renewal manages frequency; it cannot supply the missing predicate.

(c) The premise that made B attractive does not hold. B was put largely because Option A appeared to require a store-contract change the memory backend could not honour. It can: the in-memory store already implements owner-fenced conditional settles (ack_channel_outbox, fail_channel_outbox) and an owner-token CAS (idempotency_start/complete), and it already implements a status CAS for work items (transition_work_item_status). The only real obstacle was aliasing, and removing that aligns the memory store with the shipped store rather than diverging from it.

Also refused: an owner-equality fence on `self.worker_id`. Verified positively wrong - boltrig/fleet/hatchet_app.py::_default_bootstrap builds a SECOND pump in the worker process via build_org with no worker_id, so it gets a fresh `pump-<uuid4>`, different from the API-side pump that claimed. Such a fence would refuse every legitimate durable terminal write.

Evidence that would reopen Option B, so the application can be renewed rather than re-litigated: (i) a demonstration that making InMemoryStore stop sharing WorkItem objects breaks callers that rely on aliasing - I inspected all eleven non-store update/create call sites and the lease tests and found none, but I did not run the suite; (ii) a demonstration that the claim-time token is not in fact unique per claim (it derives from `now() + make_interval(...)` per claim, so two claims of one row cannot share a tuple absent clock non-monotonicity); or (iii) a measurement showing copy-on-read materially degrades a production path, which would be surprising given the memory store is documented as dev/test only.

## Obiter

Persuasive only, not part of the ratio.

1. Abandoning is safe precisely because expiry-based reclaim is the recovery mechanism. A body that loses its fenced write and simply stops does not strand the item: either the reclaimer settles it, or the lease lapses and claim_work_item picks it up again (US-FLT-05). This is why D5's no-op-and-log is the correct failure mode rather than an escalation.

2. A lease heartbeat still looks worth doing on its own merits, given steps that drive a coding agent can plainly outrun 300 seconds. It is admitted as mitigation by the holding; I decline to order it because it is not needed for the fence to be correct, and ordering it would blur what the fence does and does not achieve.

3. Two adjacent read-then-write writes are the same defect class and are candidates for the CAS the repo already owns (transition_work_item_status), but they are outside the lease question and I do not order them: kernel/hitl_expiry.py:92-102 (reads AWAITING_HUMAN, then blind-upserts CANCELLED) and WorkPump.requeue at pump.py:430-440 (reads AWAITING_HUMAN/BLOCKED, then blind-upserts PENDING with attempts=0). Both act on unleased rows, so neither is made worse by this ruling.

4. On the shape of the primitive: adding a keyword to update_work_item is fine, but a distinct named method reads better at the call site and makes D3's coverage mechanically greppable. That is a drafting preference, not a direction.

5. There is no refuse_memory_store_in_prod guard to match refuse_dev_auth_in_prod / refuse_default_audit_key_in_prod (bootstrap.py:404-453): build_store silently falls back to InMemoryStore whenever DATABASE_URL is unset. That is a separate matter and I say nothing about whether it should exist, but it is one more reason the memory store's behaviour is not safely treated as merely decorative.

## Facts the bench verified for itself

The bench rejected the case file's central premise against the code, corrected an
overstatement in it, and found two consequences the advocate never pleaded.

- HOLDS: nothing renews a work-item lease. Every lease_expires_at write on work_items in the tree is either a claim (boltrig/store/postgres.py:556, boltrig/store/memory.py:373) or a clear (pump.py:438, 489, 547; kernel/hitl_expiry.py:97). Grepped the whole of boltrig/ and services/.
- HOLDS: DEFAULT_LEASE_SECONDS = 300 (boltrig/fleet/pump.py:62) and claim_work_item reclaims any item whose lease has expired (postgres.py:558-562 `status='in_flight' AND lease_expires_at < now()`; memory.py:364-368).
- HOLDS: PostgresStore.update_work_item is literally `await self.create_work_item(item)  # upsert` (postgres.py:534-535), an unconditional INSERT ... ON CONFLICT (tenant_id, id) DO UPDATE that writes status, attempts, lease_owner, lease_expires_at and result from the caller's snapshot, with no owner and no status predicate (postgres.py:510-532). InMemoryStore.update_work_item is a bare dict assignment (memory.py:343-344).
- HOLDS: transition_work_item_status exists as a CAS in both backends and its comment reads "the loser fails instead of silently overwriting the winner" (postgres.py:537-546, memory.py:346-354). Its only caller is boltrig/work/store.py:96 (WorkItemStore.transition); the pump never calls it. Confirmed by grep across the repo.
- HOLDS: the sibling channel-outbox queue fences on the lease owner in BOTH backends: ack_channel_outbox / fail_channel_outbox use `AND lease_owner=$3` on PG (channel_outbox.py:90-119) and `msg.lease_owner != worker_id -> False` in memory (channel_outbox.py:163-190).
- DOES NOT HOLD AS STATED: "InMemoryStore cannot today [express a conditional write]". It already expresses owner-fenced conditional settles (channel_outbox mem twin), an owner-token CAS (idempotency.py:83-115, _owned at 118-121), and a status CAS for work items (memory.py:346-354). The true obstacle is narrower: the memory store hands back the LIVE row, so a caller's in-place mutation lands before any store call can refuse it.
- MATERIAL CORRECTION: the memory store's live-row handout is ITSELF the parity divergence. PostgresStore.get_work_item returns a freshly constructed WorkItem via work_item_from_row (store/work_items.py:276-303), so the shipped backend is already copy-on-read. Making InMemoryStore copy is a parity REPAIR, not a change to the parity design as the case file frames it.
- HOLDS: an owner-equality fence on self.worker_id would be positively wrong. boltrig/fleet/hatchet_app.py:273-301 (_default_bootstrap) builds a SEPARATE pump in the Hatchet worker process via build_org with no worker_id, so pump.py:217 gives it `pump-<uuid4>`, distinct from the API-side pump that claimed at pump.py:229-231. work_item_task_body (hatchet_app.py:238-242) then runs the body on that other pump.
- HOLDS: the unfenced sibling write. route_to_head does its own blind `await store.update_work_item(item)` at boltrig/fleet/authority.py:146, inside handle_claimed_item's call at pump.py:291.
- HOLDS: persist_new_work_items (pump.py:327) runs BEFORE _settle (pump.py:330), so a fence placed only on the terminal write still lets a losing body create duplicate children via create_work_item at pump.py:164.
- HOLDS: the sibling defect is fixed as claimed. _record_failure re-reads the row and refuses to re-open anything in SETTLED_STATUSES (pump.py:478-484), and the pinning test test_a_fault_after_the_terminal_write_never_reopens_a_settled_item exists at tests/integration/test_delegation_pump.py:212.
- VERIFIED BY MY OWN TRACE (beyond the case file): the pump can produce transitions that boltrig/work/store.py declares impossible. _TRANSITIONS gives DONE and CANCELLED no outgoing edge, but that guard lives in WorkItemStore.transition, which the pump bypasses entirely by calling store.update_work_item directly. A stale loser can therefore write DONE over CANCELLED or PENDING over DONE.
- VERIFIED BY MY OWN TRACE: the attempts rollback has a correctness consequence the case file does not name. Body 1 claims (attempts=1), the lease expires, body 2 reclaims (attempts=2) and settles; body 1 then writes its snapshot back with attempts=1, so the item can be retried more times than max_attempts=3 allows (pump.py:485).
- PARTIALLY VERIFIED: the finding's claim that the duplicate-enqueue path is "the steady state" is overstated. run_once's claim leaves the row IN_FLIGHT with a live lease, and claim_work_item requires an EXPIRED lease to reclaim, so run_forever cannot re-claim the same item until the lease lapses. The finding's underlying conclusion still stands and I adopt it: a fence value read at body start (not at claim time) can be identical for two bodies, which is why _still_leased failed and why the store-level CAS must use the claim-time token.
- HOLDS: the fenced lane is narrow. chat.py:705-710 and department_head.py:213-228 create items IN_FLIGHT with a NULL lease, and neither backend's claim predicate can match a NULL lease_expires_at, so those rows are never pump-claimed. Their writes (chat.py:805, department_head.py:201) are outside the lease lane.
- HOLDS: the case file's citator claim is substantially correct. I read all thirteen orders in /home/jellytot/Projects/boltrig/.vjs/orders/ and grepped them for parity, store contract, conditional write, CAS, idempotency, exactly-once and double-execution; nothing is on all fours. Nothing in /home/jellytot/Projects/vibe-justice-system/lawpack/v2/judgments/ (five opinions, all VJS-level constitutional or Opbox matters) touches it either.
- CLOSE BUT DISTINGUISHABLE: [2026] VJS-COUNTY 6 (server-side cancel) forbids "a cancel that is not persisted durably so a process restart resurrects the run" and requires CANCELLED to be written durably in a finally. The mischief there is resurrection by PROCESS RESTART; here it is resurrection by a concurrent stale writer. The ruling is not on all fours, but its principle - a durably written terminal state must not be resurrected - is engaged, and the present code can resurrect a CANCELLED row into DONE. I follow it so far as it goes and decide the rest afresh.
- STATUTE CHECKED: ACT-003 s.5 (breach discovered -> self-file and correct the work) and s.4 (material implementation decisions require a decision log) are engaged; the finding doc already self-files the open half. ACT-004 s.3 requires invariants to be deterministic mechanical checks, which is why D7 requires a bound node id in tests/invariants.yaml rather than prose.
- UNVERIFIED: I did not run the test suite. BOLTRIG_TEST_DATABASE_URL is not set in this environment, so the Postgres half of the parity suite would skip and prove nothing; and I am read-only by direction. Whether copy-on-read breaks any caller is therefore established only by inspection of all eleven non-store create/update call sites plus tests/store/test_durable_delegation.py:91-105 (which calls update_work_item explicitly and does NOT rely on aliasing), not by execution.
- UNVERIFIED: I did not empirically reproduce the double-execution or the reviewer's defeat of the _still_leased patch. Both rest on my reading of the code plus the advocate-authored finding at docs/findings/2026-07-25-work-item-lease-has-no-fence.md, which I weigh as evidence; every load-bearing assertion in it that I could check against the code did hold.

## Clerk's corrections, all of which are folded into the recorded directives

The clerk found no conflicting binding authority, having repeated the search over
all 13 local orders, 10 statutes, 5 judgments and 38 canon orders. It returned
`implementable: false` on the directives AS FIRST DRAFTED, for these reasons.

- D4 IS NOT ACHIEVABLE AS STATED, and its only available implementation is the pattern the same ruling declares failed. D4 orders 'No duplicable downstream effect ahead of the fence' and requires the body to 'confirm it still holds its claim BEFORE boltrig/fleet/pump.py:327 persist_new_work_items'. persist_new_work_items writes DIFFERENT rows (pump.py:164 create_work_item(child)), so no conditional write on the parent row can make child creation atomic with the check. Every implementation of D4 is therefore a read-then-check at the line 323 boundary, which is structurally the `_still_leased` shape the ruling rejects and which the ratio says 'cannot decide a read-then-write race'. CORRECTION: D4 must state in terms that it is a best-effort NARROWING of the duplicate-child and duplicate-notification window, not a fence, and D9's honesty prohibition must extend to it (no code comment, commit message or finding may describe child suppression or terminal notification as fenced). As drafted a reader cannot verify the directive's own claim, and an engineer could satisfy the letter while writing something false into the repo.

- D2 CONTRADICTS HOW THE DURABLE LANE ACTUALLY WORKS, at a line the judge cited for a different purpose. boltrig/fleet/hatchet_app.py:238-242 is `await pump._run_item_payload({"tenant_id": payload["tenant_id"], "item_id": payload["item_id"]})` - work_item_task_body REBUILDS the payload from exactly two keys and discards every other. A token placed on run_once's payload is silently dropped before _run_item_payload ever sees it on the Hatchet lane, so the body would fence on a missing token and either fall back to a read (the rejected pattern) or refuse every durable terminal write (the failure mode the ruling calls 'positively wrong' for the worker_id fence). D2 asserts only that the rule 'holds identically for... the durable (Hatchet) lane'; neither D2 nor D3's file-and-line enumeration names hatchet_app.py:238-242. CORRECTION: D2 must name it as a site that must carry the token through.

- D2 GIVES NO WIRE CONTRACT FOR A TOKEN THAT MUST SURVIVE SERIALIZATION AND COMPARE BY EXACT EQUALITY. The durable enqueue is boltrig/fleet/workers.py:158-165, `wf.aio_run_no_wait(payload)`, which ships the payload to the Hatchet engine and back. `lease_expires_at` is a Postgres timestamptz returned by `RETURNING *` (postgres.py claim_work_item) and a datetime in memory (memory.py claim_work_item). Any sub-microsecond truncation or timezone normalisation in that round trip makes the equality predicate in D1 fail for every durable write. D7's parity test uses in-process objects and cannot catch it. CORRECTION: D2 must require a lossless, exactly-round-tripping encoding for the token on the durable payload, and D7 (or a companion) must prove the fence ACROSS the durable enqueue, not only in-process.

- D3's EXCLUSION RATIONALE IS FALSE ON THE FACTS, AND ITS ENUMERATION IS INCOMPLETE. D3 orders that chat.py:805, department_head.py:201 and WorkPump.requeue be recorded as out of the lane 'because those rows carry no lease'. That is true of the first two (verified: chat.py:710 and department_head.py:228 create IN_FLIGHT with a NULL lease, which neither claim predicate can match) but FALSE of requeue: pump.py:527-529 `_await_human` sets AWAITING_HUMAN and calls update_work_item WITHOUT clearing lease_owner or lease_expires_at (the only clears in the tree are pump.py:438 requeue, 489 _record_failure, 547 _cancel, hitl_expiry.py:96-97). A parked row therefore CARRIES a stale claim tuple, and requeue is the thing that clears it. Two consequences. First, D3 as written orders a false statement into the code or the finding. Second, applying D3's stated test rather than its list sweeps in boltrig/kernel/hitl_expiry.py:102, `_park_expired_item`, an unconditional full-row update_work_item on an existing row that the ruling neither enumerates nor excludes, and whose read-then-write window (get at line 92, write at line 102) can clobber a row a human has just requeued and the pump has just claimed. CORRECTION: restate requeue's exclusion on its true ground (a deliberate human-initiated reset, not an absent lease) and dispose of hitl_expiry.py:102 expressly, in or out.

- D7 CAN BE SATISFIED ON THE BACKEND THAT DOES NOT SHIP, contradicting the ruling's own third ratio limb. tests/store/test_store_parity.py:34 reads `DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")` and its docstring states 'the postgres backend runs when BOLTRIG_TEST_DATABASE_URL is set (CI), and skips cleanly offline'. The judge records that the variable is not set in their environment. As drafted, a memory-only green run satisfies D7 in full while the Postgres fence - the one that ships, the one D1 expresses as raw SQL, and the one limb (3) says parity is owed to - is never executed. This repeats the exact failure recorded in this repo's own self-filed breach (LOG-2026-07-17-081838: a store change committed as 'Verified' on an offline run that skipped every Postgres test). CORRECTION: D7 must require the seeded-failure proof to be RUN with BOLTRIG_TEST_DATABASE_URL set and the postgres parameter shown as passed rather than skipped, before the work is recorded as landed.

- D8's FIRST LIMB IS UNFALSIFIABLE. 'the cancel-request row must be left intact so the lease holder settles it' cannot be breached: run_cancel_requests has no consume or delete path anywhere in the tree (postgres.py:609-624 and memory.py:407-415 are insert plus exists only; the only readers are the four is_run_cancel_requested calls in pump.py and one in _record_failure). No engineer could fail this and no reader could verify it was done. The operative half is the logging plus the prohibition on reporting a cancel as durably recorded. CORRECTION: recast the first limb as a forward-looking prohibition (no consume or delete may be ADDED on the refused path) or drop it.

- THE INSPECTION BASE FOR THE COPY-ON-READ SAFETY FINDING IS UNDERSTATED. The judge rests the D6 safety conclusion, and reopening-evidence item (i), on having 'inspected all eleven non-store update/create call sites'. Grepping boltrig/ finds SEVENTEEN: department_head.py 201 and 228; pump.py 164, 375, 413, 439, 498, 529, 549; hitl_expiry.py 102; authority.py 146; chat.py 710 and 805; work/store.py 54, 72 and 125; channel_routes.py 570. The six not accounted for (work/store.py x3, channel_routes.py:570, and pump.py 164/439 depending on how the count was taken) are exactly the wrappers most likely to hand a caller a row it later mutates. CORRECTION: restate the base as the seventeen named sites, or name the eleven that were inspected and the exclusion rule for the rest.

- THE HOLDING'S ANALOGY IS LOOSER THAN D1's PREDICATE, in a way an engineer could follow into the refused design. The holding says the memory store must implement 'exactly the shape ack_channel_outbox / fail_channel_outbox already implement in BOTH backends', and D1 repeats 'mirroring ack_channel_outbox/fail_channel_outbox'. Verified: those siblings fence on the owner column ALONE (channel_outbox.py:93-95 `AND lease_owner=$3`; the memory twin at 163-165 `msg.lease_owner != worker_id`). That is the owner-equality fence the same ruling refuses for work items as 'positively wrong'. D1 does spell out the two-column predicate, so the risk is contained, but 'exactly the shape' should read 'the same conditional-write shape, on the two-column claim tuple rather than the outbox's single lease_owner column'.

- RATIO LIMB (3) IS DRAWN WIDER THAN THE FACTS DECIDED. 'where one backend can express a correctness primitive and the other cannot, the answer is to make the second express it, never to lower the contract to the weaker backend' is stated without exception, and so decides a case nobody argued: a backend that genuinely cannot express the primitive. On these facts the judge FOUND that InMemoryStore can (verified: it already runs owner-fenced conditional settles, an owner-token CAS at idempotency.py:83-121, and a status CAS for work items at memory.py:346-354), so the absolutist form is obiter beyond the facts. The second half of the limb, 'never ship a predicate that is honest on one backend and cosmetic on the other', is the part actually decided and is sound. CORRECTION: confine limb (3) to the case where the weaker backend CAN be made to express it, which is the only case before the court.

- FORM: the order cannot be recorded as drafted. It carries no runtime_summary, which ACT-002:s10 makes mandatory ('must_not: accept_order_without_runtime_summary'), and its operative text measures 886 words against the 500-word County cap in ACT-002:s2 and s8 (every previously filed boltrig order sits at 134-587). Mechanical fix, no effect on the decision: move the Ratio, the Rejected limbs, the refused owner-equality fence and the reopening-evidence list into source_opinion under ACT-002:s7, as [2026] VJS-COUNTY 12 did, and add a runtime_summary.

- NOT A FAULT, RECORDED FOR THE RECORD: on the three things that decide the case the judge verified the facts themselves rather than taking the advocate's file. They rejected the case file's central premise ('InMemoryStore cannot express it') against the code, corrected its 'steady state' overstatement, added two consequences the advocate never pleaded (the DONE-over-CANCELLED transition the work/store.py:96 guard is bypassed for, and the attempts rollback extending the retry budget past max_attempts), positively verified the refused owner-equality fence at hatchet_app.py:273-301 and build_org (confirmed: build_org takes no worker_id, so pump.py:217 mints a fresh `pump-<hex8>` in the worker process), and expressly flagged the two things they did not verify. Every code citation I checked held, including postgres.py:534-535, memory.py:343-344, the sole transition_work_item_status caller at work/store.py:96, and the pinning test at tests/integration/test_delegation_pump.py:212. The holding does not depend on the one item taken from the advocate (the reviewer's defeat of _still_leased); ratio limb (1) is proved by construction.

## Two authorities the bench did not search, neither changing the outcome

The clerk noted that ACT-001:s3 makes local decision logs a source of authority and
that the bench searched only `.vjs/orders/`. Two logs in
`.vjs/logs/decisions/` are engaged:

- **The derive-don't-store ratio.** Engaged, and it points the SAME way: the point
  of D1 and D2 is to make the stale write unconstructable at the backend rather
  than merely detectable by a caller. It is distinguishable because the claim tuple
  is a witness of a past grant, not a value whose constituents all sit in the
  current row, and deriving it from the current row is exactly the defect found.
- **A self-filed breach on this same store layer**, recording that `make check` is
  offline and skips every Postgres test, so a green offline run says nothing about
  the durable leg. That is why D7 now requires the parity proof to be RUN with
  `BOLTRIG_TEST_DATABASE_URL` set and the postgres parameter shown as passed. The
  first draft of D7 could have been satisfied entirely on the backend that does not
  ship, which would have repeated the breach it was written after.

## Recorded honestly

The clerk's finding that D4 is unachievable as drafted is accepted in full and the
directive is restated: child rows cannot be made atomic with a predicate on the
parent row, so any pre-persist check is a best-effort NARROWING of the duplicate
window and not a fence. D9's honesty prohibition is extended to cover it, so no
comment, commit message or finding may describe child suppression as fenced.

That correction matters more than it looks. The whole reason this matter reached
the court is that a fence which does not fence was nearly shipped under a name
that said it did.

---

## Discharge record (2026-07-26)

All nine directives are implemented and the order is discharged. Where a
directive was satisfied by stating a limit rather than by removing it, that is
recorded here, because a discharge that overstates itself would be the same
defect this matter is about.

| D | Where | Note |
| --- | --- | --- |
| D1 | `boltrig/store/{base,postgres,memory}.py` | `update_work_item_if_leased`, the predicate in the same statement as the update in both backends |
| D2 | `boltrig/fleet/lease_token.py`, `pump.run_once` | Minted at claim, carried on the enqueue payload; the expiry round-trips via isoformat/fromisoformat, which preserves microseconds and offset - the fence compares for equality, so a lossy encoding would fail CLOSED |
| D3 | `pump.py` (5 sites), `hitl_expiry.py`, `pump.requeue` | Both exclusions disposed of in terms. `requeue` is unfenced because a human re-queue is an authorised RESET, **not** because a parked row has no lease - it still carries the stale claim tuple. `_park_expired_item` cannot be fenced: the sweeper never claimed the item |
| D4 | `pump.persist_new_work_items` | NARROWED, and labelled as narrowed everywhere it appears. Closing it needs `UNIQUE(parent_id, intent)`, a schema change |
| D5 | `lease_token.write` | No-op plus a warning; an exception would reach `_record_failure` and re-open a settled item |
| D6 | `boltrig/store/memory.py`, `work_items.py` | Copy-on-read across all seventeen sites |
| D7 | `tests/store/test_store_parity.py`, `tests/fleet/test_lease_fence.py` | Run with `BOLTRIG_TEST_DATABASE_URL` set against a real Postgres: 2626 passed, 16 skipped, the postgres parameter passed and not skipped |
| D8 | `lease_token.write`, `pump._cancel` | A refused cancel is logged; the prohibition on adding any consume-or-delete to that path is stated at both ends |
| D9 | `boltrig/store/base.py`, `lease_token.py` | Recorded AT the contract, which is where a later reader would upgrade "single-writer" into "exactly-once" |

**One thing the discharge does not claim.** `_park_expired_item`'s real predicate
is a status read-then-write, so a human who re-queues an item in the same instant
the expiry sweeper fires can still have it cancelled underneath them. The order
did not ask for that to be closed and it is not closed. It is written down at the
site rather than left for the next person to rediscover, which is the most this
discharge is entitled to say about it.
