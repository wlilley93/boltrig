"""Periodic audit-rollup anchoring ([2026] VJS-COUNTY 9, D4).

The rollup anchor (:class:`boltrig.kernel.security_events.AuditAnchorer`) seals a
contiguous audit-chain segment for a tenant so a verifier can later confirm the
segment has not been rewritten. The anchorer computes + writes the anchor; it is
the *trigger* that was missing - nothing called it periodically. This is that
trigger: a worker-side janitor that, on an interval, walks every tenant (org) and
seals the un-anchored tail of its audit chain.

Shape mirrors the retention janitor (:mod:`boltrig.fleet.retention`) and the
delegation pump (:class:`boltrig.fleet.pump.WorkPump`): a ``run_anchor_sweep_detailed``
the caller can drive deterministically, plus a cancellable ``run_anchor_forever``
loop that idle-sleeps and never dies on a bad cycle (P9).

Independent of the durable engine. Anchoring only reads the audit chain and
writes an anchor row through the store, so it needs no Hatchet: whether the
worker selected the ``HatchetExecutor`` or the ``LocalDurableExecutor`` fallback,
this loop runs the same way and degrades cleanly when Hatchet is absent (no
crash). It is NOT expressed as a Hatchet cron because the codebase has no native
Hatchet cron/scheduled-workflow seam (the durable tasks are enqueue/event driven,
hatchet_app.py); the WorkPump-style interval loop is the pattern that exists.

Whole-tenant seal. Each sweep anchors the tenant chain with ``workspace_id=None``,
which covers EVERY audit row for the tenant (including org-wide rows that carry no
workspace). Per-workspace anchoring would split the seal and miss the NULL-
workspace rows, so the complete rollup is the tenant-level one; the anchorer still
exposes a per-workspace ``anchor(workspace_id=...)`` for a future granular need.

Keys-only + side-effect-free beyond writing anchor rows (K-20): no audit content
is copied, no row is mutated, and a tenant with no audit rows (or no new rows
since its last anchor) is a clean no-op.

Not wired into any live process by itself; the fleet worker starts it alongside
the pump (see :mod:`boltrig.api.worker`). To drive it standalone, e.g.

    import asyncio
    from boltrig.api.bootstrap import build_kernel_async
    from boltrig.fleet.anchor import run_anchor_forever, anchor_interval_from_env

    async def _main():
        kernel = await build_kernel_async()
        await run_anchor_forever(
            kernel.store, kernel.anchorer, interval=anchor_interval_from_env()
        )

    asyncio.run(_main())
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from typing import Any

from .sweep_progress import SweepProgress

log = logging.getLogger("boltrig.fleet.anchor")

# The env knob for the sweep interval, in seconds. The default is DAILY - a
# tamper-evidence janitor, not a hot loop. A value <= 0 disables the loop (the
# worker then logs it as off), so a deployment can opt out without code changes.
INTERVAL_ENV = "BOLTRIG_AUDIT_ANCHOR_INTERVAL"
DEFAULT_INTERVAL_SECONDS = 86_400.0  # daily


def anchor_interval_from_env() -> float:
    """The configured sweep interval (seconds), or :data:`DEFAULT_INTERVAL_SECONDS`.

    A malformed value falls back to the default (never a boot crash, P9). A value
    <= 0 is honoured as "disabled" and returned as-is so the caller can skip the
    loop.
    """
    raw = os.environ.get(INTERVAL_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning(
            "%s=%r is not a number; using the daily default", INTERVAL_ENV, raw
        )
        return DEFAULT_INTERVAL_SECONDS


async def anchor_tenant_once(anchorer: Any, tenant_id: str) -> Any | None:
    """Seal the un-anchored tail of one tenant's audit chain (whole-tenant).

    Thin over :meth:`AuditAnchorer.anchor` with ``workspace_id=None`` (complete
    coverage). Returns the written anchor, or ``None`` when the tenant has no new
    audit rows to seal (a clean no-op).
    """
    return await anchorer.anchor(tenant_id)


@dataclass(frozen=True)
class AnchorSweepOutcome:
    """What one sweep actually did, as three numbers the caller can judge.

    ``sealed`` alone cannot be judged: a tenant with no new audit rows is a clean
    no-op, so sealed=0 is the correct result for a quiet deployment AND the
    result of a sweep that failed on every tenant, or saw no tenants at all.
    """

    tenants: int
    sealed: int
    failed: int

    @property
    def handled(self) -> int:
        """Tenants evaluated without error. A no-op counts: it was still handled."""
        return self.tenants - self.failed


async def run_anchor_sweep_detailed(store: Any, anchorer: Any) -> AnchorSweepOutcome:
    """Anchor every tenant's un-anchored tail once, reporting what was seen.

    Enumerates orgs via ``store.list_orgs`` (an org's id IS its tenant_id) and
    seals each. One tenant's failure is logged and the sweep continues (P9), so a
    single bad tenant never stops the rest.
    """
    sealed = 0
    failed = 0
    orgs = await store.list_orgs()
    for org in orgs:
        try:
            anchor = await anchor_tenant_once(anchorer, org.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # one tenant's fault never stops the sweep (P9)
            log.exception("anchor sweep failed for tenant=%s; continuing", org.id)
            failed += 1
            continue
        if anchor is not None:
            sealed += 1
            log.info(
                "audit-anchor: sealed tenant=%s seq[%s..%s] (dev_fallback=%s)",
                org.id, anchor.seq_start, anchor.seq_end, anchor.is_dev_fallback,
            )
    return AnchorSweepOutcome(tenants=len(orgs), sealed=sealed, failed=failed)



async def run_anchor_forever(
    store: Any,
    anchorer: Any,
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Loop :func:`run_anchor_sweep_detailed` forever; cancellable, idle-sleeping.

    A bad cycle is logged and the loop continues - an anchor failure never kills
    the janitor (P9), mirroring the pump's ``run_forever`` and the retention
    loop. Cancellation propagates so the task shuts down cleanly. This depends on
    nothing but the store, so it runs whether or not Hatchet is present.

    Every cycle now says what it saw against what it did. This loop ran for nine
    hours on 2026-07-31 sealing nothing, because RLS had made its tenant
    enumeration return an empty list, and it produced no output whatsoever - the
    only evidence was an audit chain that had quietly stopped being anchored.
    """
    from boltrig.models.base import utcnow
    from boltrig.observability.background_jobs import new_background_process_identity

    progress = SweepProgress("audit-anchor")
    # SweepProgress writes to the LOG, which survives no restart and answers no
    # operator query. The durable half is the receipt ledger /readyz reads. At a
    # DAILY interval the log is especially weak evidence: a rotated log means the
    # last thing this janitor said is simply gone.
    identity = new_background_process_identity()
    while True:
        attempted_at = utcnow()
        succeeded = True
        sealed = 0
        try:
            outcome = await run_anchor_sweep_detailed(store, anchorer)
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the janitor (P9)
            succeeded = False
            log.exception("audit-anchor sweep cycle failed; continuing")
        else:
            _report(progress, outcome)
            sealed = outcome.sealed
            # A tenant that raised is a failed sweep for that tenant. Zero tenants
            # needs no clause here and must not get one: _record iterates the same
            # empty list and writes NOTHING, so readiness reports the case as
            # `attempt_evidence_not_observed` - absent evidence, which is the honest
            # description of a janitor that cannot see the fleet. A `tenants > 0`
            # term would read as load-bearing while never being able to be false.
            succeeded = outcome.failed == 0
        await _record(store, identity, interval, attempted_at, succeeded, sealed)
        await asyncio.sleep(interval)


async def _record(
    store: Any,
    identity: str,
    interval: float,
    attempted_at: Any,
    succeeded: bool,
    sealed: int,
) -> None:
    """Write one attempt receipt per tenant this janitor is responsible for.

    Receipts are tenant-scoped, so a sweep that enumerated NO tenants has nowhere
    to write - which is precisely the failure. The readiness surface catches it as
    stale evidence instead, exactly as it caught the hitl-expiry outage.
    """
    from boltrig.observability.background_jobs import record_background_attempt

    try:
        orgs = await store.list_orgs()
    except Exception:  # evidence must never change the sweep outcome
        log.warning("audit-anchor could not enumerate tenants for evidence", exc_info=True)
        return
    for org in orgs:
        await record_background_attempt(
            store,
            tenant_id=org.id,
            job_name="anchor",
            process_instance_identity=identity,
            interval_seconds=interval,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=sealed,
        )


def _report(progress: SweepProgress, outcome: AnchorSweepOutcome) -> None:
    """Publish one cycle, and treat an empty tenant list as a fault of its own.

    ``seen`` is the tenants enumerated and ``acted`` the ones evaluated without
    error, so a sweep failing on every tenant escalates to STALLED. That pair
    cannot catch zero tenants - seen=0/acted=0 is idle by definition, the blind
    spot SweepProgress documents - and zero tenants is precisely how this janitor
    died. A control-plane enumeration returning nothing is therefore called out
    separately, at WARNING, with the cause that has actually produced it.
    """
    if outcome.tenants == 0:
        log.warning(
            "audit-anchor: enumerated ZERO tenants, so nothing was anchored. This is "
            "NOT an idle sweep. list_orgs must run outside the RLS fence; if it is "
            "bound to a tenant the policy matches nothing and returns no rows."
        )
    progress.record(seen=outcome.tenants, acted=outcome.handled)
    if outcome.failed:
        log.warning(
            "audit-anchor: %d of %d tenant(s) failed to anchor",
            outcome.failed, outcome.tenants,
        )
