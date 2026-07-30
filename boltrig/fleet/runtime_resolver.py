"""Resolve model endpoints and build runtimes for ephemeral spawns."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, cast

from boltrig.config.environment import production_signal
from boltrig.models import AgentCapability, CredentialResolution, InvocationContext, ModelEndpoint

from .model_gateway import ModelGateway, apply_gateway, gateway_config
from .model_profiles import apply_model_profile, select_model_profile
from .model_router import select_model_endpoint
from .runtime import Runtime, build_runtime, runtime_for_provider


class PinnedRuntimePolicyUnavailable(RuntimeError):
    """A composed runtime cannot honestly satisfy an authored pinned profile."""


def served_model_route(endpoint: ModelEndpoint | None) -> dict[str, str] | None:
    """The model that ACTUALLY served a call, for the audit record.

    Extracted rather than inlined so the fallback is testable on its own: reaching it through a
    full ``resolve`` means standing up a kernel, an MCP face and a gateway, which is why the gap it
    fills went unnoticed in the first place.

    Never carries a base_url or a key - only the two facts a reader needs, and both are already on
    ``_PUBLIC_ROUTE_KEYS``. Returns None when there is genuinely nothing to say, so a caller can
    tell "no endpoint resolved" from "an endpoint with no model", rather than recording an empty
    dict that reads like an answer.
    """
    if endpoint is None:
        return None
    model = getattr(endpoint, "model", None)
    if not model:
        return None
    route = {"model": str(model)}
    provider = getattr(endpoint, "kind", None)
    if provider:
        route["provider"] = str(provider)
    return route


def _routed_endpoint(tenant_id: str, base: ModelEndpoint | None, resolution: Any) -> ModelEndpoint:
    """Apply an AI-config provider/model/base-url selection to an endpoint."""
    model = resolution.model or (base.model if base is not None else "")
    base_url = resolution.base_url or (base.base_url if base is not None else None)
    if base is not None:
        return replace(base, model=model, base_url=base_url)
    return ModelEndpoint(
        id="ai-config",
        tenant_id=tenant_id,
        kind=(resolution.provider or "openai"),
        model=model,
        base_url=base_url,
        data_class="standard",
    )


class RuntimeResolver:
    """Owns runtime routing while leaving spawn orchestration thin."""

    def __init__(
        self,
        kernel: Any,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        # Trusted read-only Codex provider config, injected from the api composition
        # root ([2026] VJS-CC-VJS 2). None (the default) => the codex runtime is a
        # degrade-marked unavailable lane (off by default = total no-op).
        self._codex = codex_config
        self._rivet = {
            "agentos_url": os.environ.get("RIVET_AGENTOS_URL")
            or os.environ.get("BOLTRIG_RIVET_AGENTOS_URL")
            or None,
            # The retired Pi lane's MCP env var used to be the last fallback here.
            # It is gone with the lane; the literal default it supplied is unchanged,
            # so a deploy that set neither of the two remaining names behaves exactly
            # as before. See docs/decisions/0020-retire-the-pi-lane.md.
            "mcp_url": os.environ.get("BOLTRIG_RIVET_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or "http://kernel:8000/v1/mcp",
            "run_path": os.environ.get("RIVET_AGENTOS_RUN_PATH", "/runs"),
        }
        self._gateway = gateway_config()
        self._bindings = ModelGateway(ttl_seconds=int(cast(int, self._gateway["ttl_seconds"])))

    async def runtime_for(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None = None,
        *,
        pinned_policy: bool = False,
        allow_kernel_tools: bool = True,
    ) -> Runtime:
        """Resolve one runtime under either caller-routing or pinned profile policy.

        ``pinned_policy`` is reserved for process-composed permanent profiles.  It
        keeps the authored runtime/model endpoint authoritative while retaining
        every shared safety boundary in this resolver: sensitive-data routing,
        scoped credential resolution, the model gateway, the trusted Codex wall,
        and typed unavailable runtimes.  In particular, a user's AI-key provider
        choice or model-profile hint cannot silently turn an authored permanent
        Codex head into a different runtime. ``allow_kernel_tools`` lets a caller
        retain the same resolver/admission path while explicitly selecting the
        read-only Codex phase; permanent routing/decomposition uses that posture
        because its authored skills govern child selection, not side effects in
        the routing call itself.
        """
        endpoint, api_key, runtime_override, model_route = await self._resolve_runtime_policy(
            tenant_id,
            capability,
            context,
            pinned_policy=pinned_policy,
        )
        self._require_pinned_codex_model(
            capability,
            endpoint,
            pinned_policy=pinned_policy,
        )
        runtime = self._build_resolved_runtime(
            capability,
            endpoint,
            api_key,
            runtime_override,
            allow_kernel_tools=allow_kernel_tools,
        )
        self._attach_model_route(runtime, capability, endpoint, model_route)
        return runtime

    async def _resolve_runtime_policy(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None,
        *,
        pinned_policy: bool,
    ) -> tuple[ModelEndpoint | None, str | None, str | None, dict[str, str] | None]:
        sensitive = bool(context is not None and context.extra.get("data_class") == "sensitive")
        endpoint = await select_model_endpoint(
            self._kernel.store,
            tenant_id,
            capability.model_endpoint,
            sensitive=sensitive,
            sensitive_endpoint_id=self._sensitive_endpoint_id,
            audit=self._kernel.audit,
            actor=capability.name,
        )
        api_key, resolution = await self._resolve_ai_key(tenant_id, context)
        runtime_override: str | None = None
        model_route: dict[str, str] | None = None

        if (
            not pinned_policy
            and resolution is not None
            and not resolution.is_default
            and not sensitive
        ):
            runtime_override = runtime_for_provider(resolution.provider)
            if runtime_override is not None:
                endpoint = _routed_endpoint(tenant_id, endpoint, resolution)

        if context is not None and not sensitive and not pinned_policy:
            profile = select_model_profile(dict(context.extra or {}))
            endpoint, profile_runtime, profile_route = apply_model_profile(
                endpoint, profile, tenant_id=tenant_id
            )
            if profile_runtime is not None:
                runtime_override = profile_runtime
            if profile_route is not None:
                model_route = profile_route.audit_detail()

        conversation_id = context.extra.get("conversation_id") if context is not None else None
        endpoint = apply_gateway(
            endpoint,
            gateway_url=cast(str | None, self._gateway["base_url"]),
            binding=self._bindings,
            conversation_id=conversation_id,
            sensitive=sensitive,
        )
        return endpoint, api_key, runtime_override, model_route

    def _require_pinned_codex_model(
        self,
        capability: AgentCapability,
        endpoint: ModelEndpoint | None,
        *,
        pinned_policy: bool,
    ) -> None:
        if (
            pinned_policy
            and capability.runtime == "codex"
            and self._codex is not None
            and endpoint is not None
        ):
            composed_model = str(self._codex.get("model_id") or "").strip()
            if not composed_model or endpoint.model != composed_model:
                raise PinnedRuntimePolicyUnavailable(
                    "the composed Codex model does not satisfy the pinned profile"
                )

    def _build_resolved_runtime(
        self,
        capability: AgentCapability,
        endpoint: ModelEndpoint | None,
        api_key: str | None,
        runtime_override: str | None,
        *,
        allow_kernel_tools: bool,
    ) -> Runtime:
        def lookup(endpoint_id: str) -> ModelEndpoint | None:
            if endpoint is not None and endpoint.id == endpoint_id:
                return endpoint
            return None

        endpoint_override = endpoint if runtime_override is not None else None
        return build_runtime(
            capability,
            lookup,
            opencode_config=self._opencode_config(capability, runtime_override),
            rivet_config=self._rivet_config(capability, runtime_override),
            codex_config=self._codex_config(
                capability,
                runtime_override,
                allow_kernel_tools=allow_kernel_tools,
            ),
            api_key=api_key,
            runtime_override=runtime_override,
            endpoint_override=endpoint_override,
        )

    def _attach_model_route(
        self,
        runtime: Runtime,
        capability: AgentCapability,
        endpoint: ModelEndpoint | None,
        model_route: dict[str, str] | None,
    ) -> None:
        """Record the model that actually served the call.

        A profile route wins because it carries richer attribution. Otherwise the
        resolved endpoint, or the composed Codex model for an endpoint-free Codex
        profile, makes cost and decision provenance independently checkable.
        """
        if model_route is None:
            model_route = served_model_route(endpoint)
        if (
            model_route is None
            and capability.runtime == "codex"
            and self._codex is not None
            and self._codex.get("model_id")
        ):
            model_route = {"model": str(self._codex["model_id"])}
        if model_route:
            setattr(runtime, "model_route", model_route)

    async def _resolve_ai_key(
        self, tenant_id: str, context: InvocationContext | None
    ) -> tuple[str | None, Any | None]:
        production = production_signal() is not None
        if context is None:
            if production:
                raise CredentialResolution(
                    "production runtime requires an authenticated execution context"
                )
            return None, None
        from boltrig.identity import load_ai_key_material, resolve_ai_key

        try:
            resolution = await resolve_ai_key(
                self._kernel.store,
                tenant_id,
                workspace_id=context.workspace_id,
                user_id=context.on_behalf_of,
            )
            material = await load_ai_key_material(self._kernel.store, tenant_id, resolution)
        except Exception as exc:
            if production:
                raise CredentialResolution(
                    "production AI credential resolution is unavailable"
                ) from exc
            return None, None
        if resolution.credential_ref is not None and not material:
            raise CredentialResolution("configured AI credential material is unavailable")
        if resolution.is_default and production:
            raise CredentialResolution(
                "production AI execution requires a scoped credential reference"
            )
        return material, resolution

    def _rivet_config(
        self, capability: AgentCapability, runtime_override: str | None
    ) -> dict[str, Any] | None:
        if capability.runtime not in {"rivet", "rivet_agentos", "rivet-agentos"} and (
            runtime_override != "rivet_agentos"
        ):
            return None
        return {
            "agentos_url": self._rivet["agentos_url"],
            "mcp_url": self._rivet["mcp_url"],
            "run_path": self._rivet["run_path"],
            "issue_token": self._kernel.mcp.issue_run_token,
            "revoke_token": self._kernel.mcp.revoke,
        }

    def _codex_config(
        self,
        capability: AgentCapability,
        runtime_override: str | None,
        *,
        allow_kernel_tools: bool = True,
    ) -> dict[str, Any] | None:
        """The injected trusted-Codex config, gated ONLY on ``capability.runtime``.

        Codex is a trusted, hard-walled lane ([2026] VJS-CC-VJS 2), NOT a
        provider-routing target: an ai_config ``runtime_override == "codex"`` must
        never select it, so (unlike the opencode/rivet lanes) this never triggers on
        the override. None when the capability is not a codex runtime, or when no
        provider was injected (off by default = no-op -> unavailable lane).

        A capability with ``supported_skills: ['*']`` selects the kernel-tools
        lane (real tool use through the kernel's MCP face); anything narrower
        keeps the read-only analysis lane. The marker carries the SAME
        run-scoped-token + revocation idiom pi/opencode/rivet use
        (``kernel.mcp.issue_run_token``), the kernel MCP endpoint, and the
        tool-ceiling compiler (the kernel MCP tools/list derivation), so the
        adapter needs no store or kernel handle of its own.
        """
        if capability.runtime != "codex":
            return None
        if self._codex is None:
            return None
        cfg = dict(self._codex)
        cfg["kernel_tools"] = (
            allow_kernel_tools and "*" in (capability.supported_skills or [])
        )
        cfg["issue_token"] = self._kernel.mcp.issue_run_token
        cfg["revoke_token"] = self._kernel.mcp.revoke
        cfg["mcp_url"] = (
            os.environ.get("BOLTRIG_CODEX_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or "http://kernel:8000/v1/mcp"
        )
        cfg["compile_tool_ceiling"] = self._compile_codex_tool_ceiling
        return cfg

    async def _compile_codex_tool_ceiling(
        self, tenant_id: str, grants: Any
    ) -> tuple[str, ...]:
        """The run's effective kernel tool set: tenant ceiling ∩ run grants.

        Byte-for-byte the kernel MCP face's ``tools/list`` derivation
        (FR-MCP-02), so the admission-compiled proxy ceiling and the tools the
        kernel will actually advertise to the cell are the same set.
        """
        permissions = await self._kernel.store.get_tenant_permissions(tenant_id)
        verbs = await self._kernel.store.list_verbs(tenant_id)
        return tuple(
            verb.id
            for verb in verbs
            if permissions.grants.permits(verb.id) and grants.permits(verb.id)
        )

    def _opencode_config(
        self, capability: AgentCapability, runtime_override: str | None
    ) -> dict[str, Any] | None:
        if capability.runtime != "opencode" and runtime_override != "opencode":
            return None
        return {
            "mcp_url": os.environ.get("BOLTRIG_OPENCODE_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or None,
            "issue_token": self._kernel.mcp.issue_run_token,
            "revoke_token": self._kernel.mcp.revoke,
        }
