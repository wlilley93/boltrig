"""Run production doctor in the exact signed release-image tool context.

The normal doctor intentionally resolves stack CLIs from its own execution
environment. Running it on the deployment host would therefore inspect stray
host installs even though Herdr ships in the kernel image and OpenCode/Browser
Use ship in the fleet image. This admission step first verifies all release
digests against the protected workflow, then creates an ephemeral validation
image containing only the signed fleet image plus Herdr copied from the signed
kernel image. The tool probes and doctor run are networkless and read-only.
"""

from __future__ import annotations

import argparse
import secrets
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.validate_release_images import validate_release_image_environment
from scripts.verify_release_supply_chain import (
    resolve_release_identity,
    verify_release_image_supply_chain,
)

ROOT = Path(__file__).resolve().parents[1]
DOCTOR_DOCKERFILE = ROOT / "deploy" / "release-doctor.Dockerfile"
_MANIFEST_TARGET = "/run/boltrig/manifest.yaml"
_VALIDATION_TAG_PREFIX = "boltrig-release-doctor"

_TOOL_PROBE = """\
import os
import subprocess

tools = (
    ("herdr", "/usr/local/bin/herdr", "herdr"),
    ("opencode", "/usr/local/bin/opencode", "opencode"),
    ("browser-use", "/usr/local/bin/browser-use", "browser-cli"),
)
for name, executable, state_name in tools:
    root = f"/var/lib/boltrig/{state_name}"
    state = {
        "HOME": f"{root}/home",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "XDG_CACHE_HOME": f"{root}/cache",
        "XDG_CONFIG_HOME": f"{root}/config",
        "XDG_DATA_HOME": f"{root}/data",
        "XDG_STATE_HOME": f"{root}/state",
    }
    for path in state.values():
        if path.startswith(root):
            os.makedirs(path, mode=0o700, exist_ok=True)
    if name == "herdr":
        state["HERDR_CONFIG_PATH"] = f"{root}/config/config.toml"
    if name == "opencode":
        state["OPENCODE_CONFIG_DIR"] = f"{root}/config/opencode"
        os.makedirs(state["OPENCODE_CONFIG_DIR"], mode=0o700, exist_ok=True)
    completed = subprocess.run(
        (executable, "--version"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        env=state,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SystemExit(f"{name} release-image probe failed")
    print(f"{name}: release-image executable probe passed")
"""


@dataclass(frozen=True)
class CommandOutput:
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], str | None], CommandOutput]


class CommandExecutionError(ValueError):
    """A child command rejected release evidence without leaking its input."""

    def __init__(
        self,
        command: Sequence[str],
        returncode: int,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(f"{command[0]} exited {returncode}")
        self.stdout = stdout
        self.stderr = stderr


def _run_checked(command: Sequence[str], stdin: str | None = None) -> CommandOutput:
    try:
        completed = subprocess.run(
            command,
            check=False,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"required release validator is unavailable: {command[0]}") from exc
    if completed.returncode != 0:
        raise CommandExecutionError(
            command,
            completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return CommandOutput(stdout=completed.stdout, stderr=completed.stderr)


def _hardened_run_prefix(*, interactive: bool = False) -> tuple[str, ...]:
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=64",
        "--memory=256m",
        "--cpus=1",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--tmpfs=/var/lib/boltrig:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700",
    ]
    if interactive:
        command.append("-i")
    return tuple(command)


def validate_release_runtime(
    image_environment: Path,
    *,
    env_file: Path,
    manifest: Path,
    release_tag: str,
    release_commit: str,
    command_runner: CommandRunner = _run_checked,
    validation_tag: str | None = None,
) -> str:
    """Verify supply-chain evidence, image-owned CLIs, and production doctor."""
    if not env_file.is_file():
        raise ValueError(f"release environment does not exist: {env_file}")
    if not manifest.is_file():
        raise ValueError(f"release manifest does not exist: {manifest}")
    if not DOCTOR_DOCKERFILE.is_file():
        raise ValueError(f"release doctor Dockerfile does not exist: {DOCTOR_DOCKERFILE}")

    images = validate_release_image_environment(image_environment)

    # This happens in the same process and before the first Docker command. The
    # exact image@sha256 references cannot change between verification and use.
    verify_release_image_supply_chain(
        images,
        release_tag=release_tag,
        release_commit=release_commit,
        command_runner=lambda command: command_runner(command, None),
    )

    tag = validation_tag or f"{_VALIDATION_TAG_PREFIX}:{secrets.token_hex(12)}"
    build_command = (
        "docker",
        "build",
        "--pull",
        "--network=none",
        "--tag",
        tag,
        "--build-arg",
        f"BOLTRIG_KERNEL_IMAGE={images['BOLTRIG_KERNEL_IMAGE']}",
        "--build-arg",
        f"BOLTRIG_FLEET_IMAGE={images['BOLTRIG_FLEET_IMAGE']}",
        "-",
    )
    # Docker receives the reviewed Dockerfile over stdin with an empty build
    # context. Operator files (including `.env` and any local CA/rclone config)
    # are therefore structurally unable to enter the ephemeral image.
    command_runner(build_command, DOCTOR_DOCKERFILE.read_text(encoding="utf-8"))

    try:
        probe_command = (
            *_hardened_run_prefix(),
            "--entrypoint=/usr/local/bin/python3",
            tag,
            "-c",
            _TOOL_PROBE,
        )
        command_runner(probe_command, None)

        doctor_command = (
            *_hardened_run_prefix(interactive=True),
            "--mount",
            f"type=bind,source={manifest.resolve()},target={_MANIFEST_TARGET},readonly",
            "--entrypoint=/usr/local/bin/python3",
            tag,
            "-m",
            "boltrig.api.cli",
            "doctor",
            "--env-file",
            "/dev/stdin",
            "--manifest",
            _MANIFEST_TARGET,
            "--production",
        )
        try:
            doctor = command_runner(
                doctor_command,
                env_file.read_text(encoding="utf-8"),
            )
        except CommandExecutionError as exc:
            detail = (exc.stdout or exc.stderr).strip()
            message = "candidate-image production doctor failed"
            if detail:
                message = f"{message}:\n{detail}"
            raise ValueError(message) from exc
    except Exception:
        try:
            command_runner(("docker", "image", "rm", tag), None)
        except Exception:
            pass
        raise

    command_runner(("docker", "image", "rm", tag), None)
    return doctor.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_environment", type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    try:
        release_tag, release_commit = resolve_release_identity(args.release_tag)
        report = validate_release_runtime(
            args.image_environment,
            env_file=args.env_file,
            manifest=args.manifest,
            release_tag=release_tag,
            release_commit=release_commit,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if report.strip():
        print(report.rstrip())
    print(
        "release runtime valid in signed image context: "
        f"{release_tag} ({release_commit[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
