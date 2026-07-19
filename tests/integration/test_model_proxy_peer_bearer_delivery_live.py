"""Live Option-B bearer delivery: the attested peer receives the bearer on-socket.

Beat 2 of the SO_PEERCRED production path ([2026] VJS-CC-VJS 3). A real child
connects over a real AF_UNIX socket, is SO_PEERCRED-attested end-to-end, and the
serve loop writes the scoped bearer back on that SAME socket - proving Option-B
delivery with nothing written at rest. The bearer issuer is a stub (not the real
broker); it returns a known test bearer for the attested scope.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)
from boltrig.fleet.infrastructure.linux_peer_identity import (
    LinuxProcReader,
    capture_linux_process,
    read_boot_id,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_listener import (
    PeerAttestationUnixListener,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)

# The Option-B helper mechanism: connect, drain the bearer to EOF, write it to
# stdout. This is exactly what the production /bin/sh + /usr/local/bin/python3
# helper will do; kept dependency-free so it runs under this interpreter.
_HELPER_SCRIPT = (
    "import socket, sys\n"
    "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
    "s.connect(sys.argv[1])\n"
    "buf = bytearray()\n"
    "while True:\n"
    "    b = s.recv(4096)\n"
    "    if not b:\n"
    "        break\n"
    "    buf += b\n"
    "sys.stdout.buffer.write(bytes(buf))\n"
    "sys.stdout.buffer.flush()\n"
)

_TEST_BEARER = b"boltrig-test-bearer-3f6a1c9e"


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="SO_PEERCRED/SO_PEERPIDFD ingress is Linux-only (kernel >= 6.5)",
)
async def test_serve_delivers_scoped_bearer_to_the_attested_peer_no_file() -> None:
    """The attested child receives exactly the issued bearer, and no file is written."""

    reader = LinuxProcReader()
    boot_id = read_boot_id(reader)
    captured = capture_linux_process(reader, os.getpid(), expected_boot_id=boot_id)
    root = ModelProxyRootScope("tenant-b2", "workspace-b2", "root-b2")
    assignment = ModelProxyAssignmentScope(
        ModelProxyPhaseScope(root, "phase-b2"), "assignment-b2"
    )
    scope = ModelProxyCellScope(
        assignment,
        "cell-b2",
        captured.pid,
        captured.start_ticks,
        captured.boot_id,
        captured.pid_namespace_inode,
        captured.cgroup_identity_digest,
    )

    registry = ModelProxyProcessRegistry()
    registration = await registry.register(
        scope, expected_uid=captured.uid, expected_gid=captured.gid
    )
    attestor = LinuxModelProxyPeerAttestor(registry, max_ancestry=1)

    delivered_scopes: list[ModelProxyCellScope] = []

    async def bearer_issuer(attested: ModelProxyCellScope) -> bytes:
        # The issuer is handed the attested scope (never request data) and returns
        # the raw bearer bytes for exactly that cell.
        assert attested is registration.scope
        delivered_scopes.append(attested)
        return _TEST_BEARER

    # Short dir: an AF_UNIX path must fit in 108 bytes, so avoid the long tmp_path.
    socket_dir = Path(tempfile.mkdtemp(prefix="bpd-"))
    socket_path = socket_dir / "peer.sock"
    listener = PeerAttestationUnixListener.bind(socket_path, attestor)
    serve_task = asyncio.create_task(listener.serve(bearer_issuer))
    child: subprocess.Popen[bytes] | None = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", _HELPER_SCRIPT, os.fspath(socket_path)],
            stdout=subprocess.PIPE,
        )
        # Run the blocking child read off the loop so serve keeps running.
        stdout, _ = await asyncio.wait_for(
            asyncio.to_thread(child.communicate), timeout=10
        )

        # The child received EXACTLY the issued bearer, on the attested socket.
        assert stdout == _TEST_BEARER
        assert delivered_scopes == [registration.scope]

        # E1: nothing at rest - the only entry under the cell dir is the socket.
        assert os.listdir(socket_dir) == ["peer.sock"]
    finally:
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)
        await listener.aclose()
        await attestor.aclose()
        if child is not None:
            child.wait(timeout=10)
        shutil.rmtree(socket_dir, ignore_errors=True)
