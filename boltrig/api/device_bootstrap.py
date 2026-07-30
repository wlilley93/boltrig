"""Composition-root registration for governed desktop-device actions."""

from __future__ import annotations

import logging

from boltrig.adapters.builtin.device import build_device_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.device_crypto import DeviceLeaseSigner

log = logging.getLogger("boltrig.bootstrap")


async def register_device_actions(kernel: Kernel, tenant_id: str) -> None:
    """Publish device actions only when this process can sign their leases."""
    signer = DeviceLeaseSigner.from_environment()
    if signer is None:
        log.info("device action verbs disabled (lease signing key unavailable)")
        return
    await kernel.register_adapter(
        tenant_id, build_device_adapter(kernel.store, signer)
    )
    log.info("device action verbs registered (exact signed lease backend)")


__all__ = ["register_device_actions"]
