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
def test_release_image_environment_requires_exactly_five_digest_refs(tmp_path: Path) -> None:
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
    mutable["BOLTRIG_UI_IMAGE"] = "ghcr.io/example/boltrig-ui:v1.2.3"
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
        for name in ("kernel", "fleet-worker", "ui", "pi-sidecar", "backup")
    }
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

    document["services"]["ui"]["image"] = "registry.invalid/boltrig/ui:v1.2.3"
    with pytest.raises(ValueError, match="not pinned by image digest"):
        validate_release_compose(document, secure=False)
    document["services"]["ui"]["image"] = f"registry.invalid/boltrig/ui@sha256:{'2' * 64}"

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
