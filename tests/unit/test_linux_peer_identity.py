from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from boltrig.fleet.infrastructure.linux_peer_identity import (
    LinuxPeerIdentityError,
    LinuxProcReader,
    canonical_cgroup_digest,
    capture_linux_process,
    read_boot_id,
)

from .model_proxy_peer_fakes import (
    BOOT_ID,
    DEFAULT_CGROUP_DIGEST,
    DEFAULT_GID,
    DEFAULT_NAMESPACE,
    DEFAULT_UID,
    ScriptedProcReader,
    install_process,
    proc_stat,
    proc_status,
)


@pytest.mark.unit
def test_process_capture_normalizes_only_bounded_kernel_data() -> None:
    reader = ScriptedProcReader()
    install_process(reader, pid=200, parent_pid=100, start_ticks=20_000)

    process = capture_linux_process(reader, 200, expected_boot_id=read_boot_id(reader))

    assert process.pid == 200
    assert process.parent_pid == 100
    assert process.start_ticks == 20_000
    assert process.boot_id == BOOT_ID
    assert process.pid_namespace_inode == DEFAULT_NAMESPACE
    assert process.cgroup_identity_digest == DEFAULT_CGROUP_DIGEST
    assert process.uid == DEFAULT_UID
    assert process.gid == DEFAULT_GID
    assert repr(process) == "CapturedLinuxProcess(<redacted>)"


@pytest.mark.unit
def test_process_capture_detects_pid_reuse_between_stat_reads() -> None:
    reader = ScriptedProcReader()
    install_process(
        reader,
        pid=200,
        parent_pid=100,
        start_ticks=20_000,
        stat_sequence=[
            proc_stat(200, parent_pid=100, start_ticks=20_000),
            proc_stat(200, parent_pid=100, start_ticks=20_001),
        ],
    )

    with pytest.raises(LinuxPeerIdentityError):
        capture_linux_process(reader, 200, expected_boot_id=BOOT_ID)


@pytest.mark.unit
def test_process_capture_rejects_transitional_or_missing_credentials() -> None:
    reader = ScriptedProcReader()
    install_process(reader, pid=200, parent_pid=100, start_ticks=20_000)
    reader.files["200/status"] = ["Uid:\t1001\t1002\t1001\t1001\nGid:\t1002\t1002\t1002\t1002\n"]
    with pytest.raises(LinuxPeerIdentityError):
        capture_linux_process(reader, 200, expected_boot_id=BOOT_ID)

    reader.files["200/status"] = [proc_status(uid=DEFAULT_UID, gid=DEFAULT_GID).split("Gid:")[0]]
    with pytest.raises(LinuxPeerIdentityError):
        capture_linux_process(reader, 200, expected_boot_id=BOOT_ID)


@pytest.mark.unit
def test_cgroup_digest_is_order_and_controller_canonical() -> None:
    first = "2:memory,cpu:/boltrig/cell\n1:io:/boltrig/cell\n"
    second = "1:io:/boltrig/cell\n2:cpu,memory:/boltrig/cell\n"

    assert canonical_cgroup_digest(first) == canonical_cgroup_digest(second)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "0::/boltrig/\x00secret\n",
        "0::/boltrig//cell\n",
        "0::/boltrig/../other\n",
        "0::/boltrig/cell\n\n",
        "1:cpu,cpu:/boltrig/cell\n",
        "not-a-cgroup\n",
        "".join(f"{index}:cpu:/cell\n" for index in range(17)),
        "0::/" + "x" * 1_025 + "\n",
    ],
)
def test_cgroup_data_rejects_controls_malformed_and_multiline_bounds(raw: str) -> None:
    with pytest.raises(LinuxPeerIdentityError):
        canonical_cgroup_digest(raw)


@pytest.mark.unit
def test_boot_identity_rejects_multiple_lines_and_noncanonical_values() -> None:
    reader = ScriptedProcReader()
    for value in (BOOT_ID.upper() + "\n", BOOT_ID + "\nextra\n", BOOT_ID + " \n"):
        reader.files["sys/kernel/random/boot_id"] = [value]
        with pytest.raises(LinuxPeerIdentityError):
            read_boot_id(reader)


@pytest.mark.unit
def test_linux_proc_reader_enforces_root_and_byte_bounds(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    (root / "bounded").write_bytes(b"12345")
    reader = LinuxProcReader(root)

    assert reader.read_file("bounded", max_bytes=5) == "12345"
    with pytest.raises(LinuxPeerIdentityError):
        reader.read_file("bounded", max_bytes=4)
    with pytest.raises(LinuxPeerIdentityError):
        reader.read_file("../bounded", max_bytes=5)


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "linux", reason="Linux proc identity smoke test")
def test_linux_proc_reader_captures_current_process_identity() -> None:
    reader = LinuxProcReader()
    boot_id = read_boot_id(reader)

    process = capture_linux_process(reader, os.getpid(), expected_boot_id=boot_id)

    assert process.pid == os.getpid()
    assert process.start_ticks > 0
    assert process.pid_namespace_inode > 0
    assert process.cgroup_identity_digest.startswith("sha256:")
    assert process.uid == os.getuid()
    assert process.gid == os.getgid()
