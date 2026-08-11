from __future__ import annotations

import pytest

from boltrig.adapters.builtin.camera import CAMERA_VERBS, CameraDiscoveryAdapter
from boltrig.models import GrantSet, InvocationContext


class Provider:
    async def list_cameras(self):
        return [{"camera_id": "camera_" + "a" * 32, "capabilities": {}}]

    async def camera_status(self, camera_id):
        return {"camera_id": camera_id, "connected": True}

    async def camera_capabilities(self, camera_id):
        return {"camera_id": camera_id, "capabilities": {"snapshot": {"state": "proven"}}}

    async def snapshot(self, camera_id):
        return {"camera_id": camera_id, "status": "proven"}


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id="tenant",
        grants=GrantSet.of(["camera.*"]),
        actor="operator",
        actor_tier="human",
    )


@pytest.mark.asyncio
async def test_camera_adapter_exposes_read_only_v1_verbs_and_no_raw_transport() -> None:
    adapter = CameraDiscoveryAdapter(Provider())
    specs = {spec.verb_id: spec for spec in adapter.describe()}

    assert tuple(specs) == CAMERA_VERBS
    assert set(CAMERA_VERBS) == {
        "camera.device.list",
        "camera.device.status",
        "camera.device.capabilities",
        "camera.snapshot",
    }
    assert specs["camera.snapshot"].consequence == "high"
    assert all(
        spec.consequence == "low"
        for verb, spec in specs.items()
        if verb != "camera.snapshot"
    )
    assert all("hid" not in spec.verb_id for spec in specs.values())
    assert all("usb" not in spec.verb_id for spec in specs.values())

    listed = await adapter.execute("camera.device.list", {}, None, _context())
    assert listed.ok and len(listed.output["cameras"]) == 1
    status = await adapter.execute(
        "camera.device.status", {"camera_id": "camera_" + "a" * 32}, None, _context()
    )
    assert status.ok and status.output["connected"] is True


@pytest.mark.asyncio
async def test_camera_adapter_does_not_fake_missing_device() -> None:
    class Empty(Provider):
        async def camera_status(self, camera_id):
            return None

    result = await CameraDiscoveryAdapter(Empty()).execute(
        "camera.device.status", {"camera_id": "camera_" + "a" * 32}, None, _context()
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.message == "camera_not_found"


@pytest.mark.asyncio
async def test_camera_adapter_does_not_expose_unproven_snapshot() -> None:
    class Unproven(Provider):
        async def camera_capabilities(self, camera_id):
            return {"camera_id": camera_id, "capabilities": {"snapshot": {"state": "advertised"}}}

    result = await CameraDiscoveryAdapter(Unproven()).execute(
        "camera.snapshot", {"camera_id": "camera_" + "a" * 32}, None, _context()
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.message == "camera_snapshot_unproven"
