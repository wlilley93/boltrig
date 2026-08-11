from __future__ import annotations

import json
from pathlib import Path

import pytest

from boltrig.camera import (
    CameraDiscoveryError,
    CameraKnowledgeCache,
    CameraProfileRegistry,
    CameraDiscoveryService,
    CameraObservation,
    CapabilityState,
    descriptor_fingerprint,
    discover_camera,
    load_profile,
)
from boltrig.camera.profiles import CameraProfileError


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "cameras" / "emeet-pixy-00c0" / "probe.json"
VIDEO_ONLY_FIXTURE = ROOT / "tests" / "fixtures" / "cameras" / "uvc-video-only" / "probe.json"
PROFILE = ROOT / "camera-profiles" / "emeet-pixy" / "profile.toml"


def _pixy() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _video_only() -> dict:
    return json.loads(VIDEO_ONLY_FIXTURE.read_text(encoding="utf-8"))


def _profile_registry(*, trusted: bool = True) -> CameraProfileRegistry:
    profile = load_profile(PROFILE, trusted_ids={"emeet.pixy.v1"} if trusted else ())
    return CameraProfileRegistry([profile])


def test_pixy_fixture_projects_standard_and_proven_capabilities() -> None:
    discovery = discover_camera(_pixy(), profiles=_profile_registry())
    output = discovery.as_dict()

    assert output["v"] == 1
    assert output["camera_id"].startswith("camera_")
    assert output["profile"] == {
        "id": "emeet.pixy.v1",
        "trusted": True,
        "quirks": {
            "pan_tilt": {"ignore_get_len": True, "fixed_length": 8},
            "privacy": {"descriptor_invalid": True, "disable_write": True},
        },
    }
    assert output["capabilities"]["video"]["state"] == "proven"
    assert output["capabilities"]["snapshot"]["state"] == "proven"
    assert output["capabilities"]["pan"]["state"] == "proven"
    assert output["capabilities"]["tilt"]["state"] == "proven"
    assert output["capabilities"]["pan"]["limits"] == {
        "min": -540000,
        "max": 540000,
        "step": 3600,
    }
    assert output["capabilities"]["zoom"]["state"] == "readable"
    assert output["capabilities"]["focus"]["state"] == "readable"
    assert output["capabilities"]["privacy"]["state"] == "invalid_descriptor"
    assert output["capabilities"]["tracking"]["state"] == "unknown"
    assert output["transport"]["video"] == "uvc"
    assert output["transport"]["audio"] == "uac"
    assert output["transport"]["controls"] == ["uvc", "hid"]
    assert "camera.ptz.get" in output["allowed_verbs"]
    assert "camera.ptz.set" in output["allowed_verbs"]
    assert "camera.privacy.enable" not in output["allowed_verbs"]


def test_profile_match_is_not_proof_and_vendor_metadata_stays_inactive() -> None:
    discovery = discover_camera(_pixy(), profiles=_profile_registry(trusted=False))

    assert discovery.profile_id == "emeet.pixy.v1"
    assert discovery.profile_trusted is False
    assert "extras" not in discovery.driver
    assert discovery.capabilities["pan"].state is CapabilityState.PROVEN
    assert discovery.capabilities["tracking"].implementation is None
    assert "matching_profile_untrusted_vendor_metadata_inactive" in discovery.warnings


def test_descriptor_fingerprint_excludes_mutable_values() -> None:
    original = _pixy()
    changed = _pixy()
    changed["usb"]["video"]["controls"]["pan_tilt_absolute"]["current"] = [3600, 0]
    changed["usb"]["video"]["controls"]["focus_absolute"]["current"] = 12

    assert descriptor_fingerprint(original) == descriptor_fingerprint(changed)


def test_unknown_hid_camera_never_gains_mutating_vendor_verbs() -> None:
    probe = _pixy()
    probe["usb"]["video"]["controls"] = {}
    probe["physical_tests"] = {}
    discovery = discover_camera(probe)

    assert discovery.capabilities["tracking"].state is CapabilityState.UNKNOWN
    assert discovery.capabilities["pan"].state is CapabilityState.UNSUPPORTED
    assert "camera.ptz.set" not in discovery.allowed_verbs()
    assert all("hid" not in verb for verb in discovery.allowed_verbs())


