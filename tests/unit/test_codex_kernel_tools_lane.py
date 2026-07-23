"""The kernel-tools Codex lane: admission, provisioning, runtime, provider, probe.

These pin the lane's one new capability - the cell may call BOLTRIG verbs via
the kernel's MCP face with a run-scoped token - against the unchanged wall:
the admission compiles the ceiling from the run's grants, the proxy ceiling is
exactly that set, the token never touches the config file or argv, and the
read-only lane is byte-identical throughout.
"""

from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from boltrig.fleet.codex_runtime import CodexKernelToolWiring, CodexRuntime
from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.domain.profile_policy import BirthPolicyRequest
from boltrig.fleet.application.birth_policies import compile_birth_policy
from boltrig.fleet.domain.profile_policy_values import NativeSubagentLimits
from boltrig.fleet.domain.skill_attestation import SkillAttestationPlan
from boltrig.fleet.infrastructure.codex_cell_policy import (
    CodexCellPolicyError,
    validated_environment_additions,
)
from boltrig.fleet.infrastructure.codex_cell_policy import CodexCellLayout
from boltrig.fleet.infrastructure.codex_cell_provisioning import (
    ProvisioningCodexPhaseAdmissionSource,
)
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    CodexKernelToolScope,
    CodexKernelToolScopeRegistry,
)
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    KERNEL_TOOLS_INSTRUCTIONS,
    KERNEL_TOOLS_PROFILE_NAME,
    codex_mcp_wire_name,
    kernel_tools_static_profile,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    AdmittedCodexCell,
    CodexPhaseAdmission,
    CodexRuntimeAdmissionError,
    CodexWorkspaceProjectionBinding,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_MCP_BEARER_ENV_VAR,
)
from boltrig.fleet.infrastructure.codex_runtime_preflight import (
    _attest_kernel_tools_mcp_inventory,
)
from boltrig.fleet.infrastructure.skill_artifacts import SanitizedWorkspaceProjection
from boltrig.models import GrantSet, InvocationContext

from .codex_runtime_fakes import (
    admission,
    assignment,
    digest,
    fake_cell,
    preflight_receipt,
)

_MCP_URL = "http://kernel:8000/v1/mcp"
_TOOLS = ("mcp__boltrig__ticket_read", "mcp__boltrig__jira_create")


def _kernel_tools_admission(
    exact_assignment: PhaseAssignmentRef | None = None,
    *,
    kernel_tools: tuple[str, ...] = _TOOLS,
    workspace: str = "/srv/boltrig/cells/cell-1/workspace",
) -> CodexPhaseAdmission:
    binding = exact_assignment or assignment()
    profile = kernel_tools_static_profile("gpt-5.4-codex")
    compilation = compile_birth_policy(
        BirthPolicyRequest(
            profile.pin,
            selected_skills=(),
            requested_native_subagents=NativeSubagentLimits(),
        ),
        profile,
        (),
    )
    projection = SanitizedWorkspaceProjection(
        "/srv/boltrig/sources/workspace-1", workspace, digest("workspace"), 1, 12
    )
    layout = CodexCellLayout(
        binding.phase.phase_id,
        "cell-1",
        Path("/srv/boltrig"),
        Path("/srv/boltrig/cells/cell-1"),
        projection,
        Path("/srv/boltrig/cells/cell-1/home"),
        Path("/srv/boltrig/cells/cell-1/codex-home"),
    )
    return CodexPhaseAdmission(
        binding,
        layout,
        CodexWorkspaceProjectionBinding(binding, projection),
        compilation,
        (),
        SkillAttestationPlan(workspace, (), generation=1),
        KERNEL_TOOLS_INSTRUCTIONS,
        compilation.policy.digest(),
        kernel_tools=kernel_tools,
    )


# --- admission ---------------------------------------------------------------


@pytest.mark.invariant("SEC-184")
def test_admission_carries_the_exact_wire_name_ceiling() -> None:
    value = _kernel_tools_admission()
    assert value.kernel_tools == tuple(sorted(_TOOLS))
    policy = value.compilation.policy
    # The domain policy stays tool-free: kernel tools are not Codex runtime tools.
    assert policy.enabled_tools == ()
    assert (policy.profile.name, policy.profile.version) == (
        KERNEL_TOOLS_PROFILE_NAME,
        "1.0.0",
    )


