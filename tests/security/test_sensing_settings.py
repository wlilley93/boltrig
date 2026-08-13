"""Camera and presence as first-class Boltrig services.

The property under test is the one docs/SPEC-character-bundle.md turns on: the
camera is the USER's, governed in one place, and a character asking for it while
it is off is REFUSED HONESTLY rather than crashed or quietly substituted.
"""

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import Principal, create_app
from boltrig.kernel.device_crypto import mint_scoped_token, token_digest
from boltrig.models import utcnow
from boltrig.models.devices import EnrolledDevice
from boltrig.kernel.sensing_policy import (
    parse_enrollment,
    parse_quiet_hours,
    parse_retention_hours,
    persist_enrollment,
    sensing_config,
    sensing_settings,
)
from boltrig.models import GrantSet, UserSetting
from tests.conftest import TENANT, _build_kernel

HEADERS = {
    "x-boltrig-tenant": TENANT,
    "x-boltrig-subject": "alice",
    "x-boltrig-tier": "human",
}

ENROLMENT = {
    "digest": "a" * 64,
    "threshold": 0.62,
    "count": 150,
    "far_measured": False,
}


@pytest.mark.security
def test_a_fresh_boltrig_watches_nothing_and_says_why() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    view = client.get("/v1/me/sensing", headers=HEADERS)
    assert view.status_code == 200
    body = view.json()
    assert body["camera"] == {
        "enabled": False,
        "source": "safe_default",
        "binding": None,
        "retention_hours": 24,
        "quiet_hours": {"start": 22, "end": 8},
    }
    assert body["presence"]["enabled"] is False
    assert body["enrollment"] == {
        "present": False,
        "count": 0,
        "threshold": None,
        "far_measured": False,
        "exportable": False,
    }

    # The refusal a character gets, drawn on the settings surface itself.
    refusals = {row["capability"]: row for row in body["capabilities"]}
    assert refusals["camera_observations"]["status"] == "refused"
    assert refusals["camera_observations"]["reason"] == "camera_disabled"
    assert refusals["camera_observations"]["remedy"] == "settings:sensing"


@pytest.mark.security
def test_a_character_asking_with_the_camera_off_gets_a_reason_not_a_crash() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    refused = client.get(
        "/v1/sensing/capability?capability=camera_observations", headers=HEADERS
    )
    # 409, not 403: the user is permitted and has chosen off.
    assert refused.status_code == 409
    assert refused.json()["status"] == "refused"
    assert refused.json()["reason"] == "camera_disabled"
    assert refused.json()["detail"]

    # A name this Boltrig does not offer, answered for what it is. NOT
    # "capability_not_declared", which the kernel is in no position to say: the
    # request carries the user's session and never names a character, so
    # declaration is not enforced here and this code must not imply it was.
    unknown = client.get(
        "/v1/sensing/capability?capability=microphone", headers=HEADERS
    )
    assert unknown.status_code == 409
    assert unknown.json()["reason"] == "capability_unknown"
    # And no remedy: there is no switch in Settings that grows a capability.
    assert "remedy" not in unknown.json()


@pytest.mark.security
def test_the_kernel_does_not_know_which_character_is_asking() -> None:
    """Pins a LIMITATION, deliberately, so it cannot be mistaken for a control.

    The spec's sentence is "a character DECLARES capability usage and is refused
    honestly"; only the second half happens in the kernel. The request is
    authenticated as the USER and names no bundle, so any character the caller
    claims to be is ignored and the answer turns on the user's settings alone --
    which means an undeclared character, with the camera on, is told ``granted``.
    Declaration is honoured by the Stage (``wantsSensing``) and that is a
    constraint on the Stage, not a boundary.

    Nothing here leaks imagery: the endpoint returns a decision and never a
    frame. What closing this would take is written out in the module docstring of
    ``boltrig.kernel.sensing_capability``.
    """
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    plain = client.get(
        "/v1/sensing/capability?capability=camera_observations", headers=HEADERS
    )
    claimed = client.get(
        "/v1/sensing/capability?capability=camera_observations"
        "&character=a-bundle-that-was-never-installed",
        headers=HEADERS,
    )
    assert plain.json() == claimed.json()
    # The user's switch decides, never the caller's claim about itself.
    assert plain.json()["reason"] == "camera_disabled"


