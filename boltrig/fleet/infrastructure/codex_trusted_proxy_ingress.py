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

Three findings this module encodes (each would fail silently-until-live otherwise):
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
- FINDING #3: the uid/gid the registry is given must be the identity the cell MUST
  hold, DECLARED by the caller, never the one ``/proc`` happened to show. The
  privileged spawner publishes a cell's pid from the fork PARENT, three closes and a
  sendmsg from the wire, while the CHILD still has an after-fork fixup, three dup2 and
  only then ``drop_privileges`` to run - so a capture taken at the earliest instant the
  pid exists can read the PRE-drop credentials, which are the SPAWNER's (uid 0). A
  registration is immutable, so that snapshot is unrecoverable: once the cell settled
  at its slot uid every auth-helper attestation compared 20001 against a registered 0,
  matched no ancestor, and reported "registered process present but uid/gid differs".
  No bearer, no model call, and a turn that died as ``codex_empty_output_after_error``
  having dispatched no tool call (cv-boltrig-kernel-1, 2026-07-27, a live client
  tenant; latent since the per-cell uid lane went live 2026-07-21, intermittent because
  it is a race the API usually wins on an idle box). The declaration is the cell's SLOT,
  which is what the kernel enforces rather than an observation of it; the capture is
  demoted to a fail-closed cross-check; and ``build_ingress_bearer_issuer`` has the
  KERNEL confirm that declaration on the pid before any bearer is minted.
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
    read_pid_namespace_inode,
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

# The uid/gid the privileged spawner runs at, and therefore the credentials a cell
# still carries between ``os.fork`` and ``drop_privileges``. Named because FINDING #3's
# one lawful pre-drop reading is stated against it, and because a bare 0 in an
# authentication boundary reads as a constant nobody has thought about.
SPAWNER_PRE_DROP_ID = 0


class CodexTrustedIngressError(RuntimeError):
    """The trusted Codex socket ingress could not be started."""


@dataclass(frozen=True)
class CapturedCellIdentity:
    """The App Server's attestation-consistent scope + the identity to register.

    ``uid``/``gid`` are what the cell MUST hold; a capture can precede its drop (#3).
    """

    scope: ModelProxyCellScope
    uid: int
    gid: int


def capture_cell_identity(
    assignment: PhaseAssignmentRef,
    cell_id: str,
    pid: int,
    *,
    expected_uid: int,
    expected_gid: int,
    reader: ProcReader | None = None,
) -> CapturedCellIdentity:
    """Capture the started App Server's identity the way attestation captures it.

    Mirrors ``build_cell_scope``'s assignment mapping, but sources the process
    identity from ``capture_linux_process`` (canonical cgroup digest, parsed pid-ns
    inode) so the registered scope matches what ``attest_peer_ancestry`` derives for
    the connecting helper's ancestor (FINDING #1).

    ``expected_uid``/``expected_gid`` are the credentials the cell was ALLOCATED, and
    they are what gets registered (FINDING #3). REQUIRED and never defaulted, for the
    reason argv is ([2026] VJS-CC-VJS 6 H5): a caller who cannot say which identity a
    cell must hold has no business registering it, and a default would silently restore
    the racy snapshot at the first call site that forgot.
    """

    if type(assignment) is not PhaseAssignmentRef:
        raise TypeError("assignment must be an exact PhaseAssignmentRef")
    if type(expected_uid) is not int or type(expected_gid) is not int:
        raise TypeError("expected cell credentials must be exact ints")
    if SPAWNER_PRE_DROP_ID in (expected_uid, expected_gid):
        # No cell is ever lawfully root. Unreachable per-cell (a CellSlot uid is inside the
        # reserved band) but live in-process, where a root API would otherwise register root
        # as a cell identity and _path_obeys_cell_policy would accept an all-root chain.
        raise CodexTrustedIngressError("a cell identity may never be registered as root")
    proc_reader = reader if reader is not None else LinuxProcReader()
    boot_id = read_boot_id(proc_reader)
    # The dropped API (uid 10001, empty permitted set) cannot read a uid-distinct
    # cell's restricted /proc/<pid>/ns/pid. But this cell was forked by our spawner
    # with plain os.fork (no CLONE_NEWPID), so it is definitionally in THIS
    # container's pid namespace; that inode is an invariant we can read from self.
    # Supplying it lets the capture complete without the cross-uid read. Spoof
    # detection for a CONNECTING peer is a distinct concern at ingress attestation,
    # not here: we spawned this cell and already know its namespace.
    container_pid_ns = read_pid_namespace_inode(proc_reader)
    captured = capture_linux_process(
        proc_reader, pid, expected_boot_id=boot_id, pid_namespace_inode=container_pid_ns
    )
    # The capture is a CROSS-CHECK, never the source of the expectation: that is what lets
    # a pid published before its drop be registered correctly instead of as root. Only two
    # readings are lawful, the settled credentials and the spawner's pre-drop ones, and uid
    # and gid are compared INDEPENDENTLY because drop_privileges runs setgroups, setgid and
    # then setuid, so (uid 0, gid 20001) is a real mid-drop reading, not a foreign process.
    if captured.uid not in (expected_uid, SPAWNER_PRE_DROP_ID):
        raise CodexTrustedIngressError("the captured cell uid is neither expected nor pre-drop")
    if captured.gid not in (expected_gid, SPAWNER_PRE_DROP_ID):
        raise CodexTrustedIngressError("the captured cell gid is neither expected nor pre-drop")
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
    return CapturedCellIdentity(scope, expected_uid, expected_gid)


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
    expected_cell_uid: int | None,
) -> BearerIssuer:
    """A ``BearerIssuer`` that mints a fresh single-cell bearer per attested peer.

    Each connection re-attests and mints at a strictly higher generation (VJS-CC-VJS
    1 D2), superseding the prior grant - this per-connection issuance is what
    replaces the time-based file refresh loop (Codex re-invokes auth.command every
    ~30s). The bearer is bound to the exact ATTESTED scope; ``issue_cell_bearer``
    hard-guards a binding-builder that strays to any other cell.

    ``expected_cell_uid`` is the cell's slot uid under per-cell uids and None in the
    in-process posture. REQUIRED either way, because it is the confirming half of
    FINDING #3: registration now DECLARES an identity instead of observing one, and a
    declaration nobody asks the kernel to confirm is not a boundary. It also tightens
    J5 from "some unprivileged uid" to "THIS cell's uid" - a cell that dropped to a
    SIBLING slot's uid is unprivileged and has no boundary at all.
    """

    if expected_cell_uid is not None and (
        type(expected_cell_uid) is not int or expected_cell_uid <= SPAWNER_PRE_DROP_ID
    ):
        raise CodexTrustedIngressError("expected cell uid must be a non-root uid, or None")

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
        if expected_cell_uid is not None:
            # Per-cell uids: the registration DECLARED this uid rather than reading it
            # off a process that might not have dropped yet, so ask the kernel to
            # confirm that declaration at the instant of trust.
            assert_cell_process_unprivileged(attested.pid, expected_uid=expected_cell_uid)
        elif per_cell_uid_mode_available():
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
    "SPAWNER_PRE_DROP_ID",
    "CapturedCellIdentity",
    "CodexTrustedIngress",
    "CodexTrustedIngressError",
    "build_ingress_bearer_issuer",
    "capture_cell_identity",
    "select_ingress_socket_name",
]
