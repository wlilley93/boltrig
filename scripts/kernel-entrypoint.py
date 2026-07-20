#!/usr/local/bin/python3
"""Kernel container entrypoint: privilege-separate, then exec the real command.

[2026] VJS-CC-VJS 7 J3. The court granted CAP_SETUID/CAP_SETGID with the container
at uid 0, and conditioned it on the API never being the process that holds them.
This is where that separation happens, and it is kept small on purpose: it is the
last code that runs privileged before the API takes over, so it should be readable
in one sitting.

Two paths, and the DEFAULT is the one that changes nothing:

- **Unprivileged (today, and every deployment that has not opted in).** If the
  kernel does not report uid 0 with a non-empty permitted set, this execs the
  command it was given and gets out of the way. Byte-identical behaviour to
  running that command directly. No new failure mode is introduced for anyone who
  has not granted the capability.

- **Privileged.** Fork a minimal spawner that alone keeps CAP_SETUID/CAP_SETGID,
  drop this process to the API uid with an empty permitted set, prove the drop
  from /proc, and only then exec the API.

The order is not interchangeable. The spawner is forked BEFORE the drop because
after the drop we could not create it; the drop is proved from /proc rather than
assumed because a drop that silently failed is exactly what this exists to catch.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from boltrig.fleet.infrastructure.cell_privilege import (  # noqa: E402
    drop_privileges,
    per_cell_uid_mode_available,
)
from boltrig.fleet.infrastructure.cell_spawner import (  # noqa: E402
    SpawnPolicy,
    serve_spawner,
)

# The unprivileged identity the API runs as. Matches the image's boltrig user.
API_UID = 10001
API_GID = 10001
# How the API finds the spawner socket it inherited across the exec.
SPAWNER_FD_ENV = "BOLTRIG_CELL_SPAWNER_FD"
_BINARY_ENV = "BOLTRIG_CODEX_BINARY"
_STACK_ENV = "BOLTRIG_CODEX_STACK_ROOT"


def _run_spawner(child: socket.socket, parent: socket.socket) -> None:
    """The forked child: serve spawn requests as uid 0, then exit. Never returns."""

    parent.close()
    binary = os.environ.get(_BINARY_ENV)
    stack_root = os.environ.get(_STACK_ENV)
    if not binary or not stack_root:
        # Fail closed and loudly: a spawner with no policy would have to either
        # refuse everything (a silent outage) or trust the caller (the whole thing
        # this design exists to prevent).
        sys.stderr.write("boltrig spawner: no binary or stack root policy\n")
        os._exit(2)
    try:
        serve_spawner(child, SpawnPolicy(binary=Path(binary), stack_root=Path(stack_root)))
    finally:
        os._exit(0)


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("boltrig entrypoint: no command given\n")
        return 2
    if not per_cell_uid_mode_available():
        # The overwhelmingly common path. Nothing to separate, so do not pretend
        # to: exec the command exactly as if this entrypoint were not here.
        os.execvp(argv[0], argv)
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    if os.fork() == 0:
        _run_spawner(child, parent)
    child.close()
    # Survive the exec so the API can find it; the spawner holds the only other end.
    os.set_inheritable(parent.fileno(), True)
    os.environ[SPAWNER_FD_ENV] = str(parent.fileno())
    # drop_privileges re-reads /proc and raises if the process is still privileged,
    # so an API that reaches execvp is one the kernel has confirmed is not root.
    drop_privileges(API_UID, API_GID)
    os.execvp(argv[0], argv)
    return 0  # pragma: no cover - execvp does not return


if __name__ == "__main__":  # pragma: no cover - exercised by the container
    raise SystemExit(main(sys.argv[1:]))
