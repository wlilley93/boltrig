# An expired work-item lease double-executes, and the loser overwrites the winner

Date: 2026-07-25
Status: **OPEN.** The sibling defect (#6, a post-terminal fault re-opening a
settled item) is FIXED and shipped. This one is not, deliberately: the pump-side
fence that was written for it was defeated under adversarial review, and the
version that would hold needs a store-contract change that is going to the court.

## The defect

`PostgresStore.claim_work_item` reclaims any item whose lease has expired. That is
deliberate and correct: it is how a crashed worker's item comes back (US-FLT-05).
But nothing RENEWS a lease. Every `lease_expires_at` write in the tree either sets
it at claim time or clears it. So a step that outruns `lease_seconds` (default
300) is handed to a second executor while the first is still running.

The first body then finishes and writes its result. Every pump state write is
`update_work_item`, which on Postgres is `create_work_item` - an unconditional
full-row `ON CONFLICT DO UPDATE` that writes status, attempts, lease_owner,
lease_expires_at and result from the caller's in-memory snapshot, with no owner
predicate and no status predicate. So the loser stamps its stale row over the
winner's terminal record and rolls `attempts` back.

The repo already has the right primitive and does not use it here:
`transition_work_item_status` is a CAS whose own comment says "the loser fails
instead of silently overwriting the winner", and the sibling channel-outbox queue
does fence its claims on `lease_owner`. The pump does neither.

## Why the obvious fix is not the fix

The sweep proposed fencing the write on `lease_owner = our worker_id`. That is
wrong for this codebase: in the durable lane the item is claimed by the API pump's
worker id and the task body runs in a different process with a different worker
id, so an owner-equality fence would refuse every legitimate durable terminal
write.

The next attempt was a `_still_leased(item)` helper: re-read the row and proceed
only if `(lease_owner, lease_expires_at)` still match what this body read at the
start. An independent reviewer applied that patch and reproduced the ORIGINAL
defect with it in place. Three findings, all verified by running the code:

1. **An unfenced sibling write in the same body.** `route_to_head`
   (`boltrig/fleet/authority.py:146`) does its own blind `update_work_item` on the
   same row, inside `handle_claimed_item`. Fencing only the writes in `pump.py`
   leaves it. Probe result: final row DONE, `attempts` rolled back, the winner's
   result destroyed.
2. **The fence sat after `persist_new_work_items`.** The losing body still created
   a duplicate follow-on child before reaching any fence.
3. **The design gap, and this is the one that matters.** `_still_leased` proves
   "the lease is unchanged since THIS BODY'S read", not "this body holds the
   lease". Two bodies that both read the row while it carried the same tuple both
   pass. That is not a narrow race: it is the steady state of the duplicate-enqueue
   path, where `run_once`'s `HatchetExecutor.enqueue` returns immediately and
   `run_forever` re-claims and re-enqueues the same item under ONE worker id.

A read-then-write check cannot fix a read-then-write race. It narrows the window
from the length of a step (minutes) to one round trip, which is worth something,
but shipping it under the heading "the lease is fenced" would be a claim the code
does not support - the exact failure mode this month's work exists to remove.

## What would actually hold

A conditional work-item write at the STORE, so the fence is evaluated by the
database in the same statement that does the update: `update_work_item(item, *,
if_lease=(owner, expires_at))` returning whether it wrote, backed by
`UPDATE ... WHERE tenant_id=$ AND id=$ AND lease_owner=$ AND lease_expires_at=$`.

That is a change to the store contract and therefore to BOTH stores, and
`InMemoryStore` cannot express it as things stand because it hands callers the
live row object rather than a snapshot, so a memory-side "did it change" check
compares an object with itself. Making the memory store copy-on-read to support
this is a real change to the two-store parity design.

Filed to the court as `SUBMISSION-2026-07-25-145500` rather than decided here.

## What IS fixed

The sibling defect in the same handler shipped in this commit: a fault raised
AFTER the attempt already reached its end state durably (`_settle` writes DONE and
only then upserts its execute checkpoint; the addressed-workflow path writes DONE
and only then writes an audit row that can hit the `UNIQUE(tenant_id, seq)`
backstop) landed in `_record_failure`, which guarded only the cancel marker and
then unconditionally re-queued to PENDING. That is the done -> pending transition
`boltrig/work/store.py` forbids outright, and it re-ran the whole item - every
effect and every follow-on child - a second time.

`_record_failure` now re-reads the row and refuses to re-open anything already in
`SETTLED_STATUSES`. Pinned by
`tests/integration/test_delegation_pump.py::test_a_fault_after_the_terminal_write_never_reopens_a_settled_item`,
seeded-failure verified: without the guard it fails with "a fault AFTER the DONE
write re-opened a settled work item".

## Reachability of the open half

Needs a step that outruns the 300s lease, or the duplicate-enqueue path above.
Not remotely triggerable by an untrusted party; it is a durability and
correctness defect, not a security one. The visible damage is a lost terminal
record, a rolled-back attempt count, duplicated follow-on children, and duplicated
external effects from the step running twice.
