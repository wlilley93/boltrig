"""Live trusted-Codex ingress lifecycle: register, bind, serve, deliver (beat 3a).

Exercises CodexTrustedIngress end-to-end against real primitives - a real registry
+ attestor, a real AF_UNIX listener, and a real child process connecting as the
auth-helper - minus a real Codex App Server (this process stands in as the
registered "cell"/App Server, the child is its auth-helper descendant). Proves both
findings: the capture-based registered scope actually attests (FINDING #1), and the
short stack-root-base socket path binds (FINDING #2). The bearer issuer is a stub.
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

from boltrig.fleet.domain.execution import (
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseRef,
)
from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope
from boltrig.fleet.infrastructure.codex_cell_boundary import (
    SHARED_HELPER_ENV_KEY,
    assert_cell_isolation_boundary,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngress,
    capture_cell_identity,
    select_ingress_socket_name,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)

_HELPER_SCRIPT = (
    "import socket, sys\n"
    "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
    # Mirrors deploy/codex/model_auth_helper: translate the @name argv convention
    # back into the leading NUL an abstract socket name actually needs.
    '''s.connect("\\0" + sys.argv[1][1:])\n'''
    "buf = bytearray()\n"
    "while True:\n"
    "    b = s.recv(4096)\n"
    "    if not b:\n"
    "        break\n"
    "    buf += b\n"
    "sys.stdout.buffer.write(bytes(buf))\n"
    "sys.stdout.buffer.flush()\n"
)

_TEST_BEARER = b"ingress-test-bearer-7c2f"


def _assignment() -> PhaseAssignmentRef:
    return PhaseAssignmentRef(
        PhaseRef(
            root_run_id="run-3a",
            phase_id="phase-3a",
            principal=OrganisationUserRef("org-1", "user-1"),
            workspace_id="workspace-1",
        ),
        "assignment-3a",
    )


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="SO_PEERCRED/SO_PEERPIDFD ingress is Linux-only (kernel >= 6.5)",
)
async def test_ingress_registers_binds_serves_and_delivers_to_the_helper() -> None:
    """A real child, a descendant of the registered 'App Server', is attested and served."""

    registry = ModelProxyProcessRegistry()
    attestor = LinuxModelProxyPeerAttestor(registry, max_ancestry=1)
    # Short stack-root base so the AF_UNIX path stays within 108 bytes (FINDING #2).
    stack_root = Path(tempfile.mkdtemp(prefix="bi-"))
    # /bin/sh stands in for the baked image helper: root-owned on a chain we
    # cannot write ([2026] VJS-CC-VJS 5 G2).
    boundary = assert_cell_isolation_boundary(
        stack_root=stack_root,
        env={SHARED_HELPER_ENV_KEY: os.path.realpath("/bin/sh")},
    )
    ingress = CodexTrustedIngress(
        registry, attestor, stack_root=stack_root, boundary=boundary
    )

    # This process stands in as the cell, so the identity it was "allocated" is its
    # own; FINDING #3's cross-check is exercised on the settled-credentials path,
    # and the registered ids are the declared ones the helper must then match.
    identity = capture_cell_identity(
        _assignment(),
        "cell-3a",
        os.getpid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )

    socket_name = select_ingress_socket_name()

    async def bearer_issuer(attested: ModelProxyCellScope) -> bytes:
        # Handed the attested scope; the registered cell is this process.
        assert attested is identity.scope
        return _TEST_BEARER

    child: subprocess.Popen[bytes] | None = None
    try:
        await ingress.start(
            identity=identity, socket_name=socket_name, bearer_issuer=bearer_issuer
        )
        child = subprocess.Popen(
            [sys.executable, "-c", _HELPER_SCRIPT, socket_name],
            stdout=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            asyncio.to_thread(child.communicate), timeout=10
        )
        assert stdout == _TEST_BEARER
    finally:
        await ingress.aclose()
        await attestor.aclose()  # release the attestor's capture executor threads
        if child is not None:
            child.wait(timeout=10)
        shutil.rmtree(stack_root, ignore_errors=True)
