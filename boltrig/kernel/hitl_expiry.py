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

    Its real predicate is the status check above, and that check is a read-then-
    write, so it is not a fence either. The residual race is narrow and worth
    stating rather than implying away: a human who re-queues an item in the same
    instant this sweeper fires can have it cancelled underneath them. Closing it
    needs the status CAS (``transition_work_item_status``) to carry the cancel
    ``result`` too, which it cannot today.
    """
    item = await _linked_work_item(store, req)
    if item is None or item.status != WorkStatus.AWAITING_HUMAN:
        return
    item.status = WorkStatus.CANCELLED
    item.lease_owner = None
    item.lease_expires_at = None
    item.result = {
        "cancel_reason": "hitl_request_expired",
        "hitl_request_id": req.id,
    }
    await store.update_work_item(item)


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
) -> int:
    """Expire overdue PENDING HITL requests for EVERY tenant once.

    Enumerates tenants via ``store.list_orgs`` (an org's id IS its tenant_id),
    mirroring the anchor sweep. One tenant's failure is logged and the sweep
    continues (P9). Returns the number of requests expired.
    """
    expired = 0
    for org in await store.list_orgs():
        attempted_at = utcnow()
        try:
            tenant_expired = await expire_tenant_once(store, org.id)
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
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the janitor (P9)
            log.exception("hitl expiry sweep cycle failed; continuing")
        await asyncio.sleep(interval)
