"""Periodic audit-rollup anchoring ([2026] VJS-COUNTY 9, D4).

The rollup anchor (:class:`boltrig.kernel.security_events.AuditAnchorer`) seals a
contiguous audit-chain segment for a tenant so a verifier can later confirm the
segment has not been rewritten. The anchorer computes + writes the anchor; it is
the *trigger* that was missing - nothing called it periodically. This is that
trigger: a worker-side janitor that, on an interval, walks every tenant (org) and
seals the un-anchored tail of its audit chain.

Shape mirrors the retention janitor (:mod:`boltrig.fleet.retention`) and the
delegation pump (:class:`boltrig.fleet.pump.WorkPump`): a ``run_anchor_sweep``
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
import logging
import os
from typing import Any

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


async def run_anchor_sweep(store: Any, anchorer: Any) -> int:
    """Anchor the un-anchored tail of EVERY tenant's audit chain once.

    Enumerates orgs via ``store.list_orgs`` (an org's id IS its tenant_id) and
    seals each. One tenant's failure is logged and the sweep continues (P9), so a
    single bad tenant never stops the rest. Returns the number of anchors written
    (tenants with no new rows contribute nothing).
    """
    written = 0
    orgs = await store.list_orgs()
    for org in orgs:
        try:
            anchor = await anchor_tenant_once(anchorer, org.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # one tenant's fault never stops the sweep (P9)
            log.exception("anchor sweep failed for tenant=%s; continuing", org.id)
            continue
        if anchor is not None:
            written += 1
            log.info(
                "audit-anchor: sealed tenant=%s seq[%s..%s] (dev_fallback=%s)",
                org.id, anchor.seq_start, anchor.seq_end, anchor.is_dev_fallback,
            )
    return written


async def run_anchor_forever(
    store: Any,
    anchorer: Any,
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Loop :func:`run_anchor_sweep` forever; cancellable, idle-sleeping.

    A bad cycle is logged and the loop continues - an anchor failure never kills
    the janitor (P9), mirroring the pump's ``run_forever`` and the retention
    loop. Cancellation propagates so the task shuts down cleanly. This depends on
    nothing but the store, so it runs whether or not Hatchet is present.
    """
    while True:
        try:
            await run_anchor_sweep(store, anchorer)
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the janitor (P9)
            log.exception("audit-anchor sweep cycle failed; continuing")
        await asyncio.sleep(interval)
