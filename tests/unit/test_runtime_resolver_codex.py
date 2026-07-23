"""RuntimeResolver codex-lane gating ([2026] VJS-CC-VJS 2).

``_codex_config`` returns the injected trusted-Codex config ONLY for a capability
whose ``runtime == "codex"``, and NEVER on a ``runtime_override`` (Codex is a
trusted, hard-walled lane, not a provider-routing target). Off by default (no
config injected) it returns None so ``build_runtime`` degrades to ScriptRuntime.

The kernel-tools lane marker: a ``runtime: codex`` capability with
``supported_skills: ['*']`` gets the run-scoped-token seams (the pi idiom), the
kernel MCP endpoint, and the tool-ceiling compiler; a narrower capability keeps
the read-only lane (``kernel_tools`` False) with the same seams present but
unused.
"""

from __future__ import annotations

from boltrig.fleet.runtime_resolver import RuntimeResolver
from boltrig.models import AgentCapability, GrantSet


def _capability(runtime: str, supported_skills: list[str] | None = None) -> AgentCapability:
    return AgentCapability(
        name="cap",
        tenant_id="tenant-1",
        runtime=runtime,
        supported_skills=["*"] if supported_skills is None else supported_skills,
        max_depth=2,
        is_ephemeral=True,
        cost_tier="standard",
    )


class _FakeMcp:
    def issue_run_token(self, *args: object, **kwargs: object) -> str:
        return "run-token"

    def revoke(self, token: str) -> None:
        return None


class _FakeKernel:
    def __init__(self) -> None:
        self.mcp = _FakeMcp()
        self.store = object()


def _resolver(codex_config: dict[str, object] | None) -> RuntimeResolver:
    return RuntimeResolver(_FakeKernel(), codex_config=codex_config)


def test_codex_config_none_for_non_codex_capability() -> None:
    resolver = _resolver({"trusted": True})
    assert resolver._codex_config(_capability("pi"), None) is None


def test_codex_config_returns_injected_for_codex_capability() -> None:
    injected = {"trusted": True, "provider": object()}
    resolver = _resolver(injected)
    resolved = resolver._codex_config(_capability("codex", ["analysis/*"]), None)
    assert resolved is not None
    assert resolved["trusted"] is True
    assert resolved["provider"] is injected["provider"]
    # A narrower-skill capability keeps the read-only analysis lane.
    assert resolved["kernel_tools"] is False


def test_codex_config_marks_the_kernel_tools_lane_for_star_skills() -> None:
    resolver = _resolver({"trusted": True})
    resolved = resolver._codex_config(_capability("codex", ["*"]), None)
    assert resolved is not None
    assert resolved["kernel_tools"] is True
    # The pi idiom: the kernel's own run-scoped token seam, never a credential.
    assert resolved["issue_token"] == resolver._kernel.mcp.issue_run_token
    assert resolved["revoke_token"] == resolver._kernel.mcp.revoke
    assert resolved["mcp_url"] == "http://kernel:8000/v1/mcp"
    assert callable(resolved["compile_tool_ceiling"])


def test_codex_config_never_triggers_on_runtime_override() -> None:
    injected = {"trusted": True}
    resolver = _resolver(injected)
    # A non-codex capability with runtime_override == "codex" must NOT select the
    # trusted lane: gating is on capability.runtime only.
    assert resolver._codex_config(_capability("pi"), "codex") is None


def test_codex_config_none_when_no_config_injected() -> None:
    resolver = _resolver(None)
    assert resolver._codex_config(_capability("codex"), None) is None


class _FakeStore:
    def __init__(self) -> None:
        self._verbs = ()

    async def get_tenant_permissions(self, tenant_id: str) -> object:
        class _Perms:
            grants = GrantSet.of(["ticket.read", "jira.create"])

        return _Perms()

    async def list_verbs(self, tenant_id: str) -> tuple[object, ...]:
        class _Verb:
            def __init__(self, verb_id: str) -> None:
                self.id = verb_id

        return tuple(_Verb(v) for v in ("ticket.read", "ticket.write", "jira.create"))


async def test_compile_codex_tool_ceiling_is_tenant_ceiling_intersect_run_grants() -> None:
    kernel = _FakeKernel()
    kernel.store = _FakeStore()
    resolver = RuntimeResolver(kernel, codex_config={"trusted": True})
    # tenant ceiling permits ticket.read + jira.create; the run grants only
    # ticket.read (+ ticket.write, which the tenant does not permit).
    ceiling = await resolver._compile_codex_tool_ceiling(
        "tenant-1", GrantSet.of(["ticket.read", "ticket.write"])
    )
    assert ceiling == ("ticket.read",)
