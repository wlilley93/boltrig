"""Release image environment validation regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_release_compose import validate_release_compose
from scripts.validate_release_images import (
    REQUIRED_IMAGE_VARIABLES,
    validate_release_image_environment,
)


def _write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def _valid_environment() -> dict[str, str]:
    return {
        key: f"registry.invalid/boltrig/{index}@sha256:{str(index) * 64}"
        for index, key in enumerate(REQUIRED_IMAGE_VARIABLES, 1)
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_image_environment_requires_every_first_party_digest(tmp_path: Path) -> None:
    path = tmp_path / "boltrig-images.env"
    values = _valid_environment()
    _write_environment(path, values)
    assert validate_release_image_environment(path) == values

    missing = dict(values)
    missing.pop("BOLTRIG_BACKUP_IMAGE")
    _write_environment(path, missing)
    with pytest.raises(ValueError, match="missing release image variables"):
        validate_release_image_environment(path)

    mutable = dict(values)
    mutable["BOLTRIG_WORKER_UI_IMAGE"] = "ghcr.io/example/boltrig-worker-ui:v1.2.3"
    _write_environment(path, mutable)
    with pytest.raises(ValueError, match="immutable image@sha256"):
        validate_release_image_environment(path)

    unexpected = {**values, "UNRELATED_SECRET": "must-not-be-accepted"}
    _write_environment(path, unexpected)
    with pytest.raises(ValueError, match="unexpected release image variables"):
        validate_release_image_environment(path)


def _compose_document() -> dict:
    services = {
        name: {"image": f"registry.invalid/boltrig/{name}@sha256:{'1' * 64}"}
        for name in ("kernel", "fleet-worker", "hatchet-worker", "worker-ui", "backup")
    }
    services["hatchet-worker"]["image"] = services["fleet-worker"]["image"]
    services["hatchet-worker"]["environment"] = {
        "HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED": "true"
    }
    services["hatchet-worker"]["healthcheck"] = {
        "test": [
            "CMD-SHELL",
            "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')\" || exit 1",
        ]
    }
    for name in ("kernel", "fleet-worker"):
        services[name]["environment"] = {
            "BOLTRIG_PRODUCTION": "1",
            "BOLTRIG_RELEASE_MODE": "core",
            "REDIS_URL": "redis://redis:6379/0",
        }
    services["hatchet-worker"]["environment"]["BOLTRIG_RELEASE_MODE"] = "core"
    services["backup"]["volumes"] = [{"target": "/backups"}]
    services["local-model"] = {"ports": [{"host_ip": "127.0.0.1"}]}
    return {"services": services}


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_compose_validator_rejects_builds_tags_and_source_mounts() -> None:
    document = _compose_document()
    validate_release_compose(document, secure=False)

    document["services"]["kernel"]["build"] = {"context": "."}
    with pytest.raises(ValueError, match="still has a build"):
        validate_release_compose(document, secure=False)
    document["services"]["kernel"].pop("build")

    document["services"]["worker-ui"]["image"] = "registry.invalid/boltrig/worker-ui:v1.2.3"
    with pytest.raises(ValueError, match="not pinned by image digest"):
        validate_release_compose(document, secure=False)
    document["services"]["worker-ui"]["image"] = f"registry.invalid/boltrig/worker-ui@sha256:{'2' * 64}"

    document["services"]["backup"]["volumes"].append(
        {"target": "/usr/local/bin/backup.sh"}
    )
    with pytest.raises(ValueError, match="replaces signed code"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    with pytest.raises(ValueError, match="publishes the sensitive local-model"):
        validate_release_compose(document, secure=True)
    document["services"]["local-model"]["ports"] = []
    validate_release_compose(document, secure=True)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_requires_a_pinned_worker_image() -> None:
    document = _compose_document()
    validate_release_compose(document, secure=False)

    document["services"].pop("worker-ui")
    with pytest.raises(ValueError, match="no worker-ui service"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["worker-ui"]["image"] = "registry.invalid/worker-ui:latest"
    with pytest.raises(ValueError, match="not pinned by image digest"):
        validate_release_compose(document, secure=False)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_requires_hatchet_worker_to_share_the_pinned_fleet_image() -> None:
    document = _compose_document()
    validate_release_compose(document, secure=False)

    document["services"].pop("hatchet-worker")
    with pytest.raises(ValueError, match="no hatchet-worker service"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["hatchet-worker"]["build"] = {"context": "."}
    with pytest.raises(ValueError, match="hatchet-worker still has a build"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["hatchet-worker"]["image"] = (
        f"registry.invalid/boltrig/other-fleet@sha256:{'2' * 64}"
    )
    with pytest.raises(ValueError, match="does not use the fleet-worker image digest"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["hatchet-worker"].pop("healthcheck")
    with pytest.raises(ValueError, match="no listener-heartbeat healthcheck"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["hatchet-worker"]["environment"][
        "HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED"
    ] = "false"
    with pytest.raises(ValueError, match="health server is not enabled"):
        validate_release_compose(document, secure=False)


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_release_compose_binds_one_exact_mode_to_every_codex_capable_process() -> None:
    document = _compose_document()
    validate_release_compose(document, secure=False)

    document["services"]["kernel"]["environment"].pop("BOLTRIG_RELEASE_MODE")
    with pytest.raises(ValueError, match="kernel has no exact BOLTRIG_RELEASE_MODE"):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["fleet-worker"]["environment"]["BOLTRIG_RELEASE_MODE"] = (
        "CORE"
    )
    with pytest.raises(
        ValueError, match="fleet-worker has no exact BOLTRIG_RELEASE_MODE"
    ):
        validate_release_compose(document, secure=False)

    document = _compose_document()
    document["services"]["hatchet-worker"]["environment"][
        "BOLTRIG_RELEASE_MODE"
    ] = "full"
    with pytest.raises(ValueError, match="release services disagree"):
        validate_release_compose(document, secure=False)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.parametrize(
    ("service_name", "service"),
    [
        (
            "channel-gateway",
            {
                "profiles": ["channels"],
                "build": {"context": "/checkout/services/channel_gateway"},
                "image": "boltrig/channel-gateway:0.1.0",
            },
        ),
        (
            "whatsapp-bridge",
            {
                "profiles": ["channels"],
                "build": {
                    "context": "/checkout/services/channel_gateway/whatsapp_bridge"
                },
                "image": "boltrig/channel-gateway-whatsapp-bridge:1.0.0",
            },
        ),
        (
            "renamed-channel-service",
            {
                "profiles": ["channels"],
                "image": (
                    "registry.invalid/boltrig/renamed-channel-service@sha256:"
                    f"{'3' * 64}"
                ),
            },
        ),
    ],
)
def test_release_rejects_rendered_channels_profile_until_admitted(
    secure: bool,
    service_name: str,
    service: dict,
) -> None:
    # Model the JSON emitted by `docker compose config`, including the resolved
    # local build paths and mutable tags present when --profile channels is set.
    rendered = _compose_document()
    rendered["services"][service_name] = service
    if secure:
        rendered["services"]["local-model"]["ports"] = []

    with pytest.raises(ValueError, match="channels posture is not admitted"):
        validate_release_compose(rendered, secure=secure)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
@pytest.mark.parametrize("service_name", ["channel-gateway", "whatsapp-bridge"])
def test_release_rejects_channel_service_even_if_profile_metadata_is_removed(
    service_name: str,
) -> None:
    rendered = _compose_document()
    rendered["services"][service_name] = {
        "image": f"registry.invalid/boltrig/{service_name}@sha256:{'4' * 64}"
    }
    rendered["services"]["local-model"]["ports"] = []

    with pytest.raises(ValueError, match="channels posture is not admitted"):
        validate_release_compose(rendered, secure=True)
