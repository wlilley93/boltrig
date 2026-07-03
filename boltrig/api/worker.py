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

from boltrig.config import load_manifest
from boltrig.fleet import (
    anchor_interval_from_env,
    build_org,
    build_spawner,
    register_workers,
    run_anchor_forever,
)

from .bootstrap import _DEFAULT_TENANT, _find_manifest, build_kernel_async

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("boltrig.worker")

_POLL_SECONDS = 5.0


async def _run() -> None:
    kernel = await build_kernel_async()  # async build (no nested asyncio.run)
    executor = register_workers(kernel)
    # Honest executor selection (US-EXE-05): the boot record states durability.
    log.info(
        "fleet worker started (%s, durable=%s)",
        type(executor).__name__, executor.durable,
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
    pump = build_org(kernel, build_spawner(kernel), manifest, executor=executor)
    log.info(
        "delegation pump live (tenant=%s, departments=%s)",
        tenant, sorted(pump.heads),
    )
    # The periodic audit-rollup anchor janitor (COUNTY 9 D4): on an interval it
    # seals every tenant's un-anchored audit-chain tail so a verifier can prove a
    # segment was not rewritten. A worker-side loop (the codebase has no native
    # Hatchet cron seam), independent of the durable engine so it runs the same on
    # Hatchet or the local fallback - it never crashes boot (P9). Off when the
    # interval knob (BOLTRIG_AUDIT_ANCHOR_INTERVAL) is <= 0; conservative daily
    # default. Held in a name so the task is not garbage-collected mid-flight.
    anchor_interval = anchor_interval_from_env()
    anchor_task: asyncio.Task | None = None
    if anchor_interval > 0:
        anchor_task = asyncio.create_task(
            run_anchor_forever(kernel.store, kernel.anchorer, interval=anchor_interval)
        )
        log.info("audit-anchor janitor live (interval=%ss)", anchor_interval)
    else:
        log.info("audit-anchor janitor disabled (interval<=0)")
    try:
        await pump.run_forever(tenant, interval=_POLL_SECONDS)
    finally:
        if anchor_task is not None:
            anchor_task.cancel()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("fleet worker stopping")


if __name__ == "__main__":
    main()