def test_kernel_tools_require_the_kernel_tools_profile() -> None:
    with pytest.raises(CodexRuntimeAdmissionError, match="kernel-tools profile"):
        _misprofiled_admission()


def _misprofiled_admission() -> CodexPhaseAdmission:
    base = admission()
    return CodexPhaseAdmission(
        base.assignment,
        base.layout,
        base.workspace_binding,
        base.compilation,
        base.selected_skill_manifests,
        base.skill_plan,
        base.developer_instructions,
        base.provisioned_policy_digest,
        kernel_tools=_TOOLS,
    )


@pytest.mark.parametrize(
    "tools",
    [
        ("ticket_read",),  # not a wire name
        ("mcp__other__ticket_read",),  # another server
        ("mcp__boltrig__a", "mcp__boltrig__a"),  # duplicate
        ("mcp__boltrig__bad.name",),  # unsanitized
    ],
)
def test_admission_refuses_a_malformed_ceiling(tools: tuple[str, ...]) -> None:
    with pytest.raises(CodexRuntimeAdmissionError):
        _kernel_tools_admission(kernel_tools=tools)


@pytest.mark.invariant("SEC-184")
def test_preflight_mcp_count_is_bound_to_the_admitted_lane() -> None:
    read_only = admission()
    cell = fake_cell(read_only)
    receipt_one = type(preflight_receipt(read_only))(
        preflight_receipt(read_only).skill_attestation, observed_mcp_server_count=1
    )
    with pytest.raises(CodexRuntimeAdmissionError, match="MCP inventory"):
        AdmittedCodexCell(read_only, cell.initialized, receipt_one)

    tool_lane = _kernel_tools_admission()
    tool_cell = fake_cell(tool_lane)
    with pytest.raises(CodexRuntimeAdmissionError, match="MCP inventory"):
        AdmittedCodexCell(tool_lane, tool_cell.initialized, preflight_receipt(tool_lane))
    receipt_ok = type(preflight_receipt(tool_lane))(
        preflight_receipt(tool_lane).skill_attestation, observed_mcp_server_count=1
    )
    assert AdmittedCodexCell(tool_lane, tool_cell.initialized, receipt_ok)


# --- provisioning ------------------------------------------------------------


async def test_provisioning_compiles_the_kernel_tools_lane(tmp_path: Path) -> None:
    source = ProvisioningCodexPhaseAdmissionSource(
        stack_root=tmp_path, model_id="gpt-5.4-codex"
    )
    value = await source.admit(assignment("prov"), kernel_tools=_TOOLS)

    assert value.kernel_tools == tuple(sorted(_TOOLS))
    policy = value.compilation.policy
    assert policy.profile.name == KERNEL_TOOLS_PROFILE_NAME
    assert policy.enabled_tools == ()
    assert value.developer_instructions == KERNEL_TOOLS_INSTRUCTIONS
    assert value.provisioned_policy_digest == policy.digest()


async def test_provisioning_without_tools_is_the_read_only_lane(tmp_path: Path) -> None:
    source = ProvisioningCodexPhaseAdmissionSource(
        stack_root=tmp_path, model_id="gpt-5.4-codex"
    )
    value = await source.admit(assignment("ro"))
    assert value.kernel_tools == ()
    assert value.compilation.policy.profile.name == "codex-read-only"


# --- preflight MCP attestation -----------------------------------------------


def _mcp_payload(
    tools: dict[str, object], *, name: str = "boltrig", auth: str = "bearerToken"
) -> dict[str, object]:
    return {
        "data": [
            {
                "authStatus": auth,
                "name": name,
                "resourceTemplates": [],
                "resources": [],
                "tools": tools,
            }
        ]
    }


def test_kernel_tools_mcp_inventory_accepts_the_exact_kernel_face() -> None:
    payload = _mcp_payload(
        {"ticket.read": {"name": "ticket.read", "inputSchema": {"type": "object"}}}
    )
    _attest_kernel_tools_mcp_inventory(payload, frozenset({_TOOLS[0]}))


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},  # the declared server never came up
        {  # a second server beside ours
            "data": [
                _mcp_payload({})["data"][0],
                _mcp_payload({}, name="attacker")["data"][0],
            ]
        },
        _mcp_payload({}, auth="notLoggedIn"),  # the bearer was not delivered
        _mcp_payload({}, name="attacker"),
        _mcp_payload({"ticket.write": {"name": "ticket.write", "inputSchema": {}}}),
    ],
)
def test_kernel_tools_mcp_inventory_fails_closed(payload: dict[str, object]) -> None:
    with pytest.raises(CodexRuntimeAdmissionError):
        _attest_kernel_tools_mcp_inventory(payload, frozenset({_TOOLS[0]}))


