# A caller could assert somebody else's run id at the write doors

Found 2026-07-25 by an adversarial bug sweep, then confirmed by three independent
refuters who each reproduced it end to end over the real HTTP door before I
touched anything. Fixed the same day (SEC-186).

## What was wrong

`POST /v1/invoke` built its invocation context with
`run_id=body.context.get("run_id")` and nothing else: no validation, no ownership
check. `RESERVED_CONTEXT_KEYS` did not help, because it filters the `extra` dict
and `run_id` is a separate named parameter. `POST /v1/spawn` did the same, for
both `run_id` and `parent_run_id`.

That string is not decoration. Three things act on it:

1. **Run-scoped adapter bearers.** `dispatch.py` calls
   `resolve_run_scoped_credential(tenant, context.run_id, target_ref)`, and a
   sealed per-run bearer OVERRIDES the adapter's static credential. This is the
   permission-parity passthrough: the bearer carries a specific user's clamped
   downstream authority.
2. **Secure answers (SEC-181).** `resolve_run_scoped_params` resolved a
   `credential:run/<run>/<purpose>` reference to its plaintext.
3. **The run's event stream and its HITL bindings.** `Dispatcher._emit` publishes
   `tool_call`/`tool_result` against the context run id, and `_ask_user` binds a
   new HITL to it.

The fence on (1) and (2) was `run_id != context_run_id`. Both sides of that
comparison came out of the SAME request, so they always agreed. Quoting a live
run id was sufficient to be handed that run's sealed material.

The docstrings asserted the opposite of the behaviour: "only the SAME run may
resolve it", "scoped fail-closed to that run+adapter", and a claim that a
lingering reference is bounded because "it can never be resolved by any other
run". The invariant catalogue said resolution "FAILS CLOSED for another run". All
of that was true of the resolver and false of the system, because the door let
the attacker choose which run they were.

The asymmetry is the tell: every READ path already fenced this on the work item's
`on_behalf_of` (`visible_run_events`, `cancel_run`, `hitl_http`'s
`answer_hitl_question` with its literal "not your run"), and the sibling MCP door
deliberately pins `run_id=None` for a user-tier caller for exactly this reason.
Only the two write doors did not.

## Reachability, stated honestly

Not remote-unauthenticated. It needs an authenticated same-tenant principal, a
grant on some verb bound to the target adapter, and knowledge of a live victim
run id. Run ids are uuid4 and not published wholesale, but they are not secret
either: they reach same-department peers through the console overview, `/v1/work`
and audit trees. The bearer leg additionally requires the tenant to be running
the parity passthrough.

All three refuters graded it high rather than critical for those reasons, and
that grading is the honest one. What makes it worth this much text is not the
grade but the shape: the primitive was "caller-asserted identity used as the sole
fence on a credential", and the code believed otherwise in writing.

## The fix, in two independent layers

**At the doors** (`kernel/run_access.py::foreign_run_asserted`, used by
`/v1/invoke` and `/v1/spawn`): a body-supplied `run_id` or `parent_run_id` naming
a work item owned by another user is refused 403 "not your run" before any
dispatch, using the same predicate the read paths already use.

Deliberately narrow, so it denies impersonation without breaking the run id's
long-standing second job as a correlation label. A run with no work item is owned
by nobody; a work item with no `on_behalf_of` is an internal item no user owns.
Both stay admissible, and both are covered by the second layer.

Existence is checked WITHOUT the workspace fence. Scoping the lookup would report
a run in another workspace as "no such run", which falls into the permissive
branch - the check would have got weaker the further the caller was from the run.

**At the resolver** (`kernel/credentials.py::_owner_matches`): every run-scoped
seal now records the identity it belongs to and resolves only for that identity.
`seal_run_scoped_value` and `seal_run_scoped_adapter_bearer` require an owner and
refuse without one; `_inherit_adapter_bearer` inherits only what the same owner
sealed and re-seals to that same owner, so a child spawn cannot launder a
stranger's bearer into a run the caller owns.

Two layers because the door fence is a policy about one route and the resolver
fence is a property of the material. Whatever a future door decides to trust, the
bearer only resolves for the user it was minted for.

## Compatibility

A row sealed before this fence carries no owner and now resolves for nobody. Run
scoped rows are swept at run terminal and live only for the length of a run, so
the cost is bounded to the runs in flight at deploy time: a secure answer must be
re-asked, and a passthrough bearer falls back to the adapter's static credential,
which is the documented behaviour when no bearer is sealed.

## Evidence

`tests/security/test_asserted_run_ownership.py` (4 tests) and four additions to
`tests/security/test_run_scoped_adapter_bearer.py`, all declared under SEC-186.
Seeded-failure verified in both directions: reverting the door predicate fails 3
of the door tests, and reverting `_owner_matches` fails 3 of the resolver tests.

One test changed rather than added:
`test_round_eleven.py::test_department_scoped_user_can_read_visible_work_run_events`
pins the number of run lookups to keep the read path off a per-frame lookup. It
now expects three rather than two, because the POST that seeds the events does
its own ownership check. Still one lookup per request.
