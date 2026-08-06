"""Hermetic regression tests for the scheduled backup security boundary."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import time

import pytest


_REPO = Path(__file__).resolve().parents[2]
_BACKUP = _REPO / "scripts" / "backup.sh"
_LOOP = _REPO / "scripts" / "backup-loop.sh"
_HEALTHCHECK = _REPO / "scripts" / "backup-healthcheck.sh"


def _executable(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
    path.chmod(0o755)


# EVERY FAILURE INJECTION BELOW IS AN EXPLICIT `exit`, and that is not a style
# preference. A bare `[[ cond ]]` relying on `set -e` to abort behaves DIFFERENTLY
# across bash versions when another command follows it:
#
#   #!/usr/bin/env bash
#   set -euo pipefail
#   [[ "${FAKE:-0}" != 1 ]]
#   [[ 1 == 1 ]]
#
#   FAKE=1 ./probe.sh   ->   bash 5.3.9 (Linux):  exit 1
#                            bash 3.2.57 (macOS): exit 0
#
# macOS still ships bash 3.2, so on the M4 the pg_restore and openssl stubs
# stopped simulating failure at all: backup.sh ran to completion, wrote its
# archive and its .sha256, and exited 0 with an EMPTY stderr. The two negative
# tests then failed on `assert result.returncode != 0`, which reads like a defect
# in backup.sh and was in fact a defect in the stub that was meant to break it.
#
# The rclone stub never had the bug, because its `[[ ]]` is the last line and a
# script's exit status is its last command's on any bash. That is the whole
# difference, and it is invisible from the stub itself.
#
# A test double that silently stops injecting the failure turns a negative test
# into one that can only pass by accident. Found 2026-08-06 on the M4.


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rclone_log = tmp_path / "rclone.log"
    _executable(
        fake_bin,
        "pg_dump",
        """
if [[ "${FAKE_PG_DUMP_FAIL:-0}" == 1 ]]; then exit 41; fi
output=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == -f ]]; then output="$2"; shift 2; else shift; fi
done
[[ -n "$output" ]]
printf 'custom-format-test-dump\n' >"$output"
""".strip(),
    )
    _executable(
        fake_bin,
        "pg_restore",
        """
if [[ "${FAKE_PG_RESTORE_FAIL:-0}" == 1 ]]; then exit 42; fi
[[ "$1" == --list && -s "$2" ]]
""".strip(),
    )
    _executable(
        fake_bin,
        "rclone",
        """
printf '%s\n' "$*" >>"$RCLONE_LOG"
if [[ "${FAKE_RCLONE_FAIL:-0}" == 1 ]]; then exit 43; fi
""".strip(),
    )
    _executable(
        fake_bin,
        "openssl",
        """
input=""; output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -in) input="$2"; shift 2 ;;
    -out) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [[ "${FAKE_OPENSSL_FAIL:-0}" == 1 ]]; then exit 44; fi
cp "$input" "$output"
""".strip(),
    )
    return fake_bin, rclone_log


def _backup_env(tmp_path: Path, fake_bin: Path, rclone_log: Path) -> dict[str, str]:
    backup_dir = tmp_path / "backups"
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "BACKUP_DIR": str(backup_dir),
        "BACKUP_HEALTH_FILE": str(backup_dir / ".last-success"),
        "BACKUP_KEEP": "7",
        "BACKUP_REMOTE": "test:boltrig",
        "RCLONE_LOG": str(rclone_log),
    }


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_verifies_dump_checksum_and_remote_pair(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)

    result = _run(_BACKUP, env)

    assert result.returncode == 0, result.stderr
    artifacts = list((tmp_path / "backups").glob("boltrig-*.dump"))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    checksum = Path(f"{artifact}.sha256")
    digest, filename = checksum.read_text().split()
    assert digest == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert filename == artifact.name
    assert (tmp_path / "backups" / ".last-success").read_text().strip().isdigit()
    remote_calls = rclone_log.read_text().splitlines()
    assert len(remote_calls) == 2
    assert artifact.name in remote_calls[0]
    assert checksum.name in remote_calls[1]


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_refuses_unparseable_dump_without_success_marker(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    env["FAKE_PG_RESTORE_FAIL"] = "1"

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    assert "pg_restore could not parse" in result.stderr
    assert not list((tmp_path / "backups").glob("boltrig-*.dump"))
    assert not (tmp_path / "backups" / ".last-success").exists()
    assert not rclone_log.exists()


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_remote_failure_leaves_no_success_marker(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    env["FAKE_RCLONE_FAIL"] = "1"

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    assert "off-box copy" in result.stderr
    assert not (tmp_path / "backups" / ".last-success").exists()


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_encryption_retains_verified_checksum_contract(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    env["BACKUP_REMOTE"] = ""
    env["BACKUP_PASSPHRASE"] = "test-only-passphrase"

    result = _run(_BACKUP, env)

    assert result.returncode == 0, result.stderr
    encrypted = list((tmp_path / "backups").glob("boltrig-*.dump.enc"))
    assert len(encrypted) == 1
    assert Path(f"{encrypted[0]}.sha256").is_file()
    assert not list((tmp_path / "backups").glob("boltrig-*.dump"))


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_encryption_failure_leaves_no_final_archive(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    env["BACKUP_PASSPHRASE"] = "test-only-passphrase"
    env["FAKE_OPENSSL_FAIL"] = "1"

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    assert "encryption failed" in result.stderr
    assert not list((tmp_path / "backups").glob("boltrig-*.dump*"))
    assert not (tmp_path / "backups" / ".last-success").exists()


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_loop_exits_nonzero_instead_of_masking_failure(tmp_path: Path) -> None:
    failing_backup = tmp_path / "failing-backup"
    _executable(tmp_path, failing_backup.name, "exit 23")
    env = {
        **os.environ,
        "BACKUP_COMMAND": str(failing_backup),
        "BACKUP_INTERVAL": "1",
    }

    result = _run(_LOOP, env)

    assert result.returncode == 23


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_healthcheck_rejects_missing_malformed_and_stale_success(tmp_path: Path) -> None:
    marker = tmp_path / "last-success"
    env = {
        **os.environ,
        "BACKUP_HEALTH_FILE": str(marker),
        "BACKUP_INTERVAL": "10",
        "BACKUP_HEALTH_GRACE": "5",
    }

    assert _run(_HEALTHCHECK, env).returncode != 0
    marker.write_text("not-an-epoch\n")
    assert _run(_HEALTHCHECK, env).returncode != 0
    marker.write_text(f"{int(time.time()) - 16}\n")
    assert _run(_HEALTHCHECK, env).returncode != 0
    marker.write_text(f"{int(time.time())}\n")
    assert _run(_HEALTHCHECK, env).returncode == 0
