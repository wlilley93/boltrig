"""The fleet worker process. Run with: python -m boltrig.api.worker

Registers durable workers (Hatchet in production, a local executor as the
offline dev fallback, P6) and runs the permanent tier: the Chief of Staff polls
the work item store and routes pending items to department heads (US-FLT-01).
"""

from __future__ import annotations

import asyncio
import logging

from boltrig.fleet import register_workers

from .bootstrap import build_kernel_async

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("boltrig.worker")

_POLL_SECONDS = 5


async def _run() -> None:
    kernel = await build_kernel_async()  # async build (no nested asyncio.run)
    executor = register_workers(kernel)
    # Honest executor selection (US-EXE-05): the boot record states durability.
    log.info(
        "fleet worker started (%s, durable=%s)",
        type(executor).__name__, executor.durable,
    )
    # The permanent tier is long-lived. With Hatchet this loop is replaced by the
    # engine's durable scheduling; the local fallback simply stays alive so the
    # process is a valid compose service and can be extended to poll queues.
    while True:
        await asyncio.sleep(_POLL_SECONDS)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("fleet worker stopping")


if __name__ == "__main__":
    main()
