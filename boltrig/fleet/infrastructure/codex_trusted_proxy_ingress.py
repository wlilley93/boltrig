"""SO_PEERCRED socket ingress for the trusted Codex provider (Track 3, beat 3a).

This is the production-path credential ingress ([2026] VJS-CC-VJS 1 and 3): the
Codex App Server is registered by its REAL /proc identity, a short-path AF_UNIX
listener is bound, and its ``serve`` loop attests each connecting auth-helper peer
over SO_PEERCRED and delivers a freshly-minted, single-cell bearer back on that
same socket (Option-B, nothing at rest).

Beat 3a is ADDITIVE: this module is built and tested on its own; the beat-3b
cutover wires ``CodexTrustedIngress`` into the live provider's ``acquire`` and
removes the 0600-file delivery path (VJS-CC-VJS 3 E4). ``production_ready`` stays
False throughout (E6); writes/effects stay PR8-gated.

Two findings this module encodes (both would fail silently-until-live otherwise):
- FINDING #1: the registered scope MUST be built from ``capture_linux_process`` -
  the SAME capture attestation uses (``canonical_cgroup_digest``) - NOT from
  ``build_cell_scope``/``_read_proc_identity``, which hashes the raw cgroup bytes.
  A raw-vs-canonical digest mismatch would make every ancestry attestation fail.
- FINDING #2: the ingress must not bind a FILESYSTEM socket at all. The stack root
  is a tmpfs owned by the same uid the cells run as, and the old name was derived
  from the cell id, so a sibling cell could pre-create a predictable path and be
  handed another cell's bearer. The ingress binds an ABSTRACT name with a random
  token instead (``select_ingress_socket_name``): no inode to squat, and a name
  already held fails EADDRINUSE rather than losing a race. The 108-byte AF_UNIX
  bound still applies and is still checked.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.application.model_proxy_grants import PhaseScopedModelProxyGrantBroker
from boltrig.fleet.domain import PhaseAssignmentRef
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyBudgetBinding,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)
from boltrig.fleet.infrastructure.cell_privilege import (
    assert_cell_process_unprivileged,
    per_cell_uid_mode_available,
)
from boltrig.fleet.infrastructure.codex_cell_boundary import (
    SHARED_HELPER_ENV_KEY,
    CellIsolationBoundary,
    assert_cell_isolation_boundary,
)
from boltrig.fleet.infrastructure.codex_model_proxy_issuance import issue_cell_bearer
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    cell_model_binding,
    startup_request_id,
)
from boltrig.fleet.infrastructure.linux_peer_identity import (
    LinuxProcReader,
    ProcReader,
    capture_linux_process,
    read_boot_id,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_listener import (
    BearerIssuer,
    PeerAttestationUnixListener,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)

_SOCKET_TOKEN_BYTES = 16


class CodexTrustedIngressError(RuntimeError):
    """The trusted Codex socket ingress could not be started."""


@dataclass(frozen=True)
class CapturedCellIdentity:
    """The App Server's attestation-consistent identity + the uid/gid to register."""

    scope: ModelProxyCellScope
    uid: int
    gid: int


def capture_cell_identity(
    assignment: PhaseAssignmentRef,
    cell_id: str,
    pid: int,
    *,
    reader: ProcReader | None = None,
) -> CapturedCellIdentity:
    """Capture the started App Server's identity the way attestation captures it.

    Mirrors ``build_cell_scope``'s assignment mapping, but sources the process
    identity from ``capture_linux_process`` (canonical cgroup digest, parsed pid-ns
    inode) so the registered scope matches what ``attest_peer_ancestry`` derives for
    the connecting helper's ancestor (FINDING #1). Also yields the real uid/gid the
    registry needs.
    """

    if type(assignment) is not PhaseAssignmentRef:
        raise TypeError("assignment must be an exact PhaseAssignmentRef")
    proc_reader = reader if reader is not None else LinuxProcReader()
    boot_id = read_boot_id(proc_reader)
    captured = capture_linux_process(proc_reader, pid, expected_boot_id=boot_id)
    phase = assignment.phase
    root = ModelProxyRootScope(phase.principal.tenant_id, phase.workspace_id, phase.root_run_id)
    scope_assignment = ModelProxyAssignmentScope(
        ModelProxyPhaseScope(root, phase.phase_id), assignment.assignment_id
    )
    scope = ModelProxyCellScope(
        scope_assignment,
        cell_id,
        captured.pid,
        captured.start_ticks,
        captured.boot_id,
        captured.pid_namespace_inode,
        captured.cgroup_identity_digest,
    )
    return CapturedCellIdentity(scope, captured.uid, captured.gid)


