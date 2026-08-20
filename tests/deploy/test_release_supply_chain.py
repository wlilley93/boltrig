"""Offline tests for fail-closed production release evidence verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_release_supply_chain import (
    CERTIFICATE_ISSUER,
    EXPECTED_REPOSITORY,
    EXPECTED_SIGNER_WORKFLOW,
    PROVENANCE_TYPE,
    resolve_release_identity,
    verify_release_supply_chain,
)
import scripts.verify_release_supply_chain as release_verifier

_TAG = "v1.2.3"
_COMMIT = "a" * 40


def _environment(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                f"BOLTRIG_KERNEL_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-kernel@sha256:{'1' * 64}",
                f"BOLTRIG_FLEET_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-fleet@sha256:{'2' * 64}",
                f"BOLTRIG_UI_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-ui@sha256:{'3' * 64}",
                f"BOLTRIG_BACKUP_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-backup@sha256:{'4' * 64}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_supply_chain_requires_all_three_evidence_classes_offline(
    tmp_path: Path,
) -> None:
    commands: list[tuple[str, ...]] = []
    verify_release_supply_chain(
        _environment(tmp_path / "boltrig-images.env"),
        release_tag=_TAG,
        release_commit=_COMMIT,
        command_runner=lambda command: commands.append(tuple(command)),
    )

    assert len(commands) == 12
    identity = (
        f"https://github.com/{EXPECTED_SIGNER_WORKFLOW}@refs/tags/{_TAG}"
    )
    for index in range(0, len(commands), 3):
        signature, sbom, provenance = commands[index : index + 3]
        assert signature[:2] == ("cosign", "verify")
        assert "--certificate-identity" in signature
        assert identity in signature
        assert CERTIFICATE_ISSUER in signature
        assert signature[-1].startswith(f"ghcr.io/{EXPECTED_REPOSITORY}-")

        assert sbom[:3] == ("cosign", "verify-attestation", "--type")
        assert "cyclonedx" in sbom
        assert identity in sbom

        assert provenance[:3] == ("gh", "attestation", "verify")
        assert "--bundle-from-oci" in provenance
        assert EXPECTED_REPOSITORY in provenance
        assert EXPECTED_SIGNER_WORKFLOW in provenance
        assert _COMMIT in provenance
        assert f"refs/tags/{_TAG}" in provenance
        assert PROVENANCE_TYPE in provenance


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_supply_chain_rejects_wrong_registry_or_failed_evidence(
    tmp_path: Path,
) -> None:
    path = _environment(tmp_path / "boltrig-images.env")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"ghcr.io/{EXPECTED_REPOSITORY}-kernel", "registry.invalid/other/kernel"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not name"):
        verify_release_supply_chain(
            path,
            release_tag=_TAG,
            release_commit=_COMMIT,
            command_runner=lambda _command: None,
        )

    calls = 0

    def reject_second(_command: tuple[str, ...]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("invalid evidence")

    with pytest.raises(ValueError, match="CycloneDX SBOM attestation verification failed"):
        verify_release_supply_chain(
            _environment(path),
            release_tag=_TAG,
            release_commit=_COMMIT,
            command_runner=reject_second,
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
@pytest.mark.parametrize(
    ("tag", "commit"),
    (("latest", _COMMIT), (_TAG, "not-a-commit")),
)
def test_release_supply_chain_rejects_unbound_release_identity(
    tmp_path: Path, tag: str, commit: str
) -> None:
    with pytest.raises(ValueError, match="release (tag|commit)"):
        verify_release_supply_chain(
            _environment(tmp_path / "boltrig-images.env"),
            release_tag=tag,
            release_commit=commit,
            command_runner=lambda _command: None,
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_identity_requires_an_unchanged_tracked_tag_checkout(monkeypatch) -> None:
    responses = {
        ("status", "--porcelain", "--untracked-files=no"): " M scripts/backup.sh",
    }
    monkeypatch.setattr(
        release_verifier,
        "_git",
        lambda *args: responses[args],
    )

    with pytest.raises(ValueError, match="modified, staged, or deleted tracked files"):
        resolve_release_identity(_TAG)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_identity_allows_untracked_operator_inputs_but_binds_head_tag(
    monkeypatch,
) -> None:
    responses = {
        ("status", "--porcelain", "--untracked-files=no"): "",
        ("rev-parse", "--verify", "HEAD"): _COMMIT,
        ("tag", "--points-at", "HEAD", "--list", "v*"): _TAG,
    }
    monkeypatch.setattr(
        release_verifier,
        "_git",
        lambda *args: responses[args],
    )

    assert resolve_release_identity() == (_TAG, _COMMIT)
