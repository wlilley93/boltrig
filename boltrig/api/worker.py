"""The fleet worker process. Run with: python -m boltrig.api.worker

Builds the kernel, selects the durable executor (Hatchet in production, the
local fallback offline, US-EXE-05), builds the org from the manifest hierarchy
(Chief of Staff + department heads, P7), and runs the delegation pump: pending
work items are claimed, routed, decomposed, joined and completed (US-FLT-06).
No manifest hierarchy degrades to the minimal default org, never a crash (P9).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boltrig.config import load_manifest, load_settings
from boltrig.store import Store
from boltrig.fleet import (
    anchor_interval_from_env,
    build_org,
    build_spawner,
    register_workers,
    retention_days_from_manifest,
    retention_interval_from_env,
    run_anchor_forever,
    run_retention_forever,
)

from .bootstrap import _DEFAULT_TENANT, _find_manifest, build_kernel_async
from .codex_execution import build_codex_execution_stack

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("boltrig.worker")

_POLL_SECONDS = 5.0


def _start_hitl_expiry_janitor(store: Store) -> "asyncio.Task[None] | None":
    """Start the HITL expiry janitor (SEC-14), or None when disabled.

    On an interval the janitor transitions every overdue PENDING request to
    TIMED_OUT and settles its parked work item, so a request raised by a
    crashed run never sits actionable forever. Same worker-side loop shape as
    the anchor janitor - store-only, engine-independent, never crashes boot
    (P9). Off when BOLTRIG_HITL_EXPIRY_INTERVAL is <= 0; one-minute default
    (the lazy 409 layer already fails overdue answers closed, so this is
    hygiene). Held in a name so the task is not garbage-collected mid-flight.
    """
    from boltrig.kernel.hitl_expiry import (
        hitl_expiry_interval_from_env,
        run_hitl_expiry_forever,
    )

    interval = hitl_expiry_interval_from_env()
    if interval <= 0:
        log.info("hitl-expiry janitor disabled (interval<=0)")
        return None
    log.info("hitl-expiry janitor live (interval=%ss)", interval)
    return asyncio.create_task(
        run_hitl_expiry_forever(store, interval=interval),
        name="hitl-expiry-janitor",
    )


def _start_anchor_janitor(store: Store, anchorer: Any) -> "asyncio.Task[None] | None":
    """Start the audit-rollup anchor janitor (COUNTY 9 D4), or None when disabled.

    On an interval it seals every tenant's un-anchored audit-chain tail so a
    verifier can prove a segment was not rewritten. A worker-side loop (there is
    no native Hatchet cron seam), independent of the durable engine so it runs the
    same on Hatchet or the local fallback, and it never crashes boot (P9). Off
    when BOLTRIG_AUDIT_ANCHOR_INTERVAL is <= 0; conservative daily default. Held
    in a name so the task is not garbage-collected mid-flight."""
    interval = anchor_interval_from_env()
    if interval <= 0:
        log.info("audit-anchor janitor disabled (interval<=0)")
        return None
    log.info("audit-anchor janitor live (interval=%ss)", interval)
    return asyncio.create_task(
        run_anchor_forever(store, anchorer, interval=interval),
        name="audit-anchor-janitor",
    )


def _start_retention_janitor(
    store: Store, tenant: str, manifest: Any
) -> "asyncio.Task[None] | None":
    """Start the retention janitor (M11 / SEC-74), or None when disabled.

    It belongs here because for as long as it existed it belonged NOWHERE. Its own
    docstring told the reader to schedule it with a cron or a small entrypoint, and
    nothing ever did: no compose service, no Makefile target, no deploy unit, no
    ``__main__``. So ``purge_closed_conversations`` had never once run in a
    deployment, while docs/security-conformance.md recorded DATA-07 and PRIV-04 as
    BUILT and SEC-74 claimed a deleted conversation no longer sat in Postgres
    indefinitely. A DELETE soft-closes the thread; without this loop the body and
    every message stay there for good.

    Same shape as the anchor and HITL-expiry janitors: store-only,
    engine-independent, never crashes boot (P9). Off when
    BOLTRIG_RETENTION_INTERVAL is <= 0 - and the worker says which it did, so
    "off" is a decision on the record rather than the silence it used to be."""
    interval = retention_interval_from_env()
    if interval <= 0:
        log.info("retention janitor disabled (interval<=0)")
        return None
    days = retention_days_from_manifest(manifest)
    log.info(
        "retention janitor live (tenant=%s, window=%sd, interval=%ss)",
        tenant, days, interval,
    )
    return asyncio.create_task(
        run_retention_forever(store, tenant, days, interval=interval),
        name="retention-janitor",
    )


async def _run() -> None:
    kernel = await build_kernel_async()  # async build (no nested asyncio.run)
    executor = register_workers(kernel)
    # Honest executor selection (US-EXE-05): the boot record states durability.
    log.info(
        "fleet worker started (%s, durable=%s)",
        type(executor).__name__,
        executor.durable,
    )
    # The org from the manifest hierarchy; a missing/broken manifest degrades to
    # the minimal default org (one CoS over one general head, P9).
    manifest = None
    manifest_path = _find_manifest()
    if manifest_path:
        try:
            manifest = load_manifest(manifest_path)
        except Exception as exc:
            log.warning("manifest load failed (%s); using the default org", exc)
    tenant = manifest.tenant_id if manifest is not None else _DEFAULT_TENANT
    pump = build_org(
        kernel, build_spawner(kernel), manifest, executor=executor,
        # Codex shadow root admission (SEC-172), built here at the composition
        # root: None when BOLTRIG_CODEX_LEDGER is off => no admit.
        codex_execution=build_codex_execution_stack(load_settings(), kernel.store),
    )
    log.info(
        "delegation pump live (tenant=%s, departments=%s)",
        tenant,
        sorted(pump.heads),
    )
    # Each execution owner proves only the tools present in its own image.  The
    # fleet worker probes OpenCode, Browser Use, and loopback Chromium, then
    # publishes a short-lived redacted receipt to shared Redis.  The kernel's
    # /readyz combines it with a kernel-local Herdr probe; it never assumes a
    # fleet hostname or executes fleet binaries in the wrong container.
    from boltrig.fleet.stack_tool_health import run_fleet_tool_heartbeat

    stack_health_task: asyncio.Task[None] | None = None
    if str(os.environ.get("REDIS_URL") or "").strip():
        stack_health_task = asyncio.create_task(
            run_fleet_tool_heartbeat(tenant),
            name="fleet-stack-tool-heartbeat",
        )
        # "started", not "live". Whether it actually publishes is decided INSIDE
        # run_fleet_tool_heartbeat, which returns immediately when the audit key is
        # a placeholder - and on dev it is, so this line used to claim
        # "heartbeat live" two lines above the heartbeat logging
        # "disabled (audit HMAC key not configured)". Two records, one true.
        log.info("fleet stack-tool heartbeat started (tenant=%s)", tenant)
    else:
        log.info("fleet stack-tool heartbeat not started (REDIS_URL not configured)")
    # The audit-rollup anchor janitor (COUNTY 9 D4).
    anchor_task = _start_anchor_janitor(kernel.store, kernel.anchorer)
    # The HITL expiry janitor (SEC-14) alongside the anchor janitor.
    expiry_task = _start_hitl_expiry_janitor(kernel.store)
    # The retention janitor (M11 / SEC-74 right-to-erasure), same shape again.
    retention_task = _start_retention_janitor(kernel.store, tenant, manifest)
    try:
        await pump.run_forever(tenant, interval=_POLL_SECONDS)
    finally:
        if anchor_task is not None:
            anchor_task.cancel()
        if expiry_task is not None:
            expiry_task.cancel()
        if stack_health_task is not None:
            stack_health_task.cancel()
        if retention_task is not None:
            retention_task.cancel()
        # Gather the cancelled tasks so none is destroyed while pending (an
        # ungathered anchor janitor also leaves an unsealed anchor tail).
        pending = [
            t
            for t in (anchor_task, expiry_task, stack_health_task, retention_task)
            if t is not None
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("fleet worker stopping")


if __name__ == "__main__":
    main()