def select_ingress_socket_name() -> str:
    """A fresh unguessable ABSTRACT socket name, in the ``@name`` argv convention.

    The ingress used to bind a filesystem path under the stack root, derived by
    hashing the cell id. Both halves of that were wrong. The stack root is a tmpfs
    owned by uid 10001, which is the SAME uid the cells run as, so a hostile cell
    could pre-create or replace a sibling's socket file; and because the name was
    derived from the cell id it was entirely predictable, so the squat needed no
    guessing at all. The bearer for that sibling would then be delivered to the
    squatter.

    An abstract name has no filesystem presence, so there is nothing to create,
    replace or unlink, and a second ``bind`` of a name already held fails
    ``EADDRINUSE`` rather than quietly winning. That alone is not enough: abstract
    names live in the network namespace, which the cells share with the kernel, so
    a predictable name could still be squatted by binding it FIRST. Hence the
    random token - the name is not a secret, it exists to close the bind race.

    Returned in the ``@name`` form because the name must travel to the cell's auth
    helper through ``execve`` argv, which cannot carry the literal NUL an abstract
    name begins with. The listener and the helper both translate it.
    """

    return f"@boltrig-mp-{secrets.token_hex(_SOCKET_TOKEN_BYTES)}"


def build_ingress_bearer_issuer(
    *,
    broker: PhaseScopedModelProxyGrantBroker,
    registry: ModelProxyProcessRegistry,
    model_id: str,
    policy_digest: str,
    budget: ModelProxyBudgetBinding,
    ttl_seconds: int,
    holder: GenerationHolder,
) -> BearerIssuer:
    """A ``BearerIssuer`` that mints a fresh single-cell bearer per attested peer.

    Each connection re-attests and mints at a strictly higher generation (VJS-CC-VJS
    1 D2), superseding the prior grant - this per-connection issuance is what
    replaces the time-based file refresh loop (Codex re-invokes auth.command every
    ~30s). The bearer is bound to the exact ATTESTED scope; ``issue_cell_bearer``
    hard-guards a binding-builder that strays to any other cell.
    """

    def binding_for_cell(cell_scope: ModelProxyCellScope) -> ModelProxyGrantBinding:
        return ModelProxyGrantBinding(cell_scope, cell_model_binding(model_id, policy_digest), budget)

    async def issue(attested: ModelProxyCellScope) -> bytes:
        async def mint() -> bytes:
            holder.value += 1
            bearer = await issue_cell_bearer(
                attested,
                broker=broker,
                binding_for_cell=binding_for_cell,
                startup_request_id=startup_request_id(attested.cell_id),
                generation=holder.value,
                ttl_seconds=ttl_seconds,
            )
            return bearer.encode("ascii")

        # [2026] VJS-CC-VJS 7 J5: prove the CELL's own privilege state, read by the
        # kernel from /proc, immediately before it is trusted with a credential. A
        # cell that is root, holds any capability, or lost no_new_privs gets
        # nothing. Only meaningful once per-cell uids are enacted, and skipped
        # rather than faked before then: asserting a boundary that does not exist
        # is the failure this whole programme has been correcting.
        if per_cell_uid_mode_available():
            assert_cell_process_unprivileged(attested.pid)

        # Attestation and issuance are two steps; a cell revoked in between must
        # not still receive a bearer. authorize re-checks liveness and mints under
        # the registry lock, so the two become one indivisible fact.
        return await registry.authorize(attested, mint)

    return issue


