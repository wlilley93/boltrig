# Proposal: move idempotency replay ahead of the HITL gate and rate limit

Status: DESIGN / not implemented. This documents a confirmed correctness bug in
the dispatch chokepoint and a security-analysed fix. It is deliberately NOT
patched in directly: `AGENTS.md` forbids casually touching the dispatch
sequence, and re-ordering security-relevant steps is a first-impression
governance decision. This artifact is what must be reviewed (and, once Boltrig
is a VJS jurisdiction, routed to the court) before any code lands.

## The bug

The 10-step chokepoint (`boltrig/kernel/dispatch.py`) runs, in order:

```
3. grant check               (SEC-07)
4. consequence / HITL gate    (SEC-14)   <- consumes the single-use approval
5. rate limit                 (FR-KER-05)
6. idempotency replay         (NFR-REL-02) <- returns the cached result, if any
7. execute
...
9. record idempotent result
```

Idempotency replay sits at step 6, *after* the HITL gate (4) and rate limit (5).
For a HIGH-consequence (gated) verb this breaks the idempotency contract on a
retry:

1. First call: `approval_id` is presented. Step 4 calls
   `consume_if_approved(...)`, which **spends the approval single-use** (SEC-14
   anti-replay), then the verb executes (7) and the result is recorded under the
   idempotency key (9).
2. Retry with the **same `idempotency_key` and the same `approval_id`** (the
   client's normal retry-on-timeout): grant check passes (3), then step 4 calls
   `consume_if_approved(...)` again - but the approval is already consumed, so it
   returns false, `not approved` is true, and the kernel **raises a brand-new
   `PendingHuman` and asks for approval a second time** - even though the
   operation already completed and a cached result is sitting at step 6 that the
   retry never reaches.

Secondary effect: every idempotent retry also consumes a rate-limit token at
step 5 for work that will not be re-executed, and can be `RateLimited` away from
a result that already exists.

Net: a safe retry of a completed, approved, high-consequence action is
incorrectly re-gated (re-prompted for human approval) and rate-limited, instead
of replaying the stored result. This is the worst case precisely for the actions
we most want to be idempotent.

## The proposed fix

Move idempotency replay to immediately **after** the grant check (3) and
**before** the HITL gate (4) and rate limit (5):

```
3.  grant check
3.5 idempotency replay   <-- moved here
4.  consequence / HITL gate
5.  rate limit
6.  execute
...
```

## Why this is safe (the security analysis)

- **Stays after authorization.** A replay returns a prior result; an
  unauthorized caller must never read it. Keeping replay *after* the grant check
  preserves that - an un-granted caller is still denied at step 3 before any
  cached value is reachable. This is the load-bearing ordering constraint and it
  is retained.
- **Does not weaken the HITL gate.** A cached result exists at the idempotency
  key *only if the operation previously passed the HITL gate and executed*
  (records are written at step 9, after the gate at step 4 and execute at step
  7). So a replay can never return a result for an action that was never
  approved - there is nothing to replay until an approved execution happened
  once. Replaying it is therefore not an approval bypass; it is the correct,
  already-approved outcome.
- **Rate limit.** The limiter protects the executor. A replay does not reach the
  executor, so not consuming a token is both correct and an improvement (a flood
  of retries of one completed op can no longer exhaust the budget).
- **Tenant scoping unchanged.** `idempotency_get` is tenant-scoped; the grant
  check is per-context. Two authorized callers in the same tenant sharing a key
  still get the documented shared result, each having passed authorization.

## Threats considered and rejected

- *"A replay bypasses a now-tightened grant."* No: the grant check runs first
  and is re-evaluated on every call against current permissions; only then is a
  replay returned.
- *"A replay bypasses a now-required approval."* No: the approval requirement is
  a property of the verb's consequence, which only matters for *executing*. A
  replay does not execute; and a cached result only exists because an approval
  was satisfied at the original execution.
- *"Key collision leaks data across callers."* Unchanged by this move - keys are
  tenant-scoped and authorization still precedes replay.

## Test plan (to land with the change)

- `SEC-14` + `NFR-REL-02`: an idempotent retry of an approved+executed
  HIGH-consequence verb (same key, same spent approval) returns the stored
  result and does **not** raise `PendingHuman`.
- `FR-KER-05`: an idempotent retry does not consume a rate-limit token (set a
  limit of 1, execute, then retry many times under the same key - none are
  `RateLimited`).
- Regression: an idempotent key for a verb that was **never** approved/executed
  has no cached result, so a first gated call still raises `PendingHuman`
  (replay cannot manufacture a bypass).
- Audit: both the original and the replayed call are audited (the replay is a
  distinct event with the prior output), so the chain stays complete.

## Disposition

Routed for review. Do not patch `dispatch.py` until ratified. The fix is small
and the analysis above is the case for it; the bench (or the reviewer) owns the
decision to re-order the chokepoint.