@pytest.mark.security
def test_the_generic_settings_bag_cannot_turn_the_camera_on() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    bypass = client.put(
        "/v1/me/settings",
        headers=HEADERS,
        json={"key": "sensing.camera.enabled", "value": True},
    )
    assert bypass.status_code == 400
    assert bypass.json()["reason"] == "use the sensing endpoints"
    assert client.get("/v1/me/sensing", headers=HEADERS).json()["camera"]["enabled"] is False


@pytest.mark.security
def test_a_machine_credential_cannot_turn_the_users_camera_on() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())

    async def pat_principal(_request):
        return Principal(
            tenant_id=TENANT,
            subject="alice",
            grants=GrantSet.of(["*"]),
            role="org-admin",
            actor_tier="human",
            credential_kind="pat",
        )

    client = TestClient(create_app(kernel, principal_resolver=pat_principal))
    denied = client.put("/v1/me/sensing/camera", json={"enabled": True})
    assert denied.status_code == 403
    assert denied.json()["reason"] == "an interactive human session is required"


@pytest.mark.security
def test_an_unpublished_camera_is_refused_at_write_time_and_the_change_is_audited() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    unknown = client.put(
        "/v1/me/sensing/camera",
        headers=HEADERS,
        json={"enabled": True, "camera_id": f"camera_{'a' * 32}", "device_id": "dev-1"},
    )
    assert unknown.status_code == 409
    assert unknown.json()["reason"] == "camera_binding_unavailable"

    ok = client.put("/v1/me/sensing/camera", headers=HEADERS, json={"enabled": True})
    assert ok.status_code == 200
    assert ok.json()["camera"]["enabled"] is True
    assert ok.json()["camera"]["source"] == "user_override"

    # On but unbound is a DIFFERENT refusal from off, and says so.
    assert client.get(
        "/v1/sensing/capability?capability=camera_observations", headers=HEADERS
    ).json()["reason"] == "camera_not_bound"

    events = asyncio.run(kernel.store.audit_query(TENANT))
    assert any(event.verb == "sensing.camera.update" for event in events)


@pytest.mark.security
def test_presence_cannot_be_turned_on_without_a_room_calibrated_threshold() -> None:
    kernel, _adapter = asyncio.run(_build_kernel())
    client = TestClient(create_app(kernel))

    blocked = client.put("/v1/me/sensing/presence", headers=HEADERS, json={"enabled": True})
    assert blocked.status_code == 409
    assert blocked.json()["reason"] == "presence_not_enrolled"
    assert client.get("/v1/me/sensing", headers=HEADERS).json()["presence"]["blocked_by"] == (
        "presence_not_enrolled"
    )

    # Published by the host agent, not typed into a browser: the enrolment comes
    # from a tool on the machine with the camera.
    asyncio.run(persist_enrollment(kernel.store, TENANT, "alice", parse_enrollment(ENROLMENT)))
    assert client.get("/v1/me/sensing", headers=HEADERS).json()["enrollment"] == {
        "present": True,
        "count": 150,
        "threshold": 0.62,
        "far_measured": False,
        "exportable": False,
    }
    assert client.put(
        "/v1/me/sensing/presence", headers=HEADERS, json={"enabled": True}
    ).status_code == 200

    # Forgetting the face turns presence off in the same act: leaving it on would
    # promise an answer the daemon cannot give.
    forgotten = client.delete("/v1/me/sensing/enrollment", headers=HEADERS)
    assert forgotten.status_code == 200
    assert forgotten.json()["enrollment"]["present"] is False
    assert forgotten.json()["presence"]["enabled"] is False


@pytest.mark.security
def test_an_uncalibrated_enrolment_is_never_accepted() -> None:
    """A guessed threshold is a false-accept rate nobody measured, told as fact."""
    for body in (
        {"digest": "a" * 64, "count": 150},
        {"digest": "a" * 64, "threshold": 0, "count": 150},
        {"digest": "a" * 64, "threshold": 1.5},
        {"digest": "not-a-digest", "threshold": 0.62},
    ):
        assert parse_enrollment(body) is None