# --- environment additions ---------------------------------------------------


def test_environment_additions_extend_but_never_override_the_base() -> None:
    additions = validated_environment_additions(
        {CODEX_MCP_BEARER_ENV_VAR: "run-token-secret"}
    )
    assert additions == {CODEX_MCP_BEARER_ENV_VAR: "run-token-secret"}
    for bad in (
        {"PATH": "/tmp"},
        {"CODEX_HOME": "/tmp"},
        {"CODEX_ACCESS_TOKEN": "x"},
        {"lowercase": "x"},
        {"GOOD_NAME": "has\nnewline"},
        {"GOOD_NAME": ""},
    ):
        with pytest.raises(CodexCellPolicyError):
            validated_environment_additions(bad)


# --- runtime lane ------------------------------------------------------------


class _FakeLifecycle:
    def __init__(self, *, text: str = "the answer", fail_start: bool = False) -> None:
        self._text = text
        self._fail_start = fail_start
        self.spec: object = None
        self.closed = False

    async def start_thread(self, spec: object) -> RuntimeThreadRef:
        self.spec = spec
        if self._fail_start:
            raise RuntimeError("cell provisioning failed")
        return RuntimeThreadRef(spec.assignment, "codex_app_server", "thr-1")  # type: ignore[attr-defined]

    async def start_turn(self, spec: object) -> RuntimeTurnRef:
        return RuntimeTurnRef(spec.thread, "turn-1")  # type: ignore[attr-defined]

    def events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        return self._events(thread)

    async def _events(self, thread: RuntimeThreadRef) -> AsyncIterator[RuntimeEvent]:
        yield RuntimeEvent(
            event_id="e1",
            assignment=thread.assignment,
            kind=RuntimeEventKind.TURN_COMPLETED,
            thread=thread,
        )

    async def read_turn_output(self, thread: RuntimeThreadRef) -> str:
        return self._text

    async def close_thread(self, thread: RuntimeThreadRef) -> None:
        self.closed = True


class _RecordingTokens:
    def __init__(self) -> None:
        self.issued: list[dict[str, object]] = []
        self.revoked: list[str] = []

    def issue(self, tenant_id: str, grants: GrantSet, **kwargs: object) -> str:
        self.issued.append({"tenant_id": tenant_id, "grants": grants, **kwargs})
        return "run-token-secret"

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id="tenant-1",
        run_id="run-1",
        workspace_id="ws-1",
        actor="chief-of-staff",
        grants=GrantSet.of(["ticket.read", "jira.create"]),
    )


def _wiring(
    tokens: _RecordingTokens,
    registry: CodexKernelToolScopeRegistry,
    *,
    verb_ids: tuple[str, ...] = ("ticket.read", "jira.create"),
) -> CodexKernelToolWiring:
    async def compile_ceiling(tenant_id: str, grants: GrantSet) -> tuple[str, ...]:
        return verb_ids

    return CodexKernelToolWiring(
        issue_token=tokens.issue,
        revoke_token=tokens.revoke,
        compile_tool_ceiling=compile_ceiling,
        mcp_url=_MCP_URL,
        registry=registry,
    )


@pytest.mark.invariant("SEC-184")
async def test_kernel_tools_run_mints_scopes_and_revokes_the_run_token() -> None:
    tokens = _RecordingTokens()
    registry = CodexKernelToolScopeRegistry()
    lifecycle = _FakeLifecycle()
    runtime = CodexRuntime(
        lifecycle,  # type: ignore[arg-type]
        stack_root=Path("/stack"),
        kernel_tools=_wiring(tokens, registry),
    )

    result = await runtime.run("question?", _context(), tools=["ticket.read"])

    assert result.ok is True
    # The token was minted against the run's EXACT grants, then revoked.
    assert len(tokens.issued) == 1
    issued = tokens.issued[0]
    assert issued["tenant_id"] == "tenant-1"
    assert issued["grants"] == GrantSet.of(["ticket.read", "jira.create"])
    assert issued["run_id"] == "run-1"
    assert tokens.revoked == ["run-token-secret"]
    # The scope was consumed (or discarded): nothing is left registered.
    assert len(registry) == 0
    # The spec is the kernel-tools lane's (matching the provisioned admission).
    spec = lifecycle.spec
    assert getattr(spec, "profile").name == KERNEL_TOOLS_PROFILE_NAME


