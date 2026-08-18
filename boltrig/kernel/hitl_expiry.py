"""Periodic HITL timeout enforcement (SEC-14) - the expiry sweep janitor.

A HITL request's ``timeout_at`` is enforced in two layers. The LAZY layer lives
in :class:`~boltrig.kernel.hitl.HITLManager` (an overdue request refuses an
answer with a typed 409 and a stale approval can never be consumed). This module
is the SWEEP layer: a worker-side janitor that, on an interval, transitions
every overdue PENDING request to TIMED_OUT so a request raised by a crashed run
never sits actionable (and listed as pending) forever.

Shape mirrors the audit-anchor janitor (:mod:`boltrig.fleet.anchor`): a
``run_hitl_expiry_sweep`` the caller can drive deterministically, a cancellable
``run_hitl_expiry_forever`` loop that idle-sleeps and never dies on a bad cycle
(P9), and an env-knob interval reader. It depends on nothing but the store, so
it runs the same on Hatchet or the local fallback.

Linked work item semantics. A request may carry a ``work_item_id`` (the fleet
parks such an item AWAITING_HUMAN when it files the request). On expiry the
human never acted, so the item must NOT silently succeed - and silently
REQUEUING it would just re-raise the same request and loop. The sweep therefore
settles the item at the neutral terminal ``CANCELLED`` (the same state an
owner-initiated cancel writes; it scores neutral like AWAITING_HUMAN, never a
success), clears its lease, and records why on ``result``. Reviving the work is
an explicit human decision (re-file the item), never an automatic retry.

The request's human is notified best-effort on their bound channel surface
(``hitl_expired`` event, SEC-179): fail-safe like every notify path - a
delivery fault never voids the recorded transition.

Not wired into any live process by itself; the fleet worker starts it alongside
the pump and the anchor janitor (see :mod:`boltrig.api.worker`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boltrig.notification_catalogue import HITL_EXPIRED_EVENT
from boltrig.models import WorkStatus, utcnow
from boltrig.observability.background_jobs import (
    new_background_process_identity,
    record_background_attempt,
)
from boltrig.store import Store

from .channel_notify import enqueue_user_notification
from .held_call import settle_held_call
from .hitl import request_timed_out

log = logging.getLogger("boltrig.kernel.hitl_expiry")

# The env knob for the sweep interval, in seconds. Short (one minute): the lazy
# layer already fails overdue answers closed, so the sweep is hygiene - parking
# zombies and settling their work items promptly. A value <= 0 disables the
# loop (the worker then logs it as off); a malformed value falls back to the
# default (never a boot crash, P9).
INTERVAL_ENV = "BOLTRIG_HITL_EXPIRY_INTERVAL"
DEFAULT_INTERVAL_SECONDS = 60.0


def hitl_expiry_interval_from_env() -> float:
    """The configured sweep interval (seconds), or :data:`DEFAULT_INTERVAL_SECONDS`.

    Mirrors ``anchor_interval_from_env``: a malformed value falls back to the
    default; a value <= 0 is honoured as "disabled" and returned as-is.
    """
    raw = os.environ.get(INTERVAL_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning(
            "%s=%r is not a number; using the default", INTERVAL_ENV, raw
        )
        return DEFAULT_INTERVAL_SECONDS


async def _linked_work_item(store: Store, req: Any) -> Any | None:
    """The work item an expired request parked (by id, else by run id)."""
    if req.work_item_id:
        item = await store.get_work_item(req.tenant_id, req.work_item_id)
        if item is not None:
            return item
    if req.run_id:
        return await store.get_work_item_by_run_id(req.tenant_id, req.run_id)
    return None


async def _park_expired_item(store: Store, req: Any) -> None:
    """Settle the expired request's AWAITING_HUMAN work item at CANCELLED.

    Neutral, never a silent success: the human never acted. An item in any
    other state (resumed, finished, already cancelled) is left untouched.

    D3 disposal ([2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001): this write is
    NOT lease-fenced, and cannot be. The sweeper never claimed the item, so it
    holds no claim-time token; the parked row's stale tuple belongs to the attempt
    that parked it, and fencing on a value this caller would have to re-read is
    the defeated shape, not a fence.

    Its predicate is the payload-carrying status CAS
    (``transition_work_item_settled``), so a human who re-queues the item in the
    same instant this sweeper fires wins or loses the CAS cleanly - the old
    read-then-write could cancel a freshly re-queued item underneath them."""
    item = await _linked_work_item(store, req)
    if item is None or item.status != WorkStatus.AWAITING_HUMAN:
        return
    await store.transition_work_item_settled(
        req.tenant_id,
        item.id,
        expected=WorkStatus.AWAITING_HUMAN,
        new_status=WorkStatus.CANCELLED,
        result={
            "cancel_reason": "hitl_request_expired",
            "hitl_request_id": req.id,
        },
    )


async def _retire_held_call(store: Store, req: Any) -> None:
    """Drop the seal of a write held by a request that has just timed out.

    The chat lane never called the org lane's terminal sweep (its only caller is the org
    lane), so a held call whose approval expires unanswered would otherwise leave
    its sealed params behind for the life of the database. A request with no held
    write is a no-op. Fail-safe: the recorded expiry is the truth (P9)."""
    if not req.run_id:
        return
    try:
        await settle_held_call(store, req.tenant_id, req.run_id, req.id)
    except Exception:  # noqa: BLE001 - hygiene must never break the sweep
        log.warning("held-call seal could not be dropped on expiry", exc_info=True)


async def _notify_expired(store: Store, req: Any) -> None:
    """Best-effort channel notice that the request expired unanswered (SEC-179).
    Fail-safe, mirroring HITLManager._notify_request."""
    try:
        subject = req.assignee or req.requested_on_behalf_of or req.requested_by
        if not subject:
            return
        await enqueue_user_notification(
            store,
            req.tenant_id,
            subject,
            HITL_EXPIRED_EVENT,
            f"Request timed out unanswered: {req.question}",
        )
    except Exception:  # noqa: BLE001 - delivery is a side channel
        pass


_RECONCILE_GRACE_SECONDS = 90


async def reconcile_answered_tenant_once(kernel: Any, store: Store, tenant_id: str) -> int:
    """Re-fire the resume for ANSWERED requests whose notification was lost.

    The answer path is commit-then-notify: ``answer_hitl`` persists the ANSWERED
    status and only then fires the resume notifier, fail-safe. That fail-safe
    has a cost nobody priced - if the process dies (or the notifier faults)
    between the two, the answer is durable but NOTHING ever re-examines it: the
    approval sits ANSWERED forever, the held checkpoint stays paused forever,
    and the human saw their answer accepted. This pass is the repair arm: every
    ANSWERED request older than a grace window gets its resume re-fired. Safe
    by NFR-REL-03 - each resume leg is CAS-guarded (ANSWERED -> CONSUMED) or
    idempotent - and a no-op for anything already consumed. The grace window
    exists so the sweep cannot race a notifier that is merely slow, not dead.

    One tenant's fault is caught by the caller's P9 bracket, like expiry."""
    refired = 0
    for req in await store.list_answered_hitl(tenant_id):
        response = await store.get_hitl_response(tenant_id, req.id)
        answered_at = getattr(response, "responded_at", None) if response is not None else None
        if (
            answered_at is None
            or (utcnow() - answered_at).total_seconds() < _RECONCILE_GRACE_SECONDS
        ):
            continue
        await kernel.hitl.refire_resume(tenant_id, req.id)
        refired += 1
        log.info(
            "hitl reconcile: re-fired resume for answered request=%s tenant=%s "
            "(verb=%s, age=%.0fs)",
            req.id, tenant_id, req.verb,
            (utcnow() - answered_at).total_seconds(),
        )
    return refired


async def expire_tenant_once(store: Store, tenant_id: str) -> int:
    """Expire every overdue PENDING HITL request for one tenant. Returns the count."""
    expired = 0
    for req in await store.list_pending_hitl(tenant_id):
        if not request_timed_out(req):
            continue
        # The CAS is the transition: a request answered between the list and
        # here is not clobbered, and one winner notifies/parks exactly once.
        if not await store.expire_hitl(tenant_id, req.id):
            continue
        if req.verb == "control.ai_key.set":
            await store.invalidate_ai_key_proposal_for_approval(
                tenant_id, req.id, "expired", utcnow()
            )
        expired += 1
        await _park_expired_item(store, req)
        await _retire_held_call(store, req)
        await _notify_expired(store, req)
        log.info(
            "hitl expiry: request=%s tenant=%s timed out (work_item=%s)",
            req.id, tenant_id, req.work_item_id,
        )
    # AI-key proposals deliberately expire no later than fifteen minutes even
    # when the tenant's general approval timeout is longer. Remove their staged
    # envelopes and retire the now-useless approval ids in the same sweep.
    for approval_id in await store.expire_due_ai_key_secret_proposals(
        tenant_id, utcnow()
    ):
        await store.expire_hitl(tenant_id, approval_id)
    return expired


async def run_hitl_expiry_sweep(
    store: Store,
    *,
    process_instance_identity: str | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    kernel: Any = None,
) -> int:
    """Expire overdue PENDING HITL requests for EVERY tenant once.

    Enumerates tenants via ``store.list_orgs`` (an org's id IS its tenant_id),
    mirroring the anchor sweep. One tenant's failure is logged and the sweep
    continues (P9). Returns the number of requests expired.

    With ``kernel`` the same pass also reconciles lost ANSWER-resume
    notifications (see :func:`reconcile_answered_tenant_once`); the kernel is
    optional so store-only callers (tests, offline tooling) keep the old shape.
    """
    expired = 0
    orgs = await store.list_orgs()
    if not orgs:
        # NOT an idle sweep: nine hours of this on 2026-07-31 produced no receipt
        # and no log line, because RLS had made the enumeration return nothing and
        # the loop below simply never ran. Overdue approvals stopped timing out.
        log.warning(
            "hitl expiry: enumerated ZERO tenants, so NO overdue approval was "
            "expired (SEC-14). list_orgs must run outside the RLS fence; bound to "
            "a tenant the policy matches nothing and returns no rows."
        )
    for org in orgs:
        attempted_at = utcnow()
        try:
            tenant_expired = await expire_tenant_once(store, org.id)
            if kernel is not None:
                # The reconcile pass shares the expiry pass's P9 bracket: one
                # tenant's resume fault is logged, never the sweep's death.
                tenant_expired += await reconcile_answered_tenant_once(
                    kernel, store, org.id
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # one tenant's fault never stops the sweep (P9)
            log.exception("hitl expiry sweep failed for tenant=%s; continuing", org.id)
            if process_instance_identity is not None:
                await record_background_attempt(
                    store,
                    tenant_id=org.id,
                    job_name="hitl_expiry",
                    process_instance_identity=process_instance_identity,
                    interval_seconds=interval,
                    attempted_at=attempted_at,
                    succeeded=False,
                    item_count=0,
                )
        else:
            expired += tenant_expired
            if process_instance_identity is not None:
                await record_background_attempt(
                    store,
                    tenant_id=org.id,
                    job_name="hitl_expiry",
                    process_instance_identity=process_instance_identity,
                    interval_seconds=interval,
                    attempted_at=attempted_at,
                    succeeded=True,
                    item_count=tenant_expired,
                )
    return expired


async def run_hitl_expiry_forever(
    store: Store,
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    process_instance_identity: str | None = None,
    kernel: Any = None,
) -> None:
    """Loop :func:`run_hitl_expiry_sweep` forever; cancellable, idle-sleeping.

    A bad cycle is logged and the loop continues (P9), mirroring
    ``run_anchor_forever``; cancellation propagates for a clean shutdown.
    """
    identity = process_instance_identity or new_background_process_identity()
    while True:
        try:
            await run_hitl_expiry_sweep(
                store,
                process_instance_identity=identity,
                interval=interval,
                kernel=kernel,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the janitor (P9)
            log.exception("hitl expiry sweep cycle failed; continuing")
        await asyncio.sleep(interval)
