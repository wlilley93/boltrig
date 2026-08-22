"""Verify that release images came from Boltrig's protected release workflow."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from scripts.validate_release_images import validate_release_image_environment

EXPECTED_REPOSITORY = "wlilley93/boltrig"
EXPECTED_SIGNER_WORKFLOW = f"{EXPECTED_REPOSITORY}/.github/workflows/release.yml"
CERTIFICATE_ISSUER = "https://token.actions.githubusercontent.com"
PROVENANCE_TYPE = "https://slsa.dev/provenance/v1"

_IMAGE_SUFFIXES = {
    "BOLTRIG_KERNEL_IMAGE": "kernel",
    "BOLTRIG_FLEET_IMAGE": "fleet",
    "BOLTRIG_UI_IMAGE": "ui",
    "BOLTRIG_BACKUP_IMAGE": "backup",
}
_RELEASE_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

CommandRunner = Callable[[Sequence[str]], None]


def verify_release_supply_chain(
    image_environment: Path,
    *,
    release_tag: str,
    release_commit: str,
    command_runner: CommandRunner,
    repository: str = EXPECTED_REPOSITORY,
    signer_workflow: str = EXPECTED_SIGNER_WORKFLOW,
) -> None:
    """Fail unless every digest has the expected signature, SBOM and provenance."""
    values = validate_release_image_environment(image_environment)
    verify_release_image_supply_chain(
        values,
        release_tag=release_tag,
        release_commit=release_commit,
        command_runner=command_runner,
        repository=repository,
        signer_workflow=signer_workflow,
    )


def verify_release_image_supply_chain(
    values: Mapping[str, str],
    *,
    release_tag: str,
    release_commit: str,
    command_runner: CommandRunner,
    repository: str = EXPECTED_REPOSITORY,
    signer_workflow: str = EXPECTED_SIGNER_WORKFLOW,
) -> None:
    """Verify one already-parsed immutable image mapping.

    Accepting the mapping lets a caller both verify and consume the same image
    references, without re-reading a mutable operator file between those steps.
    ``verify_release_supply_chain`` remains the path-oriented public wrapper.
    """
    if not _RELEASE_TAG.fullmatch(release_tag):
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH with an optional prerelease")
    if not _COMMIT.fullmatch(release_commit):
        raise ValueError("release commit must be a lowercase 40-character Git commit")
    if signer_workflow != f"{repository}/.github/workflows/release.yml":
        raise ValueError("signer workflow must be this repository's release.yml")

    identity = f"https://github.com/{signer_workflow}@refs/tags/{release_tag}"
    source_ref = f"refs/tags/{release_tag}"

    for variable, suffix in _IMAGE_SUFFIXES.items():
        image_ref = values[variable]
        expected_name = f"ghcr.io/{repository}-{suffix}"
        if image_ref.partition("@")[0] != expected_name:
            raise ValueError(f"{variable} does not name {expected_name}")

        checks = (
            (
                "signature",
                (
                    "cosign",
                    "verify",
                    "--certificate-identity",
                    identity,
                    "--certificate-oidc-issuer",
                    CERTIFICATE_ISSUER,
                    image_ref,
                ),
            ),
            (
                "CycloneDX SBOM attestation",
                (
                    "cosign",
                    "verify-attestation",
                    "--type",
                    "cyclonedx",
                    "--certificate-identity",
                    identity,
                    "--certificate-oidc-issuer",
                    CERTIFICATE_ISSUER,
                    image_ref,
                ),
            ),
            (
                "SLSA provenance",
                (
                    "gh",
                    "attestation",
                    "verify",
                    f"oci://{image_ref}",
                    "--repo",
                    repository,
                    "--bundle-from-oci",
                    "--signer-workflow",
                    signer_workflow,
                    "--source-digest",
                    release_commit,
                    "--source-ref",
                    source_ref,
                    "--predicate-type",
                    PROVENANCE_TYPE,
                ),
            ),
        )
        for label, command in checks:
            try:
                command_runner(command)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                raise ValueError(f"{variable}: {label} verification failed") from exc


def _run_checked(command: Sequence[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"required release verifier is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"{command[0]} rejected the supplied release evidence") from exc


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ValueError("release validation requires a protected release Git checkout") from exc
    return completed.stdout.strip()


def resolve_release_identity(release_tag: str | None = None) -> tuple[str, str]:
    """Return the exact semantic tag and commit for the checked-out release."""
    tracked_changes = _git("status", "--porcelain", "--untracked-files=no")
    if tracked_changes:
        raise ValueError(
            "release checkout has modified, staged, or deleted tracked files; "
            "deploy only an unchanged protected tag"
        )
    commit = _git("rev-parse", "--verify", "HEAD").lower()
    tags = [
        tag
        for tag in _git("tag", "--points-at", "HEAD", "--list", "v*").splitlines()
        if _RELEASE_TAG.fullmatch(tag)
    ]
    if release_tag is None:
        if len(tags) != 1:
            raise ValueError(
                "checkout must have exactly one semantic release tag; pass --release-tag "
                "only when multiple protected release tags point at this commit"
            )
        release_tag = tags[0]
    if not _RELEASE_TAG.fullmatch(release_tag):
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH with an optional prerelease")
    if release_tag not in tags:
        raise ValueError("release tag does not point at the checked-out commit")
    return release_tag, commit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_environment", type=Path)
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    try:
        release_tag, release_commit = resolve_release_identity(args.release_tag)
        verify_release_supply_chain(
            args.image_environment,
            release_tag=release_tag,
            release_commit=release_commit,
            command_runner=_run_checked,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        "release supply chain valid: "
        f"{release_tag} ({release_commit[:12]}) from {EXPECTED_SIGNER_WORKFLOW}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
