"""The audit-outbox janitor (SEC-16 audit-always, durable half) - the drain.

An ``AuditWriter.write`` whose append faulted durably deferred the (scrubbed)
event payload to the ``audit_outbox`` table; this module drains it. Shape
mirrors the HITL expiry janitor (:mod:`boltrig.kernel.hitl_expiry`): a
deterministic sweep the caller can drive, a cancellable forever-loop that
idle-sleeps and never dies on a bad cycle (P9), and an env-knob interval reader.

CHAIN-SAFETY IS THE DESIGN CONSTRAINT. The audit stream is hash-chained per
tenant with per-tenant monotonic seq, so a deferred event CANNOT be inserted
"where it would have gone": its seq/prev_hash/hash are re-derived at drain time
against the then-current head. The chain therefore stays contiguous and
verifiable; the event's own ``ts`` preserves the ACTION time, and its ``detail``
carries an ``outbox_deferred`` marker recording that the row was admitted late -
honest about ordering rather than silently backdated. A verifier re-derives the
chain over seq, which is unaffected.

Backoff: attempts * 30s capped at 10 minutes, so a hard-down database is not
hammered while a transient blip is retried within a minute. Enqueue-time
``next_retry_at`` is ``now()``; the first drain attempt therefore happens on the
janitor's next cycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boltrig.models import utcnow
from boltrig.observability.background_jobs import (
    record_background_attempt,
)
from boltrig.store import Store

from .audit import AuditWriter, audit_event_from_payload

log = logging.getLogger("boltrig.kernel.audit_outbox")

DEFAULT_INTERVAL_SECONDS = 60.0
INTERVAL_ENV = "BOLTRIG_AUDIT_OUTBOX_INTERVAL"
_BACKOFF_BASE_SECONDS = 30.0
_BACKOFF_CAP_SECONDS = 600.0
_DRAIN_BATCH = 100


def audit_outbox_interval_from_env(env: dict[str, str] | None = None) -> float:
    """The drain interval in seconds; <= 0 disables the janitor."""
    source = os.environ if env is None else env
    raw = source.get(INTERVAL_ENV, "")
    try:
        return float(raw) if raw else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


async def drain_tenant_once(
    writer: AuditWriter, store: Store, tenant_id: str
) -> tuple[int, int]:
    """Drain one tenant's due outbox rows. Returns (drained, deferred_again)."""
    drained = 0
    deferred = 0
    now = utcnow()
    for row in await store.audit_outbox_due(tenant_id, now, limit=_DRAIN_BATCH):
        payload = row["payload"]
        if not isinstance(payload, dict):  # a JSONB row round-trips as dict; fail closed
            log.error(
                "audit outbox row %s is not a dict payload; quarantining it",
                row.get("id"),
            )
            await store.audit_outbox_delete(row["id"])
            continue
        try:
            event = audit_event_from_payload(payload)
            await writer.write_now(event)
        except Exception as exc:  # the fault persists: back off, keep the row (P9)
            deferred += 1
            attempts = int(row.get("attempts") or 0) + 1
            backoff = min(_BACKOFF_BASE_SECONDS * attempts, _BACKOFF_CAP_SECONDS)
            from datetime import timedelta

            await store.audit_outbox_mark_failed(
                row["id"], type(exc).__name__, utcnow() + timedelta(seconds=backoff)
            )
            log.warning(
                "audit outbox drain retry %d for row %s (%s); next attempt in %.0fs",
                attempts, row.get("id"), type(exc).__name__, backoff,
            )
        else:
            drained += 1
            await store.audit_outbox_delete(row["id"])
            log.info(
                "audit outbox drained row %s into the chain (seq=%s, verb=%s)",
                row.get("id"), event.seq, event.verb,
            )
    return drained, deferred


async def run_audit_outbox_sweep(
    store: Store,
    *,
    writer: AuditWriter | None = None,
    process_instance_identity: str | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> int:
    """Drain every tenant's due outbox rows once. Returns rows drained.

    Enumerates tenants via ``store.list_orgs`` like the expiry and anchor sweeps
    (RLS: each tenant's rows are read inside its own fence). One tenant's failure
    is logged and the sweep continues (P9)."""
    w = writer if writer is not None else AuditWriter(store)
    drained_total = 0
    orgs = await store.list_orgs()
    if not orgs:
        # Same silence hazard the expiry sweep documents: a zero-tenant
        # enumeration over nine hours once produced no receipt and no log line.
        log.warning(
            "audit outbox: enumerated ZERO tenants, so NO deferred row was drained "
            "(SEC-16). list_orgs must run outside the RLS fence."
        )
    for org in orgs:
        attempted_at = utcnow()
        try:
            drained, _deferred = await drain_tenant_once(w, store, org.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # one tenant's fault never stops the sweep (P9)
            log.exception("audit outbox sweep failed for tenant=%s; continuing", org.id)
            if process_instance_identity is not None:
                await record_background_attempt(
                    store,
                    tenant_id=org.id,
                    job_name="audit_outbox",
                    process_instance_identity=process_instance_identity,
                    interval_seconds=interval,
                    attempted_at=attempted_at,
                    succeeded=False,
                    item_count=0,
                )
        else:
            drained_total += drained
            if process_instance_identity is not None:
                await record_background_attempt(
                    store,
                    tenant_id=org.id,
                    job_name="audit_outbox",
                    process_instance_identity=process_instance_identity,
                    interval_seconds=interval,
                    attempted_at=attempted_at,
                    succeeded=True,
                    item_count=drained,
                )
    return drained_total


async def run_audit_outbox_forever(
    store: Store,
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    process_instance_identity: str | None = None,
    writer: Any = None,
) -> None:
    """Loop :func:`run_audit_outbox_sweep` forever; cancellable, idle-sleeping."""
    while True:
        try:
            await run_audit_outbox_sweep(
                store,
                writer=writer,
                process_instance_identity=process_instance_identity,
                interval=interval,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the janitor (P9)
            log.exception("audit outbox sweep cycle failed; continuing")
        await asyncio.sleep(interval)
