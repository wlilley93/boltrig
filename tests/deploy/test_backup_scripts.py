"""Hermetic regression tests for the scheduled backup security boundary."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
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
output=""; database=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) output="$2"; shift 2 ;;
    -d) database="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$output" ]]
if [[ -n "${PG_DUMP_LOG:-}" ]]; then printf '%s\n' "$database" >>"$PG_DUMP_LOG"; fi
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
decrypt=0; input=""; output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) decrypt=1; shift ;;
    -in) input="$2"; shift 2 ;;
    -out) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
if [[ "${FAKE_OPENSSL_FAIL:-0}" == 1 ]]; then exit 44; fi
if [[ "$decrypt" == 1 && "$input" == *boltrig-state-* \
      && "${FAKE_OPENSSL_CORRUPT_STATE_DECRYPT:-0}" == 1 ]]; then
  printf 'not-a-tar-archive\n'
elif [[ -n "$input" && -n "$output" ]]; then
  cp "$input" "$output"
elif [[ -n "$input" ]]; then
  cat "$input"
elif [[ -n "$output" ]]; then
  cat >"$output"
else
  cat
fi
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
        "PG_DUMP_LOG": str(tmp_path / "pg-dump.log"),
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
    assert len(remote_calls) == 3
    assert artifact.name in remote_calls[0]
    assert checksum.name in remote_calls[1]
    assert ".recovery.sha256" in remote_calls[2]


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_recovery_set_covers_boltrig_hatchet_and_encrypted_signing_state(
    tmp_path: Path,
) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    config = tmp_path / "hatchet-config"
    config.mkdir()
    (config / "keys.json").write_text("test-signing-state", encoding="utf-8")
    env.update(
        {
            "BACKUP_DATABASES": "boltrig,hatchet",
            "BACKUP_STATE_DIR": str(config),
            "BACKUP_PASSPHRASE": "test-only-passphrase",
        }
    )

    result = _run(_BACKUP, env)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pg-dump.log").read_text().splitlines() == ["boltrig", "hatchet"]
    backup_dir = tmp_path / "backups"
    assert len(list(backup_dir.glob("boltrig-*.dump.enc"))) == 2
    assert len(list(backup_dir.glob("boltrig-state-*.tar.gz.enc"))) == 1
    recovery = list(backup_dir.glob("boltrig-*.recovery.sha256"))
    assert len(recovery) == 1
    assert len(recovery[0].read_text().splitlines()) == 3
    # archive + checksum for each of three artifacts, then the completion marker
    assert len(rclone_log.read_text().splitlines()) == 7


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_names_custom_primary_database_for_recovery_verification(
    tmp_path: Path,
) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    state = tmp_path / "stack-state"
    state.mkdir()
    (state / "keys.json").write_text("test-signing-state", encoding="utf-8")
    env.update(
        {
            "PGDATABASE": "app_live",
            "BACKUP_DATABASES": "app_live,durable",
            "BACKUP_STATE_DIR": str(state),
            "BACKUP_PASSPHRASE": "test-only-passphrase",
        }
    )

    result = _run(_BACKUP, env)

    assert result.returncode == 0, result.stderr
    backup_dir = tmp_path / "backups"
    recovery = next(backup_dir.glob("boltrig-*.recovery.sha256"))
    names = {line.split("  ", 1)[1] for line in recovery.read_text().splitlines()}
    assert any(name.startswith("boltrig-app_live-") for name in names)
    assert any(name.startswith("boltrig-durable-") for name in names)
    assert not any(
        name.startswith("boltrig-")
        and name[len("boltrig-") :].startswith("20")
        and ".dump" in name
        for name in names
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_verifies_the_encrypted_stack_state_stream_before_publish(
    tmp_path: Path,
) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    state = tmp_path / "stack-state"
    state.mkdir()
    (state / "signing-key.json").write_text("sensitive-state", encoding="utf-8")
    env.update(
        {
            "BACKUP_REMOTE": "",
            "BACKUP_STATE_DIR": str(state),
            "BACKUP_PASSPHRASE": "test-only-passphrase",
            "FAKE_OPENSSL_CORRUPT_STATE_DECRYPT": "1",
        }
    )

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    assert "encrypted stack state archive verification failed" in result.stderr
    backup_dir = tmp_path / "backups"
    assert not list(backup_dir.glob("boltrig-state-*.tar.gz.enc"))
    assert not (backup_dir / ".last-success").exists()


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_sigkill_during_stack_state_backup_never_leaves_a_plaintext_archive(
    tmp_path: Path,
) -> None:
    real_openssl = shutil.which("openssl")
    if real_openssl is None:
        pytest.skip("openssl is required to exercise the encrypted-stream boundary")

    fake_bin, rclone_log = _fake_tools(tmp_path)
    _executable(
        fake_bin,
        "openssl",
        """
decrypt=0; output=""
args=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) decrypt=1; shift ;;
    -out) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
"$REAL_OPENSSL" "${args[@]}"
if [[ "$decrypt" == 0 && "$output" == *boltrig-state-* ]]; then
  kill -KILL "$PPID"
fi
""".strip(),
    )
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    state = tmp_path / "stack-state"
    state.mkdir()
    marker = "sensitive-signing-state-that-must-never-be-plaintext"
    (state / "signing-key.json").write_text(marker, encoding="utf-8")
    env.update(
        {
            "BACKUP_REMOTE": "",
            "BACKUP_STATE_DIR": str(state),
            "BACKUP_PASSPHRASE": "test-only-passphrase",
            "REAL_OPENSSL": real_openssl,
        }
    )

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    backup_dir = tmp_path / "backups"
    # SIGKILL bypasses EXIT cleanup. The only stack-state residue may therefore
    # be the encrypted stream itself; the former .tar.gz.tmp.PID plaintext is
    # forbidden even under an uncatchable termination.
    assert not list(backup_dir.glob("boltrig-state-*.tar.gz"))
    assert not list(backup_dir.glob("boltrig-state-*.tar.gz.tmp.*"))
    encrypted_temps = list(backup_dir.glob("boltrig-state-*.tar.gz.enc.tmp.*"))
    assert len(encrypted_temps) == 1
    encrypted_bytes = encrypted_temps[0].read_bytes()
    assert encrypted_bytes.startswith(b"Salted__")
    assert not encrypted_bytes.startswith(b"\x1f\x8b")
    assert marker.encode() not in encrypted_bytes
    assert not (backup_dir / ".last-success").exists()


@pytest.mark.security
@pytest.mark.invariant("SEC-71")
def test_backup_refuses_unencrypted_hatchet_signing_state(tmp_path: Path) -> None:
    fake_bin, rclone_log = _fake_tools(tmp_path)
    env = _backup_env(tmp_path, fake_bin, rclone_log)
    config = tmp_path / "hatchet-config"
    config.mkdir()
    (config / "keys.json").write_text("test-signing-state", encoding="utf-8")
    env["BACKUP_STATE_DIR"] = str(config)

    result = _run(_BACKUP, env)

    assert result.returncode != 0
    assert "requires BACKUP_PASSPHRASE" in result.stderr
    assert not list((tmp_path / "backups").glob("*"))


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