def test_video_only_camera_gets_no_ptz_and_snapshot_waits_for_level_two() -> None:
    discovery = discover_camera(_video_only())

    assert discovery.capabilities["video"].state is CapabilityState.ADVERTISED
    assert discovery.capabilities["snapshot"].state is CapabilityState.ADVERTISED
    assert discovery.capabilities["audio"].state is CapabilityState.UNSUPPORTED
    assert discovery.capabilities["pan"].state is CapabilityState.UNSUPPORTED
    assert discovery.allowed_verbs() == [
        "camera.device.list",
        "camera.device.status",
        "camera.device.capabilities",
    ]


def test_not_present_probe_fails_closed() -> None:
    probe = _pixy()
    probe["device"]["present"] = False
    with pytest.raises(CameraDiscoveryError, match="camera_not_present"):
        discover_camera(probe)


def test_local_cache_uses_opaque_binding_and_rebinds_on_fingerprint_change(tmp_path: Path) -> None:
    cache = CameraKnowledgeCache(tmp_path / "camera-cache.json")
    discovery = discover_camera(_pixy(), profiles=_profile_registry())
    first = cache.bind(
        hardware_key="macos-media-identity:one",
        usb_vid=discovery.usb_vid,
        usb_pid=discovery.usb_pid,
        fingerprint=discovery.descriptor_fingerprint,
    )
    second = cache.bind(
        hardware_key="macos-media-identity:one",
        usb_vid=discovery.usb_vid,
        usb_pid=discovery.usb_pid,
        fingerprint=discovery.descriptor_fingerprint,
    )
    changed = cache.bind(
        hardware_key="macos-media-identity:one",
        usb_vid=discovery.usb_vid,
        usb_pid=discovery.usb_pid,
        fingerprint="a" * 64,
    )

    assert first.startswith("camera_") and len(first) == 39
    assert second == first
    assert changed.startswith("camera_") and changed != first
    raw = (tmp_path / "camera-cache.json").read_text(encoding="utf-8")
    assert "macos-media-identity" not in raw

    cache.record(discovery)
    assert cache.get(discovery.camera_id)["capabilities"]["pan"]["state"] == "proven"


def test_cache_never_persists_probe_or_serial_fields(tmp_path: Path) -> None:
    probe = _pixy()
    probe["device"]["serial_number"] = "private-serial"
    discovery = discover_camera(probe)
    cache = CameraKnowledgeCache(tmp_path / "camera-cache.json")
    cache.record(discovery)
    raw = (tmp_path / "camera-cache.json").read_text(encoding="utf-8")

    assert "private-serial" not in raw
    assert "physical_tests" not in raw
    assert "raw_hid" not in raw


def test_profile_loader_rejects_executable_metadata() -> None:
    with pytest.raises(CameraProfileError, match="executable_profile_metadata_forbidden"):
        from boltrig.camera.profiles import CameraProfile

        CameraProfile.from_mapping(
            {
                "id": "unsafe",
                "match": {"vid": 1, "pid": 2},
                "vendor": {"command": "sh -c unsafe"},
            }
        )


def test_network_and_vendor_interfaces_are_reported_but_not_opened() -> None:
    probe = _pixy()
    probe["usb"]["interfaces"].append(
        {"number": 5, "class": "vendor_specific", "subclass": 0, "protocol": 0}
    )
    probe["usb"]["network_interface"] = True
    discovery = discover_camera(probe)

    assert discovery.interfaces["network"] is True
    assert discovery.interfaces["vendor_specific"] is True
    assert "network" in discovery.interfaces["classes"] or "vendor_specific" in discovery.interfaces["classes"]
    assert "camera.device.list" in discovery.allowed_verbs()
    assert all("network" not in verb and "vendor" not in verb for verb in discovery.allowed_verbs())


@pytest.mark.asyncio
async def test_discovery_service_binds_and_caches_read_only_observations(tmp_path: Path) -> None:
    class Platform:
        async def enumerate_cameras(self):
            return [CameraObservation("private-os-media-id", _pixy())]

    cache = CameraKnowledgeCache(tmp_path / "camera-cache.json")
    service = CameraDiscoveryService(
        Platform(), cache, profiles=_profile_registry()
    )
    discoveries = await service.discover()

    assert len(discoveries) == 1
    assert discoveries[0].camera_id.startswith("camera_")
    assert cache.get(discoveries[0].camera_id)["profile"]["id"] == "emeet.pixy.v1"
    assert "private-os-media-id" not in (tmp_path / "camera-cache.json").read_text()
