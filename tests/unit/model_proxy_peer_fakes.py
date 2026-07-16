from __future__ import annotations

from collections.abc import Callable
import threading

from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)
from boltrig.fleet.infrastructure.linux_peer_identity import (
    PeerCredentials,
    canonical_cgroup_digest,
)
from boltrig.fleet.infrastructure.linux_peer_process_handle import AcceptedUnixPeer

BOOT_ID = "018f4d4c-1111-7222-8333-123456789abc"
DEFAULT_CGROUP = "0::/boltrig/cell\n"
DEFAULT_CGROUP_DIGEST = canonical_cgroup_digest(DEFAULT_CGROUP)
DEFAULT_NAMESPACE = 4026533000
DEFAULT_UID = 1001
DEFAULT_GID = 1002


class ScriptedProcReader:
    def __init__(self) -> None:
        self.files: dict[str, list[str]] = {"sys/kernel/random/boot_id": [BOOT_ID + "\n"]}
        self.links: dict[str, list[str]] = {}
        self.calls: dict[tuple[str, str], int] = {}
        self.on_read: Callable[[str, str, int], None] | None = None
        self._lock = threading.Lock()

    def read_file(self, relative_path: str, *, max_bytes: int) -> str:
        return self._read("file", relative_path, max_bytes, self.files)

    def read_link(self, relative_path: str, *, max_bytes: int) -> str:
        return self._read("link", relative_path, max_bytes, self.links)

    def _read(
        self,
        kind: str,
        path: str,
        max_bytes: int,
        values: dict[str, list[str]],
    ) -> str:
        with self._lock:
            key = kind, path
            call = self.calls.get(key, 0)
            self.calls[key] = call + 1
            sequence = values[path]
            value = sequence[min(call, len(sequence) - 1)]
        hook = self.on_read
        if hook is not None:
            hook(kind, path, call)
        if len(value.encode("ascii", errors="ignore")) > max_bytes:
            raise RuntimeError("fake read exceeded requested bound")
        return value


class FakePeerProcessHandle:
    def __init__(
        self,
        credentials: PeerCredentials,
        *,
        fail_on_checks: set[int] | None = None,
    ) -> None:
        self._credentials = credentials
        self._fail_on_checks = fail_on_checks or set()
        self._checks = 0
        self._alive = True
        self._closed = False
        self.close_count = 0
        self._lock = threading.Lock()

    @property
    def credentials(self) -> PeerCredentials:
        return self._credentials

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def checks(self) -> int:
        with self._lock:
            return self._checks

    def mark_dead(self) -> None:
        with self._lock:
            self._alive = False

    def assert_alive(self) -> None:
        with self._lock:
            self._checks += 1
            if self._closed or not self._alive or self._checks in self._fail_on_checks:
                raise RuntimeError("fake peer is not live")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.close_count += 1


class FakePeerProcessHandleReader:
    def __init__(self, *handles: FakePeerProcessHandle) -> None:
        if not handles:
            raise ValueError("at least one fake handle is required")
        self._handles = handles
        self.acquire_count = 0

    def acquire(self, _peer: AcceptedUnixPeer) -> FakePeerProcessHandle:
        index = self.acquire_count
        self.acquire_count += 1
        if index >= len(self._handles):
            raise RuntimeError("no fake peer handle available")
        return self._handles[index]


def install_process(
    reader: ScriptedProcReader,
    *,
    pid: int,
    parent_pid: int,
    start_ticks: int,
    uid: int = DEFAULT_UID,
    gid: int = DEFAULT_GID,
    namespace: int = DEFAULT_NAMESPACE,
    cgroup: str = DEFAULT_CGROUP,
    stat_sequence: list[str] | None = None,
) -> None:
    prefix = str(pid)
    reader.files[f"{prefix}/stat"] = stat_sequence or [
        proc_stat(pid, parent_pid=parent_pid, start_ticks=start_ticks)
    ]
    reader.files[f"{prefix}/status"] = [proc_status(uid=uid, gid=gid)]
    reader.files[f"{prefix}/cgroup"] = [cgroup]
    reader.links[f"{prefix}/ns/pid"] = [f"pid:[{namespace}]"]


def proc_stat(pid: int, *, parent_pid: int, start_ticks: int) -> str:
    suffix = ["S", str(parent_pid), *("0" for _ in range(17)), str(start_ticks)]
    return f"{pid} (codex helper) {' '.join(suffix)}\n"


def proc_status(*, uid: int, gid: int) -> str:
    return f"Name:\tcodex\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nGid:\t{gid}\t{gid}\t{gid}\t{gid}\n"


def cell_scope(
    *,
    pid: int = 200,
    start_ticks: int = 20_000,
    cell_id: str = "cell-1",
    assignment_id: str = "assignment-1",
    boot_id: str = BOOT_ID,
    namespace: int = DEFAULT_NAMESPACE,
    cgroup_digest: str = DEFAULT_CGROUP_DIGEST,
) -> ModelProxyCellScope:
    root = ModelProxyRootScope("tenant-1", "workspace-1", "root-1")
    phase = ModelProxyPhaseScope(root, "phase-1")
    assignment = ModelProxyAssignmentScope(phase, assignment_id)
    return ModelProxyCellScope(
        assignment,
        cell_id,
        pid,
        start_ticks,
        boot_id,
        namespace,
        cgroup_digest,
    )
