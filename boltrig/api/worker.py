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
from boltrig.fleet import build_org, build_spawner, register_workers

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
    await pump.run_forever(tenant, interval=_POLL_SECONDS)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("fleet worker stopping")


if __name__ == "__main__":
    main()
