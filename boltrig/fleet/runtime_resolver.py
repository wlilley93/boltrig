"""Resolve model endpoints and build runtimes for ephemeral spawns."""

from __future__ import annotations

import os
from typing import Any, cast

from boltrig.config.environment import production_signal
from boltrig.models import (
    AgentCapability,
    CredentialResolution,
    InvocationContext,
    ModelEndpoint,
)

from .codex_model_selection import (
    codex_model_route,
    resolve_base_model,
    resolve_codex_model,
)
from .model_gateway import ModelGateway, gateway_config
from .runtime import Runtime, build_runtime
from .runtime_endpoint_policy import (
    apply_conversation_gateway,
    apply_legacy_provider_route,
    apply_requested_model_profile,
    served_model_route,
)


class PinnedRuntimePolicyUnavailable(RuntimeError):
    """A composed runtime cannot honestly satisfy an authored pinned profile."""


class RuntimeResolver:
    """Owns runtime routing while leaving spawn orchestration thin."""

    def __init__(
        self,
        kernel: Any,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
        model_catalogue: Any = None,
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        # Trusted read-only Codex provider config, injected from the api composition
        # root ([2026] VJS-CC-VJS 2). None (the default) => the codex runtime is a
        # degrade-marked unavailable lane (off by default = total no-op).
        self._codex = codex_config
        self._model_catalogue = model_catalogue
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
            model_route,
            allow_kernel_tools=allow_kernel_tools,
        )
        self._attach_model_route(runtime, endpoint, model_route)
        return runtime

    async def _resolve_runtime_policy(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None,
        *,
        pinned_policy: bool,
    ) -> tuple[ModelEndpoint | None, str | None, str | None, dict[str, str] | None]:
        sensitive, modality, selected_endpoint_id, capability_endpoint_id, endpoint = (
            await resolve_base_model(
                kernel=self._kernel,
                tenant_id=tenant_id,
                capability=capability,
                context=context,
                pinned_policy=pinned_policy,
                sensitive_endpoint_id=self._sensitive_endpoint_id,
            )
        )
        api_key, resolution = await self._resolve_ai_key(tenant_id, context, modality)
        runtime_override: str | None = None
        model_route: dict[str, str] | None = None
        explicit_endpoint = capability_endpoint_id is not None

        if capability.runtime == "codex" and not sensitive:
            gateway_url = cast(str | None, self._gateway["base_url"])
            endpoint = await resolve_codex_model(
                kernel=self._kernel,
                tenant_id=tenant_id,
                capability=capability,
                endpoint=endpoint,
                choice_id=selected_endpoint_id,
                modality=modality,
                pinned_policy=pinned_policy,
                codex_config=self._codex,
                gateway_url=gateway_url,
                model_catalogue=self._model_catalogue,
            )
            runtime_override = None
        else:
            endpoint, runtime_override = apply_legacy_provider_route(
                tenant_id=tenant_id,
                capability=capability,
                endpoint=endpoint,
                explicit_endpoint=explicit_endpoint,
                resolution=resolution,
                modality=modality,
                pinned_policy=pinned_policy,
                sensitive=sensitive,
            )

        endpoint, runtime_override, profile_route = apply_requested_model_profile(
            tenant_id=tenant_id,
            capability=capability,
            endpoint=endpoint,
            runtime_override=runtime_override,
            context=context,
            pinned_policy=pinned_policy,
            sensitive=sensitive,
        )
        model_route = profile_route or model_route

        conversation_id = context.extra.get("conversation_id") if context is not None else None
        endpoint = apply_conversation_gateway(
            endpoint,
            gateway_url=cast(str | None, self._gateway["base_url"]),
            bindings=self._bindings,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sensitive=sensitive,
            capability=capability,
            choice_id=selected_endpoint_id,
            pinned_policy=pinned_policy,
        )
        if capability.runtime == "codex" and endpoint is not None and not sensitive:
            model_route = codex_model_route(endpoint, selected_endpoint_id)
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
        model_route: dict[str, str] | None,
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
                model_id=(endpoint.model if endpoint is not None else None),
                model_endpoint_id=(
                    model_route.get("choice_id")
                    if model_route is not None
                    else None
                ),
                allow_kernel_tools=allow_kernel_tools,
            ),
            api_key=api_key,
            runtime_override=runtime_override,
            endpoint_override=endpoint_override,
        )

    def _attach_model_route(
        self,
        runtime: Runtime,
        endpoint: ModelEndpoint | None,
        model_route: dict[str, str] | None,
    ) -> None:
        """Record the model that actually served the call.

        A profile route wins because it carries richer attribution. Otherwise the
        resolved endpoint makes cost and decision provenance independently
        checkable. An unavailable runtime gets no speculative model label.
        """
        if model_route is None:
            model_route = served_model_route(endpoint)
        if model_route:
            setattr(runtime, "model_route", model_route)

    async def _resolve_ai_key(
        self, tenant_id: str, context: InvocationContext | None, modality: str = "text"
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
                modality=modality,
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
        model_id: str | None = None,
        model_endpoint_id: str | None = None,
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
        if model_id:
            cfg["model_id"] = model_id
        cfg["model_endpoint_id"] = model_endpoint_id
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
