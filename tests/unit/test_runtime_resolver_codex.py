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

import pytest

from boltrig.fleet.runtime_resolver import (
    PinnedRuntimePolicyUnavailable,
    RuntimeResolver,
)
from boltrig.models import AgentCapability, GrantSet, InvocationContext


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


def test_explicit_read_only_resolution_suppresses_star_kernel_tools() -> None:
    resolver = _resolver({"trusted": True})
    resolved = resolver._codex_config(
        _capability("codex", ["*"]),
        None,
        allow_kernel_tools=False,
    )
    assert resolved is not None
    assert resolved["kernel_tools"] is False


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


# --------------------------------------------------------------------------- #
# The model that served the call is part of the record (Test 4: "at what cost"
# is unverifiable without "by which model" - pricing is keyed BY model).
#
# Observed live on cvboltrig: 14 agent_spawn rows carrying token AND cost figures
# and ZERO rows anywhere naming a model, because model_route was populated only
# when a model PROFILE applied. The ordinary path audited {runtime, capability}
# and left the model silent.
# --------------------------------------------------------------------------- #
from boltrig.fleet.runtime_resolver import served_model_route  # noqa: E402
from boltrig.models import ModelEndpoint  # noqa: E402


def _endpoint(**kw) -> ModelEndpoint:
    base = dict(
        id="cerebras", tenant_id="tenant-1", kind="openai",
        model="gpt-oss-120b", data_class="standard",
    )
    base.update(kw)
    return ModelEndpoint(**base)


def test_the_served_model_and_provider_are_recorded():
    assert served_model_route(_endpoint()) == {
        "model": "gpt-oss-120b",
        "provider": "openai",
    }


def test_no_endpoint_says_nothing_rather_than_saying_empty():
    # None, not {} - a reader must be able to tell "nothing resolved" from an
    # answer, and an empty dict in the audit reads like one.
    assert served_model_route(None) is None


def test_an_endpoint_with_no_model_says_nothing():
    assert served_model_route(_endpoint(model="")) is None


def test_the_route_never_carries_a_base_url():
    # The audit detail is bounded (K-20); a base_url is infrastructure, and the
    # existing spawn test already asserts no base_url reaches the event.
    route = served_model_route(_endpoint(base_url="http://bifrost.internal/v1"))
    assert route is not None
    assert "base_url" not in route
    assert "bifrost.internal" not in repr(route)


# --- the WIRING, not just the function -------------------------------------- #
# served_model_route being correct proves nothing if resolve never calls it. That
# is the same unwired-claim shape this fix exists to close, so it gets its own
# test rather than an exemption.

class _StoreWithEndpoint:
    def __init__(self, endpoint: ModelEndpoint | None) -> None:
        self._endpoint = endpoint

    async def get_model_endpoint(self, tenant_id: str, endpoint_id: str | None):
        return self._endpoint


class _KernelWithStore(_FakeKernel):
    def __init__(self, endpoint: ModelEndpoint | None) -> None:
        super().__init__()
        self.store = _StoreWithEndpoint(endpoint)
        self.audit = None


def _cap_with_endpoint() -> AgentCapability:
    cap = _capability("script")
    return replace_capability(cap, model_endpoint="cerebras")


def replace_capability(cap: AgentCapability, **kw) -> AgentCapability:
    from dataclasses import replace as _replace

    return _replace(cap, **kw)


async def test_resolve_records_the_served_model_with_no_profile_in_play():
    """The ordinary path: no model profile, so the fallback is the ONLY thing that
    can name the model. Before this fix the runtime carried no model_route at all
    and the spawn audited {runtime, capability} with the model silent."""
    resolver = RuntimeResolver(_KernelWithStore(_endpoint()))
    runtime = await resolver.runtime_for("tenant-1", _cap_with_endpoint(), None)
    route = getattr(runtime, "model_route", None)
    assert route is not None, "resolve did not record the model that served the call"
    assert route["model"] == "gpt-oss-120b"


async def test_resolve_says_nothing_when_no_endpoint_resolves():
    resolver = RuntimeResolver(_KernelWithStore(None))
    runtime = await resolver.runtime_for("tenant-1", _capability("script"), None)
    assert getattr(runtime, "model_route", None) is None


async def test_pinned_policy_ignores_caller_provider_and_model_profile_overrides(
    monkeypatch,
):
    """Permanent profiles keep their authored runtime/model selection.

    Caller AI configuration still resolves for credential policy, but its provider
    and model cannot turn an authored permanent script/Codex profile into another
    runtime.  The same applies to a request model-profile hint.
    """
    import boltrig.identity as identity
    from boltrig.fleet.runtime import ScriptRuntime
    from boltrig.identity import AiKeyResolution

    async def configured_key(*args, **kwargs):
        return AiKeyResolution(
            level="user",
            credential_ref="sealed-key",
            provider="openai",
            model="caller-model",
            base_url="https://caller.invalid",
        )

    async def key_material(*args, **kwargs):
        return "secret-material"

    monkeypatch.setattr(identity, "resolve_ai_key", configured_key)
    monkeypatch.setattr(identity, "load_ai_key_material", key_material)
    resolver = RuntimeResolver(_KernelWithStore(_endpoint()))
    capability = _cap_with_endpoint()
    context = InvocationContext(
        tenant_id="tenant-1",
        actor="head",
        actor_tier="tier2",
        workspace_id="workspace",
        on_behalf_of="alice",
        extra={"model_profile": "caller-profile"},
    )

    runtime = await resolver.runtime_for(
        "tenant-1", capability, context, pinned_policy=True
    )

    assert isinstance(runtime, ScriptRuntime)
    assert runtime.model_route == {
        "model": "gpt-oss-120b",
        "provider": "openai",
    }


async def test_pinned_codex_profile_refuses_a_different_composed_model():
    resolver = RuntimeResolver(
        _KernelWithStore(_endpoint()),
        codex_config={
            "trusted": True,
            "provider": object(),
            "stack_root": object(),
            "model_id": "different-model",
        },
    )
    resolver._resolve_ai_key = lambda *args, **kwargs: _none_key()  # type: ignore[method-assign]
    capability = replace_capability(
        _capability("codex", ["analysis/*"]),
        model_endpoint="cerebras",
        is_ephemeral=False,
    )

    with pytest.raises(PinnedRuntimePolicyUnavailable):
        await resolver.runtime_for(
            "tenant-1",
            capability,
            InvocationContext(tenant_id="tenant-1", actor="head"),
            pinned_policy=True,
        )


async def _none_key():
    return None, None
