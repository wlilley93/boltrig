"""Tests for the trusted per-cell model-auth helper ([2026] VJS-CC-VJS 1/3).

The helper is what Codex's ``[model_providers.*.auth] command`` invokes. Option-B
delivery (VJS-CC-VJS 3): it CONNECTS to the per-cell SO_PEERCRED unix socket and
drains the raw bearer from that connection to stdout - no bearer file at rest. The
stdout contract (E3) is unchanged from the file helper (raw token to stdout, Codex
trims whitespace, exit 0); only the acquisition changed. A cell-id mismatch fails
before any connect, without leaking.

The materialized helper execs the ABSOLUTE ``/usr/local/bin/python3`` (the
sanitized cell PATH is ``/usr/bin:/bin``), which is present in the python:3.12-slim
cell image but not necessarily on the host, so the host gate asserts the script's
content + the /bin/sh cell-id guard (which never reaches python); the full
connect/drain is proven by the live socket integration tests and the in-container
re-proof.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    HELPER_FILENAME,
    TrustedProxyProvisionError,
    materialize_helper,
)

_CELL_ID = "cell-abc1234567890ab"
_SOCKET = Path("/tmp/mp-deadbeefcafe.sock")


def test_helper_is_the_absolute_python_socket_client_for_its_cell(tmp_path: Path) -> None:
    helper_path, digest = materialize_helper(tmp_path, _CELL_ID, _SOCKET)

    assert helper_path == tmp_path / HELPER_FILENAME
    assert oct(helper_path.stat().st_mode & 0o777) == "0o700"
    assert digest.startswith("sha256:")
    assert digest == "sha256:" + hashlib.sha256(helper_path.read_bytes()).hexdigest()

    script = helper_path.read_text(encoding="ascii")
    # Option-B socket client: absolute python (PATH is /usr/bin:/bin), the socket
    # path, an AF_UNIX connect + drain - and NOT the old cat-a-file delivery.
    assert "exec /usr/local/bin/python3 -c" in script
    assert _SOCKET.as_posix() in script
    assert "AF_UNIX" in script
    assert "expected='cell-abc1234567890ab'" in script
    assert "cat --" not in script and "model_auth_bearer" not in script


def test_helper_refuses_a_mismatched_cell_id_before_any_connect(tmp_path: Path) -> None:
    # The /bin/sh cell-id guard exits before exec-ing python, so this runs on any
    # host regardless of where python lives.
    helper_path, _digest = materialize_helper(tmp_path, _CELL_ID, _SOCKET)
    result = subprocess.run(
        [helper_path.as_posix(), "--cell-id", "cell-someoneelse00"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_materialize_helper_rejects_a_shell_active_socket_path(tmp_path: Path) -> None:
    for bad in (Path('/tmp/a"b.sock'), Path("/tmp/a$b.sock"), Path("/tmp/a`b.sock")):
        with pytest.raises(TrustedProxyProvisionError):
            materialize_helper(tmp_path, _CELL_ID, bad)
