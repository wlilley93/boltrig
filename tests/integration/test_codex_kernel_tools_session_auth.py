"""The SEC-184 kernel-tools lane under the wall's (b) posture: session auth.

Proves the lane end to end against the REAL kernel MCP face with session login
configured at the edge: the wall admits because per-cell uids are kernel-
attested (the probe is monkeypatched to the deployed answer; the probe itself
is pinned in tests/unit/test_codex_trusted_wall.py and cell_privilege tests),
a run mints its run-scoped token through the exact ``McpFace`` seam, the token
lists only the run's granted verbs, a grant-denied verb is refused at the
chokepoint, and the token is revoked when the run ends. It also pins the
builder: under (b) the '*' capability constructs the tool lane, and without
per-cell uids the same env degrades to the typed unavailable lane.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import boltrig.fleet.codex_trusted_wall as wall
from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.codex_runtime import CodexKernelToolWiring, CodexRuntime
from boltrig.fleet.domain import (
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeThreadRef,
    RuntimeTurnRef,
)
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    CodexKernelToolScopeRegistry,
)
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only


T = "acme"
_MCP_URL = "http://kernel:8000/v1/mcp"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter(T, build_tickets())
    return kernel


def _req(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


class _FakeLifecycle:
    def __init__(
        self, registry: CodexKernelToolScopeRegistry, kernel: Kernel
    ) -> None:
        self._registry = registry
        self._kernel = kernel
        self.scope_token: str | None = None
        self.listed_while_live: set[str] = set()

    async def start_thread(self, spec: object) -> RuntimeThreadRef:
        scope = self._registry.take("run-1-codex-assignment")
        assert scope is not None
        self.scope_token = scope.token
        # The token is LIVE here: list tools over the real kernel MCP face.
        listed = await self._kernel.mcp.handle(
            scope.token, _req("tools/list")
        )
        self.listed_while_live = {tool["name"] for tool in listed["result"]["tools"]}
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
        return "the answer"

    async def close_thread(self, thread: RuntimeThreadRef) -> None:
        return None


@pytest.fixture
def session_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session login configured at the edge, per-cell uids answering True."""
    monkeypatch.setenv("BOLTRIG_CODEX_TRUSTED", "1")
    monkeypatch.setenv("BOLTRIG_AUTH_MODE", "session")
    monkeypatch.delenv("BOLTRIG_DEV_AUTH", raising=False)
    monkeypatch.delenv("BOLTRIG_PRODUCTION", raising=False)
    monkeypatch.setattr(wall, "per_cell_uid_mode_available", lambda env=None: True)


@pytest.mark.invariant("SEC-185")
async def test_tools_lane_runs_under_session_auth_attested_posture(
    session_auth_env: None,
) -> None:
    kernel = await _kernel()
    grants = GrantSet.of(["ticket.read"])
    registry = CodexKernelToolScopeRegistry()

    async def compile_ceiling(tenant_id: str, run_grants: GrantSet) -> tuple[str, ...]:
        perms = await kernel.store.get_tenant_permissions(tenant_id)
        verbs = await kernel.store.list_verbs(tenant_id)
        return tuple(
            verb.id
            for verb in verbs
            if perms.grants.permits(verb.id) and run_grants.permits(verb.id)
        )

    # The wall admits (b) here: session auth is configured and the per-cell
    # probe answers True - the same call build_trusted_codex_runtime makes.
    wall.require_codex_trusted_posture()

    wiring = CodexKernelToolWiring(
        issue_token=kernel.mcp.issue_run_token,
        revoke_token=kernel.mcp.revoke,
        compile_tool_ceiling=compile_ceiling,
        mcp_url=_MCP_URL,
        registry=registry,
    )
    lifecycle = _FakeLifecycle(registry, kernel)
    runtime = CodexRuntime(lifecycle, stack_root=Path("/stack"), kernel_tools=wiring)  # type: ignore[arg-type]
    context = InvocationContext(
        tenant_id=T,
        run_id="run-1",
        workspace_id="ws-1",
        actor="chat-run",
        grants=grants,
    )

    result = await runtime.run("what is open?", context, tools=list(grants.allow))

    assert result.ok is True
    token = lifecycle.scope_token
    assert token is not None and token != ""
    # The minted token was a REAL run-scoped kernel token, scoped to the run's
    # grants: while live it listed exactly ticket.read and nothing else.
    assert lifecycle.listed_while_live == {"ticket.read"}
    # A grant-denied verb called through the same face is refused at the chokepoint.
    assert not kernel.mcp.is_run_token(token)  # revoked at run end
    denied_probe = kernel.mcp.issue_run_token(T, grants, run_id="run-1", actor="chat-run")
    denied = await kernel.mcp.handle(
        denied_probe,
        _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}}),
    )
    assert denied["result"]["isError"] is True
    assert denied["result"]["_boltrig"]["status"] == "denied"


@pytest.mark.invariant("SEC-185")
async def test_builder_constructs_the_tool_lane_only_under_the_attested_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boltrig.fleet.codex_runtime import build_trusted_codex_runtime
    from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
        TrustedProxyCodexPhaseCellProvider,
    )
    from tests.unit.test_codex_kernel_tools_lane import _provider

    monkeypatch.setenv("BOLTRIG_CODEX_TRUSTED", "1")
    monkeypatch.setenv("BOLTRIG_AUTH_MODE", "session")
    monkeypatch.delenv("BOLTRIG_DEV_AUTH", raising=False)
    monkeypatch.delenv("BOLTRIG_PRODUCTION", raising=False)
    provider = _provider(Path("/tmp"))
    assert type(provider) is TrustedProxyCodexPhaseCellProvider
    cfg = {
        "trusted": True,
        "provider": provider,
        "stack_root": Path("/tmp"),
        "model_id": "provider/model-b",
        "kernel_tools": True,
        "issue_token": str,
        "revoke_token": lambda token: None,
        "compile_tool_ceiling": str,
        "mcp_url": _MCP_URL,
    }

    monkeypatch.setattr(wall, "per_cell_uid_mode_available", lambda env=None: False)
    with pytest.raises(wall.CodexTrustedPostureError, match="ingress posture"):
        build_trusted_codex_runtime(cfg, "standard")

    monkeypatch.setattr(wall, "per_cell_uid_mode_available", lambda env=None: True)
    admitted = build_trusted_codex_runtime(cfg, "standard")
    assert isinstance(admitted, CodexRuntime)
    assert admitted._kernel_tools is not None
