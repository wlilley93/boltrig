"""Live SO_PEERCRED ingress: a real AF_UNIX peer is attested end-to-end.

Unlike the unit tests (which drive the attestor with fakes over a socketpair),
this exercises the REAL primitives: a real kernel ``accept()`` through
``accept_model_proxy_unix_peer``, real ``SO_PEERPIDFD`` / ``SO_PEERCRED`` via the
default ``LinuxSocketPeerProcessHandleReader``, and a real ``/proc`` capture via
the default ``LinuxProcReader`` - driven by a real child process connecting over
a real Unix socket. Beat 1 of the SO_PEERCRED production path
([2026] VJS-CC-VJS 1 and 3); no bearer is delivered and nothing is written at rest.
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

# A real direct-child peer: connect, then block on recv until the server closes
# the accepted end (recv returns b"") so the process stays alive through
# attestation. Kept tiny and dependency-free so it runs under the same interpreter.
_CONNECT_SCRIPT = (
    "import socket, sys\n"
    "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
    "s.connect(sys.argv[1])\n"
    "s.recv(1)\n"
)


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="SO_PEERCRED/SO_PEERPIDFD ingress is Linux-only (kernel >= 6.5)",
)
async def test_live_unix_peer_connection_attests_to_the_registered_cell_scope() -> None:
    """A real AF_UNIX connection from a real child is attested end-to-end.

    The connecting child is a direct child of this process, so this process is its
    registered ancestor (the "cell"); the attestor captures the child's real
    pidfd/proc identity and binds it to exactly that one live registration - the
    attested scope is proven from the kernel-observed peer, never from anything the
    child sent.
    """

    reader = LinuxProcReader()
    boot_id = read_boot_id(reader)
    captured = capture_linux_process(reader, os.getpid(), expected_boot_id=boot_id)
    root = ModelProxyRootScope("tenant-live", "workspace-live", "root-live")
    assignment = ModelProxyAssignmentScope(
        ModelProxyPhaseScope(root, "phase-live"), "assignment-live"
    )
    scope = ModelProxyCellScope(
        assignment,
        "cell-live",
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

    # Short dir: an AF_UNIX path must fit in 108 bytes, so avoid the long tmp_path.
    socket_dir = Path(tempfile.mkdtemp(prefix="bpr-"))
    socket_path = socket_dir / "peer.sock"
    listener = PeerAttestationUnixListener.bind(socket_path, attestor)
    child: subprocess.Popen[bytes] | None = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", _CONNECT_SCRIPT, os.fspath(socket_path)]
        )
        observed = await asyncio.wait_for(listener.accept_once(), timeout=10)

        # The attested scope is exactly the registered cell identity.
        assert observed is registration.scope
        assert observed == scope
        assert observed.pid == os.getpid()
    finally:
        await listener.aclose()  # closes the accepted peer -> child recv returns -> child exits
        await attestor.aclose()
        if child is not None:
            child.wait(timeout=10)
        shutil.rmtree(socket_dir, ignore_errors=True)