@pytest.mark.security
async def test_every_parse_fails_toward_off() -> None:
    kernel, _adapter = await _build_kernel()
    for key, value in (
        ("sensing.camera.enabled", "yes"),
        ("sensing.camera.binding", {"camera_id": "camera_x"}),
        ("sensing.camera.retention_hours", 100_000),
        ("sensing.camera.quiet_hours", "22-8"),
        ("sensing.presence.enabled", 1),
        ("sensing.enrollment", {"digest": "a" * 64, "threshold": 4}),
    ):
        await kernel.store.upsert_user_setting(UserSetting(
            tenant_id=TENANT, user_id="alice", key=key, value=value,
        ))

    settings = await sensing_settings(kernel.store, TENANT, "alice")
    assert settings["camera"]["enabled"] is False
    assert settings["camera"]["binding"] is None
    assert settings["camera"]["retention_hours"] == 24
    assert settings["camera"]["quiet_hours"] == {"start": 22, "end": 8}
    assert settings["presence"]["enabled"] is False
    assert settings["enrollment"] is None

    # True is an int in Python; one hour of retention must not be reachable that way.
    assert parse_retention_hours(True) == 24
    assert parse_quiet_hours({"start": 99, "end": 3}) == {"start": 22, "end": 3}
    assert parse_enrollment({"digest": "a" * 64, "threshold": 0.5})["count"] == 0


@pytest.mark.security
async def test_the_host_config_never_reports_presence_it_cannot_deliver() -> None:
    kernel, _adapter = await _build_kernel()
    await kernel.store.upsert_user_setting(UserSetting(
        tenant_id=TENANT, user_id="alice", key="sensing.presence.enabled", value=True,
    ))
    config = sensing_config(await sensing_settings(kernel.store, TENANT, "alice"))
    assert config["presence"]["enabled"] is False
    assert config["presence"]["threshold"] is None
    # The capture thresholds the daemons used to hold as constants now arrive
    # from the kernel the user controls.
    assert config["thresholds"]["dark_mean"] == 12.0
    assert config["thresholds"]["interval"] == 30

    await persist_enrollment(kernel.store, TENANT, "alice", parse_enrollment(ENROLMENT))
    config = sensing_config(await sensing_settings(kernel.store, TENANT, "alice"))
    assert config["presence"] == {
        "enabled": True,
        "enrollment_digest": "a" * 64,
        "threshold": 0.62,
    }


@pytest.mark.security
def test_the_host_agent_publishes_the_enrolment_and_reads_its_own_policy() -> None:
    """The daemons are configured by the KERNEL, over the device transport.

    This is the seam that makes the camera Boltrig's: camerad, capture and
    presence stop reading constants out of a companion's repo and read consent
    the user set instead. Nothing new listens; it is the transport the camera
    bindings already use.
    """
    kernel, _adapter = asyncio.run(_build_kernel())
    kernel.store._devices = {}
    token = mint_scoped_token("device_session", TENANT, "device_camera")
    kernel.store._devices[(TENANT, "device_camera")] = EnrolledDevice(
        id="device_camera",
        tenant_id=TENANT,
        owner_id="alice",
        label="Worker",
        public_key="public",
        public_key_fingerprint="f" * 64,
        lease_verify_key_id="k",
        session_token_hash=token_digest(token),
        session_expires_at=utcnow() + timedelta(hours=1),
    )
    client = TestClient(create_app(kernel))
    agent = {"authorization": f"Bearer {token}"}

    config = client.get("/v1/device-agent/device_camera/sensing-config", headers=agent)
    assert config.status_code == 200
    assert config.json()["camera"]["enabled"] is False
    assert config.json()["thresholds"]["gesture_pause_s"] == 1800

    uncalibrated = client.post(
        "/v1/device-agent/device_camera/sensing-enrollment",
        headers=agent,
        json={"digest": "a" * 64},
    )
    assert uncalibrated.status_code == 400
    assert uncalibrated.json()["reason"] == (
        "sensing_enrollment_requires_a_calibrated_threshold"
    )

    published = client.post(
        "/v1/device-agent/device_camera/sensing-enrollment",
        headers=agent,
        json=ENROLMENT,
    )
    assert published.status_code == 200
    assert published.json()["enrollment"]["exportable"] is False
    assert client.get("/v1/me/sensing", headers=HEADERS).json()["enrollment"]["count"] == 150

    # An unauthenticated agent gets nothing at all, config included.
    assert client.get("/v1/device-agent/device_camera/sensing-config").status_code == 401
