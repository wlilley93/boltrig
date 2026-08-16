"""The recovery-set verifier must prove completeness without modifying evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_recovery_set import verify_recovery_set
from scripts.require_local_docker import (
    effective_docker_endpoint,
    validate_local_docker_endpoint,
)


_TIMESTAMP = "20260812T120000Z"


def _write_set(root: Path, names: tuple[str, ...]) -> Path:
    lines = []
    for name in names:
        body = b"Salted__" + name.encode("ascii")
        artifact = root / name
        artifact.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        (root / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
        lines.append(f"{digest}  {name}")
    marker = root / f"boltrig-{_TIMESTAMP}.recovery.sha256"
    marker.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return marker


def _complete_names() -> tuple[str, ...]:
    return (
        f"boltrig-{_TIMESTAMP}.dump.enc",
        f"boltrig-hatchet-{_TIMESTAMP}.dump.enc",
        f"boltrig-state-{_TIMESTAMP}.tar.gz.enc",
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_set_verifier_accepts_complete_encrypted_evidence_read_only(
    tmp_path: Path,
) -> None:
    marker = _write_set(tmp_path, _complete_names())
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    assert verify_recovery_set(marker) == tuple(sorted(_complete_names()))

    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert after == before


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_set_verifier_accepts_custom_logical_database_names(
    tmp_path: Path,
) -> None:
    names = (
        f"boltrig-app_live-{_TIMESTAMP}.dump.enc",
        f"boltrig-durable-{_TIMESTAMP}.dump.enc",
        f"boltrig-state-{_TIMESTAMP}.tar.gz.enc",
    )
    marker = _write_set(tmp_path, names)

    assert verify_recovery_set(
        marker,
        required_databases=("app_live", "durable"),
    ) == tuple(sorted(names))


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_set_verifier_rejects_missing_database_or_stack_state(
    tmp_path: Path,
) -> None:
    marker = _write_set(tmp_path, (f"boltrig-{_TIMESTAMP}.dump.enc",))
    with pytest.raises(ValueError, match="omits required database.*hatchet"):
        verify_recovery_set(marker)

    with pytest.raises(ValueError, match="stack file state"):
        verify_recovery_set(marker, required_databases=("boltrig",))


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_set_verifier_rejects_tampering_and_inconsistent_sidecars(
    tmp_path: Path,
) -> None:
    marker = _write_set(tmp_path, _complete_names())
    artifact = tmp_path / f"boltrig-hatchet-{_TIMESTAMP}.dump.enc"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="does not match the recovery marker"):
        verify_recovery_set(marker)

    marker = _write_set(tmp_path, _complete_names())
    sidecar = tmp_path / f"boltrig-hatchet-{_TIMESTAMP}.dump.enc.sha256"
    sidecar.write_text(f"{'0' * 64}  {sidecar.name[:-7]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sidecar.*inconsistent"):
        verify_recovery_set(marker)


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_set_verifier_rejects_unencrypted_or_foreign_artifacts(
    tmp_path: Path,
) -> None:
    unencrypted = _write_set(
        tmp_path,
        (
            f"boltrig-{_TIMESTAMP}.dump",
            f"boltrig-hatchet-{_TIMESTAMP}.dump.enc",
            f"boltrig-state-{_TIMESTAMP}.tar.gz.enc",
        ),
    )
    with pytest.raises(ValueError, match="not encrypted"):
        verify_recovery_set(unencrypted)

    unexpected_database = _write_set(
        tmp_path,
        (*_complete_names(), f"boltrig-shadow-{_TIMESTAMP}.dump.enc"),
    )
    with pytest.raises(ValueError, match="unexpected database.*shadow"):
        verify_recovery_set(unexpected_database)

    duplicate_database = _write_set(
        tmp_path,
        (*_complete_names(), f"boltrig-boltrig-{_TIMESTAMP}.dump.enc"),
    )
    with pytest.raises(ValueError, match="repeats logical database boltrig"):
        verify_recovery_set(duplicate_database)

    foreign = _write_set(tmp_path, (*_complete_names(), "unrelated-secret.txt"))
    with pytest.raises(ValueError, match="not part of recovery timestamp"):
        verify_recovery_set(foreign)


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_recovery_rehearsal_refuses_remote_docker_and_ambient_database() -> None:
    for endpoint in (
        "unix:///var/run/docker.sock",
        "npipe:////./pipe/docker_engine",
        "tcp://127.0.0.1:2375",
        "tcp://[::1]:2375",
        "http://localhost:2375",
    ):
        assert validate_local_docker_endpoint(endpoint) == endpoint

    for endpoint in (
        "",
        "ssh://operator@production.example",
        "tcp://10.0.0.8:2375",
        "https://docker.example:2376",
    ):
        with pytest.raises(ValueError, match="requires a local Docker endpoint"):
            validate_local_docker_endpoint(endpoint)

    assert effective_docker_endpoint({"DOCKER_HOST": "unix:///tmp/docker.sock"}) == (
        "unix:///tmp/docker.sock"
    )
    with pytest.raises(ValueError, match="requires a local Docker endpoint"):
        effective_docker_endpoint({"DOCKER_HOST": "ssh://operator@production.example"})

    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
    target = makefile.split("recovery-rehearsal:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/require_local_docker.py" in target
    assert "env -u BOLTRIG_TEST_DATABASE_URL" in target
