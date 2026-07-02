"""Retention purge: hard-erasure of closed conversations (M11, right-to-erasure).

``DELETE /v1/me/conversations/{id}`` soft-closes a thread (status=CLOSED) so it
can be recovered within a grace window; the durable HARD-erasure is this worker's
job. Once a closed thread is older than the retention window its body and every
message are hard-deleted from the store, so a conversation the user asked to
delete does not persist in Postgres indefinitely - the M11 finding (memory facts
already hard-erase; conversations did not).

The audit log is EXEMPT and never purged here: it is the tamper-evident hash
chain (SEC-16); erasing it would break ``verify()`` and the accountability
record. Right-to-erasure covers the conversation content, not the fact that a
governed action happened.

Shape mirrors the delegation pump (:class:`boltrig.fleet.pump.WorkPump`): a
``run_retention_once`` the caller can drive deterministically, plus a cancellable
``run_retention_forever`` loop that idle-sleeps and never dies on a bad cycle
(P9). "Now" is injected, never read from a wall clock inside the store layer, so
the cutoff is testable and this carries no Date.now-style nondeterminism.

Not wired into any live process by default (like the backup sidecar, SEC-71):
schedule it with a small entrypoint or a cron / systemd timer, e.g.

    import asyncio
    from boltrig.api.bootstrap import build_kernel_async, _DEFAULT_TENANT, _find_manifest
    from boltrig.config import load_manifest
    from boltrig.fleet.retention import run_retention_forever, retention_days_from_manifest

    async def _main():
        kernel = await build_kernel_async()
        manifest = load_manifest(_find_manifest()) if _find_manifest() else None
        tenant = manifest.tenant_id if manifest else _DEFAULT_TENANT
        days = retention_days_from_manifest(manifest)
        await run_retention_forever(kernel.store, tenant, days)

    asyncio.run(_main())
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

log = logging.getLogger("boltrig.fleet.retention")

# The default retention window (days) when the manifest carries no privacy
# section. A CLOSED thread older than this is hard-purged (right-to-erasure).
DEFAULT_RETENTION_DAYS = 30
# Idle sleep between sweeps in the forever loop - a janitor, not a hot loop.
DEFAULT_INTERVAL_SECONDS = 3600.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_retention_once(
    store: Any,
    tenant_id: str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    *,
    now: datetime | None = None,
) -> int:
    """Purge closed conversations older than ``retention_days`` for one tenant.

    ``now`` is injected (only the top-level caller reads the wall clock) so the
    cutoff is deterministic and testable. Returns the number of conversations
    hard-erased this sweep (their messages go with them; the audit log does not).
    """
    at = now if now is not None else _utcnow()
    cutoff = at - timedelta(days=max(0, int(retention_days)))
    purged = await store.purge_closed_conversations(tenant_id, cutoff)
    if purged:
        log.info(
            "retention: hard-purged %d closed conversation(s) for tenant=%s older "
            "than %s (M11 right-to-erasure)", purged, tenant_id, cutoff.isoformat(),
        )
    return purged


async def run_retention_forever(
    store: Any,
    tenant_id: str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    clock: Callable[[], datetime] = _utcnow,
) -> None:
    """Loop :func:`run_retention_once` forever; cancellable, idle-sleeping.

    A bad sweep is logged and the loop continues - a purge failure never kills the
    janitor (P9), mirroring the pump's ``run_forever``. Cancellation propagates so
    the task shuts down cleanly.
    """
    while True:
        try:
            await run_retention_once(store, tenant_id, retention_days, now=clock())
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad sweep never kills the janitor (P9)
            log.exception("retention sweep failed; continuing")
        await asyncio.sleep(interval)


def retention_days_from_manifest(manifest: Any) -> int:
    """The configured retention window, or :data:`DEFAULT_RETENTION_DAYS`.

    Reads ``privacy.retention_days`` (config/manifest.py ``PrivacyConfig``); a
    manifest that sets no retention keeps the default. No new manifest knob is
    added - the privacy section already carries this field.
    """
    days = getattr(getattr(manifest, "privacy", None), "retention_days", None)
    return int(days) if days else DEFAULT_RETENTION_DAYS
