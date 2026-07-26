# The chat lane seals a live user bearer and never sweeps it

Date: 2026-07-26. Evidence from the live Classical Visas tenant.

## The symptom, from the record

`credential_refs` on `cvboltrig`:

| kind | rows | oldest |
|---|---|---|
| `adapter_bearer` | **29** | 2026-07-25 |
| non-run-scoped | 5 | 2026-07-24 |
| `held_call` | 0 | - |

Zero `held_call` rows is decision 0018's Order 7 working: every hold settled and dropped its
seal. The 29 `adapter_bearer` rows are the defect. Each one is a **caller's clamped external
opbox-kernel session bearer**, sealed at rest, that nothing will ever delete.

Joined against `work_items` they alternate exactly:

```
run:25c6cba1...:adapter_bearer:opbox   no work item      <- delegated child
run:90155387...:adapter_bearer:opbox   work item, done   <- chat turn root
run:2b0e11be...:adapter_bearer:opbox   no work item
run:4846c817...:adapter_bearer:opbox   work item, done
...
```

15 roots + 14 children. **Every chat turn leaks two live bearers, forever.** That is one day of
light testing by a single user.

## Why

`sweep_run_scoped` (`kernel/credentials.py:344`) has exactly **one** caller in the entire
repository: `fleet/pump.py:584`, the org lane's terminal hook.

But the parity bearer is sealed exclusively by the **chat** lane (`fleet/chat.py:744`,
`seal_run_scoped_adapter_bearer`). And the chat turn settles its own work item **directly**:

```python
        item.status = WorkStatus.FAILED
        item.result = {"error": type(exc).__name__}
    await kernel.store.update_work_item(item)   # <- terminal, and that is all
```

It never routes through `pump._on_terminal`, so the only sweep hook never fires for the only lane
that seals. The one lane that creates the secret is the one lane that never retires it.

The child half is worse: `spawn._inherit_adapter_bearer` re-seals the bearer under the **child**
run id (it must - `resolve_run_scoped_credential` keys on `context.run_id`, and the dispatch
happens on the child). A delegated child has **no work item at all**, so the pump could never have
swept it even in principle.

Two docstrings assert the lifecycle that no caller provided:

* `credentials.py:289` - "Swept with the run's other refs on terminal (`sweep_run_scoped`)"
* `spawn.py:429` - "so `sweep_run_scoped` still clears it on that run's terminal"

Meanwhile two other modules already state the truth as known fact - `held_call.py:314` and
`hitl_expiry.py:109` both say "the chat lane never calls `sweep_run_scoped`, its only caller is the
org lane". The knowledge was in the tree; nothing connected it to the bearer.

## What this is NOT

Checked and dismissed, so nobody re-files them:

* **Not an expiry problem.** `seal_run_scoped_adapter_bearer` writes no TTL and the store has no
  reaper. The row is durable until something deletes it, and nothing does.
* **Not exploitable as a lateral move.** `resolve_run_scoped_credential` is fail-closed on
  (run id, adapter id, owner), so a foreign run resolves to `None`. The exposure is a live
  credential resting indefinitely beyond the life and authority of the session that issued it,
  not a path to use someone else's.
* **Not the cause of the `adapter_unauthorised` resume.** That was a test harness passing an empty
  `on_behalf_bearer`, so no seal existed and dispatch fell back to the adapter's static credential
  - the exact signature `spawn.py:407` documents. Verified separately: `run_id` and `on_behalf_of`
  both round-trip through `context_to_envelope`, there is no TTL, and the chat lane never sweeps,
  so a held write's bearer does survive its approval window.

## The fix

The rule installed: **a run's secrets live exactly as long as something can legitimately replay
under that run, and not one moment longer.**

`held_call.sweep_run_credentials_if_settled(store, tenant, run)` is the single seam. It is guarded
by `any_held_call_paused`, and the guard is load-bearing in **both** directions, because
`delete_credential_refs_for_run` deletes the whole `run:<id>:` prefix:

* sweep too late and a live user bearer rests forever (this finding);
* sweep too early and it destroys the **held call's own seal**, so an approved write can never be
  replayed and Order 6(i) refuses it as unreadable.

Wired at all four terminals:

| terminal | site | when |
|---|---|---|
| chat turn | `chat._settle_turn` | the turn settles its work item |
| delegated child | `spawn._retire_child_credentials` | both exits of `_invoke_runtime` |
| held write resolves | `held_call.settle_held_call` | the deferred sweep the two above skipped |
| org lane | `pump._on_terminal` | now guarded, so it cannot destroy a live seal |

`settle_held_call` covers every terminal outcome at once because they all already route through
it: redeemed, declined, refused as unreadable, and timed out (`hitl_expiry._retire_held_call`).

## Tests

`tests/security/test_held_write_resume.py`, six cases. Both directions were proved by seeded
failure rather than assumed:

* disable the guard -> `test_a_paused_hold_keeps_the_run_secrets_its_own_resume_needs` and
  `test_a_second_paused_hold_keeps_the_run_alive` fail;
* remove the deferred sweep -> `test_settling_the_hold_retires_the_bearer_the_turn_sealed` and
  `test_a_second_paused_hold_keeps_the_run_alive` fail.

The first test also carries the unguarded delete inline as a control, so the record shows what the
old behaviour destroyed.

`test_a_chat_turn_retires_the_bearer_it_sealed` closes the loop end to end on the lane that leaked:
it drives a real `build_turn_executor` turn with an `on_behalf_bearer`, and its stub spawner probes
the credential MID-TURN. That probe is what makes it discriminate - asserting only that the bearer
is gone afterwards would pass just as happily against a turn that never sealed one, which is the
same worthless shape as a guard that cannot fail.

## Residual

The 29 rows already on the live tenant are **not** retroactively cleaned by this change - it stops
new ones and retires runs that settle after it ships. Purging the existing rows is a data
operation on a client tenant and is deliberately left for an explicit decision, not folded into a
code fix.