async def test_kernel_tools_run_registers_the_scope_before_start() -> None:
    tokens = _RecordingTokens()
    registry = CodexKernelToolScopeRegistry()
    seen: list[CodexKernelToolScope] = []

    class _ObservingLifecycle(_FakeLifecycle):
        async def start_thread(self, spec: object) -> RuntimeThreadRef:
            seen.append(registry.take("run-1-codex-assignment"))  # type: ignore[arg-type]
            return await super().start_thread(spec)

    lifecycle = _ObservingLifecycle()
    runtime = CodexRuntime(
        lifecycle,  # type: ignore[arg-type]
        stack_root=Path("/stack"),
        kernel_tools=_wiring(tokens, registry),
    )
    await runtime.run("question?", _context(), tools=["ticket.read"])

    assert len(seen) == 1
    scope = seen[0]
    assert scope is not None
    assert scope.mcp_url == _MCP_URL
    # The ceiling is the run's effective verbs as exact Codex wire names.
    assert scope.tools == (
        codex_mcp_wire_name("jira.create"),
        codex_mcp_wire_name("ticket.read"),
    )
    assert scope.token == "run-token-secret"
    assert "run-token-secret" not in repr(scope)


@pytest.mark.invariant("SEC-184")
async def test_kernel_tools_run_revokes_and_discards_on_failure() -> None:
    tokens = _RecordingTokens()
    registry = CodexKernelToolScopeRegistry()
    runtime = CodexRuntime(
        _FakeLifecycle(fail_start=True),  # type: ignore[arg-type]
        stack_root=Path("/stack"),
        kernel_tools=_wiring(tokens, registry),
    )

    result = await runtime.run("question?", _context(), tools=["ticket.read"])

    assert result.degraded is True
    assert result.output["_degraded"]["reason"].startswith("codex_turn_failed")
    assert tokens.revoked == ["run-token-secret"]
    assert len(registry) == 0


async def test_kernel_tools_run_degrades_without_minting_on_ceiling_failure() -> None:
    tokens = _RecordingTokens()
    registry = CodexKernelToolScopeRegistry()

    async def failing_ceiling(tenant_id: str, grants: GrantSet) -> tuple[str, ...]:
        raise RuntimeError("store unavailable")

    wiring = CodexKernelToolWiring(
        issue_token=tokens.issue,
        revoke_token=tokens.revoke,
        compile_tool_ceiling=failing_ceiling,
        mcp_url=_MCP_URL,
        registry=registry,
    )
    lifecycle = _FakeLifecycle()
    runtime = CodexRuntime(
        lifecycle,  # type: ignore[arg-type]
        stack_root=Path("/stack"),
        kernel_tools=wiring,
    )
    result = await runtime.run("question?", _context(), tools=[])

    assert result.degraded is True
    assert tokens.issued == []  # fail-closed: no token minted before the failure
    assert lifecycle.spec is None  # the lifecycle was never touched


async def test_read_only_run_never_touches_the_kernel_tools_seams() -> None:
    lifecycle = _FakeLifecycle()
    runtime = CodexRuntime(lifecycle, stack_root=Path("/stack"))  # type: ignore[arg-type]
    result = await runtime.run("hi", _context(), tools=[])
    assert result.ok is True
    assert getattr(lifecycle.spec, "profile").name == "codex-read-only"


# --- provider: config write, ceiling derivation, scope hand-off --------------
# These build the REAL trusted provider (same construction as
# test_codex_trusted_proxy_provider.py) and exercise the kernel-tools branches
# without spawning a cell.

import os  # noqa: E402

import httpx  # noqa: E402