class CodexTrustedIngress:
    """Per-cell SO_PEERCRED socket ingress: register, bind, and serve.

    Owns one App Server registration + one AF_UNIX listener + its serve task. The
    ``registry``/``attestor`` are shared (provider-level, multi-cell); a fresh
    ingress is started per cell and closed by the provider's reaper. Beat 3a builds
    and tests this in isolation; beat 3b wires it into the live ``acquire``.
    """

    __slots__ = (
        "_attestor",
        "_boundary",
        "_listener",
        "_registration",
        "_registry",
        "_serve_task",
        "_stack_root",
    )

    def __init__(
        self,
        registry: ModelProxyProcessRegistry,
        attestor: LinuxModelProxyPeerAttestor,
        *,
        stack_root: Path,
        boundary: CellIsolationBoundary,
    ) -> None:
        if type(registry) is not ModelProxyProcessRegistry:
            raise TypeError("registry must be an exact ModelProxyProcessRegistry")
        if type(attestor) is not LinuxModelProxyPeerAttestor:
            raise TypeError("attestor must be an exact LinuxModelProxyPeerAttestor")
        if type(boundary) is not CellIsolationBoundary:
            raise TypeError("boundary must be an exact CellIsolationBoundary")
        if not isinstance(stack_root, Path) or not stack_root.is_absolute():
            raise CodexTrustedIngressError("stack_root must be an absolute Path")
        self._registry = registry
        self._attestor = attestor
        self._stack_root = stack_root
        self._boundary = boundary
        self._listener: PeerAttestationUnixListener | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._registration: ModelProxyCellScope | None = None

    async def start(
        self,
        *,
        identity: CapturedCellIdentity,
        socket_name: str,
        bearer_issuer: BearerIssuer,
    ) -> None:
        """Assert the boundary, register the App Server, bind, and start serving.

        Registration happens BEFORE the listener serves, so the first auth-helper
        connection (which Codex makes lazily on its first model request) always finds
        a live registered ancestor to attest against.

        [2026] VJS-CC-VJS 5 G4: the boundary is RE-PROVED here, at ingress startup,
        not merely at composition. Composition can succeed minutes before a cell
        starts, and the whole point of the ruling is that an attestation input must
        be protected at the moment it is USED, so a boundary that has since gone is
        fatal here and no listener is ever bound.
        """

        if self._listener is not None:
            raise CodexTrustedIngressError("ingress already started")
        # Re-prove the EXACT helper composition bound to, not whatever ambient env
        # now resolves: the question is whether THIS program is still protected.
        proved = assert_cell_isolation_boundary(
            stack_root=self._stack_root,
            env={SHARED_HELPER_ENV_KEY: self._boundary.helper_path.as_posix()},
        )
        if (
            proved.mechanism != self._boundary.mechanism
            or proved.helper_path != self._boundary.helper_path
            or proved.helper_sha256 != self._boundary.helper_sha256
        ):
            raise CodexTrustedIngressError(
                "the per-cell isolation boundary changed after composition"
            )
        registration = await self._registry.register(
            identity.scope, expected_uid=identity.uid, expected_gid=identity.gid
        )
        self._registration = registration.scope
        listener = PeerAttestationUnixListener.bind(socket_name, self._attestor)
        self._listener = listener
        self._serve_task = asyncio.create_task(
            listener.serve(bearer_issuer), name=f"codex-trusted-ingress-{identity.scope.cell_id}"
        )

    async def aclose(self) -> None:
        """Stop serving, close the listener, and revoke the registration."""

        if self._serve_task is not None:
            self._serve_task.cancel()
            await asyncio.gather(self._serve_task, return_exceptions=True)
            self._serve_task = None
        if self._listener is not None:
            await self._listener.aclose()
            self._listener = None
        if self._registration is not None:
            await self._registry.revoke(self._registration)
            self._registration = None


__all__ = [
    "CapturedCellIdentity",
    "CodexTrustedIngress",
    "CodexTrustedIngressError",
    "build_ingress_bearer_issuer",
    "capture_cell_identity",
    "select_ingress_socket_name",
]
