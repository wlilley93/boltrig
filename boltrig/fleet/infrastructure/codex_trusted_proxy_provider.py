"""Trusted single-tenant read-only Codex phase-cell provider ([2026] VJS-CC-VJS 2).

This is the trusted-posture ``CodexPhaseCellProvider``: it provisions one
read-only Codex cell, stands up a per-cell loopback model proxy, and mints the
cell's short-TTL scoped bearer from the child's REAL ``/proc`` identity. It is
lawful ONLY off production: ``acquire`` calls ``require_codex_trusted_posture``
before anything, and ``build_runtime`` re-asserts the same wall at the composition
seam (D1). It never flips a production gate - it runs under the existing
``allow_test_only_runtime`` gate with ``production_ready`` left False (D4).

The credential split (D2): the real upstream key is injected server-side by the
proxy and NEVER placed in the cell environment (the supervisor is constructed with
``auth=None``, so ``sanitized_environment`` never sets ``CODEX_ACCESS_TOKEN``); the
cell holds only the short-TTL scoped bearer.

Delivery is Option B ([2026] VJS-CC-VJS 3 E1/E4): the bearer is written to the
SO_PEERCRED-attested socket connection and NO bearer file exists. The interim
0600-file path this module once described is gone, and the two are never run in
parallel. The cell scope is now peer-attested, not merely observed, and the App
Server is registered inside ``CodexCellSupervisor.start`` against the just-spawned
pid, so no live-and-unregistered window exists.

That registration DECLARES the cell's identity from the slot it was allocated
(``_expected_cell_credentials``) rather than observing it (FINDING #3 in
``codex_trusted_proxy_ingress``). Under per-cell uids the spawner publishes a cell's
pid from the fork PARENT, so the capture at ``on_spawned`` can still read the child's
PRE-drop root credentials; because a registration is immutable, registering those
refused the cell's own auth helper for the rest of its life, and every tool turn on
that tenant degraded with no bearer, no model call and no tool call ever dispatched
(cv-boltrig-kernel-1, 2026-07-27). Declaring the identity does NOT reopen the
live-and-unregistered window: registration still runs at ``on_spawned``, before any
protocol traffic, and the kernel is asked to confirm the declaration on the pid at
every issuance instead (``expected_cell_uid``).

[2026] VJS-CC-VJS 5: the auth helper is no longer written into the mutable cell
root. There is one shared helper, root-owned and non-writable on the read-only
image mount, proved at composition and re-proved at ingress startup by
``assert_cell_isolation_boundary`` (G2, G4). The cell's config.toml is NOT so
protected: it carries ``auth.command`` and lives in a CODEX_HOME the shared cell
uid owns, so G3 is OPEN. While it is open this provider REFUSES a second
concurrent cell, and ``production_ready`` stays False.

[2026] VJS-CC-VJS 6 corrects how that last sentence used to be argued. This
docstring said config.toml "must" live in a cell-owned CODEX_HOME, and that the
only routes out were CAP_SETUID or CAP_SYS_ADMIN. The "must" was our own rule in
``codex_cell_policy.validate_cell_layout``, not the runtime's, and the court
refused a capability application built on that premise. The tested position is
now narrower and evidenced: Codex 0.144.3 keeps sqlite state inside CODEX_HOME
and will not start without write access to it, so a read-only shared CODEX_HOME
is not available either (``docs/findings/2026-07-20-codex-home-writability.md``).
G3 stays open on facts, not on an assumed necessity.
Read-only reasoning cutover only; write/effects are separately court-gated
(PR8, D6).

The kernel-tools lane (codex_kernel_tools_phase): a capability with
``supported_skills: '*'`` provisions the SAME walled cell plus exactly one new
capability - an ``[mcp_servers.boltrig]`` entry pointing at the kernel's MCP
face, its bearer a run-scoped kernel token delivered ONLY as a child env var
(never the config file, never argv), and its tool ceiling the admission-compiled
wire names the model proxy enforces. Sandbox, approval plane, attestation and
the single-cell G3 posture are unchanged; the lane hands the scope over through
``kernel_tool_scopes``, a bounded pop-once registry the adapter registers into
and ``_acquire_cell`` consumes.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from boltrig.config import Settings
from boltrig.fleet.application.model_proxy_grants import (
    DEFAULT_MODEL_PROXY_TTL_SECONDS,
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.codex_trusted_wall import require_codex_trusted_posture
from boltrig.fleet.domain import NativeSubagentLimits, PhaseAssignmentRef
from boltrig.fleet.domain.model_proxy_scope import ModelProxyCellScope
from boltrig.fleet.infrastructure.cell_slots import CellSlot
from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellSupervisor,
    InitializedCodexCell,
)
from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    BearerDigestLookup,
    PerCellModelProxyServer,
)
from boltrig.fleet.infrastructure import codex_trusted_proxy_native as native_proxy
from boltrig.fleet.infrastructure.codex_trusted_proxy_ingress import (
    CodexTrustedIngress,
    build_ingress_bearer_issuer,
    capture_cell_identity,
    select_ingress_socket_name,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    AdmittedCodexCell,
    CodexPhaseAdmission,
    CodexPhaseAdmissionSource,
    CodexPreflightProbe,
    CodexRuntimeAdmissionError,
    QuarantinedCodexPreflightReceipt,
)
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    CodexKernelToolScope,
    CodexKernelToolScopeRegistry,
)
from boltrig.fleet.infrastructure.codex_assignment_model_binding import (
    CodexAssignmentModelBinding,
    CodexAssignmentModelBindingRegistry,
)
from boltrig.fleet.infrastructure.codex_runtime_preflight import (
    KernelToolsCodexPreflightProbe,
    QuarantinedCodexPreflightProbe,
)
from boltrig.fleet.infrastructure.codex_runtime_state import remove_cell_root
from boltrig.fleet.infrastructure.codex_runtime_config import (
    CodexReasoningEffort,
    CodexRuntimeConfigReceipt,
)
from boltrig.fleet.infrastructure.codex_runtime_surface_preflight import (
    BoundCodexSurfacePreflightProbe,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    GenerationHolder,
    TrustedProxyProvisionError,
    model_policy_digest,
    read_only_budget,
)
from boltrig.fleet.infrastructure.codex_trusted_cell_config import (
    _expected_cell_credentials,
    compose_and_write_cell_config,
    kernel_tools_environment,
    per_cell_tree_dirs,
)
from boltrig.fleet.infrastructure.codex_cell_boundary import (
    CellIsolationBoundary,
    assert_cell_isolation_boundary,
)
from boltrig.fleet.infrastructure.model_proxy_peer_listener import BearerIssuer
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (
    ModelProxyProcessRegistry,
)


@dataclass(eq=False)
class _TrustedSession:
    """Live per-cell resources the reaper releases when the cell closes."""

    proxy: PerCellModelProxyServer
    scope: ModelProxyCellScope
    ingress: CodexTrustedIngress
    holder: GenerationHolder
    reaper: asyncio.Task[None]
    slot: "CellSlot | None" = None


class TrustedProxyCodexPhaseCellProvider:
    """Provision a trusted read-only Codex cell behind a per-cell loopback proxy."""

    def __init__(
        self,
        *,
        source: CodexPhaseAdmissionSource,
        supervisor: CodexCellSupervisor,
        probe: CodexPreflightProbe,
        broker: PhaseScopedModelProxyGrantBroker,
        grant_store: BearerDigestLookup,
        registry: ModelProxyProcessRegistry,
        attestor: LinuxModelProxyPeerAttestor,
        stack_root: Path,
        upstream_base_url: str,
        upstream_key: str,
        http_client: httpx.AsyncClient,
        generation: int = 1,
        reasoning_effort: CodexReasoningEffort = CodexReasoningEffort.HIGH,
        ttl_seconds: int = DEFAULT_MODEL_PROXY_TTL_SECONDS,
        env: Mapping[str, str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        if type(supervisor) is not CodexCellSupervisor:
            raise TypeError("supervisor must be an exact CodexCellSupervisor")
        # D2 guard: the supervisor MUST be constructed with auth=None so the child
        # environment never carries the upstream key (CODEX_ACCESS_TOKEN).
        if supervisor._auth is not None:
            raise TrustedProxyProvisionError(
                "trusted Codex supervisor must be constructed with auth=None (D2)"
            )
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be a positive integer")
        if type(reasoning_effort) is not CodexReasoningEffort:
            raise TypeError("reasoning_effort must be an exact CodexReasoningEffort")
        if type(registry) is not ModelProxyProcessRegistry:
            raise TypeError("registry must be an exact ModelProxyProcessRegistry")
        if type(attestor) is not LinuxModelProxyPeerAttestor:
            raise TypeError("attestor must be an exact LinuxModelProxyPeerAttestor")
        if not isinstance(stack_root, Path) or not stack_root.is_absolute():
            raise TrustedProxyProvisionError("stack_root must be an absolute Path")
        self._source = source
        self._supervisor = supervisor
        self._probe = probe
        self._broker = broker
        self._grant_store = grant_store
        self._registry = registry
        self._attestor = attestor
        self._stack_root = stack_root
        self._upstream_base_url = upstream_base_url
        self._upstream_key = upstream_key
        self._client = http_client
        self._generation = generation
        self._reasoning_effort = reasoning_effort
        self._ttl = ttl_seconds
        self._env = env
        self._settings = settings
        # G4: prove the named boundary once at composition, so a misbuilt image or a
        # helper on a writable path can never construct a live provider at all.
        self._boundary: CellIsolationBoundary = assert_cell_isolation_boundary(
            stack_root=stack_root, env=env
        )
        self._sessions: dict[str, _TrustedSession] = {}
        # The kernel-tools lane hand-off: the adapter (which holds the run's
        # grants) registers one redacted scope per assignment; ``_acquire_cell``
        # pops it. Always present but empty on the read-only lane, which never
        # registers anything and is byte-identical to before.
        self._kernel_tool_scopes = CodexKernelToolScopeRegistry()
        self._model_bindings = CodexAssignmentModelBindingRegistry()
        # G3 admission is check-then-register: without a lock two concurrent
        # acquires both pass _require_admissible_concurrency before either
        # registers, provisioning the forbidden two-cell state. The lock makes
        # the check and the session registration one indivisible step.
        self._admission_lock = asyncio.Lock()

    async def acquire(self, assignment: PhaseAssignmentRef) -> AdmittedCodexCell:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        # D1: fail closed BEFORE any provisioning or bearer mint can happen.
        require_codex_trusted_posture(self._env, self._settings)
        if self._boundary.config_toml_protected:
            # The two-cell attack needs an UNPROTECTED config.toml; a protected
            # one admits concurrent cells and needs no admission serialisation.
            return await self._acquire_cell(assignment)
        async with self._admission_lock:
            self._require_admissible_concurrency()
            return await self._acquire_cell(assignment)

    @property
    def kernel_tool_scopes(self) -> CodexKernelToolScopeRegistry:
        """The registry the adapter registers a run's kernel-tools scope into."""

        return self._kernel_tool_scopes

    @property
    def model_bindings(self) -> CodexAssignmentModelBindingRegistry:
        return self._model_bindings

    async def _acquire_cell(self, assignment: PhaseAssignmentRef) -> AdmittedCodexCell:
        # Per-cell uids: reserve this cell's slot (distinct uid + kernel-owned tree)
        # up front, so admission, config and argv all use the slot's paths. None in
        # the in-process posture, which is byte-identical to before. Release ownership
        # moves to the reaper once the session is registered; until then, this method
        # releases on any failure (reaper_started tracks the handover).
        model_binding = self._take_model_binding(assignment)
        slot: CellSlot | None = None
        reaper_started = False
        # A registered run scope selects the kernel-tools admission (pop-once).
        kernel_scope = self._kernel_tool_scopes.take(assignment.assignment_id)
        admission: CodexPhaseAdmission | None = None
        holder = GenerationHolder(self._generation)
        proxy: PerCellModelProxyServer | None = None
        cell: InitializedCodexCell | None = None
        scope: ModelProxyCellScope | None = None
        ingress: CodexTrustedIngress | None = None
        try:
            slot = self._supervisor.acquire_slot()
            admission = await self._admit_for_lane(
                assignment,
                slot,
                kernel_scope,
                model_binding,
            )
            proxy, arguments, socket_name, config_receipt = await self._prepare_cell(
                admission, holder, slot, kernel_scope, model_binding
            )
            model_id = admission.compilation.policy.model.model_id
            layout = admission.layout
            ingress = self._build_ingress()
            issuer = self._build_issuer(model_id, holder, slot)

            async def register_spawned(pid: int) -> None:
                nonlocal scope
                scope = await self._register_spawned_cell(
                    assignment=assignment,
                    cell_id=layout.cell_id,
                    pid=pid,
                    slot=slot,
                    ingress=ingress,
                    socket_name=socket_name,
                    issuer=issuer,
                )

            # The supervisor runs the registration against the just-spawned pid,
            # before any protocol traffic, so there is no instant in which a live
            # App Server is unregistered. A cell that fails to register is reaped
            # by the supervisor and never handed out.
            cell = await self._supervisor.start(
                admission.layout,
                arguments=arguments,
                slot=slot,
                on_spawned=register_spawned,
                environment_additions=kernel_tools_environment(kernel_scope),
            )
            if scope is None:
                # start() only returns once on_spawned succeeded, so this cannot
                # happen; fail closed rather than hand out an unregistered cell.
                raise CodexRuntimeAdmissionError("cell started without a registered scope")
            preflight = await self._probe_for_lane(admission, kernel_scope, cell, config_receipt)
            admitted = AdmittedCodexCell(admission, cell, preflight)
            self._register_session(cell, proxy, scope, ingress, holder, slot)
            reaper_started = True
            return admitted
        except BaseException:
            await self._abort_acquire(proxy, scope, ingress, cell, admission, slot, reaper_started)
            raise

    def _take_model_binding(self, assignment: PhaseAssignmentRef) -> CodexAssignmentModelBinding:
        binding = self._model_bindings.take(assignment)
        if binding is None:
            raise CodexRuntimeAdmissionError(
                "trusted Codex assignment has no resolved model binding"
            )
        if binding.tenant_id != assignment.phase.principal.tenant_id:
            raise CodexRuntimeAdmissionError(
                "trusted Codex model binding does not match the assignment"
            )
        return binding

    async def _prepare_cell(
        self,
        admission: CodexPhaseAdmission,
        holder: GenerationHolder,
        slot: CellSlot | None,
        kernel_scope: CodexKernelToolScope | None,
        model_binding: CodexAssignmentModelBinding,
    ) -> tuple[
        PerCellModelProxyServer,
        tuple[str, ...],
        str,
        CodexRuntimeConfigReceipt,
    ]:
        policy = native_proxy.codex_proxy_admission(admission)
        proxy = await self._start_proxy(
            holder,
            policy.allowed_tools,
            policy.model_id,
            policy.reasoning_effort,
            gateway_virtual_key=model_binding.gateway_virtual_key,
            native_collaboration=policy.native_collaboration,
        )
        layout = admission.layout
        socket_name = select_ingress_socket_name()
        composed = await compose_and_write_cell_config(
            supervisor=self._supervisor,
            boundary=self._boundary,
            reasoning_effort=self._reasoning_effort,
            cell_id=layout.cell_id,
            cell_root=layout.cell_root,
            codex_home=layout.codex_home,
            model_id=policy.model_id,
            proxy_port=proxy.port,
            socket_name=socket_name,
            native_subagents=policy.native_subagents,
            slot=slot,
            tree_dirs=per_cell_tree_dirs(layout) if slot else [],
            kernel_scope=kernel_scope,
        )
        return proxy, composed.receipt.app_server_arguments, socket_name, composed.receipt

    async def _register_spawned_cell(
        self,
        *,
        assignment: PhaseAssignmentRef,
        cell_id: str,
        pid: int,
        slot: CellSlot | None,
        ingress: CodexTrustedIngress,
        socket_name: str,
        issuer: BearerIssuer,
    ) -> ModelProxyCellScope:
        """Capture the just-spawned App Server, declare its identity, register it.

        FINDING #1: the registered scope is built from the cell's real /proc identity
        via the SAME capture attestation uses (canonical cgroup digest), so the
        auth-helper child later attests against a matching ancestor.

        FINDING #3: the uid/gid REGISTERED are the ones the cell was ALLOCATED, never
        the ones this capture read. The spawner publishes a pid from the fork parent,
        so the capture can still see the child's pre-drop root credentials, and a
        registration is immutable - registering those refused the cell's own auth
        helper for the rest of its life (cv-boltrig-kernel-1, 2026-07-27).

        Raising leaves nothing live: the capture's cross-check runs before the
        registration exists, and a failure after it (the listener bind) is revoked by
        the ``ingress.aclose`` that ``_abort_acquire`` runs through ``_teardown``.
        """

        expected_uid, expected_gid = _expected_cell_credentials(slot)
        identity = capture_cell_identity(
            assignment, cell_id, pid, expected_uid=expected_uid, expected_gid=expected_gid
        )
        await ingress.start(identity=identity, socket_name=socket_name, bearer_issuer=issuer)
        return identity.scope

    async def _abort_acquire(
        self,
        proxy: PerCellModelProxyServer | None,
        scope: ModelProxyCellScope | None,
        ingress: CodexTrustedIngress | None,
        cell: InitializedCodexCell | None,
        admission: CodexPhaseAdmission | None,
        slot: CellSlot | None,
        reaper_started: bool,
    ) -> None:
        """Roll back a failed acquire: teardown, close, remove the tree, release the slot."""
        await self._teardown(proxy, scope, ingress)
        if cell is not None:
            await _close_ignoring_failure(cell)
        # A failed acquire must not strand the API-owned cell tree the
        # admission source laid down (in-process posture only; a per-cell
        # slot's tree is the spawner's to clear).
        if admission is not None and not admission.slot_provisioned:
            await remove_cell_root(admission.layout.cell_root)
        # Single-owner slot release: the reaper owns it once the session is
        # registered; before that, this failure path returns it to the pool.
        if not reaper_started:
            self._supervisor.release_slot(slot)

    async def _admit_for_lane(
        self,
        assignment: PhaseAssignmentRef,
        slot: CellSlot | None,
        kernel_scope: CodexKernelToolScope | None,
        model_binding: CodexAssignmentModelBinding,
    ) -> CodexPhaseAdmission:
        """Admit the assignment on the lane its scope (or its absence) selects."""

        if kernel_scope is not None and (
            kernel_scope.assignment_id != assignment.assignment_id or not kernel_scope.tools
        ):
            # An EMPTY ceiling is never admitted as a tools lane: the config
            # would advertise an MCP server the admission does not declare, and
            # the two must always agree. The adapter filters this case into the
            # read-only lane, so an empty scope here is a programming error.
            raise CodexRuntimeAdmissionError("kernel tool scope does not match the assignment")
        if kernel_scope is None:
            admission = await self._source.admit(
                assignment,
                slot,
                model_id=model_binding.model_id,
            )
        else:
            admission = await self._source.admit(
                assignment,
                slot,
                kernel_tools=kernel_scope.tools,
                model_id=model_binding.model_id,
            )
        if type(admission) is not CodexPhaseAdmission or admission.assignment != assignment:
            raise CodexRuntimeAdmissionError("admission source returned another assignment")
        return admission

    async def _probe_for_lane(
        self,
        admission: CodexPhaseAdmission,
        kernel_scope: CodexKernelToolScope | None,
        cell: InitializedCodexCell,
        config_receipt: CodexRuntimeConfigReceipt,
    ) -> QuarantinedCodexPreflightReceipt:
        """The lane's preflight: read-only empty-inventory, or the ONE kernel face.

        The tool-enabled probe attests the declared MCP server came up exact
        (bearer auth, no resources, tools within the admitted ceiling); the
        read-only probe is untouched.
        """

        if kernel_scope is None:
            base: CodexPreflightProbe = self._probe
        else:
            base = KernelToolsCodexPreflightProbe(admission.kernel_tools)
        # Production composition supplies the exact concrete probe. Test doubles
        # keep the protocol-only seam and cannot accidentally fabricate evidence.
        if type(self._probe) is QuarantinedCodexPreflightProbe:
            base = BoundCodexSurfacePreflightProbe(
                base,
                config_receipt,
                admission.kernel_tools,
            )
        return await base.probe(cell.client, admission.skill_plan)

    def _build_ingress(self) -> CodexTrustedIngress:
        return CodexTrustedIngress(
            self._registry,
            self._attestor,
            stack_root=self._stack_root,
            boundary=self._boundary,
        )

    def _build_issuer(
        self, model_id: str, holder: GenerationHolder, slot: CellSlot | None
    ) -> BearerIssuer:
        return build_ingress_bearer_issuer(
            broker=self._broker,
            registry=self._registry,
            model_id=model_id,
            policy_digest=model_policy_digest(model_id, self._reasoning_effort),
            budget=read_only_budget(),
            ttl_seconds=self._ttl,
            holder=holder,
            # J5's confirming half: per-cell the kernel is asked to confirm, on the
            # pid and at the instant of trust, the uid the registration DECLARED. None
            # in-process, where the cell shares the API's uid and there is nothing
            # per_cell_uid_mode_available does not already answer.
            expected_cell_uid=None if slot is None else slot.uid,
        )

    def _require_admissible_concurrency(self) -> None:
        """Refuse a second live cell while config.toml is unprotected (G3).

        config.toml carries ``auth.command`` and must live in a CODEX_HOME the cell
        uid owns, so a sibling cell can replace it and name another program. The
        attack needs two mutually distrusting cells at once, so while
        ``config_toml_protected`` is False we refuse the second one outright rather
        than assert an isolation we cannot prove.
        """

        if self._sessions and not self._boundary.config_toml_protected:
            raise TrustedProxyProvisionError(
                "concurrent Codex cells are refused: config.toml is not protected by "
                f"the {self._boundary.mechanism} boundary ([2026] VJS-CC-VJS 5 G3)"
            )

    async def _start_proxy(
        self,
        holder: GenerationHolder,
        allowed_tools: frozenset[str],
        allowed_model: str,
        allowed_reasoning_effort: str | None = None,
        *,
        gateway_virtual_key: str | None = None,
        native_collaboration: native_proxy.NativeCollaborationWireGate | None = None,
    ) -> PerCellModelProxyServer:
        return await native_proxy.start_codex_model_proxy(
            self,
            holder,
            allowed_tools,
            allowed_model,
            allowed_reasoning_effort,
            gateway_virtual_key=gateway_virtual_key,
            native_collaboration=native_collaboration,
        )

    async def _write_cell_config(
        self,
        *,
        cell_id: str,
        cell_root: Path,
        codex_home: Path,
        model_id: str,
        proxy_port: int,
        socket_name: str,
        native_subagents: NativeSubagentLimits = NativeSubagentLimits(),
        slot: CellSlot | None = None,
        tree_dirs: list[dict[str, object]] | None = None,
        kernel_scope: CodexKernelToolScope | None = None,
    ) -> tuple[str, ...]:
        """Write the cell's config.toml and return the argv pinning the same values.

        Rendering is pure and API-side. The WRITE differs by posture: in-process the
        API writes CODEX_HOME/config.toml directly; per-cell the API cannot write the
        cell-uid slot, so the tree AND the config are handed to the spawner in ONE
        provision (the child clears the slot once, creates the dirs, then writes
        config.toml 0600) - a second provision would re-clear the freshly made tree.

        The kernel-tools lane renders the one ``[mcp_servers.boltrig]`` entry
        (url + bearer env var NAME); the token itself never enters this file.
        """

        composed = await compose_and_write_cell_config(
            supervisor=self._supervisor,
            boundary=self._boundary,
            reasoning_effort=self._reasoning_effort,
            cell_id=cell_id,
            cell_root=cell_root,
            codex_home=codex_home,
            model_id=model_id,
            proxy_port=proxy_port,
            socket_name=socket_name,
            native_subagents=native_subagents,
            slot=slot,
            tree_dirs=tree_dirs,
            kernel_scope=kernel_scope,
        )
        return composed.receipt.app_server_arguments

    def _register_session(
        self,
        cell: InitializedCodexCell,
        proxy: PerCellModelProxyServer,
        scope: ModelProxyCellScope,
        ingress: CodexTrustedIngress,
        holder: GenerationHolder,
        slot: CellSlot | None = None,
    ) -> None:
        reaper = asyncio.create_task(
            self._reap(cell, proxy, scope, ingress, slot),
            name=f"codex-trusted-reap-{cell.metadata.cell_id}",
        )
        self._sessions[cell.metadata.cell_id] = _TrustedSession(
            proxy, scope, ingress, holder, reaper, slot
        )

    async def _reap(
        self,
        cell: InitializedCodexCell,
        proxy: PerCellModelProxyServer,
        scope: ModelProxyCellScope,
        ingress: CodexTrustedIngress,
        slot: CellSlot | None = None,
    ) -> None:
        try:
            await cell.wait_closed()
        finally:
            await self._teardown(proxy, scope, ingress)
            # Return the uid to the pool only after the cell is observed closed, so a
            # successor can never take a uid still in use (J10).
            self._supervisor.release_slot(slot)
            self._sessions.pop(cell.metadata.cell_id, None)

    async def _teardown(
        self,
        proxy: PerCellModelProxyServer | None,
        scope: ModelProxyCellScope | None,
        ingress: CodexTrustedIngress | None,
    ) -> None:
        if ingress is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await ingress.aclose()
        if proxy is not None:
            with contextlib.suppress(Exception):
                await proxy.aclose()
        if scope is not None:
            with contextlib.suppress(Exception):
                await self._broker.cancel_cell(scope)


async def _close_ignoring_failure(cell: InitializedCodexCell) -> None:
    task: asyncio.Task[None] = asyncio.ensure_future(cell.aclose())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
    except BaseException:
        pass


__all__ = [
    "TrustedProxyCodexPhaseCellProvider",
    "TrustedProxyProvisionError",
]
