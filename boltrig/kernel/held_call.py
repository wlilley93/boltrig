"""The HELD CALL record: what a paused write is resumed FROM (decision 0018).

A write the HITL gate holds is resumed by replaying the RECORD OF THE CALL, never
by replaying the agent that produced it. That record is written at the chokepoint
the moment the gate raises ``PendingHuman``, and it is two rows:

  * a ``paused`` ``run_checkpoints`` row on the ROOT run, keyed ``held:<call_id>``
    and carrying the approval request id. The ``held:`` prefix is RESERVED so the
    key can never collide with the workflow interpreter's ``<workflow>:<step>``
    key, and it is what the answer bridge matches on to know a held write is
    waiting;
  * the canonical call ``{noun, verb, params, ctx}`` sealed as a run-scoped
    credential under its own distinct kind (``credentials.HELD_CALL_KIND``).

The params live in the SEAL and never in the checkpoint ``output`` column: that
column is plain JSON and would become a second secret store, which is precisely
what ``dispatch._event_safe`` and ``approval_gate._approval_display_context``
exist to prevent.

Replaying THAT record is what makes the resumed call authorised by construction.
``approval_request_fingerprint`` binds the params verbatim and the initiator's
run id (``hitl.py``), so a resume that re-derived the call from a model, or minted
a fresh run id, could not match the approval it is trying to spend - it would
mint a SECOND request and the user would be asked again (SEC-14). Exactly-once
needs nothing new: ``consume_approved_by`` remains the sole authority and
``store.consume_hitl`` the sole atomic ANSWERED -> CONSUMED transition.

The kernel never imports the fleet (P1): this module writes and reads the record;
WHO replays it is injected at the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from boltrig.models import (
    InvocationContext,
    context_from_envelope,
    context_to_envelope,
)
from boltrig.store import Store

from .credentials import HELD_CALL_KIND, held_call_cred_id

# The reserved checkpoint-step namespace for a held call, and the two statuses a
# held checkpoint takes: PAUSED while the approval is claimable, SPENT once some
# lane has redeemed (or refused) it, so a duplicate delivery re-enters nothing.
HELD_STEP_PREFIX = "held:"
HELD_PAUSED = "paused"
HELD_SPENT = "done"
# The only thing a held checkpoint's plain-JSON ``output`` ever carries: the run
# the seal is keyed to, so a hold found from the dispatched run leads to the root
# without guessing. Never params - that column would become a second secret store.
HELD_ROOT_KEY = "held_run_id"

# The store seams a held call is recorded through. Named here so the gate that
# MINTS an approval and the chokepoint that RECORDS the pause ask exactly the
# same question and cannot drift apart.
_REQUIRED_SEAMS = (
    "upsert_checkpoint",
    "list_checkpoints",
    "set_credential_ref",
    "get_credential_ref",
    "delete_credential_ref",
)

# The lanes that can redeem an approval, named from the record (decision 0018,
# Order 5). Every mint must be able to name one of these.
LANE_CALLER = "caller"
LANE_HELD_WRITE = "held_write"
LANE_INTERPRETER = "interpreter"


def held_step(call_id: str) -> str:
    """The reserved checkpoint step key for one held call."""
    return f"{HELD_STEP_PREFIX}{call_id}"


def is_held_step(step: str) -> bool:
    return step.startswith(HELD_STEP_PREFIX)


def root_run_id(context: InvocationContext) -> str | None:
    """The run a pause belongs to: the run that DELEGATED to this one if any.

    Resolved exactly as ``dispatch._emit_pause`` resolves it. A chat turn never
    calls a verb itself - it spawns a worker whose cell reaches back through the
    MCP face - so the dispatch runs under the CHILD run while the client follows
    the ROOT. Recording the hold under the child would put it on a run nobody
    resumes, which is the same shape as the defect this record exists to cure.
    """
    return context.parent_run_id or context.run_id


def can_record_held_call(store: Store, context: InvocationContext) -> bool:
    """Whether this pause could be RECORDED as a held call if it happened now.

    Two things are needed and both come from the call in hand: an owning identity
    to seal under, and a store carrying the checkpoint + sealed-credential seams.
    A store missing either cannot hold the write, so an approval minted against it
    would be exactly the ground-truth state - ANSWERED with nothing able to claim
    it."""
    owner = context.on_behalf_of or context.actor
    if not owner:
        return False
    return all(callable(getattr(store, seam, None)) for seam in _REQUIRED_SEAMS)


async def _run_is_checkpointed(store: Store, tenant_id: str, run_id: str) -> bool:
    lister = getattr(store, "list_checkpoints", None)
    if lister is None:
        return False
    return bool(await store.list_checkpoints(tenant_id, run_id))


async def name_redeemer(store: Store, context: InvocationContext) -> str | None:
    """Name the lane that will redeem an approval minted for THIS call, else None.

    Derived from the record, never stored beside it:

    * no run at all -> the CALLER. The pause goes back to a synchronous caller
      which holds the request id and redeems by retrying with it. ``run_id IS
      NULL`` in ``hitl_requests`` IS that lane's marker, and the live record shows
      it reaching ``consumed`` (the control-plane ops).
    * the pause is recordable -> the HELD WRITE lane. The chokepoint writes the
      held record and the answer bridge replays it under the same run identity.
    * else, an already-checkpointed run -> the INTERPRETER lane, which re-enters
      the run and re-invokes from its own paused checkpoint.

    Anything else has no claimant and must mint nothing.
    """
    root = root_run_id(context)
    if not root:
        return LANE_CALLER
    if can_record_held_call(store, context):
        return LANE_HELD_WRITE
    if await _run_is_checkpointed(store, context.tenant_id, root):
        return LANE_INTERPRETER
    return None


async def record_held_call(
    store: Store,
    context: InvocationContext,
    *,
    noun: str,
    verb: str,
    params: dict[str, Any],
    request_id: str,
    call_id: str,
) -> bool:
    """Record the pause durably: the ``held:`` checkpoint plus the sealed call.

    Returns False (writing nothing) when this pause is not recordable, which the
    approval gate has already refused to mint against. Failures are NOT swallowed
    like the event relay's are: the relay is observability, this is the record the
    approved write is replayed from, and an approval minted without it is one
    nobody can claim.

    Two checkpoint rows when the call is delegated, for the same reason
    ``_emit_pause`` publishes the pause to two streams: the ROOT run is the one a
    client follows and the one the seal is keyed to, while the HITL request row
    names the run the verb was DISPATCHED on - so a hold recorded only against the
    root could not be found from the answered request, and one recorded only
    against the child could not be continued where anyone is listening. The child
    row is a pointer, carrying the root run id (a run id, never params) so the
    record is followed rather than guessed.
    """
    root = root_run_id(context)
    if not root or not can_record_held_call(store, context):
        return False
    owner = context.on_behalf_of or context.actor
    await store.set_credential_ref(
        context.tenant_id,
        held_call_cred_id(root, request_id),
        {
            "kind": HELD_CALL_KIND,
            "run_id": root,
            "request_id": request_id,
            "owner": owner,
            # The params VERBATIM: the approval fingerprint binds them verbatim,
            # so anything normalised, redacted or re-derived replays as a
            # DIFFERENT action and can never spend the approval it was held for.
            "value": {
                "noun": noun,
                "verb": verb,
                "params": params,
                "ctx": context_to_envelope(context),
            },
        },
    )
    await store.upsert_checkpoint(
        context.tenant_id, root, held_step(call_id), HELD_PAUSED,
        hitl_request_id=request_id,
    )
    if context.run_id and context.run_id != root:
        await store.upsert_checkpoint(
            context.tenant_id, context.run_id, held_step(call_id), HELD_PAUSED,
            output={HELD_ROOT_KEY: root}, hitl_request_id=request_id,
        )
    return True


@dataclass(frozen=True)
class HeldCall:
    """One replayable held write, read back from the record."""

    noun: str
    verb: str
    params: dict[str, Any]
    context: InvocationContext
    request_id: str
    run_id: str
    call_id: str


async def _paused_held(
    store: Store, tenant_id: str, run_id: str, request_id: str
) -> tuple[list[Any], list[str]]:
    """(held checkpoints, other lanes' steps) paused against this request here."""
    held: list[Any] = []
    other: list[str] = []
    for checkpoint in await store.list_checkpoints(tenant_id, run_id):
        if checkpoint.hitl_request_id != request_id:
            continue
        if checkpoint.status != HELD_PAUSED:
            continue
        if is_held_step(checkpoint.step):
            held.append(checkpoint)
        else:
            other.append(checkpoint.step)
    return held, other


def _pointed_root(checkpoints: list[Any], fallback: str) -> str:
    """The run the seal is keyed to, followed from a delegated call's pointer row."""
    for checkpoint in checkpoints:
        root = (checkpoint.output or {}).get(HELD_ROOT_KEY)
        if root:
            return str(root)
    return fallback


async def held_write_is_waiting(
    store: Store, tenant_id: str, run_id: str, request_id: str
) -> bool:
    """Whether the answer bridge's held-write route owns this answered approval.

    Mutually exclusive with the durable/interpreter route by the reserved prefix:
    the interpreter records its OWN paused checkpoint for the step it held, so a
    request claimed by a lane that re-enters its own run is not replayed here as
    well. Two claimants would race the ANSWERED -> CONSUMED CAS, and the loser
    would report a conflict for a write that did run.
    """
    if not run_id or not request_id or not callable(
        getattr(store, "list_checkpoints", None)
    ):
        return False
    held, other = await _paused_held(store, tenant_id, run_id, request_id)
    return bool(held) and not other


async def held_run_id(
    store: Store, tenant_id: str, run_id: str, request_id: str
) -> str:
    """The run a hold is keyed to (itself, or the root it points at)."""
    held, _other = await _paused_held(store, tenant_id, run_id, request_id)
    return _pointed_root(held, run_id)


async def read_held_call(
    store: Store, tenant_id: str, run_id: str, request_id: str
) -> HeldCall | None:
    """The recorded call for an answered approval, or None when it is gone.

    None is a REFUSAL signal, never an invitation to re-derive the call from a
    transcript: an old request, a swept seal or a forgotten checkpoint means the
    canonical action is unknown, and guessing it is exactly the probabilistic
    failure the sealed record exists to remove.
    """
    held, _other = await _paused_held(store, tenant_id, run_id, request_id)
    if not held:
        return None
    root = _pointed_root(held, run_id)
    ref = await store.get_credential_ref(tenant_id, held_call_cred_id(root, request_id))
    if (
        not isinstance(ref, dict)
        or ref.get("kind") != HELD_CALL_KIND
        or ref.get("run_id") != root
        or ref.get("request_id") != request_id
    ):
        return None
    call = ref.get("value")
    if not isinstance(call, dict) or not isinstance(call.get("ctx"), dict):
        return None
    return HeldCall(
        noun=str(call.get("noun") or ""),
        verb=str(call.get("verb") or ""),
        params=dict(call.get("params") or {}),
        context=context_from_envelope(call["ctx"]),
        request_id=request_id,
        run_id=root,
        call_id=held[0].step[len(HELD_STEP_PREFIX):],
    )


async def settle_held_call(
    store: Store, tenant_id: str, run_id: str, request_id: str
) -> None:
    """Retire a held call: drop the seal and mark its checkpoints spent.

    Called on every terminal transition of the request (redeemed, refused,
    conflicted, timed out). The chat lane never calls ``sweep_run_scoped`` - its
    only caller is the org lane - so without this the seal outlives its run. The
    checkpoints flip out of ``paused`` in the same breath so a duplicate delivery
    finds nothing to replay and re-enters the chokepoint not at all.
    """
    if not run_id or not callable(getattr(store, "list_checkpoints", None)):
        return
    held, _other = await _paused_held(store, tenant_id, run_id, request_id)
    root = _pointed_root(held, run_id)
    runs = {run_id, root}
    for run in runs:
        rows = held if run == run_id else (
            await _paused_held(store, tenant_id, run, request_id)
        )[0]
        for checkpoint in rows:
            await store.upsert_checkpoint(
                tenant_id, run, checkpoint.step, HELD_SPENT,
                output=checkpoint.output, hitl_request_id=request_id,
            )
    if callable(getattr(store, "delete_credential_ref", None)):
        await store.delete_credential_ref(
            tenant_id, held_call_cred_id(root, request_id)
        )