from boltrig.fleet.application.model_proxy_grants import (  # noqa: E402
    PhaseScopedModelProxyGrantBroker,
)
from boltrig.fleet.infrastructure.codex_cell_supervisor import (  # noqa: E402
    CodexCellSupervisor,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (  # noqa: E402
    TrustedProxyCodexPhaseCellProvider,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (  # noqa: E402
    GenerationHolder,
)
from boltrig.fleet.infrastructure.memory_model_proxy_grants import (  # noqa: E402
    MemoryModelProxyGrantStore,
)
from boltrig.fleet.infrastructure.model_proxy_peer_attestation import (  # noqa: E402
    LinuxModelProxyPeerAttestor,
)
from boltrig.fleet.infrastructure.model_proxy_peer_registry import (  # noqa: E402
    ModelProxyProcessRegistry,
)

_TEST_SHARED_HELPER = os.path.realpath("/bin/sh")
_TRUSTED_ENV = {
    "BOLTRIG_DEV_AUTH": "1",
    "BOLTRIG_CODEX_TRUSTED": "1",
    "BOLTRIG_CODEX_AUTH_HELPER": _TEST_SHARED_HELPER,
}
_CODEX_BIN = Path("/opt/boltrig/codex/codex")


class _NullSource:
    async def admit(self, assignment: object, slot: object = None) -> object:
        raise AssertionError("admit must not run in these tests")


class _NullProbe:
    async def probe(self, client: object, plan: object) -> object:
        raise AssertionError("probe must not run in these tests")


def _provider(tmp_path: Path) -> TrustedProxyCodexPhaseCellProvider:
    store = MemoryModelProxyGrantStore()
    registry = ModelProxyProcessRegistry()
    return TrustedProxyCodexPhaseCellProvider(
        source=_NullSource(),  # type: ignore[arg-type]
        supervisor=CodexCellSupervisor(binary=_CODEX_BIN, auth=None),
        probe=_NullProbe(),
        broker=PhaseScopedModelProxyGrantBroker(store),
        grant_store=store,
        registry=registry,
        attestor=LinuxModelProxyPeerAttestor(registry),
        stack_root=tmp_path,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        http_client=httpx.AsyncClient(),
        env=dict(_TRUSTED_ENV),
    )


def _scope(assignment_id: str = "run-1-codex-assignment") -> CodexKernelToolScope:
    return CodexKernelToolScope(
        assignment_id=assignment_id,
        mcp_url=_MCP_URL,
        tools=_TOOLS,
        token="run-token-secret",
    )


async def test_provider_renders_the_mcp_entry_without_the_token(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    cell_root = tmp_path / "cells" / "cell-1"
    codex_home = cell_root / "codex-home"
    codex_home.mkdir(parents=True)

    arguments = await provider._write_cell_config(
        cell_id="cell-1",
        cell_root=cell_root,
        codex_home=codex_home,
        model_id="gpt-5.4-codex",
        proxy_port=43190,
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
        kernel_scope=_scope(),
    )

    rendered = (codex_home / "config.toml").read_text(encoding="ascii")
    document = tomllib.loads(rendered)
    assert document["mcp_servers"] == {
        "boltrig": {
            "url": _MCP_URL,
            "bearer_token_env_var": CODEX_MCP_BEARER_ENV_VAR,
        }
    }
    assert "run-token-secret" not in rendered
    assert not any("run-token-secret" in argument for argument in arguments)
    overrides = dict(argument.split("=", 1) for argument in arguments[5::2])
    assert overrides["mcp_servers.boltrig.url"] == f'"{_MCP_URL}"'
    # Everything else about the wall is unchanged.
    assert document["approval_policy"] == "never"
    assert document["sandbox_mode"] == "read-only"


async def test_provider_without_a_scope_writes_the_read_only_config(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    cell_root = tmp_path / "cells" / "cell-2"
    codex_home = cell_root / "codex-home"
    codex_home.mkdir(parents=True)

    await provider._write_cell_config(
        cell_id="cell-2",
        cell_root=cell_root,
        codex_home=codex_home,
        model_id="gpt-5.4-codex",
        proxy_port=43191,
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
    )

    document = tomllib.loads((codex_home / "config.toml").read_text(encoding="ascii"))
    assert document["mcp_servers"] == {}


async def test_provider_ceiling_is_the_admitted_kernel_tools_union(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    admission_value = _kernel_tools_admission()
    holder = GenerationHolder(1)

    proxy = await provider._start_proxy(
        holder,
        frozenset(admission_value.kernel_tools)
        | frozenset(admission_value.compilation.policy.enabled_tools),
    )
    try:
        assert proxy._allowed_tools == frozenset(_TOOLS)
    finally:
        await proxy.aclose()


async def test_provider_take_is_pop_once_and_assignment_keyed(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    registry = provider.kernel_tool_scopes
    registry.register(_scope("assignment-a"))
    assert registry.take("assignment-a") is not None
    assert registry.take("assignment-a") is None
    assert registry.take("assignment-b") is None

