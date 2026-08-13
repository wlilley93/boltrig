"""Release doctor must inspect signed image tools, never deployment-host PATH."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_release_runtime import (
    CommandExecutionError,
    CommandOutput,
    validate_release_runtime,
)
from scripts.verify_release_supply_chain import EXPECTED_REPOSITORY

_TAG = "v1.2.3"
_COMMIT = "a" * 40
_VALIDATION_TAG = "boltrig-release-doctor:test"


def _image_environment(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                f"BOLTRIG_KERNEL_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-kernel@sha256:{'1' * 64}",
                f"BOLTRIG_FLEET_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-fleet@sha256:{'2' * 64}",
                f"BOLTRIG_WORKER_UI_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-worker-ui@sha256:{'3' * 64}",
                f"BOLTRIG_BACKUP_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-backup@sha256:{'4' * 64}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _operator_inputs(tmp_path: Path) -> tuple[Path, Path]:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            (
                "HERDR_BIN=/usr/local/bin/herdr",
                "BOLTRIG_OPENCODE_BIN=/usr/local/bin/opencode",
                "BOLTRIG_BROWSER_CLI_BIN=/usr/local/bin/browser-use",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("organisation: test\ntenant_id: test\n", encoding="utf-8")
    return env, manifest


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
@pytest.mark.invariant("FR-HOST-10")
@pytest.mark.invariant("FR-RUN-18")
def test_release_runtime_verifies_evidence_before_image_context_doctor(
    tmp_path: Path,
) -> None:
    image_environment = _image_environment(tmp_path / "boltrig-images.env")
    env, manifest = _operator_inputs(tmp_path)
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def run(command, stdin):
        command = tuple(command)
        calls.append((command, stdin))
        if len(calls) == 1:
            # A concurrent operator-file change cannot switch the digests after
            # evidence verification: the validator consumes one parsed snapshot.
            image_environment.write_text(
                image_environment.read_text(encoding="utf-8").replace(
                    f"sha256:{'1' * 64}", f"sha256:{'9' * 64}"
                ),
                encoding="utf-8",
            )
        if "doctor" in command:
            return CommandOutput(stdout="Boltrig doctor (production mode)\nSummary: 0 fail")
        return CommandOutput()

    report = validate_release_runtime(
        image_environment,
        env_file=env,
        manifest=manifest,
        release_tag=_TAG,
        release_commit=_COMMIT,
        command_runner=run,
        validation_tag=_VALIDATION_TAG,
    )

    assert "0 fail" in report
    commands = [command for command, _stdin in calls]
    first_docker = next(index for index, command in enumerate(commands) if command[0] == "docker")
    assert first_docker == 12, "all 4 x signature/SBOM/provenance checks must precede Docker"

    build = commands[first_docker]
    assert build[:3] == ("docker", "build", "--pull")
    assert "--network=none" in build
    assert build[-1] == "-", "the build must receive no filesystem context"
    assert (
        f"BOLTRIG_KERNEL_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-kernel@sha256:{'1' * 64}"
        in build
    )
    assert (
        f"BOLTRIG_FLEET_IMAGE=ghcr.io/{EXPECTED_REPOSITORY}-fleet@sha256:{'2' * 64}"
        in build
    )
    build_stdin = calls[first_docker][1]
    assert build_stdin is not None
    assert "FROM ${BOLTRIG_KERNEL_IMAGE}" in build_stdin
    assert env.read_text(encoding="utf-8") not in build_stdin

    docker_runs = [command for command in commands if command[:2] == ("docker", "run")]
    assert len(docker_runs) == 2
    for command in docker_runs:
        assert "--pull=never" in command
        assert "--network=none" in command
        assert "--read-only" in command
        assert "--cap-drop=ALL" in command
        assert "--security-opt=no-new-privileges:true" in command
        assert any(
            item.startswith("--tmpfs=/var/lib/boltrig:") for item in command
        )
        assert _VALIDATION_TAG in command

    probe = next(command for command in docker_runs if "-c" in command)
    probe_program = probe[probe.index("-c") + 1]
    for executable in (
        "/usr/local/bin/herdr",
        "/usr/local/bin/opencode",
        "/usr/local/bin/browser-use",
    ):
        assert executable in probe_program
    assert '"--version"' in probe_program
    assert '"PATH": "/usr/local/bin:/usr/bin:/bin"' in probe_program
    assert "env=state" in probe_program

    doctor = next(command for command in docker_runs if "doctor" in command)
    doctor_stdin = next(stdin for command, stdin in calls if command == doctor)
    assert "-i" in doctor
    assert doctor[doctor.index("--env-file") + 1] == "/dev/stdin"
    assert doctor[doctor.index("--manifest") + 1] == "/run/boltrig/manifest.yaml"
    assert doctor_stdin == env.read_text(encoding="utf-8")
    assert commands[-1] == ("docker", "image", "rm", _VALIDATION_TAG)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_release_runtime_never_uses_an_unverified_image(tmp_path: Path) -> None:
    image_environment = _image_environment(tmp_path / "boltrig-images.env")
    env, manifest = _operator_inputs(tmp_path)
    calls: list[tuple[str, ...]] = []

    def reject_evidence(command, _stdin):
        command = tuple(command)
        calls.append(command)
        raise ValueError("signature rejected")

    with pytest.raises(ValueError, match="signature verification failed"):
        validate_release_runtime(
            image_environment,
            env_file=env,
            manifest=manifest,
            release_tag=_TAG,
            release_commit=_COMMIT,
            command_runner=reject_evidence,
            validation_tag=_VALIDATION_TAG,
        )

    assert calls
    assert all(command[0] != "docker" for command in calls)


@pytest.mark.security
@pytest.mark.invariant("SEC-137")
def test_failed_candidate_doctor_is_blocking_and_ephemeral_image_is_removed(
    tmp_path: Path,
) -> None:
    image_environment = _image_environment(tmp_path / "boltrig-images.env")
    env, manifest = _operator_inputs(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run(command, _stdin):
        command = tuple(command)
        calls.append(command)
        if "doctor" in command:
            raise CommandExecutionError(
                command,
                1,
                stdout="Boltrig doctor (production mode)\nSummary: 1 fail",
            )
        return CommandOutput()

    with pytest.raises(ValueError, match="candidate-image production doctor failed"):
        validate_release_runtime(
            image_environment,
            env_file=env,
            manifest=manifest,
            release_tag=_TAG,
            release_commit=_COMMIT,
            command_runner=run,
            validation_tag=_VALIDATION_TAG,
        )

    assert calls[-1] == ("docker", "image", "rm", _VALIDATION_TAG)


@pytest.mark.security
@pytest.mark.invariant("FR-HOST-10")
@pytest.mark.invariant("FR-RUN-18")
def test_release_doctor_image_contains_only_signed_image_owned_tool_bytes() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[2] / "deploy" / "release-doctor.Dockerfile"
    ).read_text(encoding="utf-8")

    assert "FROM ${BOLTRIG_KERNEL_IMAGE} AS kernel_release" in dockerfile
    assert "FROM ${BOLTRIG_FLEET_IMAGE} AS release_doctor" in dockerfile
    assert (
        "COPY --from=kernel_release /usr/local/bin/herdr /usr/local/bin/herdr"
        in dockerfile
    )
    assert "COPY ." not in dockerfile
    assert "ADD " not in dockerfile
