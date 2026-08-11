"""Composition-root registration for governed native-camera leases."""

from __future__ import annotations

import logging

from boltrig.adapters.builtin.camera_leases import build_camera_lease_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.device_crypto import DeviceLeaseSigner

log = logging.getLogger("boltrig.bootstrap")


async def register_camera_actions(kernel: Kernel, tenant_id: str) -> None:
    signer = DeviceLeaseSigner.from_environment()
    if signer is None:
        log.info("camera lease verbs disabled (lease signing key unavailable)")
        return
    await kernel.register_adapter(tenant_id, build_camera_lease_adapter(kernel.store, signer))
    log.info("camera lease verbs registered (root-free signed UVC transport)")


__all__ = ["register_camera_actions"]
